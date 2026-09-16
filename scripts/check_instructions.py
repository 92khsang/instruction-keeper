#!/usr/bin/env python3
"""Deterministic checker for the instruction-keeper AGENTS.md / CLAUDE.md standard.

Standard library only, Python 3.8+.

What this script does and does not do
-------------------------------------
It checks only what a script can check with high precision: size over the
resolved @-import closure of the whole file pair, the section allowlist and its
order, per-section length caps, link and path resolution, and a small set of
high-precision content heuristics.

It deliberately does NOT try to judge most of the criteria that carry the
intellectual weight of the standard -- "can this be inferred from the code", "is
this an inventory or a responsibility". Those are model judgments. The one
exception is LINT_LEAKAGE, a deliberately narrow keyword check that fires only
when a formatter config is present; it catches the most literal instances of the
most common defect and nothing subtler. Silence from this script is not
approval; see references/section-criteria.md for the tests a human or an agent
must apply.

Two hosts are checked on every run, because AGENTS.md exists to be read by more
than one runtime and they do not read it the same way. Claude Code reads
CLAUDE.md, expands its @-imports and strips block-level HTML comments; Codex
reads AGENTS.md itself as raw bytes, expands nothing and strips nothing. The
Host table below records those differences once; see references/evidence.md for
the citation behind each field.

Measurement units, stated once because they differ by design:

* The Claude Code budget counts every line of the resolved closure, blank lines
  included, because that is what occupies context. Block-level HTML comments are
  excluded: Claude Code strips them before injection.
* The Codex budget counts raw bytes on disk over the chain of files from the
  repository root down to a working directory, comments and unexpanded import
  lines included, because that is what Codex concatenates.
* Per-section caps and the CLAUDE.md stub cap count non-blank lines only.

Exit codes: 0 = no failures (warnings and info allowed), 1 = at least one
failure, 2 = usage or internal error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

# --------------------------------------------------------------------------
# Standard parameters. Every number here is a budget, not a measurement.
# See references/evidence.md for what is and is not supported by evidence.
# --------------------------------------------------------------------------

AGENTS_TARGET_LINES = 120
AGENTS_WARN_LINES = 200
AGENTS_FAIL_LINES = 400

CLAUDE_STUB_WARN_LINES = 10
CLAUDE_STUB_FAIL_LINES = 20
CLAUDE_OVERLAP_FAIL_RATIO = 0.30
CLAUDE_OVERLAP_MIN_LINES = 2

PREAMBLE_WARN_LINES = 2

MAX_IMPORT_HOPS = 4
POINTER_FILE_MAX_LINES = 10
EMPHASIS_TOKEN_WARN = 5
CONTRIBUTING_STEP_WARN = 4

SECTION_ORDER = ["Rules", "Commands", "Boundaries", "Contributing", "Pointers"]
SECTION_CAPS = {
    "Rules": 40,
    "Commands": 25,
    "Boundaries": 15,
    "Contributing": 20,
    "Pointers": 10,
}
REQUIRED_SECTIONS = ["Rules", "Commands"]

# Claude Code loads a project CLAUDE.md from either location.
# https://code.claude.com/docs/en/memory
CLAUDE_MD_LOCATIONS = ["CLAUDE.md", ".claude/CLAUDE.md"]


@dataclass(frozen=True)
class Host:
    """An agent runtime's instruction-file loading model.

    Every host behaviour the checker depends on is a field here rather than a
    branch inside a check, so that a claim about a runtime is one value with one
    citation. Each field is sourced in references/evidence.md.

    Attributes:
        key: Stable identifier used in ``--json`` output.
        label: Name used in finding messages.
        expands_imports: Whether an ``@path`` line loads the file it names.
        strips_comments: Whether block-level HTML comments are removed before
            the file reaches the model.
    """
    key: str
    label: str
    expands_imports: bool
    strips_comments: bool


CLAUDE_CODE = Host("claude-code", "Claude Code", expands_imports=True, strips_comments=True)
CODEX = Host("codex", "Codex", expands_imports=False, strips_comments=False)
HOSTS = (CLAUDE_CODE, CODEX)

# Codex reads one file per directory along the chain from the project root to
# the working directory, taking the first of these names that exists. Both are
# read as raw bytes: no import is expanded and no comment is removed.
# https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs
CODEX_FILENAMES = ("AGENTS.override.md", "AGENTS.md")

# project_doc_max_bytes, from codex-rs/config/defaults.toml. Codex concatenates
# the chain root-first and truncates on a byte boundary once this is reached.
# The truncation is silent: it is a tracing warning, not a message in the TUI.
CODEX_DEFAULT_MAX_BYTES = 32768
CODEX_WARN_RATIO = 0.75

# Comments are free in Claude Code and billed in Codex, so a comment-heavy file
# is reported once it is large enough for the difference to matter.
CODEX_COMMENT_WARN_RATIO = 0.25
CODEX_COMMENT_WARN_BYTES = 2048

# Directories the nested scan never descends into. A repository is walked to
# find instruction files, not indexed, so vendored trees are skipped outright
# and the total is capped to keep the walk bounded on a large checkout.
CODEX_SCAN_SKIP_DIRS = frozenset({
    "node_modules", "vendor", "target", "dist", "build", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".git",
})
CODEX_SCAN_KEEP_DOT_DIRS = frozenset({".claude", ".codex"})
CODEX_SCAN_DIR_LIMIT = 20000

# A defect that repeats once per package is one defect with one fix. Past this
# many instances of a code the rest are collapsed into a single finding that
# states the true count, because a wall of identical warnings is the fastest way
# to teach a reader to skip the whole report. The cap is never silent.
REPEATED_FINDING_CAP = 10

# Heading synonyms -> canonical section. Matched on a normalized heading:
# lowercased, punctuation stripped, whitespace collapsed.
SECTION_SYNONYMS: Dict[str, str] = {}


def _register(canonical: str, *names: str) -> None:
    for n in names:
        SECTION_SYNONYMS[n] = canonical


_register(
    "Rules",
    "rules", "hard rules", "key rules", "core rules", "ground rules",
    "invariants", "constraints", "principles", "core principles",
    "core development principles", "project guidelines", "guidelines",
    "policies", "mandatory rules", "policies mandatory rules",
    "never", "do not", "donts", "forbidden actions", "anti patterns",
    "antipatterns", "important reminders", "code review rules", "security",
    "security requirements", "hard constraints", "non negotiables",
)
_register(
    "Commands",
    "commands", "common commands", "development commands", "dev commands",
    "build", "build commands", "building", "build and test commands",
    "build test and development commands", "quick start", "quick reference",
    "development", "scripts", "tasks", "make targets", "verification",
    "validation", "how to build", "essential commands",
)
_register(
    "Boundaries",
    "boundaries", "architecture", "architecture overview", "architecture notes",
    "project architecture", "ownership", "dependency rules",
    "dependency direction", "module boundaries", "layering",
    "cross repository boundaries", "repository map", "compatibility rule",
)
_register(
    "Contributing",
    "contributing", "contribution", "contribution policy", "contributing guidelines",
    "contributor guidelines", "workflow", "git workflow", "development workflow",
    "development workflows", "pull requests", "pr guidelines", "pr title format",
    "commit messages", "commits and prs", "branching", "branch names", "release",
    "changesets", "agent conduct", "agent policy", "ai usage policy",
    "llm usage policy", "agent contribution policy", "human review gates",
)
_register(
    "Pointers",
    "pointers", "further guidance", "documentation", "docs",
    "additional resources", "references", "see also", "where to look",
    "start here", "links", "additional notes", "more information",
)

# Headings that must not exist as top-level sections under this standard,
# mapped to the specific action the author should take.
SPLIT_HEADINGS: Dict[str, Tuple[str, str]] = {}


def _split(action_key: str, message: str, *names: str) -> None:
    for n in names:
        SPLIT_HEADINGS[n] = (action_key, message)


_split(
    "testing",
    "Split this section. Runnable invocations (how to run the whole suite, one "
    "file, one test) go to `## Commands`. Invariants ('never remove an existing "
    "test', 'never mutate fixtures', 'every change needs a test') go to "
    "`## Rules`. Harness reference and base-class tables go to a skill.",
    "testing", "tests", "testing conventions", "testing guidelines",
    "testing rules", "test rules", "running tests", "test commands",
    "testing strategy", "test strategy",
)
_split(
    "style",
    "Delete whatever a formatter, linter, type checker or CI job already fails "
    "on -- name the check in `## Commands` instead. Keep only non-default "
    "conventions no checker enforces, as bullets in `## Rules`. Restating "
    "linter-enforced rules is the most common defect measured in real "
    "instruction files.",
    "code style", "code style guidelines", "coding standards", "code standards",
    "coding guidelines", "code conventions", "conventions", "naming conventions",
    "style guide", "style", "code quality", "formatting", "comments",
)
_split(
    "setup",
    "Fold into `## Commands`. Keep only runtime versions and required "
    "environment variables that differ from what the toolchain implies. Install "
    "tutorials and prerequisites narrative belong in CONTRIBUTING.md.",
    "setup", "installation", "install", "prerequisites", "getting started",
    "development setup", "environment setup", "environment",
    "environment variables", "package management",
)
_split(
    "structure",
    "Delete. Directory layouts are derivable from the repository, and Claude "
    "Code's own /doctor trim cuts them by name. If a genuine ownership or "
    "dependency rule is hiding in here, move that one rule to `## Boundaries`.",
    "project structure", "repository structure", "repo structure", "structure",
    "directory structure", "codebase structure", "monorepo structure",
    "key files", "key files reference", "file layout", "entry points",
    "project layout",
)
_split(
    "troubleshooting",
    "Move to a skill -- a diagnostic procedure does not belong in a file loaded "
    "on every request. Keep only one-line gotchas, attached to the command they "
    "qualify, inside `## Commands`.",
    "troubleshooting", "debugging", "faq", "common issues", "known issues",
    "gotchas", "common gotchas",
)
_split(
    "overview",
    "Move to the unheaded preamble at the top of the file, at most 2 lines, and "
    "drop the technology inventory. Repository overviews are the one content "
    "type with direct negative evidence: measured popular and measured "
    "unhelpful.",
    "overview", "project overview", "repository overview", "repo overview",
    "about", "introduction", "high level overview", "tech stack",
    "technology stack", "technologies", "active technologies",
)
_split(
    "domain",
    "Move to a skill -- it is relevant only sometimes, so it should load on "
    "demand. Exception: at most 2-3 lines may stay in `## Rules` when the "
    "model's prior is actively wrong, for example after a major-version rename.",
    "glossary", "terminology", "domain model", "key concepts", "concepts",
    "patterns", "key patterns", "key development patterns", "architecture guide",
    "background", "how it works",
)
_split(
    "persona",
    "Delete from this file. Tone, verbosity, persona and response format are "
    "output-style concerns, not project instructions. Permission gates ('do not "
    "push', 'do not open PRs on my behalf') are real content -- move those to "
    "`## Contributing`.",
    "personality", "tone", "tone and style", "response format", "communication",
    "communication preferences", "your role", "review philosophy",
    "think before coding", "simplicity first",
)
_split(
    "residue",
    "Delete. A table of contents inside a file targeted under 200 lines is pure "
    "overhead, license text is derivable from LICENSE, and machine-appended "
    "change logs go stale without anyone noticing.",
    "table of contents", "contents", "license", "recent changes", "changelog",
    "learned user preferences",
)

# Keywords that, combined with a detected formatter config, indicate the author
# restated a rule the formatter already enforces. Matched on word boundaries,
# because these keywords are also ordinary English words ("spaces between
# services", "tab completion").
LINT_LEAKAGE_KEYWORDS = [
    "indent", "indents", "indentation", "tab", "tabs", "space", "spaces",
    "single quote", "single quotes", "double quote", "double quotes",
    "semicolon", "semicolons", "semi-colon", "semi-colons",
    "line length", "max line", "line width",
    "trailing comma", "trailing commas", "import order", "sort imports",
    "trailing whitespace",
]
LINT_LEAKAGE_RES = [
    (k, re.compile(r"\b" + re.escape(k).replace(r"\ ", r"\s+") + r"\b"))
    for k in LINT_LEAKAGE_KEYWORDS
]
# A bare "space"/"tab" is only evidence when it qualifies a width or a
# formatting verb; otherwise it is ordinary prose.
LINT_LEAKAGE_WEAK = {"tab", "tabs", "space", "spaces", "indent", "indents"}
LINT_LEAKAGE_WEAK_CONTEXT = re.compile(
    r"\b(\d+[- ]?(space|tab)|space[- ]?(indent|width)|tab[- ]?(indent|width)|"
    r"indent\w*\s+with|use\s+(tabs?|spaces?)|prefer\s+(tabs?|spaces?))",
    re.I,
)

FORMATTER_CONFIGS = [
    ".prettierrc", ".prettierrc.json", ".prettierrc.yaml", ".prettierrc.yml",
    ".prettierrc.js", "prettier.config.js", "biome.json", "biome.jsonc",
    ".editorconfig", "rustfmt.toml", ".rustfmt.toml", ".clang-format",
    ".eslintrc", ".eslintrc.json", ".eslintrc.js", "eslint.config.js",
    "eslint.config.mjs", ".ruff.toml", "ruff.toml", ".scalafmt.conf",
    ".ktlint",
]

EMPHASIS_TOKENS = ["MUST", "NEVER", "ALWAYS", "IMPORTANT", "CRITICAL", "REQUIRED"]
EMPHASIS_RE = re.compile(r"\b(" + "|".join(EMPHASIS_TOKENS) + r")\b")
BOX_DRAWING_RE = re.compile(r"[─-╿]")
DIAGRAM_FENCE_RE = re.compile(r"^\s*(?:```|~~~)\s*(mermaid|plantuml|dot|graphviz)\b", re.I)
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\b")
DEFAULT_SPECKIT_START = "<!-- SPECKIT START -->"
DEFAULT_SPECKIT_END = "<!-- SPECKIT END -->"
SPECKIT_CONFIG = Path(".specify") / "extensions" / "agent-context" / "agent-context-config.yml"
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
BARE_PATH_RE = re.compile(r"`([^`\n]+)`")
URI_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:")
VERSION_SEGMENT_RE = re.compile(r"^v?[\d.]+$")
ORDERED_ITEM_RE = re.compile(r"^\s{0,3}\d+[.)]\s+\S")
STEP_HEADING_RE = re.compile(r"^\s*#{1,6}\s*step\s+\d+", re.I)
SETEXT_UNDERLINE_RE = re.compile(r"^\s{0,3}(=+|-+)\s*$")
FENCE_OPEN_RE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})(.*)$")

SEVERITY_RANK = {"info": 0, "warn": 1, "fail": 2}


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


@dataclass
class Finding:
    severity: str          # "fail" | "warn" | "info"
    code: str              # stable machine key
    file: str              # repo-relative path
    message: str
    section: Optional[str] = None
    line: Optional[int] = None
    fix: Optional[str] = None
    host: Optional[str] = None   # Host.key, or None when the finding is host-neutral

    def key(self) -> str:
        """Identity used to decide whether a finding is new.

        Deliberately excludes the line number: inserting a line shifts every
        later finding's position without changing what any of them says, and
        --new-only must not treat unchanged findings as newly introduced. The
        message digest distinguishes two findings that share a code and a
        section. Severity is encoded in ``code``, so crossing a threshold still
        reads as new.
        """
        # ``host`` is deliberately absent: every host-specific code already
        # carries the host in its name, so adding the field would change every
        # stored key and invalidate every --new-only baseline for nothing.
        #
        # Numbers are normalized out: a size or cap finding restates its own
        # count, and keying on that would make the finding read as new on every
        # edit that changed the count by one.
        normalized = re.sub(r"\d+(?:[.,]\d+)*", "#", self.message)
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
        return f"{self.file}|{self.code}|{self.section or ''}|{digest}"


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    metrics: Dict[str, object] = field(default_factory=dict)

    def add(self, *args, **kwargs) -> None:
        self.findings.append(Finding(*args, **kwargs))

    @property
    def failed(self) -> bool:
        return any(f.severity == "fail" for f in self.findings)


# --------------------------------------------------------------------------
# Markdown helpers
# --------------------------------------------------------------------------


def read_text(path: Path) -> str:
    """Read an instruction file.

    Decoded as ``utf-8-sig``: editors that default to "UTF-8 with BOM" are
    common enough that a byte-order mark must not reach the parser, where it
    would sit in front of a first-line heading or import and stop either from
    matching.
    """
    return path.read_text(encoding="utf-8-sig", errors="replace")


@dataclass
class FenceScan:
    blanked: str                 # fenced content emptied, line count preserved
    opens: Set[int]              # line indices of top-level fence-opening lines
    unclosed: Optional[int]      # line index of an unterminated fence opener


def scan_fences(text: str) -> FenceScan:
    """Locate fenced code blocks.

    Fence length and character are both significant: CommonMark closes a fence
    only with a run of the same character at least as long as the opener, so a
    ```` ``` ```` nested inside a ```` ```` ```` block does not end it.
    """
    out: List[str] = []
    opens: Set[int] = set()
    fence_char: Optional[str] = None
    fence_len = 0
    opened_at: Optional[int] = None
    for i, line in enumerate(text.split("\n")):
        m = FENCE_OPEN_RE.match(line)
        if fence_char is None:
            if m:
                fence_char = m.group(2)[0]
                fence_len = len(m.group(2))
                opened_at = i
                opens.add(i)
                out.append("")
                continue
            out.append(line)
        else:
            out.append("")
            if (
                m
                and m.group(2)[0] == fence_char
                and len(m.group(2)) >= fence_len
                and not m.group(3).strip()
            ):
                fence_char = None
                opened_at = None
    return FenceScan("\n".join(out), opens, opened_at)


def strip_fences(text: str) -> str:
    """Blank out fenced code blocks, preserving line numbering."""
    return scan_fences(text).blanked


def strip_code_spans(text: str) -> str:
    return re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), text)


@dataclass
class CommentScan:
    """Where block-level HTML comments sit in a file.

    ``removed`` holds line indices that are nothing but comment. ``rewritten``
    holds lines that begin with a closed comment and still carry content, mapped
    to the content that survives -- Claude Code strips the comment span, not the
    whole line. ``unclosed`` is the opening line of a ``<!--`` that never
    terminates.
    """
    removed: Set[int]
    rewritten: Dict[int, str]
    unclosed: Optional[int]


def scan_block_comments(text: str) -> CommentScan:
    """Find block-level HTML comments.

    Claude Code strips these before injecting a memory file into context, so
    they cost nothing and must not count against any budget. Comments inside
    fenced blocks are preserved and therefore not reported here.

    An unterminated ``<!--`` is *not* treated as a comment running to the end of
    the file. Claude Code's stripper keeps such a block verbatim, so everything
    below the opener really does load and must stay visible to every check and
    to the size budget. ``unclosed`` records the opener so the caller can report
    it.
    """
    lines = text.split("\n")
    removed: Set[int] = set()
    rewritten: Dict[int, str] = {}
    run: List[int] = []           # lines of the comment currently being consumed
    in_comment = False
    opened_at: Optional[int] = None
    fence_char: Optional[str] = None
    fence_len = 0

    # Fence state and comment state are tracked together, in one pass. They are
    # not independent: a fence opens only outside a comment, and a `<!--` opens
    # only outside a fence, so a map of one built without the other desynchronises
    # on a fence-looking line inside a comment or a `<!--` inside a code block.
    for i, raw in enumerate(lines):
        if in_comment:
            run.append(i)
            end = raw.find("-->")
            if end == -1:
                continue
            in_comment = False
            opened_at = None
            remainder = raw[end + 3:]
            for idx in run:
                removed.add(idx)
            run = []
            leftover = _consume_leading_comments(remainder)
            if leftover is None:
                in_comment = True
                opened_at = i
                run = [i]
            elif leftover.strip():
                removed.discard(i)
                rewritten[i] = leftover
            continue

        fence = FENCE_OPEN_RE.match(raw)
        if fence_char is not None:
            if (
                fence
                and fence.group(2)[0] == fence_char
                and len(fence.group(2)) >= fence_len
                and not fence.group(3).strip()
            ):
                fence_char = None
            continue
        if fence:
            fence_char = fence.group(2)[0]
            fence_len = len(fence.group(2))
            continue

        if not raw.lstrip().startswith("<!--"):
            continue

        leftover = _consume_leading_comments(raw)
        if leftover is None:
            in_comment = True
            opened_at = i
            run = [i]
        elif leftover.strip():
            rewritten[i] = leftover
        else:
            removed.add(i)

    unclosed = opened_at if in_comment else None
    return CommentScan(removed, rewritten, unclosed)


def _consume_leading_comments(line: str) -> Optional[str]:
    """Strip closed ``<!-- ... -->`` spans from the front of a line.

    Returns what is left, or ``None`` when a comment opens and does not close on
    this line.
    """
    rest = line
    while True:
        stripped = rest.lstrip()
        if not stripped.startswith("<!--"):
            return rest
        lead = len(rest) - len(stripped)
        end = stripped.find("-->", 4)
        if end == -1:
            return None
        rest = " " * lead + stripped[end + 3:]


def blank_block_html_comments(text: str) -> str:
    """Same line count, comment content emptied. Used for parsing so that line
    numbers still map onto the real file."""
    scan = scan_block_comments(text)
    out = []
    for i, line in enumerate(text.split("\n")):
        if i in scan.removed:
            out.append("")
        elif i in scan.rewritten:
            out.append(scan.rewritten[i])
        else:
            out.append(line)
    return "\n".join(out)


def strip_block_html_comments(text: str) -> Tuple[str, int]:
    """Comment lines removed outright. Used for the size budget."""
    scan = scan_block_comments(text)
    kept = []
    for i, line in enumerate(text.split("\n")):
        if i in scan.removed:
            continue
        kept.append(scan.rewritten.get(i, line))
    return "\n".join(kept), len(scan.removed)


def find_imports(text: str) -> List[str]:
    """@path imports, ignoring code spans, fenced blocks and block-level HTML
    comments, matching the documented Claude Code behaviour.

    Comments are excluded because Claude Code strips them before expanding
    imports: a commented-out `@archive.md` does not load, and a commented
    `@AGENTS.md` does not satisfy the stub contract.
    """
    scrubbed = strip_code_spans(strip_fences(blank_block_html_comments(text)))
    found: List[str] = []
    for m in re.finditer(r"(?:^|\s)@([^\s`]+)", scrubbed):
        target = m.group(1).rstrip(".,;:)")
        if target and not target.startswith("@"):
            found.append(target)
    return found


