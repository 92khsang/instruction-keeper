# Section criteria

One page per section: the question it answers, the admission test for a single
line, what is explicitly excluded, and worked examples drawn from real
repositories.

Apply the admission test to **each line**, not to the section as a whole. A
section is the sum of lines that passed; it is never a topic to be covered.

---

## 0. Preamble (unheaded, ≤ 2 lines)

**Question:** What is this repository responsible for?

**Admission test:** Would an agent that has the repository open still be unsure
what this codebase is accountable for? If the name and the top-level layout
already answer it, write nothing.

**Excluded:** history, funding, adoption numbers, marketing adjectives,
technology inventories, anything phrased as "this project aims to". A
technology list is the exact shape that was measured popular and measured
unhelpful.

**Good**

```markdown
Acme API owns the public REST surface and the webhook dispatcher. Billing lives
in the separate `acme-billing` repository.
```

The second sentence earns its place: it prevents the agent from implementing
billing here. The first is borderline and would be cut first under budget
pressure.

**Bad**

```markdown
Acme API is a blazing fast, industry-leading platform. Founded in 2019, it now
serves millions of requests. Built with TypeScript, React, Postgres, Redis,
Kafka and Kubernetes.
```

Every clause is either marketing or derivable from `package.json`.

---

## 1. `## Rules` (≤ 40 lines)

**Question:** What must hold on every change?

**Admission test, applied per line:**

1. Would removing this line cause a mistake? If not, cut it.
2. Does a formatter, linter, type checker, build file or CI job already fail on
   a violation? If so, delete the line and name the check in `## Commands`.
3. Does the language or framework default already give you this? If so, cut it.
4. Must it hold *every* time regardless of judgment? If so, it is a hook, a
   `permissions.deny` entry, or a CI gate — not a sentence here.

This is the section with the strongest evidence behind it and the last one to
cut. It is also where the invariant half of a former `Testing` section and the
non-default residue of a former `Code Style` section land.

**Good**

```markdown
- Never weaken or delete an existing test to make a change pass.
- Webhook payloads are versioned; adding a field is allowed, renaming one is not.
- `src/db/generated/` is generated; edit `schema.prisma` and regenerate instead.
- Do not write comments that narrate what the code does. Comments explain why.
```

Each one is repository-specific, non-inferable, and unenforced by tooling.

**Bad**

```markdown
- Use 2-space indentation          <- .prettierrc enforces this
- Prefer single quotes             <- .prettierrc enforces this
- Write clean, readable code       <- self-evident
- Always validate user input       <- true everywhere; not repository-specific
- Never commit secrets             <- make it a PreToolUse hook, not a request
```

**Narrow exception for domain vocabulary.** Two or three lines are allowed when
the model's prior is actively *wrong* — a major-version rename, or a word this
project uses against its industry meaning. A path-scoped rule does not help
here, because it fires only after the agent opens a matching file, and the
failure happens before that.

```markdown
- This repo is on v3. Your training data likely describes the v2 config format;
  `EntryPoint` and `Router` mean different things there. Check `docs/v3.md` first.
```

Everything else about the domain goes to a skill.

---

## 2. `## Commands` (≤ 25 lines)

**Question:** How do I build, run, and verify here?

**Admission test:**

1. Is it copy-pasteable, and has it actually been run?
2. Is it repository-owned tooling the agent could not guess from the manifest?
   `npm test` and `cargo build` are guessable; a wrapper, a required flag, or a
   non-obvious filter is not.
3. Is it a command, or is it prose about a command?

Order from narrowest to broadest: one test, one file, the package, the full
suite, lint. The narrow loop is what an agent needs most often.

This section absorbs `Setup` and the runnable half of `Testing`. Runtime
versions and required environment variables appear only where they differ from
what the toolchain implies.

**Permitted tail, ≤ 5 lines:** environment gotchas that make a command lie — a
test that always fails locally, a stale build directory, a wrapper that must be
used instead of the obvious tool. Attach the gotcha to the command it qualifies.

**Good**

````markdown
Requires Node 20 and a running Postgres on `DATABASE_URL`.

```bash
pnpm install
pnpm test path/to/file.test.ts   # one file, fastest loop
pnpm test                        # full suite
pnpm lint                        # also enforces the dependency direction
```

`packages/web/dist/` is not cleaned by `pnpm build`; remove it by hand after
changing the bundler config or you will test a stale artifact.
````

**Bad**

