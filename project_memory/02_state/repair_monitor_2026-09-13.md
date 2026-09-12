# Repair Monitor and printable repair register, 2026-09-13

- Added a read-only `Repair Monitor` page to both development and VPS navigation. The page replays the current Repair Review queue through the deployed deterministic parser and separates `Needs decision`, `Hard avoid`, `Priced`, and no-cost context outcomes.
- The production surface does not write Repair Review decisions or pricing inputs. Astra suggestions remain advisory and operator-approved changes continue through tests, review, and the governed release path.
- The page provides action-first tabs, repair-text and occurrence filters, Astra rationale for unresolved items, a complete CSV download, and a printable HTML download.
- Classifier checks now write a small current-status JSON file and append a run-history CSV beside the AI suggestion cache. Records include model, result, item counts, latency, and available token usage; telemetry persistence is best-effort and cannot fail the classifier.
- A standalone PDF generator creates a complete landscape repair register from specified queue, suggestion, and decision snapshots. The 2026-09-13 VPS snapshot contained 439 repair lines: 252 priced, 47 needing a decision, 53 hard avoids, and 87 no-cost context entries.
- Verification covered focused monitor/navigation/classifier tests, the complete repository suite, governance/readiness/project-memory checks, browser rendering, and visual plus text inspection of the 29-page PDF.
