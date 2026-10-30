"""Unified-diff extraction, safety validation and application."""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import PatchError

_HUNK = re.compile(r"^@@ ")


@dataclass
class DiffInfo:
    text: str
    paths: list[str]
    hunks: int
    added: int
    removed: int

    def as_dict(self) -> dict[str, object]:
        return {
            "paths": self.paths,
            "hunks": self.hunks,
            "added_lines": self.added,
            "removed_lines": self.removed,
        }


def extract_unified_diff(response: str) -> str:
    """Pull the first unified diff out of a model answer."""

    text = response.replace("\r\n", "\n").replace("\r", "\n").strip()
    if text.startswith("\ufeff"):
        text = text[1:]
    if "```" in text:
        blocks = re.findall(r"```(?:diff|patch)?\n(.*?)```", text, flags=re.DOTALL)
        for block in blocks:
            if _looks_like_diff(block):
                return block.strip() + "\n"
    start = None
    for marker in ("diff --git ", "--- a/", "--- "):
        index = text.find(marker)
        if index != -1 and (start is None or index < start):
            start = index
    if start is None:
        raise PatchError("MiniMax 响应中没有找到 unified diff")
    candidate = text[start:].strip()
    if not _looks_like_diff(candidate):
        raise PatchError("MiniMax 响应中的 diff 结构不完整")
    return candidate + "\n"


def _looks_like_diff(text: str) -> bool:
    return any(line.startswith("@@ ") for line in text.splitlines()) and (
        "--- " in text and "+++ " in text
    )


def validate_diff(diff: str, *, allowed_prefix: str = "src/") -> DiffInfo:
    lines = diff.splitlines()
    paths: list[str] = []
    hunks = 0
    added = 0
    removed = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("GIT binary patch") or line.startswith("Binary files "):
            raise PatchError("拒绝二进制补丁")
        if _HUNK.match(line):
            hunks += 1
            index += 1
            continue
        # A file header is exactly the adjacent ``---`` / ``+++`` pair.  Removed
        # content can itself start with ``--`` inside a hunk, so checking two
        # adjacent lines avoids misreading that content as a path.
        if line.startswith("--- ") and index + 1 < len(lines) and lines[index + 1].startswith("+++ "):
            for raw in (line[4:], lines[index + 1][4:]):
                if raw.strip() == "/dev/null":
                    continue
                path = raw.split("\t", 1)[0].strip()
                path = path.removeprefix("a/").removeprefix("b/")
                if not path:
                    raise PatchError("diff 文件头缺少路径")
                normalised = path.replace("\\", "/")
                if (
                    normalised.startswith("/")
                    or re.match(r"^[A-Za-z]:", normalised)
                    or ".." in normalised.split("/")
                ):
                    raise PatchError(f"diff 使用了非法路径: {path}")
                if not normalised.startswith(allowed_prefix):
                    raise PatchError(
                        f"diff 试图修改 {normalised}；本任务只允许修改 {allowed_prefix} 下的实现文件，"
                        "不得修改测试或规格。"
                    )
                if normalised not in paths:
                    paths.append(normalised)
            index += 2
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
        index += 1
    if not paths:
        raise PatchError("diff 没有声明任何目标文件")
    if hunks == 0:
        raise PatchError("diff 没有 hunk")
    if added == 0:
        raise PatchError("diff 没有新增行")
    return DiffInfo(text=diff, paths=paths, hunks=hunks, added=added, removed=removed)


_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def normalize_hunk_headers(diff: str) -> tuple[str, list[str]]:
    """Recompute unified-diff hunk line counts from the hunk bodies.

    ``git apply`` refuses a patch whose ``@@ -a,b +c,d @@`` counts disagree with
    the hunk body ("corrupt patch").  Models routinely emit plausible but wrong
    counts even when the context and the ``+/-`` lines are exactly right, so the
    counts are derived from the body instead of being trusted.

    Returns the normalized diff plus one human-readable note per correction.
    """

    lines = diff.splitlines()
    output: list[str] = []
    notes: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _HUNK_HEADER.match(line)
        if not match:
            output.append(line)
            index += 1
            continue
        body: list[str] = []
        cursor = index + 1
        while cursor < len(lines):
            candidate = lines[cursor]
            if _HUNK_HEADER.match(candidate) or candidate.startswith("diff --git "):
                break
            if (
                candidate.startswith("--- ")
                and cursor + 1 < len(lines)
                and lines[cursor + 1].startswith("+++ ")
            ):
                break
            if candidate[:1] in (" ", "-", "+", "\\"):
                body.append(candidate)
                cursor += 1
                continue
            break
        old_count = sum(1 for item in body if item[:1] in (" ", "-"))
        new_count = sum(1 for item in body if item[:1] in (" ", "+"))
        declared_old = int(match.group(2)) if match.group(2) is not None else 1
        declared_new = int(match.group(4)) if match.group(4) is not None else 1
        old_start = match.group(1)
        new_start = match.group(3)
        trailing = match.group(5)
        if body and (declared_old, declared_new) != (old_count, new_count):
            notes.append(
                f"@@ -{old_start},{declared_old} +{new_start},{declared_new} @@ 的行数与正文不符，"
                f"已按正文修正为 -{old_start},{old_count} +{new_start},{new_count}"
            )
        if body:
            output.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@{trailing}")
        else:
            output.append(line)
        output.extend(body)
        index = cursor
    return "\n".join(output) + "\n", notes


def apply_diff(diff: str, project_root: Path, *, check_only: bool = False, reverse: bool = False) -> str:
    if not diff.strip():
        raise PatchError("空补丁")
    if not shutil_which_git():
        raise PatchError("需要 git 命令来应用补丁；请安装 Git 并加入 PATH")
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".patch", delete=False, dir=str(project_root.parent), newline="\n"
    ) as handle:
        handle.write(diff)
        patch_path = Path(handle.name)
    command = ["git", "apply", "--whitespace=nowarn", "-p1"]
    if check_only:
        command.append("--check")
    if reverse:
        command.append("-R")
    command.append(str(patch_path))
    try:
        completed = subprocess.run(
            command,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    finally:
        patch_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PatchError(f"git apply 失败: {detail[:1500]}")
    return (completed.stdout or completed.stderr or "").strip()


def shutil_which_git() -> str | None:
    from shutil import which

    return which("git")
