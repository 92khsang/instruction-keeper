# instruction-keeper

A Claude Code plugin that keeps `AGENTS.md` and `CLAUDE.md` inside a fixed
structure with explicit admission tests and enforced length budgets.

Instruction files grow monotonically, and two separate studies say what they
grow into. This plugin's own survey of 195 files across 176 well-known open
source repositories found that every file over 300 lines had a diagnosable
defect rather than a justified reason for its size. A separate catalog of
instruction-file defects across 100 repositories found the most common defect
of all — restating a rule a linter already enforces — in 62% of the files it
examined; that figure is not from this plugin's survey. Both sources, and what they do not
support, are in `skills/instruction-standard/references/evidence.md`.

## The standard in one screen

`AGENTS.md` is the real file. `CLAUDE.md` is a stub that imports it:

```markdown
@AGENTS.md

## Claude Code

Use plan mode for changes under `src/billing/`.
```

Claude Code reads `CLAUDE.md`, not `AGENTS.md`, so the import is what makes the
shared file reach Claude; coding agents that follow the AGENTS.md convention
read `AGENTS.md` directly. The import de-duplicates maintenance, not tokens. In
Claude Code an `@path` import loads at launch, resolves relative to the file
that contains it, and recurses at most four hops — so there is one budget and
it covers the pair.

Five sections, this order. `Rules` and `Commands` are expected: the checker
warns `MISSING_RULES` and `MISSING_COMMANDS` when either is absent. A warning,
not a failure — a repository with no invariant a checker does not already
enforce may legitimately omit `Rules`, but that is worth confirming rather than
assuming. The other three sections are omit-if-empty.

| # | Section | The one question it answers | Cap |
|---|---------|-----------------------------|-----|
| 0 | *(unheaded preamble)* | What is this repository responsible for? | 2 lines |
| 1 | `## Rules` | What must hold on every change? | 40 lines |
| 2 | `## Commands` | How do I build, run, and verify here? | 25 lines |
| 3 | `## Boundaries` | Where do ownership and dependency directions run? | 15 lines |
| 4 | `## Contributing` | How does a change reach main, and what may the agent do? | 20 lines |
| 5 | `## Pointers` | Where does everything else live? | 10 lines |

Total budget: **120 lines target, 200 warns, 400 fails**. It is measured over
the union of the `AGENTS.md` and `CLAUDE.md` `@`-import closures,
de-duplicated, after block-level HTML comments are stripped — Claude Code
removes those before injecting the file, so they cost nothing and are free for
maintainer notes. `CLAUDE.md` itself: 10 lines, hard fail past 20.

The two measurements differ on purpose. The closure budget counts **every
line, blanks included**, because a blank line occupies context like any other.
The per-section caps in the table and the `CLAUDE.md` cap count **non-blank
lines only**, and the per-section caps **include fenced code** — a fenced block
fills a section exactly as much as the same number of bullets, and `Commands`
and `Boundaries` are where that volume collects.

Three tests decide every line: is it true in **every** session, would an agent
reach it by **reading the repository**, and would **removing** it cause a
mistake? A fourth disqualifies content outright — if a rule must hold every time
regardless of judgment, it is a hook or a CI check, not a sentence in a file the
model is free to weigh.

Sections that are findings rather than sections, each with a destination:
`Testing` (split between `Commands` and `Rules`), `Code Style` (mostly deleted;
the linter owns it), `Setup` (folds into `Commands`), `Project Structure`
(deleted), `Project Overview` (two lines of preamble), `Troubleshooting` (a
skill).

## What you get

| Component | Name | Purpose |
|---|---|---|
| Skill | `instruction-standard` | The standard itself. Loads automatically whenever an instruction file is being written or discussed. |
| Skill | `/instruction-keeper:audit` | Reports every deviation, separating what a script verified from what needs judgment. |
| Skill | `/instruction-keeper:init` | Analyses the repository and writes a conforming pair from scratch. |
| Skill | `/instruction-keeper:split` | Migrates an existing `CLAUDE.md` to the pair, routing content that does not belong to skills, rules, or `docs/`. |
| Agent | `instruction-keeper:instruction-auditor` | Autonomous audit, reachable by that scoped name in the `@`-mention list. Reads the repository's linter and CI config to decide which rules are already enforced — the judgment a keyword match cannot make. |
| Hook | `PostToolUse`, matcher `Write\|Edit` | Re-checks the root pair after Claude writes or edits it. Warns, never blocks; findings reach Claude's context and the user sees a one-line notice. Reports only what the edit introduced. Needs `python3` on `PATH`. It does not fire when a `Bash` command rewrites the file. |
| Script | `scripts/check_instructions.py` | Deterministic checker. Standard library only, Python 3.8+. |
| Tests | `tests/` | The checker's suite and the hook's. `python3 tests/run_all.py`, or either file on its own. |

