# Epic B - Questionnaire Service

## objective

Provide the backend service that defines, stores, validates, and serves questionnaires and answers. The service is authoritative for integrity and gating of document generation—**excluding conditional-question logic** **and progress computation** (both delivered in other epics).

## out-of-scope functionality

* **Conditional visibility is out of scope.** All questions are treated as available; any UI hints are non-authoritative.
* **Progress computation is out of scope** for this epic and will be delivered by another epic.

## in-scope functionality

* **Questionnaire & question management** CRUD for questionnaires, screens, questions, answer kinds, input hints, tooltips. Bulk import/export to spreadsheet formats.\*\*

  **Answer kinds & validation**
  `short_string`, `long_text`, `boolean`, `number`, `enum_single`. Type-aware validation.
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
* **Security:** Server-side validation; reject malformed or out-of-scope writes. **Authentication required; fine-grained authorization (RBAC/roles) is out of scope and will be delivered in a separate Security/Access epic.**
* **Flexibility:** Questionnaire updates without redeploys; spreadsheet-driven where useful.

## api shape

* **GET /questionnaires/{id}** → Questionnaire metadata and screens index (no questions).

* **GET /response-sets/{response\_set\_id}/screens/{screen\_id}** → Returns screen metadata and all questions bound to that screen **with any existing answers for the response set**; includes `ETag`. No conditional filtering.

* **\[Optional] POST /response-sets/{id}/answers**\*\*:batch\*\* → Bulk upsert for importer/integration use only; not used for interactive autosave. May be omitted if imports write server-side.

* **POST /response-sets/{id}/regenerate-check** → `ok: true` when no outstanding mandatory items; otherwise list blocking items.

* **POST /questionnaires/import** → **CSV import (v1.0)** for authoring updates.

  * **Encoding:** UTF-8, RFC4180, header row required.
  * **Columns:** `external_qid` (required; unique key), `screen_key` (string), `question_order` (int), `question_text` (text), `answer_kind` (one of ERD `answer_kind`: short\_string|long\_text|boolean|number|enum\_single), `mandatory` (true|false), `placeholder_code` (optional), `options` (for enum types only; `value[:label]` pairs delimited by `|`).
  * **Semantics:** Upsert by `external_qid`. Missing `external_qid` → create. Duplicate `external_qid` rows in a single file are rejected. CSV v1.0 **deletes** questions not present in the CSV; any existing question missing from the file will be removed.
  * **Mapping:** `options` are expanded into `AnswerOption` rows in import order (used as `sort_index`).
  * **Response:** `{created, updated, errors[]}` with CSV line numbers and messages.

* **GET /questionnaires/{id}/export** → **CSV export (v1.0)** snapshot for authoring and review.

  * **Encoding:** UTF-8, RFC4180, header row required.
  * **Columns:** `external_qid` (required; unique key), `screen_key` (string), `question_order` (int), `question_text` (text), `answer_kind` (one of ERD `answer_kind`: short\_string|long\_text|boolean|number|enum\_single), `mandatory` (true|false), `placeholder_code` (optional), `options` (for enum types only; `value[:label]` pairs delimited by `|`).
  * **Export building (DB→CSV):**

    * **Isolation:** Run export inside a **read-only, repeatable-read** transaction (or equivalent snapshot) to guarantee a consistent snapshot.
    * **Selection:** Pull rows scoped to the questionnaire (e.g., `questionnaire_id = :id`) from `QuestionnaireQuestion` plus **left join** to screens if modeled (or read `screen_key` from the question record if denormalised).
    * **Projection:** Emit exactly the CSV columns above. Derive:

      * `section_key` = `Section.screen_key` or `QuestionnaireQuestion.screen_key`.
      * `question_order` = integer order stored on the question; default to stable ordinal if null.
      * `answer_kind` = stored enum token (no translation).
      * `options` for enum types via ordered aggregation of `AnswerOption` on the question: `string_agg(ao.value || COALESCE(':'||ao.label,''), '|' ORDER BY ao.sort_index, ao.value)`.
    * **Sorting (stable):** `ORDER BY screen_key NULLS LAST, question_order NULLS LAST, question_id` to provide deterministic files and stable diffs.
    * **Escaping:** RFC4180 quoting (wrap fields containing comma, quote, or newline in double quotes; escape `"` as `""`). Always emit a header row.
    * **Streaming:** Stream the response in chunks to avoid buffering the entire file; set `Content-Type: text/csv; charset=utf-8` and a strong `ETag` computed from the export payload (or `SHA-256` over the rowset).
    * **Null/empty handling:** Emit empty cells for `placeholder_code`, `screen_key`, or `question_order` when absent; leave `options` empty for non-enum types.
    * **Performance hints:** Use existing indexes on `(questionnaire_id, question_order)` and `AnswerOption(question_id, sort_index)`; batch-fetch options by question ids and aggregate in memory if needed.
    * **Diagnostics:** If no questions exist for the questionnaire, return a valid CSV with just the header row (HTTP 200). If the questionnaire id is unknown, return `404`.

* **PATCH /response-sets/{response\_set\_id}/answers/{question\_id}** → Per-answer autosave. Headers: `Idempotency-Key` (required), `If-Match: <etag>`. Body holds a type-appropriate `value` (and `option_id` where applicable). Responses: `200 OK` with `{ saved: true, etag }`; `409 Conflict` on precondition failure; `422 Unprocessable Entity` on validation errors; `404 Not Found` for unknown IDs.

## API documentation specification

* **Source of truth:** OpenAPI **3.1** in `docs/api/openapi.yaml`. This file defines paths, parameters/headers, responses, and embeds JSON Schemas under `components.schemas`.
* **Schemas:** Publish and version the request/response JSON Schemas used by the endpoints in `docs/schemas/`. Minimum set for Epic B:

  * `AnswerUpsert` (single-answer autosave)
  * `AnswerDeltaBatch` (batch upsert)
  * `Error` / `ValidationError` (problem+json style)
* **Headers & concurrency (documented per operation):**

  * `Idempotency-Key` (required for autosave), `If-Match` for concurrency.
  * Responses include `ETag` and `X-Request-Id`. Document rate-limit headers if applicable.
* **Errors:** Use `application/problem+json` with fields `{type, title, status, detail, instance, errors[]}`. Validation items carry `{path, message, code}`.
* **Versioning & compatibility:** Expose as `/api/v1/...` (URI version) and commit to **non-breaking additive changes only** within `v1`. Mark deprecations via `Deprecation: true` and `Sunset` headers.
* **Security:** `components.securitySchemes.bearerAuth` (JWT/bearer). Tag operations with required scopes (e.g., `questionnaire:read`, `answers:write`).
* **Examples:** Provide concrete request/response examples for every 2xx/4xx code in `components.examples` and reference them via `$ref`.
* **Docs output:** Render Redoc/Swagger UI from the OpenAPI file, published from CI. Contract tests (e.g., Schemathesis) run against the spec on PRs.

## data model notes

* Reuse Epic A entities for questions, options, response sets, and responses.
* No additional tables required for this epic; any conditional fields from other epics are **not evaluated** here.

# 1. Scope

## **1.1 Purpose**
The questionnaire service provides a central system to define, manage, and validate questionnaires and their responses. Its objective is to ensure reliable data capture and enforce completion rules before document generation.

## **1.2 Inclusions**

* Creation, update, and retrieval of questionnaires, screens, questions, and answer kinds
* Validation of responses by answer kind, with clear error reporting
* Per-answer autosave with concurrency and idempotency safeguards
* Bulk import and export of questionnaires in CSV format for authoring and review
* Gating check to confirm all mandatory questions are complete before generation
* Pre-population of questionnaires using prior responses

## **1.3 Exclusions**

* Conditional visibility of questions
* Progress tracking or completion percentages
* Role-based access control or fine-grained authorisation
* Any features outside questionnaire definition, response intake, and gating

## **1.4 Context**
This story is part of Epic B, which establishes the questionnaire service as the source of truth for questions and responses. It integrates with document generation by enforcing gating checks before content is produced. It exposes a versioned API that supports both interactive front-end applications and automated imports. External interactions are limited to client applications and related services that consume validated questionnaire data.

## 2.2 EARS Functionality

### 2.2.1 Ubiquitous requirements

* **U1** The system will create questionnaires, screens, questions, answer kinds, input hints, and tooltips.
* **U2** The system will update questionnaires, screens, questions, answer kinds, input hints, and tooltips.
* **U3** The system will delete questionnaires, screens, and questions when requested.
* **U4** The system will retrieve questionnaires, screens, and questions for authorised users.
* **U5** The system will validate responses according to the declared answer kind.
* **U6** The system will store responses in response sets.
* **U7** The system will provide stable interfaces for ingesting answers and invoking generation gating checks.
* **U8** The system will pre-populate questionnaires using prior responses where available.
* **U9** The system will export questionnaires to CSV with required columns and deterministic ordering.
* **U10** The system will import questionnaires from CSV with required columns and apply updates accordingly.
* **U11** The system will ensure that questionnaire data can be authored and iterated via spreadsheets without code changes.
* **U12** The system will enforce authentication on all operations.
* **U13** The system will provide consistent error responses using problem+json format.

### 2.2.2 Event-driven requirements

* **E1** When a client requests questionnaire metadata, the system will return questionnaire details and screen indexes.
* **E2** When a client requests a screen for a response set, the system will return screen metadata, bound questions, and existing answers.
* **E3** When a client submits a single answer, the system will upsert the answer for the specified response set and question.
* **E4** When a client submits a batch of answers, the system will upsert multiple answers in bulk.
* **E5** When a client triggers a regenerate check, the system will report whether mandatory questions are complete or list blocking items.
* **E6** When a questionnaire import file is submitted, the system will create, update, or delete questions according to the file contents.
* **E7** When a questionnaire export is requested, the system will generate and stream a CSV snapshot.

### 2.2.3 State-driven requirements

* **S1** While a questionnaire is incomplete, the system will block document generation.
* **S2** While a response set exists, the system will link each answer to that response set and its parent questionnaire.

### 2.2.4 Optional-feature requirements

* **O1** Where bulk import or integration is required, the system will allow batch answer upsert operations.

### 2.2.5 Unwanted-behaviour requirements

* **N1** If a response does not conform to the expected answer kind, the system will return a 422 validation error with field-level detail.
* **N2** If an idempotent request is retried with the same key, the system will return the original outcome without duplication.
* **N3** If an `If-Match` token does not match the server’s version, the system will return a 409 conflict response.
* **N4** If a requested questionnaire ID or screen ID is unknown, the system will return a 404 error.
* **N5** If a CSV import contains duplicate external question IDs, the system will reject the file and report errors.
* **N6** If a questionnaire has no questions, the system will return an empty CSV with only a header row on export.

### 2.2.6 Step Index

* **STEP-1** Questionnaire and question management → U1, U2, U3, U4
* **STEP-2** Answer kinds and validation → U5, N1
* **STEP-3** Gating check → S1, E5
* **STEP-4** Pre-population → U8
* **STEP-5** Interfaces for ingestion and generation → U7
* **STEP-6** Autosave per answer → E3, U6, N2, N3, N4
* **STEP-7** Bulk import and export → U9, U10, E6, E7, O1, N5, N6
* **STEP-8** Goals of reproducibility and iteration → U11
* **STEP-9** Authentication and security → U12
* **STEP-10** Error handling → U13, N1–N6
* **STEP-11** Data model context → S2

| Field                     | Description                                                      | Type                        | Schema / Reference                                          | Notes                                                                | Pre-Conditions                                                                                  | Origin   |
| ------------------------- | ---------------------------------------------------------------- | --------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | -------- |
| questionnaire\_id         | Unique identifier of a questionnaire requested or exported       | string (uuid)               | schemas/QuestionnaireId.schema.json                         | None                                                                 | Field is required and must be provided; Value must conform to UUID format                       | provided |
| response\_set\_id         | Identifier of a response set associated with answers and screens | string (uuid)               | schemas/ResponseSetId.schema.json                           | None                                                                 | Field is required and must be provided; Value must conform to UUID format                       | provided |
| screen\_id                | Identifier of a screen within a questionnaire                    | string (uuid)               | schemas/ScreenId.schema.json                                | None                                                                 | Field is required and must be provided; Value must conform to UUID format                       | provided |
| question\_id              | Identifier of a question for per-answer autosave                 | string (uuid)               | schemas/QuestionId.schema.json                              | None                                                                 | Field is required and must be provided; Value must conform to UUID format                       | provided |
| Idempotency-Key           | Unique token ensuring duplicate requests return the same result  | string                      | docs/api/openapi.yaml#/components/parameters/IdempotencyKey | Provisional reference until parameter is added to OpenAPI components | Field is required and must be provided; Value must be unique per logical request                | provided |
| If-Match                  | ETag token used for optimistic concurrency control               | string                      | docs/api/openapi.yaml#/components/parameters/IfMatch        | Provisional reference until parameter is added to OpenAPI components | Field is required and must be provided; Value must match the latest ETag of the resource        | provided |
| AnswerUpsert              | Structured body containing a single answer to upsert             | object                      | schemas/AnswerUpsert.schema.json                            | None                                                                 | Field is required and must be provided; Content must conform to referenced schema               | provided |
| AnswerUpsert.question\_id | Identifier of the question being answered                        | string (uuid)               | schemas/AnswerUpsert.schema.json#/properties/question\_id   | None                                                                 | Field is required and must be provided; Value must conform to UUID format                       | provided |
| AnswerUpsert.value        | Value supplied for the answer                                    | string \| number \| boolean | schemas/AnswerUpsert.schema.json#/properties/value          | Type varies by answer\_kind                                          | Field is required and must be provided; Value must conform to answer\_kind type                 | provided |
| AnswerUpsert.option\_id   | Identifier of selected option for enum answers                   | string (uuid)               | schemas/AnswerUpsert.schema.json#/properties/option\_id     | Only required for enum answers                                       | Field must be provided when answer\_kind is enum\_single; Value must conform to UUID format     | provided |
| AnswerDeltaBatch          | Structured body containing multiple answers for batch upsert     | object                      | schemas/AnswerDeltaBatch.schema.json                        | None                                                                 | Field is required and must be provided; Content must conform to referenced schema               | provided |
| CSVImportFile             | Questionnaire spreadsheet file uploaded for import               | file (csv)                  | schemas/CSVImportFile.schema.json                           | Must be UTF-8 encoded and RFC4180 compliant                          | File exists and is readable; Content parses as valid CSV; Content conforms to referenced schema | provided |
| CSVExportSnapshot         | Questionnaire spreadsheet produced on export                     | file (csv)                  | schemas/CSVExportSnapshot.schema.json                       | Re                                                                   |                                                                                                 |          |

| Field              | Description                                                   | Type          | Schema / Reference                                                           | Notes                                                        | Post-Conditions                                                                                                                                       |
| ------------------ | ------------------------------------------------------------- | ------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| saved              | Result flag for per-answer autosave requests                  | boolean       | #/components/schemas/AutosaveResult/properties/saved                         | Only present in PATCH /answers response                      | Field is required when autosave completes; Value is a boolean; Value reflects autosave outcome for the addressed question                             |
| etag               | Concurrency token associated with the returned resource state | string        | #/components/schemas/AutosaveResult/properties/etag                          | Returned with autosave and screen retrieval responses        | Value is a non-empty string; Value matches the server’s current entity tag for this resource; Value is stable for identical content                   |
| ok                 | Gating verdict indicating whether generation may proceed      | boolean       | #/components/schemas/RegenerateCheckResult/properties/ok                     | Present only in regenerate-check response                    | Field is required for regenerate-check; Value is true when no mandatory items remain; Value is false when blocking\_items contains at least one entry |
| blocking\_items\[] | List of unmet mandatory items that prevent generation         | list\[object] | #/components/schemas/RegenerateCheckResult/properties/blocking\_items/items  | Projection of gating failures returned by regenerate-check   | List may be empty when ok is true; Each item validates against the item schema; Ordering is deterministic for identical inputs                        |
| csv\_export        | Snapshot CSV produced by export                               | file (csv)    | schemas/CSVExportSnapshot.schema.json                                        | Returned by export endpoint for authoring and review         | File validates against schema; Content type is text/csv; Content is immutable within this step; Header row is present                                 |
| screen             | Screen metadata returned for a response set and screen        | object        | #/components/schemas/ScreenView                                              | Contains non-conditional metadata only                       | Object validates against schema; Object contains screen identifier and related metadata; Object excludes conditional-visibility fields                |
| questions\[]       | Questions for the screen with any existing answers            | list\[object] | #/components/schemas/QuestionWithAnswer                                      | Items correspond to bound questions for the requested screen | List may be empty when no questions are bound; Each item validates against schema; Ordering is deterministic by question order then id                |
| screens\[]         | Screens index for a questionnaire                             | list\[object] | #/components/schemas/ScreenIndexItem                                         | Returned by questionnaire metadata endpoint                  | List may be empty for questionnaires without screens; Each item validates against schema; Ordering is deterministic by screen order then id           |
| created            | Count of questions created by CSV import                      | integer       | #/components/schemas/ImportResult/properties/created                         | Returned only by CSV import response                         | Value is an integer ≥ 0; Field is required for CSV import responses                                                                                   |
| updated            | Count of questions updated by CSV import                      | integer       | #/components/schemas/ImportResult/properties/updated                         | Returned only by CSV import response                         | Value is an integer ≥ 0; Field is required for CSV import responses                                                                                   |
| errors\[]          | Row-level import errors with CSV line numbers and messages    | list\[object] | #/components/schemas/ImportResult/properties/errors/items                    | Projection of validation issues encountered during import    | List may be empty when no errors occurred; Each item validates against schema; Each item includes a valid line reference and message                  |
| errors\[].line     | CSV line number associated with the error                     | integer       | #/components/schemas/ImportResult/properties/errors/items/properties/line    | None                                                         | Value is an integer ≥ 1; Field is required when errors\[] is present                                                                                  |
| errors\[].message  | Human-readable explanation of the error                       | string        | #/components/schemas/ImportResult/properties/errors/items/properties/message | None                                                         | Value is a non-empty string; Field is required when errors\[] is present                                                                              |

