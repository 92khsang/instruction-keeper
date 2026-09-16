---
name: audit
description: This skill should be used when the user asks to "audit AGENTS.md", "check my CLAUDE.md", "review my instruction files", "lint my instruction files", "is my AGENTS.md too long", "what should I cut from CLAUDE.md", or runs /instruction-keeper:audit. It reads the existing files and reports every deviation from the instruction-file standard, separating what the deterministic checker verified from what required judgment, with a concrete fix for each finding. It reports and proposes; it does not restructure. Use the split skill instead when the user wants the file migrated or reorganized, and the init skill when no instruction file exists yet.
argument-hint: "[path to AGENTS.md or CLAUDE.md, defaults to the repository root pair]"
allowed-tools:
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_instructions.py":*)
  - Read
  - Glob
  - Grep
---

# Audit instruction files

Report how far the repository's `AGENTS.md` and `CLAUDE.md` are from the
standard, and what to do about each finding. Do not edit anything unless the
user asks — this skill produces a report and a proposal.

## Step 1: Load the standard

Invoke the `instruction-standard` skill if it is not already loaded, and read
`${CLAUDE_PLUGIN_ROOT}/skills/instruction-standard/references/section-criteria.md`
— it holds the per-section admission tests this audit applies by hand.

## Step 2: Run the deterministic checker

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_instructions.py" --project-root "${CLAUDE_PROJECT_DIR}"
```

Run it with no path argument, even when the user named one file: that is the
only invocation that reports the whole pair. Add `--json` when the output needs
to be processed rather than read.

Positional paths are accepted, and a relative one resolves against
`--project-root` rather than against the shell's working directory. Two results
are worth knowing before you use one:

- A named file that does not exist yields a `TARGET_MISSING` warning. Silence
  about a file that was never read is not a clean bill of health.
- Naming `CLAUDE.md` while `AGENTS.md` exists yields a `TARGET_IS_STUB` note
  and skips the section and cap checks, because those live on `AGENTS.md`.
  Naming `AGENTS.md` does not skip them. When the user asks about `CLAUDE.md`,
  run without a path and report the pair.

Do not pass `--new-only` here. The `PostToolUse` hook already runs the checker
with that flag after every edit and advances the stored baseline, so an audit
that reused it would hide everything the hook has already reported once. Expect
to surface findings the user has seen in passing; a report is supposed to be
complete.

Whenever either file of the pair exists, the text output begins with one
budget line, on a clean run too:

```
instruction-keeper: 12 lines / 0.2 KB over AGENTS.md, CLAUDE.md (target 120, warn 200, fail 400).
```

Under `--json` the same figures are `metrics.resolved_lines`,
`metrics.resolved_bytes` and `metrics.closure_files`. The count is the union of
the `AGENTS.md` and `CLAUDE.md` `@`-import closures, de-duplicated, with
block-level HTML comments stripped and blank lines counted, because blank lines
occupy context too.

Beyond that size, the checker verifies the section allowlist and order,
per-section caps, link and path resolution, the `CLAUDE.md` stub contract
including copy-instead-of-import, Spec Kit marker integrity, and a small set of
high-precision content heuristics. Treat its output as established fact.

## Step 3: Apply the judgment checks the checker does not make

The checker is deliberately quiet on the criteria that carry the weight of the
standard. Apply the per-section admission tests from `section-criteria.md` by
hand, line by line, and gather the evidence each one needs.

**Tooling overlap — the highest-value check, and the most common defect in real
files.** The checker makes exactly one narrow pass at this. `LINT_LEAKAGE` fires
only when a formatter config sits at the repository root *and* `## Rules`
mentions one of a fixed keyword list — indentation, tabs, quotes, semicolons,
line length, import order, trailing commas. It is a keyword match against a short
list of root-level config filenames, not a judgment about what any tool actually
enforces. A hit names a keyword and a config file that both exist, not a rule
that config enforces — open the config and confirm before reporting it. Its
silence is no information at all. Judging enforcement in general is yours. Open the configs before judging any
`Rules` line: `.prettierrc`, `biome.json`, `eslint.config.*`, `.eslintrc*`,
`ruff.toml`, `pyproject.toml` `[tool.ruff]` / `[tool.black]`, `rustfmt.toml`,
`.clang-format`, `.editorconfig`, `.golangci.yml`, and
`.github/workflows/*.yml`. Never claim a rule is already enforced without naming
the config file read.

**Command accuracy.** For every line in `## Commands`, confirm the script or
target exists in `package.json`, `Makefile`, `justfile`, `Cargo.toml`,
`pyproject.toml` or `go.mod`, and judge whether it is guessable from that
manifest alone. Do not execute project commands during an audit.

**Breadth, inferability, procedures, enforceability.** Flag content that applies
to only part of the codebase, anything an agent would reach by reading the
repository, any section that has grown from a fact into a sequence of steps, and
any absolute that would be a guarantee as a hook or CI gate and is only a
request where it currently sits.

**Duplication.** Compare `AGENTS.md` against `CLAUDE.md`, and confirm
`CLAUDE.md` imports rather than copies.

## Step 4: Report

Lead with the verdict in one or two sentences: does the file conform, and if
not, what is the single largest problem.

Then two clearly separated groups:

**Verified by the checker** — reproduce each finding with its file, line,
message and suggested fix. Do not paraphrase the numbers.

**Requires judgment** — each item as: the exact line, why it fails which test,
and the concrete replacement. Never report a judgment finding without naming
the specific line it applies to.

Close with the budget. Quote the checker's budget line, or
`metrics.resolved_lines` / `metrics.resolved_bytes` / `metrics.closure_files`
under `--json`; never count the lines yourself. Say that the figure covers both
files' import closures together, and — if over — name the specific blocks to
move and where each one goes.

## Step 5: Hand off the fix

This skill audits; it does not restructure. Offer the right next step and stop,
so that an audit never quietly turns into a rewrite the user did not ask for.

- **A restructure is needed** — sections to route out, content to migrate into
  `AGENTS.md`, a `CLAUDE.md` that is not yet a stub: tell the user to run
  `/instruction-keeper:split`, and name the specific blocks it will route.
- **No instruction file exists**: tell the user to run `/instruction-keeper:init`.
- **A few line-level fixes** — delete a linter-enforced rule, add a purpose
  clause to a pointer, rename a heading: write out the exact replacement text for
  each one, offer to apply them, and re-run the checker afterwards.

Whatever the route, state that a `<!-- SPECKIT START -->` … `<!-- SPECKIT END -->`
region must be carried verbatim and never edited across a marker.

## Reporting rules

- Never claim a file is fine because the checker was silent. Its only overlap
  check is the narrow `LINT_LEAKAGE` keyword match described above; enforcement
  in general, inferability, and whether a `Boundaries` entry is a responsibility
  or an inventory are judgments it does not attempt. Say which checks were
  automated and which were read by hand.
- The checker governs the repository-root pair only. A nested pair in a monorepo
  package is outside its scope, so say so rather than letting its silence read as
  approval of the whole tree.
- The `instruction-auditor` agent reads the same `section-criteria.md` tests and
  runs the same judgment pass autonomously, returning a structured report. Use
  this skill when the user asked for an audit and wants the conversation; use the
  agent when an audit is a step inside larger work and only its conclusions are
  needed.
- When the user pushes back on a finding, check it against
  `${CLAUDE_PLUGIN_ROOT}/skills/instruction-standard/references/evidence.md`
  before defending it. Several numbers in this standard are budgets rather than
  measurements, and saying so is correct.