```markdown
First, make sure you have Node installed. You can get it from nodejs.org or use
nvm, which most of the team prefers because it handles version switching well.
Once that is done, install pnpm globally. Then clone the repository...
```

That is an install tutorial. It belongs in `CONTRIBUTING.md`.

---

## 3. `## Boundaries` (≤ 15 lines, usually absent)

**Question:** Where do ownership and dependency directions run, that the agent
cannot read off the code?

Named `Boundaries` and not `Architecture` deliberately. The word "architecture"
reliably attracts directory inventories and design rationale, which is the most
commonly excluded content in every vendor's guidance. The name enforces the
definition.

**Admission test:**

1. Is it a *rule* about direction or ownership, stated as a sentence?
2. Could the agent infer it by reading one file? If yes, cut it.
3. Does a dependency linter already enforce it? If so, write the one-line rule
   plus the check name — not the explanation.

**Excluded, without exception:** directory trees, file-by-file maps, dependency
lists, architecture overviews, diagrams, images, rationale. Those go to `docs/`
and are linked from `## Pointers`.

Most repositories have nothing to put here. That is the expected outcome —
genuine boundary content is the rarest thing in real instruction files.

**Good**

```markdown
`src/api/` may import from `src/db/`, never the reverse. `pnpm lint` enforces it.
Deployment modules depend on runtime modules, never the reverse.
`packages/*/src` must not import from the root package.
The mobile client lives in `acme-mobile`; do not add client code here.
```

**Bad**

```markdown
src/
├── api/        # HTTP handlers
├── db/         # database access
└── web/        # frontend
```

Derivable in one `ls`. Delete it.

---

## 4. `## Contributing` (≤ 20 lines)

**Question:** How does a change reach `main`, and what may the agent do on the
user's behalf?

Two kinds of content share one heading because each is only a few lines:

**Etiquette — facts, not steps.** Branch naming, commit and PR title format, a
required commit trailer, who merges, what must not be pushed.

**Agent permission gates.** Whether the agent may push, open a PR, or post
review comments; any required AI-disclosure trailer; when to stop and ask. This
is the most convergent content across real repositories and the most frequently
omitted from section taxonomies.

**Admission test:** Would the agent get this wrong on every change without the
line? Is it a fact rather than a sequence?

**Excluded:** anything with numbered steps. A release, deploy, migration or
review checklist is a skill; name the skill here in one line and stop.
Human-facing contribution policy and DCO narrative go to `CONTRIBUTING.md`.
Tone, persona and verbosity go to an output style.

**Good**

```markdown
Branch as `feat/<slug>`. PR titles follow Conventional Commits; the repo ships
a `.gitmessage` template. Do not push to `main` and do not open a PR on my
behalf without asking. Releases: run the `release` skill, not by hand.
```

**Bad**

```markdown
1. Create a branch off main
2. Make your changes
3. Run the tests
4. Bump the version in package.json
5. Update the changelog
6. Open a PR
```

A six-step procedure. Make it a skill.

---

## 5. `## Pointers` (≤ 10 lines)

**Question:** Where does everything that is not in this file live?

**Admission test:**

1. Does the target exist?
2. Does the line say **what is in the target and when to read it**? A bare link
   is a documented defect and is frequently not followed.
3. Does the runtime already discover it? If so, do not list it.

That last test removes most of what people put here. Claude Code discovers
`.claude/rules/*.md` recursively and loads them itself, and a skill's name and
description are already in the skill listing. Listing either is duplication, and
it violates this section's own rule against adding what the agent can discover.
The one case that is not duplication is a skill carrying
`disable-model-invocation: true`, which the model will not reach on its own: a
line saying *when* to prefer it is legitimate, a catalogue of skills is not.

What remains is `docs/`, `CONTRIBUTING.md`, the nested `AGENTS.md` files of a
monorepo, and anything outside the repository.

**Good**

```markdown
- [docs/webhooks.md](docs/webhooks.md) — payload versions and the retry ladder;
  read before touching the dispatcher.
- `packages/*/AGENTS.md` — per-package rules, each imported by the `CLAUDE.md`
  beside it.
```

That second line points at the package files for a reader and for an agent that
reads `AGENTS.md`. It is not what delivers them to Claude Code, which never
reads an `AGENTS.md`: the `CLAUDE.md` beside each one does that, and Claude Code
includes it when it reads files in that package.

**Bad**

```markdown
- See docs/
- .claude/skills/ has our skills
- [Architecture](docs/architecture.md)
```

The first is not a pointer. The second lists something already in context. The
third has no purpose clause, so nothing tells the agent when it would matter.