| Error Code                                       | Field Reference           | Description                                                                                | Likely Cause                     | Flow Impact    | Behavioural AC Required |
| ------------------------------------------------ | ------------------------- | ------------------------------------------------------------------------------------------ | -------------------------------- | -------------- | ----------------------- |
| PRE\_QUESTIONNAIRE\_ID\_MISSING                  | questionnaire\_id         | questionnaire\_id is required but was not provided                                         | Missing value                    | halt\_pipeline | Yes                     |
| PRE\_QUESTIONNAIRE\_ID\_INVALID\_UUID            | questionnaire\_id         | questionnaire\_id does not conform to UUID format                                          | Invalid format                   | halt\_pipeline | Yes                     |
| PRE\_RESPONSE\_SET\_ID\_MISSING                  | response\_set\_id         | response\_set\_id is required but was not provided                                         | Missing value                    | halt\_pipeline | Yes                     |
| PRE\_RESPONSE\_SET\_ID\_INVALID\_UUID            | response\_set\_id         | response\_set\_id does not conform to UUID format                                          | Invalid format                   | halt\_pipeline | Yes                     |
| PRE\_SCREEN\_ID\_MISSING                         | screen\_id                | screen\_id is required but was not provided                                                | Missing value                    | halt\_pipeline | Yes                     |
| PRE\_SCREEN\_ID\_INVALID\_UUID                   | screen\_id                | screen\_id does not conform to UUID format                                                 | Invalid format                   | halt\_pipeline | Yes                     |
| PRE\_QUESTION\_ID\_MISSING                       | question\_id              | question\_id is required but was not provided                                              | Missing value                    | halt\_pipeline | Yes                     |
| PRE\_QUESTION\_ID\_INVALID\_UUID                 | question\_id              | question\_id does not conform to UUID format                                               | Invalid format                   | halt\_pipeline | Yes                     |
| PRE\_IDEMPOTENCY\_KEY\_MISSING                   | Idempotency-Key           | Idempotency-Key is required but was not provided                                           | Missing header                   | halt\_pipeline | Yes                     |
| PRE\_IDEMPOTENCY\_KEY\_NOT\_UNIQUE               | Idempotency-Key           | Idempotency-Key is not unique for the logical request                                      | Duplicate key                    | halt\_pipeline | Yes                     |
| PRE\_IF\_MATCH\_MISSING                          | If-Match                  | If-Match is required but was not provided                                                  | Missing header                   | halt\_pipeline | Yes                     |
| PRE\_IF\_MATCH\_ETAG\_MISMATCH                   | If-Match                  | If-Match value does not match the latest ETag of the resource                              | Stale or incorrect ETag          | halt\_pipeline | Yes                     |
| PRE\_ANSWER\_UPSERT\_MISSING                     | AnswerUpsert              | AnswerUpsert body is required but was not provided                                         | Missing body                     | halt\_pipeline | Yes                     |
| PRE\_ANSWER\_UPSERT\_SCHEMA\_MISMATCH            | AnswerUpsert              | AnswerUpsert does not conform to the referenced schema                                     | Schema validation failure        | halt\_pipeline | Yes                     |
| PRE\_ANSWER\_UPSERT\_QUESTION\_ID\_MISSING       | AnswerUpsert.question\_id | AnswerUpsert.question\_id is required but was not provided                                 | Missing value                    | halt\_pipeline | Yes                     |
| PRE\_ANSWER\_UPSERT\_QUESTION\_ID\_INVALID\_UUID | AnswerUpsert.question\_id | AnswerUpsert.question\_id does not conform to UUID format                                  | Invalid format                   | halt\_pipeline | Yes                     |
| PRE\_ANSWER\_UPSERT\_VALUE\_MISSING              | AnswerUpsert.value        | AnswerUpsert.value is required but was not provided                                        | Missing value                    | halt\_pipeline | Yes                     |
| PRE\_ANSWER\_UPSERT\_VALUE\_KIND\_MISMATCH       | AnswerUpsert.value        | AnswerUpsert.value does not conform to the declared answer\_kind type                      | Type mismatch                    | halt\_pipeline | Yes                     |
| PRE\_ANSWER\_UPSERT\_OPTION\_ID\_REQUIRED        | AnswerUpsert.option\_id   | AnswerUpsert.option\_id is required when answer\_kind is enum\_single but was not provided | Missing conditional field        | halt\_pipeline | Yes                     |
| PRE\_ANSWER\_UPSERT\_OPTION\_ID\_INVALID\_UUID   | AnswerUpsert.option\_id   | AnswerUpsert.option\_id does not conform to UUID format                                    | Invalid format                   | halt\_pipeline | Yes                     |
| PRE\_ANSWER\_DELTA\_BATCH\_MISSING               | AnswerDeltaBatch          | AnswerDeltaBatch body is required but was not provided                                     | Missing body                     | halt\_pipeline | Yes                     |
| PRE\_ANSWER\_DELTA\_BATCH\_SCHEMA\_MISMATCH      | AnswerDeltaBatch          | AnswerDeltaBatch does not conform to the referenced schema                                 | Schema validation failure        | halt\_pipeline | Yes                     |
| PRE\_CSV\_IMPORT\_FILE\_MISSING                  | CSVImportFile             | CSVImportFile does not exist or is not readable                                            | Missing file or permissions      | halt\_pipeline | Yes                     |
| PRE\_CSV\_IMPORT\_FILE\_INVALID\_CSV             | CSVImportFile             | CSVImportFile content does not parse as valid CSV                                          | Malformed CSV                    | halt\_pipeline | Yes                     |
| PRE\_CSV\_IMPORT\_FILE\_SCHEMA\_MISMATCH         | CSVImportFile             | CSVImportFile content does not conform to the referenced schema                            | Schema mismatch                  | halt\_pipeline | Yes                     |
| PRE\_CSV\_EXPORT\_SNAPSHOT\_CALL\_FAILED         | CSVExportSnapshot         | CSVExportSnapshot call did not complete without error                                      | Upstream failure                 | halt\_pipeline | Yes                     |
| PRE\_CSV\_EXPORT\_SNAPSHOT\_SCHEMA\_MISMATCH     | CSVExportSnapshot         | CSVExportSnapshot does not match the declared schema                                       | Schema mismatch                  | halt\_pipeline | Yes                     |
| PRE\_CSV\_EXPORT\_SNAPSHOT\_NOT\_IMMUTABLE       | CSVExportSnapshot         | CSVExportSnapshot was not treated as immutable within this step                            | Unexpected mutation              | halt\_pipeline | Yes                     |
| PRE\_PROBLEM\_CALL\_FAILED                       | Problem                   | Problem provider call did not complete without error                                       | Upstream failure                 | halt\_pipeline | Yes                     |
| PRE\_PROBLEM\_SCHEMA\_MISMATCH                   | Problem                   | Problem object does not match the declared schema                                          | Schema mismatch                  | halt\_pipeline | Yes                     |
| PRE\_PROBLEM\_NOT\_IMMUTABLE                     | Problem                   | Problem object was not treated as immutable within this step                               | Unexpected mutation              | halt\_pipeline | Yes                     |
| PRE\_VALIDATION\_PROBLEM\_CALL\_FAILED           | ValidationProblem         | ValidationProblem provider call did not complete without error                             | Upstream failure                 | halt\_pipeline | Yes                     |
| PRE\_VALIDATION\_PROBLEM\_SCHEMA\_MISMATCH       | ValidationProblem         | ValidationProblem object does not match the declared schema                                | Schema mismatch                  | halt\_pipeline | Yes                     |
| PRE\_VALIDATION\_PROBLEM\_NOT\_IMMUTABLE         | ValidationProblem         | ValidationProblem object was not treated as immutable within this step                     | Unexpected mutation              | halt\_pipeline | Yes                     |
| PRE\_OPENAPI\_YAML\_MISSING                      | openapi.yaml              | openapi.yaml file does not exist or is not readable                                        | Missing file or permissions      | halt\_pipeline | Yes                     |
| PRE\_OPENAPI\_YAML\_INVALID\_YAML                | openapi.yaml              | openapi.yaml content does not parse as valid YAML                                          | Malformed YAML                   | halt\_pipeline | Yes                     |
| PRE\_OPENAPI\_YAML\_NOT\_OPENAPI\_31             | openapi.yaml              | openapi.yaml does not conform to OpenAPI 3.1 schema                                        | Schema mismatch                  | halt\_pipeline | Yes                     |
| PRE\_SCHEMAS\_DIR\_MISSING                       | schemas/\*.json           | schemas/\*.json directory does not exist or is not readable                                | Missing directory or permissions | halt\_pipeline | Yes                     |
| PRE\_SCHEMAS\_DIR\_INVALID\_JSON                 | schemas/\*.json           | One or more schema files do not parse as valid JSON                                        | Malformed JSON                   | halt\_pipeline | Yes                     |
| PRE\_SCHEMAS\_DIR\_MISSING\_ID                   | schemas/\*.json           | One or more schema files do not include a unique \$id                                      | Missing identifier               | halt\_pipeline | Yes                     |
| PRE\_SCHEMAS\_DIR\_BROKEN\_REF                   | schemas/\*.json           | One or more \$ref values do not resolve to an existing definition                          | Broken reference                 | halt\_pipeline | Yes                     |

| Error Code                                            | Output Field Ref   | Description                                                                | Likely Cause                              | Flow Impact         | Behavioural AC Required |
| ----------------------------------------------------- | ------------------ | -------------------------------------------------------------------------- | ----------------------------------------- | ------------------- | ----------------------- |
| POST\_SAVED\_MISSING\_WHEN\_AUTOSAVE                  | saved              | saved field is missing when autosave response is returned                  | Field omitted from response               | block\_finalization | Yes                     |
| POST\_SAVED\_NOT\_BOOLEAN                             | saved              | saved value is not a boolean in autosave response                          | Serialization or typing error             | block\_finalization | Yes                     |
| POST\_SAVED\_OUTCOME\_MISMATCH                        | saved              | saved value does not reflect actual autosave outcome                       | Incorrect result mapping                  | block\_finalization | Yes                     |
| POST\_ETAG\_EMPTY                                     | etag               | etag value is empty when a token is required                               | Missing or blank token                    | block\_finalization | Yes                     |
| POST\_ETAG\_MISMATCH                                  | etag               | etag value does not match server’s current entity tag                      | Stale or incorrect entity tag             | block\_finalization | Yes                     |
| POST\_ETAG\_NOT\_STABLE                               | etag               | etag value is not stable for identical content                             | Non-deterministic hashing or ordering     | block\_finalization | Yes                     |
| POST\_OK\_MISSING\_FOR\_REGENERATE\_CHECK             | ok                 | ok field is missing in regenerate-check response                           | Field omitted from response               | block\_finalization | Yes                     |
| POST\_OK\_FALSE\_WITH\_NO\_BLOCKERS                   | ok                 | ok is false when no mandatory blocking items remain                        | Incorrect gating verdict computation      | block\_finalization | Yes                     |
| POST\_OK\_TRUE\_WITH\_BLOCKERS                        | ok                 | ok is true while blocking\_items contains entries                          | Incorrect gating verdict computation      | block\_finalization | Yes                     |
| POST\_BLOCKING\_ITEMS\_ITEM\_SCHEMA\_INVALID          | blocking\_items\[] | One or more blocking\_items do not validate against item schema            | Schema or serialization mismatch          | block\_finalization | Yes                     |
| POST\_BLOCKING\_ITEMS\_NOT\_DETERMINISTIC             | blocking\_items\[] | blocking\_items ordering is not deterministic for identical inputs         | Unstable sort or non-deterministic source | block\_finalization | Yes                     |
| POST\_CSV\_EXPORT\_SCHEMA\_INVALID                    | csv\_export        | csv\_export file does not validate against declared schema                 | CSV shape or content mismatch             | block\_finalization | Yes                     |
| POST\_CSV\_EXPORT\_WRONG\_CONTENT\_TYPE               | csv\_export        | csv\_export content type is not text/csv                                   | Incorrect response headers                | block\_finalization | Yes                     |
| POST\_CSV\_EXPORT\_MUTATED                            | csv\_export        | csv\_export content is not immutable within this step                      | Post-creation modification occurred       | block\_finalization | Yes                     |
| POST\_CSV\_EXPORT\_HEADER\_MISSING                    | csv\_export        | csv\_export is missing the required header row                             | Header not written by exporter            | block\_finalization | Yes                     |
| POST\_SCREEN\_SCHEMA\_INVALID                         | screen             | screen object does not validate against schema                             | Schema or serialization mismatch          | block\_finalization | Yes                     |
| POST\_SCREEN\_IDENTIFIER\_MISSING                     | screen             | screen object does not contain a screen identifier                         | Missing required identifier               | block\_finalization | Yes                     |
| POST\_SCREEN\_METADATA\_MISSING                       | screen             | screen object does not contain required related metadata                   | Missing required metadata fields          | block\_finalization | Yes                     |
| POST\_SCREEN\_CONDITIONAL\_FIELDS\_PRESENT            | screen             | screen object includes conditional-visibility fields that must be excluded | Incorrect projection of screen fields     | block\_finalization | Yes                     |
| POST\_QUESTIONS\_ITEM\_SCHEMA\_INVALID                | questions\[]       | One or more questions items do not validate against schema                 | Schema or serialization mismatch          | block\_finalization | Yes                     |
| POST\_QUESTIONS\_ORDER\_INCORRECT                     | questions\[]       | questions list ordering is not by question order then id                   | Incorrect or unstable sort                | block\_finalization | Yes                     |
| POST\_SCREENS\_ITEM\_SCHEMA\_INVALID                  | screens\[]         | One or more screens items do not validate against schema                   | Schema or serialization mismatch          | block\_finalization | Yes                     |
| POST\_SCREENS\_ORDER\_INCORRECT                       | screens\[]         | screens list ordering is not by screen order then id                       | Incorrect or unstable sort                | block\_finalization | Yes                     |
| POST\_CREATED\_NOT\_NONNEGATIVE\_INTEGER              | created            | created value is not an integer greater than or equal to zero              | Wrong type or negative count              | block\_finalization | Yes                     |
| POST\_CREATED\_MISSING\_FOR\_IMPORT\_RESPONSE         | created            | created field is missing from CSV import response                          | Field omitted from response               | block\_finalization | Yes                     |
| POST\_UPDATED\_NOT\_NONNEGATIVE\_INTEGER              | updated            | updated value is not an integer greater than or equal to zero              | Wrong type or negative count              | block\_finalization | Yes                     |
| POST\_UPDATED\_MISSING\_FOR\_IMPORT\_RESPONSE         | updated            | updated field is missing from CSV import response                          | Field omitted from response               | block\_finalization | Yes                     |
| POST\_ERRORS\_ITEM\_SCHEMA\_INVALID                   | errors\[]          | One or more errors items do not validate against schema                    | Schema or serialization mismatch          | block\_finalization | Yes                     |
| POST\_ERRORS\_LINE\_NOT\_POSITIVE\_INTEGER            | errors\[].line     | errors\[].line is not an integer greater than or equal to one              | Wrong type or out-of-range value          | block\_finalization | Yes                     |
| POST\_ERRORS\_LINE\_MISSING\_WHEN\_ERRORS\_PRESENT    | errors\[].line     | errors\[].line is missing when errors\[] is present                        | Required field omitted                    | block\_finalization | Yes                     |
| POST\_ERRORS\_MESSAGE\_EMPTY                          | errors\[].message  | errors\[].message is an empty string                                       | Missing human-readable message            | block\_finalization | Yes                     |
| POST\_ERRORS\_MESSAGE\_MISSING\_WHEN\_ERRORS\_PRESENT | errors\[].message  | errors\[].message is missing when errors\[] is present                     | Required field omitted                    | block\_finalization | Yes                     |

