# Evidence behind this standard

Every number and every section in this standard is recorded here with its
source, together with an explicit statement of what the evidence does **not**
support. Nothing here should be repeated to a user as a measured fact unless it
is marked as one. Claims with no source at all are listed under
[Asserted, not sourced](#asserted-not-sourced) rather than left to look cited.

## How the empirical data was gathered

176 well-known open source repositories were sampled across eight ecosystems
(AI tooling, MCP and developer tooling, JavaScript frameworks, language runtimes
and systems software, data and infrastructure, Python/ML, products and
applications, JVM/Go/enterprise). For each, `AGENTS.md`, `CLAUDE.md` and
`.github/copilot-instructions.md` were fetched from `raw.githubusercontent.com`,
and every top-level section was classified by the dominant kind of content in
its body. 195 instruction files were found.

This is a convenience sample of popular repositories, not a random sample. It
describes what well-known projects do, which is a statement about convention,
not about efficacy. It is this plugin's own measurement: it is not published,
not peer reviewed, and not independently replicated.

## What the corpus shows

**Size distribution**

| File | n | p25 | median | p75 | p90 | max |
|---|---|---|---|---|---|---|
| `AGENTS.md` | 97 | 28 | **105** | 235 | 367 | 1017 |
| `CLAUDE.md` | 70 | 1 | **1** | 18 | 240 | 550 |

65 of 195 files are pointer-only. 33 `CLAUDE.md` files are a bare `@AGENTS.md`
import or symlink. 64 repositories carry both files.

**The file pair is settled practice, not a design choice.** The modal
`CLAUDE.md` is one line. This standard's file-pair rule reports what the
ecosystem already converged on.

**Content by kind** (dominant kind per section, summed across all 195 files)

| Kind | Sections | Total lines | Avg lines/section |
|---|---:|---:|---:|
| process | 127 | 3031 | 24 |
| domain-knowledge | 87 | 3111 | **36** |
| testing | 101 | 2684 | 27 |
| commands | 111 | 2431 | 22 |
| invariants | 118 | 2238 | 19 |
| structure | 77 | 1850 | 24 |
| style | 90 | 1799 | 20 |
| agent-behavior | 80 | 1472 | 18 |
| pointers | 83 | 786 | **9** |
| overview | 34 | 322 | 9 |
| setup | 22 | 563 | 26 |
| boundaries | 11 | 220 | 20 |

Three readings drive the standard:

1. The four kinds with the **largest average sections** — domain-knowledge 36,
   testing 27, setup 26, structure 24 — are all kinds first-party guidance
   routes out of the file. The kinds this standard keeps as sections of their own are
   already among the leanest measured: pointers at 9 lines a section,
   agent-behavior at 18, invariants at 19. `overview` is also 9 and is still cut
   to two lines of preamble, because it is the one content type with direct
   negative evidence against it.
2. **Rule-shaped content already exceeds command-shaped content** by roughly
   25% (invariants + style + half of testing ≈ 5380 lines, versus commands +
   setup + half of testing ≈ 4330). "It is all really just Commands" is not what
   the data says. Invariants are the centre of mass, yet they rarely get their
   own heading — which is why this standard gives them one and puts it first.
3. **`boundaries` is the rarest kind in the entire corpus** (11 sections) while
   `structure` is among the most common (77 sections). The heading "Architecture"
   attracts inventory. Renaming the section to `Boundaries` is the fix.

**Every file over 300 lines had a diagnosable defect**, not a justified reason
for its size: concatenated documentation pages (1017 lines), machine-appended
stale blocks, a generated copy already out of date against its source, or one
runaway procedure (537 lines of which 317 were a single "Commits and PRs"
section; 258 lines of which 222 were one policy section).

## First-party guidance

Quotes in this section were re-checked against the live pages on 2026-09-16,
except the `agents.md` specification and the Claude Code skills, context-window
and large-codebases pages, which are cited from the Sources list without a
re-check this session.

**Anthropic, Claude Code documentation**

- "target under 200 lines per CLAUDE.md file. Longer files consume more context
  and reduce adherence." The memory page states this twice: once as guidance
  under *Write effective instructions*, and once in troubleshooting as "Files
  over 200 lines consume more context and may reduce adherence." No experiment
  is cited for the number in either place.
- Hard ceiling: "Claude Code loads a CLAUDE.md file of up to 4 MiB in full and
  skips a larger file."
- `/doctor` trim criteria: cuts "content Claude can derive from the codebase,
  such as directory layouts, dependency lists, and architecture overviews", and
  keeps "pitfalls, rationale, and conventions that differ from tool defaults".
- Exclude list, summarized across the documentation rather than quoted from one
  place: anything derivable from code, standard conventions the model already
  knows, detailed API docs, frequently-changing information, long explanations
  or tutorials, file-by-file descriptions, self-evident advice.
- "If an entry is a multi-step procedure or only matters for one part of the
  codebase, move it to a skill or a path-scoped rule instead."
- "Splitting into `@path` imports helps organization but doesn't reduce context,
  since imported files load at launch."
- "Claude Code reads `CLAUDE.md`, not `AGENTS.md`" — and the documented bridge
  is a `CLAUDE.md` that imports it.
- Nested loading is a `CLAUDE.md` mechanism only: "Claude also discovers
  `CLAUDE.md` and `CLAUDE.local.md` files in subdirectories under your current
  working directory. Instead of loading them at launch, they are included when
  Claude reads files in those subdirectories." Nothing in the documentation
  loads a nested `AGENTS.md`.
- Trigger for adding a line: Claude made the same mistake a second time, a code
  review caught it, the same correction was retyped, or a new teammate would
  need it.
- Keep `SKILL.md` under 500 lines.

**agents.md specification** — no required fields, no required headings, no size
guidance of any kind. Popular topics listed: project overview, build and test
commands, code style, testing instructions, security considerations. Nesting is
nearest-wins. Any claim that "the AGENTS.md spec says keep it under N lines" is
citing something that does not exist.

**GitHub Copilot** — "Instructions must be no longer than 2 pages" and
"Instructions must not be task specific", both from the `<Limitations>` block of
the prompt GitHub recommends for *generating* the file, not from prose guidance.
Separately, as a best practice: "Limit any single instruction file to a maximum
of about 1,000 lines. Beyond this, the quality of responses may deteriorate."
Instructions that ask Copilot to "Follow external links" are listed among those
that do not have the intended effect, with the workaround "Copy the relevant
content directly into your instruction file instead".

**OpenAI Codex** — on rule writing: "Keep rules concise, explain the behavior to
flag and any safe path or exception, and reserve formatting and lint checks for
CI."

Loading behaviour, from the documentation:

- Discovery is hierarchical and per directory: "Codex concatenates files from
  the root down, joining them with blank lines. Files closer to your current
  directory override earlier guidance because they appear later in the combined
  prompt."
- The chain is capped: "Codex skips empty files and stops adding files once the
  combined size reaches the limit defined by `project_doc_max_bytes` (32 KiB by
  default)." The documented remedy is "Raise the limit or split instructions
  across nested directories when you hit the cap."
- `project_doc_fallback_filenames` configures additional names to try. The
  documented example is `["TEAM_GUIDE.md", ".agents.md"]`; `CLAUDE.md` is not
  mentioned.
- The page says nothing about file imports, `@`-references or HTML comments.

### Codex behaviour established by reading the source, not the documentation

The three facts the checker's Codex model depends on most are not stated on any
documentation page, two of them because they are negative. They were established
by reading
[`codex-rs/core/src/agents_md.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs)
and
[`codex-rs/config/defaults.toml`](https://github.com/openai/codex/blob/main/codex-rs/config/defaults.toml)
on 2026-09-16. Cite them as a source reading of that revision, not as vendor
guidance, and re-check them before relying on them against a much later release.

- **No import is expanded.** `read_agents_md` reads the file as bytes,
  truncates to the remaining budget, converts with `String::from_utf8_lossy`
  and pushes the text verbatim into an `InstructionEntry`. There is no markdown
  parse anywhere on that path, and the repository contains no import-resolution
  machinery. An `@path` line in a file Codex loads therefore reaches the model
  as literal text, and the file it names is never read.
- **No HTML comment is stripped.** Same path, same reason: the bytes on disk
  are the bytes in the prompt. A block comment costs its own length against
  `project_doc_max_bytes` and is read by the model as part of the instructions.
- **Truncation is on a byte boundary and is silent.** `data.truncate(remaining)`
  cuts mid-line and mid-fence if that is where the budget ends. The only signal
  is `tracing::warn!("project doc exceeds remaining budget; truncating")`, which
  does not surface in the TUI; a user issue describes it as "`AGENTS.md` is
  silently truncated without any warning within the TUI".

Two further values, read from the same revision:

- `candidate_filenames` tries `AGENTS.override.md` first, then `AGENTS.md`, then
  each configured fallback, and **returns on the first match in a directory**. An
  `AGENTS.override.md` therefore replaces the `AGENTS.md` beside it rather than
  adding to it.
- `defaults.toml` sets `project_doc_max_bytes = 32768`,
  `project_doc_fallback_filenames = []` and `project_root_markers = [".git"]`.
  The empty fallback list is why Codex does not read `CLAUDE.md` in a default
  installation, which is what makes the stub safe to keep host-specific.

`.codex/config.toml` is the **Project** layer of Codex's config stack, above the
user's `config.toml` and below session flags and managed config, and it is part
of the effective config like any other layer. One documented exception matters
here: "Project-root discovery and project trust use the applicable non-project
layers." So a repository can raise its own `project_doc_max_bytes` and add its
own `project_doc_fallback_filenames`, and cannot change `project_root_markers`.
The checker reads the first two from `.codex/config.toml` and not the third for
exactly that reason. Source:
[`codex-rs/config/src/loader/README.md`](https://github.com/openai/codex/blob/main/codex-rs/config/src/loader/README.md).

A limit raised in a user's own `~/.codex/config.toml` is invisible to the
repository and is not modelled: the checker measures what a teammate with a
default installation would get.

### Codex's plugin and hook surfaces

Relevant because this plugin ships into both runtimes from one directory. Read
from the same revision, and from
[learn.chatgpt.com/docs/hooks](https://learn.chatgpt.com/docs/hooks) and
[/docs/plugins](https://learn.chatgpt.com/docs/plugins).

- `DISCOVERABLE_PLUGIN_MANIFEST_PATHS` is `[".codex-plugin/plugin.json",
  ".claude-plugin/plugin.json", ".cursor-plugin/plugin.json"]`, tried after a
  root `plugin.json` carrying an Agent Plugins schema. Codex therefore reads a
  Claude Code plugin manifest as-is.
- `HookToolName::apply_patch()` carries the matcher aliases `Write` and `Edit`,
  commented "for compatibility with hook configurations that describe edits
  using Claude Code-style names". The serialized `tool_name` stays
  `apply_patch`.
- The hook environment includes `CLAUDE_PLUGIN_ROOT` and `CLAUDE_PLUGIN_DATA`
  beside `PLUGIN_ROOT` and `PLUGIN_DATA`, commented "For OOTB compat with
  existing plugins that use this env var". There is no `CLAUDE_PROJECT_DIR`.
- `HookHandlerConfig::Command` has `command`, `commandWindows`, `timeout`,
  `async`, `statusMessage` and `additionalContextLimit`. **No `args`**, so an
  exec-form hook config deserializes with the script dropped.
- `tool_input.command` for `apply_patch` is the raw patch text:
  `apply_patch_payload_command` returns the `ToolPayload::Custom` input
  verbatim. The file markers are `*** Add File:`, `*** Update File:`,
  `*** Delete File:` and `*** Move to:`.
- `resolve_manifest_hooks` returns `None` when the manifest omits `hooks`, so a
  plugin must declare the path. `plugin_skill_roots` does fall back to
  `<plugin_root>/skills`, so skills are discovered.
- Model-visible hook output defaults to roughly 2,500 tokens before spilling to
  disk, against Claude Code's 10,000-character cap.
- Codex subagents are TOML files under `.codex/agents/` requiring `name`,
  `description` and `developer_instructions`. The plugin manifest has no
  `agents` field and nothing documents a plugin shipping one.
- **Not established:** whether Codex substitutes `${CLAUDE_PLUGIN_ROOT}` or any
  placeholder inside a `SKILL.md` body. Nothing in `codex-rs/ext/skills`
  performs a substitution, and the hook environment that carries the variable
  is built in `codex-rs/hooks/src/engine/discovery.rs`, which is the hook path
  and not the skill path. Absence of evidence in a source reading is weaker
  than a documented denial, so this is recorded as unknown rather than as a
  negative finding.

Together these make the two runtimes exact opposites below the repository root:
Codex loads a nested `AGENTS.md` and never a `CLAUDE.md`; Claude Code loads a
nested `CLAUDE.md` and never an `AGENTS.md`.

**Cursor** — "Keep rules under 500 lines"; "Copying entire style guides: Use a
linter instead. Agent already knows common style conventions."; "Agent knows
common tools like npm, git, and pytest."; "Add rules only when you notice Agent
making the same mistake repeatedly."

**VS Code / Microsoft** — "Keep your instructions short and self-contained";
"Focus on non-obvious rules. Skip conventions that standard linters or
formatters already enforce." The same page is the citation behind treating
`AGENTS.md` as the cross-agent file: it lists "Repository instructions
(`.github/copilot-instructions.md` or `AGENTS.md`)" as one precedence level.

Three independent vendors — OpenAI, Anysphere (Cursor) and Microsoft — exclude
linter-enforced style rules by name. That is the strongest convergence found
anywhere in the sources. GitHub Copilot is not a fourth: GitHub is Microsoft,
and its own example instruction file contains "Limit line length to 88
characters (Black formatter standard)", which is the defect the other three
warn against.

## Academic and industry evidence

Every claim below names the paper it comes from. All are arXiv preprints except
where noted; treat them as reported results, not settled findings.

- **Context files did not improve task success rates.** Gloaguen, Mündler,
  Müller, Raychev and Vechev, *Evaluating AGENTS.md: Are Repository-Level
  Context Files Helpful for Coding Agents?* (arXiv:2602.11988): "we find that providing context files does not generally
  improve task success rates, while increasing inference cost by over 20% on
  average. This observation holds across different LLMs, coding agents, and for
  both LLM-generated and developer-committed context files." The same abstract
  states that "instructions in the context files are well followed by coding
  agents", that "repository overviews, although popular and recommended by model
  providers, are not helpful", and that "context files are useful for specifying
  non-standard coding practices" — which is exactly what `## Rules` holds.
- **Efficiency gains are real, and separate from correctness.** *On the Impact
  of AGENTS.md Files on the Efficiency of AI Coding Agents* (arXiv:2601.20404),
  a paired within-task design over 124 real GitHub pull requests run with and
  without the file: median wall-clock runtime −28.64% and median output tokens
  −16.58% when the file is present. This is a cost and latency result. It is not
  a success-rate result, and must not be quoted as one.
- **More material did not raise pass rates.** Khatri, *Do Context Files Help
  Coding Agents? A Two-Agent Ablation Study on Real Repositories*
  (arXiv:2607.27250), 288 evaluated runs across two agents and 17 tasks:
  "Context strategy does not measurably move correctness on either agent
  (bounded to <=10-15pp via equivalence testing)." In two of its repositories
  the on-demand condition's wiki was "roughly 10× and 18× the words of the
  AGENTS.md", and the paper concludes that "the larger corpus only strengthens
  the correctness null — it gave the agent strictly more material and still did
  not raise pass-rates". Note the scope: it varies *which material is
  available*, not the length of one always-loaded file.
- **File length has been manipulated directly — against adherence, not
  success.** McMillan, *Instruction Adherence in Coding Agent Configuration
  Files: A Factorial Study of Four File-Structure Variables* (arXiv:2605.10039),
  1,650 Claude Code CLI sessions and 16,050 function-level observations, with
  file size set to 25, 100, 250 or 500 lines and instruction position to five
  ordinal levels: "None of the four structural variables or three two-way
  interactions produces a detectable contrast after multiple-testing correction.
  Size and conflict nulls are supported by affirmative-null Bayes factors (BF10
  between 0.05 and 0.10)." Its outcome measure is compliance with a target
  annotation, not task correctness.
- **Growth is monotonic unless pruning is deliberate.** Chatlatanagulchai et
  al., *Agent READMEs: An Empirical Study of Context Files for Agentic Coding*
  (arXiv:2511.12884), 2,303 context files across 1,925 repositories: Claude Code
  files have a median of 485.0 words, and "deletions are consistently negligible
  across all context file types, with median values less than 15.0 words",
  against a median of 57.0 words added per Claude Code commit. That asymmetry is
  the whole argument for a pruning rule rather than a cap.
- **The defect catalog.** dos Santos, Costa, Montandon, Silva and Valente,
  *Configuration Smells in AGENTS.md Files: Common Mistakes in Configuring
  Coding Agents* (arXiv:2606.15828), 100 popular open-source repositories:
  "Lint Leakage was the most common smell, affecting 62% of the files, followed
  by Context Bloat (42%) and Skill Leakage (35%)", and "We detected at least one
  smell in 91 agent configuration files." The catalog's six smells are Context
  Bloat, Skill Leakage, Lint Leakage, Blind References, Init Fossilization and
  Conflicting Instructions; the checker's `LINT_LEAKAGE` and `BLIND_REFERENCE`
  codes are named after two of them, and the size budget, the routing table and
  the growth-control rules answer three more. No prevalence figure is recorded
  here for the remaining three smells, because none was verified against the
  paper itself.
- **Position effects, and the limit of the analogy.** Liu et al., *Lost in the
  Middle: How Language Models Use Long Contexts* (TACL 2024, arXiv:2307.03172,
  the one peer-reviewed source here) measures a U-shaped curve in long-context
  retrieval, with the middle worst. Zeng et al., *Order Matters: Investigate the
  Position Bias in Multi-constraint Instruction Following* (arXiv:2502.17204)
  finds that "LLMs are more performant when presented with the constraints in a
  'hard-to-easy' order" — constraint order does move compliance, but the result
  is about difficulty ordering, not about earlier being better. Neither studies
  an always-loaded instruction file, and the one study that did manipulate
  position inside a `CLAUDE.md` (arXiv:2605.10039, above) found no detectable
  effect. `Rules` goes first because it is the highest-value content, not
  because position was measured to matter.

## What is NOT supported

State these honestly whenever the standard is being justified.

1. **The 200-line threshold is asserted, never measured.** It is stated twice on
   Anthropic's memory page with no cited experiment, and no other vendor gives a
   comparable line figure for an always-loaded file — Copilot's is about 1,000
   lines, Cursor's 500, and the `agents.md` spec gives none.
2. **"Long files reduce adherence" is not merely unproven for a file this
   size — it has an affirmative null against it.** arXiv:2605.10039 varied a
   `CLAUDE.md` from 25 to 500 lines and found no detectable effect on
   compliance, with Bayes factors supporting the null. What no study
   isolates is context-file *length* against *task success*: the length evidence
   that exists measures adherence, and the success evidence that exists varies
   presence or strategy rather than length.
3. **The retrieval result behind the "lost in the middle" mechanism was not
   measured at anything like an instruction file's scale, in either
   direction.** arXiv:2307.03172 evaluates multi-document QA over 10, 20 and 30
   retrieved documents — roughly 4K to 6K tokens — and key-value retrieval over
   75 to 300 pairs. That is a few times a 1,500-token file, not orders of
   magnitude above it, and the 100K figure that appears in the paper is a
   model's context window rather than an evaluated input. Applying the curve to
   a 120-line file is inference, not a measured result.
4. **The strongest controlled evidence cuts against the whole artifact**, not
   just against long ones: context files did not raise success rates at all. No
   source found argues long files perform *better*; the counter-evidence argues
   the files are ineffective regardless of length.
5. Therefore the honest argument for this standard is **cost, not obedience**:
   on a correctness tie with a one-directional cost, the cheaper artifact wins,
   and everything outside `Rules` and `Commands` is paying tokens for no
   demonstrated benefit.
6. **The section names are this standard's invention.** No vendor mandates any
   section list. `Rules`, `Boundaries`, `Contributing` and `Pointers` are chosen
   for the question each answers, not because the ecosystem uses those words —
   it largely does not.
7. **The per-section caps are budgets, not findings.** They are calibrated so
   the sum sits near the observed corpus median, nothing more.
8. Of the papers cited above, *Lost in the Middle* is peer-reviewed, and the
   defect catalog carries an arXiv journal reference to SCAM 2026. The rest are
   arXiv preprints, several of them recent, and are cited as such.

## Asserted, not sourced

These are claims this standard makes with no external source. They are honest
engineering judgments or observations from this plugin's own corpus survey, and
should be presented that way — never as findings.

- Every figure in *What the corpus shows*. The survey is this plugin's own,
  described above, and has not been replicated.
- "A duplicated `CLAUDE.md` goes stale silently." Observed in that survey as a
  generated copy already out of date against its source; the frequency was not
  measured.
- The three admission tests (breadth, non-inferability, deletion) and the fourth
  disqualifier. They are a decision procedure, not a measured one.
- The claim that an empty heading invites padding.
- The per-section caps, the 2-line preamble, and the 10/20-line `CLAUDE.md`
  thresholds, as distinct from the 120/200/400 closure budget derived from the
  corpus median.
- The order of the five sections, beyond the reasoning given in
  *Position effects* above.

## Sources

First-party documentation:

- [Claude Code — How Claude remembers your project](https://code.claude.com/docs/en/memory)
- [Claude Code — Skills](https://code.claude.com/docs/en/skills)
- [Claude Code — Context window](https://code.claude.com/docs/en/context-window)
- [Claude Code — Monorepos and large repos](https://code.claude.com/docs/en/large-codebases)
- [AGENTS.md specification](https://agents.md/)
- [GitHub — Add repository custom instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions)
- [GitHub — Use custom instructions](https://docs.github.com/en/copilot/tutorials/use-custom-instructions)
- [OpenAI Codex — Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) — `developers.openai.com/codex/guides/agents-md` now redirects here
- [OpenAI Codex — `agents_md.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs) and [`defaults.toml`](https://github.com/openai/codex/blob/main/codex-rs/config/defaults.toml) — read at revision `main`, 2026-09-16
- [openai/codex#7138](https://github.com/openai/codex/issues/7138) — the silent-truncation report, cited as empirical evidence and not as documentation
- [Cursor — Rules](https://cursor.com/docs/rules)
- [VS Code — Custom instructions](https://code.visualstudio.com/docs/copilot/customization/custom-instructions)
- [Spec Kit — agent-context extension](https://github.com/github/spec-kit/tree/main/extensions/agent-context)

Papers:

- Gloaguen, Mündler, Müller, Raychev, Vechev — [Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?](https://arxiv.org/abs/2602.11988) (ETH Zurich SRI Lab)
- [On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents](https://arxiv.org/abs/2601.20404)
- Khatri — [Do Context Files Help Coding Agents? A Two-Agent Ablation Study on Real Repositories](https://arxiv.org/abs/2607.27250)
- McMillan — [Instruction Adherence in Coding Agent Configuration Files: A Factorial Study of Four File-Structure Variables](https://arxiv.org/abs/2605.10039)
- Chatlatanagulchai et al. — [Agent READMEs: An Empirical Study of Context Files for Agentic Coding](https://arxiv.org/abs/2511.12884)
- dos Santos, Costa, Montandon, Silva, Valente — [Configuration Smells in AGENTS.md Files](https://arxiv.org/abs/2606.15828)
- Zeng et al. — [Order Matters: Investigate the Position Bias in Multi-constraint Instruction Following](https://arxiv.org/abs/2502.17204)
- Liu et al. — [Lost in the Middle: How Language Models Use Long Contexts](https://arxiv.org/abs/2307.03172) (TACL 2024)
