---
name: instruction-standard
description: This skill defines the AGENTS.md / CLAUDE.md standard — the fixed section set, the per-line admission test for each section, the length budgets, and where content goes when it does not belong in an always-loaded file. It should be used whenever AGENTS.md, CLAUDE.md, .claude/rules/, or any project instruction file is being written, edited, reviewed or discussed, including when the user says "add this to CLAUDE.md", "update AGENTS.md", "what goes in AGENTS.md", "should this be a rule or a skill", or asks where a piece of project guidance belongs. It supplies the criteria only; the audit, init and split skills run the whole-file workflows and load this skill themselves.
---

# The AGENTS.md / CLAUDE.md Standard

Use the tests below when a single line is in question. For a whole-file review
use the `audit` skill, to create a pair use `init`, and to migrate an existing
file use `split`. Read `references/section-criteria.md` before judging any
specific section, and `references/placement-guide.md` before routing content out
of the file.

## The file pair

`AGENTS.md` is the real artifact. `CLAUDE.md` is a stub.

```markdown
@AGENTS.md

## Claude Code

Use plan mode for changes under `src/billing/`.
```

Claude Code reads `CLAUDE.md`, not `AGENTS.md`, so the import is what makes the
shared file reach Claude. Coding agents that follow the `AGENTS.md` convention
read `AGENTS.md` directly, which is why the content lives there rather than in
`CLAUDE.md`.

Three consequences that are easy to get wrong:

- **The import does not save tokens.** Imported files load at launch. It
  de-duplicates maintenance, not context. There is exactly one budget and it
  covers the pair.
- **Never copy instead of importing.** A duplicated `CLAUDE.md` goes stale
  silently, which is an observed failure in real repositories.
- **`CLAUDE.md` holds only genuinely Claude-specific lines** below the import:
  plan-mode preferences, subagent guidance, output-style notes. Ten lines is the
  working cap. Do not list skills or `.claude/rules/` files here — Claude Code
  discovers both on its own, so a listing is duplication. Saying *when* to prefer
  a named skill over doing the work by hand is legitimate; cataloguing them is
  not. Anything another agent would also need belongs in `AGENTS.md`.

A symlink (`ln -s AGENTS.md CLAUDE.md`) works when no Claude-specific content is
needed, but on Windows it needs Administrator privileges or Developer Mode.
Prefer the import.

### `@`-imports inside `AGENTS.md`

This standard neither recommends nor forbids them. The mechanics for Claude
Code, so the decision is made on facts:

- An `@path` import is expanded and loaded at launch, so it costs exactly what
  pasting the file in would cost. Splitting a file into imports organizes it; it
  does not reduce context.
- Paths resolve relative to the file containing the import, not the working
  directory, and imports recurse to a maximum of four hops.
- Import parsing skips Markdown code spans and fenced code blocks, so a path in
  backticks is text rather than an import.
- An import in a project memory file whose path resolves outside the working
  directory is external: Claude Code shows a one-time approval dialog, and loads
  nothing from it if the user declines.

The budget below is measured over the whole closure for exactly this reason.

## The section set

Five headings, this order. `Rules` and `Commands` are expected: the checker
warns `MISSING_RULES` and `MISSING_COMMANDS` when either is absent. That is a
warning rather than a failure, because a repository with no invariant a checker
does not already enforce may legitimately omit `Rules` — but confirm that rather
than assume it. The other three are omit-if-empty. Do not create a heading with
nothing repository-specific under it: an empty section invites padding, and
padding is the defect this standard exists to prevent.

| # | Section | The one question it answers | Cap |
|---|---------|-----------------------------|-----|
| 0 | *(unheaded preamble)* | What is this repository responsible for? | 2 lines |
| 1 | `## Rules` | What must hold on every change? | 40 lines |
| 2 | `## Commands` | How do I build, run, and verify here? | 25 lines |
| 3 | `## Boundaries` | Where do ownership and dependency directions run? | 15 lines |
| 4 | `## Contributing` | How does a change reach main, and what may the agent do? | 20 lines |
| 5 | `## Pointers` | Where does everything else live? | 10 lines |

