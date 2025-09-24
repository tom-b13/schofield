# Epic B - Questionnaire Service
## objective

Provide the backend service that defines, stores, validates, and serves questionnaires and answers. The service is authoritative for integrity and gating of document generation—**excluding conditional-question logic** **and progress computation** (both delivered in other epics).

## out-of-scope functionality

* **Conditional visibility is out of scope.** All questions are treated as available; any UI hints are non-authoritative.
* **Progress computation is out of scope** for this epic and will be delivered by another epic.

## in-scope functionality

* **Questionnaire & question management** CRUD for questionnaires, screens, questions, answer types, input hints, tooltips. Bulk import/export to spreadsheet formats.\*\*

  **Answer types & validation**
  `short_string`, `long_text`, `boolean`, `number`, `enum_single`, `date`. Type-aware validation.
* **Gating** Block handbook generation until all mandatory questions are valid.
* **Pre-population** Reuse prior answers to pre-populate the questionnaire.
* **Integrations**
  Stable interfaces for: (a) ingestion/upsert of answers, (b) a generation workflow that **calls the gating check** before attempting document generation.
* **Autosave (per-answer) — backend only**

  * Atomic **single-answer upsert** for one `(response_set_id, question_id)` per request (uses existing uniqueness guarantees).
  * **Type-aware validation**; failures return `422` with field-level detail.
  * **Idempotency** via `Idempotency-Key` header; identical retries are safe and return the same outcome.
  * **Optimistic concurrency** using `If-Match: <ETag>`; mismatches return `409 Conflict` with the server’s current token.

## goals

* Single source of truth for questionnaires, answers, validation, and completion.
* Deterministic, reproducible behaviour suitable for audit and compliance.
* Fast authoring and iteration via spreadsheets without code changes.

## deliverables

* Backend services for questionnaire CRUD, answer intake, and validation.
* Importer and exporter for questionnaire spreadsheets.
* End-to-end tests covering edits, ingestion, and document-generation gating.

## non-functional requirements

* **Performance:** Responsive with 200–400 questions per questionnaire.
* **Reliability:** Durable storage; optimistic concurrency (ETags) to avoid lost updates.
* **Security:** Server-side validation; reject malformed or out-of-scope writes. **Authentication required; fine‑grained authorization (RBAC/roles) is out of scope and will be delivered in a separate Security/Access epic.**
* **Flexibility:** Questionnaire updates without redeploys; spreadsheet-driven where useful.

## api shape

* **GET /questionnaires/{id}** → Questionnaire metadata and screens index (no questions).

* **GET /response-sets/{response\_set\_id}/screens/{screen\_id}** → Returns screen metadata and all questions bound to that screen **with any existing answers for the response set**; includes `ETag`. No conditional filtering. 

* **\[Optional] POST /response-sets/{id}/answers**\*\*:batch\*\* → Bulk upsert for importer/integration use only; not used for interactive autosave. May be omitted if imports write server-side.

* **POST /response-sets/{id}/regenerate-check** → `ok: true` when no outstanding mandatory items; otherwise list blocking items.

* **POST /questionnaires/import** → **CSV import (v1.0)** for authoring updates.

  * **Encoding:** UTF‑8, RFC4180, header row required.
  * **Columns:** `external_qid` (required; unique key), `screen_key` (string), `question_order` (int), `question_text` (text), `answer_type` (one of ERD `answer_kind`: short\_string|long\_text|boolean|number|enum\_single), `mandatory` (true|false), `placeholder_code` (optional), `options` (for enum types only; `value[:label]` pairs delimited by `|`).
  * **Semantics:** Upsert by `external_qid`. Missing `external_qid` → create. Duplicate `external_qid` rows in a single file are rejected. CSV v1.0 **deletes** questions not present in the CSV; any existing question missing from the file will be removed.
  * **Mapping:** `options` are expanded into `AnswerOption` rows in import order (used as `sort_index`).
  * **Response:** `{created, updated, errors[]}` with CSV line numbers and messages.

