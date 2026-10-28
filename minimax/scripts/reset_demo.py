"""Reset the demo to a clean, reproducible state.

``--baseline`` restores the pre-change sample project from the committed zip,
clears the local PowerContext database, and re-imports the seekdb index.
Without ``--baseline`` only the PowerContext state and the index are refreshed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from specanchor.config import Settings  # noqa: E402
from specanchor.db import Database  # noqa: E402
from specanchor.ingest import import_project  # noqa: E402
from specanchor.state import reset_state  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="重置验证样例（可选恢复修改前基线）")
    parser.add_argument("--baseline", action="store_true", help="从 evidence/baseline 还原 sample_project")
    parser.add_argument("--project", default="booknest")
    parser.add_argument("--yes", action="store_true", help="不询问，直接覆盖样例工程")
    args = parser.parse_args()

    settings = Settings.load()
    root = settings.project_root
    if args.baseline:
        if not args.yes:
            answer = input(f"将覆盖 {root} 下的 src/specs/tests，继续？[y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                print("已取消")
                return 1
        archive = PACKAGE_ROOT / "evidence" / "baseline" / "sample_project.zip"
        if not archive.is_file():
            raise SystemExit(f"基线快照不存在: {archive}")
        for name in ("src", "specs", "tests"):
            target = root / name
            if target.exists():
                shutil.rmtree(target)
        with zipfile.ZipFile(archive) as zip_file:
            zip_file.extractall(root)
        print(f"已从 {archive} 还原基线到 {root}")

    removed = reset_state(settings)
    print("PowerContext 状态文件: " + ("已删除 " + ", ".join(removed) if removed else "无需清理"))

    database = Database(settings)
    database.init_schema()
    result = import_project(database, args.project, root, reset=True)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