`Rules` and `Commands` are the load-bearing pair; the rest are usually absent.
`Rules` goes first because it is the highest-value content and the last thing to
cut under budget pressure. That ordering is a convention, not a measured effect:
the one controlled test of instruction position inside a `CLAUDE.md` found no
detectable difference. Do not defend the order as an adherence result — see
`references/evidence.md`.

Read `references/section-criteria.md` for each section's admission test, worked
examples, and the exact content that must be kept out of it.

## Length budget

Measured over the resolved `@`-import closure of the pair — the union of what
`AGENTS.md` and `CLAUDE.md` pull in, de-duplicated — after stripping block-level
HTML comments. Claude Code removes those before injecting the file, so they cost
nothing and are free for maintainer notes.

- Target **120 lines**, warn at **200**, fail at **400**.
- `CLAUDE.md`: 10 lines, hard fail past 20.

The units differ on purpose. Say which one you are quoting:

- The closure budget counts **every line, blank lines included**, because a
  blank line occupies context like any other.
- Per-section caps and the `CLAUDE.md` cap count **non-blank lines only**, and
  per-section caps **include fenced code**: a 40-line command block fills
  `Commands` exactly as much as 40 bullets do.

These are budgets, not measurements. The case for them is cost rather than
obedience, and `references/evidence.md` records what the evidence does and does
not support — read it before defending a number to a user who pushes back.

### Monorepos

A root file that cannot fit has a nesting problem, not a budget problem. Give
each package its own `AGENTS.md` covering only what differs there, and put a
`CLAUDE.md` beside it whose content is the import of that file:

```text
packages/api/AGENTS.md    the package's rules
packages/api/CLAUDE.md    one line: @AGENTS.md
```

Both files are needed. Claude Code discovers `CLAUDE.md` in subdirectories under
the working directory and includes it when it reads files in that directory; it
never reads an `AGENTS.md` at any level. Without the nested `CLAUDE.md` the
package file reaches every other agent and never reaches Claude.

This standard's checker governs only the repository-root pair. Nested pairs are
a legitimate pattern it deliberately leaves alone.

## The three tests that decide every line

Apply these in order to any candidate line.

1. **Breadth.** Is it true in every session, for every task? If it matters only
   sometimes, or only for one part of the codebase, it goes to a skill or a
   path-scoped rule under `.claude/rules/`.
2. **Non-inferability.** Would an agent reach the same conclusion by reading the
   repository? Directory layouts, dependency lists, architecture overviews and
   standard language conventions all fail this test. Pitfalls, rationale, and
   conventions that differ from tool defaults pass it.
3. **Deletion.** Would removing this line cause a mistake? If not, cut it.

A fourth test disqualifies content outright: if the rule must hold *every* time
regardless of judgment, it is a hook, a `permissions.deny` entry, or a CI check.
An instruction file is advisory context, never enforcement. Writing "never edit
`.env`" here is a request; a `PreToolUse` hook is a guarantee.

## Where content goes when it does not belong here

The four routes that account for nearly everything cut from an instruction file:

| Content | Destination |
|---|---|
| A multi-step procedure — release, deploy, migration, review checklist | a skill |
| Anything true of one directory or file type only | `.claude/rules/` with `paths:`, or a nested `AGENTS.md` + `CLAUDE.md` pair |
| A rule a formatter, linter, type checker or CI already fails on | delete it; name the check in `## Commands` |
| Directory trees, architecture explanation, diagrams | `docs/`, linked from `## Pointers` with a purpose clause |

Read `references/placement-guide.md` before routing anything out of the file. It
carries the full table — reference material, install tutorials, deterministic
rules, output styles — with each mechanism's loading behaviour, a worked
decision, and the destination for every legacy heading a real file arrives with
(`Testing`, `Code Style`, `Setup`, `Project Structure`, `Project Overview`,
`Troubleshooting`, `Table of Contents`).

