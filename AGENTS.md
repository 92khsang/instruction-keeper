This repository is the instruction-keeper plugin: it defines the AGENTS.md /
CLAUDE.md standard and ships the checker, skills, agent and hook that apply it.

## Rules

- `scripts/` is standard library only and must run on Python 3.8: no
  third-party import, no syntax or stdlib API newer than 3.8. CI runs both test
  files on 3.8 and on the newest release.
- Finding codes and their severities are a public contract. The tests and any
  `--json` consumer pin them, so add a code rather than repurposing one, and
  treat a rename or a severity change as breaking.
- The hook never blocks and never raises. It exits 0 on every path, reports
  through `hookSpecificOutput.additionalContext`, and keeps `systemMessage` to
  one line because that field reaches the user and not Claude.
- A check belongs in the checker only when it is deterministic and
  high-precision. Judgment — whether a linter already enforces a rule, whether
  a line is inferable from the code — belongs to the audit skill and the
  instruction-auditor agent.
- Every claim about how an agent runtime behaves carries a citation in
  `evidence.md` or is generalized until it needs none. Do not invent a source,
  a figure, or a vendor's behaviour.
- Claude Code reads `CLAUDE.md`, never `AGENTS.md`, at any level. A nested
  `AGENTS.md` is not loaded on demand; a nested `CLAUDE.md` beside it is.
- The budget numbers are restated in prose across the skills, the agent and
  the README. Run `grep -rn '\b120\b\|\b200\b\|\b400\b' --include='*.md' .`
  before changing one: the checker is the authority and the prose has to follow
  it.

## Commands

`python3` alone runs the tests and the checker; the two manifest checks need
the `claude` CLI.

```bash
python3 tests/test_check_instructions.py
python3 tests/test_hook_post_edit.py
python3 scripts/check_instructions.py --project-root .
claude plugin validate --strict .claude-plugin/plugin.json
claude plugin validate --strict .claude-plugin/marketplace.json
```

Name the manifest you mean: `claude plugin validate --strict .` checks only the
marketplace file once one exists. The plugin form warns on any `CLAUDE.md` at a
plugin root — hence the stub at `.claude/CLAUDE.md` — and on a local, gitignored
`CLAUDE.local.md`, which a clean checkout does not have.

The hook reads a PostToolUse payload on stdin and prints nothing when it has
nothing to report:

```bash
echo "{\"tool_input\":{\"file_path\":\"$PWD/AGENTS.md\"}}" |
  CLAUDE_PROJECT_DIR="$PWD" python3 scripts/hook_post_edit.py
```

## Boundaries

`scripts/` is the deterministic layer and `skills/` the judgment layer: a check
that needs judgment belongs in `skills/audit/SKILL.md` or
`agents/instruction-auditor.md`, never in the checker.
`skills/instruction-standard/` is the only place the standard's prose lives.
The audit, init and split skills load it rather than restating it.

## Contributing

Commit messages follow Conventional Commits. The repository ships
`.gitmessage`; wire it per clone with
`git config commit.template .gitmessage`.
A pull request fills `.github/pull_request_template.md` — what changed, and the
commands you actually ran to verify it rather than that tests "pass".
`.github/workflows/ci.yml` runs both test files and the checker against this
repository on every push and pull request.

## Pointers

- [evidence.md](skills/instruction-standard/references/evidence.md) — the source behind
  every number, and the list of claims nothing supports; read it before adding or
  defending a factual claim.
- [AGENTS.md.template](assets/AGENTS.md.template) — a conforming skeleton with
  each section's admission test as a stripped HTML comment.
