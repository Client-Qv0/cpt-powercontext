"""Check internal consistency of submitted evidence; never calls a model.

These are local artifacts, not cryptographic proof of a remote provider call.
"""
from __future__ import annotations
import json
from pathlib import Path
from .errors import SpecAnchorError
from .patch import extract_unified_diff, normalize_hunk_headers, validate_diff


def verify_model_evidence(run: Path, task_id: str) -> dict:
    try:
        result = json.loads((run / "result.json").read_text(encoding="utf-8"))
        context = json.loads((run / "context.json").read_text(encoding="utf-8"))
        calls = [json.loads(line) for line in (run / "minimax-calls.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        if result.get("status") != "succeeded" or result.get("task_id") != task_id or context["task"]["id"] != task_id:
            raise ValueError("task/status mismatch")
        attempts = result["attempts"]
        if not isinstance(attempts, int) or attempts <= 0 or len(calls) != attempts:
            raise ValueError("attempt count mismatch")
        for index, call in enumerate(calls, 1):
            response = call["response"]
            if (call["attempt"] != index or not response["request_id"]
                    or not response["model"].lower().startswith("minimax")
                    or call["request"]["model"] != response["model"]
                    or response["usage"]["total_tokens"] <= 0):
                raise ValueError("incomplete call metadata")
        response = (run / f"minimax-response-{attempts}.txt").read_text(encoding="utf-8")
        patch = (run / f"attempt-{attempts}.diff").read_text(encoding="utf-8")
        recorded = extract_unified_diff(response)
        normalized, _notes = normalize_hunk_headers(recorded)
        if normalized != patch:
            raise ValueError("response/patch mismatch")
        info = validate_diff(patch)
        for key, log in (("baseline_target", "baseline-target.log"),
                         ("baseline_regression", "baseline-regression.log"),
                         ("target", f"attempt-{attempts}-target.log"),
                         ("regression", f"attempt-{attempts}-regression.log"),
                         ("full_suite", "full-suite.log")):
            record = result["test_runs"][key]
            text = (run / log).read_text(encoding="utf-8")
            if key == "baseline_target":
                if record["exit_code"] != 1 or record["failed"] <= 0 or f'{record["failed"]} failed' not in text:
                    raise ValueError("missing baseline failure")
            elif record["exit_code"] != 0 or record["passed"] <= 0 or f'{record["passed"]} passed' not in text:
                raise ValueError(f"invalid verification: {key}")
        return {"task_id": task_id, "attempts": attempts, "paths": info.paths, "model": calls[-1]["response"]["model"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SpecAnchorError(f"模型证据不完整或不一致: {exc}") from exc