| Error Code                                  | Description                                                                 | Likely Cause                                       | Source (Step in Section 2.x)                  | Step ID (from Section 2.2.6)                   | Reachability Rationale                                                        | Flow Impact         | Behavioural AC Required |
| ------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------- | --------------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------------- | ------------------- | ----------------------- |
| RUN\_CREATE\_ENTITY\_DB\_WRITE\_FAILED      | Create operation failed to persist questionnaire/screen/question            | Database write error or constraint violation       | 2.2 – Questionnaire and question management   | STEP-1 Questionnaire and question management   | U1 includes create operations that require durable writes                     | halt\_pipeline      | Yes                     |
| RUN\_UPDATE\_ENTITY\_DB\_WRITE\_FAILED      | Update operation failed to persist changes to questionnaire/screen/question | Database write error or constraint violation       | 2.2 – Questionnaire and question management   | STEP-1 Questionnaire and question management   | U2 includes update operations requiring writes                                | halt\_pipeline      | Yes                     |
| RUN\_DELETE\_ENTITY\_DB\_WRITE\_FAILED      | Delete operation failed for questionnaire/screen/question                   | Database constraint or transaction failure         | 2.2 – Questionnaire and question management   | STEP-1 Questionnaire and question management   | U3 covers delete operations which can fail at runtime                         | halt\_pipeline      | Yes                     |
| RUN\_RETRIEVE\_ENTITY\_DB\_READ\_FAILED     | Retrieval of questionnaire/screen/question failed                           | Database read timeout or connectivity issue        | 2.2 – Questionnaire and question management   | STEP-1 Questionnaire and question management   | U4 requires retrieval that depends on successful reads                        | halt\_pipeline      | Yes                     |
| RUN\_VALIDATION\_ENGINE\_ERROR              | Type-aware response validation crashed unexpectedly                         | Validator misconfiguration or code path error      | 2.2 – Answer kinds and validation             | STEP-2 Answer kinds and validation             | U5 mandates type-aware validation; internal engine can fail                   | block\_finalization | Yes                     |
| RUN\_ANSWER\_KIND\_UNSUPPORTED              | Declared answer\_kind not supported by validation runtime                   | Missing handler for enumerated kind                | 2.2 – Answer kinds and validation             | STEP-2 Answer kinds and validation             | U5 implies mapping from kind→validator; unsupported kind is a runtime failure | block\_finalization | Yes                     |
| RUN\_GATING\_EVALUATION\_ERROR              | Gating evaluation failed to compute completion state                        | Aggregation or rules evaluation error              | 2.2 – Gating check                            | STEP-3 Gating check                            | E5 requires computing ok/blockers; evaluation may fail                        | block\_finalization | Yes                     |
| RUN\_BLOCKING\_ITEMS\_AGGREGATION\_FAILED   | Assembly of blocking items list failed                                      | Join/aggregation over questions and answers failed | 2.2 – Gating check                            | STEP-3 Gating check                            | E5 outputs blockers; building that list is a runtime step                     | block\_finalization | Yes                     |
| RUN\_PREPOPULATION\_LOOKUP\_FAILED          | Pre-population could not retrieve prior answers                             | Lookup or data access failure                      | 2.2 – Pre-population                          | STEP-4 Pre-population                          | U8 requires fetching prior responses; read can fail                           | halt\_pipeline      | Yes                     |
| RUN\_PREPOPULATION\_APPLY\_ERROR            | Pre-population failed to apply prior answers to current view                | Merge/mapping error in application layer           | 2.2 – Pre-population                          | STEP-4 Pre-population                          | U8 implies applying values into current questionnaire                         | block\_finalization | Yes                     |
| RUN\_INGESTION\_INTERFACE\_UNAVAILABLE      | Answer ingestion interface unavailable                                      | Service binding or network failure                 | 2.2 – Interfaces for ingestion and generation | STEP-5 Interfaces for ingestion and generation | U7 exposes stable interfaces; runtime availability can fail                   | halt\_pipeline      | Yes                     |
| RUN\_GENERATION\_GATE\_CALL\_FAILED         | Generation workflow failed to invoke gating check                           | Internal call/contract failure                     | 2.2 – Interfaces for ingestion and generation | STEP-5 Interfaces for ingestion and generation | U7 states generation workflow calls gating                                    | block\_finalization | Yes                     |
| RUN\_ANSWER\_UPSERT\_DB\_WRITE\_FAILED      | Autosave upsert failed to persist answer                                    | Transaction deadlock or write failure              | 2.2 – Autosave per answer                     | STEP-6 Autosave per answer                     | E3+U6 require atomic single-answer upsert                                     | halt\_pipeline      | Yes                     |
| RUN\_IDEMPOTENCY\_STORE\_UNAVAILABLE        | Idempotency state could not be recorded or read                             | Cache/store outage for idempotency keys            | 2.2 – Autosave per answer                     | STEP-6 Autosave per answer                     | Autosave guarantees idempotency; runtime relies on store                      | halt\_pipeline      | Yes                     |
| RUN\_ETAG\_COMPUTE\_FAILED                  | ETag computation failed for returned resource                               | Hashing error or serialization failure             | 2.2 – Autosave per answer                     | STEP-6 Autosave per answer                     | Autosave response includes ETag; computing it can fail                        | block\_finalization | Yes                     |
| RUN\_CONCURRENCY\_TOKEN\_GENERATION\_FAILED | Concurrency token could not be produced for autosave                        | Versioning state not available                     | 2.2 – Autosave per answer                     | STEP-6 Autosave per answer                     | Optimistic concurrency requires token generation                              | block\_finalization | Yes                     |
| RUN\_IMPORT\_STREAM\_READ\_FAILED           | Import failed while reading CSV stream                                      | I/O error or premature stream termination          | 2.2 – Bulk import and export                  | STEP-7 Bulk import and export                  | E6 processes CSV import; streaming read can fail                              | halt\_pipeline      | Yes                     |
| RUN\_IMPORT\_TRANSACTION\_FAILED            | Import transaction failed to commit changes                                 | Constraint violation or deadlock                   | 2.2 – Bulk import and export                  | STEP-7 Bulk import and export                  | U10/E6 imply DB writes during import                                          | halt\_pipeline      | Yes                     |
| RUN\_IMPORT\_OPTIONS\_EXPANSION\_FAILED     | Expansion of options into AnswerOption rows failed                          | Mapping or batch insert failure                    | 2.2 – Bulk import and export                  | STEP-7 Bulk import and export                  | E6 “Mapping” expands options to rows; that step can fail                      | halt\_pipeline      | Yes                     |
| RUN\_EXPORT\_SNAPSHOT\_TXN\_FAILED          | Export snapshot transaction could not be established                        | Database transaction or isolation failure          | 2.2 – Bulk import and export                  | STEP-7 Bulk import and export                  | U9/E7 require read-only repeatable-read transaction                           | halt\_pipeline      | Yes                     |
| RUN\_EXPORT\_STREAM\_WRITE\_FAILED          | Export failed while streaming CSV to client                                 | Streaming/back-pressure or socket error            | 2.2 – Bulk import and export                  | STEP-7 Bulk import and export                  | E7 streams CSV snapshot; stream write can fail                                | halt\_pipeline      | Yes                     |
| RUN\_EXPORT\_ETAG\_COMPUTE\_FAILED          | Export ETag (payload hash) computation failed                               | Hashing over rowset failed                         | 2.2 – Bulk import and export                  | STEP-7 Bulk import and export                  | Export specifies strong ETag over payload                                     | block\_finalization | Yes                     |
| RUN\_EXPORT\_SORT\_EVALUATION\_FAILED       | Export sort evaluation failed for stable ordering                           | Comparator or null-handling error                  | 2.2 – Bulk import and export                  | STEP-7 Bulk import and export                  | U9 requires deterministic ORDER BY; sort computation may fail                 | block\_finalization | Yes                     |
| RUN\_SNAPSHOT\_HASHING\_FAILED              | Snapshot hashing for determinism failed                                     | Hash function or encoding error                    | 2.2 – Goals of reproducibility and iteration  | STEP-8 Goals of reproducibility and iteration  | U11 emphasises reproducibility; hashing supports determinism                  | block\_finalization | Yes                     |
| RUN\_AUTHN\_VERIFICATION\_FAILED            | Authentication verification failed at runtime                               | Invalid/expired token processing failure           | 2.2 – Authentication and security             | STEP-9 Authentication and security             | U12 enforces authentication on operations                                     | halt\_pipeline      | Yes                     |
| RUN\_PROBLEM\_JSON\_ENCODING\_FAILED        | Problem/ValidationProblem serialization failed                              | Problem+json marshalling error                     | 2.2 – Error handling                          | STEP-10 Error handling                         | U13 mandates consistent problem+json responses                                | block\_finalization | Yes                     |
| RUN\_LINKAGE\_RELATION\_ENFORCEMENT\_FAILED | Linking answer to response set/questionnaire failed                         | Foreign-key enforcement or relation lookup failed  | 2.2 – Data model context                      | STEP-11 Data model context                     | S2 requires linking each answer to its response set                           | halt\_pipeline      | Yes                     |

| Error Code                        | Description                                                           | Likely Cause               | Impacted Steps                                         | EARS Refs                                                    | Flow Impact    | Behavioural AC Required |
| --------------------------------- | --------------------------------------------------------------------- | -------------------------- | ------------------------------------------------------ | ------------------------------------------------------------ | -------------- | ----------------------- |
| ENV\_NETWORK\_UNREACHABLE         | Network connectivity required for service dependencies is unavailable | network unreachable        | STEP-1, STEP-3, STEP-4, STEP-6, STEP-7, STEP-11        | U1, U2, U3, U4, E5, S1, U8, E3, U6, U9, U10, E6, E7, O1, S2  | halt\_pipeline | Yes                     |
| ENV\_DNS\_RESOLUTION\_FAILED      | Hostname resolution for dependent services failed                     | dns resolution failure     | STEP-1, STEP-3, STEP-4, STEP-6, STEP-7, STEP-11        | U1, U2, U3, U4, E5, S1, U8, E3, U6, U9, U10, E6, E7, O1, S2  | halt\_pipeline | Yes                     |
| ENV\_TLS\_HANDSHAKE\_FAILED       | TLS/SSL handshake to dependent service could not be established       | invalid certificate        | STEP-1, STEP-3, STEP-4, STEP-6, STEP-7                 | U1, U2, U3, U4, E5, S1, U8, E3, U6, U9, U10, E6, E7          | halt\_pipeline | Yes                     |
| ENV\_RUNTIME\_CONFIG\_MISSING     | Mandatory runtime configuration value is missing                      | unset environment variable | STEP-1, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7, STEP-9 | U1, U2, U3, U4, E5, S1, U8, U7, E3, U6, U9, U10, E6, E7, U12 | halt\_pipeline | Yes                     |
| ENV\_SECRET\_INVALID              | Required secret is invalid or cannot be loaded                        | wrong credential or format | STEP-1, STEP-6, STEP-7, STEP-9                         | U1, U2, U3, U4, E3, U6, U9, U10, E6, E7, U12                 | halt\_pipeline | Yes                     |
| ENV\_DATABASE\_UNAVAILABLE        | Database service is unavailable for reads or writes                   | database offline           | STEP-1, STEP-3, STEP-4, STEP-6, STEP-7, STEP-11        | U1, U2, U3, U4, E5, S1, U8, E3, U6, U9, U10, E6, E7, O1, S2  | halt\_pipeline | Yes                     |
| ENV\_DATABASE\_PERMISSION\_DENIED | Database permission prevents required operation                       | insufficient privileges    | STEP-1, STEP-6, STEP-7, STEP-11                        | U1, U2, U3, U4, E3, U6, U9, U10, E6, E7, S2                  | halt\_pipeline | Yes                     |
| ENV\_CACHE\_UNAVAILABLE           | Idempotency/cache backend is unavailable                              | cache backend offline      | STEP-6                                                 | E3, U6                                                       | halt\_pipeline | Yes                     |
| ENV\_CACHE\_PERMISSION\_DENIED    | Idempotency/cache operation is not permitted                          | access denied to cache     | STEP-6                                                 | E3, U6                                                       | halt\_pipeline | Yes                     |
| ENV\_FILESYSTEM\_READONLY         | Filesystem is read-only where writes are expected                     | readonly mount             | STEP-7                                                 | U9, U10, E6, E7                                              | halt\_pipeline | Yes                     |
| ENV\_DISK\_SPACE\_EXHAUSTED       | Local disk space is exhausted during file operations                  | disk full                  | STEP-7                                                 | U9, U10, E6, E7                                              | halt\_pipeline | Yes                     |
| ENV\_TEMP\_DIR\_UNAVAILABLE       | Temporary directory is unavailable for staging files                  | temp path missing          | STEP-7                                                 | U9, U10, E6, E7                                              | halt\_pipeline | Yes                     |
| ENV\_SYSTEM\_CLOCK\_UNSYNCED      | System clock is not synchronised causing auth timing errors           | clock skew                 | STEP-9                                                 | U12                                                          | halt\_pipeline | Yes                     |

### 6.1 Architectural Acceptance Criteria

**6.1.1 Separation of questionnaire CRUD module**  
The codebase must implement a distinct module responsible for questionnaire, screen, and question CRUD operations, separated from answer upsert and import/export logic.  
*References: STEP-1 Questionnaire and question management; U1, U2, U3, U4*

**6.1.2 Type-aware validation module**  
Validation logic must be encapsulated in a dedicated component that accepts `answer_kind` as a selector and applies type-specific rules.  
*References: STEP-2 Answer kinds and validation; U5*

**6.1.3 Gating check service isolation**  
The gating check (producing `ok` and `blocking_items[]`) must be implemented as a separate callable unit distinct from document generation workflows.  
*References: STEP-3 Gating check; E5; Outputs table: ok, blocking_items[]*

**6.1.4 Pre-population logic segregation**  
Pre-population of answers must be contained in its own module that fetches prior responses without embedding logic into questionnaire CRUD handlers.  
*References: STEP-4 Pre-population; U8*

**6.1.5 Stable interface boundaries**  
External interfaces for ingestion and generation workflows must be encapsulated in designated modules exposing consistent entrypoints.  
*References: STEP-5 Interfaces for ingestion and generation; U7*

**6.1.6 Atomic autosave unit**  
The autosave mechanism must be architecturally implemented as a discrete unit supporting single `(response_set_id, question_id)` upserts.  
*References: STEP-6 Autosave per answer; E3; Outputs table: saved, etag*

**6.1.7 Idempotency key enforcement**  
A structural component must exist that accepts and verifies `Idempotency-Key` headers, with persistence independent of autosave write logic.  
*References: STEP-6 Autosave per answer; E3; Inputs table: Idempotency-Key*

**6.1.8 Concurrency token generation**  
A separate mechanism must produce and attach `ETag` values for concurrency, not hardcoded into business logic.  
*References: STEP-6 Autosave per answer; E3; Outputs table: etag*

**6.1.9 CSV import parser module**  
The CSV import functionality must be implemented in a distinct module that reads UTF-8, RFC4180-compliant files and maps columns to internal entities.  
*References: STEP-7 Bulk import and export; E6; Inputs table: CSVImportFile*

**6.1.10 Options expansion subcomponent**  
Option expansion from CSV `options` column into `AnswerOption` entities must be isolated in a subcomponent of the import module.  
*References: STEP-7 Bulk import and export; E6*

**6.1.11 Import response construction**  
Import responses must be produced through a defined schema with `created`, `updated`, and `errors[]` fields, not via ad hoc payloads.  
*References: STEP-7 Bulk import and export; Outputs table: created, updated, errors[]*

**6.1.12 CSV export builder module**  
CSV export must be implemented as a separate builder that projects questionnaire data into a snapshot, enforcing header row and RFC4180 escaping.  
*References: STEP-7 Bulk import and export; E7; Outputs table: csv_export*

**6.1.13 Export transaction encapsulation**  
The export builder must encapsulate execution within a read-only, repeatable-read transaction.  
*References: STEP-7 Bulk import and export; E7*

**6.1.14 Export ETag computation**  
The export module must include a structural mechanism to compute a strong ETag over the payload.  
*References: STEP-7 Bulk import and export; E7; Outputs table: etag*

**6.1.15 Authentication enforcement layer**  
Authentication (bearer/JWT) must be enforced by a dedicated middleware or gateway component separate from business logic.  
*References: STEP-9 Authentication and security; U12*

**6.1.16 Problem+json error encoder**  
Errors must be serialised through a defined component that emits `application/problem+json` objects with required fields.  
*References: STEP-10 Error handling; U13; Outputs table: Problem, ValidationProblem*

**6.1.17 Deterministic export ordering**  
The export builder must apply stable ordering logic (`screen_key`, `question_order`, `question_id`) to output files.  
*References: STEP-7 Bulk import and export; U9*

**6.1.18 Linkage enforcement module**  
Answers must be linked to their corresponding `response_set_id` and `question_id` by a dedicated relational mapping component.  
*References: STEP-11 Data model context; S2*

**6.1.19 Modular separation for persistence and linkage**  
Persistence of entities (questions, answers, options) must be implemented separately from linkage logic to avoid coupling.  
*References: STEP-11 Data model context; S2; U6*

### 6.2 Happy Path Contractual Acceptance Criteria

**6.2.1.1 Autosave result flag**
*Given* a valid per-answer autosave request with `response_set_id` and `question_id`,
*When* the answer is successfully stored,
*Then* the system must return a `saved` flag set to true.
*Reference: EARS E3; Outputs table: saved*

**6.2.1.2 Concurrency token return**
*Given* a successful autosave or screen retrieval request,
*When* the resource is returned,
*Then* the response must include a non-empty `etag` value.
*Reference: EARS E3; Outputs table: etag*

**6.2.1.3 Gating verdict true**
*Given* all mandatory items are satisfied,
*When* a regenerate-check request is issued,
*Then* the response must return `ok` as true.
*Reference: EARS E5; Outputs table: ok*

**6.2.1.4 Gating verdict false**
*Given* one or more mandatory items are not satisfied,
*When* a regenerate-check request is issued,
*Then* the response must return `ok` as false.
*Reference: EARS E5; Outputs table: ok*

**6.2.1.5 Blocking items presence**
*Given* a regenerate-check request where mandatory items are missing,
*When* the system returns the gating verdict,
*Then* the response must include a non-empty `blocking_items[]` list.
*Reference: EARS E5; Outputs table: blocking\_items\[]*

**6.2.1.6 Blocking items empty**
*Given* a regenerate-check request where all mandatory items are present,
*When* the system returns the gating verdict,
*Then* the response must include an empty `blocking_items[]` list.
*Reference: EARS E5; Outputs table: blocking\_items\[]*

**6.2.1.7 CSV export snapshot**
*Given* a valid questionnaire export request,
*When* the system generates the snapshot,
*Then* the response must include a valid `csv_export` file.
*Reference: EARS E7; Outputs table: csv\_export*

**6.2.1.8 Screen metadata return**
*Given* a valid request for a response set and screen,
*When* the system retrieves the screen,
*Then* the response must include `screen` metadata.
*Reference: EARS U1; Outputs table: screen*

**6.2.1.9 Questions list presence**
*Given* a valid request for a screen with bound questions,
*When* the system returns the screen,
*Then* the response must include a `questions[]` list containing those questions.
*Reference: EARS U2; Outputs table: questions\[]*

**6.2.1.10 Questions list empty**
*Given* a valid request for a screen without bound questions,
*When* the system returns the screen,
*Then* the response must include an empty `questions[]` list.
*Reference: EARS U2; Outputs table: questions\[]*

**6.2.1.11 Screens index return**
*Given* a valid request for questionnaire metadata,
*When* the system returns the metadata,
*Then* the response must include a `screens[]` index.
*Reference: EARS U3; Outputs table: screens\[]*

**6.2.1.12 Created count**
*Given* a successful CSV import,
*When* the response is produced,
*Then* the response must include the `created` count of imported questions.
*Reference: EARS E6; Outputs table: created*

**6.2.1.13 Updated count**
*Given* a successful CSV import,
*When* the response is produced,
*Then* the response must include the `updated` count of questions modified by the import.
*Reference: EARS E6; Outputs table: updated*

**6.2.1.14 Errors list on import**
*Given* a CSV import request that encounters validation issues,
*When* the response is produced,
*Then* the response must include an `errors[]` list of row-level validation errors.
*Reference: EARS E6; Outputs table: errors\[]*

**6.2.1.15 Errors absent on success**
*Given* a CSV import request that completes without validation issues,
*When* the response is produced,
*Then* the response must include an empty `errors[]` list.
*Reference: EARS E6; Outputs table: errors\[]*

**6.2.1.16 Error line number**
*Given* a CSV import request with row-level validation errors,
*When* the system returns the errors,
*Then* each error must include a valid `errors[].line` number.
*Reference: EARS E6; Outputs table: errors\[].line*

**6.2.1.17 Error message**
*Given* a CSV import request with row-level validation errors,
*When* the system returns the errors,
*Then* each error must include a non-empty `errors[].message`.
*Reference: EARS E6; Outputs table: errors\[].message*

### 6.2.2 Sad Path Contractual Acceptance Criteria