@dataclass
class Closure:
    """The measured result of resolving an @-import closure.

    Thresholds are compared in ``report_size`` and nowhere else, so a new
    measurement -- raw bytes against another agent's truncation limit, for
    instance -- is an addition here plus a comparison there.
    """
    lines: int = 0
    effective_bytes: int = 0     # after stripping block-level HTML comments
    raw_bytes: int = 0           # as stored on disk, comments included
    files: List[Path] = field(default_factory=list)
    missing: List[Tuple[Path, str]] = field(default_factory=list)
    external: List[Tuple[Path, str]] = field(default_factory=list)


def measure_closure(
    path: Path,
    project_root: Path,
    closure: Optional[Closure] = None,
    hop: int = 0,
    seen: Optional[Set[Path]] = None,
) -> Closure:
    """Accumulate lines, bytes and file list over the transitive @-import closure.

    Imports load at launch and do not reduce context, so the budget applies to
    the closure, not to one file. ``seen`` is shared across the AGENTS.md and
    CLAUDE.md calls so that the file both import is counted once.
    """
    if closure is None:
        closure = Closure()
    if seen is None:
        seen = set()
    try:
        real = path.resolve()
    except (OSError, RuntimeError):
        return closure
    if real in seen or hop > MAX_IMPORT_HOPS or not real.is_file():
        return closure
    seen.add(real)
    try:
        text = read_text(real)
        raw = real.read_bytes()
    except OSError:
        return closure

    effective, _ = strip_block_html_comments(text)
    closure.lines += len(effective.splitlines())
    closure.effective_bytes += len(effective.encode("utf-8"))
    closure.raw_bytes += len(raw)
    closure.files.append(real)

    for target in find_imports(text):
        base = Path(os.path.expanduser(target))
        candidate = base if base.is_absolute() else (real.parent / base)
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            closure.missing.append((real, target))
            continue
        if not resolved.is_file():
            closure.missing.append((real, target))
            continue
        if not _within(resolved, project_root):
            closure.external.append((real, target))
        measure_closure(candidate, project_root, closure, hop + 1, seen)
    return closure


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


