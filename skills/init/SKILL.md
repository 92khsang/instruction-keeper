---
name: init
description: This skill should be used when a repository has no instruction file, or only a trivial one, and the user asks to "create AGENTS.md", "set up AGENTS.md and CLAUDE.md", "generate instruction files for this repo", "write a CLAUDE.md for this project", "bootstrap agent instructions", or runs /instruction-keeper:init. It analyses the repository, asks for the few invariants it cannot derive, and writes a conforming AGENTS.md plus a CLAUDE.md stub that imports it. Use the split skill instead when a substantial CLAUDE.md or AGENTS.md already exists — this skill writes from repository analysis and does not preserve existing content.
argument-hint: "[optional: repository root, defaults to the current project]"
allowed-tools:
  - Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_instructions.py":*)
  - Bash(ls:*)
  - Read
  - Glob
  - Grep
---

# Create AGENTS.md and CLAUDE.md

Write a conforming instruction file pair for a repository that has none, or has
only an unstructured `CLAUDE.md`.

If a substantial `CLAUDE.md` or `AGENTS.md` already exists, use the `split`
skill instead — that one preserves existing content. This skill writes from
repository analysis and does not.

## Step 1: Load the standard and check the ground

Invoke the `instruction-standard` skill. Then:

```bash
ls -a "${CLAUDE_PROJECT_DIR}"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_instructions.py" --project-root "${CLAUDE_PROJECT_DIR}"
```

Read the budget line: it names the files already in play. A project
`CLAUDE.md` lives at either `CLAUDE.md` or `.claude/CLAUDE.md`, and this skill
must write the one that already exists rather than adding a second.

If `AGENTS.md` exists with any section body, or `CLAUDE.md` holds more than the
`@AGENTS.md` import line, stop and ask whether to audit or split instead of
overwriting. Never overwrite an existing instruction file without explicit
confirmation.

## Step 2: Gather only what the standard admits

The output is short, so the investigation is narrow. Do not survey the codebase
broadly — most of what a survey produces is exactly the derivable content the
standard excludes.

**For `## Commands`** — read the manifests and CI, and prefer what they already
declare:

- `package.json` scripts, `Makefile` targets, `justfile` recipes,
  `Cargo.toml`, `pyproject.toml`, `go.mod`, `build.gradle.kts`, `pom.xml`
- `.github/workflows/*.yml` — what CI actually runs is what "verify" means here
- `.nvmrc`, `.tool-versions`, `.python-version`, `mise.toml` — runtime versions,
  but only record them where they differ from what the toolchain implies
- `.env.example` — required environment variables

Prefer the narrowest useful invocation. Find how to run a *single test file*,
not just the whole suite.

**For `## Rules`** — look for invariants no checker enforces:

- Generated directories that must not be hand-edited (look for codegen config,
  `*.generated.*`, `prisma/schema.prisma`, `buf.gen.yaml`, protobuf output)
- Compatibility or versioning constraints stated in code comments or ADRs
- `CONTRIBUTING.md` statements that are rules rather than onboarding

Then check what is already enforced and **exclude it**: if `.prettierrc`,
`biome.json`, `eslint.config.*`, `ruff.toml`, `rustfmt.toml` or `.editorconfig`
exists, no formatting rule goes in `Rules`. Name the lint command in
`## Commands` instead.

**For `## Boundaries`** — only if a real constraint exists. Look for a
dependency-direction linter (`eslint-plugin-boundaries`, `dependency-cruiser`,
`import-linter`, `ArchUnit`, a `lint:deps` script), a workspace layout with
clear ownership, or sibling repositories referenced in the README. If none of
this turns up, omit the section. Most repositories should.

**For `## Contributing`** — read `.gitmessage`, `.github/PULL_REQUEST_TEMPLATE*`,
`CONTRIBUTING.md`, and commit-lint config for the commit and PR conventions.
Ask the user directly what the agent may do on their behalf: push, open PRs,
post review comments.

**For the preamble** — one or two sentences, and only if the repository name and
layout do not already answer "what is this responsible for".

## Step 3: Ask what cannot be derived

Ask a short, concrete list. Do not guess these.

- Which invariants have bitten you that a linter does not catch?
- Is there a dependency direction or ownership rule that is not enforced by
  tooling?
- May I push to branches, open PRs, or post review comments on your behalf?
- Is there a runtime or environment quirk that makes an obvious command fail?

Three or four questions in one message. If the user says "whatever you think",
propose specific lines drawn from the repository and ask for a yes or no.

## Step 4: Write the files

Step 3 ends the turn, so the writes land on the turn *after* the user answers.
This skill deliberately does not pre-approve `Write` or `Edit`: an
`allowed-tools` grant clears when the user sends their next message, so a grant
made on the asking turn is already gone by the time there is anything to write.
Expect the ordinary permission prompt for each file, and do not shortcut the
questions to keep a grant alive.

Write both files at the repository root, addressed absolutely —
`${CLAUDE_PROJECT_DIR}/AGENTS.md` and `${CLAUDE_PROJECT_DIR}/CLAUDE.md`, unless
Step 1 found the project's `CLAUDE.md` at `.claude/CLAUDE.md`, in which case
write that path and import `@../AGENTS.md`, because the import resolves relative
to the file containing it. The
session shell's working directory moves whenever a command runs `cd`, and a bare
`AGENTS.md` written from a drifted directory creates a second, unmaintained
instruction pair inside a subdirectory — where Claude Code will then load the
nested `CLAUDE.md` on demand every time it reads a file in that directory.

Start from `${CLAUDE_PLUGIN_ROOT}/assets/AGENTS.md.template`. Every non-comment
line in it is sample content from the standard's worked example — replace all of
it. Delete any section whose sample cannot be replaced with something
repository-specific; an empty heading invites padding later. The guidance
comments are block-level HTML comments and cost no context, so keep or drop them
as the user prefers, but never ship a line mentioning `ACME`, `pnpm`,
`src/db/generated` or `acme-billing` that was not confirmed against this
repository.

Then write `${CLAUDE_PROJECT_DIR}/CLAUDE.md`:

```markdown
@AGENTS.md
```

Add Claude-specific lines below the import only when there are any — plan-mode
preferences, subagent guidance. Ten lines is the cap. Do not list skills or
`.claude/rules/` files; Claude Code discovers both already.

If the repository has a `.specify/` directory, leave the end of `AGENTS.md` free
for Spec Kit's managed block and tell the user that
`.specify/extensions/agent-context/agent-context-config.yml` can list both files
under `context_files` to keep them in sync.

## Step 5: Verify and report

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_instructions.py" --project-root "${CLAUDE_PROJECT_DIR}"
```

The first line of the output is always the budget, on a clean run too:

```
instruction-keeper: 12 lines / 0.2 KB over AGENTS.md, CLAUDE.md (target 120, warn 200, fail 400).
```

Quote it rather than counting lines yourself, and say that the figure covers the
`AGENTS.md` and `CLAUDE.md` import closures together. Then list every command
that was written, and state plainly which commands were **not** verified by
running them. Offer to run them.

Then state what was deliberately left out and where it would go instead —
directory layout, style rules the linter owns, any procedure that would have
become a skill. The omissions are the part the user is most likely to question.
