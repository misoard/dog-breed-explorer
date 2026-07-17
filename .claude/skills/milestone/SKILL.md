---
name: milestone
description: End-of-milestone check — verify the build is green, tick only what's evidenced, reconcile the docs against the live pipeline, update DAY_REPORT, and prepare the ship ONLY if nothing needs a human decision. Use when the user says a milestone is finished or invokes it explicitly.
allowed-tools: [Bash, Read, Edit, Write, Grep, Glob]
---

# /milestone — close out a milestone honestly

Run the mechanical checks with a script, so they cannot be answered by optimism. Then do the
judgment pass, which a script cannot. **Never tick a box from memory; never auto-resolve a
decision.**

## 1. The mechanical pass — run it first, read it before anything else

```bash
.venv/bin/python scripts/audit.py --milestone M<n>
```

It reports, and never edits:
- **build green?** exit code + `PASS/WARN/ERROR`. A non-zero exit ends the run — an unfinished
  milestone is not a milestone.
- **`Found N models, M data tests`** — dbt DROPS a test whose `ref()` doesn't resolve. If M fell,
  a test silently stopped existing. Investigate before anything else.
- **numbers**: every figure in `LIVE_NUMBERS` read from the warehouse, and which docs quote it.
- **coverage**: every test/model/seed on disk vs SPEC + ARCHITECTURE_PLAN.
- **checklist**: every unticked `- [ ]`.

If `audit.py` exits non-zero, **the answer is a report, not a commit.**

## 2. Tick the checklist — from evidence only

For each `- [ ]` in the milestone: tick it **only if you can point at the artifact** — the file
exists, its tests are in the green run, the number matches. If you cannot, it stays unticked and
goes in the report as remaining work.

**Never tick because you remember doing it.** When you tick, append what makes it checkable
(the row count, the test name, the verified figure), so the tick is auditable later.

## 3. The judgment pass — two kinds of inconsistency, and they are NOT the same

This is the whole reason this is a skill and not a cron job.

**MECHANICAL drift → fix it, list it.** The docs quote a number the pipeline no longer produces.
The live pipeline is the truth. Correct every doc, and report each correction as
`file: old → new (why)`.
> e.g. SPEC said 3,539 bridge rows; the warehouse says 3,538 (a sentinel was excluded).

**SEMANTIC disagreement → STOP. Ask.** Two docs disagree about *intent*, or a decision no longer
matches what was built. You do not get to pick a side — picking one buries a decision the user
owns.
> e.g. "is Mongrel's sentence a free-text tag to warn about, or a sentinel to exclude?"
> Both readings were defensible. Only the user could choose.

**The test:** if reconciling requires knowing *what was decided*, it's semantic → ask.
If it only requires knowing *what the data says*, it's mechanical → fix.

Also reconcile, since `audit.py` only checks existence, not agreement:
- a decision in DECISIONS.md that the code no longer implements
- a SPEC column list vs the model's real output
- a claim in one doc contradicted by another (**a claim a test has since disproved is not a
  disagreement — the test wins, fix the doc, and say so**)

## 4. DAY_REPORT — the narrative the other docs deliberately drop

Append/extend the day's section. **Problem → solution**, in the user's voice, leading with what
would matter to someone who wasn't there. Include:
- **reversals with their reasoning intact** — DECISIONS.md keeps only where it landed; this is the
  only place the *path* survives, and a reversal you can explain is stronger evidence of thinking
  than a decision never tested
- **what broke and how it was caught** — especially anything a test caught that a human missed
- **what I got wrong** — bad predictions, wrong claims, bugs in my own fixes. This is the most
  valuable content in the file and the easiest to quietly omit
- **what's still open**, honestly, including anything only *partly* verified

Do NOT restate DECISIONS.md. Reasoning → DECISIONS · schema → SPEC · milestones → PLAN.

## 5. The gate — prepare the ship ONLY if all of these hold

1. `audit.py` exits **0**
2. every checklist item in the milestone is ticked **with evidence**
3. **zero** semantic inconsistencies pending — nothing waiting on a user decision
4. DAY_REPORT is updated

If any fails: **report and stop.** Say precisely what's missing and what you need. A milestone
that isn't done is not made done by committing it.

If all pass, prepare — **do not run** — the `/ship` plan: the commit split (one logical working
step each), the one-sentence subjects, and any `--force`/branch caveats. **`/ship` is the user's
to invoke**: they review, they commit (CLAUDE.md).

## 6. Report

Lead with the verdict — **ready** or **not ready, because X**. Then: what was ticked and on what
evidence · what was mechanically corrected (`old → new`) · what needs a decision · what's still
open. If anything was skipped or only partly verified, say so. Never report a milestone as closed
when a box is open.