# --------------------------------------------------------------------------
# The Codex load
#
# Claude Code and Codex read different files under different rules, so they are
# measured by different functions on purpose. measure_closure above follows one
# CLAUDE.md through its @-imports and counts lines with comments removed;
# measure_codex_chain below walks a directory chain and counts raw bytes with
# nothing removed. Folding them together would hide the fact that the two
# runtimes disagree, which is the whole thing this release exists to report.
# --------------------------------------------------------------------------


@dataclass
class CodexConfig:
    """The parts of a repository's .codex/config.toml the checker needs.

    Defaults match codex-rs/config/defaults.toml. A repository that raises
    ``project_doc_max_bytes`` must not be told its files are too large, so the
    file is read when it exists; anything that cannot be parsed confidently
    leaves the corresponding default in place.
    """
    max_bytes: int = CODEX_DEFAULT_MAX_BYTES
    fallback_filenames: Tuple[str, ...] = ()
    source: Optional[str] = None   # repo-relative path the values came from

    @property
    def filenames(self) -> Tuple[str, ...]:
        """Candidate names Codex tries in one directory, in order."""
        names = list(CODEX_FILENAMES)
        for name in self.fallback_filenames:
            if name not in names:
                names.append(name)
        return tuple(names)


# Deliberately not a TOML parser. Three keys are read from the top level of the
# file by shape; a table header ends the region this can speak about, because a
# key of the same name under [profiles.x] is not the active value.
_TOML_INT_RE = re.compile(r"^\s*project_doc_max_bytes\s*=\s*(\d[\d_]*)\s*(?:#.*)?$")
_TOML_LIST_RE = re.compile(
    r"^\s*project_doc_fallback_filenames\s*=\s*\[(.*?)\]\s*(?:#.*)?$")
_TOML_TABLE_RE = re.compile(r"^\s*\[")
_TOML_STRING_RE = re.compile(r"[\"\']([^\"\']*)[\"\']")


def read_codex_config(project_root: Path) -> CodexConfig:
    """Read .codex/config.toml, falling back to Codex's own defaults.

    Only top-level scalar and single-line array forms are recognised. A value
    this cannot read is left at its default rather than guessed at, because a
    wrong budget produces a wrong finding and this checker's contract is
    precision over recall.

    ``project_root_markers`` is deliberately **not** read from here even though
    it lives in the same file. Codex composes project-root discovery from the
    non-project layers only, so a repository cannot change where its own root
    is; honouring it here would model a behaviour Codex does not have.
    """
    path = project_root / ".codex" / "config.toml"
    try:
        if not path.is_file():
            return CodexConfig()
        text = read_text(path)
    except (OSError, RuntimeError):
        return CodexConfig()

    config = CodexConfig(source=rel(project_root, path))
    for line in text.splitlines():
        if _TOML_TABLE_RE.match(line):
            break
        m = _TOML_INT_RE.match(line)
        if m:
            try:
                config.max_bytes = int(m.group(1).replace("_", ""))
            except ValueError:
                pass
            continue
        m = _TOML_LIST_RE.match(line)
        if m:
            config.fallback_filenames = tuple(
                n for n in _TOML_STRING_RE.findall(m.group(1)) if n
            )
    return config


@dataclass
class CodexFile:
    """One file Codex loads, measured as Codex sees it."""
    path: Path
    raw_bytes: int = 0
    comment_bytes: int = 0        # block-level HTML comments, billed here
    imports: List[Tuple[int, str]] = field(default_factory=list)   # (line, target)
    shadowed: Optional[Path] = None   # AGENTS.md this file hides in its directory


@dataclass
class CodexChain:
    """Everything Codex concatenates for one working directory.

    ``leaf`` is the directory a session would have to be in for this chain to
    load. The root chain always exists when the repository has a root
    AGENTS.md; a package chain exists for every directory below it that has one
    of its own.
    """
    leaf: Path
    files: List[CodexFile] = field(default_factory=list)

    @property
    def raw_bytes(self) -> int:
        return sum(f.raw_bytes for f in self.files)


def _measure_codex_file(path: Path) -> Optional[CodexFile]:
    """Measure one file the way Codex loads it: raw bytes, nothing removed."""
    try:
        raw = path.read_bytes()
        text = read_text(path)
    except (OSError, RuntimeError):
        return None

    measured = CodexFile(path=path, raw_bytes=len(raw))

    effective, _ = strip_block_html_comments(text)
    measured.comment_bytes = max(
        0, len(text.encode("utf-8")) - len(effective.encode("utf-8")))

    # Reported per line so the finding can point at the import that will not
    # load. find_imports collapses position, so the scan is repeated here on the
    # same scrubbed view it uses.
    scrubbed = strip_code_spans(strip_fences(blank_block_html_comments(text)))
    for number, line in enumerate(scrubbed.splitlines(), 1):
        for m in re.finditer(r"(?:^|\s)@([^\s`]+)", line):
            target = m.group(1).rstrip(".,;:)")
            if target and not target.startswith("@"):
                measured.imports.append((number, target))
    return measured


def _codex_file_in(directory: Path, config: CodexConfig) -> Optional[CodexFile]:
    """The one file Codex loads from this directory, if any.

    Codex takes the first name that exists and never looks at the rest, so a
    stray AGENTS.override.md silently replaces AGENTS.md. That is recorded on
    the returned file rather than discovered again later.
    """
    names = config.filenames
    for index, name in enumerate(names):
        candidate = directory / name
        try:
            if not candidate.is_file():
                continue
        except OSError:
            continue
        measured = _measure_codex_file(candidate)
        if measured is None:
            continue
        for later in names[index + 1:]:
            hidden = directory / later
            try:
                if hidden.is_file():
                    measured.shadowed = hidden
                    break
            except OSError:
                continue
        return measured
    return None


def codex_directories(
    project_root: Path,
    config: Optional[CodexConfig] = None,
) -> Tuple[List[Path], bool]:
    """Directories holding an instruction file either host would load.

    Returns the directories and whether the walk stopped early. Both hosts'
    filenames are collected in one pass so the nested-pair check can see a
    CLAUDE.md that has no AGENTS.md beside it, and a name the repository added
    to ``project_doc_fallback_filenames`` counts as one Codex would load.
    """
    config = config or CodexConfig()
    watched = set(config.filenames) | {"CLAUDE.md"}
    found: List[Path] = []
    visited = 0
    truncated = False

    for current, dirnames, filenames in os.walk(project_root):
        visited += 1
        if visited > CODEX_SCAN_DIR_LIMIT:
            truncated = True
            dirnames[:] = []
            break
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in CODEX_SCAN_SKIP_DIRS
            and (not d.startswith(".") or d in CODEX_SCAN_KEEP_DOT_DIRS)
        )
        if watched.intersection(filenames):
            found.append(Path(current))
    return found, truncated


def codex_chains(
    project_root: Path,
    config: CodexConfig,
    directories: Sequence[Path],
) -> List[CodexChain]:
    """One chain per directory a session could sit in and load something new.

    Codex concatenates every file from the project root down to the working
    directory, so the amount loaded depends on where the session is. Each
    directory that contributes a file of its own is therefore a distinct
    scenario, and each is measured from the root down.
    """
    measured: Dict[Path, Optional[CodexFile]] = {}

    def file_in(directory: Path) -> Optional[CodexFile]:
        if directory not in measured:
            measured[directory] = _codex_file_in(directory, config)
        return measured[directory]

    chains: List[CodexChain] = []
    for leaf in directories:
        if file_in(leaf) is None:
            continue
        chain = CodexChain(leaf=leaf)
        try:
            parts = leaf.relative_to(project_root).parts
        except ValueError:
            continue
        cursor = project_root
        for step in (None,) + parts:
            if step is not None:
                cursor = cursor / step
            found = file_in(cursor)
            if found is not None:
                chain.files.append(found)
        if chain.files:
            chains.append(chain)
    return chains


def normalize_heading(text: str) -> str:
    """Fold a heading to its synonym-lookup form.

    Lowercases, drops backticks and punctuation, expands ``&`` to ``and``, and
    collapses whitespace, so that `## Build & Test Commands` and
    `## build and test commands` resolve to the same canonical section.
    """
    t = text.strip().lower()
    t = re.sub(r"`", "", t)
    t = re.sub(r"[^a-z0-9& ]+", " ", t)
    t = t.replace("&", " and ")
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class Section:
    raw_heading: str
    normalized: str
    canonical: Optional[str]
    level: int
    start_line: int      # 1-indexed, the heading line
    lines: List[str] = field(default_factory=list)

    @property
    def prose_lines(self) -> int:
        """Body lines outside fenced code, blanks excluded."""
        blanked = strip_fences("\n".join(self.lines))
        return len([l for l in blanked.split("\n") if l.strip()])

    @property
    def code_lines(self) -> int:
        """Non-blank lines inside fenced blocks."""
        return max(0, self.total_lines - self.prose_lines)

    @property
    def has_fence(self) -> bool:
        return any(FENCE_OPEN_RE.match(l) for l in self.lines)

    @property
    def total_lines(self) -> int:
        """Every non-blank body line. This is what the per-section cap governs:
        a 250-line fenced command block occupies a section of an always-loaded
        file exactly as much as 250 bullets do."""
        return len([l for l in self.lines if l.strip()])


