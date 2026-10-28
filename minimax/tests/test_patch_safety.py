"""Safety tests for the unified-diff guard used before touching real code."""

from __future__ import annotations

import difflib
import shutil
import uuid
from pathlib import Path

import pytest

from specanchor.config import PACKAGE_ROOT
from specanchor.errors import PatchError
from specanchor.patch import apply_diff, extract_unified_diff, validate_diff


def _patch_for(old: str, new: str, path: str = "src/booknest/catalog.py") -> str:
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=1,
    )
    return "".join(diff)


def test_accepts_a_normal_src_patch() -> None:
    patch = _patch_for("x = 1\n", "x = 2\n")
    info = validate_diff(patch)
    assert info.paths == ["src/booknest/catalog.py"]
    assert info.hunks == 1
    assert info.added == 1
    assert info.removed == 1


def test_rejects_test_or_spec_paths() -> None:
    for path in ("tests/test_x.py", "specs/catalog.md", "README.md"):
        patch = f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-x\n+y\n"
        with pytest.raises(PatchError):
            validate_diff(patch)


def test_rejects_absolute_and_parent_paths() -> None:
    for path in ("/etc/passwd", "../outside.py", "C:/Windows/x.py"):
        patch = f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-x\n+y\n"
        with pytest.raises(PatchError):
            validate_diff(patch)


def test_rejects_binary_patch() -> None:
    patch = "diff --git a/src/x.py b/src/x.py\nGIT binary patch\nliteral 3\n"
    with pytest.raises(PatchError):
        validate_diff(patch)


def test_extracts_diff_from_markdown_fence() -> None:
    patch = _patch_for("x = 1\n", "x = 2\n")
    response = f"这是补丁：\n```diff\n{patch}```\n"
    extracted = extract_unified_diff(response)
    assert validate_diff(extracted).added == 1


def test_apply_and_reverse_a_patch() -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    from shutil import copytree

    root = PACKAGE_ROOT / ".state" / "test-tmp" / f"patch-{uuid.uuid4().hex[:8]}"
    copytree(PACKAGE_ROOT / "sample_project", root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "pytest-cache-files-*"))
    target = root / "src" / "booknest" / "catalog.py"
    original = target.read_text(encoding="utf-8")
    changed = original.replace(
        "        self._validate_paging(page, page_size)\n",
        "        self._validate_paging(page, page_size)\n\n        # patch guard test\n",
        1,
    )
    patch = _patch_for(original, changed)
    try:
        apply_diff(patch, root, check_only=True)
        apply_diff(patch, root)
        assert "# patch guard test" in target.read_text(encoding="utf-8")
        apply_diff(patch, root, reverse=True)
        assert target.read_text(encoding="utf-8") == original
    finally:
        shutil.rmtree(root, ignore_errors=True)

