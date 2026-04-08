# DEC-005: constitution, machine rules, decisions, and manifest are protected

Status: accepted
Date: 2026-04-08

## Decision
`project_memory/memory_manifest.yaml`, `00_constitution/`, `01_machine_rules/`, and `03_decisions/` are protected layers and require explicit approval to edit.

## Reason
If agents can rewrite project law and machine rules casually, the memory system will drift instead of protecting the project.

## Consequences
Pre-commit and CI should block protected-memory edits unless `AUTOSNIPER_MEMORY_WRITE_APPROVED=1` is set intentionally.