@dataclass
class ParsedDoc:
    path: Path
    text: str
    effective: str
    preamble: List[str]
    sections: List[Section]
    speckit_span: Optional[Tuple[int, int]]
    speckit_markers: Tuple[str, str]
    is_pointer: bool
    import_targets: List[str]
    unclosed_comment: Optional[int]
    unclosed_fence: Optional[int]


def speckit_markers(project_root: Path) -> Tuple[str, str]:
    """The SPECKIT marker pair for this repository.

    Spec Kit's agent-context extension lets a project override the markers in
    ``agent-context-config.yml``. Read them rather than assuming the defaults --
    with custom markers the managed block otherwise parses as ordinary content
    and the checker advises deleting a region Spec Kit owns. Parsed with a
    regex because the standard library has no YAML reader.
    """
    config = project_root / SPECKIT_CONFIG
    start, end = DEFAULT_SPECKIT_START, DEFAULT_SPECKIT_END
    try:
        raw = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return start, end
    for key, default in (("start", start), ("end", end)):
        m = re.search(
            r"^\s*[\w-]*" + key + r"[\w-]*\s*:\s*[\"']?(<!--.*?-->)[\"']?\s*$",
            raw, re.M | re.I,
        )
        if m:
            if key == "start":
                start = m.group(1)
            else:
                end = m.group(1)
    return start, end


def parse(path: Path, text: str, project_root: Optional[Path] = None) -> ParsedDoc:
    """Split an instruction file into a preamble and top-level sections.

    Normalization matters more than it looks, because real files break every
    naive assumption: a lone `# Title` above `##` sections is a title and not a
    section; some files use `#` for every section; content routinely sits before
    the first heading; and headings appear inside fenced blocks and HTML
    comments where they must not be parsed.

    Line numbers in the result index the file on disk, so findings can be
    reported at a position the reader can open.
    """
    comment_scan = scan_block_comments(text)
    effective, _ = strip_block_html_comments(text)

    # Parse against a view where block-level HTML comments are emptied but line
    # positions are preserved: comments cost no context, so they must not count
    # toward the preamble or any section cap, yet reported line numbers must
    # still map onto the real file.
    raw_lines = blank_block_html_comments(text).split("\n")
    fence_scan = scan_fences("\n".join(raw_lines))
    blanked = fence_scan.blanked.split("\n")

    # SPECKIT markers are themselves HTML comments, so locate them on the raw
    # text. The span is excluded from section parsing: Spec Kit owns that
    # region, and this plugin never reformats or relocates it.
    start_marker, end_marker = (
        speckit_markers(project_root) if project_root else (DEFAULT_SPECKIT_START, DEFAULT_SPECKIT_END)
    )
    start_re = re.compile(re.escape(start_marker).replace(r"\ ", r"\s+"), re.I)
    end_re = re.compile(re.escape(end_marker).replace(r"\ ", r"\s+"), re.I)

    # Located on a view with fenced blocks and code spans blanked, so that a file
    # documenting the convention by quoting a marker does not acquire a protected
    # region. Both helpers preserve line positions.
    scannable = strip_code_spans(strip_fences(text)).split("\n")
    speckit_span: Optional[Tuple[int, int]] = None
    start_idx = end_idx = None
    for i, line in enumerate(scannable):
        if start_idx is None and start_re.search(line):
            start_idx = i
        elif start_idx is not None and end_re.search(line):
            end_idx = i
            break
    if start_idx is not None and end_idx is not None:
        speckit_span = (start_idx, end_idx)

    def in_speckit(i: int) -> bool:
        return speckit_span is not None and speckit_span[0] <= i <= speckit_span[1]

    heading_positions: List[Tuple[int, int, str]] = []
    for i, line in enumerate(raw_lines):
        if blanked[i] == "" and line.strip() != "":
            continue  # inside a fenced block
        if in_speckit(i):
            continue
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            heading_positions.append((i, len(m.group(1)), m.group(2)))
            continue
        # Setext headings, recognized only when the text maps onto a section
        # this standard knows. A bare `---` under a paragraph is far more often
        # a thematic break, and guessing produced false MISSING_RULES findings.
        if i > 0 and SETEXT_UNDERLINE_RE.match(line) and len(line.strip()) >= 3:
            prev = raw_lines[i - 1]
            if prev.strip() and not prev.lstrip().startswith(("#", "-", "*", ">", "|")):
                if blanked[i - 1] != "" or prev.strip() == "":
                    norm = normalize_heading(prev)
                    if norm in SECTION_SYNONYMS or norm in SPLIT_HEADINGS:
                        level = 1 if line.strip()[0] == "=" else 2
                        heading_positions.append((i - 1, level, prev.strip()))

    heading_positions.sort()

    # The section level is the level of the heading that opens the section run,
    # not the shallowest level in the file. A file whose sections are `##` may
    # carry a stray `#` heading lower down, and that heading must not redefine
    # what counts as a section.
    title_line: Optional[int] = None
    if heading_positions:
        first_level = heading_positions[0][1]
        if len(heading_positions) > 1 and heading_positions[1][1] > first_level:
            title_line = heading_positions[0][0]
            section_level = heading_positions[1][1]
        else:
            section_level = first_level
    else:
        section_level = 2

    tops = [
        (i, lvl, txt)
        for i, lvl, txt in heading_positions
        if lvl <= section_level and i != title_line
    ]

    first_heading = tops[0][0] if tops else len(raw_lines)
    preamble = [
        l for idx, l in enumerate(raw_lines[:first_heading])
        if l.strip() and not in_speckit(idx) and idx != title_line
    ]

    sections: List[Section] = []
    for n, (i, lvl, txt) in enumerate(tops):
        end = tops[n + 1][0] if n + 1 < len(tops) else len(raw_lines)
        # Blank the protected region rather than dropping it, so that offsets
        # into ``lines`` still map onto real file positions.
        body = [
            "" if in_speckit(idx) else l
            for idx, l in enumerate(raw_lines[i + 1:end], start=i + 1)
        ]
        norm = normalize_heading(txt)
        sections.append(
            Section(
                raw_heading=txt,
                normalized=norm,
                canonical=SECTION_SYNONYMS.get(norm),
                level=lvl,
                start_line=i + 1,
                lines=body,
            )
        )

    # A pointer file redirects somewhere else instead of carrying content. Short
    # is necessary but not sufficient: a file that already uses the standard's
    # headings is a real instruction file however brief, and must be checked.
    effective_lines = len([l for l in effective.split("\n") if l.strip()])
    points_somewhere = bool(
        LINK_RE.search(effective)
        or find_imports(text)
        or re.search(r"[\w.-]+/[\w./-]+|\b[\w-]+\.(?:md|rst|txt)\b", effective)
    )
    is_pointer = (
        not sections
        and 0 < effective_lines <= POINTER_FILE_MAX_LINES
        and points_somewhere
    )

    return ParsedDoc(
        path=path,
        text=text,
        effective=effective,
        preamble=preamble,
        sections=sections,
        speckit_span=speckit_span,
        speckit_markers=(start_marker, end_marker),
        is_pointer=is_pointer,
        import_targets=find_imports(text),
        unclosed_comment=comment_scan.unclosed,
        unclosed_fence=fence_scan.unclosed,
    )


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


def rel(root: Path, p: Path) -> str:
    """Repository-relative display path.

    The unresolved path is tried first so that a symlink is named where the
    reader will find it rather than by the target it points at, which for a
    broken link is a path that does not exist.
    """
    try:
        return str(p.relative_to(root))
    except ValueError:
        pass
    try:
        return str(p.resolve().relative_to(root.resolve()))
    except (ValueError, OSError, RuntimeError):
        return str(p)


def locate_claude_md(root: Path) -> List[Path]:
    """Every project CLAUDE.md present, in Claude Code's own load order.

    Claude Code reads a project CLAUDE.md from ``./CLAUDE.md`` or
    ``./.claude/CLAUDE.md``, and loads both when both exist. Returning the list
    rather than the first match lets the caller say so.
    """
    found: List[Path] = []
    for candidate in CLAUDE_MD_LOCATIONS:
        p = root / candidate
        if p.is_file() or p.is_symlink():
            found.append(p)
    return found