* **GET /questionnaires/{id}/export** → **CSV export (v1.0)** snapshot for authoring and review.

  * **Encoding:** UTF‑8, RFC4180, header row required.
  * **Columns:** `external_qid` (required; unique key), `screen_key` (string), `question_order` (int), `question_text` (text), `answer_type` (one of ERD `answer_kind`: short\_string|long\_text|boolean|number|enum\_single), `mandatory` (true|false), `placeholder_code` (optional), `options` (for enum types only; `value[:label]` pairs delimited by `|`).
  * **Export building (DB→CSV):**

    * **Isolation:** Run export inside a **read-only, repeatable-read** transaction (or equivalent snapshot) to guarantee a consistent snapshot.
    * **Selection:** Pull rows scoped to the questionnaire (e.g., `questionnaire_id = :id`) from `QuestionnaireQuestion` plus **left join** to screens if modeled (or read `screen_key` from the question record if denormalised).
    * **Projection:** Emit exactly the CSV columns above. Derive:

      * `section_key` = `Section.screen_key` or `QuestionnaireQuestion.screen_key`.
      * `question_order` = integer order stored on the question; default to stable ordinal if null.
      * `answer_type` = stored enum token (no translation).
      * `options` for enum types via ordered aggregation of `AnswerOption` on the question: `string_agg(ao.value || COALESCE(':'||ao.label,''), '|' ORDER BY ao.sort_index, ao.value)`.
    * **Sorting (stable):** `ORDER BY screen_key NULLS LAST, question_order NULLS LAST, question_id` to provide deterministic files and stable diffs.
    * **Escaping:** RFC4180 quoting (wrap fields containing comma, quote, or newline in double quotes; escape `"` as `""`). Always emit a header row.
    * **Streaming:** Stream the response in chunks to avoid buffering the entire file; set `Content-Type: text/csv; charset=utf-8` and a strong `ETag` computed from the export payload (or `SHA-256` over the rowset).
    * **Null/empty handling:** Emit empty cells for `placeholder_code`, `screen_key`, or `question_order` when absent; leave `options` empty for non‑enum types.
    * **Performance hints:** Use existing indexes on `(questionnaire_id, question_order)` and `AnswerOption(question_id, sort_index)`; batch‑fetch options by question ids and aggregate in memory if needed.
    * **Diagnostics:** If no questions exist for the questionnaire, return a valid CSV with just the header row (HTTP 200). If the questionnaire id is unknown, return `404`.

* **PATCH /response-sets/{response\_set\_id}/answers/{question\_id}** → Per-answer autosave. Headers: `Idempotency-Key` (required), `If-Match: <etag>`. Body holds a type-appropriate `value` (and `option_id` where applicable). Responses: `200 OK` with `{ saved: true, etag }`; `409 Conflict` on precondition failure; `422 Unprocessable Entity` on validation errors; `404 Not Found` for unknown IDs.

## API documentation specification

* **Source of truth:** OpenAPI **3.1** in `docs/api/openapi.yaml`. This file defines paths, parameters/headers, responses, and embeds JSON Schemas under `components.schemas`.
* **Schemas:** Publish and version the request/response JSON Schemas used by the endpoints in `docs/schemas/`. Minimum set for Epic B:

  * `AnswerUpsert` (single-answer autosave)
  * `AnswerDeltaBatch` (batch upsert)
  * `Error` / `ValidationError` (problem+json style)
* **Headers & concurrency (documented per operation):**

  * `Idempotency-Key` (required for autosave), `If-Match` for concurrency.
  * Responses include `ETag` and `X-Request-Id`. Document rate-limit headers if applicable.
* **Errors:** Use `application/problem+json` with fields `{type, title, status, detail, instance, errors[]}`. Validation items carry `{path, message, code}`.
* **Versioning & compatibility:** Expose as `/api/v1/...` (URI version) and commit to **non‑breaking additive changes only** within `v1`. Mark deprecations via `Deprecation: true` and `Sunset` headers.
* **Security:** `components.securitySchemes.bearerAuth` (JWT/bearer). Tag operations with required scopes (e.g., `questionnaire:read`, `answers:write`).
* **Examples:** Provide concrete request/response examples for every 2xx/4xx code in `components.examples` and reference them via `$ref`.
* **Docs output:** Render Redoc/Swagger UI from the OpenAPI file, published from CI. Contract tests (e.g., Schemathesis) run against the spec on PRs.

## data model notes

* Reuse Epic A entities for questions, options, response sets, and responses.
* No additional tables required for this epic; any conditional fields from other epics are **not evaluated** here.
