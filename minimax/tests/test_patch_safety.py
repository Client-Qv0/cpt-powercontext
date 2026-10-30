"""Safety tests for the unified-diff guard used before touching real code."""

from __future__ import annotations

import difflib
import re
import shutil
import uuid
from pathlib import Path

import pytest

from specanchor.config import PACKAGE_ROOT
from specanchor.errors import PatchError
from specanchor.patch import (
    apply_diff,
    extract_unified_diff,
    normalize_hunk_headers,
    validate_diff,
)


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


def test_normalizes_wrong_hunk_counts() -> None:
    """Models emit plausible but wrong @@ counts; the hunk body is authoritative."""

    patch = (
        "--- a/src/booknest/catalog.py\n"
        "+++ b/src/booknest/catalog.py\n"
        "@@ -39,10 +39,23 @@ class CatalogService:\n"
        " \n"
        "         self._validate_paging(page, page_size)\n"
        " \n"
        "-        ordered = sorted(self._books)\n"
        "+        ordered = sorted(filtered)\n"
    )
    normalized, notes = normalize_hunk_headers(patch)
    assert "@@ -39,4 +39,4 @@" in normalized
    assert len(notes) == 1
    assert "行数与正文不符" in notes[0]
    info = validate_diff(normalized)
    assert info.hunks == 1
    assert info.added == 1
    assert info.removed == 1


def test_normalization_keeps_correct_headers_untouched() -> None:
    patch = (
        "--- a/src/booknest/catalog.py\n"
        "+++ b/src/booknest/catalog.py\n"
        "@@ -1,2 +1,2 @@\n"
        " keep\n"
        "-drop\n"
        "+add\n"
    )
    normalized, notes = normalize_hunk_headers(patch)
    assert notes == []
    assert normalized == patch


def test_normalized_patch_applies_when_the_model_header_is_wrong() -> None:
    """A wrong @@ count used to abort the whole run; now it is repaired."""

    if shutil.which("git") is None:
        pytest.skip("git is not installed")

    root = PACKAGE_ROOT / ".state" / "test-tmp" / f"hunk-{uuid.uuid4().hex[:8]}"
    target = root / "src" / "pkg" / "mod.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "def run(items):\n    return sorted(items)\n"
    changed = "def run(items):\n    return sorted(items, reverse=True)\n"
    target.write_text(original, encoding="utf-8")

    good = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            changed.splitlines(keepends=True),
            fromfile="a/src/pkg/mod.py",
            tofile="b/src/pkg/mod.py",
            n=1,
        )
    )
    corrupted = re.sub(
        r"^@@ -\d+,\d+ \+\d+,\d+ @@",
        "@@ -39,10 +39,23 @@",
        good,
        count=1,
        flags=re.M,
    )
    try:
        # The malformed header is rejected by git as it stands ...
        with pytest.raises(PatchError):
            apply_diff(corrupted, root, check_only=True)
        # ... and accepted once the counts are derived from the body.
        normalized, notes = normalize_hunk_headers(corrupted)
        assert notes
        apply_diff(normalized, root, check_only=True)
        apply_diff(normalized, root)
        assert target.read_text(encoding="utf-8") == changed
    finally:
        shutil.rmtree(root, ignore_errors=True)
