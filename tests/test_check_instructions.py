#!/usr/bin/env python3
"""Tests for check_instructions.py. Standard library only, Python 3.8+.

Run:  python3 tests/test_check_instructions.py

Every fixture lives in its own temp directory and is removed in tearDown. No
test reads or writes inside the plugin repository, and no test depends on the
process working directory: a project root is always passed explicitly.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the repository
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_instructions as ci  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

CONFORMING = """\
Acme API owns the public REST surface. Billing lives in `acme-billing`.

## Rules

- Never weaken or delete an existing test to make a change pass.

## Commands

```bash
pnpm test
```
"""


def line_of(text: str, needle: str) -> int:
    """The 1-indexed line of the first line containing ``needle``.

    Expected line numbers are derived from the fixture rather than hard-coded so
    that editing a fixture cannot silently turn a position assertion into a
    tautology or a false failure.
    """
    for i, line in enumerate(text.split("\n"), start=1):
        if needle in line:
            return i
    raise AssertionError("fixture has no line containing %r" % needle)


class Fixture:
    """A throwaway repository on disk.

    ``root`` is a subdirectory of the temp directory so that a test can place a
    file outside the repository -- for the external-import case -- without
    writing anywhere it does not own.
    """

    def __init__(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="ik-test-"))
        self.root = self.base / "repo"
        self.root.mkdir()

    def write(self, rel: str, content: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def write_bytes(self, rel: str, data: bytes) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def write_outside(self, rel: str, content: str) -> Path:
        """Write next to the repository, not inside it."""
        p = self.base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def mkdir(self, rel: str) -> None:
        (self.root / rel).mkdir(parents=True, exist_ok=True)

    def check(self, targets=None) -> ci.Report:
        return ci.run(self.root, targets)

    def codes(self, targets=None) -> set:
        return {f.code for f in self.check(targets).findings}

    def cleanup(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)


def describe(report: ci.Report) -> str:
    if not report.findings:
        return "no findings"
    return "; ".join(
        "%s/%s@%s:%s" % (f.severity, f.code, f.file, f.line) for f in report.findings
    )


class BaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture()

    def tearDown(self) -> None:
        self.fx.cleanup()

    def assertFinding(self, code, severity=None, line=None, file=None,
                      report=None, targets=None) -> ci.Finding:
        """Assert a finding exists, optionally pinning severity, line and file.

        Returns the matching finding so a caller can make further assertions on
        its message or fix text.
        """
        rep = report if report is not None else self.fx.check(targets)
        matches = [f for f in rep.findings if f.code == code]
        self.assertTrue(matches, "expected %s; got %s" % (code, describe(rep)))
        narrowed = matches
        if severity is not None:
            narrowed = [f for f in narrowed if f.severity == severity]
        if line is not None:
            narrowed = [f for f in narrowed if f.line == line]
        if file is not None:
            narrowed = [f for f in narrowed if f.file == file]
        self.assertTrue(
            narrowed,
            "expected %s with severity=%r line=%r file=%r; got %s"
            % (code, severity, line, file,
               ", ".join("%s@%s:%s" % (f.severity, f.file, f.line) for f in matches)),
        )
        return narrowed[0]

    def assertNoCode(self, code: str, targets=None) -> None:
        rep = self.fx.check(targets)
        self.assertNotIn(
            code, {f.code for f in rep.findings},
            "did not expect %s; got %s" % (code, describe(rep)),
        )

    def assertNoFailures(self, report=None, targets=None) -> None:
        rep = report if report is not None else self.fx.check(targets)
        fails = [f for f in rep.findings if f.severity == "fail"]
        self.assertEqual(
            fails, [],
            "unexpected failures: "
            + "; ".join("%s@%s:%s %s" % (f.code, f.file, f.line, f.message) for f in fails),
        )


class AgentsCase(BaseCase):
    """A base for tests that write the root pair with a conforming stub."""

    def _agents(self, body: str) -> None:
        self.fx.write("AGENTS.md", body)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")


# --------------------------------------------------------------------------
# The AGENTS.md / CLAUDE.md pair contract
# --------------------------------------------------------------------------


class TestFilePair(BaseCase):
    def test_conforming_pair_is_clean(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        self.assertEqual(self.fx.check().findings, [])

    def test_missing_both(self):
        self.assertFinding("PAIR_MISSING", severity="warn", file="AGENTS.md")

    def test_agents_without_claude(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.assertFinding("PAIR_NO_CLAUDE", severity="warn", file="CLAUDE.md")

    def test_claude_without_agents_warns_without_failing(self):
        self.fx.write("CLAUDE.md", CONFORMING)
        self.assertFinding("PAIR_NO_AGENTS", severity="warn")
        self.assertNoCode("CLAUDE_NO_IMPORT")

    def test_claude_missing_import(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "Use plan mode.\n")
        self.assertFinding("CLAUDE_NO_IMPORT", severity="fail", file="CLAUDE.md")

    def test_claude_duplicates_agents(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", CONFORMING)
        self.assertFinding("CLAUDE_DUPLICATES_AGENTS", severity="fail")

    def test_stub_repeating_one_shared_line_is_not_a_copy(self):
        # The stub cap plus a real import is the contract. This fixture repeats
        # one AGENTS.md line verbatim and adds one line of its own, so the
        # overlap ratio is 0.5 and only the is_stub guard keeps the finding off.
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write(
            "CLAUDE.md",
            "@AGENTS.md\n\n## Claude Code\n\n"
            "- Never weaken or delete an existing test to make a change pass.\n"
            "Use plan mode for any change under `src/billing/` before editing.\n",
        )
        self.assertNoCode("CLAUDE_DUPLICATES_AGENTS")
        self.assertNoCode("CLAUDE_NO_IMPORT")

    def test_stub_guard_is_what_suppresses_the_duplication_finding(self):
        # Same overlap, but past the stub cap: the finding must fire, proving the
        # test above is guarded by is_stub rather than by an empty intersection.
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write(
            "CLAUDE.md",
            "@AGENTS.md\n\n## Claude Code\n\n"
            "- Never weaken or delete an existing test to make a change pass.\n"
            "Use plan mode for any change under `src/billing/` before editing.\n"
            # Short lines: they push the file past the stub cap without
            # entering the >20-character sets the overlap ratio is built from.
            + "\n".join("- note %d" % i for i in range(12))
            + "\n",
        )
        self.assertFinding("CLAUDE_DUPLICATES_AGENTS", severity="fail")

    def test_claude_too_long(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n" + "\n".join("- line %d" % i for i in range(25)))
        self.assertFinding("CLAUDE_TOO_LONG", severity="fail")

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlink_claude_is_accepted(self):
        self.fx.write("AGENTS.md", CONFORMING)
        (self.fx.root / "CLAUDE.md").symlink_to(self.fx.root / "AGENTS.md")
        self.assertNoCode("CLAUDE_NO_IMPORT")
        self.assertNoCode("CLAUDE_DUPLICATES_AGENTS")

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_dangling_claude_symlink_is_named_by_the_link(self):
        # The reader has to open CLAUDE.md to fix it; naming the target would
        # name a path that does not exist.
        self.fx.write("AGENTS.md", CONFORMING)
        (self.fx.root / "CLAUDE.md").symlink_to(self.fx.root / "nowhere.md")
        finding = self.assertFinding(
            "CLAUDE_BROKEN_SYMLINK", severity="fail", file="CLAUDE.md"
        )
        self.assertNotIn("nowhere.md", finding.file)

    def test_import_in_backticks_does_not_count(self):
        # Claude Code's import parser skips code spans; so must this one.
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "Write `@AGENTS.md` to import it.\n")
        self.assertFinding("CLAUDE_NO_IMPORT", severity="fail")

    def test_import_inside_an_html_comment_does_not_satisfy_the_stub(self):
        # Comments are stripped before imports are expanded, so a commented
        # import loads nothing.
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "<!-- @AGENTS.md -->\nUse plan mode.\n")
        self.assertFinding("CLAUDE_NO_IMPORT", severity="fail")

    def test_import_inside_an_html_comment_is_not_followed(self):
        self.fx.write("AGENTS.md", "<!-- @big.md -->\n\n" + CONFORMING)
        self.fx.write("big.md", "\n".join("- line %d" % i for i in range(300)))
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        rep = self.fx.check()
        self.assertNoFailures(rep)
        self.assertNotIn("SIZE_WARN", {f.code for f in rep.findings})
        self.assertNotIn("big.md", rep.metrics["closure_files"])

    def test_utf8_bom_before_the_import(self):
        # "UTF-8 with BOM" is a common editor default; the mark must not sit in
        # front of the import and stop it from matching.
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write_bytes("CLAUDE.md", b"\xef\xbb\xbf@AGENTS.md\n")
        self.assertNoCode("CLAUDE_NO_IMPORT")
        self.assertEqual(self.fx.check().findings, [])


class TestClaudeMdInDotClaude(BaseCase):
    """.claude/CLAUDE.md is the other place Claude Code reads a project memory."""

    def test_dot_claude_location_is_recognized(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write(".claude/CLAUDE.md", "@../AGENTS.md\n")
        self.assertNoCode("PAIR_NO_CLAUDE")
        self.assertNoCode("CLAUDE_NO_IMPORT")

    def test_dot_claude_bare_import_points_at_the_wrong_file(self):
        # An import resolves relative to the file holding it, so `@AGENTS.md`
        # inside .claude/ names .claude/AGENTS.md and loads nothing.
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write(".claude/CLAUDE.md", "@AGENTS.md\n")
        finding = self.assertFinding(
            "CLAUDE_NO_IMPORT", severity="fail",
            file=str(Path(".claude") / "CLAUDE.md"),
        )
        self.assertIn("@../AGENTS.md", finding.fix)

    def test_dot_claude_relative_import_is_accepted(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write(".claude/CLAUDE.md", "@../AGENTS.md\n")
        rep = self.fx.check()
        self.assertNoFailures(rep)
        self.assertEqual(
            rep.metrics["closure_files"],
            ["AGENTS.md", str(Path(".claude") / "CLAUDE.md")],
        )


# --------------------------------------------------------------------------
# Size budget over the import closure
# --------------------------------------------------------------------------


class TestSize(BaseCase):
    def _many_rules(self, n: int) -> str:
        return "## Rules\n\n" + "\n".join("- rule %d" % i for i in range(n)) + "\n"

    def _repo_of_lines(self, total: int) -> None:
        """A pair whose resolved closure is exactly ``total`` lines.

        One line goes to the CLAUDE.md stub and one to the `## Rules` heading;
        the rest are bullets.
        """
        bullets = total - 2
        self.fx.write(
            "AGENTS.md",
            "## Rules\n" + "\n".join("- rule %d" % i for i in range(bullets)) + "\n",
        )
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        self.assertEqual(self.fx.check().metrics["resolved_lines"], total)

    def test_warn_threshold(self):
        self.fx.write("AGENTS.md", self._many_rules(205))
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        self.assertFinding("SIZE_WARN", severity="warn", file="AGENTS.md")
        self.assertNoCode("SIZE_FAIL")

    def test_fail_threshold(self):
        self.fx.write("AGENTS.md", self._many_rules(405))
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        self.assertFinding("SIZE_FAIL", severity="fail", file="AGENTS.md")

    def test_at_target_is_silent_and_one_over_is_a_note(self):
        self._repo_of_lines(ci.AGENTS_TARGET_LINES)
        self.assertNoCode("SIZE_OVER_TARGET")
        self._repo_of_lines(ci.AGENTS_TARGET_LINES + 1)
        self.assertFinding("SIZE_OVER_TARGET", severity="info")

    def test_at_warn_threshold_is_still_a_note_and_one_over_warns(self):
        self._repo_of_lines(ci.AGENTS_WARN_LINES)
        self.assertFinding("SIZE_OVER_TARGET", severity="info")
        self.assertNoCode("SIZE_WARN")
        self._repo_of_lines(ci.AGENTS_WARN_LINES + 1)
        self.assertFinding("SIZE_WARN", severity="warn")

    def test_at_fail_threshold_still_warns_and_one_over_fails(self):
        self._repo_of_lines(ci.AGENTS_FAIL_LINES)
        self.assertFinding("SIZE_WARN", severity="warn")
        self.assertNoCode("SIZE_FAIL")
        self._repo_of_lines(ci.AGENTS_FAIL_LINES + 1)
        self.assertFinding("SIZE_FAIL", severity="fail")

    def test_html_comments_do_not_count(self):
        comment = "<!--\n" + "\n".join("note %d" % i for i in range(300)) + "\n-->\n"
        self.fx.write("AGENTS.md", comment + CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        self.assertNoCode("SIZE_WARN")
        self.assertNoCode("SIZE_FAIL")
        self.assertNoCode("PREAMBLE_TOO_LONG")

    def test_import_closure_is_summed(self):
        # Imports load at launch, so hiding bulk behind one does not shrink it.
        self.fx.write("AGENTS.md", "@big.md\n\n" + CONFORMING)
        self.fx.write("big.md", "\n".join("- line %d" % i for i in range(250)))
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        self.assertFinding("SIZE_WARN", severity="warn")

    def test_claude_import_closure_counts_toward_the_budget(self):
        # A stub short in itself can still pull in an arbitrarily large file.
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n@notes.md\n")
        self.fx.write("notes.md", "\n".join("- note %d" % i for i in range(250)))
        rep = self.fx.check()
        self.assertFinding("SIZE_WARN", severity="warn", report=rep)
        self.assertIn("notes.md", rep.metrics["closure_files"])

    def test_union_is_deduplicated(self):
        agents = "## Rules\n\n- a rule\n\n## Commands\n\n```sh\nmake\n```\n"
        self.fx.write("AGENTS.md", agents)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        rep = self.fx.check()
        self.assertEqual(rep.metrics["closure_files"], ["AGENTS.md", "CLAUDE.md"])
        self.assertEqual(
            rep.metrics["resolved_lines"], len(agents.splitlines()) + 1
        )

    def test_import_cycle_terminates(self):
        self.fx.write("AGENTS.md", "@b.md\n\n" + CONFORMING)
        self.fx.write("b.md", "@AGENTS.md\n")
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        rep = self.fx.check()
        self.assertEqual(rep.metrics["closure_files"], ["AGENTS.md", "b.md", "CLAUDE.md"])

    def test_import_depth_stops_at_max_hops(self):
        chain = ["a%d.md" % n for n in range(1, 6)]
        self.fx.write("AGENTS.md", "@a1.md\n\n" + CONFORMING)
        for n, name in enumerate(chain):
            nxt = chain[n + 1] if n + 1 < len(chain) else None
            self.fx.write(name, ("@%s\n" % nxt) if nxt else "- leaf\n")
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        files = self.fx.check().metrics["closure_files"]
        self.assertEqual(
            files, ["AGENTS.md", "a1.md", "a2.md", "a3.md", "a4.md", "CLAUDE.md"]
        )
        self.assertNotIn("a5.md", files)

    def test_missing_import_target_is_reported(self):
        self.fx.write("AGENTS.md", "@gone.md\n\n" + CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        finding = self.assertFinding("IMPORT_MISSING", severity="warn", file="AGENTS.md")
        self.assertIn("gone.md", finding.message)

    def test_external_import_is_noted(self):
        outside = self.fx.write_outside("shared.md", "- a shared rule\n")
        self.fx.write("AGENTS.md", "@../%s\n\n" % outside.name + CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        self.assertFinding("IMPORT_EXTERNAL", severity="info", file="AGENTS.md")

    def test_metrics_are_present_on_a_clean_run(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        rep = self.fx.check()
        self.assertEqual(rep.findings, [])
        for key in ("resolved_lines", "resolved_bytes", "raw_bytes", "closure_files"):
            self.assertIn(key, rep.metrics)
        self.assertIsNotNone(ci.budget_line(rep))


# --------------------------------------------------------------------------
# Standard parameters
# --------------------------------------------------------------------------


class TestThresholdConstants(unittest.TestCase):
    """The budget numbers are the standard. Changing one is a change to the
    documented contract, so it must not pass silently."""

    def test_size_thresholds(self):
        self.assertEqual(ci.AGENTS_TARGET_LINES, 120)
        self.assertEqual(ci.AGENTS_WARN_LINES, 200)
        self.assertEqual(ci.AGENTS_FAIL_LINES, 400)

    def test_claude_stub_thresholds(self):
        self.assertEqual(ci.CLAUDE_STUB_WARN_LINES, 10)
        self.assertEqual(ci.CLAUDE_STUB_FAIL_LINES, 20)

    def test_preamble_and_import_depth(self):
        self.assertEqual(ci.PREAMBLE_WARN_LINES, 2)
        self.assertEqual(ci.MAX_IMPORT_HOPS, 4)

    def test_section_caps_and_order(self):
        self.assertEqual(
            ci.SECTION_CAPS,
            {"Rules": 40, "Commands": 25, "Boundaries": 15, "Contributing": 20,
             "Pointers": 10},
        )
        self.assertEqual(
            ci.SECTION_ORDER,
            ["Rules", "Commands", "Boundaries", "Contributing", "Pointers"],
        )


class TestCapBoundaries(AgentsCase):
    def _section(self, canonical: str, n: int) -> None:
        body = "\n".join("- line %d" % i for i in range(n))
        self._agents("## %s\n\n%s\n" % (canonical, body))

    def test_exactly_at_cap_is_silent(self):
        for canonical, cap in sorted(ci.SECTION_CAPS.items()):
            with self.subTest(section=canonical):
                self._section(canonical, cap)
                self.assertNoCode("SECTION_CAP_WARN")
                self.assertNoCode("SECTION_CAP_FAIL")

    def test_one_over_cap_warns(self):
        for canonical, cap in sorted(ci.SECTION_CAPS.items()):
            with self.subTest(section=canonical):
                self._section(canonical, cap + 1)
                self.assertFinding("SECTION_CAP_WARN", severity="warn", line=1)

    def test_double_the_cap_still_warns(self):
        for canonical, cap in sorted(ci.SECTION_CAPS.items()):
            with self.subTest(section=canonical):
                self._section(canonical, cap * 2)
                self.assertFinding("SECTION_CAP_WARN", severity="warn")
                self.assertNoCode("SECTION_CAP_FAIL")

    def test_past_double_the_cap_fails(self):
        for canonical, cap in sorted(ci.SECTION_CAPS.items()):
            with self.subTest(section=canonical):
                self._section(canonical, cap * 2 + 1)
                self.assertFinding("SECTION_CAP_FAIL", severity="fail")

    def test_preamble_at_cap_is_silent_and_one_over_warns(self):
        self._agents("one\ntwo\n\n" + CONFORMING.split("\n", 2)[2])
        self.assertNoCode("PREAMBLE_TOO_LONG")
        self._agents("one\ntwo\nthree\n\n" + CONFORMING.split("\n", 2)[2])
        self.assertFinding("PREAMBLE_TOO_LONG", severity="warn", line=1)

    def test_claude_stub_boundaries(self):
        self.fx.write("AGENTS.md", CONFORMING)
        body = ["@AGENTS.md"] + ["- note %d" % i for i in range(ci.CLAUDE_STUB_WARN_LINES - 1)]
        self.fx.write("CLAUDE.md", "\n".join(body) + "\n")
        self.assertNoCode("CLAUDE_GROWING")

        self.fx.write("CLAUDE.md", "\n".join(body + ["- one more note"]) + "\n")
        self.assertFinding("CLAUDE_GROWING", severity="warn")
        self.assertNoCode("CLAUDE_TOO_LONG")

        at_fail = ["@AGENTS.md"] + ["- note %d" % i for i in range(ci.CLAUDE_STUB_FAIL_LINES - 1)]
        self.fx.write("CLAUDE.md", "\n".join(at_fail) + "\n")
        self.assertFinding("CLAUDE_GROWING", severity="warn")
        self.assertNoCode("CLAUDE_TOO_LONG")

        self.fx.write("CLAUDE.md", "\n".join(at_fail + ["- one more note"]) + "\n")
        self.assertFinding("CLAUDE_TOO_LONG", severity="fail")


# --------------------------------------------------------------------------
# Section parsing
# --------------------------------------------------------------------------


class TestSections(AgentsCase):
    def test_title_heading_is_not_a_section(self):
        self._agents("# acme-api\n\n" + CONFORMING)
        self.assertNoCode("UNKNOWN_SECTION")
        self.assertNoCode("MISSING_RULES")

    def test_all_h1_sections_are_parsed(self):
        self._agents("# Rules\n\n- a rule\n\n# Commands\n\n```sh\nmake\n```\n")
        self.assertNoCode("MISSING_RULES")
        self.assertNoCode("MISSING_COMMANDS")

    def test_stray_h1_below_h2_sections_does_not_hide_them(self):
        # The section level is the level of the heading that opens the run, not
        # the shallowest level anywhere in the file.
        self._agents(CONFORMING + "\n# Appendix\n\nleftover prose\n")
        self.assertNoCode("MISSING_RULES")
        self.assertNoCode("MISSING_COMMANDS")

    def test_title_plus_a_trailing_h1_still_leaves_the_sections_visible(self):
        self._agents("# acme-api\n\n" + CONFORMING + "\n# Appendix\n\nleftover prose\n")
        self.assertNoCode("MISSING_RULES")
        self.assertNoCode("MISSING_COMMANDS")

    def test_setext_headings_naming_known_sections_are_recognized(self):
        body = "Rules\n-----\n\n- a rule\n\nCommands\n--------\n\n```sh\nmake\n```\n"
        self._agents(body)
        # Assert the sections themselves, not only the absence of MISSING_*:
        # an unparsed file this short is classified as a pointer file, which
        # suppresses MISSING_* and would make a negative assertion vacuous.
        doc = ci.parse(self.fx.root / "AGENTS.md", body, self.fx.root)
        self.assertEqual([s.canonical for s in doc.sections], ["Rules", "Commands"])
        self.assertFalse(doc.is_pointer)
        self.assertNoCode("POINTER_FILE")
        self.assertNoCode("MISSING_RULES")
        self.assertNoCode("MISSING_COMMANDS")

    def test_a_thematic_break_is_not_read_as_a_setext_heading(self):
        # A bare `---` under a paragraph is far more often a thematic break;
        # guessing produced false MISSING_RULES findings.
        body = CONFORMING + "\nSome closing prose.\n---\n"
        doc = ci.parse(self.fx.root / "AGENTS.md", body, self.fx.root)
        self.assertEqual([s.canonical for s in doc.sections], ["Rules", "Commands"])

    def test_order_violation(self):
        self._agents("## Commands\n\n```sh\nmake\n```\n\n## Rules\n\n- a rule\n")
        self.assertFinding("SECTION_ORDER", severity="warn")

    def test_synonym_maps_and_suggests_rename(self):
        body = (
            "## Rules\n\n- a\n\n## Commands\n\n```sh\nmake\n```\n\n"
            "## Architecture\n\n`a/` may not import `b/`.\n"
        )
        self._agents(body)
        self.assertFinding(
            "SECTION_RENAME", severity="info", line=line_of(body, "## Architecture")
        )
        self.assertNoCode("UNKNOWN_SECTION")

    def test_split_headings_are_flagged(self):
        for heading, code in [
            ("Testing", "SPLIT_TESTING"),
            ("Code Style", "SPLIT_STYLE"),
            ("Setup", "SPLIT_SETUP"),
            ("Project Structure", "SPLIT_STRUCTURE"),
            ("Project Overview", "SPLIT_OVERVIEW"),
            ("Troubleshooting", "SPLIT_TROUBLESHOOTING"),
        ]:
            with self.subTest(heading=heading):
                body = CONFORMING + "\n## %s\n\nsomething\n" % heading
                self._agents(body)
                self.assertFinding(
                    code, severity="warn", line=line_of(body, "## %s" % heading)
                )

    def test_section_cap(self):
        self._agents("## Rules\n\n" + "\n".join("- rule %d" % i for i in range(45)))
        self.assertFinding("SECTION_CAP_WARN", severity="warn")

    def test_section_cap_fail_at_double(self):
        self._agents("## Rules\n\n" + "\n".join("- rule %d" % i for i in range(85)))
        self.assertFinding("SECTION_CAP_FAIL", severity="fail")

    def test_commands_cap_counts_fenced_lines(self):
        # A 30-line fenced block occupies an always-loaded file exactly as much
        # as 30 bullets do.
        block = "\n".join("pnpm run task-%d" % i for i in range(30))
        self._agents("## Rules\n\n- a rule\n\n## Commands\n\n```sh\n%s\n```\n" % block)
        self.assertFinding("SECTION_CAP_WARN", severity="warn")
        self.assertNoCode("COMMANDS_NO_FENCE")

    def test_preamble_cap(self):
        self._agents("one\ntwo\nthree\nfour\n\n" + CONFORMING)
        self.assertFinding("PREAMBLE_TOO_LONG", severity="warn", line=1)

    def test_duplicate_section(self):
        body = "## Rules\n\n- a\n\n## Rules\n\n- b\n"
        self._agents(body)
        self.assertFinding("DUPLICATE_SECTION", severity="warn", line=5)

    def test_pointer_file_skips_structure(self):
        self._agents("See CONTRIBUTING.md.\n")
        self.assertFinding("POINTER_FILE", severity="info")
        self.assertNoCode("MISSING_RULES")

    def test_empty_file_is_not_a_pointer_file(self):
        # A pointer file redirects somewhere. An empty or placeholder AGENTS.md
        # points nowhere, and classifying it as a pointer would suppress every
        # structural check on the file most in need of them.
        self._agents("")
        self.assertNoCode("POINTER_FILE")
        self.assertFinding("MISSING_RULES", severity="warn", file="AGENTS.md")
        self.assertFinding("MISSING_COMMANDS", severity="warn", file="AGENTS.md")

    def test_placeholder_file_is_not_a_pointer_file(self):
        self._agents("TODO: write this.\n")
        self.assertNoCode("POINTER_FILE")
        self.assertFinding("MISSING_RULES", severity="warn", file="AGENTS.md")


# --------------------------------------------------------------------------
# Malformed markup
# --------------------------------------------------------------------------


class TestMalformedMarkup(AgentsCase):
    def test_unterminated_comment_is_reported_and_does_not_swallow_the_file(self):
        # Claude Code keeps an unterminated comment verbatim, so everything
        # below the opener still loads and must still be parsed and counted.
        agents = (
            "## Rules\n"
            "\n"
            "- a rule\n"
            "\n"
            "<!-- an incident note that never closes\n"
            "\n"
            "## Commands\n"
            "\n"
            "```sh\n"
            "make\n"
            "```\n"
        )
        self._agents(agents)
        self.assertFinding(
            "HTML_COMMENT_UNCLOSED", severity="fail", file="AGENTS.md",
            line=line_of(agents, "never closes"),
        )
        self.assertNoCode("MISSING_COMMANDS")
        self.assertNoCode("MISSING_RULES")
        self.assertEqual(
            self.fx.check().metrics["resolved_lines"],
            len(agents.splitlines()) + 1,
        )

    def test_closed_comment_does_not_delete_the_rest_of_its_line(self):
        agents = (
            CONFORMING
            + "\n## Pointers\n\n"
            + "<!-- added after the 2024-03 incident --> - [docs/gone.md](docs/gone.md)"
            " — the retry ladder; read before touching the dispatcher.\n"
        )
        self._agents(agents)
        self.assertFinding(
            "STALE_PATH", severity="warn", line=line_of(agents, "docs/gone.md")
        )

    def test_closed_comment_remainder_survives_stripping(self):
        text = "<!-- note --> - a surviving rule\n"
        stripped, removed = ci.strip_block_html_comments(text)
        self.assertIn("a surviving rule", stripped)
        self.assertEqual(removed, 0)

    def test_unterminated_fence_is_reported(self):
        agents = "## Rules\n\n- a rule\n\n## Commands\n\n```sh\nmake\n"
        self._agents(agents)
        self.assertFinding(
            "FENCE_UNCLOSED", severity="fail", file="AGENTS.md",
            line=line_of(agents, "```sh"),
        )

    def test_a_longer_fence_is_not_closed_by_a_shorter_nested_run(self):
        scan = ci.scan_fences("````\n```\ninner\n```\n````\n")
        self.assertIsNone(scan.unclosed)
        self.assertEqual(scan.opens, {0})

    def test_nested_fence_in_commands_is_not_unclosed(self):
        self._agents(
            "## Rules\n\n- a rule\n\n## Commands\n\n"
            "````markdown\n```sh\nmake\n```\n````\n"
        )
        self.assertNoCode("FENCE_UNCLOSED")

    def test_quoted_diagram_fence_in_boundaries_is_not_a_diagram(self):
        # Only a fence the section itself opens counts; a ```mermaid line nested
        # inside an outer example fence is quoted text.
        self._agents(
            CONFORMING
            + "\n## Boundaries\n\n````markdown\n```mermaid\ngraph TD; A-->B;\n```\n````\n"
        )
        self.assertNoCode("BOUNDARIES_DIAGRAM")


# --------------------------------------------------------------------------
# Content heuristics
# --------------------------------------------------------------------------


class TestContentHeuristics(AgentsCase):
    def test_boundaries_rejects_diagram(self):
        body = CONFORMING + "\n## Boundaries\n\n```mermaid\ngraph TD; A-->B;\n```\n"
        self._agents(body)
        self.assertFinding(
            "BOUNDARIES_DIAGRAM", severity="fail", line=line_of(body, "```mermaid")
        )

    def test_boundaries_rejects_directory_tree(self):
        self._agents(CONFORMING + "\n## Boundaries\n\nsrc/\n├── api/\n└── db/\n")
        self.assertFinding("BOUNDARIES_TREE", severity="fail")

    def test_boundaries_rejects_image(self):
        self._agents(
            CONFORMING + "\n## Boundaries\n\n![layers](docs/layers.png) shows the layers.\n"
        )
        self.assertFinding("BOUNDARIES_IMAGE", severity="fail")

    def test_contributing_rejects_procedure(self):
        self._agents(
            CONFORMING + "\n## Contributing\n\n1. Branch\n2. Commit\n3. Push\n4. Open a PR\n"
        )
        self.assertFinding("CONTRIBUTING_PROCEDURE", severity="warn")

    def test_contributing_accepts_three_facts(self):
        # Branch naming, PR title format and who merges are commonly three
        # items; the threshold sits above three to leave them alone.
        self._agents(
            CONFORMING
            + "\n## Contributing\n\n"
            "1. Branch from main as `feat/<ticket>`.\n"
            "2. PR titles follow Conventional Commits.\n"
            "3. A human merges; the agent never pushes to main.\n"
        )
        self.assertNoCode("CONTRIBUTING_PROCEDURE")

    def test_blind_reference(self):
        self.fx.write("docs/a.md", "x")
        body = CONFORMING + "\n## Pointers\n\n- [Docs](docs/a.md)\n"
        self._agents(body)
        self.assertFinding(
            "BLIND_REFERENCE", severity="warn", line=line_of(body, "[Docs]")
        )

    def test_pointer_with_purpose_clause_is_accepted(self):
        self.fx.write("docs/a.md", "x")
        self._agents(
            CONFORMING
            + "\n## Pointers\n\n- [docs/a.md](docs/a.md) — retry ladder and payload "
              "versions; read before touching the dispatcher.\n"
        )
        self.assertNoCode("BLIND_REFERENCE")

    def test_short_purpose_clause_is_accepted_and_a_bare_link_is_still_caught(self):
        # A purpose clause is prose, not a word count: a threshold rejects short
        # but complete clauses and is satisfied by padding.
        self.fx.write("docs/a.md", "x")
        self.fx.write("docs/b.md", "x")
        body = (
            CONFORMING
            + "\n## Pointers\n\n"
            "- [docs/a.md](docs/a.md) — retry ladder internals.\n"
            "- [docs/b.md](docs/b.md)\n"
        )
        self._agents(body)
        finding = self.assertFinding(
            "BLIND_REFERENCE", severity="warn", line=line_of(body, "docs/b.md](")
        )
        self.assertIn("docs/b.md", finding.message)
        self.assertEqual(
            1, sum(1 for f in self.fx.check().findings if f.code == "BLIND_REFERENCE")
        )

    def test_stale_path(self):
        body = (
            CONFORMING
            + "\n## Pointers\n\n- [docs/gone.md](docs/gone.md) — a page that no longer "
              "exists anywhere.\n"
        )
        self._agents(body)
        self.assertFinding(
            "STALE_PATH", severity="warn", line=line_of(body, "docs/gone.md")
        )

    def test_urls_are_not_treated_as_paths(self):
        self._agents(
            CONFORMING
            + "\n## Pointers\n\n- [the spec](https://agents.md/) — the AGENTS.md "
              "format, when adding a section.\n"
        )
        self.assertNoCode("STALE_PATH")

    def test_dotfile_paths_that_exist_resolve(self):
        # Stripping "./" as a character set used to eat the leading dot of
        # .claude/ and .github/. The missing third path is the control that
        # proves the section really was scanned.
        self.fx.write(".claude/rules/api.md", "x")
        self.fx.write(".github/PULL_REQUEST_TEMPLATE.md", "x")
        body = (
            CONFORMING
            + "\n## Pointers\n\n"
            "- [.claude/rules/api.md](./.claude/rules/api.md) — path-scoped rules "
            "for the API layer.\n"
            "- [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) "
            "— the checklist reviewers expect.\n"
            "- [.github/gone.md](.github/gone.md) — deleted last quarter.\n"
        )
        self._agents(body)
        stale = [f for f in self.fx.check().findings if f.code == "STALE_PATH"]
        self.assertEqual([f.message for f in stale], ["`.github/gone.md` does not exist."])

    def test_mailto_routes_and_branch_names_are_not_paths(self):
        # The fourth bullet is a real stale path: without it, a section that was
        # never scanned would satisfy this test.
        body = (
            CONFORMING
            + "\n## Pointers\n\n"
            "- [security@example.com](mailto:security@example.com) — report "
            "vulnerabilities here, never in an issue.\n"
            "- The public route is `/api/v1/users`; read the handler before "
            "changing its shape.\n"
            "- Release branches are named `release/1.2` and are cut from main.\n"
            "- [docs/gone.md](docs/gone.md) — deleted last quarter.\n"
        )
        self._agents(body)
        stale = [f for f in self.fx.check().findings if f.code == "STALE_PATH"]
        self.assertEqual([f.message for f in stale], ["`docs/gone.md` does not exist."])

    def test_relative_paths_resolve_against_the_file_being_checked(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        self.fx.write("rootonly.md", "x")
        self.fx.write("pkg/local.md", "x")
        nested = (
            CONFORMING
            + "\n## Pointers\n\n"
            "- [local.md](local.md) — the package's own notes; read before editing it.\n"
            "- [rootonly.md](rootonly.md) — lives at the repository root only.\n"
        )
        self.fx.write("pkg/AGENTS.md", nested)
        targets = [self.fx.root / "pkg" / "AGENTS.md"]
        rep = self.fx.check(targets)
        stale = [f for f in rep.findings if f.code == "STALE_PATH"]
        self.assertEqual(
            [f.message for f in stale], ["`rootonly.md` does not exist."],
            describe(rep),
        )
        self.assertEqual(stale[0].line, line_of(nested, "[rootonly.md]"))

    def test_lint_leakage_requires_a_formatter_config(self):
        rules = (
            "## Rules\n\n- Use 2-space indentation and single quotes.\n\n"
            "## Commands\n\n```sh\nmake\n```\n"
        )
        self._agents(rules)
        self.assertNoCode("LINT_LEAKAGE")
        self.fx.write(".prettierrc", "{}")
        self.assertFinding("LINT_LEAKAGE", severity="warn", line=1)

    def test_lint_leakage_ignores_ordinary_english(self):
        # "spaces" and "tab" are ordinary words; only a width or a formatting
        # verb makes them evidence.
        self.fx.write(".prettierrc", "{}")
        prose = (
            "## Rules\n\n"
            "- Keep tab completion working in the CLI shim.\n"
            "- Deploy to staging spaces before production.\n"
        )
        tail = "\n## Commands\n\n```sh\nmake\n```\n"
        self._agents(prose + tail)
        self.assertNoCode("LINT_LEAKAGE")
        # The same section with a real width rule still fires, which proves the
        # keyword scan was live rather than skipped.
        self._agents(prose + "- Indent with 4 spaces.\n" + tail)
        self.assertFinding("LINT_LEAKAGE", severity="warn")

    def test_commands_without_a_fence(self):
        self._agents("## Rules\n\n- a\n\n## Commands\n\nRun the tests with pnpm.\n")
        self.assertFinding("COMMANDS_NO_FENCE", severity="warn", line=5)

    def test_emphasis_inflation(self):
        self._agents(CONFORMING + "\nMUST NEVER ALWAYS IMPORTANT CRITICAL REQUIRED MUST\n")
        self.assertFinding("EMPHASIS_INFLATION", severity="warn")

    def test_emphasis_inside_a_fence_is_not_counted(self):
        self._agents(
            "## Rules\n\n- a rule\n\n## Commands\n\n```sh\n"
            "echo MUST NEVER ALWAYS IMPORTANT CRITICAL REQUIRED MUST\n```\n"
        )
        self.assertNoCode("EMPHASIS_INFLATION")

    def test_emphasis_inside_the_speckit_block_is_not_counted(self):
        self.fx.mkdir(".specify")
        self._agents(
            CONFORMING
            + "\n<!-- SPECKIT START -->\n"
            "MUST NEVER ALWAYS IMPORTANT CRITICAL REQUIRED MUST\n"
            "<!-- SPECKIT END -->\n"
        )
        self.assertNoCode("EMPHASIS_INFLATION")
        self.assertFinding("SPECKIT_PROTECTED", severity="info")


# --------------------------------------------------------------------------
# Spec Kit interop
# --------------------------------------------------------------------------


class TestSpecKit(AgentsCase):
    BLOCK = (
        "\n<!-- SPECKIT START -->\n"
        "Read the current plan at specs/001/plan.md\n"
        "<!-- SPECKIT END -->\n"
    )

    def test_protected_when_specify_exists(self):
        self.fx.mkdir(".specify")
        self._agents(CONFORMING + self.BLOCK)
        self.assertFinding("SPECKIT_PROTECTED", severity="info")
        self.assertNoCode("UNKNOWN_SECTION")

    def test_orphan_markers_without_specify(self):
        self._agents(CONFORMING + self.BLOCK)
        self.assertFinding("SPECKIT_ORPHAN", severity="info")

    def test_unbalanced_markers_fail(self):
        self.fx.mkdir(".specify")
        self._agents(CONFORMING + "\n<!-- SPECKIT START -->\ncontent\n")
        self.assertFinding("SPECKIT_UNBALANCED", severity="fail")

    def test_reversed_markers_fail(self):
        self.fx.mkdir(".specify")
        self._agents(
            CONFORMING
            + "\n<!-- SPECKIT END -->\ncontent\n<!-- SPECKIT START -->\n"
        )
        self.assertFinding("SPECKIT_REVERSED", severity="fail")
        self.assertNoCode("SPECKIT_UNBALANCED")

    def test_block_not_last(self):
        self.fx.mkdir(".specify")
        self._agents(
            CONFORMING + self.BLOCK
            + "\n## Pointers\n\n- something trailing here for the check\n"
        )
        self.assertFinding("SPECKIT_NOT_LAST", severity="info")

    def test_absent_block_in_a_speckit_repository_is_a_note(self):
        self.fx.mkdir(".specify")
        self._agents(CONFORMING)
        self.assertFinding("SPECKIT_ABSENT", severity="info")

    def test_markers_quoted_in_a_code_span_are_not_markers(self):
        self._agents(
            CONFORMING
            + "\n## Pointers\n\n- Spec Kit owns the region between "
              "`<!-- SPECKIT START -->` and `<!-- SPECKIT END -->`; never edit inside it.\n"
        )
        codes = self.fx.codes()
        self.assertEqual(
            [c for c in sorted(codes) if c.startswith("SPECKIT")], [], sorted(codes)
        )

    def test_markers_quoted_in_a_fence_are_not_markers(self):
        self._agents(
            CONFORMING
            + "\n## Commands\n\n```markdown\n<!-- SPECKIT START -->\n"
              "managed\n<!-- SPECKIT END -->\n```\n"
        )
        codes = self.fx.codes()
        self.assertEqual(
            [c for c in sorted(codes) if c.startswith("SPECKIT")], [], sorted(codes)
        )

    def test_custom_markers_from_the_extension_config_are_honoured(self):
        self.fx.write(
            ".specify/extensions/agent-context/agent-context-config.yml",
            "markers:\n"
            '  start: "<!-- AGENT CONTEXT START -->"\n'
            '  end: "<!-- AGENT CONTEXT END -->"\n',
        )
        self._agents(
            CONFORMING
            + "\n<!-- AGENT CONTEXT START -->\n"
              "## Active Technologies\n\nTypeScript, Postgres\n"
              "<!-- AGENT CONTEXT END -->\n"
        )
        self.assertFinding("SPECKIT_PROTECTED", severity="info")
        self.assertNoCode("SPLIT_OVERVIEW")
        self.assertNoCode("SPECKIT_UNBALANCED")

    def test_default_markers_are_used_when_no_config_exists(self):
        self.fx.mkdir(".specify")
        self.assertEqual(
            ci.speckit_markers(self.fx.root),
            (ci.DEFAULT_SPECKIT_START, ci.DEFAULT_SPECKIT_END),
        )


# --------------------------------------------------------------------------
# Explicit targets
# --------------------------------------------------------------------------


class TestTargets(BaseCase):
    def test_missing_target_is_reported(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        targets = [self.fx.root / "nope.md"]
        self.assertFinding(
            "TARGET_MISSING", severity="warn", file="nope.md", targets=targets
        )

    def test_naming_claude_md_explains_where_the_checks_live(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        targets = [self.fx.root / "CLAUDE.md"]
        finding = self.assertFinding(
            "TARGET_IS_STUB", severity="info", file="CLAUDE.md", targets=targets
        )
        self.assertIn("AGENTS.md", finding.fix)


# --------------------------------------------------------------------------
# Markdown helpers
# --------------------------------------------------------------------------


class TestMarkdownHelpers(unittest.TestCase):
    def test_fences_are_blanked_not_removed(self):
        text = "a\n```\nb\n```\nc"
        self.assertEqual(ci.strip_fences(text).split("\n"), ["a", "", "", "", "c"])

    def test_comment_inside_fence_is_preserved(self):
        text = "```\n<!-- kept -->\n```\n"
        stripped, removed = ci.strip_block_html_comments(text)
        self.assertIn("kept", stripped)
        self.assertEqual(removed, 0)

    def test_blanking_preserves_line_count(self):
        text = "a\n<!-- x\ny -->\nb"
        self.assertEqual(
            len(ci.blank_block_html_comments(text).split("\n")),
            len(text.split("\n")),
        )

    def test_imports_ignore_fences_and_spans(self):
        text = "@real.md\n`@span.md`\n```\n@fenced.md\n```\n"
        self.assertEqual(ci.find_imports(text), ["real.md"])

    def test_imports_ignore_html_comments(self):
        self.assertEqual(ci.find_imports("<!-- @hidden.md -->\n@real.md\n"), ["real.md"])

    def test_heading_normalization(self):
        self.assertEqual(
            ci.normalize_heading("## Build & Test Commands"), "build and test commands"
        )
        self.assertEqual(ci.normalize_heading("`Rules`:"), "rules")

    def test_unterminated_comment_scan_reports_the_opener(self):
        scan = ci.scan_block_comments("a\n<!-- open\nb\n")
        self.assertEqual(scan.unclosed, 1)
        self.assertEqual(scan.removed, set())


# --------------------------------------------------------------------------
# Finding identity and --new-only
# --------------------------------------------------------------------------


class TestFindingKey(unittest.TestCase):
    def _finding(self, **kwargs) -> ci.Finding:
        base = dict(
            severity="warn", code="STALE_PATH", file="AGENTS.md",
            message="`docs/gone.md` does not exist.", section="Pointers", line=12,
        )
        base.update(kwargs)
        return ci.Finding(**base)

    def test_line_number_is_excluded_from_identity(self):
        self.assertEqual(self._finding().key(), self._finding(line=99).key())

    def test_message_distinguishes_two_findings_sharing_a_code(self):
        self.assertNotEqual(
            self._finding().key(),
            self._finding(message="`docs/other.md` does not exist.").key(),
        )

    def test_code_and_file_are_part_of_identity(self):
        self.assertNotEqual(self._finding().key(), self._finding(code="SIZE_WARN").key())
        self.assertNotEqual(self._finding().key(), self._finding(file="CLAUDE.md").key())


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def run_cli(argv):
    """Call main() with stdout and stderr captured.

    Returns (exit_code, stdout, stderr).
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ci.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliCase(BaseCase):
    """Isolates the --new-only baseline so no test touches the real state dir."""

    def setUp(self) -> None:
        super().setUp()
        self._saved_env = {
            k: os.environ.get(k) for k in ("XDG_STATE_HOME", "CLAUDE_PROJECT_DIR")
        }
        state = self.fx.base / "state"
        state.mkdir(parents=True, exist_ok=True)
        os.environ["XDG_STATE_HOME"] = str(state)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def tearDown(self) -> None:
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        super().tearDown()

    def cli(self, *args):
        return run_cli(["--project-root", str(self.fx.root)] + list(args))


