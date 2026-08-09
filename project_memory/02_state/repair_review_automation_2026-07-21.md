# Repair Review automation - 2026-07-21

- Active valuation queues unresolved condition fragments into Repair Review before valuation refresh.
- Optional OpenAI suggestions are disabled by default and only prefill operator review fields; they cannot promote rules automatically.
- Older valuation rows with missing repair low/high fields can be repaired with the audited backfill script.
- Scheduler toggles, classifier failure behavior, queue integration, and backfill behavior have regression coverage.