**6.2.2.1 Missing required autosave field**
Given a request to autosave an answer,
When the required field `saved` is missing,
Then the system must return error mode `PRE_SAVED_MISSING`.
**Error Mode:** PRE\_SAVED\_MISSING
**Reference:** saved

**6.2.2.2 Invalid autosave field type**
Given a request to autosave an answer,
When the field `saved` is present but not a boolean,
Then the system must return error mode `PRE_SAVED_INVALID_TYPE`.
**Error Mode:** PRE\_SAVED\_INVALID\_TYPE
**Reference:** saved

**6.2.2.3 Missing concurrency token**
Given a request using an entity with an etag,
When the field `etag` is missing,
Then the system must return error mode `PRE_ETAG_MISSING`.
**Error Mode:** PRE\_ETAG\_MISSING
**Reference:** etag

**6.2.2.4 Invalid concurrency token**
Given a request using an entity with an etag,
When the field `etag` value does not match the current resource state,
Then the system must return error mode `PRE_ETAG_MISMATCH`.
**Error Mode:** PRE\_ETAG\_MISMATCH
**Reference:** etag

**6.2.2.5 Gating verdict missing**
Given a regenerate-check request,
When the field `ok` is not present,
Then the system must return error mode `POST_OK_MISSING`.
**Error Mode:** POST\_OK\_MISSING
**Reference:** ok

**6.2.2.6 Blocking items missing**
Given a regenerate-check request,
When the field `blocking_items[]` is omitted while `ok` is false,
Then the system must return error mode `POST_BLOCKING_ITEMS_MISSING`.
**Error Mode:** POST\_BLOCKING\_ITEMS\_MISSING
**Reference:** blocking\_items\[]

**6.2.2.7 Invalid blocking items schema**
Given a regenerate-check request,
When any item in `blocking_items[]` does not validate against schema,
Then the system must return error mode `POST_BLOCKING_ITEMS_INVALID`.
**Error Mode:** POST\_BLOCKING\_ITEMS\_INVALID
**Reference:** blocking\_items\[]

**6.2.2.8 CSV export missing file**
Given a CSV export request,
When the output file `csv_export` is missing,
Then the system must return error mode `POST_CSV_EXPORT_MISSING`.
**Error Mode:** POST\_CSV\_EXPORT\_MISSING
**Reference:** csv\_export

**6.2.2.9 Invalid CSV format**
Given a CSV export request,
When the file `csv_export` is not valid CSV,
Then the system must return error mode `POST_CSV_EXPORT_INVALID_FORMAT`.
**Error Mode:** POST\_CSV\_EXPORT\_INVALID\_FORMAT
**Reference:** csv\_export

**6.2.2.10 Screen metadata missing**
Given a request for screen metadata,
When the object `screen` is not returned,
Then the system must return error mode `POST_SCREEN_MISSING`.
**Error Mode:** POST\_SCREEN\_MISSING
**Reference:** screen

**6.2.2.11 Questions list missing**
Given a request for screen questions,
When the list `questions[]` is omitted,
Then the system must return error mode `POST_QUESTIONS_MISSING`.
**Error Mode:** POST\_QUESTIONS\_MISSING
**Reference:** questions\[]

**6.2.2.12 Screens list missing**
Given a request for questionnaire screens,
When the list `screens[]` is omitted,
Then the system must return error mode `POST_SCREENS_MISSING`.
**Error Mode:** POST\_SCREENS\_MISSING
**Reference:** screens\[]

**6.2.2.13 Created count missing**
Given a CSV import response,
When the field `created` is missing,
Then the system must return error mode `POST_CREATED_MISSING`.
**Error Mode:** POST\_CREATED\_MISSING
**Reference:** created

**6.2.2.14 Created count invalid**
Given a CSV import response,
When the field `created` is not an integer ≥ 0,
Then the system must return error mode `POST_CREATED_INVALID`.
**Error Mode:** POST\_CREATED\_INVALID
**Reference:** created

**6.2.2.15 Updated count missing**
Given a CSV import response,
When the field `updated` is missing,
Then the system must return error mode `POST_UPDATED_MISSING`.
**Error Mode:** POST\_UPDATED\_MISSING
**Reference:** updated

**6.2.2.16 Updated count invalid**
Given a CSV import response,
When the field `updated` is not an integer ≥ 0,
Then the system must return error mode `POST_UPDATED_INVALID`.
**Error Mode:** POST\_UPDATED\_INVALID
**Reference:** updated

**6.2.2.17 Errors list missing**
Given a CSV import response,
When the list `errors[]` is omitted,
Then the system must return error mode `POST_ERRORS_LIST_MISSING`.
**Error Mode:** POST\_ERRORS\_LIST\_MISSING
**Reference:** errors\[]

**6.2.2.18 Error line missing**
Given a CSV import response with errors,
When an item in `errors[]` does not include `line`,
Then the system must return error mode `POST_ERRORS_LINE_MISSING`.
**Error Mode:** POST\_ERRORS\_LINE\_MISSING
**Reference:** errors\[].line

**6.2.2.19 Error message missing**
Given a CSV import response with errors,
When an item in `errors[]` does not include `message`,
Then the system must return error mode `POST_ERRORS_MESSAGE_MISSING`.
**Error Mode:** POST\_ERRORS\_MESSAGE\_MISSING
**Reference:** errors\[].message

### 6.3 Happy Path Behavioural Acceptance Criteria

**6.3.1.1 Transition from initialisation to screen retrieval**
Given the system has completed initialisation,
When the starting conditions for a questionnaire are met,
Then the system must trigger retrieval of the screen metadata step.
**Reference:** E1, S1

**6.3.1.2 Transition from screen retrieval to question binding**
Given the system has retrieved a screen’s metadata,
When the screen definition is available,
Then the system must initiate binding of questions to that screen.
**Reference:** E2, S2

**6.3.1.3 Transition from question binding to answer autosave**
Given questions for a screen are bound,
When a user enters an answer,
Then the system must trigger the autosave step for that answer.
**Reference:** E3, S3

**6.3.1.4 Transition from answer autosave to regenerate-check**
Given an answer has been autosaved,
When gating logic must be evaluated,
Then the system must proceed to the regenerate-check step.
**Reference:** E4, S4

**6.3.1.5 Transition from regenerate-check to export preparation**
Given a regenerate-check verdict is available,
When it allows continuation,
Then the system must trigger preparation of export artefacts.
**Reference:** E5, S5

**6.3.1.6 Transition from export preparation to CSV export**
Given export artefacts are prepared,
When the user requests an export,
Then the system must trigger CSV export.
**Reference:** E6, S6

**6.3.1.7 Transition from CSV export to questionnaire finalisation**
Given a CSV export has been triggered,
When export processing completes successfully,
Then the system must initiate questionnaire finalisation.
**Reference:** E7, S7

### 6.3.2 Sad Path Behavioural Acceptance Criteria

**6.3.2.1 Failure on create entity write**
Given a create request for questionnaire, screen, or question,
When `RUN_CREATE_ENTITY_DB_WRITE_FAILED` occurs,
Then halt the create step and stop propagation to persistence confirmation.
**Error Mode:** RUN\_CREATE\_ENTITY\_DB\_WRITE\_FAILED
**Reference:** STEP-1 Questionnaire and question management

**6.3.2.2 Failure on update entity write**
Given an update request for questionnaire, screen, or question,
When `RUN_UPDATE_ENTITY_DB_WRITE_FAILED` occurs,
Then halt the update step and stop propagation to persistence confirmation.
**Error Mode:** RUN\_UPDATE\_ENTITY\_DB\_WRITE\_FAILED
**Reference:** STEP-1 Questionnaire and question management

**6.3.2.3 Failure on delete entity write**
Given a delete request for questionnaire, screen, or question,
When `RUN_DELETE_ENTITY_DB_WRITE_FAILED` occurs,
Then halt the delete step and stop propagation to entity removal.
**Error Mode:** RUN\_DELETE\_ENTITY\_DB\_WRITE\_FAILED
**Reference:** STEP-1 Questionnaire and question management

**6.3.2.4 Failure on entity retrieval read**
Given a retrieval request for questionnaire, screen, or question,
When `RUN_RETRIEVE_ENTITY_DB_READ_FAILED` occurs,
Then halt the retrieval step and stop propagation to response assembly.
**Error Mode:** RUN\_RETRIEVE\_ENTITY\_DB\_READ\_FAILED
**Reference:** STEP-1 Questionnaire and question management

**6.3.2.5 Failure in validation engine**
Given type-aware validation of an answer is underway,
When `RUN_VALIDATION_ENGINE_ERROR` occurs,
Then halt validation and stop propagation to response acceptance.
**Error Mode:** RUN\_VALIDATION\_ENGINE\_ERROR
**Reference:** STEP-2 Answer kinds and validation

**6.3.2.6 Unsupported answer kind**
Given validation is invoked for a declared answer kind,
When `RUN_ANSWER_KIND_UNSUPPORTED` occurs,
Then halt validation and stop propagation to answer persistence.
**Error Mode:** RUN\_ANSWER\_KIND\_UNSUPPORTED
**Reference:** STEP-2 Answer kinds and validation

**6.3.2.7 Failure in gating evaluation**
Given gating logic is executing,
When `RUN_GATING_EVALUATION_ERROR` occurs,
Then halt the gating step and stop propagation to generation workflow.
**Error Mode:** RUN\_GATING\_EVALUATION\_ERROR
**Reference:** STEP-3 Gating check

**6.3.2.8 Failure in blocking items aggregation**
Given gating evaluation is assembling blocking items,
When `RUN_BLOCKING_ITEMS_AGGREGATION_FAILED` occurs,
Then halt aggregation and stop propagation to gating verdict.
**Error Mode:** RUN\_BLOCKING\_ITEMS\_AGGREGATION\_FAILED
**Reference:** STEP-3 Gating check

**6.3.2.9 Failure in pre-population lookup**
Given pre-population is fetching prior answers,
When `RUN_PREPOPULATION_LOOKUP_FAILED` occurs,
Then halt pre-population and stop propagation to answer application.
**Error Mode:** RUN\_PREPOPULATION\_LOOKUP\_FAILED
**Reference:** STEP-4 Pre-population

**6.3.2.10 Failure in pre-population apply**
Given pre-population is applying prior answers,
When `RUN_PREPOPULATION_APPLY_ERROR` occurs,
Then halt application and stop propagation to screen binding.
**Error Mode:** RUN\_PREPOPULATION\_APPLY\_ERROR
**Reference:** STEP-4 Pre-population

**6.3.2.11 Ingestion interface unavailable**
Given an ingestion request is being processed,
When `RUN_INGESTION_INTERFACE_UNAVAILABLE` occurs,
Then halt ingestion and stop propagation to answer persistence.
**Error Mode:** RUN\_INGESTION\_INTERFACE\_UNAVAILABLE
**Reference:** STEP-5 Interfaces for ingestion and generation

**6.3.2.12 Generation gate call failure**
Given a generation workflow invokes the gating check,
When `RUN_GENERATION_GATE_CALL_FAILED` occurs,
Then halt the generation workflow and stop propagation to document generation.
**Error Mode:** RUN\_GENERATION\_GATE\_CALL\_FAILED
**Reference:** STEP-5 Interfaces for ingestion and generation

**6.3.2.13 Failure in autosave write**
Given autosave is persisting an answer,
When `RUN_ANSWER_UPSERT_DB_WRITE_FAILED` occurs,
Then halt autosave and stop propagation to response confirmation.
**Error Mode:** RUN\_ANSWER\_UPSERT\_DB\_WRITE\_FAILED
**Reference:** STEP-6 Autosave per answer

**6.3.2.14 Idempotency store unavailable**
Given autosave requires idempotency verification,
When `RUN_IDEMPOTENCY_STORE_UNAVAILABLE` occurs,
Then halt autosave and stop propagation to persistence.
**Error Mode:** RUN\_IDEMPOTENCY\_STORE\_UNAVAILABLE
**Reference:** STEP-6 Autosave per answer

**6.3.2.15 Failure in ETag computation**
Given an autosave response is being finalised,
When `RUN_ETAG_COMPUTE_FAILED` occurs,
Then halt response finalisation and stop propagation to response return.
**Error Mode:** RUN\_ETAG\_COMPUTE\_FAILED
**Reference:** STEP-6 Autosave per answer

**6.3.2.16 Concurrency token generation failed**
Given autosave requires concurrency control,
When `RUN_CONCURRENCY_TOKEN_GENERATION_FAILED` occurs,
Then halt autosave and stop propagation to response return.
**Error Mode:** RUN\_CONCURRENCY\_TOKEN\_GENERATION\_FAILED
**Reference:** STEP-6 Autosave per answer

**6.3.2.17 Failure in import stream read**
Given a CSV import is reading a file,
When `RUN_IMPORT_STREAM_READ_FAILED` occurs,
Then halt import and stop propagation to question creation.
**Error Mode:** RUN\_IMPORT\_STREAM\_READ\_FAILED
**Reference:** STEP-7 Bulk import and export

**6.3.2.18 Failure in import transaction**
Given a CSV import transaction is committing,
When `RUN_IMPORT_TRANSACTION_FAILED` occurs,
Then halt import and stop propagation to question updates.
**Error Mode:** RUN\_IMPORT\_TRANSACTION\_FAILED
**Reference:** STEP-7 Bulk import and export

**6.3.2.19 Failure in options expansion**
Given a CSV import expands options,
When `RUN_IMPORT_OPTIONS_EXPANSION_FAILED` occurs,
Then halt expansion and stop propagation to AnswerOption persistence.
**Error Mode:** RUN\_IMPORT\_OPTIONS\_EXPANSION\_FAILED
**Reference:** STEP-7 Bulk import and export

**6.3.2.20 Export snapshot transaction failure**
Given an export requires a snapshot transaction,
When `RUN_EXPORT_SNAPSHOT_TXN_FAILED` occurs,
Then halt export and stop propagation to CSV building.
**Error Mode:** RUN\_EXPORT\_SNAPSHOT\_TXN\_FAILED
**Reference:** STEP-7 Bulk import and export

**6.3.2.21 Failure in export stream write**
Given export is streaming a CSV,
When `RUN_EXPORT_STREAM_WRITE_FAILED` occurs,
Then halt streaming and stop propagation to export finalisation.
**Error Mode:** RUN\_EXPORT\_STREAM\_WRITE\_FAILED
**Reference:** STEP-7 Bulk import and export

**6.3.2.22 Failure in export ETag compute**
Given export requires payload hashing,
When `RUN_EXPORT_ETAG_COMPUTE_FAILED` occurs,
Then halt export and stop propagation to snapshot return.
**Error Mode:** RUN\_EXPORT\_ETAG\_COMPUTE\_FAILED
**Reference:** STEP-7 Bulk import and export

**6.3.2.23 Failure in export sort evaluation**
Given export requires deterministic ordering,
When `RUN_EXPORT_SORT_EVALUATION_FAILED` occurs,
Then halt export and stop propagation to CSV return.
**Error Mode:** RUN\_EXPORT\_SORT\_EVALUATION\_FAILED
**Reference:** STEP-7 Bulk import and export

**6.3.2.24 Snapshot hashing failed**
Given reproducibility requires snapshot hashing,
When `RUN_SNAPSHOT_HASHING_FAILED` occurs,
Then halt reproducibility check and stop propagation to iteration outputs.
**Error Mode:** RUN\_SNAPSHOT\_HASHING\_FAILED
**Reference:** STEP-8 Goals of reproducibility and iteration

**6.3.2.25 Authentication verification failed**
Given an operation requires authentication,
When `RUN_AUTHN_VERIFICATION_FAILED` occurs,
Then halt the operation and stop propagation to business logic execution.
**Error Mode:** RUN\_AUTHN\_VERIFICATION\_FAILED
**Reference:** STEP-9 Authentication and security

**6.3.2.26 Failure in problem+json encoding**
Given an error response must be encoded,
When `RUN_PROBLEM_JSON_ENCODING_FAILED` occurs,
Then halt error encoding and stop propagation to response delivery.
**Error Mode:** RUN\_PROBLEM\_JSON\_ENCODING\_FAILED
**Reference:** STEP-10 Error handling

**6.3.2.27 Linkage enforcement failed**
Given an answer must be linked to a response set and questionnaire,
When `RUN_LINKAGE_RELATION_ENFORCEMENT_FAILED` occurs,
Then halt linkage and stop propagation to response persistence.
**Error Mode:** RUN\_LINKAGE\_RELATION\_ENFORCEMENT\_FAILED
**Reference:** STEP-11 Data model context

### 6.3.2 Sad Path Behavioural Acceptance Criteria – Environmental Errors Only

**6.3.2.28**
**Title:** Halt on network connectivity loss
**Criterion:** Given dependent services require network access, when ENV\_NETWORK\_UNREACHABLE occurs, then halt STEP-1, STEP-3, STEP-4, STEP-6, and STEP-7 and stop propagation to their downstream steps (CRUD completion, gating evaluation, pre-population application, autosave finalisation, export streaming), as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_NETWORK\_UNREACHABLE
**Reference:** Dependency: network; Steps: STEP-1, STEP-3, STEP-4, STEP-6, STEP-7

**6.3.2.29**
**Title:** Halt on DNS resolution failure
**Criterion:** Given dependent services are addressed by hostnames, when ENV\_DNS\_RESOLUTION\_FAILED occurs, then halt STEP-1, STEP-3, STEP-4, STEP-6, and STEP-7 and stop propagation to their downstream steps (CRUD completion, gating evaluation, pre-population application, autosave finalisation, export streaming), as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_DNS\_RESOLUTION\_FAILED
**Reference:** Dependency: DNS; Steps: STEP-1, STEP-3, STEP-4, STEP-6, STEP-7

**6.3.2.30**
**Title:** Halt on TLS handshake failure
**Criterion:** Given dependent calls require TLS, when ENV\_TLS\_HANDSHAKE\_FAILED occurs, then halt STEP-1, STEP-3, STEP-4, STEP-6, and STEP-7 and stop propagation to their downstream steps (CRUD completion, gating evaluation, pre-population application, autosave finalisation, export streaming), as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_TLS\_HANDSHAKE\_FAILED
**Reference:** Dependency: TLS; Steps: STEP-1, STEP-3, STEP-4, STEP-6, STEP-7