def check_file_pair(root: Path, report: Report) -> Tuple[Optional[Path], Optional[Path]]:
    """Check the AGENTS.md / CLAUDE.md contract and report which files exist.

    Returns the two paths, each ``None`` when that file is absent. A returned
    ``CLAUDE.md`` is not structurally checked by the caller: once ``AGENTS.md``
    exists, ``CLAUDE.md`` is a stub whose whole contract lives here. Its import
    closure is still measured, in ``run``.
    """
    agents = root / "AGENTS.md"
    claude_files = locate_claude_md(root)
    claude = claude_files[0] if claude_files else None
    a_exists = agents.is_file()

    if len(claude_files) > 1:
        report.add(
            "warn", "CLAUDE_MD_DUPLICATED", rel(root, claude_files[1]),
            "Both CLAUDE.md and .claude/CLAUDE.md exist. Claude Code loads both, "
            "so the instructions are concatenated and can disagree with each other.",
            fix="Keep one. The checker reports the contract against "
                + rel(root, claude_files[0]) + "; delete the other or fold it in.",
        )

    if not a_exists and claude is None:
        report.add(
            "warn", "PAIR_MISSING", "AGENTS.md",
            "No AGENTS.md at the repository root, and no CLAUDE.md at either "
            "CLAUDE.md or .claude/CLAUDE.md.",
            fix="Run /instruction-keeper:init to create AGENTS.md plus a CLAUDE.md stub.",
        )
        return None, None

    if a_exists and not claude_files:
        report.add(
            "warn", "PAIR_NO_CLAUDE", "CLAUDE.md",
            "AGENTS.md exists but CLAUDE.md does not. Claude Code reads CLAUDE.md, "
            "not AGENTS.md, so none of this file reaches Claude.",
            fix="Create CLAUDE.md containing the single line `@AGENTS.md`.",
        )
        return agents, None

    if claude is not None and not a_exists:
        report.add(
            "warn", "PAIR_NO_AGENTS", rel(root, claude),
            "CLAUDE.md exists but AGENTS.md does not, so coding agents that read "
            "AGENTS.md find nothing.",
            fix="Run /instruction-keeper:split to move the shared content into "
                "AGENTS.md and leave CLAUDE.md as an `@AGENTS.md` import plus any "
                "Claude-specific lines.",
        )
        return None, claude

    # Both exist.
    cname = rel(root, claude)
    if claude.is_symlink():
        try:
            if claude.resolve() == agents.resolve():
                return agents, claude
        except (OSError, RuntimeError):
            pass
        if not claude.exists():
            report.add(
                "fail", "CLAUDE_BROKEN_SYMLINK", cname,
                "CLAUDE.md is a symlink whose target does not exist, so Claude Code "
                "loads nothing from it.",
                fix="Point the link at AGENTS.md, or replace it with a file whose "
                    "first line is `@AGENTS.md`.",
            )
            return agents, None

    try:
        ctext = read_text(claude)
    except OSError:
        return agents, None

    # An import resolves relative to the file that contains it, so the target
    # must be matched by resolved path and not by basename: a `.claude/CLAUDE.md`
    # whose import reads `@AGENTS.md` points at `.claude/AGENTS.md` and loads
    # nothing, which a basename comparison would accept.
    imports_agents = False
    for target in find_imports(ctext):
        base = Path(os.path.expanduser(target))
        candidate = base if base.is_absolute() else (claude.parent / base)
        try:
            if candidate.resolve() == agents.resolve():
                imports_agents = True
                break
        except (OSError, RuntimeError):
            continue
    if not imports_agents:
        depth = len(Path(cname).parts) - 1
        prefix = "../" * depth
        report.add(
            "fail", "CLAUDE_NO_IMPORT", cname,
            "CLAUDE.md does not import the repository's AGENTS.md, so the two files "
            "will drift apart.",
            fix=f"Make `@{prefix}AGENTS.md` the first line of CLAUDE.md. Note the "
                f"import is for de-duplicating maintenance, not for saving tokens -- "
                f"imported files load at launch.",
        )

    ceffective, _ = strip_block_html_comments(ctext)
    clines = [l for l in ceffective.split("\n") if l.strip()]
    if len(clines) > CLAUDE_STUB_FAIL_LINES:
        report.add(
            "fail", "CLAUDE_TOO_LONG", cname,
            f"CLAUDE.md is {len(clines)} non-blank lines. Once AGENTS.md exists, "
            f"CLAUDE.md holds only the import and genuinely Claude-specific lines "
            f"such as plan-mode and subagent preferences.",
            fix=f"Move everything that is not Claude-specific into AGENTS.md. Do not "
                f"replace it with a listing of skills or .claude/rules/ files -- "
                f"Claude Code discovers both already. Cap is "
                f"{CLAUDE_STUB_FAIL_LINES} lines.",
        )
    elif len(clines) > CLAUDE_STUB_WARN_LINES:
        report.add(
            "warn", "CLAUDE_GROWING", cname,
            f"CLAUDE.md is {len(clines)} non-blank lines. Anything here that is not "
            f"specific to Claude Code belongs in AGENTS.md.",
        )

    # Duplication instead of import: a copied CLAUDE.md goes stale against
    # AGENTS.md without anyone noticing. A file that already imports AGENTS.md
    # and fits the stub cap is not that failure whatever the ratio says, and the
    # ratio is unreliable there anyway because the denominator is a handful of
    # lines.
    is_stub = imports_agents and len(clines) <= CLAUDE_STUB_WARN_LINES
    try:
        atext = read_text(agents)
    except OSError:
        return agents, claude
    aset = {l.strip() for l in atext.split("\n") if len(l.strip()) > 20}
    cset = {l.strip() for l in ctext.split("\n") if len(l.strip()) > 20}
    shared = sorted(aset & cset)
    if not is_stub and len(cset) >= CLAUDE_OVERLAP_MIN_LINES and shared:
        overlap = len(shared) / len(cset)
        if overlap > CLAUDE_OVERLAP_FAIL_RATIO:
            sample = shared[0][:60]
            report.add(
                "fail", "CLAUDE_DUPLICATES_AGENTS", cname,
                f"{overlap:.0%} of CLAUDE.md's substantive lines are copied from "
                f"AGENTS.md, starting with \"{sample}\". A duplicated copy goes "
                f"stale; an import does not.",
                fix="Delete the copied lines and keep `@AGENTS.md` plus only the "
                    "lines that are specific to Claude Code.",
            )

    return agents, claude


def report_size(root: Path, closure: Closure, report: Report) -> None:
    """Compare one measured closure against Claude Code's length budget.

    This function and ``report_codex`` below are the only two places in the
    checker where a measurement meets a threshold. ``Closure`` carries more
    measurements than this function reads; that is deliberate.
    """
    if not closure.files:
        return
    name = rel(root, closure.files[0])
    lines = closure.lines
    kb = closure.effective_bytes / 1024

    report.metrics["resolved_lines"] = lines
    report.metrics["resolved_bytes"] = closure.effective_bytes
    report.metrics["raw_bytes"] = closure.raw_bytes
    report.metrics["closure_files"] = [rel(root, f) for f in closure.files]

    closure_note = ""
    if len(closure.files) > 1:
        closure_note = (
            f" (resolved over {len(closure.files)} files: "
            + ", ".join(rel(root, f) for f in closure.files)
            + ")"
        )

    if lines > AGENTS_FAIL_LINES:
        report.add(
            "fail", "SIZE_FAIL", name,
            f"{lines} lines / {kb:.1f} KB{closure_note}. "
            f"Over the {AGENTS_FAIL_LINES}-line ceiling.",
            fix="Every surveyed instruction file over 300 lines had a diagnosable "
                "defect: concatenated docs, a machine-appended stale block, or one "
                "runaway procedure. Find that block and move it to a skill, a "
                "path-scoped rule under .claude/rules/, or docs/.",
        )
    elif lines > AGENTS_WARN_LINES:
        report.add(
            "warn", "SIZE_WARN", name,
            f"{lines} lines / {kb:.1f} KB{closure_note}. "
            f"Over the {AGENTS_WARN_LINES}-line warning threshold; the target is "
            f"{AGENTS_TARGET_LINES}.",
            fix="Cut in this order: preamble, Boundaries, Pointers. Never cut Rules first.",
        )
    elif lines > AGENTS_TARGET_LINES:
        report.add(
            "info", "SIZE_OVER_TARGET", name,
            f"{lines} lines / {kb:.1f} KB{closure_note}. "
            f"Over the {AGENTS_TARGET_LINES}-line target but under the warning "
            f"threshold.",
        )

    for importer, target in closure.missing:
        report.add(
            "warn", "IMPORT_MISSING", rel(root, importer),
            f"`@{target}` does not resolve to a file, so nothing is imported.",
            fix="Fix the path or delete the import. A broken import loads silently "
                "as nothing; the instructions you expect are simply absent.",
        )
    for importer, target in closure.external:
        report.add(
            "info", "IMPORT_EXTERNAL", rel(root, importer),
            f"`@{target}` resolves outside the repository.",
            fix="Claude Code asks the user to approve external imports in a project "
                "memory file the first time it sees them, and loads nothing from "
                "them if the user declines. Teammates will not have this file.",
        )


def report_codex(
    root: Path,
    chains: Sequence[CodexChain],
    config: CodexConfig,
    report: Report,
    host: Host = CODEX,
) -> None:
    """Compare the Codex load against Codex's own limits.

    Codex reads what is on disk: every byte of every file in the chain, comments
    and unexpanded import lines included. Once the running total reaches
    ``project_doc_max_bytes`` it truncates on a byte boundary and says nothing,
    so the size finding here is a hard failure where the Claude Code equivalent
    at that point is a warning about a file that still loads whole.

    ``host`` decides which of the per-file measurements become findings. An
    unexpanded import and a billed comment are defects only because this
    runtime does neither of the two things Claude Code does; a host whose table
    entry says otherwise is silent about them without any check changing.
    """
    if not chains:
        return

    limit = config.max_bytes
    warn_at = int(limit * CODEX_WARN_RATIO)
    budget_note = ""
    if config.source and limit != CODEX_DEFAULT_MAX_BYTES:
        budget_note = f" The limit comes from `{config.source}`."

    capped = _Capped(report, root)
    worst = max(chains, key=lambda c: c.raw_bytes)
    report.metrics["codex_chain_bytes"] = worst.raw_bytes
    report.metrics["codex_chain_files"] = [rel(root, f.path) for f in worst.files]
    report.metrics["codex_max_bytes"] = limit

    # Shallowest first, and a chain is skipped once an ancestor of its leaf has
    # already been reported: if the root file alone is over the limit then every
    # chain in the repository is over it for the same reason and has the same
    # fix. Reporting each one names the wrong file as the cause.
    reported: List[Path] = []
    for chain in sorted(chains, key=lambda c: len(c.files)):
        if any(chain.leaf == d or d in chain.leaf.parents for d in reported):
            continue
        name = rel(root, chain.files[-1].path)
        chain_note = ""
        if len(chain.files) > 1:
            chain_note = (
                f" {host.label} loads this as a chain of {len(chain.files)} files: "
                + ", ".join(rel(root, f.path) for f in chain.files) + "."
            )
        kib = chain.raw_bytes / 1024
        if chain.raw_bytes >= limit:
            capped.add(
                "fail", "CODEX_SIZE_FAIL", name,
                f"{chain.raw_bytes} bytes / {kib:.1f} KiB on disk, at or over the "
                f"{limit}-byte project_doc_max_bytes.{chain_note} {host.label} "
                f"truncates on a byte boundary and warns nobody, so the tail of "
                f"this file is silently absent.{budget_note}",
                host=host.key,
                fix="Cut content, or move it below the repository root so it "
                    "loads only for sessions working in that package. Raising "
                    "project_doc_max_bytes in .codex/config.toml moves the limit "
                    "but not the context cost.",
            )
            reported.append(chain.leaf)
        elif chain.raw_bytes >= warn_at:
            capped.add(
                "warn", "CODEX_SIZE_WARN", name,
                f"{chain.raw_bytes} bytes / {kib:.1f} KiB on disk, past "
                f"{int(CODEX_WARN_RATIO * 100)}% of the {limit}-byte "
                f"project_doc_max_bytes.{chain_note}{budget_note}",
                host=host.key,
                fix=f"There is no warning at the limit itself -- {host.label} "
                    f"simply stops reading. Cut before the chain reaches it.",
            )
            reported.append(chain.leaf)

    # Per-file findings are reported once per file, not once per chain that
    # contains it: a root AGENTS.md appears in every chain in the repository.
    for measured in _unique_codex_files(chains):
        name = rel(root, measured.path)
        for line, target in ([] if host.expands_imports else measured.imports):
            capped.add(
                "warn", "CODEX_IMPORT_LITERAL", name,
                f"`@{target}` is expanded by {CLAUDE_CODE.label} and not by "
                f"{host.label}, which has no import mechanism. {host.label} "
                f"passes this line through as literal text and never loads "
                f"`{target}`.",
                line=line, host=host.key,
                fix=f"Move what the target holds into this file, or keep the "
                    f"import only in CLAUDE.md, which {host.label} does not read.",
            )
        if measured.shadowed is not None:
            capped.add(
                "warn", "AGENTS_OVERRIDE_SHADOW", name,
                f"{host.label} reads one file per directory and takes this one "
                f"first, so `{rel(root, measured.shadowed)}` is never loaded in "
                f"a {host.label} session.",
                host=host.key,
                fix=f"Delete the override, or accept that it replaces the file "
                    f"beside it rather than adding to it. {CLAUDE_CODE.label} "
                    f"reads neither, so the two hosts diverge while this exists.",
            )
        if not host.strips_comments and measured.comment_bytes >= CODEX_COMMENT_WARN_BYTES and (
            measured.raw_bytes > 0
            and measured.comment_bytes / measured.raw_bytes >= CODEX_COMMENT_WARN_RATIO
        ):
            share = measured.comment_bytes / measured.raw_bytes
            capped.add(
                "warn", "CODEX_COMMENT_COST", name,
                f"Block-level HTML comments are {measured.comment_bytes} bytes, "
                f"{share * 100:.0f}% of this file. {CLAUDE_CODE.label} strips "
                f"them before injection; {host.label} does not, so in a "
                f"{host.label} session they occupy context and the model reads "
                f"them as part of the instructions.",
                host=host.key,
                fix=f"Move maintainer notes that are not meant for the model out "
                    f"of the file. A comment is free in {CLAUDE_CODE.label} and "
                    f"billed everywhere else.",
            )

    capped.flush()


