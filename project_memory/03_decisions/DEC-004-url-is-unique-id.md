# DEC-004: URL is the unique identifier

Status: accepted
Date: 2026-04-08

## Decision
The full listing URL is the canonical unique identifier for lifecycle tracking and dataset joins unless a future approved migration replaces it everywhere.

## Reason
The current pipeline, state table, and tracking flows already depend on URL identity. Letting agents invent alternate identifiers would break continuity.

## Consequences
Tasks touching state tracking, matching, or dataset joins must preserve URL-keyed behavior.
