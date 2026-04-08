# System Architecture

AutoSniper has four important layers:

1. Data acquisition and pipeline scripts
   - Scrapers and pipeline utilities discover links, collect vehicle details, normalize datasets, and update lifecycle tables.
2. Shared domain logic
   - `shared/` contains dataset schemas, governance helpers, curve logic, canonical tagging, and other reusable domain rules.
3. Operator and UI surfaces
   - Streamlit pages and dashboard files present the governed datasets and trigger workflows.
4. Governance and memory enforcement
   - Governance code validates dataset contracts and curve integrity.
   - Project memory enforces durable business context, current state, and approved decisions.

The memory architecture overlays the existing codebase instead of replacing it:

- authoritative technical truth still comes from code where code already owns it
- machine-readable memory is generated from those code sources
- constitution and decisions capture business rules that code alone does not explain clearly
- state files capture what is currently happening, blocked, or risky