## Spec Kit interop

When the repository has a `.specify/` directory and the `agent-context`
extension installed, Spec Kit owns the region between
`<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` and rewrites it in place.

- Treat it as a protected region: never edit inside the markers, never
  reformat it, never move content across a marker.
- Keep the block last in the file.
- The markers are configurable. Read
  `.specify/extensions/agent-context/agent-context-config.yml` before assuming
  the defaults; when that file exists, the checker reads the custom pair from it
  and uses those markers instead.
- The protected region is excluded from section parsing and from every content
  check, and counted in the size budget, because Spec Kit's lines occupy context
  like any others. A file that is over budget because of that block is over
  budget, and the fix is elsewhere in the file.
- A marker quoted in prose — in backticks, or inside a fenced block, in a file
  that documents the convention rather than using it — is not a marker and is
  not treated as one.
- To keep both files in sync, set `context_files` in that config to
  `[AGENTS.md, CLAUDE.md]`.

## Running the checker

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_instructions.py" --project-root "${CLAUDE_PROJECT_DIR}"
```

With no path argument it checks the root `AGENTS.md` and `CLAUDE.md`. Positional
paths narrow the structural checks to the named files — the pair contract and
the budget are measured either way — and a relative path resolves against
`--project-root` rather than the shell's working directory. Naming a file that
does not exist produces a `TARGET_MISSING` warning rather than silence, and
naming `CLAUDE.md` while `AGENTS.md` exists produces `TARGET_IS_STUB`: the
section and cap checks live on `AGENTS.md`.

Flags: `--json` for machine output, `--quiet-info` to hide notes (it applies to
JSON output too), `--new-only` to report only findings not seen on the previous
run.

Whenever either file of the pair exists, the run prints one budget line first,
a clean run included:

```text
instruction-keeper: 12 lines / 0.2 KB over AGENTS.md, CLAUDE.md (target 120, warn 200, fail 400).
```

The same numbers are in `--json` under `metrics`: `resolved_lines`,
`resolved_bytes`, `raw_bytes` and `closure_files`. Quote that line when
reporting size to a user instead of counting lines by hand.

The checker verifies size over the closure, the section allowlist and order,
per-section caps, link and path resolution, and a few high-precision content
heuristics. One of those touches linter overlap: `LINT_LEAKAGE` is a
deliberately narrow keyword match that fires only when a formatter config exists
in the repository, and it catches the most literal instances and nothing
subtler. It **cannot** judge enforcement in general — whether *this* rule is
already covered by *this* repository's linter, type checker or CI — nor whether
a statement is inferable from the code, nor whether a `Boundaries` entry is a
responsibility or an inventory. Those judgments belong to the `audit` skill and
the `instruction-auditor` agent, which read the repository's own tool
configuration. Silence from the checker is not approval — apply the three tests
above by hand.

## Growth control

Caps without a pruning rule expire quietly; `references/evidence.md` has the
corpus measurement behind that. Apply two rules when maintaining an existing
file:

- Add a line only when an incident is behind it — a mistake made twice, a review
  catch, a correction retyped. Record the incident in an HTML comment beside the
  line; block-level comments are stripped before injection and cost nothing.
- When asked to review or update the file, bias toward deletion. If the agent
  already does the right thing without a line, propose removing it and say so,
  rather than leaving it in place by default.

## Additional resources

- **`references/section-criteria.md`** — per-section admission tests, worked
  examples, and exclusions.
- **`references/placement-guide.md`** — the full routing table for content that
  belongs somewhere else, with the mechanism's loading behaviour.
- **`references/evidence.md`** — the survey and first-party sources behind every
  number in this standard, and an explicit list of what is unproven.
- **`${CLAUDE_PLUGIN_ROOT}/assets/AGENTS.md.template`** — a conforming skeleton
  carrying each section's admission test in a stripped HTML comment.
