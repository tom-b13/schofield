# Changelog

## Epic K Phase-0

- Centralised ETag header emission via `app.logic.header_emitter.emit_etag_headers`
- Pre-body preconditions pipeline for write routes:
  - 415 PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED when Content-Type is not `application/json`
  - 428 PRE_IF_MATCH_MISSING when `If-Match` header is missing or blank
- Guard-based mismatch handling only:
  - Answers/screens mismatch → 409 PRE_IF_MATCH_ETAG_MISMATCH
  - Documents reorder mismatch → 412 PRE_IF_MATCH_ETAG_MISMATCH with diagnostics
- Expose domain headers via CORS: `ETag`, `Screen-ETag`, `Question-ETag`, `Document-ETag`, `Questionnaire-ETag`
- Non-breaking release; preserves token values and does not add runtime behaviour outside specified scope