## Installation

Requires `python3` on `PATH` — the checker and the hook are standard library
only, Python 3.8+. Without it the hook cannot start and the skills lose their
deterministic half.

For one session, without installing:

```bash
claude --plugin-dir /path/to/instruction-keeper
```

To install it, add this repository as a marketplace — it ships
`.claude-plugin/marketplace.json` — and install from it:

```bash
claude plugin marketplace add /path/to/instruction-keeper
claude plugin install instruction-keeper
```

The same two steps work as `/plugin marketplace add` and `/plugin install`
inside a session. Hooks load at session start, so restart Claude Code after
installing, or run `/reload-plugins`.

Note that Claude Code ships a builtin `/init`. Typing `/init` gets the builtin,
which generates a `CLAUDE.md` from a codebase scan; this plugin's command is
`/instruction-keeper:init` and writes the `AGENTS.md` pair instead.

## Using the checker directly

```bash
python3 scripts/check_instructions.py --project-root /path/to/repo
```

Whenever either file of the pair exists the run prints the budget first, a
clean one included, because a conforming file produces no findings and the
number is still worth seeing:

```
instruction-keeper: 18 lines / 0.3 KB over AGENTS.md, CLAUDE.md (target 120, warn 200, fail 400).
instruction-keeper: no findings.
```

| Flag | Effect |
|---|---|
| `[paths ...]` | Redirect the per-file structural checks to these files. The root-pair contract checks and the budget still run. A relative path resolves against `--project-root`, not against the shell's working directory. A path that does not exist is reported as `TARGET_MISSING` rather than passing in silence. Naming `CLAUDE.md` while `AGENTS.md` exists yields the `TARGET_IS_STUB` note: the section and cap checks live on `AGENTS.md`. |
| `--project-root DIR` | Repository root. Defaults to the `CLAUDE_PROJECT_DIR` environment variable, then the working directory. |
| `--json` | Machine-readable output: `findings`, `failed`, and `metrics` — `resolved_lines`, `resolved_bytes`, `raw_bytes`, `closure_files`, the same numbers as the budget line. |
| `--quiet-info` | Hide informational findings. Works with `--json` as well as with the text output. |
| `--new-only` | Report only findings not seen on the previous run, and update the baseline. Findings are keyed by file, code, section and message, deliberately not by line number, so inserting a paragraph does not re-report everything below it. Used by the hook. |

### Severities and exit codes

Exit codes: `0` no failures, `1` at least one failure, `2` usage or internal
error.

**Only the fail severity moves the exit code.** Warnings and notes exit `0`, and
most codes are warnings — a file can be well over the target, past the 200-line
warning threshold, and still pass CI:

```
instruction-keeper: 247 lines / 4.3 KB over AGENTS.md, extra.md, CLAUDE.md (target 120, warn 200, fail 400).

WARN  AGENTS.md  [SIZE_WARN]
      247 lines / 4.3 KB (resolved over 3 files: AGENTS.md, extra.md, CLAUDE.md). Over the 200-line warning threshold; the target is 120.
      -> Cut in this order: preamble, Boundaries, Pointers. Never cut Rules first.

0 failure(s), 1 warning(s), 0 note(s).
```

That run exits `0`. The thirteen fail codes are the whole of what an unmodified
CI gate catches:

