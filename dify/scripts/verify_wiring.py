#!/usr/bin/env python3
"""本地接线自检：按 DSL 里的节点顺序，直接执行 code / http-request / if-else / answer 节点。

用途只有一个：在没有 Dify、也没有模型额度的机器上，确认
1) DSL 里的每个 Code 节点都能跑通；
2) 四个 PowerContext HTTP 节点真实可调用（会打印真实请求与响应）；
3) 卷宗 → 提示词 → 归档 → 下一次开庭复用的闭环成立。

它不是 Dify：LLM 节点在 `--llm-base-url` 缺省时使用离线桩。
正式体验请按 README 导入 DSL，在 Dify 里运行。

依赖：Python 3.10+、pyyaml。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

TEMPLATE = re.compile(r"\{\{#([A-Za-z0-9_.\-]+)#\}\}")


class ReplayError(RuntimeError):
    pass


def load_dsl(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "workflow" not in data:
        raise ReplayError("DSL 缺少 workflow 段")
    return data


def render(template: str, scope: dict) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in scope:
            raise ReplayError("模板变量未定义：" + key)
        value = scope[key]
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return TEMPLATE.sub(replace, template)


def resolve(selector: list, scope: dict) -> Any:
    key = ".".join(str(part) for part in selector)
    if key not in scope:
        raise ReplayError("变量未定义：" + key)
    return scope[key]


def coerce(value: Any, kind: str) -> Any:
    if kind == "number":
        return float(value)
    if kind == "string":
        return "" if value is None else str(value)
    if kind == "object":
        return value if isinstance(value, dict) else json.loads(value)
    if kind == "array":
        return value if isinstance(value, list) else json.loads(value)
    return value


class Recorder:
    def __init__(self, path: Path | None):
        self.path = path
        self.entries: list[dict] = []
        if path and path.exists():
            path.unlink()

    def add(self, record: dict) -> None:
        record = {"at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), **record}
        self.entries.append(record)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def evaluate_conditions(case: dict, scope: dict) -> bool:
    results = []
    for condition in case.get("conditions") or []:
        left = resolve(condition["variable_selector"], scope)
        right = condition.get("value")
        op = condition.get("comparison_operator")
        var_type = condition.get("varType", "string")
        if var_type == "number":
            try:
                left, right = float(left), float(right)
            except (TypeError, ValueError):
                pass
        elif var_type == "boolean":
            left, right = bool(left), str(right).lower() == "true"
        else:
            left, right = ("" if left is None else str(left)), str(right)
        if op in ("contains",):
            results.append(right in left)
        elif op in ("not contains",):
            results.append(right not in left)
        elif op in ("=", "is"):
            results.append(left == right)
        elif op in ("≠", "not is", "!="):
            results.append(left != right)
        elif op in ("start with", "startswith"):
            results.append(str(left).startswith(str(right)))
        elif op in ("end with", "endswith"):
            results.append(str(left).endswith(str(right)))
        elif op == "empty":
            results.append(left in ("", None))
        elif op == "not empty":
            results.append(left not in ("", None))
        elif op == ">":
            results.append(left > right)
        elif op == "<":
            results.append(left < right)
        elif op in (">=", "≥"):
            results.append(left >= right)
        elif op in ("<=", "≤"):
            results.append(left <= right)
        else:
            raise ReplayError("未实现的比较运算符：" + str(op))
    if not results:
        return False
    return all(results) if case.get("logical_operator", "and") == "and" else any(results)


def http_post(url: str, payload: dict, timeout: float) -> tuple[int, str, dict]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json; charset=utf-8"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace"), payload
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise ReplayError("HTTP %s %s -> %s: %s" % ("POST", url, error.code, detail)) from error
    except urllib.error.URLError as error:
        raise ReplayError("无法连接 %s：%s（PowerContext 是否已启动？）" % (url, error.reason)) from error


def run_llm(node: dict, scope: dict, args: argparse.Namespace, recorder: Recorder) -> str:
    model = node["data"]["model"]
    messages = []
    for message in node["data"]["prompt_template"]:
        messages.append({"role": message["role"], "content": render(message["text"], scope)})
    recorder.add(
        {
            "kind": "llm-prompt",
            "node": node["id"],
            "model": "%s/%s" % (model.get("provider"), model.get("name")),
            "messages": messages,
            "mode": "live" if args.llm_base_url else "offline-stub",
        }
    )
    if not args.llm_base_url:
        if not args.stub_verdict:
            raise ReplayError("缺少 --llm-base-url 时需要 --stub-verdict 提供离线判词")
        return Path(args.stub_verdict).read_text(encoding="utf-8")

    payload = {
        "model": args.llm_model,
        "messages": messages,
        "temperature": float(model.get("completion_params", {}).get("temperature", 0.7)),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        args.llm_base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + (args.llm_api_key or "sk-local"),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=args.timeout * 10) as response:
        answer = json.loads(response.read().decode("utf-8"))
    text = answer["choices"][0]["message"]["content"]
    recorder.add({"kind": "llm-response", "node": node["id"], "text": text})
    return text


def run_turn(dsl: dict, args: argparse.Namespace, query: str, user_id: str,
             dialogue_count: int, recorder: Recorder) -> str:
    graph = dsl["workflow"]["graph"]
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = graph["edges"]
    env = {item["name"]: item.get("value", "") for item in dsl["workflow"].get("environment_variables") or []}
    if args.base_url:
        env["POWERCONTEXT_BASE_URL"] = args.base_url

    scope: dict[str, Any] = {
        "sys.query": query,
        "sys.user_id": user_id,
        "sys.dialogue_count": dialogue_count,
    }
    for name, value in env.items():
        scope["env." + name] = value

    current = next(node for node in graph["nodes"] if node["data"]["type"] == "start")
    hop = 0
    while current["data"]["type"] != "answer":
        hop += 1
        if hop > 40:
            raise ReplayError("节点链路出现循环")
        data = current["data"]
        kind = data["type"]
        node_id = current["id"]

        if kind == "start":
            current = follow(nodes, edges, node_id, "source")
            continue

        if kind == "code":
            namespace: dict[str, Any] = {}
            exec(compile(data["code"], "<%s>" % node_id, "exec"), namespace)
            kwargs = {item["variable"]: resolve(item["value_selector"], scope) for item in data["variables"]}
            result = namespace["main"](**kwargs)
            if not isinstance(result, dict):
                raise ReplayError("%s 的 main() 必须返回 dict" % node_id)
            for name, spec in (data.get("outputs") or {}).items():
                if name not in result:
                    raise ReplayError("%s 缺少输出 %s" % (node_id, name))
                scope["%s.%s" % (node_id, name)] = coerce(result[name], spec.get("type", "string"))
            recorder.add({"kind": "code", "node": node_id, "outputs": result})
            current = follow(nodes, edges, node_id, "source")
            continue

        if kind == "http-request":
            url = render(data["url"], scope)
            body = data.get("body") or {}
            items = body.get("data") or []
            if body.get("type") in ("raw-text", "json") and len(items) == 1:
                rendered = render(str(items[0].get("value", "")), scope)
                payload = json.loads(rendered)
            else:
                payload = {item["key"]: render(str(item["value"]), scope) for item in items}
            status, text, _ = http_post(url, payload, args.timeout)
            scope["%s.body" % node_id] = text
            scope["%s.status_code" % node_id] = status
            recorder.add(
                {"kind": "http", "node": node_id, "method": data["method"].upper(), "url": url,
                 "request": payload, "status": status, "response": text[:4000]}
            )
            current = follow(nodes, edges, node_id, "source")
            continue

        if kind == "if-else":
            chosen = "false"
            for case in data.get("cases") or []:
                if evaluate_conditions(case, scope):
                    chosen = case.get("id", "true")
                    break
            recorder.add({"kind": "if-else", "node": node_id, "result": chosen})
            current = follow(nodes, edges, node_id, chosen)
            continue

        if kind == "llm":
            scope["%s.text" % node_id] = run_llm(current, scope, args, recorder)
            current = follow(nodes, edges, node_id, "source")
            continue

        raise ReplayError("回放不支持节点类型：" + kind)

    answer = render(current["data"]["answer"], scope)
    recorder.add({"kind": "answer", "node": current["id"], "text": answer})
    return answer


def follow(nodes: dict, edges: list, node_id: str, handle: str) -> dict:
    for edge in edges:
        if edge["source"] == node_id and edge.get("sourceHandle") == handle:
            return nodes[edge["target"]]
    raise ReplayError("%s 没有 handle=%s 的出边" % (node_id, handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="喵喵法庭 · 本地接线自检")
    parser.add_argument("--dsl", default="dsl/meow-court.yml")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="覆盖 DSL 里的 POWERCONTEXT_BASE_URL")
    parser.add_argument("--user", default="verify-user", help="对应 Dify 的 sys.user_id")
    parser.add_argument("--turn", action="append", required=True, help="依次执行的用户输入，可重复")
    parser.add_argument("--stub-verdict", help="离线判词 JSON 文件（无模型时使用）")
    parser.add_argument("--llm-base-url", help="OpenAI 兼容端点，如 http://127.0.0.1:8080/v1")
    parser.add_argument("--llm-model", default="local-model")
    parser.add_argument("--llm-api-key", default="")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--evidence", help="把每个节点的真实请求/响应写成 JSONL")
    args = parser.parse_args()

    dsl = load_dsl(Path(args.dsl))
    recorder = Recorder(Path(args.evidence) if args.evidence else None)

    for index, query in enumerate(args.turn):
        print("\n" + "=" * 72)
        print("第 %d 轮 · user=%s · 输入：%s" % (index + 1, args.user, query))
        print("=" * 72)
        print(run_turn(dsl, args, query, args.user, index, recorder))
    if args.evidence:
        print("\n证据已写入：%s" % args.evidence)
    return 0


if __name__ == "__main__":
    sys.exit(main())
