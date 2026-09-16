#!/usr/bin/env python3
"""Tests for scripts/hook_post_edit.py. Standard library only, Python 3.8+.

Run:  python3 tests/test_hook_post_edit.py

The hook is driven the way Claude Code drives it: as a subprocess with a
PostToolUse JSON payload on stdin. Nothing is imported from it, because the
contract under test is the process contract -- exit status and the JSON written
to stdout.

Every test gets its own repository and its own XDG_STATE_HOME so that the
--new-only baseline the hook writes cannot leak between tests or into the
developer's real state directory. The subprocess is started outside the fixture
repository so that a fallback to the process working directory cannot silently
make an out-of-scope file look in scope.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the repository

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOOK = PLUGIN_ROOT / "scripts" / "hook_post_edit.py"
CHECKER = PLUGIN_ROOT / "scripts" / "check_instructions.py"

CONFORMING = """\
Acme API owns the public REST surface. Billing lives in `acme-billing`.

## Rules

- Never weaken or delete an existing test to make a change pass.

## Commands

```bash
pnpm test
```
"""

SPECKIT_BLOCK = (
    "\n<!-- SPECKIT START -->\n"
    "Read the current plan at specs/001/plan.md\n"
    "<!-- SPECKIT END -->\n"
)

# Fields that would make the hook block the edit or hide its own output. The
# hook warns and never blocks, so none of these may ever appear.
FORBIDDEN_TOP_LEVEL = [
    "suppressOutput", "decision", "continue", "stopReason", "permissionDecision",
    "permissionDecisionReason",
]


class HookResult:
    def __init__(self, proc: subprocess.CompletedProcess) -> None:
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr

    @property
    def emitted(self) -> bool:
        return bool(self.stdout.strip())

    def payload(self) -> dict:
        return json.loads(self.stdout)


class HookCase(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="ik-hook-"))
        self.root = self.base / "repo"
        self.root.mkdir()
        self.state = self.base / "state"
        self.state.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    # -- fixture helpers ---------------------------------------------------

    def write(self, rel: str, content: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def payload(self, file_path, cwd=None, tool_name="Write") -> dict:
        tool_input = {"file_path": str(file_path)} if file_path is not None else {}
        if tool_name == "Edit":
            tool_input.update({"old_string": "a", "new_string": "b"})
        else:
            tool_input["content"] = "..."
        return {
            "session_id": "test-session",
            "transcript_path": str(self.base / "transcript.jsonl"),
            "cwd": str(cwd if cwd is not None else self.root),
            "hook_event_name": "PostToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_response": {"filePath": str(file_path), "success": True},
        }

    def run_hook(self, payload, project_dir="", stdin=None, hook=None) -> HookResult:
        """Run the hook once.

        Args:
            payload: the object sent on stdin; ignored when ``stdin`` is given.
            project_dir: value for CLAUDE_PROJECT_DIR. The default "" means the
                fixture root; ``None`` means the variable is unset.
            stdin: raw bytes-as-text to send instead of a serialized payload.
            hook: an alternative hook script path.
        """
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        if project_dir == "":
            env["CLAUDE_PROJECT_DIR"] = str(self.root)
        elif project_dir is not None:
            env["CLAUDE_PROJECT_DIR"] = str(project_dir)
        env["XDG_STATE_HOME"] = str(self.state)
        proc = subprocess.run(
            [sys.executable, str(hook or HOOK)],
            input=stdin if stdin is not None else json.dumps(payload),
            capture_output=True, text=True, timeout=60,
            cwd=str(self.base), env=env,
        )
        return HookResult(proc)

    # -- assertions --------------------------------------------------------

    def assertExitsCleanly(self, result: HookResult) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)

    def assertSilent(self, result: HookResult) -> None:
        self.assertExitsCleanly(result)
        self.assertEqual(result.stdout, "", result.stdout)

    def assertNeverBlocks(self, result: HookResult) -> dict:
        """Check the shape every emitting run must have, and return the payload."""
        self.assertExitsCleanly(result)
        self.assertTrue(result.emitted, "the hook emitted nothing")
        payload = result.payload()
        for key in FORBIDDEN_TOP_LEVEL:
            self.assertNotIn(key, payload)
        specific = payload.get("hookSpecificOutput", {})
        for key in FORBIDDEN_TOP_LEVEL:
            self.assertNotIn(key, specific)
        return payload


class TestOutputContract(HookCase):
    def test_root_agents_edit_emits_additional_context(self):
        # AGENTS.md with no CLAUDE.md is a warning, which is what the hook
        # channel exists to carry.
        agents = self.write("AGENTS.md", CONFORMING)
        result = self.run_hook(self.payload(agents))
        payload = self.assertNeverBlocks(result)

        specific = payload["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PostToolUse")
        context = specific["additionalContext"]
        self.assertIn("CLAUDE.md", context)
        self.assertIn("[WARN]", context)
        self.assertLessEqual(len(context), 10000)

    def test_system_message_is_a_one_line_user_notice(self):
        # systemMessage is shown to the user and does not reach Claude's
        # context, so it carries a notice and not the findings.
        agents = self.write("AGENTS.md", CONFORMING)
        payload = self.assertNeverBlocks(self.run_hook(self.payload(agents)))
        message = payload["systemMessage"]
        self.assertNotIn("\n", message)
        self.assertTrue(message.startswith("instruction-keeper: "), message)
        self.assertIn("warn", message)

    def test_edit_payloads_are_handled_like_write_payloads(self):
        agents = self.write("AGENTS.md", CONFORMING)
        result = self.run_hook(self.payload(agents, tool_name="Edit"))
        payload = self.assertNeverBlocks(result)
        self.assertIn("additionalContext", payload["hookSpecificOutput"])

    def test_findings_are_capped_and_the_remainder_is_counted(self):
        pointers = "".join(
            "- [docs/gone-%d.md](docs/gone-%d.md) — a page that no longer exists.\n"
            % (i, i)
            for i in range(10)
        )
        agents = self.write("AGENTS.md", CONFORMING + "\n## Pointers\n\n" + pointers)
        self.write("CLAUDE.md", "@AGENTS.md\n")
        payload = self.assertNeverBlocks(self.run_hook(self.payload(agents)))
        context = payload["hookSpecificOutput"]["additionalContext"]
        bullets = [l for l in context.split("\n") if l.startswith("- [")]
        self.assertEqual(len(bullets), 6, context)
        self.assertRegex(context, r"- \.\.\.and \d+ more\.")
        self.assertLessEqual(len(context), 10000)


class TestFailOpen(HookCase):
    def test_malformed_stdin_exits_zero_silently(self):
        self.write("AGENTS.md", CONFORMING)
        self.assertSilent(self.run_hook(None, stdin="this is not json"))

    def test_empty_stdin_exits_zero_silently(self):
        self.write("AGENTS.md", CONFORMING)
        self.assertSilent(self.run_hook(None, stdin=""))

    def test_payload_without_a_file_path_exits_zero_silently(self):
        self.write("AGENTS.md", CONFORMING)
        self.assertSilent(self.run_hook(self.payload(None)))

    def test_missing_checker_exits_zero_silently(self):
        # The hook resolves the checker beside itself; a truncated install must
        # not surface an error into the session.
        orphan_dir = self.base / "orphan-scripts"
        orphan_dir.mkdir()
        orphan = orphan_dir / "hook_post_edit.py"
        shutil.copyfile(str(HOOK), str(orphan))
        self.assertFalse((orphan_dir / CHECKER.name).exists())
        agents = self.write("AGENTS.md", CONFORMING)
        self.assertSilent(self.run_hook(self.payload(agents), hook=orphan))

    def test_unwatched_file_emits_nothing(self):
        self.write("AGENTS.md", CONFORMING)
        readme = self.write("README.md", "# acme-api\n")
        self.assertSilent(self.run_hook(self.payload(readme)))


class TestScope(HookCase):
    def test_nested_package_agents_is_out_of_scope(self):
        # A nested AGENTS.md in a monorepo package is a legitimate pattern the
        # plugin deliberately does not govern.
        self.write("AGENTS.md", CONFORMING)
        nested = self.write("packages/api/AGENTS.md", "## Rules\n\n- a nested rule\n")
        self.assertSilent(self.run_hook(self.payload(nested)))

    def test_nested_package_claude_md_is_out_of_scope(self):
        self.write("AGENTS.md", CONFORMING)
        nested = self.write("packages/api/CLAUDE.md", "@AGENTS.md\n")
        self.assertSilent(self.run_hook(self.payload(nested)))

    def test_dot_claude_claude_md_is_in_scope(self):
        # Claude Code reads a project memory from .claude/CLAUDE.md as well, and
        # there a bare @AGENTS.md resolves to .claude/AGENTS.md and loads
        # nothing.
        self.write("AGENTS.md", CONFORMING)
        claude = self.write(".claude/CLAUDE.md", "@AGENTS.md\n")
        payload = self.assertNeverBlocks(self.run_hook(self.payload(claude)))
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("[FAIL]", context)
        self.assertIn(str(Path(".claude") / "CLAUDE.md"), context)

    def test_claude_project_dir_wins_over_a_drifted_cwd(self):
        # cwd follows Claude: it is whatever directory Claude last cd'd into.
        agents = self.write("AGENTS.md", CONFORMING)
        drifted = self.root / "packages" / "api"
        drifted.mkdir(parents=True)
        result = self.run_hook(self.payload(agents, cwd=drifted))
        payload = self.assertNeverBlocks(result)
        self.assertIn("additionalContext", payload["hookSpecificOutput"])

    def test_without_claude_project_dir_a_drifted_cwd_loses_the_root_pair(self):
        # The contrast that makes the previous test meaningful: with only the
        # payload cwd to go on, the root pair stops being recognized as the
        # root pair.
        agents = self.write("AGENTS.md", CONFORMING)
        drifted = self.root / "packages" / "api"
        drifted.mkdir(parents=True)
        self.assertSilent(
            self.run_hook(self.payload(agents, cwd=drifted), project_dir=None)
        )


class TestDiffScoping(HookCase):
    def test_second_identical_run_emits_nothing(self):
        # Re-emitting the same standing warning on every edit trains the agent
        # to ignore the channel.
        agents = self.write("AGENTS.md", CONFORMING)
        first = self.run_hook(self.payload(agents))
        self.assertNeverBlocks(first)
        second = self.run_hook(self.payload(agents))
        self.assertSilent(second)

    def test_a_newly_introduced_finding_is_emitted(self):
        agents = self.write("AGENTS.md", CONFORMING)
        self.write("CLAUDE.md", "@AGENTS.md\n")
        self.assertSilent(self.run_hook(self.payload(agents)))

        self.write(
            "AGENTS.md",
            CONFORMING
            + "\n## Pointers\n\n- [docs/gone.md](docs/gone.md) — the retry ladder.\n",
        )
        payload = self.assertNeverBlocks(self.run_hook(self.payload(agents)))
        self.assertIn("docs/gone.md", payload["hookSpecificOutput"]["additionalContext"])

    def test_info_severity_findings_are_not_emitted(self):
        # SPECKIT markers with no .specify/ directory is a note, not a warning.
        agents = self.write("AGENTS.md", CONFORMING + SPECKIT_BLOCK)
        self.write("CLAUDE.md", "@AGENTS.md\n")
        result = self.run_hook(self.payload(agents))
        self.assertSilent(result)

    def test_a_clean_pair_emits_nothing(self):
        agents = self.write("AGENTS.md", CONFORMING)
        self.write("CLAUDE.md", "@AGENTS.md\n")
        self.assertSilent(self.run_hook(self.payload(agents)))


class TestHookRegistration(unittest.TestCase):
    """The hook is only reached if hooks.json points at it correctly."""

    def setUp(self) -> None:
        self.config = json.loads(
            (PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
        )

    def test_matcher_covers_the_file_writing_tools(self):
        entries = self.config["hooks"]["PostToolUse"]
        self.assertEqual(len(entries), 1)
        matcher = entries[0]["matcher"]
        self.assertEqual(sorted(matcher.split("|")), ["Edit", "Write"])

    def test_command_points_at_the_hook_script(self):
        hook = self.config["hooks"]["PostToolUse"][0]["hooks"][0]
        self.assertEqual(hook["type"], "command")
        self.assertEqual(hook["command"], "python3")
        self.assertEqual(hook["args"], ["${CLAUDE_PLUGIN_ROOT}/scripts/hook_post_edit.py"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
