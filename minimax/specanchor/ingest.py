"""Import engineering materials into seekdb and build the retrieval index.

Imported material:

* Markdown specifications -> one row per ``## [SPEC-ID]`` section, revisioned.
* Python source -> one row per module/class/function/method (AST parsed).
* pytest files -> one row per test function with its ``covers`` annotations
  and module imports, which later drive target/regression selection.

Every import rebuilds the term index for the project, so a specification edit
is immediately visible to retrieval and the old revision is kept for audit.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import SpecAnchorError
from .db import Database, Session
from .tokens import term_frequencies, tokenize

SPEC_ID_RE = re.compile(r"\[([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+)\]")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
COVERS_RE = re.compile(r"(?:covers|覆盖)\s*[:：]?\s*([A-Za-z0-9,，、/\-\s]+)", re.IGNORECASE)
COVERS_ID_RE = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\d+")

MAX_CODE_CHARS = 12_000


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _as_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


# ---------------------------------------------------------------------------
# Markdown specifications
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpecDocMeta:
    doc_path: str
    spec_name: str
    version: str
    status: str
    applies_to: tuple[str, ...]
    content_hash: str


@dataclass(frozen=True)
class SpecSection:
    doc_path: str
    section_key: str
    spec_id: str
    heading: str
    level: int
    line_start: int
    line_end: int
    body: str
    content_hash: str

    @property
    def tokens(self) -> list[str]:
        return tokenize(self.heading + "\n" + self.body)


def _parse_frontmatter(lines: list[str]) -> tuple[dict[str, Any], int]:
    if not lines or lines[0].strip() != "---":
        return {}, 0
    meta: dict[str, Any] = {}
    current_key: str | None = None
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            return meta, index + 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            meta.setdefault(current_key, []).append(stripped[2:].strip())
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                meta[key] = value
                current_key = None
            else:
                current_key = key
                meta.setdefault(key, [])
    return meta, 0


def _slug(text: str) -> str:
    cleaned = re.sub(r"\[[^\]]+\]", "", text)
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", cleaned).strip("-").lower()
    return cleaned or "section"


def parse_specs(root: Path) -> tuple[list[SpecDocMeta], list[SpecSection]]:
    specs_root = root / "specs"
    docs: list[SpecDocMeta] = []
    sections: list[SpecSection] = []
    if not specs_root.is_dir():
        return docs, sections

    for path in sorted(specs_root.rglob("*.md")):
        rel = _as_posix(path, root)
        lines = path.read_text(encoding="utf-8").splitlines()
        meta, start = _parse_frontmatter(lines)
        body_lines = lines[start:]
        spec_name = str(meta.get("spec") or path.stem)
        applies_to = tuple(str(item) for item in meta.get("applies_to", []) if str(item).strip())
        docs.append(
            SpecDocMeta(
                doc_path=rel,
                spec_name=spec_name,
                version=str(meta.get("version", "")),
                status=str(meta.get("status", "")),
                applies_to=applies_to,
                content_hash=sha256_text("\n".join(lines)),
            )
        )

        headings: list[tuple[int, int, str]] = []
        for offset, line in enumerate(body_lines):
            match = HEADING_RE.match(line)
            if match:
                headings.append((len(match.group(1)), start + offset, match.group(2)))

        used_keys: Counter[str] = Counter()
        for position, (level, line_index, heading) in enumerate(headings):
            if level < 2:
                continue
            end_line = len(lines)
            for next_level, next_index, _next_heading in headings[position + 1 :]:
                if next_level <= level:
                    end_line = next_index
                    break
            match = SPEC_ID_RE.search(heading)
            if not match:
                # A heading without an ID belongs to its parent section's body.
                continue
            spec_id = match.group(1)
            used_keys[spec_id] += 1
            section_key = spec_id if used_keys[spec_id] == 1 else f"{spec_id}#{used_keys[spec_id]}"
            body = "\n".join(lines[line_index:end_line]).rstrip()
            sections.append(
                SpecSection(
                    doc_path=rel,
                    section_key=section_key,
                    spec_id=spec_id,
                    heading=heading,
                    level=level,
                    line_start=line_index + 1,
                    line_end=end_line,
                    body=body,
                    content_hash=sha256_text(heading + "\n" + body),
                )
            )
    return docs, sections


# ---------------------------------------------------------------------------
# Python code and tests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodeSymbol:
    path: str
    module: str
    qualname: str
    kind: str
    signature: str
    lineno: int
    end_lineno: int
    source: str
    docstring: str
    content_hash: str

    @property
    def tokens(self) -> list[str]:
        return tokenize("\n".join((self.qualname, self.signature, self.docstring, self.source)))


@dataclass(frozen=True)
class TestRecord:
    path: str
    test_id: str
    qualname: str
    kind: str
    lineno: int
    end_lineno: int
    source: str
    docstring: str
    covers: tuple[str, ...]
    imports: tuple[str, ...]
    content_hash: str

    @property
    def tokens(self) -> list[str]:
        return tokenize("\n".join((self.test_id, self.docstring, self.source)))


def _module_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    parts = list(relative.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    rendered = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"{prefix}{node.name}({rendered}){returns}"


def _parse_code_file(path: Path, root: Path) -> list[CodeSymbol]:
    rel = _as_posix(path, root)
    source_text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return []
    module = _module_name(path, root)
    symbols: list[CodeSymbol] = [
        CodeSymbol(
            path=rel,
            module=module,
            qualname=module,
            kind="module",
            signature=f"module {module}",
            lineno=1,
            end_lineno=len(source_text.splitlines()),
            source=(ast.get_docstring(tree) or "")[:MAX_CODE_CHARS],
            docstring=ast.get_docstring(tree) or "",
            content_hash=sha256_text(ast.get_docstring(tree) or module),
        )
    ]

    def visit(node: ast.AST, prefix: str) -> None:
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                segment = ast.get_source_segment(source_text, child) or ""
                qualname = f"{prefix}{child.name}"
                symbols.append(
                    CodeSymbol(
                        path=rel,
                        module=module,
                        qualname=qualname,
                        kind="function" if isinstance(node, ast.Module) else "method",
                        signature=_signature(child),
                        lineno=child.lineno,
                        end_lineno=child.end_lineno or child.lineno,
                        source=segment[:MAX_CODE_CHARS],
                        docstring=ast.get_docstring(child) or "",
                        content_hash=sha256_text(segment),
                    )
                )
            elif isinstance(child, ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                header = f"class {child.name}"
                doc = ast.get_docstring(child) or ""
                segment = f"{header}\n{doc}"[:MAX_CODE_CHARS]
                symbols.append(
                    CodeSymbol(
                        path=rel,
                        module=module,
                        qualname=qualname,
                        kind="class",
                        signature=header,
                        lineno=child.lineno,
                        end_lineno=child.end_lineno or child.lineno,
                        source=segment,
                        docstring=doc,
                        content_hash=sha256_text(segment),
                    )
                )
                visit(child, f"{qualname}.")

    visit(tree, "")
    return symbols


def parse_code(root: Path) -> list[CodeSymbol]:
    src_root = root / "src"
    if not src_root.is_dir():
        return []
    symbols: list[CodeSymbol] = []
    for path in sorted(src_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        symbols.extend(_parse_code_file(path, root))
    return symbols


def _module_imports(tree: ast.Module) -> tuple[str, ...]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return tuple(dict.fromkeys(modules))


def _covers(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in COVERS_RE.finditer(text):
        found.extend(COVERS_ID_RE.findall(match.group(1)))
    # Also accept a plain ``[BOOK-004]`` reference in the docstring.
    found.extend(SPEC_ID_RE.findall(text))
    return tuple(dict.fromkeys(item.strip() for item in found if item.strip()))


def parse_tests(root: Path) -> list[TestRecord]:
    tests_root = root / "tests"
    if not tests_root.is_dir():
        return []
    records: list[TestRecord] = []
    for path in sorted(tests_root.rglob("test_*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = _as_posix(path, root)
        source_text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source_text)
        except SyntaxError:
            continue
        imports = _module_imports(tree)

        def visit(node: ast.AST, prefix: str) -> None:
            for child in getattr(node, "body", []):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                    segment = ast.get_source_segment(source_text, child) or ""
                    doc = ast.get_docstring(child) or ""
                    header = "\n".join(segment.splitlines()[:12])
                    records.append(
                        TestRecord(
                            path=rel,
                            test_id=f"{prefix}{child.name}",
                            qualname=f"{prefix}{child.name}",
                            kind="function" if isinstance(node, ast.Module) else "method",
                            lineno=child.lineno,
                            end_lineno=child.end_lineno or child.lineno,
                            source=segment,
                            docstring=doc,
                            covers=_covers(doc + "\n" + header),
                            imports=imports,
                            content_hash=sha256_text(segment),
                        )
                    )
                elif isinstance(child, ast.ClassDef) and child.name.startswith("Test"):
                    visit(child, f"{prefix}{child.name}.")

        visit(tree, "")
    return records


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@dataclass
class ImportResult:
    project: str
    root: str
    specs: int = 0
    code: int = 0
    tests: int = 0
    changed_sections: list[dict[str, Any]] = field(default_factory=list)
    terms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "root": self.root,
            "spec_sections": self.specs,
            "code_symbols": self.code,
            "tests": self.tests,
            "terms": self.terms,
            "changed_sections": self.changed_sections,
        }


def _sync_specs(session: Session, project: str, root: Path, docs: list[SpecDocMeta], sections: list[SpecSection], result: ImportResult) -> None:
    now = _now()
    active_docs = session.fetchall(
        "SELECT id, doc_path, content_hash FROM sa_spec_docs WHERE project=%s AND active=1", (project,)
    )
    doc_by_path = {row["doc_path"]: row for row in active_docs}
    current_paths = {doc.doc_path for doc in docs}
    for doc in docs:
        previous = doc_by_path.get(doc.doc_path)
        if previous is not None and previous["content_hash"] == doc.content_hash:
            session.execute("UPDATE sa_spec_docs SET imported_at=%s WHERE id=%s", (now, previous["id"]))
            continue
        if previous is not None:
            session.execute("UPDATE sa_spec_docs SET active=0 WHERE id=%s", (previous["id"],))
        session.execute(
            "INSERT INTO sa_spec_docs "
            "(project, doc_path, spec_name, version, status, applies_to, content_hash, active, imported_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s) "
            "ON DUPLICATE KEY UPDATE active=1, imported_at=VALUES(imported_at), "
            "spec_name=VALUES(spec_name), version=VALUES(version), status=VALUES(status), "
            "applies_to=VALUES(applies_to)",
            (
                project,
                doc.doc_path,
                doc.spec_name,
                doc.version,
                doc.status,
                json.dumps(list(doc.applies_to), ensure_ascii=False),
                doc.content_hash,
                now,
            ),
        )
    for doc_path, row in doc_by_path.items():
        if doc_path not in current_paths:
            session.execute("UPDATE sa_spec_docs SET active=0 WHERE id=%s", (row["id"],))

    active_sections = session.fetchall(
        "SELECT id, doc_path, section_key, spec_id, content_hash, revision FROM sa_spec_sections "
        "WHERE project=%s AND active=1",
        (project,),
    )
    max_rows = session.fetchall(
        "SELECT doc_path, section_key, MAX(revision) AS max_revision FROM sa_spec_sections "
        "WHERE project=%s GROUP BY doc_path, section_key",
        (project,),
    )
    max_by_key = {(row["doc_path"], row["section_key"]): int(row["max_revision"]) for row in max_rows}
    by_key = {(row["doc_path"], row["section_key"]): row for row in active_sections}
    current_keys = {(section.doc_path, section.section_key) for section in sections}
    for section in sections:
        previous = by_key.get((section.doc_path, section.section_key))
        tokens = section.tokens
        if previous is not None and previous["content_hash"] == section.content_hash:
            session.execute(
                "UPDATE sa_spec_sections SET line_start=%s, line_end=%s, token_count=%s, imported_at=%s WHERE id=%s",
                (section.line_start, section.line_end, len(tokens), now, previous["id"]),
            )
            continue
        revision = int(max_by_key.get((section.doc_path, section.section_key), 0)) + 1
        if previous is not None:
            revision = int(previous["revision"]) + 1
            session.execute("UPDATE sa_spec_sections SET active=0 WHERE id=%s", (previous["id"],))
            session.execute(
                "INSERT INTO sa_spec_changes "
                "(project, doc_path, section_key, spec_id, old_hash, new_hash, old_revision, new_revision, changed_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    project,
                    section.doc_path,
                    section.section_key,
                    section.spec_id,
                    previous["content_hash"],
                    section.content_hash,
                    previous["revision"],
                    revision,
                    now,
                ),
            )
            result.changed_sections.append(
                {
                    "spec_id": section.spec_id,
                    "doc_path": section.doc_path,
                    "section_key": section.section_key,
                    "old_revision": previous["revision"],
                    "new_revision": revision,
                    "old_hash": previous["content_hash"],
                    "new_hash": section.content_hash,
                }
            )
        session.execute(
            "INSERT INTO sa_spec_sections "
            "(project, doc_path, section_key, spec_id, heading, level, line_start, line_end, body, "
            " revision, content_hash, token_count, active, imported_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
            (
                project,
                section.doc_path,
                section.section_key,
                section.spec_id,
                section.heading,
                section.level,
                section.line_start,
                section.line_end,
                section.body,
                revision,
                section.content_hash,
                len(tokens),
                now,
            ),
        )
    for key, row in by_key.items():
        if key not in current_keys:
            session.execute("UPDATE sa_spec_sections SET active=0 WHERE id=%s", (row["id"],))
    result.specs = len(sections)


def _sync_code(session: Session, project: str, symbols: list[CodeSymbol], result: ImportResult) -> None:
    now = _now()
    active = session.fetchall(
        "SELECT id, path, qualname, content_hash, revision FROM sa_code_symbols WHERE project=%s AND active=1",
        (project,),
    )
    max_rows = session.fetchall(
        "SELECT path, qualname, MAX(revision) AS max_revision FROM sa_code_symbols "
        "WHERE project=%s GROUP BY path, qualname",
        (project,),
    )
    max_by_key = {(row["path"], row["qualname"]): int(row["max_revision"]) for row in max_rows}
    by_key = {(row["path"], row["qualname"]): row for row in active}
    current = {(symbol.path, symbol.qualname): symbol for symbol in symbols}
    for key, symbol in current.items():
        previous = by_key.get(key)
        tokens = symbol.tokens
        if previous is not None and previous["content_hash"] == symbol.content_hash:
            session.execute(
                "UPDATE sa_code_symbols SET lineno=%s, end_lineno=%s, token_count=%s, imported_at=%s WHERE id=%s",
                (symbol.lineno, symbol.end_lineno, len(tokens), now, previous["id"]),
            )
            continue
        revision = int(max_by_key.get(key, 0)) + 1
        if previous is not None:
            session.execute("UPDATE sa_code_symbols SET active=0 WHERE id=%s", (previous["id"],))
        session.execute(
            "INSERT INTO sa_code_symbols "
            "(project, path, module, qualname, kind, signature, lineno, end_lineno, source, docstring, "
            " revision, content_hash, token_count, active, imported_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
            (
                project,
                symbol.path,
                symbol.module,
                symbol.qualname,
                symbol.kind,
                symbol.signature,
                symbol.lineno,
                symbol.end_lineno,
                symbol.source,
                symbol.docstring,
                revision,
                symbol.content_hash,
                len(tokens),
                now,
            ),
        )
    for key, row in by_key.items():
        if key not in current:
            session.execute("UPDATE sa_code_symbols SET active=0 WHERE id=%s", (row["id"],))
    result.code = len(symbols)


def _sync_tests(session: Session, project: str, tests: list[TestRecord], result: ImportResult) -> None:
    now = _now()
    active = session.fetchall(
        "SELECT id, path, test_id, content_hash, revision FROM sa_tests WHERE project=%s AND active=1",
        (project,),
    )
    max_rows = session.fetchall(
        "SELECT path, test_id, MAX(revision) AS max_revision FROM sa_tests "
        "WHERE project=%s GROUP BY path, test_id",
        (project,),
    )
    max_by_key = {(row["path"], row["test_id"]): int(row["max_revision"]) for row in max_rows}
    by_key = {(row["path"], row["test_id"]): row for row in active}
    current = {(record.path, record.test_id): record for record in tests}
    for key, record in current.items():
        previous = by_key.get(key)
        tokens = record.tokens
        if previous is not None and previous["content_hash"] == record.content_hash:
            session.execute(
                "UPDATE sa_tests SET lineno=%s, end_lineno=%s, token_count=%s, imported_at=%s WHERE id=%s",
                (record.lineno, record.end_lineno, len(tokens), now, previous["id"]),
            )
            continue
        revision = int(max_by_key.get(key, 0)) + 1
        if previous is not None:
            session.execute("UPDATE sa_tests SET active=0 WHERE id=%s", (previous["id"],))
        session.execute(
            "INSERT INTO sa_tests "
            "(project, path, test_id, qualname, kind, lineno, end_lineno, source, docstring, covers, imports, "
            " revision, content_hash, token_count, active, imported_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
            (
                project,
                record.path,
                record.test_id,
                record.qualname,
                record.kind,
                record.lineno,
                record.end_lineno,
                record.source,
                record.docstring,
                json.dumps(list(record.covers), ensure_ascii=False),
                json.dumps(list(record.imports), ensure_ascii=False),
                revision,
                record.content_hash,
                len(tokens),
                now,
            ),
        )
    for key, row in by_key.items():
        if key not in current:
            session.execute("UPDATE sa_tests SET active=0 WHERE id=%s", (row["id"],))
    result.tests = len(tests)


def _rebuild_terms(session: Session, project: str) -> int:
    total = 0
    plan = (
        ("spec", "SELECT id, heading, body FROM sa_spec_sections WHERE project=%s AND active=1"),
        ("code", "SELECT id, qualname, signature, docstring, source FROM sa_code_symbols WHERE project=%s AND active=1"),
        ("test", "SELECT id, test_id, docstring, source FROM sa_tests WHERE project=%s AND active=1"),
    )
    for kind, sql in plan:
        session.execute("DELETE FROM sa_terms WHERE project=%s AND kind=%s", (project, kind))
        rows = session.fetchall(sql, (project,))
        for row in rows:
            if kind == "spec":
                text = f"{row['heading']}\n{row['body']}"
            elif kind == "code":
                text = "\n".join(
                    str(value or "") for value in (row["qualname"], row["signature"], row["docstring"], row["source"])
                )
            else:
                text = "\n".join(str(value or "") for value in (row["test_id"], row["docstring"], row["source"]))
            frequencies = term_frequencies(tokenize(text))
            if frequencies:
                session.executemany(
                    "INSERT INTO sa_terms (project, kind, ref_id, term, tf) VALUES (%s,%s,%s,%s,%s)",
                    [(project, kind, row["id"], term[:96], count) for term, count in frequencies.items()],
                )
                total += len(frequencies)
    return total


def _rebuild_links(session: Session, project: str, docs: list[SpecDocMeta], tests: list[TestRecord]) -> None:
    session.execute("DELETE FROM sa_spec_targets WHERE project=%s", (project,))
    rows: list[tuple[Any, ...]] = []
    for doc in docs:
        for target in doc.applies_to:
            rows.append((project, doc.doc_path, target.strip()))
    if rows:
        session.executemany("INSERT INTO sa_spec_targets (project, doc_path, target_path) VALUES (%s,%s,%s)", rows)

    session.execute("DELETE FROM sa_test_imports WHERE project=%s", (project,))
    imports: set[tuple[str, str, str]] = set()
    for record in tests:
        for module in record.imports:
            imports.add((project, record.path, module))
    if imports:
        session.executemany(
            "INSERT INTO sa_test_imports (project, test_path, module) VALUES (%s,%s,%s)", sorted(imports)
        )


_PROJECT_TABLES = (
    "sa_source_files",
    "sa_spec_sections",
    "sa_spec_docs",
    "sa_spec_changes",
    "sa_code_symbols",
    "sa_tests",
    "sa_terms",
    "sa_spec_targets",
    "sa_test_imports",
    "sa_import_runs",
    "sa_agent_runs",
)


def clear_project(session: Session, project: str) -> None:
    """Delete one project's index generation (used by reset/demo flows)."""

    for table in _PROJECT_TABLES:
        session.execute(f"DELETE FROM {table} WHERE project=%s", (project,))