**6.3.2.31**
**Title:** Halt on missing runtime configuration
**Criterion:** Given execution requires configured values, when ENV\_RUNTIME\_CONFIG\_MISSING occurs, then halt STEP-1, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7, and STEP-9 and stop propagation to their downstream steps (CRUD completion, gating evaluation, pre-population application, interface invocation, autosave finalisation, export streaming, authentication), as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_RUNTIME\_CONFIG\_MISSING
**Reference:** Dependency: runtime configuration; Steps: STEP-1, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7, STEP-9

**6.3.2.32**
**Title:** Halt on invalid or unavailable secret
**Criterion:** Given secure operations require secrets, when ENV\_SECRET\_INVALID occurs, then halt STEP-1, STEP-6, STEP-7, and STEP-9 and stop propagation to their downstream steps (CRUD completion, autosave finalisation, export streaming, authentication), as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_SECRET\_INVALID
**Reference:** Dependency: secrets; Steps: STEP-1, STEP-6, STEP-7, STEP-9

**6.3.2.33**
**Title:** Halt on database unavailability
**Criterion:** Given persistence and reads require the database, when ENV\_DATABASE\_UNAVAILABLE occurs, then halt STEP-1, STEP-3, STEP-4, STEP-6, STEP-7, and STEP-11 and stop propagation to their downstream steps (CRUD completion, gating evaluation, pre-population application, autosave finalisation, export snapshotting, linkage enforcement), as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_DATABASE\_UNAVAILABLE
**Reference:** Dependency: database; Steps: STEP-1, STEP-3, STEP-4, STEP-6, STEP-7, STEP-11

**6.3.2.34**
**Title:** Halt on database permission denial
**Criterion:** Given operations require authorised DB access, when ENV\_DATABASE\_PERMISSION\_DENIED occurs, then halt STEP-1, STEP-6, STEP-7, and STEP-11 and stop propagation to their downstream steps (CRUD completion, autosave finalisation, export snapshotting, linkage enforcement), as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_DATABASE\_PERMISSION\_DENIED
**Reference:** Dependency: database permissions; Steps: STEP-1, STEP-6, STEP-7, STEP-11

**6.3.2.35**
**Title:** Halt on cache/idempotency store unavailability
**Criterion:** Given autosave requires idempotency checks, when ENV\_CACHE\_UNAVAILABLE occurs, then halt STEP-6 and stop propagation to autosave finalisation, as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_CACHE\_UNAVAILABLE
**Reference:** Dependency: cache/idempotency store; Steps: STEP-6

**6.3.2.36**
**Title:** Halt on cache permission denial
**Criterion:** Given autosave requires idempotency checks, when ENV\_CACHE\_PERMISSION\_DENIED occurs, then halt STEP-6 and stop propagation to autosave finalisation, as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_CACHE\_PERMISSION\_DENIED
**Reference:** Dependency: cache/idempotency store permissions; Steps: STEP-6

**6.3.2.37**
**Title:** Halt on read-only filesystem during export
**Criterion:** Given export requires file operations, when ENV\_FILESYSTEM\_READONLY occurs, then halt STEP-7 and stop propagation to export streaming, as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_FILESYSTEM\_READONLY
**Reference:** Dependency: filesystem (writeability); Steps: STEP-7

**6.3.2.38**
**Title:** Halt on disk space exhaustion during export
**Criterion:** Given export requires local disk space, when ENV\_DISK\_SPACE\_EXHAUSTED occurs, then halt STEP-7 and stop propagation to export streaming, as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_DISK\_SPACE\_EXHAUSTED
**Reference:** Dependency: disk space; Steps: STEP-7

**6.3.2.39**
**Title:** Halt on missing temporary directory during export
**Criterion:** Given export requires a temporary staging area, when ENV\_TEMP\_DIR\_UNAVAILABLE occurs, then halt STEP-7 and stop propagation to export streaming, as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_TEMP\_DIR\_UNAVAILABLE
**Reference:** Dependency: temporary directory; Steps: STEP-7

**6.3.2.40**
**Title:** Halt on unsynchronised system clock for auth
**Criterion:** Given authentication requires correct time, when ENV\_SYSTEM\_CLOCK\_UNSYNCED occurs, then halt STEP-9 and stop propagation to protected operation execution, as required by the error mode’s Flow Impact.
**Error Mode:** ENV\_SYSTEM\_CLOCK\_UNSYNCED
**Reference:** Dependency: system clock/time synchronisation; Steps: STEP-9

7.1.1 – CRUD operations grouped under a distinct surface
Purpose: Verify questionnaire/screen/question CRUD operations are separated from answer upsert and import/export concerns at the API contract boundary.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection; mocking would invalidate structural verification.
Assertions: OpenAPI paths for CRUD (create/update/delete/retrieve of questionnaires, screens, questions) are tagged consistently under a CRUD-specific tag; autosave (`PATCH /response-sets/{response_set_id}/answers/{question_id}`) and import/export (`/questionnaires/import`, `/questionnaires/{id}/export`) use different tags; no CRUD path is co-tagged with autosave or import/export tags.
AC-Ref: 6.1.1

7.1.2 – Dedicated validation component expressed in API schema
Purpose: Ensure validation is encapsulated via `answer_kind`-driven schemas rather than embedded ad hoc in endpoint shapes.
Test Data: Project root; docs/api/openapi.yaml; docs/schemas/AnswerUpsert.schema.json
Mocking: None — static schema inspection.
Assertions: `AnswerUpsert` schema exists and references `answer_kind`-specific rules (enum or discriminator for `short_string|long_text|boolean|number|enum_single`); no endpoint in OpenAPI inlines per-kind constraints instead of referencing the shared schema; schema file exists on disk and validates as JSON.
AC-Ref: 6.1.2

7.1.3 – Gating service boundary present in contract
Purpose: Verify gating is exposed as an isolated callable separate from generation.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: `POST /response-sets/{id}/regenerate-check` exists with its own tag distinct from any generation/export tag; response schema references `ok` and `blocking_items[]` (e.g., `RegenerateCheckResult`) and is not reused by export/generation paths.
AC-Ref: 6.1.3

7.1.4 – Pre-population concerns not fused with CRUD
Purpose: Ensure pre-population is modelled as its own concern and not embedded into CRUD API shapes.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: No CRUD path documents side effects that fetch prior answers; pre-population behaviour is referenced only in screen retrieval (`GET /response-sets/{response_set_id}/screens/{screen_id}`) with a distinct tag from CRUD; no CRUD endpoint description mentions pre-population.
AC-Ref: 6.1.4

7.1.5 – Stable interfaces surfaced with distinct tags
Purpose: Ensure ingestion and generation interfaces are encapsulated behind stable, named entry points.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: OpenAPI defines explicit paths for ingestion/upsert and for gating invocation by generation; both are tagged under interface-specific tags; operationIds are unique and stable (no duplicates).
AC-Ref: 6.1.5

7.1.6 – Atomic autosave unit at API boundary
Purpose: Confirm autosave is a discrete per-answer operation.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: `PATCH /response-sets/{response_set_id}/answers/{question_id}` exists; request body `$ref` is `AnswerUpsert`; no batch path is tagged “autosave”; autosave path requires `Idempotency-Key` and `If-Match`.
AC-Ref: 6.1.6

7.1.7 – Idempotency header enforcement defined centrally
Purpose: Ensure `Idempotency-Key` is specified as a reusable parameter, not inlined.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: `#/components/parameters/IdempotencyKey` exists; autosave operation references this parameter by `$ref`; same parameter is not duplicated inline elsewhere.
AC-Ref: 6.1.7

7.1.8 – Concurrency token (ETag) generation separated from business logic (contract signal)
Purpose: Verify ETag is modelled consistently as a reusable header.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: `#/components/parameters/IfMatch` exists; autosave endpoint declares `If-Match` request header and returns `ETag` response header via reusable components; no endpoint inlines these headers.
AC-Ref: 6.1.8

7.1.9 – CSV import parser contract present
Purpose: Ensure CSV import is defined with RFC4180/UTF-8 contract and mapped columns.
Test Data: Project root; docs/api/openapi.yaml; docs/schemas/CSVImportFile.schema.json
Mocking: None — static contract inspection.
Assertions: `POST /questionnaires/import` exists; request body describes CSV with required columns per spec; CSVImportFile schema file exists and validates; schema mentions `external_qid`, `screen_key`, `question_order`, `question_text`, `answer_kind`, `mandatory`, `placeholder_code`, `options`.
AC-Ref: 6.1.9

7.1.10 – Options expansion subcomponent expressed in schema contract
Purpose: Verify `options` column is treated as a structured mapping input, not free-form.
Test Data: Project root; docs/schemas/CSVImportFile.schema.json
Mocking: None — static schema inspection.
Assertions: The schema defines `options` as a string with documented `value[:label]` and `|` delimiter semantics (via description/format) and not an untyped blob; presence is optional as specified.
AC-Ref: 6.1.10

7.1.11 – Import response schema formalised
Purpose: Ensure import responses use a defined schema with the required fields.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: `#/components/schemas/ImportResult` exists with properties `created`, `updated`, `errors` (array of objects with `line`, `message`); the import operation’s 200/4xx responses `$ref` this schema.
AC-Ref: 6.1.11

7.1.12 – CSV export builder contract separated from question reads
Purpose: Ensure export is a distinct operation producing a CSV snapshot.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: `GET /questionnaires/{id}/export` exists; response content type includes `text/csv; charset=utf-8`; operation is tagged separately from CRUD; operation description mentions streaming.
AC-Ref: 6.1.12

7.1.13 – Export transaction requirement captured in API description
Purpose: Verify the export operation documents snapshot isolation.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: The export operation description explicitly states “read-only, repeatable-read transaction (or equivalent snapshot)”; this text is present in the OpenAPI description for the path/operation.
AC-Ref: 6.1.13

7.1.14 – Strong ETag for export payload
Purpose: Ensure the export defines a strong ETag over the payload.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: The export operation declares an `ETag` response header and description notes computation from payload (e.g., SHA-256 over rowset); header is present in responses.
AC-Ref: 6.1.14

7.1.15 – Authentication middleware boundary expressed in securitySchemes
Purpose: Confirm authentication is enforced centrally, not per-endpoint ad hoc.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: `#/components/securitySchemes/bearerAuth` exists; global `security` or per-operation security references `bearerAuth`; no operation bypasses security unless explicitly documented as public (none expected).
AC-Ref: 6.1.15

7.1.16 – problem+json encoder contract present
Purpose: Ensure error responses are consistently defined via shared schemas.
Test Data: Project root; docs/api/openapi.yaml; docs/schemas/Problem.schema.json; docs/schemas/ValidationProblem.schema.json
Mocking: None — static contract inspection.
Assertions: `#/components/schemas/Problem` and `#/components/schemas/ValidationProblem` exist in OpenAPI or as external `$ref`s; 4xx/5xx responses reference these schemas with `application/problem+json`; schema files exist and validate.
AC-Ref: 6.1.16

7.1.17 – Deterministic export ordering documented
Purpose: Verify stable ordering is part of the export contract.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: Export operation description includes the stable ORDER BY definition (`screen_key NULLS LAST, question_order NULLS LAST, question_id`); this text is present verbatim or equivalently precise.
AC-Ref: 6.1.17

7.1.18 – Linkage enforcement expressed in API view models
Purpose: Ensure answer linkage to `response_set_id` and `question_id` is represented in response models.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: The schema used for screen retrieval (e.g., `QuestionWithAnswer`) includes properties that tie each answer to its `question_id` and the enclosing `response_set_id` context; linkage is not implied only in prose.
AC-Ref: 6.1.18

7.1.19 – Separation of persistence vs linkage responsibilities (contract signal)
Purpose: Verify persistence entities and linkage are modelled via distinct schemas/components.
Test Data: Project root; docs/api/openapi.yaml
Mocking: None — static contract inspection.
Assertions: CRUD entity schemas (questionnaire, screen, question, answer) are defined separately from linkage/view schemas (e.g., `QuestionWithAnswer`, `ScreenView`); no single schema conflates persistence fields with linkage metadata.
AC-Ref: 6.1.19

7.2.1.1
Title: Autosave returns saved=true
Purpose: Verify that a successful per-answer autosave returns `saved: true`.
Test data:

* HTTP: `PATCH /api/v1/response-sets/7b6c8a2e-1b5d-4a8e-9a3b-0f6d9b1f4e21/answers/1f0a2b4c-3d5e-4f6a-8b9c-0d1e2f3a4b5c`
* Headers: `Authorization: Bearer eyJ.fake.jwt`, `Idempotency-Key: 1d5c9c44-7e1c-4a6a-9a1d-6cfe6f9a3b20`, `If-Match: "q-screen-etag-v1"`
* Body: `{ "question_id": "1f0a2b4c-3d5e-4f6a-8b9c-0d1e2f3a4b5c", "value": "Acme Ltd" }`
  Mocking:
* Mock persistence gateway to upsert the answer and return success; assert called once with the exact IDs and value.
* Mock idempotency store to record the key (“not seen” → “seen”); assert single write and no duplicate writes.
  Assertions:
* HTTP 200.
* Response JSON validates against `#/components/schemas/AutosaveResult`; `saved === true`.
* Deep snapshot of other answers for the same `response_set_id` before call equals post-call snapshot (no mutation outside target).
* Invariants (status/capability/metadata): N/A for this API.
  AC-Ref: 6.2.1.1
  EARS-Refs: E3

7.2.1.2
Title: ETag is returned on successful autosave and screen retrieval
Purpose: Verify a non-empty `etag` is returned on success.
Test data:

* Scenario A (autosave): reuse 7.2.1.1 request.
* Scenario B (screen retrieval): `GET /api/v1/response-sets/7b6c8a2e-1b5d-4a8e-9a3b-0f6d9b1f4e21/screens/8aa0b6f6-9c77-4a58-9d2a-7b3f9b8f5d21`
  Mocking:
* For autosave, mock versioning component to return `W/"etag-abc123"`.
* For screen retrieval, mock read model to produce a stable screen snapshot and `ETag: "screen-etag-42"`.
  Assertions:
* Autosave response JSON `etag` is a non-empty string and equals response header `ETag`.
* Screen retrieval response header `ETag` present and non-empty; if body includes `etag`, it equals the header value.
* Schema: autosave body validates `#/components/schemas/AutosaveResult`.
  AC-Ref: 6.2.1.2
  EARS-Refs: E3

7.2.1.3
Title: Regenerate-check returns ok=true when all mandatory items satisfied
Purpose: Confirm gating verdict is true when no blockers remain.
Test data:

* HTTP: `POST /api/v1/response-sets/7b6c8a2e-1b5d-4a8e-9a3b-0f6d9b1f4e21/regenerate-check`
  Mocking:
* Mock gating evaluator to return no blocking items.
  Assertions:
* HTTP 200; body validates `#/components/schemas/RegenerateCheckResult`; `ok === true`.
* `blocking_items` exists and is `[]`.
  AC-Ref: 6.2.1.3
  EARS-Refs: E5

7.2.1.4
Title: Regenerate-check returns ok=false when mandatory items missing
Purpose: Confirm gating verdict is false when at least one mandatory item is missing/invalid.
Test data: same endpoint as 7.2.1.3.
Mocking:

* Gating evaluator returns:

  * `{ "qid": "Q-BUSINESS_NAME", "reason": "missing", "screen_key": "company" }`
  * `{ "qid": "Q-INCORP_DATE", "reason": "invalid_format", "screen_key": "company" }`
    Assertions:
* HTTP 200; body validates `#/components/schemas/RegenerateCheckResult`; `ok === false`.
* `blocking_items.length === 2` and array equals evaluator order.
  AC-Ref: 6.2.1.4
  EARS-Refs: E5

7.2.1.5
Title: Blocking items are present and non-empty when ok=false
Purpose: Ensure `blocking_items[]` is non-empty whenever `ok` is false.
Test data: reuse 7.2.1.4.
Mocking: reuse 7.2.1.4.
Assertions:

* `ok === false`.
* `Array.isArray(blocking_items)` and `blocking_items.length >= 1`.
* Each item validates `#/components/schemas/RegenerateCheckResult/properties/blocking_items/items`.
  AC-Ref: 6.2.1.5
  EARS-Refs: E5

7.2.1.6
Title: Blocking items are empty when ok=true
Purpose: Ensure `blocking_items[]` is empty when no blockers remain.
Test data: reuse 7.2.1.3.
Mocking: gating evaluator returns empty list.
Assertions:

* `ok === true`.
* `blocking_items` is an array of length `0`.
  AC-Ref: 6.2.1.6
  EARS-Refs: E5

7.2.1.7
Title: CSV export returns a valid RFC4180 snapshot
Purpose: Verify export returns a CSV file with correct header and ordering.
Test data:

* HTTP: `GET /api/v1/questionnaires/3c2a1d4e-5678-49ab-9abc-0123456789ab/export`
  Mocking:
* Mock export builder to project three questions (one enum with two options) and to apply stable sort and quoting; return payload and strong ETag.
  Assertions:
* HTTP 200; `Content-Type: text/csv; charset=utf-8`.
* First line exactly: `external_qid,screen_key,question_order,question_text,answer_kind,mandatory,placeholder_code,options`.
* Lines sorted by `screen_key`, then `question_order`, then `question_id`.
* Quotes doubled where needed.
* `ETag` header present and non-empty.
* Treat file as immutable within the test step (buffer equality on repeat read).
  AC-Ref: 6.2.1.7
  EARS-Refs: E7

7.2.1.8
Title: Screen metadata is returned for screen retrieval
Purpose: Confirm `screen` metadata is included in the response.
Test data:

* HTTP: `GET /api/v1/response-sets/7b6c8a2e-1b5d-4a8e-9a3b-0f6d9b1f4e21/screens/8aa0b6f6-9c77-4a58-9d2a-7b3f9b8f5d21`
  Mocking:
* Read model returns screen object `{ "screen_id": "8aa0b6f6-9c77-4a58-9d2a-7b3f9b8f5d21", "title": "Company", "order": 1 }`.
  Assertions:
* Response JSON contains `screen` object validating `#/components/schemas/ScreenView`.
* `screen.screen_id` equals requested ID.
  AC-Ref: 6.2.1.8
  EARS-Refs: U1

7.2.1.9
Title: Questions list present when screen has bound questions
Purpose: Confirm `questions[]` list is included with bound questions.
Test data: reuse request from 7.2.1.8.
Mocking:

* Read model returns two questions bound to the screen and any existing answers.
  Assertions:
