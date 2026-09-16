---
name: split
description: This skill should be used when a substantial instruction file already exists and the user asks to "split my CLAUDE.md", "move CLAUDE.md into AGENTS.md", "migrate to AGENTS.md", "make my CLAUDE.md work with Codex", "make my CLAUDE.md work with other coding agents", "my CLAUDE.md is too long, restructure it", or runs /instruction-keeper:split. It migrates the existing content into the AGENTS.md plus CLAUDE.md-stub pair, reorganizes it into the standard's section set, and routes what does not belong there to a skill, a path-scoped rule, or docs/. Use the audit skill instead when the user wants findings rather than a rewrite, and the init skill when there is no existing file whose content must be preserved.
argument-hint: "[optional: path to the file to split, defaults to CLAUDE.md]"
allowed-tools:
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_instructions.py":*)
  - Read
  - Glob
  - Grep
---

# Split an existing instruction file

Migrate a repository that has one unstructured instruction file into the
standard's pair, without losing content that has value.

This is a destructive restructuring of a file someone wrote deliberately. Show
the plan before writing anything, and never delete content silently: every line
proposed for deletion is listed with its reason and approved before it goes.

## Step 1: Load the standard and take a baseline

Invoke the `instruction-standard` skill, then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_instructions.py" --project-root "${CLAUDE_PROJECT_DIR}"
```

Whenever either file of the pair exists, the first line of the output is the
budget, on a clean run too:

```
instruction-keeper: Claude Code loads 412 lines / 19.4 KB over AGENTS.md, CLAUDE.md (target 120, warn 200, fail 400).
instruction-keeper: Codex loads 21.8 KiB over AGENTS.md (limit 32 KiB, truncated silently past it).
```

Those are the "before" numbers. The first covers the `AGENTS.md` and `CLAUDE.md`
import closures together; the second is raw bytes on disk, which is what Codex
concatenates and truncates. Keep both; step 5 reports the "after" against them.

Read the source file in full. Read any file it imports with `@`, to the full
depth — the import closure is what actually loads, and content hiding behind an
import is part of the migration.

## Step 2: Classify every line

Go through the source file and assign each block exactly one destination. Work
at the level of individual lines, not sections: the common case is one heading
whose contents split three ways.

| Destination | What goes there |
|---|---|
| `AGENTS.md` → preamble | one or two sentences on what the repo is responsible for |
| `AGENTS.md` → `## Rules` | invariants no checker enforces; the invariant half of any Testing section; the non-default residue of any Code Style section |
| `AGENTS.md` → `## Commands` | runnable invocations; the Setup section's non-default versions and env vars; the runnable half of any Testing section |
| `AGENTS.md` → `## Boundaries` | ownership and dependency direction only |
| `AGENTS.md` → `## Contributing` | branch/PR/commit facts; what the agent may do on the user's behalf |
| `AGENTS.md` → `## Pointers` | `docs/` links, each with a purpose clause |
| `CLAUDE.md` (below the import) | genuinely Claude-specific lines: plan mode, subagent guidance. Not skill or rules listings — the runtime discovers those |
| a skill | any multi-step procedure; reference material needed only sometimes |
| `.claude/rules/` with `paths:` | anything that applies to one directory or file type |
| `docs/` | architecture explanation, rationale, diagrams, directory maps |
| `CONTRIBUTING.md` | install tutorials, human contribution policy |
| a hook or CI | anything that must hold every time regardless of judgment |
| delete | linter-enforced style rules, directory trees, tech-stack inventories, tables of contents, self-evident advice |

Three splits are the ones that matter most, because they are where almost all
the volume is:

- **Testing** splits three ways: invocations to `Commands`, invariants to
  `Rules`, harness and base-class reference tables to a skill.
- **Code Style** is mostly deleted. Check which formatter and linter configs
  exist and delete every rule they already enforce; what remains is a handful of
  bullets in `Rules`.
- **A long process or workflow section** splits into a few facts in
  `Contributing` and one or more skills for the numbered procedures.

## Step 3: Present the plan and get approval

Show a table of every source block and its destination, plus:

- the projected line count for the pair against the target the checker reported
- every new file that will be created (skills, rules, docs pages)
- everything proposed for deletion, with the reason

Get explicit approval before writing. Deletions are the part the user will
disagree with, so list them separately and be specific about why each one goes.

