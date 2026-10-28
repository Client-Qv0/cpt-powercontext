#!/usr/bin/env python3
"""把某位玩家的卷宗清空，让「前科」从 0 重新开始。

它用的是 PowerContext 自己的软删除接口 `POST /v1/atomic-memory/lifecycle`
（`state=forgotten`）：条目不会被物理删除，但 `memory/entries/list` 默认不再返回，
所以工作流算出来的前科次数会归零，下一次开庭就是「第 1 号」。

用法：
    python scripts/reset_player.py --base-url http://127.0.0.1:8000 --user <玩家标识>
    python scripts/reset_player.py --user <玩家标识> --dry-run     # 只看会删几条

玩家标识就是 Dify 里的 `sys.user_id`：
  - Web 界面：登录 Dify 的用户 id（在「运行历史」的输入里能看到）
  - API 调用：`POST /v1/chat-messages` 里的 `user` 字段

只依赖标准库。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

CASE_KIND = "meow-court/case"


def player_key(user_id: str) -> str:
    """与工作流「庭前登记」节点完全一致的 Scope 标识算法。"""
    key = re.sub(r"[^0-9A-Za-z_-]", "", (user_id or "").strip())[:40]
    return key or "guest"


def post(base_url: str, path: str, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        raise SystemExit("POST %s 失败：HTTP %s %s" % (path, error.code, detail)) from error
    except urllib.error.URLError as error:
        raise SystemExit("连不上 PowerContext（%s）：%s" % (base_url, error.reason)) from error


def resolve_scope(base_url: str, key: str, timeout: float) -> str:
    """用幂等键取回该玩家的卷宗柜（不会新建重复的）。"""
    scope = post(
        base_url,
        "/v1/scopes",
        {
            "title": "喵喵法庭 · " + key,
            "summary": "喵喵法庭玩家的跨会话案底（PowerContext Scope）",
            "idempotency_key": "meow-court:v1:" + key,
        },
        timeout,
    )
    return scope["scope_id"]


def main() -> int:
    parser = argparse.ArgumentParser(description="清空喵喵法庭某位玩家的前科")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user", required=True, help="Dify 的 sys.user_id")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不真的清空")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    key = player_key(args.user)
    scope_id = resolve_scope(args.base_url, key, args.timeout)
    print("玩家 %s（Scope %s）" % (key, scope_id))

    listing = post(args.base_url, "/v1/memory/entries/list", {"scope_id": scope_id}, args.timeout)
    cases = [item for item in listing.get("entries", []) if item.get("kind") == CASE_KIND]
    print("当前案底：%d 条" % len(cases))
    if not cases:
        print("已经是空的，下次开庭就是第 1 号。")
        return 0
    if args.dry_run:
        print("（dry-run，不修改）")
        return 0

    for item in cases:
        artifact = item.get("artifact") or {}
        post(
            args.base_url,
            "/v1/atomic-memory/lifecycle",
            {
                "scope_id": scope_id,
                "target": {
                    "artifact": {
                        "family": artifact.get("family", "atomic-memory"),
                        "artifact_id": artifact.get("artifact_id"),
                        "revision": artifact.get("revision", 1),
                    },
                    "state_version": item.get("state_version", 0),
                },
                "state": "forgotten",
            },
            args.timeout,
        )
        print("  已清空 %s" % artifact.get("artifact_id"))

    after = post(args.base_url, "/v1/memory/entries/list", {"scope_id": scope_id}, args.timeout)
    left = [item for item in after.get("entries", []) if item.get("kind") == CASE_KIND]
    print("清空后案底：%d 条 → 下次开庭是第 %d 号" % (len(left), len(left) + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
