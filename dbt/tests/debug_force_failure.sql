-- TEST-ONLY chaos hook — NOT part of the 39-test contract.
--
-- Disabled by default (`enabled=false`), so on a normal build it is not even registered: the test
-- count stays 39 and it never runs. The scheduled cron's `workflow_dispatch` can set
-- `force_test_failure=true`, which enables it and makes it return a row → an ERROR-severity failure.
--
-- Use it to exercise the FAILURE path end to end at the real cron level:
--   • the build fails → the atomic swap is SKIPPED → live `main_marts` untouched, "Last refreshed"
--     stays at the last good run (the honesty guarantee, visible);
--   • dbt still writes run_results.json, so Elementary's on-run-end hook records status=fail →
--     `./scripts/observability_report.sh md:dogs` shows it (and the pass → fail history);
--   • the success heartbeat is skipped and the `/fail` ping fires → the dead man's switch alarms.
-- See ARCHITECTURE_PLAN.md M10 and SPEC.md "TEST-ONLY chaos hooks".
{{ config(enabled=var('force_test_failure', false)) }}

select 1 as forced_failure
