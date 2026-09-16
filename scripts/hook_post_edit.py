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

Output contract. Findings go to ``hookSpecificOutput.additionalContext``, which
is the PostToolUse field that reaches Claude's context; ``systemMessage`` is
shown to the user and not to Claude, so it carries only a one-line notice.
Both are capped at 10,000 characters by Claude Code.
https://code.claude.com/docs/en/hooks
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WATCHED = {"AGENTS.md", "CLAUDE.md"}
MAX_FINDINGS = 6
MAX_CONTEXT_CHARS = 9000


def project_root(payload: dict) -> Path:
    """The repository this session is anchored to.

    ``CLAUDE_PROJECT_DIR`` is read before the payload's ``cwd`` because ``cwd``
    follows Claude: it is whatever directory Claude last changed into, so a
    session that runs ``cd packages/api`` would otherwise stop recognising the
    repository-root pair as the root pair.
    """
    declared = os.environ.get("CLAUDE_PROJECT_DIR")
    raw = declared or payload.get("cwd") or os.getcwd()
    return Path(raw).resolve()


def in_scope(path: Path, root: Path) -> bool:
    """Whether this file is the repository-root instruction pair.

    A nested AGENTS.md in a monorepo package is a legitimate pattern this plugin
    deliberately does not govern. Claude Code loads a project CLAUDE.md from
    either ``CLAUDE.md`` or ``.claude/CLAUDE.md``, so both count as the root
    pair.
    """
    try:
        parent = path.parent.resolve()
    except OSError:
        return False
    if parent == root:
        return True
    return path.name == "CLAUDE.md" and parent == (root / ".claude").resolve()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    tool_input = payload.get("tool_input") or {}
    raw_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not raw_path:
        return 0

    path = Path(raw_path)
    if path.name not in WATCHED:
        return 0

    root = project_root(payload)
    if not in_scope(path, root):
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
        "instruction-keeper checked the repository-root AGENTS.md / CLAUDE.md "
        "pair after this edit. These findings are new since the last check, and "
        "may concern either file in the pair rather than only the one just "
        "written:"
    ]
    for f in shown:
        where = f["file"] + (f":{f['line']}" if f.get("line") else "")
        lines.append(f"- [{f['severity'].upper()}] {where} — {f['message']}")
        if f.get("fix"):
            lines.append(f"  {f['fix']}")
    if len(findings) > len(shown):
        lines.append(f"- ...and {len(findings) - len(shown)} more.")
    lines.append(
        "Run /instruction-keeper:audit for the full report, including the checks "
        "this script cannot make."
    )

    context = "\n".join(lines)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n- ...truncated."

    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    summary = ", ".join(f"{n} {sev}" for sev, n in sorted(counts.items()))

    json.dump({
        "systemMessage": f"instruction-keeper: {summary} new in AGENTS.md / CLAUDE.md.",
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
