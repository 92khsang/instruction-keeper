#!/usr/bin/env python3
"""PostToolUse hook: check AGENTS.md / CLAUDE.md after they are written.

Design constraints, in order of importance:

1. Never block. An instruction file that is 205 lines long is not a reason to
   refuse an edit. Blocking belongs to real guardrails.
2. Diff-scoped. Report only findings this edit introduced, plus threshold
   crossings. Re-emitting the same standing warning on every edit trains the
   agent to ignore the channel, which is the attention problem the standard
   exists to prevent.
3. Fail open. Any internal error exits 0 and says nothing.

Two runtimes deliver this event, and the parts that differ are small enough to
handle in one script rather than two:

* Claude Code sends ``tool_input.file_path`` for Write and Edit, and sets
  ``CLAUDE_PROJECT_DIR``.
  https://code.claude.com/docs/en/hooks
* Codex sends ``tool_input.command`` for ``apply_patch``, holding the raw patch
  text, and sets no project-directory variable. It accepts ``Write`` and
  ``Edit`` as matcher aliases for ``apply_patch``, so one matcher serves both.
  https://learn.chatgpt.com/docs/hooks

Output contract, identical in both: findings go to
``hookSpecificOutput.additionalContext``, the field that reaches the model;
``systemMessage`` is shown to the user and not to the model, so it carries only
a one-line notice. Claude Code caps each at 10,000 characters and Codex spills
past roughly 2,500 tokens to disk, so the cap below satisfies the tighter of the
two.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

WATCHED = {"AGENTS.md", "CLAUDE.md", "AGENTS.override.md"}
MAX_FINDINGS = 6
MAX_CONTEXT_CHARS = 9000

# Directories the checker does not walk either. An instruction file inside a
# vendored tree is not this repository's to govern.
SKIP_DIRS = frozenset({
    "node_modules", "vendor", "target", "dist", "build", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".git",
})

# The apply_patch envelope. Codex passes the whole patch as tool_input.command,
# so the files an edit touched are the ones these lines name.
# https://github.com/openai/codex/blob/main/codex-rs/apply-patch/src/lib.rs
PATCH_PATH_RE = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$",
    re.M,
)


def project_root(payload: dict) -> Path:
    """The repository this session is anchored to.

    ``CLAUDE_PROJECT_DIR`` is read first because it is exact and because
    ``cwd`` follows Claude: it is whatever directory Claude last changed into,
    so a session that runs ``cd packages/api`` would otherwise stop recognising
    the repository root as the root.

    Codex sets no such variable, so the root is found the way Codex finds it --
    walking up for a ``.git`` directory, which is its default
    ``project_root_markers``. A repository cannot override that marker list, so
    there is nothing further to read.
    """
    declared = os.environ.get("CLAUDE_PROJECT_DIR")
    if declared:
        try:
            return Path(declared).resolve()
        except (OSError, RuntimeError):
            pass

    raw = payload.get("cwd") or os.getcwd()
    try:
        cwd = Path(raw).resolve()
    except (OSError, RuntimeError):
        return Path(raw)

    for candidate in (cwd,) + tuple(cwd.parents):
        try:
            if (candidate / ".git").exists():
                return candidate
        except OSError:
            continue
    return cwd


def edited_paths(payload: dict) -> List[Path]:
    """Every file this tool call wrote, as absolute paths.

    Claude Code names one file directly. Codex hands over the patch it applied,
    which may touch several files and states each as a path relative to the
    working directory.
    """
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return []

    found: List[Path] = []
    direct = tool_input.get("file_path") or tool_input.get("path")
    if isinstance(direct, str) and direct:
        found.append(Path(direct))

    command = tool_input.get("command")
    if isinstance(command, str) and "*** " in command:
        for update, move in PATCH_PATH_RE.findall(command):
            target = update or move
            if target:
                found.append(Path(target))

    base_raw = payload.get("cwd") or os.getcwd()
    try:
        base = Path(base_raw).resolve()
    except (OSError, RuntimeError):
        base = Path(base_raw)
    return [p if p.is_absolute() else (base / p) for p in found]


def in_scope(path: Path, root: Path) -> bool:
    """Whether an edit to this file can change what the checker reports.

    Any instruction file inside the repository can: the checker measures the
    nested pairs as well as the root one, and a nested file is part of the byte
    chain a Codex session below it loads. Vendored trees are excluded, matching
    the directories the checker does not walk.
    """
    if path.name not in WATCHED:
        return False
    try:
        relative = path.parent.resolve().relative_to(root)
    except (ValueError, OSError, RuntimeError):
        return False
    return not any(part in SKIP_DIRS for part in relative.parts)


def audit_hint() -> str:
    """How to get the full report, named for the runtime that is running us.

    ``/instruction-keeper:audit`` is a Claude Code slash command. Offering it to
    a Codex session would be an instruction that cannot be followed.
    """
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return ("Run /instruction-keeper:audit for the full report, including "
                "the checks this script cannot make.")
    return ("Run the checker without --new-only for the full report, and read "
            "skills/instruction-standard/ for the checks it cannot make.")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0

    root = project_root(payload)
    if not any(in_scope(p, root) for p in edited_paths(payload)):
        return 0

    checker = Path(__file__).with_name("check_instructions.py")
    try:
        proc = subprocess.run(
            [sys.executable, str(checker), "--json", "--new-only",
             "--project-root", str(root)],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return 0

    if proc.returncode == 2 or not proc.stdout.strip():
        return 0

    try:
        result = json.loads(proc.stdout)
    except ValueError:
        return 0

    findings = [f for f in result.get("findings", []) if f.get("severity") != "info"]
    if not findings:
        return 0

    rank = {"fail": 0, "warn": 1}
    findings.sort(key=lambda f: rank.get(f.get("severity", "warn"), 2))
    shown = findings[:MAX_FINDINGS]

    # Stated as a report rather than an instruction. A hook's output is data
    # about the environment; telling the model what to do from here belongs to
    # the user and to the skills.
    lines = [
        "instruction-keeper checked this repository's AGENTS.md / CLAUDE.md "
        "files after this edit, for both Claude Code and Codex. These findings "
        "are new since the last check, and may concern a file other than the "
        "one just written:"
    ]
    for f in shown:
        where = f["file"] + (f":{f['line']}" if f.get("line") else "")
        host = f" [{f['host']}]" if f.get("host") else ""
        lines.append(f"- [{f['severity'].upper()}]{host} {where} — {f['message']}")
        if f.get("fix"):
            lines.append(f"  {f['fix']}")
    if len(findings) > len(shown):
        lines.append(f"- ...and {len(findings) - len(shown)} more.")
    lines.append(audit_hint())

    context = "\n".join(lines)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n- ...truncated."

    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    summary = ", ".join(f"{n} {sev}" for sev, n in sorted(counts.items()))

    json.dump({
        "systemMessage": f"instruction-keeper: {summary} new in the instruction files.",
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        },
    }, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - a hook must never break the session
        sys.exit(0)