`SIZE_FAIL`, `SECTION_CAP_FAIL` (past double a section's cap), `CLAUDE_TOO_LONG`,
`CLAUDE_NO_IMPORT`, `CLAUDE_DUPLICATES_AGENTS`, `CLAUDE_BROKEN_SYMLINK`,
`BOUNDARIES_DIAGRAM`, `BOUNDARIES_IMAGE`, `BOUNDARIES_TREE`, `FENCE_UNCLOSED`,
`HTML_COMMENT_UNCLOSED`, `SPECKIT_UNBALANCED`, `SPECKIT_REVERSED`.

Twenty-two further codes are warnings and ten are notes. To gate on more than the
failures, read `--json` and pick the threshold you want; the severities here are
set for an interactive editing loop, not for a build.

### What the checker can and cannot do

It verifies:

- size over the union closure, and the per-section and `CLAUDE.md` caps;
- the section allowlist, the section order, duplicate and unknown headings, and
  headings that are synonyms of a known section;
- the `CLAUDE.md` stub contract — import present, copy-instead-of-import,
  broken symlink, stub length. `.claude/CLAUDE.md` counts as the project file,
  and `CLAUDE_NO_IMPORT` matches the resolved target rather than the basename,
  so a `.claude/CLAUDE.md` must write `@../AGENTS.md`;
- `@`-import integrity: a target that does not exist is `IMPORT_MISSING`, and
  one resolving outside the repository is the `IMPORT_EXTERNAL` note, because
  Claude Code asks the user to approve an external import and loads nothing if
  they decline;
- link and path resolution **inside `Pointers` and `Boundaries` only** — no
  other section is scanned for paths, paths resolve relative to the file that
  contains them, and `mailto:` links, URL routes and branch names are not
  treated as paths;
- diagram, image and directory-tree detection in `Boundaries`, procedure
  detection in `Contributing`, tutorial prose and unfenced commands in
  `Commands`, missing purpose clauses on pointers, emphasis inflation;
- Spec Kit marker integrity;
- malformed markup that would otherwise swallow the rest of the file: an
  unterminated `<!--` is `HTML_COMMENT_UNCLOSED` and an unterminated fence is
  `FENCE_UNCLOSED`, rather than a silently truncated parse.

One check crosses into judgment, and only just. `LINT_LEAKAGE` fires when
`## Rules` mentions something from a fixed keyword list — indentation, quote
style, semicolons, line length, trailing commas, import order — **and** a
formatter config exists in the repository (`.prettierrc`, `.editorconfig`,
`rustfmt.toml`, `eslint.config.js`, `ruff.toml` and a dozen others). It is one
deliberately narrow keyword match against the single most common measured
defect. It is not an assessment of enforcement: it cannot see what your linter
rules actually contain, what CI runs, or whether any other rule is already
enforced. That judgment stays with `/instruction-keeper:audit` and the
`instruction-auditor` agent, which read the linter and CI config.

Everything else carrying the intellectual weight of the standard is out of
reach for a script: whether a statement is inferable from the code, whether a
`Boundaries` entry is a responsibility or an inventory, whether a rule has an
incident behind it. **Silence from the checker is not approval.**

## Scope

The repository-root pair only — `AGENTS.md` plus `CLAUDE.md` or
`.claude/CLAUDE.md`. The checker governs that pair and nothing else.

A monorepo package that needs its own instructions gets **two** files, not one:
a nested `AGENTS.md` covering what differs in that package, and a nested
`CLAUDE.md` beside it whose content is the import of that `AGENTS.md`. Claude
Code discovers a nested `CLAUDE.md` under the working directory and loads it on
demand when it reads files in that directory; it never reads an `AGENTS.md` at
any level. Without the nested stub, the package file reaches agents that read
`AGENTS.md` but never reaches Claude Code. Splitting this way is also the fix
when the root file
cannot fit the budget — but the checker still looks only at the root pair, so
nested files are yours to keep honest.

## Spec Kit interop

When a `.specify/` directory exists, the region between `<!-- SPECKIT START -->`
and `<!-- SPECKIT END -->` is treated as a protected region: excluded from every
structural check, never reformatted, never moved. The checker verifies that both
markers are present and in that order, and reports when the block is not last in
the file.

The markers are read from
`.specify/extensions/agent-context/agent-context-config.yml` when that file
exists, and default to the pair above when it does not. A marker quoted in prose
or inside a code fence is not treated as a real marker, so a file that documents
the convention does not trip the check.

To keep both files in sync, set `context_files` in that config to
`[AGENTS.md, CLAUDE.md]`.

## Honest limitations

The 200-line figure is Anthropic's guidance for `CLAUDE.md`, stated twice on
their memory page with no cited experiment. The `AGENTS.md` specification states
no size guidance at all. No published study isolates instruction-file length as
an independent variable against task outcomes; the one ablation that varied
length measured adherence rather than success, and found no detectable effect
between 25 and 500 lines. The strongest
controlled study found context files did not improve task success rates at all
while costing over 20% more — though the same study found that instructions in
these files *are* well followed and that the files are useful for specifying
non-standard coding practices, which is exactly what `## Rules` holds.

So the case for this standard is cost, not obedience: on a correctness tie with
a one-directional cost, the cheaper artifact wins, and everything outside
`Rules` and `Commands` is paying tokens on every request for no demonstrated
benefit. The section names are this plugin's invention; no vendor mandates any
section list, and the per-section caps are budgets calibrated against the
observed corpus median rather than findings.

`skills/instruction-standard/references/evidence.md` records every source and
every unsupported claim in full.

## License

MIT
