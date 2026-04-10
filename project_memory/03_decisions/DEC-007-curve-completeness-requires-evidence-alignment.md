# DEC-007: curve completeness requires evidence alignment

Status: accepted
Date: 2026-04-10

## Decision
A curve is not considered complete just because its anchor years and km rows have been filled in.

To count as complete, the curve must also be aligned with the appropriate evidence lanes for that tag family:

- the saved curve tag/base must match the intended Autotrader active-market listings
- the saved curve tag/base must match the intended sold/Grays evidence rows

## Reason
Anchors alone can create a neat-looking grid while still hiding a bad grouping, a wrong trim mix, or a tag that is not actually pulling the right market evidence. The Toyota Corolla hatch split exposed exactly that failure mode.

## Consequences
- Manual curve work may still save provisional rows before the evidence lanes are fully aligned.
- Those provisional rows should not be treated as a finished curve until active and sold evidence alignment is confirmed.
- Curve completion decisions should explicitly check both the shape of the grid and the relevance of the evidence feeding it.