* `questions` is an array of length `2`.
* Each item validates `#/components/schemas/QuestionWithAnswer`.
* Deterministic order by `question_order` then `id`.
  AC-Ref: 6.2.1.9
  EARS-Refs: U2

7.2.1.10
Title: Questions list empty when no questions bound
Purpose: Confirm `questions[]` is an empty array if none are bound.
Test data: reuse request from 7.2.1.8 for a screen with no questions.
Mocking:

* Read model returns empty question set for that screen.
  Assertions:
* `questions` exists and `questions.length === 0`.
  AC-Ref: 6.2.1.10
  EARS-Refs: U2

7.2.1.11
Title: Screens index returned for questionnaire metadata
Purpose: Confirm `screens[]` index is included.
Test data:

* HTTP: `GET /api/v1/questionnaires/3c2a1d4e-5678-49ab-9abc-0123456789ab`
  Mocking:
* Read model returns index with three screens: keys `{screen_id, title, order}`.
  Assertions:
* `screens` is an array of length `3`.
* Each item validates `#/components/schemas/ScreenIndexItem`.
* Order deterministic by `order` then `screen_id`.
  AC-Ref: 6.2.1.11
  EARS-Refs: U3

7.2.1.12
Title: Import response includes created count
Purpose: Confirm `created` count appears in import response.
Test data:

* HTTP: `POST /api/v1/questionnaires/import`
* Body: CSV file with 2 new rows and 0 updates.
  Mocking:
* Importer parses CSV, upserts two new questions, expands options, returns counts `{created:2, updated:0, errors:[]}`.
  Assertions:
* Response JSON `created === 2` and validates `#/components/schemas/ImportResult/properties/created`.
* `errors.length === 0`.
  AC-Ref: 6.2.1.12
  EARS-Refs: E6

7.2.1.13
Title: Import response includes updated count
Purpose: Confirm `updated` count appears in import response.
Test data: same endpoint; CSV modifies 3 existing questions, adds none.
Mocking:

* Importer reports `{created:0, updated:3, errors:[]}`.
  Assertions:
* `updated === 3` and validates `#/components/schemas/ImportResult/properties/updated`.
  AC-Ref: 6.2.1.13
  EARS-Refs: E6

7.2.1.14
Title: Import response includes errors\[] for validation issues
Purpose: Confirm row-level errors are listed when present.
Test data: CSV containing a duplicate `external_qid` on line 7.
Mocking:

* Importer detects duplicate key at line 7; returns `{created:0, updated:0, errors:[{line:7, message:"duplicate external_qid"}]}`.
  Assertions:
* `errors` is an array of length `1`.
* `errors[0].line === 7`; `errors[0].message === "duplicate external_qid"`.
* Item validates `#/components/schemas/ImportResult/properties/errors/items`.
  AC-Ref: 6.2.1.14
  EARS-Refs: E6

7.2.1.15
Title: Import response has empty errors\[] on success
Purpose: Confirm `errors[]` is empty when no issues occur.
Test data: CSV with 1 create and 1 update, both valid.
Mocking:

* Importer returns `{created:1, updated:1, errors:[]}`.
  Assertions:
* `errors` exists and `errors.length === 0`.
  AC-Ref: 6.2.1.15
  EARS-Refs: E6

7.2.1.16
Title: Error items include line numbers
Purpose: Confirm each error includes `errors[].line`.
Test data: CSV with two issues at lines 4 and 10.
Mocking:

* Importer returns `errors:[{line:4, message:"missing question_text"},{line:10, message:"invalid answer_kind"}]`.
  Assertions:
* `errors.length === 2`.
* `errors[0].line === 4`, `errors[1].line === 10`; both integers ≥ 1.
  AC-Ref: 6.2.1.16
  EARS-Refs: E6

7.2.1.17
Title: Error items include messages
Purpose: Confirm each error includes non-empty `errors[].message`.
Test data: reuse 7.2.1.16 dataset.
Mocking: reuse 7.2.1.16 importer result.
Assertions:

* `typeof errors[0].message === "string"` and `errors[0].message.length > 0`.
* Same for `errors[1].message`.
  AC-Ref: 6.2.1.17
  EARS-Refs: E6

Notes applicable to all tests:

* Secrets/logging invariants: Not applicable; API responses here do not include secret handling requirements — mark N/A.
* Envelope invariants (status/capability/metadata): Not applicable; there is no global envelope in Section 2 — mark N/A.
* Mocking discipline: Only external boundaries (DB/persistence, idempotency store, gating evaluator, import/export builders) are mocked; internal orchestration is not mocked.

7.2.2.1 Missing required autosave field
**Title:** PATCH autosave returns problem+json when `saved` is missing
**Purpose:** Verify the API surfaces the defined error mode when the `saved` flag is absent in the autosave response contract.
**Test Data:**

* HTTP: `PATCH /api/v1/response-sets/7c3a9d0e-4b55-4b2d-8a7b-2c2f8f8f9a11/answers/1d5c0e77-b96a-4ef3-9f3a-343f5a6d6a10`
* Headers: `Authorization: Bearer <token>`, `Idempotency-Key: 2a6b8c56-6d1a-4c2e-9f0c-8f3e2a1b7d22`, `If-Match: "v9"`
* Body: `{ "value": "Alpha" }`
  **Mocking:**
* Mock the autosave domain service to persist the answer and return an internal DTO omitting `saved` (e.g., `{ "etag": "v10" }`).
* Rationale: The controller/gateway is the unit under test; domain service is an external boundary.
* Assertions on mocks: autosave called once with exact `response_set_id`, `question_id`, and `value`; no retries.
  **Assertions:**
* HTTP status is `500`.
* `Content-Type` is `application/problem+json`.
* Body contains `errors[0].code == "PRE_SAVED_MISSING"` and `errors[0].path == "saved"`.
* `status == 500`, `title` non-empty, `type` present.
  **AC-Ref:** 6.2.2.1
  **Error Mode:** PRE\_SAVED\_MISSING

7.2.2.2 Invalid autosave field type
**Title:** PATCH autosave returns problem+json when `saved` is not boolean
**Purpose:** Confirm the contract error mode when `saved` has wrong type.
**Test Data:** Same endpoint/headers as 7.2.2.1. Body `{ "value": "Beta" }`.
**Mocking:**

* Mock autosave domain service to return `{ "saved": "yes", "etag": "v10" }` (string instead of boolean).
* Assert service called once with exact arguments.
  **Assertions:**
* HTTP 500; `application/problem+json`.
* `errors[0].code == "PRE_SAVED_INVALID_TYPE"`; `errors[0].path == "saved"`.
  **AC-Ref:** 6.2.2.2
  **Error Mode:** PRE\_SAVED\_INVALID\_TYPE

7.2.2.3 Missing concurrency token
**Title:** PATCH autosave returns problem+json when `etag` is missing
**Purpose:** Ensure missing `etag` is surfaced via the specified error mode.
**Test Data:** As 7.2.2.1.
**Mocking:**

* Domain service returns `{ "saved": true }` with no `etag`.
* Assert single call with correct args.
  **Assertions:**
* HTTP 500; problem+json with `errors[0].code == "PRE_ETAG_MISSING"`; `errors[0].path == "etag"`.
  **AC-Ref:** 6.2.2.3
  **Error Mode:** PRE\_ETAG\_MISSING

7.2.2.4 Invalid concurrency token
**Title:** PATCH autosave returns problem+json when `etag` mismatches server version
**Purpose:** Verify the contract error when provided `If-Match` mismatches.
**Test Data:**

* Same endpoint; headers `If-Match: "v8"` (stale).
* Body `{ "value": "Gamma" }`.
  **Mocking:**
* Domain service persists and computes new version `"v10"`; controller detects mismatch vs request precondition and surfaces contract error.
* Assert domain persist called once.
  **Assertions:**
* HTTP 409; problem+json with `errors[0].code == "PRE_ETAG_MISMATCH"`; `errors[0].path == "If-Match"`; `status == 409`.
  **AC-Ref:** 6.2.2.4
  **Error Mode:** PRE\_ETAG\_MISMATCH

7.2.2.5 Gating verdict missing
**Title:** POST regenerate-check returns problem+json when `ok` missing
**Purpose:** Ensure missing `ok` field is treated as contract failure.
**Test Data:** `POST /api/v1/response-sets/7c3a9d0e.../regenerate-check`
**Mocking:**

* Mock gating evaluator to return `{ "blocking_items": [] }` (omit `ok`).
* Assert evaluator called once with `response_set_id`.
  **Assertions:**
* HTTP 500; problem+json has `errors[0].code == "POST_OK_MISSING"`; `errors[0].path == "ok"`.
  **AC-Ref:** 6.2.2.5
  **Error Mode:** POST\_OK\_MISSING

7.2.2.6 Blocking items missing when `ok=false`
**Title:** POST regenerate-check returns problem+json when blockers omitted
**Purpose:** Validate contract when blockers are absent but `ok=false`.
**Test Data:** same endpoint.
**Mocking:** evaluator returns `{ "ok": false }`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_BLOCKING_ITEMS_MISSING"`; `errors[0].path == "blocking_items"`.
  **AC-Ref:** 6.2.2.6
  **Error Mode:** POST\_BLOCKING\_ITEMS\_MISSING

7.2.2.7 Invalid blocker item shape
**Title:** POST regenerate-check returns problem+json when a blocker item is invalid
**Purpose:** Ensure invalid `blocking_items[]` element is surfaced.
**Test Data:** same endpoint.
**Mocking:** evaluator returns `{ "ok": false, "blocking_items": [ { "id_only": "Q-1" } ] }` (missing required fields).
**Assertions:**

* HTTP 500; `errors[0].code == "POST_BLOCKING_ITEMS_INVALID"`; `errors[0].path == "blocking_items[0]"`.
  **AC-Ref:** 6.2.2.7
  **Error Mode:** POST\_BLOCKING\_ITEMS\_INVALID

7.2.2.8 CSV export missing file
**Title:** GET export returns problem+json when `csv_export` missing
**Purpose:** Verify contract error when snapshot file is not present.
**Test Data:** `GET /api/v1/questionnaires/1fa3e0a8-.../export`
**Mocking:**

* Mock export builder to signal success but controller receives `None` for file handle.
* Assert builder invoked once with questionnaire id and repeatable-read flag.
  **Assertions:**
* HTTP 500; `errors[0].code == "POST_CSV_EXPORT_MISSING"`; `errors[0].path == "csv_export"`.
  **AC-Ref:** 6.2.2.8
  **Error Mode:** POST\_CSV\_EXPORT\_MISSING

7.2.2.9 Invalid CSV format
**Title:** GET export returns problem+json for invalid CSV content
**Purpose:** Ensure invalid CSV (e.g., missing header row) is flagged.
**Test Data:** same endpoint.
**Mocking:** builder streams body `b"not,csv\n\"unterminated"` and `Content-Type: application/octet-stream`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_CSV_EXPORT_INVALID_FORMAT"`; `errors[0].path == "csv_export"`; response header `Content-Type` captured for diagnostics.
  **AC-Ref:** 6.2.2.9
  **Error Mode:** POST\_CSV\_EXPORT\_INVALID\_FORMAT

7.2.2.10 Screen metadata missing
**Title:** GET screen view returns problem+json when `screen` object missing
**Purpose:** Confirm omission of `screen` is treated as contract error.
**Test Data:** `GET /api/v1/response-sets/…/screens/…`
**Mocking:** screen view service returns `{ "questions": [] }`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_SCREEN_MISSING"`; `errors[0].path == "screen"`.
  **AC-Ref:** 6.2.2.10
  **Error Mode:** POST\_SCREEN\_MISSING

7.2.2.11 Questions list missing
**Title:** GET screen view returns problem+json when `questions[]` missing
**Purpose:** Ensure missing questions list is surfaced.
**Test Data:** same endpoint.
**Mocking:** service returns `{ "screen": { "id": "c9…"}, "answers": {} }`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_QUESTIONS_MISSING"`; `errors[0].path == "questions"`.
  **AC-Ref:** 6.2.2.11
  **Error Mode:** POST\_QUESTIONS\_MISSING

7.2.2.12 Screens index missing
**Title:** GET questionnaire returns problem+json when `screens[]` missing
**Purpose:** Validate missing `screens[]` index is reported.
**Test Data:** `GET /api/v1/questionnaires/1fa3e0a8-...`
**Mocking:** metadata service returns `{ "questionnaire": {"id":"1fa3e0a8-..."}}`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_SCREENS_MISSING"`; `errors[0].path == "screens"`.
  **AC-Ref:** 6.2.2.12
  **Error Mode:** POST\_SCREENS\_MISSING

7.2.2.13 Created count missing
**Title:** POST import returns problem+json when `created` missing
**Purpose:** Ensure `created` omission is surfaced.
**Test Data:** `POST /api/v1/questionnaires/import` with multipart CSV `text/csv; charset=utf-8`.
**Mocking:** import service returns `{ "updated": 4, "errors": [] }`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_CREATED_MISSING"`; `errors[0].path == "created"`.
  **AC-Ref:** 6.2.2.13
  **Error Mode:** POST\_CREATED\_MISSING

7.2.2.14 Created count invalid
**Title:** POST import returns problem+json when `created` is negative
**Purpose:** Validate numeric domain of `created`.
**Test Data:** same endpoint & CSV.
**Mocking:** import service returns `{ "created": -1, "updated": 2, "errors": [] }`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_CREATED_INVALID"`; `errors[0].path == "created"`; include offending value in `detail`.
  **AC-Ref:** 6.2.2.14
  **Error Mode:** POST\_CREATED\_INVALID

7.2.2.15 Updated count missing
**Title:** POST import returns problem+json when `updated` missing
**Purpose:** Ensure `updated` omission is surfaced.
**Test Data:** same endpoint.
**Mocking:** service returns `{ "created": 3, "errors": [] }`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_UPDATED_MISSING"`; `errors[0].path == "updated"`.
  **AC-Ref:** 6.2.2.15
  **Error Mode:** POST\_UPDATED\_MISSING

7.2.2.16 Updated count invalid
**Title:** POST import returns problem+json when `updated` is not ≥ 0
**Purpose:** Validate numeric domain of `updated`.
**Test Data:** same endpoint.
**Mocking:** service returns `{ "created": 0, "updated": "two", "errors": [] }`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_UPDATED_INVALID"`; `errors[0].path == "updated"`; `detail` mentions expected integer.
  **AC-Ref:** 6.2.2.16
  **Error Mode:** POST\_UPDATED\_INVALID

7.2.2.17 Errors list missing
**Title:** POST import returns problem+json when `errors[]` missing
**Purpose:** Ensure absence of `errors[]` is flagged regardless of whether empty or populated.
**Test Data:** same endpoint.
**Mocking:** service returns `{ "created": 2, "updated": 1 }` (no `errors`).
**Assertions:**

* HTTP 500; `errors[0].code == "POST_ERRORS_LIST_MISSING"`; `errors[0].path == "errors"`.
  **AC-Ref:** 6.2.2.17
  **Error Mode:** POST\_ERRORS\_LIST\_MISSING

7.2.2.18 Error line missing
**Title:** POST import returns problem+json when `errors[].line` missing
**Purpose:** Validate each error item contains a `line` number.
**Test Data:** same endpoint.
**Mocking:** service returns `{ "created": 0, "updated": 0, "errors": [ { "message": "Duplicate external_qid" } ] }`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_ERRORS_LINE_MISSING"`; `errors[0].path == "errors[0].line"`.
  **AC-Ref:** 6.2.2.18
  **Error Mode:** POST\_ERRORS\_LINE\_MISSING

7.2.2.19 Error message missing
**Title:** POST import returns problem+json when `errors[].message` missing
**Purpose:** Validate each error item contains a human-readable message.
**Test Data:** same endpoint.
**Mocking:** service returns `{ "created": 0, "updated": 0, "errors": [ { "line": 12 } ] }`.
**Assertions:**

* HTTP 500; `errors[0].code == "POST_ERRORS_MESSAGE_MISSING"`; `errors[0].path == "errors[0].message"`.
  **AC-Ref:** 6.2.2.19
  **Error Mode:** POST\_ERRORS\_MESSAGE\_MISSING

**7.3.1.1 — Trigger screen retrieval after initialisation**
**Title:** Initialisation transitions to screen retrieval
**Purpose:** Verify that, once initialisation completes, the screen retrieval step is invoked.
**Test Data:** Minimal boot context `{ tenant_id: "t-001", user_id: "u-001" }`.
**Mocking:** Mock external auth/token introspection to return a dummy success sufficient to allow flow; no other mocks.
**Assertions:** Assert invoked once immediately after initialisation completes, and not before.
**AC-Ref:** 6.3.1.1

**7.3.1.2 — Trigger question binding after screen retrieval**
**Title:** Screen retrieval transitions to question binding
**Purpose:** Verify that, after screen metadata is retrieved, the question binding step is invoked.
**Test Data:** Request `{ response_set_id: "rs-001", screen_id: "sc-001" }` with a valid session.
**Mocking:** Mock metadata store read to return a dummy screen record sufficient to allow flow; no question data mocked.
**Assertions:** Assert invoked once immediately after screen retrieval completes, and not before.
**AC-Ref:** 6.3.1.2

**7.3.1.3 — Trigger autosave after question binding**
**Title:** Question binding transitions to per-answer autosave
**Purpose:** Verify that, once questions are bound to the screen, autosave is initiated when an answer is entered.
**Test Data:** `{ response_set_id: "rs-001", question_id: "q-001", value: "Acme Ltd" }`.
**Mocking:** Mock idempotency store to return a dummy success (gets/puts succeed) to allow flow; no business logic mocked.
**Assertions:** Assert invoked once immediately after question binding completes, and not before.
**AC-Ref:** 6.3.1.3

**7.3.1.4 — Trigger regenerate-check after autosave**
**Title:** Autosave transitions to regenerate-check
**Purpose:** Verify that, after a single-answer autosave completes, the regenerate-check step is invoked.
**Test Data:** `{ response_set_id: "rs-001" }` with a recently autosaved `question_id: "q-001"`.
**Mocking:** Mock gating dependencies (e.g., read-only lookup of mandatory set) to return a dummy success sufficient to proceed.
**Assertions:** Assert invoked once immediately after autosave completes, and not before.
**AC-Ref:** 6.3.1.4

