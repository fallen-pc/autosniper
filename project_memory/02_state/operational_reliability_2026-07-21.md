# Operational reliability - 2026-07-21

- CSV read-modify-write operations are serialized with destination-scoped lock files and retry transient Windows replace locks.
- Canonical-tagging and restricted-dataset diagnostics now write bounded latest snapshots instead of extending multi-gigabyte append-only audit files.
- Dashboard CSV counts use logical records, including quoted fields containing embedded newlines.
- Focused reliability and canonical-tagging regression coverage is included in the same commit.
