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

## 4. Branch — only if the user asks

Default is the **current branch**. Never create or switch branches on your own; a branch the user
didn't ask for is a commit they can't find.

If the user asks for a new branch ("/ship to a new branch", "/ship on a feature branch"):

```bash
git switch -c <branch>          # branches off current HEAD, keeping the staged work
git push -u origin <branch>     # -u sets upstream so later pushes are a bare `git push`
```

- **Name it after the work**, not the tool: `m2-dbt-staging`, `m3-marts`. Ask if it's ambiguous.
- A new branch has **no remote counterpart, so there is no divergence and never a force push** —
  the rejected-push problem below only exists on a rewritten `main`.
- **Already on a non-main branch?** Don't nest a new one off it unless asked — just commit there.
- **Uncommitted work carries over** to the new branch with `switch -c`, which is what we want:
  create the branch first, then commit onto it.
- Tell the user the branch name and the PR URL that GitHub prints, if they want one. Do **not**
  open a PR unless asked.

> Worth knowing: milestone branches + PRs into `main` are also what make the M5 CI actually fire —
> a `on: pull_request` workflow needs a PR to run against. Committing straight to `main` means the
> PR-triggered half of CI never demonstrates itself.

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
