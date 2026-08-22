# Resource, storage, and latency

- Duration: `602.01304` seconds; samples: `120`.
- No monotonic memory/handle/thread leak.
- Idle DB, WAL, GOLDI spool, and GOLDM spool growth: `0` bytes.
- Native latency samples: GOLDI `14`, GOLDM `10`.
- Actual real-tick processing: GOLDI `3,958,514`; GOLDM `3,916,275`.
- Internet Telegram latency is not claimed.
- Evidence: `../evidence/G19-resource-storage-latency/certification.json` and
  the external artifact `resource-analysis-actual-latency.json`.
- Production REAL orders: **DISABLED**.
