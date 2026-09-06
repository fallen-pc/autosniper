# VPS PyArrow crash fix - 2026-09-04

- The production Streamlit process crashed twice at the same instruction in `libarrow.so.2500`, causing temporary Nginx 502 responses.
- The VPS had resolved the unpinned dependency to affected `pyarrow==25.0.0`.
- Pin `pyarrow==25.0.1`, whose Apache Arrow release includes the bundled mimalloc segmentation-fault fix.
- Preserve VPS runtime data; upgrade only the Python dependency and restart the dashboard service.