**7.3.1.5 — Trigger export preparation after regenerate-check**
**Title:** Regenerate-check transitions to export preparation when continuation allowed
**Purpose:** Verify that, when the regenerate-check allows continuation, the export-preparation step is invoked.
**Test Data:** `{ response_set_id: "rs-001" }` with gating result available in context.
**Mocking:** Mock rules service (if any) to return a dummy “continuation allowed” response sufficient to allow flow.
**Assertions:** Assert invoked once immediately after regenerate-check completes, and not before.
**AC-Ref:** 6.3.1.5

**7.3.1.6 — Trigger CSV export after export preparation**
**Title:** Export preparation transitions to CSV export on user request
**Purpose:** Verify that, after export artefacts are prepared, the CSV export step is invoked upon request.
**Test Data:** `{ questionnaire_id: "qn-001" }` with a “prepare\_export” trigger flag set.
**Mocking:** Mock storage/stream sink to accept a dummy write success sufficient to allow sequencing; do not mock export orchestration.
**Assertions:** Assert invoked once immediately after export preparation completes, and not before.
**AC-Ref:** 6.3.1.6

**7.3.1.7 — Trigger finalisation after CSV export**
**Title:** CSV export transitions to questionnaire finalisation
**Purpose:** Verify that, once CSV export completes successfully, the finalisation step is invoked.
**Test Data:** `{ questionnaire_id: "qn-001", export_request_id: "ex-001" }`.
**Mocking:** Mock downstream notifier (if any) to accept a dummy success to allow flow; streaming sink continues to return success.
**Assertions:** Assert invoked once immediately after CSV export completes, and not before.
**AC-Ref:** 6.3.1.7

**7.3.2.1 – Create entity DB write failure halts downstream management**

**Purpose:** Verify that a create failure in STEP-1 halts STEP-1’s flow and prevents any subsequent management actions.

**Test Data:** `POST /questionnaires` body: `{ "name": "Onboarding v1" }`.

**Mocking:** Mock `QuestionnaireRepository.create(...)` to raise a DB write error mapped to `RUN_CREATE_ENTITY_DB_WRITE_FAILED`. Mock exists only at the persistence boundary; internal orchestration is real. Assert the mock is called once with the provided body.

**Assertions:** Assert error handler is invoked once immediately when **STEP-1: Questionnaire and question management** raises, and not before. Assert **STEP-2: GET /response-sets/{id}/screens/{screen\_id}** is not invoked following the failure. Assert that error mode `RUN_CREATE_ENTITY_DB_WRITE_FAILED` is observed.

**AC-Ref:** 6.3.2.1
**Error Mode:** RUN\_CREATE\_ENTITY\_DB\_WRITE\_FAILED&#x20;

---

**7.3.2.2 – Update entity DB write failure halts downstream management**

**Purpose:** Verify that an update failure in STEP-1 halts STEP-1 and prevents downstream steps.

**Test Data:** `PATCH /questions/{id}` body: `{ "text": "Updated prompt" }`.

**Mocking:** Mock `QuestionRepository.update(...)` to raise mapped error `RUN_UPDATE_ENTITY_DB_WRITE_FAILED`. Assert called once with the question id and patch body.

**Assertions:** Assert error handler is invoked once immediately when **STEP-1** raises, and not before. Assert **STEP-2** is not invoked. Assert error mode `RUN_UPDATE_ENTITY_DB_WRITE_FAILED` is observed.

**AC-Ref:** 6.3.2.2
**Error Mode:** RUN\_UPDATE\_ENTITY\_DB\_WRITE\_FAILED&#x20;

---

**7.3.2.3 – Delete entity DB write failure halts downstream management**

**Purpose:** Verify that a delete failure in STEP-1 halts further flow.

**Test Data:** `DELETE /screens/{id}`.

**Mocking:** Mock `ScreenRepository.delete(...)` to raise `RUN_DELETE_ENTITY_DB_WRITE_FAILED`. Assert called once with the screen id.

**Assertions:** Assert error handler is invoked once immediately when **STEP-1** raises, and not before. Assert **STEP-2** is not invoked. Assert error mode `RUN_DELETE_ENTITY_DB_WRITE_FAILED` is observed.

**AC-Ref:** 6.3.2.3
**Error Mode:** RUN\_DELETE\_ENTITY\_DB\_WRITE\_FAILED&#x20;

---

**7.3.2.4 – Screen query failure prevents screen payload build**

**Purpose:** Verify that a query failure in STEP-2 prevents building the screen payload.

**Test Data:** `GET /response-sets/7b2e.../screens/f3a1...` with valid UUIDs.

**Mocking:** Mock `ScreenViewRepository.fetch(screen_id, response_set_id)` to raise `RUN_SCREEN_QUERY_FAILED`. Assert called with those IDs.

**Assertions:** Assert error handler is invoked once immediately when **STEP-2: GET /response-sets/.../screens** raises, and not before. Assert no rendering/serialization step executes. Assert error mode `RUN_SCREEN_QUERY_FAILED` is observed.

**AC-Ref:** 6.3.2.4
**Error Mode:** RUN\_SCREEN\_QUERY\_FAILED&#x20;

---

**7.3.2.5 – Answers hydration failure prevents screen payload build**

**Purpose:** Verify that failure hydrating existing answers in STEP-2 prevents payload assembly.

**Test Data:** Same GET as above.

**Mocking:** Let `ScreenViewRepository.fetch` succeed; mock `AnswersService.hydrate(response_set_id, question_ids)` to raise `RUN_ANSWERS_HYDRATION_FAILED`. Assert it’s called once.

**Assertions:** Assert error handler is invoked once immediately when **STEP-2** hydration raises, and not before. Assert screen serialization is not invoked. Assert error mode `RUN_ANSWERS_HYDRATION_FAILED` is observed.

**AC-Ref:** 6.3.2.5
**Error Mode:** RUN\_ANSWERS\_HYDRATION\_FAILED&#x20;

---

**7.3.2.6 – Screen payload serialization failure halts STEP-2**

**Purpose:** Verify that serialization failure in STEP-2 stops flow.

**Test Data:** Same GET as above.

**Mocking:** Allow fetch + hydrate to succeed; mock `ScreenPresenter.serialize(view)` to raise `RUN_SCREEN_PAYLOAD_SERIALIZE_FAILED`. Assert called once with the view model.

**Assertions:** Assert error handler is invoked once immediately when **STEP-2** serialization raises, and not before. Assert no ETag computation occurs. Assert error mode `RUN_SCREEN_PAYLOAD_SERIALIZE_FAILED` is observed.

**AC-Ref:** 6.3.2.6
**Error Mode:** RUN\_SCREEN\_PAYLOAD\_SERIALIZE\_FAILED&#x20;

---

**7.3.2.7 – Gating query failure prevents gating verdict**

**Purpose:** Verify that gating data fetch failure in STEP-3 prevents verdict evaluation.

**Test Data:** `POST /response-sets/7b2e.../regenerate-check`.

**Mocking:** Mock `GatingRepository.loadChecklist(response_set_id)` to raise `RUN_GATING_QUERY_FAILED`. Assert called once.

**Assertions:** Assert error handler is invoked once immediately when **STEP-3: Gating check** raises, and not before. Assert blocker aggregation not invoked. Assert error mode `RUN_GATING_QUERY_FAILED` is observed.

**AC-Ref:** 6.3.2.7
**Error Mode:** RUN\_GATING\_QUERY\_FAILED&#x20;

---

**7.3.2.8 – Blocking items aggregation failure blocks finalisation**

**Purpose:** Verify that failure aggregating blockers in STEP-3 prevents downstream generation.

**Test Data:** Same POST as above.

**Mocking:** Let `loadChecklist` succeed; mock `GatingService.aggregateBlockingItems(...)` to raise `RUN_BLOCKING_ITEMS_AGGREGATION_FAILED`. Assert called.

**Assertions:** Assert error handler is invoked once immediately when **STEP-3** aggregation raises, and not before. Assert no verdict emission occurs. Assert error mode `RUN_BLOCKING_ITEMS_AGGREGATION_FAILED` is observed.

**AC-Ref:** 6.3.2.8
**Error Mode:** RUN\_BLOCKING\_ITEMS\_AGGREGATION\_FAILED&#x20;

---

**7.3.2.9 – Pre-population lookup failure halts pre-population**

**Purpose:** Verify that inability to fetch prior answers in STEP-4 halts pre-population.

**Test Data:** `GET /response-sets/7b2e.../screens/f3a1...` with query `prepopulate=true`.

**Mocking:** Mock `PriorAnswersRepository.fetch(company_id, questionnaire_id)` to raise `RUN_PREPOPULATION_LOOKUP_FAILED`. Assert called once.

**Assertions:** Assert error handler is invoked once immediately when **STEP-4: Pre-population** raises, and not before. Assert apply-to-view not invoked. Assert error mode `RUN_PREPOPULATION_LOOKUP_FAILED` is observed.

**AC-Ref:** 6.3.2.9
**Error Mode:** RUN\_PREPOPULATION\_LOOKUP\_FAILED&#x20;

---

**7.3.2.10 – Pre-population apply failure blocks finalisation**

**Purpose:** Verify that merge/apply failure in STEP-4 blocks moving forward.

**Test Data:** Same GET with `prepopulate=true`.

**Mocking:** Mock `PrepopulateService.apply(prior_answers, view)` to raise `RUN_PREPOPULATION_APPLY_ERROR`. Assert called with hydrated data.

**Assertions:** Assert error handler is invoked once immediately when **STEP-4** apply raises, and not before. Assert no screen rendering occurs. Assert error mode `RUN_PREPOPULATION_APPLY_ERROR` is observed.

**AC-Ref:** 6.3.2.10
**Error Mode:** RUN\_PREPOPULATION\_APPLY\_ERROR&#x20;

---

**7.3.2.11 – Ingestion interface unavailable halts ingestion**

**Purpose:** Verify that ingestion interface unavailability in STEP-5 halts ingestion/generation integration.

**Test Data:** Internal call `IngestionInterface.upsertAnswers([...])`.

**Mocking:** Mock interface client construction to raise `RUN_INGESTION_INTERFACE_UNAVAILABLE`. Assert attempted once.

**Assertions:** Assert error handler is invoked once immediately when **STEP-5: Interfaces for ingestion and generation** raises, and not before. Assert no gating call is attempted. Assert error mode `RUN_INGESTION_INTERFACE_UNAVAILABLE` is observed.

**AC-Ref:** 6.3.2.11
**Error Mode:** RUN\_INGESTION\_INTERFACE\_UNAVAILABLE&#x20;

---

**7.3.2.12 – Generation gate call failure blocks finalisation**

**Purpose:** Verify that failure to invoke the gating check from the generation workflow in STEP-5 blocks progress.

**Test Data:** `POST /generation/start` triggers internal `GatingClient.regenerateCheck(...)`.

**Mocking:** Mock `GatingClient.regenerateCheck` to raise `RUN_GENERATION_GATE_CALL_FAILED`. Assert called.

**Assertions:** Assert error handler is invoked once immediately when **STEP-5** gating call raises, and not before. Assert no generation proceeds. Assert error mode `RUN_GENERATION_GATE_CALL_FAILED` is observed.

**AC-Ref:** 6.3.2.12
**Error Mode:** RUN\_GENERATION\_GATE\_CALL\_FAILED&#x20;

---

**7.3.2.13 – Autosave DB write failure halts autosave**

**Purpose:** Verify that an answer upsert write failure in STEP-6 halts autosave.

**Test Data:** `PATCH /response-sets/aa55.../answers/qq99...` with body `{ "value": "Acme Ltd" }` and headers `Idempotency-Key: K1`, `If-Match: "v3"`.

**Mocking:** Mock `AnswerRepository.upsert(...)` to raise `RUN_ANSWER_UPSERT_DB_WRITE_FAILED`. Assert called with `(response_set_id, question_id, value)`.

**Assertions:** Assert error handler is invoked once immediately when **STEP-6: Autosave per answer** raises, and not before. Assert no idempotency/ETag steps run. Assert error mode `RUN_ANSWER_UPSERT_DB_WRITE_FAILED` is observed.

**AC-Ref:** 6.3.2.13
**Error Mode:** RUN\_ANSWER\_UPSERT\_DB\_WRITE\_FAILED&#x20;

---

**7.3.2.14 – Idempotency store unavailable halts autosave**

**Purpose:** Verify that idempotency backend unavailability in STEP-6 halts autosave.

**Test Data:** Same PATCH as above.

**Mocking:** Let `AnswerRepository.upsert` succeed; mock `IdempotencyStore.record(key, fingerprint, result)` to raise `RUN_IDEMPOTENCY_STORE_UNAVAILABLE`. Assert called with `K1`.

**Assertions:** Assert error handler is invoked once immediately when **STEP-6** idempotency persistence raises, and not before. Assert response not returned. Assert error mode `RUN_IDEMPOTENCY_STORE_UNAVAILABLE` is observed.

**AC-Ref:** 6.3.2.14
**Error Mode:** RUN\_IDEMPOTENCY\_STORE\_UNAVAILABLE&#x20;

---

**7.3.2.15 – ETag compute failure blocks finalisation of autosave**

**Purpose:** Verify that failure computing ETag in STEP-6 blocks finalisation.

**Test Data:** Same PATCH as above.

**Mocking:** Mock `Etag.compute(payload)` to raise `RUN_ETAG_COMPUTE_FAILED`. Assert called once with the serialized payload.

**Assertions:** Assert error handler is invoked once immediately when **STEP-6** ETag computation raises, and not before. Assert response not committed. Assert error mode `RUN_ETAG_COMPUTE_FAILED` is observed.

**AC-Ref:** 6.3.2.15
**Error Mode:** RUN\_ETAG\_COMPUTE\_FAILED&#x20;

---

**7.3.2.16 – Concurrency token generation failure blocks autosave**

**Purpose:** Verify that failure generating concurrency/version token in STEP-6 blocks finalisation.

**Test Data:** Same PATCH as above.

**Mocking:** Mock `VersioningToken.issue(question_id, response_set_id)` to raise `RUN_CONCURRENCY_TOKEN_GENERATION_FAILED`. Assert called.

**Assertions:** Assert error handler is invoked once immediately when **STEP-6** token generation raises, and not before. Assert response not sent. Assert error mode `RUN_CONCURRENCY_TOKEN_GENERATION_FAILED` is observed.

**AC-Ref:** 6.3.2.16
**Error Mode:** RUN\_CONCURRENCY\_TOKEN\_GENERATION\_FAILED&#x20;

---

**7.3.2.17 – Import stream read failure halts import**

**Purpose:** Verify that reading the CSV stream failure in STEP-7 halts import.

**Test Data:** `POST /questionnaires/import` with mocked stream “broken pipe”.

**Mocking:** Mock `CsvStream.readChunk()` to raise `RUN_IMPORT_STREAM_READ_FAILED` on first read. Assert called once.

**Assertions:** Assert error handler is invoked once immediately when **STEP-7: Bulk import and export** read raises, and not before. Assert no transaction is started. Assert error mode `RUN_IMPORT_STREAM_READ_FAILED` is observed.

**AC-Ref:** 6.3.2.17
**Error Mode:** RUN\_IMPORT\_STREAM\_READ\_FAILED&#x20;

---

**7.3.2.18 – Import transaction failure halts import**

**Purpose:** Verify that a commit/transaction error in STEP-7 halts import.

**Test Data:** Same POST with minimal valid CSV rows.

**Mocking:** Allow parsing; mock `ImportUnitOfWork.commit()` to raise `RUN_IMPORT_TRANSACTION_FAILED`. Assert called once.

**Assertions:** Assert error handler is invoked once immediately when **STEP-7** transaction commit raises, and not before. Assert no success summary is produced. Assert error mode `RUN_IMPORT_TRANSACTION_FAILED` is observed.

**AC-Ref:** 6.3.2.18
**Error Mode:** RUN\_IMPORT\_TRANSACTION\_FAILED&#x20;

---

**7.3.2.19 – Export snapshot query failure halts export**

**Purpose:** Verify that failure building the export rowset halts STEP-7 export.

**Test Data:** `GET /questionnaires/{id}/export`.

**Mocking:** Mock `ExportRepository.buildRowset(questionnaire_id)` to raise `RUN_EXPORT_SNAPSHOT_QUERY_FAILED`. Assert called with id.

**Assertions:** Assert error handler is invoked once immediately when **STEP-7** query raises, and not before. Assert no streaming begins. Assert error mode `RUN_EXPORT_SNAPSHOT_QUERY_FAILED` is observed.

**AC-Ref:** 6.3.2.19
**Error Mode:** RUN\_EXPORT\_SNAPSHOT\_QUERY\_FAILED&#x20;

---

**7.3.2.20 – Export row projection failure blocks finalisation**

**Purpose:** Verify that projection/formatting errors block STEP-7 export.

**Test Data:** Same GET.

**Mocking:** Let query succeed; mock `ExportProjector.project(row)` to raise `RUN_EXPORT_ROW_PROJECTION_FAILED` for first row. Assert called.

**Assertions:** Assert error handler is invoked once immediately when **STEP-7** projection raises, and not before. Assert no CSV chunk is emitted. Assert error mode `RUN_EXPORT_ROW_PROJECTION_FAILED` is observed.

**AC-Ref:** 6.3.2.20
**Error Mode:** RUN\_EXPORT\_ROW\_PROJECTION\_FAILED&#x20;

---

**7.3.2.21 – Export stream write failure halts export**

**Purpose:** Verify that streaming write failure halts STEP-7.

**Test Data:** Same GET.

**Mocking:** Mock `CsvStream.writeChunk(...)` to raise `RUN_EXPORT_STREAM_WRITE_FAILED` on first write. Assert called once.

**Assertions:** Assert error handler is invoked once immediately when **STEP-7** stream write raises, and not before. Assert stream is closed and no further writes attempted. Assert error mode `RUN_EXPORT_STREAM_WRITE_FAILED` is observed.

**AC-Ref:** 6.3.2.21
**Error Mode:** RUN\_EXPORT\_STREAM\_WRITE\_FAILED&#x20;

---

**7.3.2.22 – Export ETag compute failure blocks finalisation**

**Purpose:** Verify that failure computing ETag for the export payload blocks STEP-7 finalisation.

**Test Data:** Same GET.

**Mocking:** Let projection + streaming buffer accumulate; mock `Etag.compute(export_bytes)` to raise `RUN_EXPORT_ETAG_COMPUTE_FAILED`. Assert called.

