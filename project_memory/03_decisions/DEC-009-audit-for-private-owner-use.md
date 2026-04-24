# DEC-009: audit for private owner use, not commercial SaaS

Status: accepted
Date: 2026-04-24

## Decision
AutoSniper should be audited and judged against fitness for safe private owner use.

It should not be audited as if it were intended for:

- commercial distribution
- public multi-user deployment
- enterprise SaaS operation

This decision does not lower the standard for issues that can directly affect buying decisions or system trustworthiness.

Audits must still treat these as high priority:

- valuation correctness
- data integrity and dataset alignment
- scheduler and pipeline reliability
- money-impacting safeguards and operator-facing decision logic

## Reason
The project is a private owner-operated tool, not a commercial software product. Comparing it to a production-grade public platform creates noise and can pull attention away from the things that matter most for getting the tool running reliably for the owner.

## Consequences
- Audits should focus on whether the tool is reliable and understandable for the owner in normal private use.
- Findings that only matter for public SaaS, enterprise compliance, multi-tenant hardening, or commercial scale should be treated as lower priority unless the intended use changes.
- Findings that can cause bad buying decisions, broken daily operation, misleading prices, or hidden data drift remain important and should still be called out clearly.