class _Capped:
    """Emits at most ``REPEATED_FINDING_CAP`` findings per code, then a summary.

    Nested-package findings are unbounded -- a monorepo can have hundreds -- and
    every one of them has the same fix. The overflow finding names the code and
    the number withheld so the report never understates what was found.
    """

    def __init__(self, report: Report, root: Path) -> None:
        self._report = report
        self._root = root
        self._counts: Dict[str, int] = {}
        self._withheld: Dict[str, int] = {}

    def add(self, severity: str, code: str, *args, **kwargs) -> None:
        seen = self._counts.get(code, 0)
        self._counts[code] = seen + 1
        if seen < REPEATED_FINDING_CAP:
            self._report.add(severity, code, *args, **kwargs)
        else:
            self._withheld[code] = self._withheld.get(code, 0) + 1

    def flush(self) -> None:
        for code in sorted(self._withheld):
            held = self._withheld[code]
            self._report.add(
                "info", "MORE_OF_THE_SAME", ".",
                f"{held} further `{code}` findings exist and are not in this "
                f"report, in text or in --json. {self._counts[code]} were found "
                f"in total; the first {REPEATED_FINDING_CAP} are listed above "
                f"and the fix is the same for all of them.",
                fix="Fix the listed ones and run again for the next batch. The "
                    "cap keeps one repeated defect from burying every other "
                    "finding in the report.",
            )


def _unique_codex_files(chains: Sequence[CodexChain]) -> List[CodexFile]:
    """Every distinct file across the chains, in a stable order."""
    seen: Set[Path] = set()
    out: List[CodexFile] = []
    for chain in chains:
        for measured in chain.files:
            if measured.path in seen:
                continue
            seen.add(measured.path)
            out.append(measured)
    return out


def report_nested_pairs(
    root: Path,
    directories: Sequence[Path],
    config: CodexConfig,
    report: Report,
) -> None:
    """Report packages where the two hosts disagree about what loads.

    Below the repository root the hosts are exact opposites: Claude Code loads a
    nested CLAUDE.md when it reads files in that directory and never reads a
    nested AGENTS.md, while Codex loads the nested AGENTS.md and never looks at
    CLAUDE.md. A package therefore needs both files, and the one that is missing
    is invisible to exactly one host.
    """
    # The root pair has its own, fuller check, and .claude is one of the two
    # places that pair's CLAUDE.md is allowed to live -- it is host
    # configuration, not a package that needs an AGENTS.md of its own.
    capped = _Capped(report, root)
    host_dirs = {root, (root / ".codex")}
    for location in CLAUDE_MD_LOCATIONS:
        host_dirs.add((root / location).parent)

    # A repository that lists CLAUDE.md in project_doc_fallback_filenames has
    # told Codex to read it where no AGENTS.md exists, so the file is not
    # invisible to Codex and saying it is would be wrong.
    codex_reads_claude = "CLAUDE.md" in config.filenames

    for directory in directories:
        if directory in host_dirs:
            continue
        rel_dir = rel(root, directory)
        agents = directory / "AGENTS.md"
        claude = directory / "CLAUDE.md"
        try:
            has_agents = agents.is_file()
            has_claude = claude.is_file()
        except OSError:
            continue

        if has_agents and not has_claude:
            capped.add(
                "warn", "NESTED_NO_CLAUDE", rel(root, agents),
                f"Codex loads this file for sessions working in `{rel_dir}`, but "
                f"Claude Code never reads an AGENTS.md at any level, so none of "
                f"it reaches Claude.",
                host=CLAUDE_CODE.key,
                fix=f"Add `{rel_dir}/CLAUDE.md` containing `@AGENTS.md`. Claude "
                    f"Code loads a nested CLAUDE.md on demand when it reads "
                    f"files in that directory.",
            )
        elif has_claude and not has_agents and not codex_reads_claude:
            capped.add(
                "warn", "NESTED_NO_AGENTS", rel(root, claude),
                f"Claude Code loads this file on demand, but Codex reads no "
                f"CLAUDE.md, so nothing here reaches a Codex session working in "
                f"`{rel_dir}`.",
                host=CODEX.key,
                fix=f"Move the content to `{rel_dir}/AGENTS.md` and leave "
                    f"`@AGENTS.md` here. Both hosts then load the same text.",
            )
        elif has_agents and has_claude:
            try:
                wanted = agents.resolve()
            except (OSError, RuntimeError):
                continue
            # A symlink to the sibling AGENTS.md satisfies the stub contract the
            # same way it does at the repository root: the two files are one
            # file, so they cannot drift. Reading through it would see the
            # target's text and report a missing import that is not missing.
            if claude.is_symlink():
                try:
                    if claude.resolve() == wanted:
                        continue
                except (OSError, RuntimeError):
                    pass
            try:
                text = read_text(claude)
            except (OSError, RuntimeError):
                continue
            imported = False
            for target in find_imports(text):
                candidate = Path(os.path.expanduser(target))
                if not candidate.is_absolute():
                    candidate = claude.parent / candidate
                try:
                    if candidate.resolve() == wanted:
                        imported = True
                        break
                except (OSError, RuntimeError):
                    continue
            if not imported:
                capped.add(
                    "warn", "NESTED_NOT_STUB", rel(root, claude),
                    f"This file does not import `{rel(root, agents)}` beside it, "
                    f"so the two carry separate text and the hosts read "
                    f"different instructions for `{rel_dir}`.",
                    fix="Make the body `@AGENTS.md` plus only what is specific "
                        "to Claude Code. One file is the source; the other "
                        "points at it.",
                )

    capped.flush()


def check_structure(root: Path, doc: ParsedDoc, report: Report, project_root: Path) -> None:
    name = rel(root, doc.path)

    # Marker integrity matters regardless of how short the file is: an
    # unbalanced pair makes Spec Kit overwrite the rest of the file.
    _check_speckit(root, doc, report, project_root)

    if doc.unclosed_comment is not None:
        report.add(
            "fail", "HTML_COMMENT_UNCLOSED", name,
            "An HTML comment opens here and never closes.",
            line=doc.unclosed_comment + 1,
            fix="Add the missing `-->`. Claude Code keeps an unterminated comment "
                "verbatim, so everything below this line is loading into context as "
                "instructions even though it reads as a maintainer note.",
        )
    if doc.unclosed_fence is not None:
        report.add(
            "fail", "FENCE_UNCLOSED", name,
            "A fenced code block opens here and never closes.",
            line=doc.unclosed_fence + 1,
            fix="Close the fence. Everything below it is parsed as code, so no "
                "section, cap or content check applies to the rest of the file.",
        )

    if doc.is_pointer:
        report.add(
            "info", "POINTER_FILE", name,
            "Pointer file; structural checks skipped.",
        )
        return

    if len(doc.preamble) > PREAMBLE_WARN_LINES:
        report.add(
            "warn", "PREAMBLE_TOO_LONG", name,
            f"The preamble before the first heading is {len(doc.preamble)} non-blank "
            f"lines; the cap is {PREAMBLE_WARN_LINES}.",
            line=1,
            fix="One or two sentences on what this repository is responsible for. "
                "No history, no marketing, no technology inventory.",
        )

    seen: Dict[str, Section] = {}
    positions: List[Tuple[int, str]] = []

    for sec in doc.sections:
        if sec.normalized in SPLIT_HEADINGS:
            _, message = SPLIT_HEADINGS[sec.normalized]
            report.add(
                "warn", f"SPLIT_{SPLIT_HEADINGS[sec.normalized][0].upper()}", name,
                f"`{sec.raw_heading}` is not a section in this standard.",
                section=sec.raw_heading, line=sec.start_line, fix=message,
            )
            continue

        if sec.canonical is None:
            report.add(
                "info", "UNKNOWN_SECTION", name,
                f"`{sec.raw_heading}` is not a recognized section.",
                section=sec.raw_heading, line=sec.start_line,
                fix="Either map it onto one of "
                    + ", ".join(f"`## {s}`" for s in SECTION_ORDER)
                    + ", or move the content to a skill, a path-scoped rule, or docs/.",
            )
            continue

        canonical = sec.canonical
        if canonical in seen:
            report.add(
                "warn", "DUPLICATE_SECTION", name,
                f"`{sec.raw_heading}` is a second `{canonical}` section.",
                section=sec.raw_heading, line=sec.start_line,
                fix=f"Merge it into the earlier `## {canonical}`.",
            )
        else:
            seen[canonical] = sec
            positions.append((SECTION_ORDER.index(canonical), canonical))

        if sec.raw_heading.strip() != canonical:
            report.add(
                "info", "SECTION_RENAME", name,
                f"`{sec.raw_heading}` maps to `{canonical}`.",
                section=sec.raw_heading, line=sec.start_line,
                fix=f"Rename the heading to `## {canonical}` so the section set stays "
                    f"identical across repositories.",
            )

        cap = SECTION_CAPS[canonical]
        # Counted over every non-blank body line, fenced code included. A
        # fenced block occupies a section of an always-loaded file exactly as
        # much as the same number of bullets, and Commands and Boundaries are
        # where that volume collects.
        used = sec.total_lines
        if used > cap * 2:
            report.add(
                "fail", "SECTION_CAP_FAIL", name,
                f"`{canonical}` is {used} non-blank lines against a cap of {cap}.",
                section=canonical, line=sec.start_line,
                fix="At more than double the cap this is no longer a section of an "
                    "always-loaded file. Move the bulk to a skill or a path-scoped rule.",
            )
        elif used > cap:
            report.add(
                "warn", "SECTION_CAP_WARN", name,
                f"`{canonical}` is {used} non-blank lines against a cap of {cap}.",
                section=canonical, line=sec.start_line,
            )

        _check_section_content(root, project_root, name, canonical, sec, doc, report)

    for required in REQUIRED_SECTIONS:
        if required not in seen:
            report.add(
                "warn", f"MISSING_{required.upper()}", name,
                f"No `## {required}` section.",
                fix={
                    "Rules": "Rules is the one section with affirmative evidence "
                             "that agents follow it. If the repository truly has no "
                             "invariant a checker does not already enforce, omitting "
                             "it is correct -- but verify that first.",
                    "Commands": "List the build, test and lint invocations an agent "
                                "cannot guess from the manifest. Every command must "
                                "have been run.",
                }[required],
            )

    ordered = [c for _, c in positions]
    expected = sorted(ordered, key=SECTION_ORDER.index)
    if ordered != expected:
        report.add(
            "warn", "SECTION_ORDER", name,
            "Sections are out of order: " + " -> ".join(ordered),
            fix="The standard fixes the order as "
                + " -> ".join(SECTION_ORDER)
                + ". Rules goes first because it is the highest-value content and "
                  "the last thing to cut under budget pressure. The order is a "
                  "convention, not a measured adherence effect.",
        )

    # Emphasis is counted over prose only. Fenced commands contain these tokens
    # for reasons that have nothing to do with emphasis, and the SPECKIT block
    # cannot be edited by the author this finding would address.
    emphasis_text = "\n".join(
        doc.preamble + [strip_fences("\n".join(s.lines)) for s in doc.sections]
    )
    emphasis = len(EMPHASIS_RE.findall(emphasis_text))
    if emphasis > EMPHASIS_TOKEN_WARN:
        report.add(
            "warn", "EMPHASIS_INFLATION", name,
            f"{emphasis} all-caps emphasis tokens "
            f"({' / '.join(EMPHASIS_TOKENS)}).",
            fix="If many lines are emphasized, none of them stands out. Keep the "
                "emphasis for the few rules that actually carry it, and make anything "
                "that must hold every time a hook or a CI check instead.",
        )


