---
name: ship
description: Stages, commits, and pushes the current work as one milestone-shaped commit, after showing the user exactly what will land. Use ONLY when the user explicitly invokes it — never commit or push on Claude's own initiative.
allowed-tools: [Bash, Read, Write]
---

# /ship — commit and push, on the user's word only

The user reviews every milestone before it lands. This skill is the **only** path to a commit.
Outside of it, never run `git add`, `git commit`, or `git push` — finish the work, say it's done,
and stop. Waiting is correct behaviour, not a failure to act.

## 1. Pre-flight — refuse rather than guess

```bash
git status --short
git diff --stat HEAD
git log --oneline -3
```

- **Nothing to commit?** Say so and stop. Do not invent work.
- **Is this actually one logical, working step?** If the diff is clearly two or more unrelated
  steps (e.g. a dbt model *and* an unrelated doc rewrite), do NOT bundle them. Propose the split,
  let the user choose, then make separate commits.
- **Is it working?** A commit is a *working* step. If dbt exists and models changed, run
  `dbt build --target dev` first; if it fails, report the failure and **do not commit**. Skip this
  check only when dbt isn't set up yet. Never commit a red build to "save progress".

## 2. Secret & junk guard — every time, no exceptions

```bash
git status --porcelain --ignored | grep '^!!' | head        # confirm ignores are working
git diff --cached --name-only                               # nothing secret about to land
```

Refuse to proceed if any of these are staged: `.env`, `*.duckdb`, `Heyra_Data_Engineer_Case.pdf`,
`RECAP_NOTES.md`, `dbt/target/`, `__pycache__`. They are gitignored; if one is staged, something is
wrong — stop and tell the user rather than committing it.

The repo is **private** and the case brief is Heyra's document, not ours. Never redistribute it.

## 3. The commit — one working step, one sentence

- **Subject:** one sentence, imperative, explains the whole step. `feat:` / `fix:` / `docs:` /
  `chore:` / `refactor:`. The history must read like the milestones (M0 · M1 · M2…), not like a
  changelog of an afternoon's edits.
- **Body:** at most ~3 lines, and only if it adds something the subject can't. It says *what
  changed* and **points at** the docs. It never duplicates them:
  - reasoning → `DECISIONS.md`
  - narrative, reversals, what broke → `DAY_REPORT.md`
  - schema → `SPEC.md`
- **A fixup for a bug introduced minutes ago is not its own commit** — fold it in (`--amend` if
  unpushed).
- The tests-first loop happens *inside* a commit, never as commits. No `wip: parser red`. A model
  and its tests land together — a model without its contract isn't a working step.
- End the message with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

Write long messages to a scratchpad file and use `git commit -F <file>` — heredocs with `-m` break
on quotes and em-dashes.

_(Why these rules exist: M0–M1 produced 10 commits — 8 of them one afternoon of doc churn — with
17–31-line essay messages, for 2 real milestones. Squashed to 4.)_

## 4. Branch — ALWAYS. `main` is protected.

**Never commit to `main`.** A branch ruleset on `main` requires a PR with passing checks, and
**admin bypass is off on purpose** — the rule binds the repo owner too, or it proves nothing
(DECISIONS.md §4). A push to `main` will simply be **rejected by the remote**.

**If the current branch is `main`, create one before staging anything:**

```bash
git switch -c <branch>          # branches off main, carrying the uncommitted work with it
git push -u origin <branch>     # -u sets upstream so later pushes are a bare `git push`
```

- **Name it after the work**, not the tool: `m5-ci`, `m6-dashboard`, `fix-parser-sentinel`.
  Derive it from what changed; ask only if genuinely ambiguous.
- **Already on a non-`main` branch?** Stay on it. Don't nest a branch off a branch.
- **Uncommitted work carries over** with `switch -c` — so branch first, then commit onto it.
- A new branch has **no remote counterpart, so there is no divergence and never a force push** —
  the rejected-push problem below only ever applies to a rewritten `main`.

**Then hand the user a PR link with the title and body already drafted.**

GitHub's compare URL accepts `title` and `body` as query params, so the form opens pre-filled and
the user only reviews and clicks **Create**. Build it with `scripts/pr_url.py` (URL-encodes and
prints the link):

```bash
.venv/bin/python scripts/pr_url.py --branch <branch> --title "<title>" --body-file <file>
```

> **NEVER use an em-dash (—) in the PR title or body.** Not once. Rewrite the sentence instead:
> use a colon, a full stop, or split it in two. This is a hard rule, not a preference to weigh
> against readability, and it applies to every character of generated PR text.
>
> | instead of | write |
> |---|---|
> | `M5 — CI on PR and a daily cron` | `M5: CI on PR and a daily cron` |
> | `two triggers — one pipeline` | `two triggers, one pipeline` |
> | `it warns, and that's the point — nobody reads it` | `it warns, and that's the point. Nobody reads it.` |
>
> If a sentence seems to need one, it is doing two jobs and wants to be two sentences.

**Draft the title by the same rule as a commit subject**: one sentence, says what changed. Name the
change, not the milestone. `M5 ci` is a label; `M5: CI on PR, daily cron, and dbt warnings
surfaced` is a sentence someone can act on.
_(With **rebase-only** merging the title does NOT become a commit message — each commit keeps its
own. So it's the label in the PR list, not load-bearing. With squash it would be; we don't squash.)_

**Draft the body by the same rule as a commit message: WHY, not what — the diff shows what.**
Reasoning → DECISIONS.md · narrative → DAY_REPORT.md · schema → SPEC.md. **Point at them; never
paste them.** A useful body is four short sections:

```markdown
<one line: what this lands>

**What landed** — the files, one line each
**Why <the non-obvious choice>** — the decision a reviewer would question, answered in 2 lines
**How to verify** — the command, the expected numbers, and where the reasoning lives
**Note** — anything half-wired, uncertain, or deliberately deferred. Say it before they find it.
```

That last section is the one that earns trust: flag what's incomplete rather than letting a reviewer
discover it. Communication is a graded dimension of this project — a PR body is evidence of how I
work, not paperwork.

**Then STOP.** Do **NOT** open the PR and do **NOT** merge. The PR *is* the review checkpoint, and an
agent that opens and merges its own PRs has reinvented pushing to `main` with extra ceremony. The
user clicks Create, watches CI, and merges.

**After they merge, their local `main` is behind** — the merge happened on GitHub. Remind them:

```bash
git switch main && git pull      # BEFORE starting the next milestone
```

Skipping this forks the next branch off a stale base, which is the classic first-PR trap.

## 5. Push — never force without asking

```bash
git push
```

**No credential handling here, ever.** The SSH key passphrase lives in the macOS Keychain
(`ssh-add --apple-use-keychain ~/.ssh/id_ed25519`); ssh-agent authenticates the push. Never read,
store, log, or ask for a passphrase or token. If the push prompts for one, the Keychain isn't set up
— tell the user to run `ssh-add --apple-use-keychain ~/.ssh/id_ed25519` themselves. They type it,
not you.

**If the push is rejected as non-fast-forward**, the local history was rewritten and has diverged.
Do **not** `--force` on your own — it overwrites the remote. Report it and ask. Only force with the
user's explicit go-ahead, and only after confirming the local tree is the one they want:

```bash
git rev-list --left-right --count origin/main...main   # behind / ahead
git push --force origin main                            # ONLY on explicit approval
```

## 6. Report

State plainly what landed: the subject line, the files, and the push result. If anything was
skipped, refused, or failed, say so — including a failed build or a rejected push. Never report a
commit as pushed when it wasn't.
