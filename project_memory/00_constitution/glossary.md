# Glossary

- `canonical_tag`: The normalized vehicle identity used for matching listings, grouping evidence, and attaching curve coverage.
- `curve`: A price band table keyed by `canonical_tag`, `anchor_year`, and `km_bucket`.
- `restricted_group_map`: The governed dataset that records canonical-tag grouping decisions used by restricted outputs.
- `valuation`: The process of estimating resale and decision support for a listing.
- `hammer bid`: Auction-side bid guidance informed by sold-car history and auction behavior.
- `project memory`: The repo-local memory system under `project_memory/` that replaces fragile chat-only continuity.
- `protected memory`: Constitution, machine rules, decisions, and the manifest. These require explicit approval to change.
- `state memory`: The `project_memory/02_state/` layer that tracks current status, open issues, next actions, and recent changes.