def _check_section_content(
    root: Path, project_root: Path, name: str, canonical: str,
    sec: Section, doc: ParsedDoc, report: Report,
) -> None:
    body = "\n".join(sec.lines)
    fences = scan_fences(body)
    blanked = fences.blanked

    if canonical == "Commands":
        if not sec.has_fence:
            report.add(
                "warn", "COMMANDS_NO_FENCE", name,
                "`Commands` contains no fenced code block.",
                section=canonical, line=sec.start_line,
                fix="Commands must be copy-pasteable. Put them in a fenced block.",
            )
        prose, code = sec.prose_lines, sec.code_lines
        if prose >= 15 and code > 0 and prose > code * 4:
            report.add(
                "warn", "COMMANDS_TUTORIAL", name,
                f"`Commands` is {prose} prose lines around {code} command lines.",
                section=canonical, line=sec.start_line,
                fix="This reads like a setup tutorial. Keep the invocations plus at "
                    "most a few lines of environment gotchas; install narrative "
                    "belongs in CONTRIBUTING.md.",
            )

    if canonical == "Boundaries":
        # Only a fence the section itself opens counts: a ```mermaid line
        # nested inside an outer example fence is quoted text, not a diagram.
        for offset, line in enumerate(sec.lines):
            if offset in fences.opens and DIAGRAM_FENCE_RE.match(line):
                report.add(
                    "fail", "BOUNDARIES_DIAGRAM", name,
                    "`Boundaries` contains a diagram fence.",
                    section=canonical, line=sec.start_line + offset + 1,
                    fix="Diagrams and rationale go to docs/ and are linked from "
                        "`## Pointers`. This section holds only ownership and "
                        "dependency direction, as sentences.",
                )
                break
        # Trees are scanned on the un-blanked body, because a directory tree is
        # nearly always written inside a fence -- unfenced it collapses into a
        # single rendered paragraph.
        for offset, line in enumerate(strip_code_spans(body).split("\n")):
            if BOX_DRAWING_RE.search(line):
                report.add(
                    "fail", "BOUNDARIES_TREE", name,
                    "`Boundaries` contains a drawn directory tree.",
                    section=canonical, line=sec.start_line + offset + 1,
                    fix="Delete it. Directory layouts are derivable from the "
                        "repository. Keep only rules the agent cannot read off the "
                        "code, such as 'deployment depends on runtime, never the reverse'.",
                )
                break
        if IMAGE_RE.search(blanked):
            report.add(
                "fail", "BOUNDARIES_IMAGE", name,
                "`Boundaries` embeds an image.",
                section=canonical, line=sec.start_line,
                fix="Link it from docs/ instead.",
            )

    if canonical == "Contributing":
        ordered_items = sum(1 for l in blanked.split("\n") if ORDERED_ITEM_RE.match(l))
        step_headings = sum(1 for l in blanked.split("\n") if STEP_HEADING_RE.match(l))
        # The facts this section is supposed to hold -- branch naming, PR title
        # format, who merges -- are commonly three items, so the threshold sits
        # above three to leave them alone.
        if ordered_items >= CONTRIBUTING_STEP_WARN or step_headings >= 2:
            report.add(
                "warn", "CONTRIBUTING_PROCEDURE", name,
                f"`Contributing` contains a {max(ordered_items, step_headings)}-step "
                f"procedure.",
                section=canonical, line=sec.start_line,
                fix="A procedure with steps is a skill. Keep the facts here (branch "
                    "naming, PR title format, required commit trailer, who merges, "
                    "what the agent may do on your behalf) and link the skill in one line.",
            )

    if canonical == "Pointers":
        for offset, entry in _logical_entries(blanked):
            links = LINK_RE.findall(entry)
            if not links:
                continue
            without_links = LINK_RE.sub(" ", entry)
            # A purpose clause is prose, not a word count: a word threshold
            # rejects short but complete clauses and is satisfied by padding.
            if not re.search(r"[A-Za-z]{3,}(\s+\S+){2,}", without_links):
                report.add(
                    "warn", "BLIND_REFERENCE", name,
                    f"Pointer `{links[0][0] or links[0][1]}` carries no purpose clause.",
                    section=canonical, line=sec.start_line + offset + 1,
                    fix="State what is in the target and when to read it. A bare link "
                        "is a documented defect and is frequently not followed.",
                )

    if canonical in ("Pointers", "Boundaries"):
        _check_paths_resolve(project_root, name, canonical, sec, doc, report)

    if canonical == "Rules":
        configs = [c for c in FORMATTER_CONFIGS if (project_root / c).exists()]
        if configs:
            lowered = strip_code_spans(blanked).lower()
            hits = []
            for keyword, pattern in LINT_LEAKAGE_RES:
                if not pattern.search(lowered):
                    continue
                if keyword in LINT_LEAKAGE_WEAK and not LINT_LEAKAGE_WEAK_CONTEXT.search(lowered):
                    continue
                hits.append(keyword)
            if hits:
                report.add(
                    "warn", "LINT_LEAKAGE", name,
                    f"`Rules` mentions {', '.join(sorted(set(hits))[:4])} while "
                    f"{configs[0]} exists in the repository.",
                    section=canonical, line=sec.start_line,
                    fix=f"Restating a rule {configs[0]} already enforces is the single "
                        f"most common defect measured in real instruction files. Delete "
                        f"the line and name the check in `## Commands` instead. This "
                        f"check is a keyword match, not a judgment: run "
                        f"/instruction-keeper:audit for the rules it cannot see.",
                )