def source_manifest(root: Path) -> dict[str, str]:
    """Fingerprint all material inputs, including fixtures and module-level data."""
    result = {}
    for directory, pattern in (("specs", "*.md"), ("src", "*.py"), ("tests", "*.py")):
        for path in sorted((root / directory).rglob(pattern)):
            if "__pycache__" not in path.parts:
                resolved = path.resolve()
                if not resolved.is_relative_to(root.resolve()):
                    raise SpecAnchorError(f"来源路径越界: {path}")
                result[path.relative_to(root).as_posix()] = sha256_text(path.read_text(encoding="utf-8"))
    return result


def import_project(database: Database, project: str, root: Path, *, reset: bool = False) -> ImportResult:
    """Parse ``root`` and replace the active index generation for ``project``."""

    result = ImportResult(project=project, root=str(root))
    manifest = source_manifest(root)
    docs, sections = parse_specs(root)
    symbols = parse_code(root)
    tests = parse_tests(root)
    if source_manifest(root) != manifest:
        raise SpecAnchorError("导入时来源发生变化，请重试 ingest")

    with database.session() as session:
        if reset:
            clear_project(session, project)
        session.execute(
            "INSERT INTO sa_import_runs (project, root_path, started_at, status) VALUES (%s,%s,%s,%s)",
            (project, str(root), _now(), "running"),
        )
        run_id = session.fetchone("SELECT LAST_INSERT_ID() AS id")["id"]
        session.execute(
            "INSERT INTO sa_projects (project, root_path, updated_at) VALUES (%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE root_path=VALUES(root_path), updated_at=VALUES(updated_at)",
            (project, str(root), _now()),
        )
        session.execute("DELETE FROM sa_source_files WHERE project=%s", (project,))
        if manifest:
            session.executemany(
                "INSERT INTO sa_source_files (project, path, content_hash) VALUES (%s,%s,%s)",
                [(project, path, digest) for path, digest in manifest.items()],
            )
        _sync_specs(session, project, root, docs, sections, result)
        _sync_code(session, project, symbols, result)
        _sync_tests(session, project, tests, result)
        if source_manifest(root) != manifest:
            raise SpecAnchorError("导入时来源发生变化，请重试 ingest")
        result.terms = _rebuild_terms(session, project)
        _rebuild_links(session, project, docs, tests)
        session.execute(
            "UPDATE sa_import_runs SET finished_at=%s, status=%s, spec_count=%s, code_count=%s, "
            "test_count=%s WHERE id=%s",
            (_now(), "succeeded", result.specs, result.code, result.tests, run_id),
        )
    return result