class TestCli(CliCase):
    def _pair(self, agents=CONFORMING, claude="@AGENTS.md\n"):
        self.fx.write("AGENTS.md", agents)
        self.fx.write("CLAUDE.md", claude)

    def test_clean_run_exits_zero_and_always_prints_the_budget_line(self):
        self._pair()
        code, out, err = self.cli()
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("instruction-keeper: "), out)
        self.assertIn(
            "(target %d, warn %d, fail %d)."
            % (ci.AGENTS_TARGET_LINES, ci.AGENTS_WARN_LINES, ci.AGENTS_FAIL_LINES),
            out,
        )
        self.assertIn("no findings", out)

    def test_failure_exits_one(self):
        self._pair(claude="Use plan mode.\n")
        code, out, _ = self.cli()
        self.assertEqual(code, 1)
        self.assertIn("CLAUDE_NO_IMPORT", out)

    def test_nonexistent_project_root_exits_two(self):
        missing = self.fx.base / "no-such-repo"
        code, out, err = run_cli(["--project-root", str(missing)])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("is not a directory", err)

    def test_json_shape(self):
        self._pair()
        code, out, _ = self.cli("--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(sorted(payload), ["failed", "findings", "metrics"])
        self.assertEqual(payload["findings"], [])
        self.assertIs(payload["failed"], False)
        for key in ("resolved_lines", "resolved_bytes", "raw_bytes", "closure_files"):
            self.assertIn(key, payload["metrics"])
        self.assertEqual(payload["metrics"]["closure_files"], ["AGENTS.md", "CLAUDE.md"])

    def test_json_findings_carry_severity_code_and_line(self):
        self._pair(claude="Use plan mode.\n")
        code, out, _ = self.cli("--json")
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertIs(payload["failed"], True)
        codes = {f["code"] for f in payload["findings"]}
        self.assertIn("CLAUDE_NO_IMPORT", codes)
        for finding in payload["findings"]:
            self.assertEqual(
                sorted(finding),
                ["code", "file", "fix", "line", "message", "section", "severity"],
            )

    def test_quiet_info_hides_notes_in_text_output(self):
        body = (
            "## Rules\n\n- a\n\n## Commands\n\n```sh\nmake\n```\n\n"
            "## Architecture\n\n`a/` may not import `b/`.\n"
        )
        self._pair(agents=body)
        _, noisy, _ = self.cli()
        self.assertIn("SECTION_RENAME", noisy)
        _, quiet, _ = self.cli("--quiet-info")
        self.assertNotIn("SECTION_RENAME", quiet)
        self.assertTrue(quiet.startswith("instruction-keeper: "), quiet)

    def test_quiet_info_works_with_json(self):
        body = (
            "## Rules\n\n- a\n\n## Commands\n\n```sh\nmake\n```\n\n"
            "## Architecture\n\n`a/` may not import `b/`.\n"
        )
        self._pair(agents=body)
        _, out, _ = self.cli("--json", "--quiet-info")
        payload = json.loads(out)
        self.assertEqual([f for f in payload["findings"] if f["severity"] == "info"], [])
        self.assertIn("resolved_lines", payload["metrics"])

    def test_relative_positional_path_resolves_against_project_root(self):
        self._pair()
        self.fx.write("pkg/AGENTS.md", CONFORMING)
        code, out, _ = self.cli("--json", str(Path("pkg") / "AGENTS.md"))
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertNotIn("TARGET_MISSING", {f["code"] for f in payload["findings"]})

    def test_relative_positional_path_that_is_absent_is_reported(self):
        self._pair()
        _, out, _ = self.cli("--json", "nope.md")
        payload = json.loads(out)
        missing = [f for f in payload["findings"] if f["code"] == "TARGET_MISSING"]
        self.assertEqual(len(missing), 1, out)
        self.assertEqual(missing[0]["file"], "nope.md")
        self.assertEqual(missing[0]["severity"], "warn")


class TestNewOnly(CliCase):
    STALE = (
        CONFORMING
        + "\n## Pointers\n\n- [docs/gone.md](docs/gone.md) — the retry ladder and "
          "payload versions.\n"
    )

    def _codes(self, out):
        return {f["code"] for f in json.loads(out)["findings"]}

    def test_second_identical_run_reports_nothing(self):
        self.fx.write("AGENTS.md", self.STALE)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        _, first, _ = self.cli("--json", "--new-only")
        self.assertIn("STALE_PATH", self._codes(first))
        _, second, _ = self.cli("--json", "--new-only")
        self.assertEqual(self._codes(second), set())

    def test_inserting_a_line_above_does_not_make_a_finding_new(self):
        self.fx.write("AGENTS.md", self.STALE)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        _, first, _ = self.cli("--json", "--new-only")
        self.assertIn("STALE_PATH", self._codes(first))
        self.fx.write("AGENTS.md", "\n" + self.STALE)
        _, second, _ = self.cli("--json", "--new-only")
        self.assertEqual(self._codes(second), set())

    def test_a_genuinely_new_finding_is_reported(self):
        self.fx.write("AGENTS.md", self.STALE)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        self.cli("--json", "--new-only")
        self.fx.write(
            "AGENTS.md",
            self.STALE + "- [docs/also-gone.md](docs/also-gone.md) — the webhook "
                         "payload table.\n",
        )
        _, out, _ = self.cli("--json", "--new-only")
        findings = json.loads(out)["findings"]
        self.assertEqual([f["code"] for f in findings], ["STALE_PATH"], out)
        self.assertIn("docs/also-gone.md", findings[0]["message"])

    def test_unwritable_state_directory_does_not_crash_or_fail(self):
        # A hardened image with no writable state directory is a reason to skip
        # diff scoping, never a reason to fail the run.
        blocker = self.fx.base / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        os.environ["XDG_STATE_HOME"] = str(blocker / "state")
        self.assertIsNone(ci.state_path(self.fx.root))

        self.fx.write("AGENTS.md", self.STALE)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        code, out, err = self.cli("--json", "--new-only")
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertIn("STALE_PATH", self._codes(out))
        # Without a baseline every run reports the same findings rather than
        # silently suppressing them.
        code, out, _ = self.cli("--json", "--new-only")
        self.assertEqual(code, 0)
        self.assertIn("STALE_PATH", self._codes(out))


# --------------------------------------------------------------------------
# The shipped template
# --------------------------------------------------------------------------


class TestShippedTemplate(BaseCase):
    def test_template_has_no_failures(self):
        template = PLUGIN_ROOT / "assets" / "AGENTS.md.template"
        self.assertTrue(template.is_file(), "missing %s" % template)
        self.fx.write("AGENTS.md", template.read_text(encoding="utf-8"))
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        rep = self.fx.check()
        self.assertNoFailures(rep)
        # A template that does not parse as the standard's section set would
        # ship the wrong skeleton without failing anything.
        codes = {f.code for f in rep.findings}
        self.assertNotIn("MISSING_RULES", codes)
        self.assertNotIn("MISSING_COMMANDS", codes)
        self.assertNotIn("UNKNOWN_SECTION", codes)
        # A skeleton over the target ships a file that is already over budget
        # before the user has written a line of their own.
        self.assertLessEqual(
            rep.metrics["resolved_lines"], ci.AGENTS_TARGET_LINES,
            "the template's resolved closure must start under the %d-line target"
            % ci.AGENTS_TARGET_LINES,
        )


# --------------------------------------------------------------------------
# Regressions found by the 0.1.0 release gate
# --------------------------------------------------------------------------


class TestGateRegressions(AgentsCase):
    def test_fence_inside_a_comment_does_not_blind_the_comment_scanner(self):
        # A fence-looking line inside a comment must not open a fence for the
        # comment scanner; if it did, every later comment would be invisible.
        self._agents(
            "ACME API owns the REST surface.\n\n"
            "<!-- Commands must be fenced, like this:\n"
            "```bash\npnpm test\n```\n-->\n\n"
            "## Rules\n\n- Never weaken a test.\n\n"
            "<!-- this comment never closes\n\n"
            "## Commands\n\n```bash\npnpm test\n```\n"
        )
        self.assertFinding("HTML_COMMENT_UNCLOSED", severity="fail")

    def test_a_later_comment_is_still_stripped_after_a_fence_in_an_earlier_one(self):
        body = (
            "ACME API owns the REST surface.\n\n"
            "<!-- like this:\n```bash\npnpm test\n```\n-->\n\n"
            "## Rules\n\n- Never weaken a test.\n\n"
            "<!-- a second note\nspanning two lines\n-->\n\n"
            "## Commands\n\n```bash\npnpm test\n```\n"
        )
        self._agents(body)
        self.assertNoCode("SPLIT_TESTING")
        rep = self.fx.check()
        # Both comments out, CLAUDE.md's single line in.
        self.assertEqual(rep.metrics["resolved_lines"], 14)

    def test_a_heading_inside_a_comment_is_not_a_section(self):
        self._agents(
            "ACME API owns the REST surface.\n\n"
            "<!-- like this:\n```bash\npnpm test\n```\n-->\n\n"
            "## Rules\n\n- Never weaken a test.\n\n"
            "<!-- do not add\n## Testing\n-->\n\n"
            "## Commands\n\n```bash\npnpm test\n```\n"
        )
        self.assertNoCode("SPLIT_TESTING")

    def test_speckit_markers_quoted_on_two_separate_lines_are_not_a_region(self):
        # Two quoted markers must not define a protected span; doing so deleted
        # every heading between them from the parse.
        self._agents(
            "ACME API owns the REST surface.\n\n"
            "## Rules\n\n"
            "- Spec Kit owns the block opening with `<!-- SPECKIT START -->`.\n\n"
            "## Commands\n\n```bash\npnpm test\n```\n\n"
            "## Pointers\n\n"
            "- It closes with `<!-- SPECKIT END -->`; never edit inside it.\n"
        )
        self.assertNoCode("MISSING_COMMANDS")
        self.assertNoCode("SPECKIT_ORPHAN")

    def test_speckit_markers_quoted_in_two_fences_are_not_a_region(self):
        self._agents(
            "ACME API owns the REST surface.\n\n"
            "## Rules\n\n- a rule\n\n"
            "```text\n<!-- SPECKIT START -->\n```\n\n"
            "## Commands\n\n```bash\npnpm test\n```\n\n"
            "```text\n<!-- SPECKIT END -->\n```\n"
        )
        self.assertNoCode("MISSING_COMMANDS")

    def test_a_wrapped_purpose_clause_is_a_purpose_clause(self):
        self.fx.write("docs/webhooks.md", "x")
        self.fx.write("docs/adr/0004.md", "y")
        self._agents(
            CONFORMING
            + "\n## Pointers\n\n"
            "- [docs/webhooks.md](docs/webhooks.md) — payload versions and the\n"
            "  retry ladder; read before touching the dispatcher.\n"
            "- [docs/adr/0004.md](docs/adr/0004.md) — why the monolith was not\n"
            "  split; read before proposing a service extraction.\n"
        )
        self.assertNoCode("BLIND_REFERENCE")

    def test_a_wrapped_bare_link_is_still_bare(self):
        self.fx.write("docs/webhooks.md", "x")
        self._agents(
            CONFORMING
            + "\n## Pointers\n\n"
            "- [docs/webhooks.md](docs/webhooks.md)\n"
            "- [docs/webhooks.md](docs/webhooks.md) — payload versions and the\n"
            "  retry ladder; read before touching the dispatcher.\n"
        )
        self.assertFinding("BLIND_REFERENCE", severity="warn")
        self.assertEqual(
            len([f for f in self.fx.check().findings if f.code == "BLIND_REFERENCE"]), 1
        )

    def test_both_claude_md_locations_present_is_reported(self):
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        self.fx.write(".claude/CLAUDE.md", "@../AGENTS.md\n")
        self.assertFinding("CLAUDE_MD_DUPLICATED", severity="warn")

    def test_a_changed_count_does_not_make_a_finding_new(self):
        a = ci.Finding("warn", "SIZE_WARN", "AGENTS.md", "247 lines / 4.3 KB. Over.")
        b = ci.Finding("warn", "SIZE_WARN", "AGENTS.md", "248 lines / 4.3 KB. Over.")
        self.assertEqual(a.key(), b.key())

    def test_a_different_message_is_a_different_finding(self):
        a = ci.Finding("warn", "STALE_PATH", "AGENTS.md", "`docs/a.md` does not exist.")
        b = ci.Finding("warn", "STALE_PATH", "AGENTS.md", "`docs/b.md` does not exist.")
        self.assertNotEqual(a.key(), b.key())

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_symlink_loop_does_not_abort_the_run(self):
        self.fx.write("AGENTS.md", CONFORMING)
        loop = self.fx.root / "CLAUDE.md"
        other = self.fx.root / "other.md"
        loop.symlink_to(other)
        other.symlink_to(loop)
        rc, out, err = run_cli(["--project-root", str(self.fx.root)])
        self.assertIn(rc, (0, 1), err)
        self.assertNotIn("internal error", err)

    def test_an_unreadable_instruction_file_is_reported_not_crashed(self):
        if os.name == "nt" or os.geteuid() == 0:
            self.skipTest("chmod does not deny the owner here")
        self.fx.write("AGENTS.md", CONFORMING)
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        os.chmod(self.fx.root / "AGENTS.md", 0o000)
        try:
            rc, out, err = run_cli(["--project-root", str(self.fx.root)])
            self.assertNotEqual(rc, 2, err)
            self.assertIn("FILE_UNREADABLE", out)
        finally:
            os.chmod(self.fx.root / "AGENTS.md", 0o644)

    def test_new_only_does_not_clear_a_standing_failure(self):
        self.fx.write("AGENTS.md", "Repo.\n\n## Rules\n\n" + "\n".join(
            "- rule %d" % i for i in range(90)))
        self.fx.write("CLAUDE.md", "@AGENTS.md\n")
        state = self.fx.root / "state"
        prev = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = str(state)
        try:
            first, _, _ = run_cli(["--project-root", str(self.fx.root), "--new-only"])
            second, out, _ = run_cli(["--project-root", str(self.fx.root), "--new-only"])
        finally:
            if prev is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = prev
        self.assertEqual(first, 1)
        # Nothing new to print, but the file still fails.
        self.assertEqual(second, 1)
        self.assertIn("no findings", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