def _logical_entries(body: str) -> List[Tuple[int, str]]:
    """Group a section body into list entries, each joined with its wrapped
    continuation lines.

    A pointer's purpose clause routinely wraps onto the next line. Judging one
    physical line at a time would call that entry bare, which is the opposite of
    what it is. The returned offset is the entry's first line, so a finding still
    points at the link.
    """
    entries: List[Tuple[int, str]] = []
    start: Optional[int] = None
    buf: List[str] = []
    for offset, line in enumerate(body.split("\n")):
        opens = re.match(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+\S", line)
        if opens or (start is None and line.strip()):
            if start is not None:
                entries.append((start, " ".join(buf)))
            start, buf = offset, [line.strip()]
        elif start is not None and line.strip():
            buf.append(line.strip())
        elif start is not None:
            entries.append((start, " ".join(buf)))
            start, buf = None, []
    if start is not None:
        entries.append((start, " ".join(buf)))
    return entries


def _looks_like_repo_path(target: str) -> bool:
    """Whether a bare code span is plausibly a path in this repository.

    Route fragments (`/api/v1/users`), branch names (`release/1.2`) and opaque
    URIs appear in instruction files in backticks but are not filesystem paths,
    so they are outside what this check can judge.
    """
    if not target or URI_SCHEME_RE.match(target):
        return False
    if target.startswith(("/", "~", "#")):
        return False
    if "/" not in target:
        return False
    last = target.rstrip("/").rsplit("/", 1)[-1]
    if VERSION_SEGMENT_RE.match(last):
        return False
    return target.endswith("/") or "." in last


def _check_paths_resolve(
    project_root: Path, name: str, canonical: str, sec: Section,
    doc: ParsedDoc, report: Report,
) -> None:
    body = strip_fences("\n".join(sec.lines))
    base_dir = doc.path.parent
    candidates: List[Tuple[int, str]] = []
    for offset, line in enumerate(body.split("\n")):
        for _, target in LINK_RE.findall(line):
            if URI_SCHEME_RE.match(target) or target.startswith("#"):
                continue
            candidates.append((offset, target.split("#")[0]))
        for span in BARE_PATH_RE.findall(line):
            if " " not in span and _looks_like_repo_path(span):
                candidates.append((offset, span))

    for offset, target in candidates:
        clean = target.strip()
        if not clean or clean.startswith("~"):
            continue
        if "*" in clean or "<" in clean:
            continue
        # Strip exactly the "./" prefix, character by character rather than as
        # a character set, so that the leading dot of .claude/ and .github/
        # survives.
        while clean.startswith("./"):
            clean = clean[2:]
        if not clean:
            continue
        candidate = base_dir / clean
        if not _within(candidate, project_root):
            continue  # escapes the repository; not ours to verify
        if not candidate.exists():
            report.add(
                "warn", "STALE_PATH", name,
                f"`{target}` does not exist.",
                section=canonical, line=sec.start_line + offset + 1,
                fix="Fix or remove the reference. A stale path in an always-loaded "
                    "file sends the agent somewhere that is not there.",
            )


def _check_speckit(root: Path, doc: ParsedDoc, report: Report, project_root: Path) -> None:
    name = rel(root, doc.path)
    uses_speckit = (project_root / ".specify").is_dir()
    start_marker, end_marker = doc.speckit_markers

    # Markers are located on a view with code spans and fences removed, so that
    # a file documenting the Spec Kit convention by quoting a marker is not read
    # as carrying one.
    scannable = strip_code_spans(strip_fences(doc.text))
    start_re = re.compile(re.escape(start_marker).replace(r"\ ", r"\s+"), re.I)
    end_re = re.compile(re.escape(end_marker).replace(r"\ ", r"\s+"), re.I)
    start_at = start_re.search(scannable)
    end_at = end_re.search(scannable)

    if bool(start_at) != bool(end_at):
        report.add(
            "fail", "SPECKIT_UNBALANCED", name,
            "Only one of the SPECKIT start/end markers is present.",
            fix="Restore both markers. Spec Kit's agent-context extension rewrites "
                "everything between them; an unbalanced pair makes it overwrite the "
                "rest of the file.",
        )
        return

    if not start_at:
        if uses_speckit:
            report.add(
                "info", "SPECKIT_ABSENT", name,
                "This repository uses Spec Kit but the file carries no SPECKIT block.",
                fix="If the agent-context extension is installed, it will append its "
                    "managed block on the next run. Leave room for it at the end of "
                    "the file and never edit inside the markers.",
            )
        return

    if start_at.start() > end_at.start():
        report.add(
            "fail", "SPECKIT_REVERSED", name,
            "The SPECKIT end marker appears before the start marker.",
            fix="Put the start marker first. In this order the extension has no "
                "well-defined region to rewrite.",
        )
        return

    if not uses_speckit:
        report.add(
            "info", "SPECKIT_ORPHAN", name,
            "SPECKIT markers are present but no .specify/ directory exists.",
            fix="Remove the block, or restore the Spec Kit installation that owns it.",
        )
        return

    span = doc.speckit_span
    total = len(doc.text.split("\n"))
    if span and span[1] < total - 1:
        trailing = [l for l in doc.text.split("\n")[span[1] + 1:] if l.strip()]
        if trailing:
            report.add(
                "info", "SPECKIT_NOT_LAST", name,
                f"The SPECKIT managed block is not at the end of the file; "
                f"{len(trailing)} non-blank line(s) follow it.",
                fix="Keep it last. It is rewritten in place by "
                    "scripts/update_agent_context.py, so anything after it is harder "
                    "to reason about when the block changes length.",
            )
    report.add(
        "info", "SPECKIT_PROTECTED", name,
        "SPECKIT managed block detected. It is excluded from section parsing and "
        "from every content check, and counted in the size budget because it "
        "occupies context like any other line.",
        fix="Never edit between the markers; Spec Kit owns that region.",
    )


# --------------------------------------------------------------------------
# Diff scoping
# --------------------------------------------------------------------------


def state_path(project_root: Path) -> Optional[Path]:
    """Where the --new-only baseline for a repository lives, or None.

    Keyed by a digest of the absolute root so that several checkouts of the same
    project do not share a baseline. It lives outside the repository because a
    baseline is machine-local state that must never be committed.

    A per-user directory is preferred over the shared temp directory: the keys
    in this file suppress findings, so a world-writable location would let any
    other local account silently switch warnings off. Returns None when no
    directory can be created -- a hardened image with no home directory is a
    reason to skip diff scoping, never a reason to fail the run.
    """
    digest = hashlib.sha1(str(project_root.resolve()).encode("utf-8")).hexdigest()[:16]

    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        base = Path(xdg) / "instruction-keeper"
    elif os.name != "nt" and Path.home() != Path("/"):
        base = Path.home() / ".local" / "state" / "instruction-keeper"
    else:
        uid = getattr(os, "geteuid", lambda: "user")()
        base = Path(tempfile.gettempdir()) / f"instruction-keeper-{uid}"

    try:
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            os.chmod(base, 0o700)
    except OSError:
        return None
    return base / f"{digest}.json"


def load_state(project_root: Path) -> Dict[str, object]:
    p = state_path(project_root)
    if p is None or not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(project_root: Path, keys: Iterable[str]) -> None:
    """Write the baseline atomically.

    Hook invocations can overlap, and a partially written baseline is unreadable
    on the next run, which would re-report every finding it was meant to
    suppress.
    """
    p = state_path(project_root)
    if p is None:
        return
    payload = json.dumps({"keys": sorted(set(keys))}, indent=0)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".ik-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, str(p))
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except OSError:
        pass


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

ICON = {"fail": "FAIL", "warn": "WARN", "info": "INFO"}
HOST_LABELS = {h.key: h.label for h in HOSTS}


def budget_line(report: Report) -> Optional[str]:
    """One line per host, stating what it loads against its own limit.

    Printed on every run, including a clean one. These are not findings: a
    conforming file has none, and the skills still need a number to report. The
    two lines use different units because the runtimes do -- Claude Code loads a
    resolved closure and Codex loads bytes from disk.
    """
    out: List[str] = []
    lines = report.metrics.get("resolved_lines")
    if lines is not None:
        kb = float(report.metrics.get("resolved_bytes", 0)) / 1024
        files = report.metrics.get("closure_files") or []
        over = ", ".join(str(f) for f in files)
        out.append(
            f"instruction-keeper: {CLAUDE_CODE.label} loads {lines} lines / "
            f"{kb:.1f} KB over {over} (target {AGENTS_TARGET_LINES}, "
            f"warn {AGENTS_WARN_LINES}, fail {AGENTS_FAIL_LINES})."
        )

    codex_bytes = report.metrics.get("codex_chain_bytes")
    if codex_bytes is not None:
        limit = int(report.metrics.get("codex_max_bytes", CODEX_DEFAULT_MAX_BYTES))
        files = report.metrics.get("codex_chain_files") or []
        over = ", ".join(str(f) for f in files)
        # KiB rather than the KB the Claude Code line uses: Codex's limit is a
        # binary quantity documented as 32 KiB, and rounding it to a decimal
        # kilobyte in the same breath as the exact byte counts would be wrong.
        out.append(
            f"instruction-keeper: {CODEX.label} loads "
            f"{float(codex_bytes) / 1024:.1f} KiB over {over} "
            f"(limit {float(limit) / 1024:.0f} KiB, truncated silently past it)."
        )
    return "\n".join(out) if out else None


def render(report: Report, show_info: bool = True) -> str:
    findings = [f for f in report.findings if show_info or f.severity != "info"]
    findings.sort(key=lambda f: (-SEVERITY_RANK[f.severity], f.file, f.line or 0))
    budget = budget_line(report)
    if not findings:
        return "\n".join([b for b in (budget, "instruction-keeper: no findings.") if b])
    out: List[str] = []
    if budget:
        out += [budget, ""]
    for f in findings:
        where = f.file
        if f.line:
            where += f":{f.line}"
        label = HOST_LABELS.get(f.host or "")
        suffix = f"  ({label})" if label else ""
        out.append(f"{ICON[f.severity]}  {where}  [{f.code}]{suffix}")
        out.append(f"      {f.message}")
        if f.fix:
            for i, chunk in enumerate(_wrap(f.fix, 86)):
                out.append(f"      {'-> ' if i == 0 else '   '}{chunk}")
        out.append("")
    counts = {s: sum(1 for f in report.findings if f.severity == s) for s in ICON}
    out.append(
        f"{counts['fail']} failure(s), {counts['warn']} warning(s), {counts['info']} note(s)."
    )
    return "\n".join(out)


def _wrap(text: str, width: int) -> List[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def run(project_root: Path, targets: Optional[Sequence[Path]] = None) -> Report:
    """Check a repository and collect every finding.

    Args:
        project_root: Repository root. Paths in findings are reported relative
            to it, and path-resolution checks are anchored to it.
        targets: Specific files to check. Defaults to the root ``AGENTS.md`` and
            ``CLAUDE.md`` pair.
    """
    report = Report()
    report.metrics["hosts"] = [h.key for h in HOSTS]
    agents, claude = check_file_pair(project_root, report)

    # Claude Code's budget is the union of both closures, because every line
    # either file imports loads on every request. A stub that is short in itself
    # can still pull in an arbitrarily large file.
    seen: Set[Path] = set()
    closure = Closure()
    for path in (agents, claude):
        if path is not None and path.is_file():
            measure_closure(path, project_root, closure, seen=seen)
    report_size(project_root, closure, report)

    # Codex reads different files under different rules, so it is measured
    # separately and compared against its own limit.
    codex_config = read_codex_config(project_root)
    directories, truncated = codex_directories(project_root, codex_config)
    if truncated:
        report.metrics["codex_scan_truncated"] = True
    report_codex(
        project_root, codex_chains(project_root, codex_config, directories),
        codex_config, report,
    )
    report_nested_pairs(project_root, directories, codex_config, report)

    if targets:
        to_check = list(targets)
        for path in to_check:
            if not path.is_file():
                report.add(
                    "warn", "TARGET_MISSING", rel(project_root, path),
                    "Requested file does not exist, so nothing about it was checked.",
                    fix="Check the path. Silence about a file that was never read is "
                        "not a clean bill of health.",
                )
    else:
        to_check = [p for p in (agents, claude) if p]

    for path in to_check:
        if not path.is_file():
            continue
        if path.name == "CLAUDE.md" and agents is not None:
            # CLAUDE.md is a stub once AGENTS.md exists; the pair check covers
            # its whole contract. Say so rather than returning silence.
            if targets:
                report.add(
                    "info", "TARGET_IS_STUB", rel(project_root, path),
                    "CLAUDE.md is checked as a stub against AGENTS.md, not as a "
                    "standalone instruction file.",
                    fix="The section and cap checks apply to AGENTS.md. Run the "
                        "checker without a path argument to see them.",
                )
            continue
        try:
            text = read_text(path)
        except OSError as exc:
            report.add(
                "warn", "FILE_UNREADABLE", rel(project_root, path),
                "The file exists but could not be read (%s), so nothing about it "
                "was checked." % exc.__class__.__name__,
                fix="Check the file's permissions. Silence about a file that was "
                    "never read is not a clean bill of health.",
            )
            continue
        doc = parse(path, text, project_root)
        check_structure(project_root, doc, report, project_root)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Check AGENTS.md / CLAUDE.md against the instruction-keeper standard."
    )
    ap.add_argument("paths", nargs="*", type=Path,
                    help="Files to check. Defaults to AGENTS.md and CLAUDE.md at the root.")
    ap.add_argument("--project-root", type=Path, default=None,
                    help="Repository root. Defaults to $CLAUDE_PROJECT_DIR or the cwd.")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    ap.add_argument("--quiet-info", action="store_true", help="Hide informational findings.")
    ap.add_argument("--new-only", action="store_true",
                    help="Report only findings not seen on a previous run, and update "
                         "the stored baseline. Used by the PostToolUse hook.")
    args = ap.parse_args(argv)

    root = args.project_root or Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    root = root.resolve()
    if not root.is_dir():
        print(f"instruction-keeper: {root} is not a directory", file=sys.stderr)
        return 2

    # Relative positional paths belong to the repository being checked, not to
    # wherever the shell happens to be.
    targets = None
    if args.paths:
        targets = [p if p.is_absolute() else (root / p) for p in args.paths]

    try:
        report = run(root, targets)
    except Exception as exc:  # noqa: BLE001 - a checker must never break the session
        print(f"instruction-keeper: internal error: {exc}", file=sys.stderr)
        return 2

    findings = report.findings
    if args.new_only:
        try:
            previous = set(load_state(root).get("keys", []))
            current = {f.key() for f in findings}
            findings = [f for f in findings if f.key() not in previous]
            save_state(root, current)
        except Exception as exc:  # noqa: BLE001
            print(f"instruction-keeper: internal error: {exc}", file=sys.stderr)
            return 2

    if args.quiet_info:
        findings = [f for f in findings if f.severity != "info"]

    if args.json:
        print(json.dumps({
            "findings": [asdict(f) for f in findings],
            "metrics": report.metrics,
            "failed": any(f.severity == "fail" for f in findings),
        }, indent=2))
    else:
        filtered = Report(findings=findings, metrics=report.metrics)
        print(render(filtered, show_info=not args.quiet_info))

    # The exit code reflects the file's state, not the diff. --new-only narrows
    # what is printed so a hook does not repeat itself; a standing failure is
    # still a failure.
    return 1 if any(f.severity == "fail" for f in report.findings) else 0


if __name__ == "__main__":
    sys.exit(main())
