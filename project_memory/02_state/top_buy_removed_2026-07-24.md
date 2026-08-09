# Top Buy removed

Date: 2026-07-24

The unused Top Buy gate was removed from AI Analysis and the valuation pipeline.
It had never produced a recorded Top Buy, did not filter listings, and its
uncertainty-buffer behavior was disabled. Buy / Review / Avoid remains the
operator decision policy, and proxy-max calculations are unchanged.

Removed:

- Top Buy calculation and persisted output fields
- AI Analysis badge and passed/failed explanations
- monitor placeholders, implementation module, and dedicated tests
- current flowchart and refactor-plan references

Historical CSV columns and existing runtime data were left untouched for
compatibility.

Verification:

- focused tests: 56 passed
- full suite: 551 passed
- AI Analysis Streamlit smoke: 0 exceptions and no Top Buy text rendered
