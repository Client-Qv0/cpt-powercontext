"""Task-scoped context selection over the seekdb index.

The builder answers three questions for one task:

1. which *active* specification sections govern the change;
2. which code symbols are likely to be edited;
3. which tests prove the new behaviour and which ones protect the old one.

Ranking is BM25 over the database term index, then shallow, explicit
traceability boosts (spec mentions, ``applies_to`` paths, ``covers`` tags,
test imports).  Every selected source is verified against the filesystem
before the context is returned.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import Database, QueryTrace, Session
from .errors import DatabaseUnavailable, SpecAnchorError
from .tokens import tokenize

K1 = 1.2
B = 0.75


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except OSError:
        return 0


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    request: str
    project: str
    focus: tuple[str, ...] = ()
    must_preserve: tuple[str, ...] = ()
    focus_specs: tuple[str, ...] = ()
    target_specs: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: Path) -> "Task":
        payload = json.loads(path.read_text(encoding="utf-8"))
        missing = [key for key in ("id", "title", "request", "project") if not str(payload.get(key, "")).strip()]
        if missing:
            raise SpecAnchorError(f"任务文件缺少字段: {', '.join(missing)}")
        return cls(
            id=str(payload["id"]).strip(),
            title=str(payload["title"]).strip(),
            request=str(payload["request"]).strip(),
            project=str(payload["project"]).strip(),
            focus=tuple(str(item) for item in payload.get("focus", [])),
            must_preserve=tuple(str(item) for item in payload.get("must_preserve", [])),
            focus_specs=tuple(str(item) for item in payload.get("focus_specs", [])),
            target_specs=tuple(str(item) for item in payload.get("target_specs", [])),
        )

    def query_text(self) -> str:
        return "\n".join((self.title, self.request, " ".join(self.focus), " ".join(self.must_preserve)))


def build_query_weights(task: Task) -> dict[str, float]:
    weights: dict[str, float] = {}

    def add(text: str, weight: float) -> None:
        for term in tokenize(text):
            weights[term] = max(weights.get(term, 0.0), weight)

    add(task.title, 2.0)
    add(task.request, 3.0)
    add(" ".join(task.focus), 1.5)
    add(" ".join(task.must_preserve), 1.0)
    add(task.project, 0.5)
    return weights


def _bm25(
    session: Session,
    *,
    project: str,
    kind: str,
    table: str,
    weights: dict[str, float],
) -> tuple[dict[int, float], dict[int, set[str]], dict[str, Any]]:
    terms = sorted(weights)
    if not terms:
        return {}, {}, {"terms": 0, "candidates": 0}
    placeholders = ",".join(["%s"] * len(terms))
    postings = session.fetchall(
        f"SELECT ref_id, term, tf FROM sa_terms WHERE project=%s AND kind=%s AND term IN ({placeholders})",
        (project, kind, *terms),
    )
    doc_freq_rows = session.fetchall(
        f"SELECT term, COUNT(DISTINCT ref_id) AS df FROM sa_terms "
        f"WHERE project=%s AND kind=%s AND term IN ({placeholders}) GROUP BY term",
        (project, kind, *terms),
    )
    lengths = session.fetchall(
        f"SELECT id, token_count FROM {table} WHERE project=%s AND active=1", (project,)
    )
    total_docs = len(lengths) or 1
    avg_length = (sum(int(row["token_count"]) for row in lengths) / total_docs) or 1.0
    length_by_id = {int(row["id"]): int(row["token_count"]) or 1 for row in lengths}
    df_by_term = {row["term"]: int(row["df"]) for row in doc_freq_rows}

    scores: dict[int, float] = {}
    matched: dict[int, set[str]] = {}
    for row in postings:
        ref_id = int(row["ref_id"])
        term = row["term"]
        tf = int(row["tf"])
        df = df_by_term.get(term, 1)
        idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
        length = length_by_id.get(ref_id, avg_length)
        denominator = tf + K1 * (1 - B + B * length / avg_length)
        contribution = weights.get(term, 1.0) * idf * (tf * (K1 + 1)) / (denominator or 1)
        scores[ref_id] = scores.get(ref_id, 0.0) + contribution
        matched.setdefault(ref_id, set()).add(term)
    diagnostics = {
        "terms": len(terms),
        "postings": len(postings),
        "candidates": len(lengths),
        "avg_token_count": round(avg_length, 2),
    }
    return scores, matched, diagnostics


def _why(score: float, terms: set[str], weights: dict[str, float], boosts: list[str] | None = None) -> str:
    top = sorted(terms, key=lambda term: (-weights.get(term, 0.0), term))[:4]
    pieces = [f"BM25={score:.3f}"]
    if top:
        pieces.append("命中=" + "/".join(top))
    if boosts:
        pieces.extend(boosts)
    return "; ".join(pieces)


class ContextBuilder:
    def __init__(self, database: Database, project: str, root: Path) -> None:
        self.database = database
        self.project = project
        self.root = root
        self.query_weights = {}

    # -- specifications ---------------------------------------------------
    def specs(self, task: Task, *, limit: int = 6) -> list[dict[str, Any]]:
        with self.database.session() as session:
            scores, matched, diagnostics = _bm25(
                session, project=self.project, kind="spec", table="sa_spec_sections", weights=self.query_weights
            )
            rows = session.fetchall(
                "SELECT id, doc_path, section_key, spec_id, heading, level, line_start, line_end, body, "
                "revision, content_hash, token_count FROM sa_spec_sections "
                "WHERE project=%s AND active=1",
                (self.project,),
            )
        self.spec_diagnostics = diagnostics
        by_id = {int(row["id"]): row for row in rows}
        lowered = task.query_text().casefold()
        boosted: dict[int, float] = {}
        reasons: dict[int, list[str]] = {}
        for ref_id, row in by_id.items():
            score = scores.get(ref_id, 0.0)
            extra: list[str] = []
            if row["spec_id"].casefold() in lowered:
                score += 5.0
                extra.append("任务显式引用规格")
            if row["spec_id"] in task.focus_specs:
                score += 8.0
                extra.append("focus_specs")
            heading_terms = set(tokenize(row["heading"]))
            overlap = heading_terms & set(self.query_weights)
            if overlap:
                score += 0.8 * len(overlap)
                extra.append("标题命中=" + "/".join(sorted(overlap)))
            boosted[ref_id] = score
            reasons[ref_id] = extra

        ranked = sorted(boosted.items(), key=lambda item: (-item[1], by_id[item[0]]["spec_id"]))
        selected_rows: dict[int, float] = {}
        target_rows: dict[int, str] = {}
        by_spec_id = {row["spec_id"]: row for row in rows}
        for spec_id in task.target_specs:
            row = by_spec_id.get(spec_id)
            if row is not None:
                ref_id = int(row["id"])
                selected_rows[ref_id] = boosted.get(ref_id, 0.0)
                target_rows[ref_id] = "任务声明的目标规格"
        for ref_id, score in ranked:
            if len(selected_rows) >= limit + len(target_rows):
                break
            if score <= 0:
                continue
            selected_rows.setdefault(ref_id, score)

        ordered = sorted(
            selected_rows.items(),
            key=lambda item: (0 if item[0] in target_rows else 1, -item[1], by_id[item[0]]["spec_id"]),
        )
        selected: list[dict[str, Any]] = []
        for ref_id, score in ordered:
            row = by_id[ref_id]
            extra_reasons = list(reasons.get(ref_id, []))
            if ref_id in target_rows:
                extra_reasons.insert(0, target_rows[ref_id])
            selected.append(
                {
                    "spec_id": row["spec_id"],
                    "section_key": row["section_key"],
                    "path": row["doc_path"],
                    "heading": row["heading"],
                    "line_start": int(row["line_start"]),
                    "line_end": int(row["line_end"]),
                    "revision": int(row["revision"]),
                    "content_hash": row["content_hash"],
                    "score": round(score, 4),
                    "why": _why(score, matched.get(ref_id, set()), self.query_weights, extra_reasons),
                    "text": row["body"],
                }
            )
        return selected

    # -- code -------------------------------------------------------------
    def code(self, task: Task, specs: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
        doc_paths = sorted({spec["path"] for spec in specs})
        with self.database.session() as session:
            scores, matched, diagnostics = _bm25(
                session, project=self.project, kind="code", table="sa_code_symbols", weights=self.query_weights
            )
            targets: set[str] = set()
            if doc_paths:
                placeholders = ",".join(["%s"] * len(doc_paths))
                target_rows = session.fetchall(
                    f"SELECT target_path FROM sa_spec_targets WHERE project=%s AND doc_path IN ({placeholders})",
                    (self.project, *doc_paths),
                )
                targets = {row["target_path"] for row in target_rows}
            rows = session.fetchall(
                "SELECT id, path, module, qualname, kind, signature, lineno, end_lineno, source, docstring, "
                "revision, content_hash FROM sa_code_symbols WHERE project=%s AND active=1",
                (self.project,),
            )
        self.code_diagnostics = diagnostics
        lowered = task.query_text().casefold()
        by_id = {int(row["id"]): row for row in rows}
        boosted: dict[int, float] = {}
        reasons: dict[int, list[str]] = {}
        for ref_id, row in by_id.items():
            score = scores.get(ref_id, 0.0)
            extra: list[str] = []
            short_name = str(row["qualname"]).split(".")[-1]
            named = bool(short_name) and short_name.casefold() in lowered
            if targets and row["path"] not in targets and not named:
                # Keep the edit surface tight: unrelated modules (reports, seed
                # data) are not candidates for this task.
                continue
            if named:
                score += 6.0
                extra.append("任务点名符号")
            if row["path"] in targets:
                score += 3.0
                extra.append("规格 applies_to")
            if row["kind"] == "module":
                score *= 0.6
            boosted[ref_id] = score
            reasons[ref_id] = extra
        ranked = sorted(boosted.items(), key=lambda item: (-item[1], by_id[item[0]]["qualname"]))[:limit]
        selected: list[dict[str, Any]] = []
        for ref_id, score in ranked:
            row = by_id[ref_id]
            if score <= 0:
                continue
            selected.append(
                {
                    "path": row["path"],
                    "qualname": row["qualname"],
                    "kind": row["kind"],
                    "signature": row["signature"],
                    "line_start": int(row["lineno"]),
                    "line_end": int(row["end_lineno"]),
                    "revision": int(row["revision"]),
                    "content_hash": row["content_hash"],
                    "score": round(score, 4),
                    "why": _why(score, matched.get(ref_id, set()), self.query_weights, reasons[ref_id]),
                    "docstring": row["docstring"] or "",
                    "source": row["source"],
                }
            )
        return selected

    # -- tests ------------------------------------------------------------
    def tests(self, task: Task, specs: list[dict[str, Any]], code: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        target_spec_ids = set(task.target_specs) or ({specs[0]["spec_id"]} if specs else set())
        strong_code = [
            symbol
            for symbol in code
            if "规格 applies_to" in symbol["why"] or "任务点名符号" in symbol["why"]
        ] or code[:2]
        affected_modules = {
            self._module_from_path(symbol["path"]) for symbol in strong_code if symbol["kind"] != "module"
        }
        affected_modules = {module for module in affected_modules if module}
        with self.database.session() as session:
            rows = session.fetchall(
                "SELECT id, path, test_id, qualname, kind, lineno, end_lineno, source, docstring, covers, imports, "
                "revision, content_hash FROM sa_tests WHERE project=%s AND active=1",
                (self.project,),
            )
        target: list[dict[str, Any]] = []
        regression: list[dict[str, Any]] = []
        for row in rows:
            covers = set(json.loads(row["covers"] or "[]"))
            imports = set(json.loads(row["imports"] or "[]"))
            entry = {
                "path": row["path"],
                "test_id": row["test_id"],
                "kind": row["kind"],
                "line_start": int(row["lineno"]),
                "line_end": int(row["end_lineno"]),
                "covers": sorted(covers),
                "revision": int(row["revision"]),
                "content_hash": row["content_hash"],
                "source": row["source"],
            }
            if covers & target_spec_ids:
                entry["why"] = "覆盖目标规格 " + ", ".join(sorted(covers & target_spec_ids))
                target.append(entry)
                continue
            related = sorted(
                imported
                for imported in imports
                if any(
                    imported == module or imported.startswith(module + ".") or module.startswith(imported + ".")
                    for module in affected_modules
                )
            )
            if related:
                entry["why"] = "导入受影响模块 " + ", ".join(related)
                regression.append(entry)

        target.sort(key=lambda item: (item["path"], item["test_id"]))
        regression.sort(key=lambda item: (item["path"], item["test_id"]))
        # Keep regression focused on the modules the change touches, but never
        # drop the contract tests that import through the package root.
        return {"target": target, "regression": regression}

    def _module_from_path(self, path: str) -> str:
        relative = path.replace("\\", "/")
        if relative.startswith("src/"):
            relative = relative[4:]
        if relative.endswith(".py"):
            relative = relative[:-3]
        return relative.replace("/", ".")

    # -- assembly ---------------------------------------------------------
    def build(self, task: Task, state: dict[str, Any], *, spec_limit: int = 6, code_limit: int = 8) -> dict[str, Any]:
        self.database.trace.entries.clear()
        self.query_weights = build_query_weights(task)
        specs = self.specs(task, limit=spec_limit)
        code = self.code(task, specs, limit=code_limit)
        tests = self.tests(task, specs, code)
        self._verify_sources(specs, code, tests)

        inventory: dict[str, dict[str, Any]] = {}
        for relative in [spec["path"] for spec in specs] + [symbol["path"] for symbol in code] + [
            test["path"] for group in tests.values() for test in group
        ]:
            path = self.root / relative
            inventory[relative] = {
                "path": relative,
                "exists": path.is_file(),
                "sha256": _sha256_file(path) if path.is_file() else None,
                "lines": _line_count(path) if path.is_file() else 0,
            }

        context = {
            "schema": "specanchor.context.v1",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "task": {
                "id": task.id,
                "title": task.title,
                "project": task.project,
                "request": task.request,
                "must_preserve": list(task.must_preserve),
            },
            "project": {"name": task.project, "root": str(self.root)},
            "specs": specs,
            "code": code,
            "tests": tests,
            "state": state,
            "sources": list(inventory.values()),
            "diagnostics": {
                "query_terms": dict(sorted(self.query_weights.items())),
                "spec_search": getattr(self, "spec_diagnostics", {}),
                "code_search": getattr(self, "code_diagnostics", {}),
                "db": {
                    "engine": "seekdb/OceanBase (MySQL protocol)",
                    "database": self.database.settings.db_name,
                    "queries": self.database.trace.as_list(),
                },
            },
        }
        context["context_digest"] = hashlib.sha256(
            json.dumps(
                {
                    "specs": [(item["spec_id"], item["content_hash"]) for item in specs],
                    "code": [(item["path"], item["qualname"], item["content_hash"]) for item in code],
                    "tests": {kind: [(item["path"], item["test_id"], item["content_hash"]) for item in group] for kind, group in tests.items()},
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return context

    def _verify_sources(self, specs: list[dict[str, Any]], code: list[dict[str, Any]], tests: dict[str, list[dict[str, Any]]]) -> None:
        for item in specs:
            path = self.root / item["path"]
            if not path.is_file():
                raise SpecAnchorError(f"规格来源不存在: {item['path']}")
            if item["line_end"] > _line_count(path):
                raise SpecAnchorError(f"规格行号越界: {item['path']}#{item['spec_id']}")
        for item in code:
            path = self.root / item["path"]
            if not path.is_file():
                raise SpecAnchorError(f"代码来源不存在: {item['path']}")
        for group in tests.values():
            for item in group:
                if not (self.root / item["path"]).is_file():
                    raise SpecAnchorError(f"测试来源不存在: {item['path']}")


def render_markdown(context: dict[str, Any]) -> str:
    task = context["task"]
    lines: list[str] = []
    lines.append(f"# 开发上下文 · {task['id']}")
    lines.append("")
    lines.append(f"**任务**：{task['title']}")
    lines.append("")
    lines.append("## 适用规格")
    for spec in context["specs"]:
        lines.append(
            f"- `{spec['spec_id']}` ({spec['path']}:{spec['line_start']}-{spec['line_end']}, rev {spec['revision']}) "
            f"— {spec['why']}"
        )
    lines.append("")
    lines.append("## 需要修改的代码")
    for symbol in context["code"]:
        lines.append(
            f"- `{symbol['qualname']}` ({symbol['path']}:{symbol['line_start']}-{symbol['line_end']}) "
            f"— {symbol['why']}"
        )
    lines.append("")
    lines.append("## 目标测试")
    for test in context["tests"]["target"]:
        lines.append(f"- `{test['path']}::{test['test_id']}` — {test['why']}")
    lines.append("")
    lines.append("## 回归测试")
    for test in context["tests"]["regression"]:
        lines.append(f"- `{test['path']}::{test['test_id']}` — {test['why']}")
    lines.append("")
    lines.append("## 任务状态（PowerContext）")
    state = context["state"]
    lines.append(f"- scope: `{state.get('scope_id', '-')}`")
    for item in state.get("done", []):
        lines.append(f"- 已完成：{item}")
    for item in state.get("todo", []):
        lines.append(f"- 待办：{item}")
    for item in state.get("verification", []):
        lines.append(f"- 验证：{item['name']} → {item['status']} {item.get('details', '')}")
    lines.append("")
    lines.append("## 数据来源")
    db = context["diagnostics"]["db"]
    lines.append(f"- {db['engine']} / `{db['database']}`，本次构建执行 {len(db['queries'])} 条查询")
    lines.append(f"- 上下文摘要 `{context['context_digest'][:16]}…`")
    return "\n".join(lines)
