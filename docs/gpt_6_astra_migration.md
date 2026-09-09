# GPT-6 Astra repair-classifier migration

The OpenAI integration classifies unresolved repair fragments and supplies
operator-review defaults. Resale estimates, proxy bid limits, and buying actions
continue to use the governed curves and deterministic policy. Suggestions cannot
approve dictionary rules or repair decisions.

## Configuration

Selection order is the explicit CLI `--model` / function argument, then
`AUTOSNIPER_REPAIR_AI_MODEL`, then `gpt-6-astra`. Astra uses Chat Completions with
`reasoning_effort="low"` and the existing strict JSON schema, without temperature.
The prior `gpt-4.1-mini` request remains supported for rollback. The Python SDK
pin is retained unless an actual compatibility check requires a change.

Astra requests are capped at 8,192 completion tokens with a 120-second request
timeout and one SDK retry. The timeout applies per attempt; it is not a
120-second total batch deadline. A completion that reaches the token cap is
rejected instead of saving a partial batch. API/validation failures return CLI
exit code 1; absent credentials remain an optional skip. Request logs record
elapsed time and returned input/output/cached/reasoning token counts.

The scheduler requires `AUTOSNIPER_REPAIR_AI_CLASSIFIER=1`; its default is off.
`AUTOSNIPER_REPAIR_AI_LIMIT` retains the existing default of 25 fragments per
daily/hourly invocation. The manual CLI runs independently of the scheduler flag.

## Evaluation and promotion

1. Confirm the deployed commit, SDK, model override, scheduler flag, and API model
   access. Use credential presence checks only; never print a key or an env file.
2. Freeze a small set of actual operator-reviewed repair examples and their
   expected decisions. Use the same source rows and dictionary for both models.
3. Run each model with a fresh, separate `--output` file under ignored `output/`.
   Do not send expected labels as part of the prompt. `--dry-run` still makes a
   paid API request and only suppresses the suggestion-file write.
4. Check exact unique repair-key coverage, schema validity, failures, safety
   classifications, decision/category accuracy, actual token usage and elapsed
   time. Reject a response that is refused, truncated, malformed, or incomplete.
   A missing API key is a skipped run, not evaluation success.
5. Require no serious-risk downgrades, no invented pricing, and useful accuracy
   improvement within the evaluation's explicit cost/runtime limits before
   enabling recurring Astra use. Model confidence is not an accuracy score.
6. Release reviewed code through the governed VPS workflow. Verify the marker,
   installed source and service health, then run a small manual batch to a
   separate output path using the production environment. Inspect the Repair
   Review authoring screen locally; production intentionally hides that page.

Current API guidance and pricing:
[Astra migration](https://developers.openai.com/api/docs/guides/latest-model),
[Astra model](https://developers.openai.com/api/docs/models/gpt-6-astra), and
[GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
Record the evaluation date and actual usage; token rates alone do not determine
the cost of a completed classification batch.

## Existing suggestions and rollback

The suggestion cache is keyed by `repair_key`, independently of model. Merely
switching models preserves previous suggestions. `--force` replaces matching
keys in the selected output file, so use it only with a bounded queue after
backing up the production suggestion file. Never use an evaluation output as an
implicit replacement for operator-approved decisions.

Rollback sets `AUTOSNIPER_REPAIR_AI_MODEL=gpt-4.1-mini` (or disables the optional
classifier), restores the previous suggestion file if any suggestions were
promoted, and verifies the next result's model and key coverage. Preserve the
prior scheduler enable state. Use the normal governed release rollback if the
code or service itself fails validation.

## 2026-09-09 verification boundary

The deployed baseline was `92b845f19a9bf9ed2405fad1df642ffeae90c457`, with SDK
`2.26.0`, no configured OpenAI key, and the optional classifier disabled. Its
3,085-row governed decision file matched the local committed file exactly
(SHA256 `7f1d8812705c3255a59f0daa9b2b93eb7800ff1c45f3011cd9cab31ad51485f8`).

A frozen local comparison set contains 50 unique repairs, including 13
mechanical/structural hard-avoid references. Of the labels, 42 record operator
approval, seven record bulk review without an identified reviewer, and one
records bulk AI review. This measures agreement with saved references, not
independently certified accuracy. Expected labels are excluded from prompts.

The existing local credential successfully retrieved `gpt-6-astra` model
metadata. Both actual comparison requests (`gpt-6-astra` and `gpt-4.1-mini`)
then failed with HTTP 429 `credit_balance_exhausted`. No classifications or
token-usage records were returned, so quality, latency under successful load,
and per-batch cost remain unmeasured. The ignored local
`output/astra_migration_20260909/` directory retains the frozen inputs,
methodology, runner, and failure metadata. Preserve it before another run.

Code deployment must keep the classifier disabled until a funded credential
is available and the comparison and production canary pass. Production
credential configuration and live activation are separate from shipping this
compatible code.