## Step 4: Execute

The approval arrives as a new user message, which ends the turn that asked for
it. This skill therefore does not pre-approve `Write` or `Edit`: an
`allowed-tools` grant clears when the user sends their next message, so a grant
made while presenting the plan would already be gone on the turn that writes.
Expect the ordinary permission prompt for each file.

Address every write absolutely — `${CLAUDE_PROJECT_DIR}/AGENTS.md`,
`${CLAUDE_PROJECT_DIR}/CLAUDE.md`, and `${CLAUDE_PROJECT_DIR}/docs/…` — because
the session shell's working directory moves whenever a command runs `cd`, and a
bare `AGENTS.md` written from a drifted directory lands in a subdirectory rather
than replacing the file being migrated.

1. Create the destination files first — skills, path-scoped rules, `docs/`
   pages — so nothing is deleted before it has somewhere to live.
2. Write `${CLAUDE_PROJECT_DIR}/AGENTS.md` with the sections in the standard's
   order, omitting every section with no content.
3. Replace the existing `CLAUDE.md` with `@AGENTS.md` plus any Claude-specific
   lines. **Replace the file the checker named**, not `CLAUDE.md` by reflex:
   Claude Code loads a project `CLAUDE.md` from either `CLAUDE.md` or
   `.claude/CLAUDE.md`, and the budget line lists whichever one is in play. When
   it is `.claude/CLAUDE.md`, the import resolves relative to that file, so the
   line is `@../AGENTS.md`. Writing a second `CLAUDE.md` at the root instead of
   replacing the first leaves both loading, which the checker reports as
   `CLAUDE_MD_DUPLICATED`.
4. Add a `## Pointers` entry for each `docs/` page created in step 1, with a
   clause saying what is in it and when to read it. Do **not** list the new
   skills or `.claude/rules/` files: Claude Code discovers both on its own, and
   `section-criteria.md` records listing them as a `## Pointers` defect.

**Preserve the Spec Kit region exactly.** If the source carries
`<!-- SPECKIT START -->` … `<!-- SPECKIT END -->`, carry the whole block to the
end of the new `AGENTS.md` verbatim. Do not edit inside it, do not reformat it,
do not move content across a marker. Then check
`.specify/extensions/agent-context/agent-context-config.yml`: if `context_file`
points at `CLAUDE.md`, tell the user to change it to `AGENTS.md`, or to set
`context_files` to both, or Spec Kit will keep writing into the stub.

**Never leave a copy.** A `CLAUDE.md` that duplicates `AGENTS.md` instead of
importing it goes stale silently; the checker fails on this for that reason.

## Step 5: Verify and report

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_instructions.py" --project-root "${CLAUDE_PROJECT_DIR}"
```

Report:

- the budget line before and after, quoted from the checker rather than counted
  by hand
- every file created, with its purpose in one line
- every line deleted, grouped by reason
- any remaining findings, and why they were left

## When the root file still will not fit

If the repository is a monorepo and `AGENTS.md` is still over budget, the answer
is not a tighter root file. Give the package a nested pair of its own: an
`AGENTS.md` in the package directory carrying only what differs there, and a
`CLAUDE.md` beside it whose whole content is the import of it.

```markdown
@AGENTS.md
```

Both halves are needed, and for different readers. Claude Code reads `CLAUDE.md`
and never `AGENTS.md`, at any level; it discovers a nested `CLAUDE.md` under the
working directory and includes it when it reads files in that directory. Codex
is the mirror image: it walks from the project root down to the working
directory, takes one file per directory, and never reads a `CLAUDE.md`. A nested
`AGENTS.md` alone reaches Codex and never Claude; a nested `CLAUDE.md` alone
reaches Claude and never Codex. The checker reports each case as
`NESTED_NO_CLAUDE` or `NESTED_NO_AGENTS`.

This, like a path-scoped rule, actually reduces context for both runtimes: the
root file is in every Codex chain and loads at launch for Claude Code, while a
package file loads only for work in that package. An `@path` import reduces
nothing — in Claude Code imported files load at launch, and in Codex they do not
load at all.

The checker verifies that a nested pair exists and that the stub imports its
sibling. It does not run the section, cap or content checks on nested files, so
say which of the two you mean rather than letting its silence read as approval
of what the package file says.
