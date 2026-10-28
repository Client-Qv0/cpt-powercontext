"""Build a test-only DSL variant: replace the LLM node with a deterministic code stub."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

STUB_CODE = '''
import json


def main(case_text: str, prior_count: float, hearing_no: float, stars: str) -> dict:
    # 测试副本专用：用确定性桩替代模型，用来验证 Dify 侧其余节点与 PowerContext 接线
    precedent = "第 %d 号" % max(1, int(prior_count)) if prior_count else "无"
    return {
        "text": json.dumps(
            {
                "charge": "测试案由",
                "plea": "认罪（离线桩）",
                "verdict": "本庭测试判词，援引旧案 %s。" % precedent,
                "penalty": "罚测试猫粮一罐",
                "clause": "本条为离线桩输出，不代表模型能力",
                "precedent": precedent,
                "gavel": "退庭。",
            },
            ensure_ascii=False,
        )
    }
'''


def _str_rep(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|" if "\n" in data else None)


class Dumper(yaml.Dumper):
    pass


Dumper.add_representer(str, _str_rep)


def main() -> int:
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    doc = yaml.safe_load(source.read_text(encoding="utf-8"))

    nodes = doc["workflow"]["graph"]["nodes"]
    for index, node in enumerate(nodes):
        if node["id"] == "judge":
            nodes[index] = {
                "data": {
                    "code": STUB_CODE.strip() + "\n",
                    "code_language": "python3",
                    "desc": "测试副本：用确定性桩替代模型节点（正式作品不含此节点）",
                    "outputs": {"text": {"children": None, "type": "string"}},
                    "selected": False,
                    "title": "橘座法官（离线桩）",
                    "type": "code",
                    "variables": [
                        {"value_selector": ["intake", "case_text"], "variable": "case_text"},
                        {"value_selector": ["brief", "prior_count"], "variable": "prior_count"},
                        {"value_selector": ["brief", "hearing_no"], "variable": "hearing_no"},
                        {"value_selector": ["brief", "stars"], "variable": "stars"},
                    ],
                },
                "height": 90,
                "id": "judge",
                "position": node["position"],
                "positionAbsolute": node["positionAbsolute"],
                "selected": False,
                "sourcePosition": "right",
                "targetPosition": "left",
                "type": "custom",
                "width": 244,
            }

    for edge in doc["workflow"]["graph"]["edges"]:
        if edge["source"] == "judge":
            edge["data"]["sourceType"] = "code"
        if edge["target"] == "judge":
            edge["data"]["targetType"] = "code"

    doc["app"]["name"] = "喵喵法庭-测试副本"
    doc["app"]["description"] = "仅用于本地验证：LLM 节点被替换为确定性桩，正式作品见 dsl/meow-court.yml"
    target.write_text(
        yaml.dump(doc, Dumper=Dumper, allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000),
        encoding="utf-8",
    )
    print("wrote", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
