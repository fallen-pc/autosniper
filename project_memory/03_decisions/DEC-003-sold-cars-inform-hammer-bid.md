# DEC-003: sold cars inform hammer bid, not resale override

Status: accepted
Date: 2026-04-08

## Decision
Historical sold-car evidence may inform hammer-bid strategy, but it does not become a resale-estimate override by default.

## Reason
Auction outcomes and resale guidance are related but not interchangeable. Treating them as the same thing would mix two separate decision surfaces.

## Consequences
Future work on valuation or profit logic must keep hammer-bid reasoning separate from resale-estimate governance unless an explicit new decision changes that rule.
