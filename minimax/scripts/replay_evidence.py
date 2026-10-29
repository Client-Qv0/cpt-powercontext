"""Replay a recorded patch in a temporary standalone Git repo, without API/DB calls."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from specanchor.evidence import verify_model_evidence
from specanchor.patch import apply_diff


def replay(run: Path, baseline: Path) -> dict:
    context = json.loads((run / "context.json").read_text(encoding="utf-8"))
    proof = verify_model_evidence(run, context["task"]["id"])
    tests = context["tests"]
    nodes = {kind: [item["path"] + "::" + "::".join(item["test_id"].split(".")) for item in tests[kind]] for kind in ("target", "regression")}
    if not all(nodes.values()):
        raise ValueError("missing target/regression tests")
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryDirectory(prefix="specanchor-replay-") as directory:
        root = Path(directory)
        with zipfile.ZipFile(baseline) as archive:
            for member in archive.infolist():
                if not (root / member.filename).resolve().is_relative_to(root.resolve()):
                    raise ValueError("unsafe baseline archive")
            archive.extractall(root)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        outcomes = {}
        def test(name, selected, expect_failure=False):
            proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *selected], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", env=environment)
            output = proc.stdout + proc.stderr
            print(f"[{name}]\n{output}", flush=True)
            ok = (proc.returncode == 1 and " failed" in output and "ERROR collecting" not in output) if expect_failure else proc.returncode == 0
            if not ok:
                raise RuntimeError(f"replay failed: {name} (exit={proc.returncode})")
            outcomes[name] = {"exit_code": proc.returncode, "output": output}
        test("before.target", nodes["target"], True)
        test("before.regression", nodes["regression"])
        patch = (run / f"attempt-{proof['attempts']}.diff").read_text(encoding="utf-8")
        apply_diff(patch, root, check_only=True)
        apply_diff(patch, root)
        test("after.target", nodes["target"])
        test("after.regression", nodes["regression"])
        test("after.full", [])
        return {"mode": "recorded-patch-replay (no model call, no state restoration)", "evidence": proof, "checks": outcomes}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=ROOT / "evidence/baseline/sample_project.zip")
    args = parser.parse_args()
    replay(args.run_dir.resolve(), args.baseline.resolve())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
