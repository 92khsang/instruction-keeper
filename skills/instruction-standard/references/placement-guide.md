# Placement guide

Given a piece of project guidance, where should it live? The axis that decides
it is **when does this need to be in context**, not how important it is.

## Loading behaviour, in order of decreasing cost

| Mechanism | When it loads | Cost profile |
|---|---|---|
| `AGENTS.md` via `CLAUDE.md` import | every session, in full, at launch | highest — pays on every request |
| `.claude/rules/*.md` **without** `paths:` | every session, same priority as `.claude/CLAUDE.md` | identical to the above; purely an organizational split |
| `.claude/rules/*.md` **with** `paths:` | only when Claude reads a matching file | resident only while relevant |
| Nested `CLAUDE.md` in a subdirectory, importing the `AGENTS.md` beside it | when Claude reads files in that directory | resident only while relevant |
| Skill (`.claude/skills/<name>/SKILL.md` in a project) | name + description in the skill listing; body on invocation; supporting files on demand | near-zero until used |
| Hook | never in context | zero, and it is enforcement rather than a request |
| `docs/`, `CONTRIBUTING.md` | only when explicitly read | zero |

The single most common mistake is believing `@path` imports reduce context.
They do not — imported files load at launch. Splitting a file into imports
de-duplicates maintenance, not tokens. Only path scoping, nesting, and skills
actually defer loading.

## Routing table

### → A skill

- Any multi-step procedure: release, deploy, database migration, incident
  response, security review, a `/review` checklist.
- Reference material needed only sometimes: API schemas, query patterns, test
  harness and base-class tables, which-level-to-test decision tables, domain
  explainers, glossaries.
- Anything pasted into chat a third time.
- Any section of an instruction file that has grown from a fact into a procedure.

Keep a skill body concise too — under 500 lines, with detail pushed into
supporting files next to it. For procedures with side effects (deploy, commit,
send-message), set `disable-model-invocation: true` so only the user triggers
them.

### → `.claude/rules/` with `paths:` frontmatter

- Constraints tied to a file type, a directory, or a set of scattered paths:
  "all API handlers validate input", "test files must use the shared fixture",
  "generated files under `src/db/generated/` are never edited by hand".

```markdown
---
paths:
  - "src/api/**/*.ts"
---

- Every endpoint validates its input with the shared zod schema.
- Error responses use the `ApiError` shape, never a bare string.
```

Choose a path-scoped rule over a nested pair when the rule spans scattered paths
or when conventions should stay centralized at the root. Choose a nested pair
when directory owners maintain their own conventions.

A rule file **without** `paths:` saves nothing. If the content is always
relevant, it belongs in `AGENTS.md`; if it is not, give it a `paths:` list.

### → A nested `AGENTS.md` with a `CLAUDE.md` beside it

- Package or subsystem conventions in a monorepo. The subtree file states only
  what *differs* from the root.
- This is the correct answer when the root file cannot fit the budget. A
  200-line root in a ten-package monorepo is either bloated or too generic to
  help; one 80-line file per package is neither.
- Write both files. Claude Code discovers `CLAUDE.md` in subdirectories under
  the working directory and includes it when it reads files there; it never
  reads an `AGENTS.md` at any level. The nested `CLAUDE.md` is one line,
  `@AGENTS.md`, which resolves relative to itself:

```text
packages/api/AGENTS.md    the package's rules
packages/api/CLAUDE.md    one line: @AGENTS.md
```

A nested `AGENTS.md` on its own defers loading for agents that read
`AGENTS.md`, and delivers nothing at all to Claude Code.

### → `docs/`, linked from `## Pointers`

- Architecture rationale, diagrams, design decisions with their reasoning.
- Directory maps and file-by-file descriptions, if they are wanted at all.
- Detailed API documentation.

Every link must carry a purpose clause. A bare link is a documented defect and
is frequently not followed.

### → `README.md` / `CONTRIBUTING.md`

- Install tutorials, prerequisites narrative, quick starts.
- Human contribution policy, DCO text, code of conduct.
- Anything addressed to a person deciding whether to contribute.

### → A hook, `permissions.deny`, or CI

- Anything that must hold *every* time regardless of judgment: "never edit
  `.env`", "always run the formatter after editing", "never push to `main`".
- Formatting and lint enforcement.

An instruction file is context delivered as a user message; it shapes behaviour
but guarantees nothing. A `PreToolUse` hook executes regardless of what the
model decides. If a rule matters enough to write in capitals, it probably
belongs in a hook.

### → The linter or formatter config

- Indentation, quote style, semicolons, line length, trailing commas, import
  order — anything a formatter already rewrites or a linter already fails on.

Restating these in prose is the single most common defect measured in real
instruction files. Delete the prose and name the check in `## Commands`.

### → An output style

- Tone, persona, verbosity, response format, "be concise", "no preamble".

These change how the agent responds, not what it knows about the project.

### → Auto memory (not an authoring target)

- Learned preferences and corrections. Claude writes these itself, and it
  deliberately skips anything the instruction files already say. Do not
  hand-maintain a "learned preferences" section; promote durable items from auto
  memory into `AGENTS.md` instead.

## Legacy headings and where each one goes

These headings are findings, not sections. Each marks a topic someone decided to
cover, rather than a set of lines that each passed an admission test.

| Heading | Destination |
|---|---|
| `Testing` | invocations to `Commands`, invariants to `Rules`, harness and base-class tables to a skill |
| `Code Style` | delete what the linter enforces; the non-default residue is two or three bullets in `Rules` |
| `Setup` | fold into `Commands`; keep only non-default runtime versions and required env vars |
| `Project Structure` / `Repository Structure` | delete; if a real ownership or dependency rule is hiding there, move that one rule to `Boundaries` |
| `Project Overview` / `Tech Stack` | the preamble, at most two lines |
| `Troubleshooting` / `Debugging` | a skill; one-line gotchas stay in `Commands` beside the command they qualify |
| `Table of Contents`, `License`, `Recent Changes` | delete |

## A worked decision

> "Our GraphQL resolvers must never call the ORM directly; they go through the
> service layer. Also here is how to add a new resolver, in seven steps."

Two pieces, two destinations.

- The invariant is a dependency-direction rule. If it applies repo-wide, it is
  one line in `## Boundaries`. If it applies only under `src/graphql/`, it is a
  path-scoped rule — which is better, because it costs nothing until the agent
  opens a resolver.
- The seven steps are a procedure. That is a skill, named in `## Contributing`
  in one line and described nowhere else.

If a dependency linter already fails on a direct ORM import, the invariant
becomes `pnpm lint:deps` in `## Commands` and disappears from `Boundaries`
entirely.
