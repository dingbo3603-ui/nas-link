# NAS Link architecture decisions

## Data safety

The drop folder is a staging area, not the authoritative library. A file is accepted only after it is stable across two watcher passes. The service hashes it, checks for an existing content hash, records metadata, and then moves it atomically on the same NAS volume. Duplicate inputs are retained in `review/duplicates` instead of being deleted.

Backups are append-only snapshots over content-addressed blobs. A snapshot becomes `complete` only after every referenced blob exists and a manifest is written. File restore reads through the snapshot entry rather than accepting a raw NAS path from a client.

## Search and AI

DeepSeek never chooses an arbitrary filesystem path. The server expands a natural-language query, searches its local index, and gives the model a bounded list of real candidates. The answer may only return candidate IDs; unknown IDs are discarded. The UI then resolves those IDs back to database records.

Classification has a deterministic fallback by extension. DeepSeek output is constrained to a fixed top-level category list and sanitized before it is used in a directory name. If the API fails, ingestion continues with local classification and records the warning.

## Desktop trust boundary

The renderer is sandboxed, has no Node integration, and loads local assets only. OS clipboard, filesystem, backup and network operations stay in the Electron main process behind a narrow preload bridge. Renderer-provided file paths are not used for NAS-side path traversal; server backup paths are normalized and rejected if absolute or parent-relative.

## Known MVP limitations

- Text clipboard only; images, HTML and files-on-clipboard are not synchronized yet.
- Shared-token authentication is intended for a trusted LAN. HTTPS should be enabled before crossing an untrusted network.
- PDF, DOCX, XLSX and plain-text extraction are supported. OCR for scanned documents and images is not yet included.
- Search is keyword plus DeepSeek candidate ranking, not an embedding/vector index.
- Snapshot retention and immutable/offline replication are not automated yet.
