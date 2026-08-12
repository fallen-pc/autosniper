# PR10 Review Hardening - 2026-08-11

The final PR10 source review was addressed as a separate slice from governed curve data and local runtime evidence.

- Carsales Apify imports now deduplicate independently by ad ID and URL, parse mixed timestamp offsets before choosing the newest row, collapse repeated content-only rows, and preserve legitimate zero values.
- Explicit supplier fuel labels remain authoritative; the shared canonical helper only infers hybrid fuel from known Toyota series prefixes when the source fuel is blank.
- Paid exact-URL runs require HTTPS Carsales private make/model URLs even when coverage preflight is skipped, and deferred imports return a distinct non-zero status.
- Body aliases no longer guess that every fastback is a coupe, people-mover matches take precedence over the generic commercial alias, Mercedes ML model badges are narrowly excluded from series inference, and punctuation-boundary behavior is documented and tested.
- AI Analysis Overview again renders confidence, completeness, risk, listing-profile, expected-sale, and analysis-note diagnostics.

Focused regressions and the full repository gates must pass before this slice is published.