**Assertions:** Assert error handler is invoked once immediately when **STEP-7** ETag computation raises, and not before. Assert no `ETag` header is sent. Assert error mode `RUN_EXPORT_ETAG_COMPUTE_FAILED` is observed.

**AC-Ref:** 6.3.2.22
**Error Mode:** RUN\_EXPORT\_ETAG\_COMPUTE\_FAILED&#x20;

---

**7.3.2.23 – Export snapshot transaction failure halts export**

**Purpose:** Verify that snapshot/transaction failure prevents export delivery.

**Test Data:** Same GET.

**Mocking:** Mock `ExportUnitOfWork.beginRepeatableRead()` to raise `RUN_EXPORT_SNAPSHOT_TX_FAILED`. Assert called.

**Assertions:** Assert error handler is invoked once immediately when **STEP-7** snapshot begin raises, and not before. Assert no data is streamed. Assert error mode `RUN_EXPORT_SNAPSHOT_TX_FAILED` is observed.

**AC-Ref:** 6.3.2.23
**Error Mode:** RUN\_EXPORT\_SNAPSHOT\_TX\_FAILED&#x20;

---

**7.3.2.24 – Questionnaire index query failure halts GET /questionnaires/{id}**

**Purpose:** Verify that failure loading screens index prevents returning questionnaire metadata.

**Test Data:** `GET /questionnaires/71f9...`.

**Mocking:** Mock `QuestionnaireRepository.getWithScreens(id)` to raise `RUN_QUESTIONNAIRE_INDEX_QUERY_FAILED`. Assert called.

**Assertions:** Assert error handler is invoked once immediately when **STEP-1** (read path) raises, and not before. Assert no index list is returned. Assert error mode `RUN_QUESTIONNAIRE_INDEX_QUERY_FAILED` is observed.

**AC-Ref:** 6.3.2.24
**Error Mode:** RUN\_QUESTIONNAIRE\_INDEX\_QUERY\_FAILED&#x20;

---

**7.3.2.25 – Screen query failure prevents serialization (dup of 4 at list position)**

**Purpose:** Verify mapping for STEP-2 screen query failure prevents serialization (AC variant).

**Test Data:** Same GET `/response-sets/{id}/screens/{screen_id}`.

**Mocking:** Mock `ScreenViewRepository.fetch(...)` to raise `RUN_SCREEN_QUERY_FAILED`. Assert called with IDs.

**Assertions:** Assert error handler is invoked once immediately when **STEP-2** raises, and not before. Assert serialization not invoked. Assert error mode `RUN_SCREEN_QUERY_FAILED` is observed.

**AC-Ref:** 6.3.2.25
**Error Mode:** RUN\_SCREEN\_QUERY\_FAILED&#x20;

---

**7.3.2.26 – Answers hydration failure prevents serialization (variant)**

**Purpose:** Verify that STEP-2 hydration failure prevents serialization (AC variant).

**Test Data:** Same GET.

**Mocking:** Hydration service raises `RUN_ANSWERS_HYDRATION_FAILED`. Assert called.

**Assertions:** Assert error handler is invoked once immediately when **STEP-2** raises, and not before. Assert serialization not invoked. Assert error mode `RUN_ANSWERS_HYDRATION_FAILED` is observed.

**AC-Ref:** 6.3.2.26
**Error Mode:** RUN\_ANSWERS\_HYDRATION\_FAILED&#x20;

---

**7.3.2.27 – Screen payload serialization failure blocks STEP-2 (variant)**

**Purpose:** Verify that STEP-2 serialization failure blocks finalisation (AC variant).

**Test Data:** Same GET.

**Mocking:** Presenter serializer raises `RUN_SCREEN_PAYLOAD_SERIALIZE_FAILED`. Assert called.

**Assertions:** Assert error handler is invoked once immediately when **STEP-2** raises, and not before. Assert no ETag step is invoked. Assert error mode `RUN_SCREEN_PAYLOAD_SERIALIZE_FAILED` is observed.

**AC-Ref:** 6.3.2.27
**Error Mode:** RUN\_SCREEN\_PAYLOAD\_SERIALIZE\_FAILED&#x20;

**7.3.2.28**
**Title:** Network outage halts CRUD, gating, pre-population, autosave, and export flows
**Purpose:** Verify that loss of network connectivity halts the triggering step and prevents all downstream steps per AC.
**Test Data:** Request `GET /questionnaires/Q-123`; `response_set_id=RS-456`; `screen_id=SCR-001`.
**Mocking:** At the HTTP transport boundary used by STEP-1/STEP-3/STEP-4/STEP-6/STEP-7, configure the client to raise a connection error (`ECONNREFUSED`) on first call. Do not mock internal orchestration. Assert the transport is called exactly once by the failing step and never by downstream steps.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1: Questionnaire & question management** raises due to network outage, and not before. Assert **STEP-3: Gating check**, **STEP-4: Pre-population**, **STEP-6: Autosave (per-answer)**, and **STEP-7: Bulk import/export** are skipped. Assert that error mode **ENV\_NETWORK\_UNREACHABLE** is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
**AC-Ref:** 6.3.2.28
**Error Mode:** ENV\_NETWORK\_UNREACHABLE

**7.3.2.29**
**Title:** DNS resolution failure halts CRUD, gating, pre-population, autosave, and export flows
**Purpose:** Verify that a DNS failure at the triggering step prevents all downstream steps per AC.
**Test Data:** Request `POST /response-sets/RS-456/regenerate-check`.
**Mocking:** At the DNS/HTTP resolver boundary used by STEP-1/3/4/6/7, raise `ENOTFOUND` on first hostname lookup. Assert the resolver is called once by the failing step and never by downstream steps.
**Assertions:** Assert error handler is invoked once immediately when **STEP-3: Gating check** raises due to DNS resolution failure, and not before. Assert **STEP-4**, **STEP-6**, and **STEP-7** are skipped. Assert that error mode **ENV\_DNS\_RESOLUTION\_FAILED** is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
**AC-Ref:** 6.3.2.29
**Error Mode:** ENV\_DNS\_RESOLUTION\_FAILED

**7.3.2.30**
**Title:** TLS handshake failure halts CRUD, gating, pre-population, autosave, and export flows
**Purpose:** Verify that a TLS handshake error halts the triggering step and prevents all downstream steps per AC.
**Test Data:** Request `GET /questionnaires/Q-123/export`.
**Mocking:** At the HTTPS transport boundary used by STEP-1/3/4/6/7, raise a TLS handshake exception on first connect (e.g., `SSLHandshakeError`). Assert the transport is called once by the failing step and never by downstream steps.
**Assertions:** Assert error handler is invoked once immediately when **STEP-7: Bulk import/export** raises due to TLS handshake failure, and not before. Assert no further export streaming is attempted; Assert **STEP-3**, **STEP-4**, and **STEP-6** are not subsequently invoked as a consequence of this request path. Assert that error mode **ENV\_TLS\_HANDSHAKE\_FAILED** is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
**AC-Ref:** 6.3.2.30
**Error Mode:** ENV\_TLS\_HANDSHAKE\_FAILED

**7.3.2.31**
**Title:** Missing runtime configuration halts interface, auth, and data flows
**Purpose:** Verify that absence of required configuration halts the triggering step and prevents all listed downstream steps per AC.
**Test Data:** Invoke an integration call through **STEP-5: Integrations interface** using `POST /response-sets/RS-456/answers:batch`.
**Mocking:** At the config provider boundary, simulate missing keys by raising `ConfigKeyMissing("EXPORT_SNAPSHOT_TXN_TIMEOUT")`. Assert config lookup called exactly once by the failing step; assert no further config or network calls occur.
**Assertions:** Assert error handler is invoked once immediately when **STEP-5: Integrations interface invocation** raises due to missing runtime configuration, and not before. Assert **STEP-1**, **STEP-3**, **STEP-4**, **STEP-6**, **STEP-7**, and **STEP-9** are prevented for this transaction. Assert that error mode **ENV\_RUNTIME\_CONFIG\_MISSING** is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
**AC-Ref:** 6.3.2.31
**Error Mode:** ENV\_RUNTIME\_CONFIG\_MISSING

**7.3.2.32**
**Title:** Invalid or unavailable secret halts secure operations and auth paths
**Purpose:** Verify that an invalid secret halts the triggering step and prevents all listed downstream steps per AC.
**Test Data:** Request `PATCH /response-sets/RS-456/answers/Q-789` with header `Authorization: Bearer sk-invalid`.
**Mocking:** At the secrets manager boundary, return `InvalidSecret("JWT_SIGNING_KEY")`. Assert secret lookup called once by the failing step; assert no token signing or downstream calls occur.
**Assertions:** Assert error handler is invoked once immediately when **STEP-9: Authentication and security** raises due to invalid secret, and not before. Assert **STEP-1**, **STEP-6**, and **STEP-7** are prevented in this request path. Assert that error mode **ENV\_SECRET\_INVALID** is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
**AC-Ref:** 6.3.2.32
**Error Mode:** ENV\_SECRET\_INVALID

**7.3.2.33**
**Title:** Database unavailability halts persistence, reads, linkage, and dependent flows
**Purpose:** Verify that database outage halts the triggering step and prevents all listed downstream steps per AC.
**Test Data:** Request `PATCH /response-sets/RS-456/answers/Q-789` with body `{ "value": true, "question_id": "Q-789" }`.
**Mocking:** At the database client boundary, raise `DBConnectionError("primary")` on first query. Assert DB client called once by the failing step; assert no retries without backoff and no further persistence calls.
**Assertions:** Assert error handler is invoked once immediately when **STEP-6: Autosave (per-answer)** raises due to database unavailability, and not before. Assert **STEP-1**, **STEP-3**, **STEP-4**, **STEP-7**, and **STEP-11** are prevented in this request path. Assert that error mode **ENV\_DATABASE\_UNAVAILABLE** is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
**AC-Ref:** 6.3.2.33
**Error Mode:** ENV\_DATABASE\_UNAVAILABLE

*Note:* Section 6.3.2 of the specification defines environmental behavioural ACs **6.3.2.28–6.3.2.33**. No ACs **6.3.2.34–6.3.2.40** are present in the provided document, so additional tests are not emitted.

**7.3.2.34 — Database permission denied halts CRUD and downstream linkage**

**Title:** STEP-1 database permission error halts STEP-1 and prevents STEP-11
**Purpose:** Verify that a database permission failure at questionnaire CRUD halts STEP-1 and stops propagation to linkage enforcement (STEP-11).
**Test Data:** Minimal create/update request sufficient to invoke STEP-1 (e.g., `questionnaire_id="4f1f3c3e-0b3a-4a4e-9b6c-5a9d2be1b101"`, payload `{ "title": "Tax return 2025" }`).
**Mocking:**

* Mock the **database adapter** used by STEP-1 to raise a permission error on first write (e.g., throws `PermissionDenied`/`AccessDenied`).
* Justification: Database is an external dependency; mocking triggers the environmental failure deterministically.
* Usage assertions: adapter called once with the expected SQL/collection and parameters; no retry attempted by STEP-1.
  **Assertions:**
* Assert error handler is invoked once immediately when **STEP-1** raises due to database permission denial, and not before.
* Assert **STEP-11** and downstream steps are **halted** / **not invoked** as specified in the AC.
* Assert that error mode **ENV\_DATABASE\_PERMISSION\_DENIED** is observed.
* Assert no unintended side-effects (no partial commit, no retry without backoff).
* Assert exactly **one** error telemetry event is emitted for this error mode.
  **AC-Ref:** 6.3.2.34
  **Error Mode:** ENV\_DATABASE\_PERMISSION\_DENIED

---

**7.3.2.35 — Cache backend unavailable halts autosave**

**Title:** STEP-6 cache unavailability halts autosave and prevents completion
**Purpose:** Verify that a cache backend outage during autosave (idempotency/checkpoint) halts STEP-6 and prevents downstream completion.
**Test Data:** Autosave request invoking STEP-6: `response_set_id="6b2f60f8-2a21-4afe-b7a9-6a5f0d1f8e20"`, `question_id="3a6a7b1d-6a9c-4a3f-bc3e-1d2c3e4f5a6b"`, `value="ACME Ltd."`.
**Mocking:**

* Mock the **cache client** (idempotency store) to raise a connection error on first operation (e.g., `BackendUnavailable`).
* Justification: Cache is an external infra service; mocking isolates the boundary.
* Usage assertions: attempted exactly once with expected idempotency key; no fallback to in-memory.
  **Assertions:**
* Assert error handler is invoked once immediately when **STEP-6** raises due to cache unavailability, and not before.
* Assert downstream completion of STEP-6 is **halted** and no further autosave sub-steps run.
* Assert that error mode **ENV\_CACHE\_UNAVAILABLE** is observed.
* Assert no unintended side-effects (no duplicate write attempt, no partial autosave state).
* Assert exactly **one** error telemetry event is emitted.
  **AC-Ref:** 6.3.2.35
  **Error Mode:** ENV\_CACHE\_UNAVAILABLE

---

**7.3.2.36 — Cache permission denied halts autosave**

**Title:** STEP-6 cache permission error halts STEP-6
**Purpose:** Verify that access denied at the cache layer during autosave halts STEP-6 and prevents completion.
**Test Data:** Same autosave invocation as 7.3.2.35 with distinct `Idempotency-Key: "idem-36"` header.
**Mocking:**

* Mock the **cache client** to raise `PermissionDenied` on first write/check.
* Usage assertions: called once with key derived from `Idempotency-Key`; no subsequent cache calls.
  **Assertions:**
* Assert error handler is invoked once immediately when **STEP-6** raises due to cache permission denial, and not before.
* Assert downstream completion of STEP-6 is **halted**.
* Assert that error mode **ENV\_CACHE\_PERMISSION\_DENIED** is observed.
* Assert no unintended side-effects (no fallback to insecure cache, no partial autosave).
* Assert exactly **one** error telemetry event is emitted.
  **AC-Ref:** 6.3.2.36
  **Error Mode:** ENV\_CACHE\_PERMISSION\_DENIED

---

**7.3.2.37 — Read-only filesystem halts export**

**Title:** STEP-7 write to read-only filesystem halts export and prevents streaming
**Purpose:** Verify that attempting to write CSV snapshot to a read-only mount halts STEP-7 and stops propagation to export streaming.
**Test Data:** Export request initiating STEP-7 for `questionnaire_id="1c2d3e4f-1111-2222-3333-444455556666"`.
**Mocking:**

* Mock the **filesystem layer** used by STEP-7 to raise an `OSError`/`EROFS` on first write/open.
* Usage assertions: open called once with expected export path; no retries or alternate path attempted.
  **Assertions:**
* Assert error handler is invoked once immediately when **STEP-7** raises due to read-only filesystem, and not before.
* Assert export streaming and any subsequent STEP-7 sub-steps are **halted** / **not invoked**.
* Assert that error mode **ENV\_FILESYSTEM\_READONLY** is observed.
* Assert no unintended side-effects (no partial files, no temp artefacts).
* Assert exactly **one** error telemetry event is emitted.
  **AC-Ref:** 6.3.2.37
  **Error Mode:** ENV\_FILESYSTEM\_READONLY

---

**7.3.2.38 — Disk space exhausted halts export**

**Title:** STEP-7 disk-full condition halts export and prevents streaming
**Purpose:** Verify that running out of disk space during CSV snapshot write halts STEP-7 and prevents streaming.
**Test Data:** Same export invocation as 7.3.2.37 with larger dataset flag `include_all=true`.
**Mocking:**

* Mock the **filesystem layer** write to raise `OSError`/`ENOSPC` on buffer flush.
* Usage assertions: write attempted once; no further writes after error; no retry without backoff.
  **Assertions:**
* Assert error handler is invoked once immediately when **STEP-7** raises due to disk space exhaustion, and not before.
* Assert export streaming and remaining STEP-7 sub-steps are **halted**.
* Assert that error mode **ENV\_DISK\_SPACE\_EXHAUSTED** is observed.
* Assert no unintended side-effects (no partial/incomplete CSV left behind).
* Assert exactly **one** error telemetry event is emitted.
  **AC-Ref:** 6.3.2.38
  **Error Mode:** ENV\_DISK\_SPACE\_EXHAUSTED

---

**7.3.2.39 — Temp directory unavailable halts export**

**Title:** STEP-7 missing temp directory halts export staging and prevents streaming
**Purpose:** Verify that an unavailable temp directory for staging halts STEP-7 and stops propagation to streaming.
**Test Data:** Export request as in 7.3.2.37 with `staging=true`.
**Mocking:**

* Mock the **filesystem/tempdir provider** to raise `FileNotFoundError` when resolving the temp directory path.
* Usage assertions: tempdir resolution called once; no ad-hoc directory creation attempted.
  **Assertions:**
* Assert error handler is invoked once immediately when **STEP-7** raises due to temp directory unavailability, and not before.
* Assert all STEP-7 staging and streaming sub-steps are **halted**.
* Assert that error mode **ENV\_TEMP\_DIR\_UNAVAILABLE** is observed.
* Assert no unintended side-effects (no orphaned temp files or directories).
* Assert exactly **one** error telemetry event is emitted.
  **AC-Ref:** 6.3.2.39
  **Error Mode:** ENV\_TEMP\_DIR\_UNAVAILABLE

---

**7.3.2.40 — System clock unsynchronised halts authentication**

**Title:** STEP-9 clock skew halts authentication and prevents downstream calls
**Purpose:** Verify that an unsynchronised system clock causes authentication to halt at STEP-9 and prevents invocation of any authenticated downstream steps.
**Test Data:** Authenticated request requiring STEP-9 (e.g., export with `Authorization: Bearer <token>`).
**Mocking:**

* Mock the **time/clock provider** used by STEP-9 to return a skewed time (e.g., +10 minutes) causing token validation failure **due to clock**.
* Usage assertions: clock read occurs once; auth validator invoked once; no retry with adjusted time.
  **Assertions:**
* Assert error handler is invoked once immediately when **STEP-9** raises due to clock synchronisation error, and not before.
* Assert all **authenticated downstream steps** are **halted** / **not invoked** following the failure.
* Assert that error mode **ENV\_SYSTEM\_CLOCK\_UNSYNCED** is observed.
* Assert no unintended side-effects (no partial sessions or secondary auth attempts).
* Assert exactly **one** error telemetry event is emitted.
  **AC-Ref:** 6.3.2.40
  **Error Mode:** ENV\_SYSTEM\_CLOCK\_UNSYNCED
