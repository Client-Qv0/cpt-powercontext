#!/usr/bin/env python3
"""给某位玩家预置「前科」，让累犯/援引旧案的玩法一开局就能看到。

它做的事和 Dify 工作流完全一样（同一套 Scope 幂等键、同一种 kind、同一段文本格式），
所以预置的案底会和后续真实判决混在同一个卷宗里。

用法：
    python scripts/seed_demo_memory.py --base-url http://127.0.0.1:8000 --user demo-grader
    python scripts/seed_demo_memory.py --user demo-grader --force   # 已有案底也再写一遍

只依赖标准库。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

DEFAULT_CASES = [
    "第1号 · 累犯★☆☆☆☆ · 被告自述：把猫罐头换成减肥罐头，还说是猫自己说要减肥 | "
    "案由：偷换猫粮 | 判读：狡辩 | 判决：本庭认定被告主观恶意明显，念在初犯，改为从轻发落 | "
    "刑罚：罚手剥鸡胸肉三块 | 附加条款：本周纸箱归本庭所有 | 援引旧案：无",
    "第2号 · 累犯★★☆☆☆ · 被告自述：凌晨三点把猫从键盘上抱走，害猫失去一次占领文件的机会 | "
    "案由：妨碍猫务 | 判读：认罪 | 判决：本庭援引第 1 号，被告屡教不改，本次加罚 | "
    "刑罚：罚陪玩逗猫棒十五分钟，中途不许看手机 | 附加条款：键盘使用权收回三天 | 援引旧案：第 1 号",
    "第3号 · 累犯★★★☆☆ · 被告自述：把猫的纸箱扔了，还说是风干的 | "
    "案由：毁坏猫居 | 判读：嫁祸天气 | 判决：本庭援引第 2 号，被告已构成惯犯，本次启用通缉令 | "
    "刑罚：罚新纸箱两个，且必须亲自钻进纸箱示范一次 | 附加条款：通缉令张贴于冰箱门 | 援引旧案：第 2 号",
]


def player_key(user_id: str) -> str:
    """与 Dify「庭前登记」节点完全一致的 Scope 标识算法。"""
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


def main() -> int:
    parser = argparse.ArgumentParser(description="预置喵喵法庭前科")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user", default="demo-grader", help="对应 Dify 的 sys.user_id")
    parser.add_argument("--force", action="store_true", help="已有案底时也继续追加")
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    key = player_key(args.user)
    scope = post(
        args.base_url,
        "/v1/scopes",
        {
            "title": "喵喵法庭 · " + key,
            "summary": "喵喵法庭玩家的跨会话案底（PowerContext Scope）",
            "idempotency_key": "meow-court:v1:" + key,
        },
        args.timeout,
    )
    scope_id = scope["scope_id"]
    print("scope_id =", scope_id, "(玩家标识 %s)" % key)

    listing = post(args.base_url, "/v1/memory/entries/list", {"scope_id": scope_id}, args.timeout)
    existing = [item for item in listing.get("entries", []) if item.get("kind") == "meow-court/case"]
    if existing and not args.force:
        print("该玩家已有 %d 条案底，跳过预置（要再加请加 --force）。" % len(existing))
        return 0

    for text in DEFAULT_CASES:
        result = post(
            args.base_url,
            "/v1/memory/remember",
            {
                "scope_id": scope_id,
                "kind": "meow-court/case",
                "text": text,
                "reason": "喵喵法庭演示数据预置",
            },
            args.timeout,
        )
        records = result.get("records") or []
        artifact = (records[0].get("artifact") or {}).get("artifact_id") if records else "?"
        print("已写入", artifact, "->", text[:34], "…")

    print("\n预置完成。在 Dify 里用同一个 user 打开「喵喵法庭」，输入「查卷宗」即可看到这几条前科")
    print("（Web 界面里 user 由浏览器会话决定；用 API 体验时可显式指定 user=demo-grader）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
