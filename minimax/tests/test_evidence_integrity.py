import json
import shutil
import tempfile
from pathlib import Path
import pytest
from specanchor.evidence import verify_model_evidence
from specanchor.errors import SpecAnchorError

RUN = Path(__file__).resolve().parents[1] / "evidence/runs/20261029-080429-TASK-BOOK-0042-run-ca941f5461"

def test_recorded_evidence_without_credentials(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    assert verify_model_evidence(RUN, "TASK-BOOK-0042")["paths"] == ["src/booknest/catalog.py"]

@pytest.fixture
def scratch():
    with tempfile.TemporaryDirectory(prefix="specanchor-evidence-") as directory:
        yield Path(directory)

@pytest.mark.parametrize("damage", ["response", "log", "request", "task"])
def test_tampered_evidence_rejected(scratch, damage):
    run = scratch / "run"
    shutil.copytree(RUN, run)
    if damage == "response":
        (run / "minimax-response-1.txt").write_text("no patch", encoding="utf-8")
    elif damage == "log":
        (run / "attempt-1-target.log").write_text("8 failed", encoding="utf-8")
    elif damage == "request":
        path = run / "minimax-calls.jsonl"
        call = json.loads(path.read_text(encoding="utf-8"))
        call["response"]["request_id"] = ""
        path.write_text(json.dumps(call), encoding="utf-8")
    else:
        path = run / "result.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["task_id"] = "other-task"
        path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SpecAnchorError):
        verify_model_evidence(run, "TASK-BOOK-0042")
