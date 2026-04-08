# DEC-006: agents update state memory only by default

Status: accepted
Date: 2026-04-08

## Decision
Agents may update `project_memory/02_state/` during normal work, but they should not update protected memory layers without explicit approval.

## Reason
State changes frequently and needs lightweight upkeep. Durable rules and decisions change rarely and should not drift through routine task execution.

## Consequences
Normal AI task completion should update current status, open issues, next actions, or recent changes when needed, without silently changing project law.
