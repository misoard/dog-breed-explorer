-- TEST-ONLY chaos hook — NOT part of the 39-test contract.
--
-- Disabled by default (`enabled=false`); the scheduled cron's `workflow_dispatch` can set
-- `force_test_warn=true` to enable it as a WARN-severity test that returns a row.
--
-- Unlike the failure hook, a WARN does NOT fail the build: the run stays green, publishes gold
-- normally, and pings success — but the warn is surfaced by `scripts/annotate_warns.py` and recorded
-- by Elementary as status=warn. Use it to see the observability / warn-annotation path *without*
-- tripping the dead man's switch (a warn is drift for a human to judge, not a failure — DECISIONS §3).
-- See ARCHITECTURE_PLAN.md M10 and SPEC.md "TEST-ONLY chaos hooks".
{{ config(enabled=var('force_test_warn', false), severity='warn') }}

select 1 as forced_warn
