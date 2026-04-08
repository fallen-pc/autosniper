# DEC-001: repo-local project memory is primary

Status: accepted
Date: 2026-04-08

## Decision
AutoSniper uses repo-local project memory as its operational source of truth. Chat memory and tool session context are secondary.

## Reason
Session memory resets, folder drift, context window pressure, and tool restarts are too unreliable for a project with this many moving parts.

## Consequences
Every serious task should start from the manifest-driven memory bootstrap, not from chat recollection alone.
