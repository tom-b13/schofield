# epic name

etag optimistic concurrency control (epic k, phase 0)

# intent

Centralise how etags are enforced and emitted so the front end can read a single, predictable set of headers and stop special‑casing. Phase 0 is non‑destructive: no token value changes, no status‑code changes, no new body fields.

# glossary

- etag: opaque version token for a resource
- if-match: precondition header that must match the current etag to allow a write
- domain header: a resource‑specific etag header alias, e.g. Screen-ETag, Question-ETag, Questionnaire-ETag, Document-ETag

# actors

- end user in the authoring ui (screens/questions)
- end user in the runtime ui (answers/screens)
- http clients consuming document or csv endpoints (downloads)

# guiding principles

- do not change token algorithms or values in phase 0
- enforce preconditions early on routes that already do so today (answers/documents); preserve existing status codes and problem shapes; do not add enforcement to authoring routes in phase 0
- emit domain headers on all in-scope responses; emit ETag alongside the domain header only on routes that already return ETag (runtime/answers/documents). Do not add ETag to authoring routes in phase 0
- keep existing body mirrors as‑is (e.g. screen_view.etag); do not add outputs.etags
- on successful mutation, always echo fresh tags

### Append to guiding principles — Post‑Review Additions (Phase‑0)
- Mount a **central precondition guard** on all in‑scope **write** routes (answers/documents) via dependency injection; **do not** mount on authoring or read (GET) routes.
- Keep handlers **free of inline If‑Match logic**. Parsing/normalisation/comparison and problem responses belong **only** in the guard.
- The guard must be **DB‑free**: do not import or touch repositories/DB drivers (e.g., psycopg2); call only public `app.logic.etag` helpers and import them **inside** guard functions.
- Declare `If-Match` as a **required header parameter** on in‑scope write routes for contract visibility (enforcement remains in the guard).
- UI/event sequencing is **out of scope** for Epic K; no requirements on event order are introduced here.

# contract overview

read responses

- runtime JSON resources (answers/screens/documents): include both ETag and the domain header with the same legacy value
- authoring JSON resources (Epic G): include domain header(s) only (no generic ETag added in phase 0)
- screens continue to include screen_view.etag in the body (unchanged)
- csv or other non‑json downloads: include both ETag and the domain header where feasible; bodies are unchanged

write requests (patch/post/delete)

- if-match is normalised and checked before mutation
- on mismatch, return the route’s existing status code and problem shape (unchanged)
- on success, return domain header(s) with the fresh legacy value. Also return ETag where the route already returns it today (runtime/answers/documents). Do not add generic ETag to authoring routes in phase 0; bodies remain unchanged except where they already include an etag field

### Append to contract overview — Post‑Review Additions (Phase‑0)
- **Problem+json mapping (unchanged shapes):**
  - Missing `If-Match` → **428 Precondition Required**, `code=PRE_IF_MATCH_MISSING`.
  - Mismatched `If-Match` → existing route status (**409** or **412**) with `code=PRE_IF_MATCH_ETAG_MISMATCH`.
- On **document reorder** precondition failures, emit diagnostic headers **`X-List-ETag`** and, when applicable, **`X-If-Match-Normalized`** alongside the problem body.

# per‑resource behaviour

screens

- get: set Screen-ETag and ETag to the same legacy value; ensure screen_view.etag remains populated
- patch/post/delete: enforce if-match early; keep current conflict status; on success, set both headers with the fresh value
- authoring screen routes (Epic G): domain headers only; do not introduce generic ETag in phase 0

answers

- patch/post/delete: enforce if-match early; return 409 on mismatch and 428 when missing If-Match; on success, set Screen-ETag and ETag with the fresh value

questions

- phase 0: no change (headers as currently emitted); the front end reads `Question-ETag` if present, else `ETag`

documents

- get and any write endpoints that already exist: keep current behaviour and status codes; additionally emit Document-ETag alongside ETag; no body mirror added
- preserve diagnostic headers already emitted by reorder (e.g., X-List-ETag and X-If-Match-Normalized) during Phase 0

questionnaires (csv export)

- get csv: keep legacy ETag behaviour; additionally emit Questionnaire-ETag with the same legacy value
- header names are case-insensitive; some clients (e.g., fetch) lowercase to `questionnaire-etag`

placeholders

- post /placeholders/bind and /placeholders/unbind: preserve current 412 behaviour on mismatch and include ETag header in the response as today; no additional domain headers in phase 0
- get /questions/{id}/placeholders: preserve existing body "etag" field and set ETag header to the same value

response sets

- no change in phase 0

### Append to per‑resource behaviour — Post‑Review Additions (Phase‑0)
- **Guard scope**: apply guard to **answers** and **documents** writes only; **exclude** authoring and all **GET** endpoints.
- **Documents reorder failures**: must include **`X-List-ETag`** and **`X-If-Match-Normalized`** where normalisation occurred.

# request handling pipeline (phase 0)

1. normalise if-match

   - preserve "*" semantics: treat "*" as unconditional write (resource-exists precondition) where routes already accept it; do not change route status codes.
   - support comma-separated lists: split on commas outside quotes; match succeeds if ANY tag matches the current token.
   - accept weak/strong forms: treat W/"abc" and "abc" as equivalent in phase 0.
   - quote handling: strip surrounding quotes, unescape " inside, and trim whitespace.
   - case handling: compare token bytes case-sensitively; ignore case only for the W/ prefix.
   - multiple headers: join multiple If-Match header instances with "," before parsing.
   - empty/invalid tokens: ignore invalid entries; if nothing valid remains, treat as mismatch (preserve each route’s existing status on mismatch).
   - parity basis: compare against the current legacy token normalised with the same rules; do not alter the stored/emitted value.
   - note: comma-separated If-Match support is provided by the normaliser for forward-compatibility; current endpoints do not require it.

2. precondition enforcement

   - perform the check before mutation
   - on mismatch: return the existing status code and problem body used by the route

3. mutation and tag retrieval

   - perform the mutation as today
   - retrieve the current legacy tag value using the existing algorithm

4. header emission

   - set ETag to the legacy value
   - set the domain header (Screen-ETag, Question-ETag, Questionnaire-ETag, Document-ETag) to the same value (placeholders: ETag only in phase 0)

5. body mirrors

   - do not add new mirrors; continue to include screen_view.etag where it already exists

### Append to request handling pipeline — Post‑Review Additions (Phase‑0)
- **Guard placement**: steps **1–2** execute inside `precondition_guard`; handlers must enter at step **3** only after guard success.
- **DB isolation**: the guard must not import DB drivers or repositories; it must rely solely on public ETag helpers, imported **inside** the guard function scope.
- **Diagnostics on failure** (documents reorder): on step **2** failure, emit **`X-List-ETag`** and optional **`X-If-Match-Normalized`**.

# caching and conditional gets

- no behavioural change mandated in phase 0
- endpoints may accept If-None-Match as they do today; validators and 304s remain as currently implemented

# logging and observability

- log an etag.enforce event when preconditions are checked, including route name and a redacted indicator of match/mismatch (not the raw token); log only `matched: true|false` and a route id; never log token substrings
- log an etag.emit event when headers are written, including route name and domain header used

### Append to logging and observability — Post‑Review Additions (Phase‑0)
- Emit minimal telemetry for guard outcomes: `etag.enforce` (pre‑mutation), `etag.emit` (post‑success headers). No UI/event sequencing logs are required by this epic.

# openapi updates (non‑breaking)

- annotate affected endpoints to declare the additional domain headers in 2xx and error responses where applicable
- ensure `Access-Control-Expose-Headers` exposes the added domain headers (Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag)
- bodies remain unchanged

### Append to openapi updates — Post‑Review Additions (Phase‑0)
- Declare `If-Match` as a **required header parameter** on in‑scope write routes (visibility only; enforcement remains in the guard).
- Document error responses for **428** and **409/412** with invariant problem shapes and codes (`PRE_IF_MATCH_MISSING`, `PRE_IF_MATCH_ETAG_MISMATCH`).

# compatibility constraints

- legacy token values must not change in phase 0
  - tests: capture a baseline tag from the current build; after refactor, the same request must return **exactly the same** header token string (including `W/` prefix and quotes). No whitespace/quoting/strength changes.
- existing status codes and problem bodies must not change (e.g., answers: 409 on mismatch; 428 when missing; documents: 412 on mismatch)
  - tests: trigger each route’s mismatch/missing-precondition and assert the same status. Assert problem JSON has identical keys/shape and invariant error codes/messages; no additional/renamed fields.
- authoring routes must not add If-Match enforcement in phase 0; keep current success flows (tests assume success without precondition checks)
  - tests: authoring writes should succeed without asserting If-Match; adding enforcement would fail existing features.
- no new body fields are introduced; preserve existing body mirrors (e.g., `screen_view.etag`, placeholders `etag`)
  - tests: assert `outputs.etags` is **absent**. For screens, assert `screen_view.etag` exists and equals the domain header value. For placeholders, assert body `etag` exists and equals response `ETag`.
- csv and other binary formats remain unchanged aside from additional response headers
  - tests: assert `Content-Type` unchanged; payload bytes equal baseline (or checksum match). Assert presence of `Questionnaire-ETag` and/or `ETag`; no wrapper/format changes.
- preserve existing diagnostic headers on document reorder (X-List-ETag, X-If-Match-Normalized)
  - tests: assert both headers are present and non-empty; values follow the same legacy format/rules as before; no rename or removal.

### Append to compatibility constraints — Post‑Review Additions (Phase‑0)
- **Handler isolation**: confirm handlers contain **no** If‑Match parsing/validation or precondition problem construction.
- **Guard isolation**: confirm guard contains **no** imports of private ETag internals and **no** DB/repository imports at module scope; any allowed helper imports occur inside the guard function.
- **CORS**: confirm `Access-Control-Expose-Headers` includes all domain headers in both success and error responses for in‑scope routes.

1. Scope
1.1 Purpose

Establish a uniform, non-destructive ETag contract so clients can rely on consistent request preconditions and response headers across resources, reducing UI complexity and test flakiness in Phase 0.

1.2 Inclusions

Centralised normalisation of If-Match for routes that already enforce preconditions (answers, documents).

Consistent header exposure: emit domain ETag headers (Screen-/Question-/Questionnaire-/Document-ETag) on in-scope responses; also emit generic ETag only where it exists today (runtime/answers/documents).

Preserve existing body mirrors where present (e.g., screen_view.etag); ensure successful writes echo fresh tags in headers.

Per resource behaviour: runtime JSON returns domain header + ETag; authoring JSON returns domain header only; CSV/binary returns domain header (and existing ETag) without changing payloads.

Non-breaking documentation/ops updates: declare headers in OpenAPI and expose them via CORS so browsers can read them.

Lightweight observability: log precondition checks and header emission events (redacted).

1.3 Exclusions

No changes to token algorithms/values, response bodies, or status codes/problem shapes.

No new body fields (e.g., no outputs.etags) and no database/schema changes.

No addition of If-Match enforcement to authoring routes in Phase 0.

No caching/idempotency redesign or front-end UI rewrites.

1.4 Context

This story is part of Epic K (Phase 0) and underpins Epic H’s frontend shim by providing a stable concurrency and header contract. It aligns with Epic G authoring flows without altering their success paths. The work touches server HTTP interfaces only, interacting with existing REST endpoints and standard HTTP semantics (ETag/If-Match) plus CORS for header exposure.

# 2.2. EARS Functionality

## 2.2.1 Ubiquitous requirements

* **U1** The system will join multiple If-Match header instances into a single comma-separated string prior to parsing.
* **U2** The system will trim whitespace around each If-Match token during normalisation.
* **U3** The system will strip surrounding quotes from each If-Match token during normalisation.
* **U4** The system will unescape internal quotes within each If-Match token during normalisation.
* **U5** The system will treat the W/ prefix case-insensitively during token normalisation.
* **U6** The system will consider weak and strong forms of an identical token equivalent during comparison.
* **U7** The system will support comma-separated If-Match token lists such that a match succeeds when any token equals the current tag.
* **U8** The system will preserve legacy ETag token values in all responses during Phase 0.
* **U9** The system will include a domain ETag header for the resource scope in all in-scope responses.
* **U10** The system will include the generic ETag header only on routes that already emit it today.
* **U11** The system will echo the fresh tag value in response headers after a successful mutation.
* **U12** The system will retain existing body ETag mirrors unchanged where they are present.
* **U13** The system will expose domain ETag headers to browsers via CORS Access-Control-Expose-Headers.
* **U14** The system will record an etag.enforce log event for each precondition check including only a match result indicator.
* **U15** The system will record an etag.emit log event for each response where ETag headers are set.
* **U16** The system will associate each emitted domain ETag header with its corresponding resource scope.
* **U17** The system will retrieve the current legacy tag value after mutation using the existing algorithm.
* **U18** The system will evaluate If-Match preconditions exclusively within a precondition guard before handler execution.
* **U19** The system will evaluate preconditions without accessing repositories or database drivers during guard execution.
* **U20** The system will declare If-Match as a required header parameter on in-scope write routes for interface visibility.

## 2.2.2 Event-driven requirements

* **E1** When a write request with If-Match is received on answers routes, the system will check the precondition before performing any mutation.
* **E2** When a write request with If-Match is received on document routes, the system will check the precondition before performing any mutation.
* **E3** When a write operation completes successfully, the system will emit updated domain ETag header(s) in the response.
* **E4** When a runtime JSON GET is processed, the system will include both the domain ETag header and the generic ETag header with the same value.
* **E5** When an authoring JSON GET is processed, the system will include domain ETag header(s) only.
* **E6** When exporting questionnaire CSV, the system will include Questionnaire-ETag in the response without changing the payload.
* **E7** When returning a screen GET, the system will include screen_view.etag in the body.
* **E8** When If-Match is missing on an in-scope write route, the system will return 428 Precondition Required with problem code PRE_IF_MATCH_MISSING.
* **E9** When If-Match does not match on an in-scope write route, the system will return the route’s existing conflict status (409 or 412) with problem code PRE_IF_MATCH_ETAG_MISMATCH.

## 2.2.3 State-driven requirements

* **S1** While authoring routes are in Phase 0, the system will not enforce If-Match preconditions.
* **S2** While processing placeholders endpoints in Phase 0, the system will emit only the generic ETag header in responses.
* **S3** While If-None-Match validators are supported on an endpoint, the system will maintain the current 304 behaviour unchanged.
* **S4** While processing read (GET) endpoints, the system will bypass the precondition guard.

## 2.2.4 Optional-feature requirements

* **O1** Where wildcard If-Match "*" is accepted by a route, the system will treat it as a resource-exists precondition.
* **O2** Where multiple resource scopes are affected by a mutation, the system will emit domain ETag headers for each affected scope present in the response.
* **O3** Where both a domain ETag header and a body mirror are present for screens, the system will treat the header value as authoritative.
* **O4** Where document reorder diagnostics are supported, the system will include existing diagnostic headers unchanged in corresponding responses.
* **O5** Where token normalisation occurs on document reorder failures, the system will include X-If-Match-Normalized alongside diagnostic headers.

## 2.2.5 Unwanted-behaviour requirements

* **N1** If all provided If-Match tokens are invalid after normalisation, the system will treat the request as a precondition mismatch.
* **N2** If a non-matching If-Match token is supplied on answers routes, the system will respond 409 without mutating state.
* **N3** If a non-matching If-Match token is supplied on document routes, the system will respond 412 without mutating state.
* **N4** If If-Match is missing on answers routes, the system will respond 428 without mutating state.
* **N5** If both a domain ETag header and a generic ETag header are present and differ, the system will prefer the domain header value when exposing tags.
* **N6** If header and body ETag values for a screen differ, the system will prefer the header value without failing the request.
* **N7** If a document reorder precondition fails, the system will include X-List-ETag and X-If-Match-Normalized in the response.
* **N8** If If-Match is missing on document write routes, the system will respond 428 without mutating state.
* **N9** If a precondition failure response is returned, the system will include a stable problem code of PRE_IF_MATCH_MISSING or PRE_IF_MATCH_ETAG_MISMATCH.

## 2.2.6 Step Index

* **STEP-1** normalise if-match → U1, U2, U3, U4, U5, U6, U7, O1, N1
* **STEP-2** precondition enforcement (guard) → U18, U19, E1, E2, U14, E8, E9, N2, N3, N4, N8, O5, N7, N9
* **STEP-3** mutation and tag retrieval → U17, U8
* **STEP-4** header emission → U9, U10, U11, U13, U15, U16, E3, E4, E5, E6
* **STEP-5** body mirrors → U12, E7, O3, N6

| Field                               | Description                                                                               | Type   | Schema / Reference                                        | Notes                                                                      | Pre-Conditions                                                                                                                                                                                                       | Origin   |
| ----------------------------------- | ----------------------------------------------------------------------------------------- | ------ | --------------------------------------------------------- | -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| request.headers.If-Match            | Precondition header carrying one or more ETag tokens for optimistic concurrency on writes | string | schemas/IfMatchHeader.schema.json                         | Provisional schema for header syntax and examples                          | Header is required and must be provided for guarded routes; Value must be a non-empty string; Value must parse as one or more tokens per normaliser rules; Multiple header instances are concatenated before parsing | provided |
| request.path.response_set_id        | Identifier of the active response set used to scope screen/answer operations              | string | schemas/ResponseSetId.schema.json                         | None                                                                       | Field is required and must be provided; Value must conform to the referenced schema; Value must be a non-empty string                                                                                                | provided |
| request.path.screen_key             | Stable screen slug used in REST paths to address a screen                                 | string | schemas/ScreenKey.schema.json                             | Provisional schema to reflect slug form distinct from ScreenId             | Field is required and must be provided; Value must match the allowed slug pattern; Value must be a non-empty string                                                                                                  | provided |
| request.path.question_id            | Identifier of a question targeted by an operation                                         | string | schemas/QuestionId.schema.json                            | None                                                                       | Field is required and must be provided; Value must conform to the referenced schema; Value must be a non-empty string                                                                                                | provided |
| request.path.document_id            | Identifier of a document targeted by an operation                                         | string | schemas/DocumentId.schema.json                            | None                                                                       | Field is required and must be provided; Value must conform to the referenced schema; Value must be a non-empty string                                                                                                | provided |
| request.path.questionnaire_id       | Identifier of a questionnaire targeted by an operation (including CSV export)             | string | schemas/QuestionnaireId.schema.json                       | None                                                                       | Field is required and must be provided; Value must conform to the referenced schema; Value must be a non-empty string                                                                                                | provided |
| acquired.current_etag.screen        | Current legacy ETag token for the addressed screen                                        | string | schemas/EtagToken.schema.json                             | Provisional schema for opaque token string                                 | Token must be retrievable for the addressed screen; Token must be a string; Token must represent the current persisted version                                                                                       | acquired |
| acquired.current_etag.document      | Current legacy ETag token for the addressed document                                      | string | schemas/EtagToken.schema.json                             | Provisional schema for opaque token string                                 | Token must be retrievable for the addressed document; Token must be a string; Token must represent the current persisted version                                                                                     | acquired |
| acquired.current_etag.questionnaire | Current legacy ETag token for the addressed questionnaire                                 | string | schemas/EtagToken.schema.json                             | Provisional schema for opaque token string                                 | Token must be retrievable for the addressed questionnaire; Token must be a string; Token must represent the current persisted version                                                                                | acquired |
| returned.screen_view.etag           | Body mirror of the active screen’s token used for parity verification                     | string | schemas/ScreenView.schema.json#/properties/etag           | Provider: GET /api/v1/response-sets/{response_set_id}/screens/{screen_key} | Call must complete without error; Return value must match the declared schema; Returned etag must be treated as advisory for parity checks only                                                                      | returned |
| returned.placeholders_response.etag | Collection-level token for question placeholders used for parity verification             | string | schemas/PlaceholdersResponse.schema.json#/properties/etag | Provider: GET /api/v1/questions/{id}/placeholders                          | Call must complete without error; Return value must match the declared schema; Returned etag must be treated as advisory for parity checks only                                                                      | returned |

| Field                                 | Description                                                                          | Type                   | Schema / Reference                                                                   | Notes                                                                                                 | Post-Conditions                                                                                                                                                                                                                            |
| ------------------------------------- | ------------------------------------------------------------------------------------ | ---------------------- | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| outputs                               | Canonical container for all fields returned, persisted, or displayed by this feature | object                 | schemas/Outputs.schema.json                                                          | Single source of truth for Phase-0 ETag contract outputs                                              | Object validates against the referenced schema; Object contains keys `headers` and `body`; Object is immutable within this step after emission; Key set is deterministic for identical inputs                                              |
| outputs.headers                       | HTTP response headers carrying ETag information and diagnostics                      | mapping[string→string] | schemas/Outputs.schema.json#/properties/headers                                      | Includes domain headers and legacy `ETag`; diagnostic headers appear on specific error responses only | Mapping validates against the referenced fragment; Keys are case-insensitive by protocol but represented once each here; Mapping may be empty on routes out of scope; Mapping order is not significant                                     |
| outputs.headers.ETag                  | Legacy ETag header value mirrored for applicable routes                              | string                 | schemas/Outputs.schema.json#/properties/headers/properties/ETag                      | Present on runtime reads and on routes that already emitted `ETag` prior to Phase-0                   | Field is required on in-scope success responses that historically emitted `ETag`; Value validates against schemas/EtagToken.schema.json; Value equals the current legacy token string for the addressed resource                           |
| outputs.headers.Screen-ETag           | Domain header for the screen scope                                                   | string                 | schemas/Outputs.schema.json#/properties/headers/properties/Screen-ETag               | Present on screen GET and on successful screen/answer mutations                                       | Field is required on screen-scope responses; Value validates against schemas/EtagToken.schema.json; Value equals the current legacy token string for the screen                                                                            |
| outputs.headers.Question-ETag         | Domain header for the question scope                                                 | string                 | schemas/Outputs.schema.json#/properties/headers/properties/Question-ETag             | Present on authoring question routes that already emit it                                             | Field is required on question-scope responses that historically emitted it; Value validates against schemas/EtagToken.schema.json; Value equals the current legacy token string for the question                                           |
| outputs.headers.Questionnaire-ETag    | Domain header for the questionnaire scope                                            | string                 | schemas/Outputs.schema.json#/properties/headers/properties/Questionnaire-ETag        | Present on questionnaire CSV export and other questionnaire-scope endpoints as applicable             | Field is required on questionnaire-scope responses; Value validates against schemas/EtagToken.schema.json; Value equals the current legacy token string for the questionnaire                                                              |
| outputs.headers.Document-ETag         | Domain header for the document scope                                                 | string                 | schemas/Outputs.schema.json#/properties/headers/properties/Document-ETag             | Present on document GET and on successful document writes where applicable                            | Field is required on document-scope responses; Value validates against schemas/EtagToken.schema.json; Value equals the current legacy token string for the document                                                                        |
| outputs.headers.X-List-ETag           | Diagnostic header exposing list collection token for document reorder flows          | string                 | schemas/Outputs.schema.json#/properties/headers/properties/X-List-ETag               | Emitted on document reorder precondition errors                                                       | Field is optional; Value validates against schemas/EtagToken.schema.json; Field appears only on reorder-related error responses; Value equals the legacy list token string                                                                 |
| outputs.headers.X-If-Match-Normalized | Diagnostic header echoing the normalized If-Match used for decisioning               | string                 | schemas/Outputs.schema.json#/properties/headers/properties/X-If-Match-Normalized     | Emitted on document reorder precondition errors to aid troubleshooting                                | Field is optional; Value validates against schemas/IfMatchHeader.schema.json; Field appears only on reorder-related error responses; Value reflects the normalized token list string used for evaluation                                   |
| outputs.body                          | Response body fields that mirror ETag values for parity where applicable             | object                 | schemas/Outputs.schema.json#/properties/body                                         | Mirrors are informational only and unchanged in Phase-0                                               | Object validates against the referenced fragment; Object may be empty when no mirrors exist for the route; Object is immutable within this step after emission                                                                             |
| outputs.body.screen_view.etag         | Body mirror of the active screen’s token on screen GET responses                     | string                 | schemas/Outputs.schema.json#/properties/body/properties/screen_view/properties/etag  | Header remains authoritative where both appear                                                        | Field is required on screen GET responses that include `screen_view`; Value validates against schemas/EtagToken.schema.json; Value equals outputs.headers.Screen-ETag; Value is consistent across header and body within the same response |
| outputs.body.placeholders.etag        | Body mirror of the placeholders collection token on placeholders GET responses       | string                 | schemas/Outputs.schema.json#/properties/body/properties/placeholders/properties/etag | Present only on placeholders reads that already include it                                            | Field is required on placeholders reads that include a body `etag`; Value validates against schemas/EtagToken.schema.json; Value equals outputs.headers.ETag within the same response                                                      |

| Error Code | Field Reference | Description | Likely Cause | Flow Impact | Behavioural AC Required |
|---|---|---|---|---|---|
| PRE_REQUEST_HEADERS_IF_MATCH_MISSING | request.headers.If-Match | If-Match header is required but not provided for a guarded route. | Missing value | halt_pipeline | Yes |
| PRE_REQUEST_HEADERS_IF_MATCH_EMPTY_STRING | request.headers.If-Match | If-Match header value is present but an empty string. | Empty string | halt_pipeline | Yes |
| PRE_REQUEST_HEADERS_IF_MATCH_INVALID_TOKENS_FORMAT | request.headers.If-Match | If-Match header value does not parse as one or more tokens per normaliser rules. | Invalid format | halt_pipeline | Yes |
| PRE_REQUEST_HEADERS_IF_MATCH_MULTI_HEADERS_NOT_JOINED | request.headers.If-Match | Multiple If-Match header instances were provided but not concatenated before parsing. | Multiple headers not joined | halt_pipeline | Yes |
| PRE_REQUEST_PATH_RESPONSE_SET_ID_MISSING | request.path.response_set_id | Response set identifier is required but not provided. | Missing value | halt_pipeline | Yes |
| PRE_REQUEST_PATH_RESPONSE_SET_ID_SCHEMA_MISMATCH | request.path.response_set_id | Response set identifier does not conform to the referenced schema. | Schema mismatch | halt_pipeline | Yes |
| PRE_REQUEST_PATH_RESPONSE_SET_ID_EMPTY_STRING | request.path.response_set_id | Response set identifier is present but an empty string. | Empty string | halt_pipeline | Yes |
| PRE_REQUEST_PATH_SCREEN_KEY_MISSING | request.path.screen_key | Screen key is required but not provided. | Missing value | halt_pipeline | Yes |
| PRE_REQUEST_PATH_SCREEN_KEY_INVALID_SLUG_PATTERN | request.path.screen_key | Screen key does not match the allowed slug pattern. | Invalid slug pattern | halt_pipeline | Yes |
| PRE_REQUEST_PATH_SCREEN_KEY_EMPTY_STRING | request.path.screen_key | Screen key is present but an empty string. | Empty string | halt_pipeline | Yes |
| PRE_REQUEST_PATH_QUESTION_ID_MISSING | request.path.question_id | Question identifier is required but not provided. | Missing value | halt_pipeline | Yes |
| PRE_REQUEST_PATH_QUESTION_ID_SCHEMA_MISMATCH | request.path.question_id | Question identifier does not conform to the referenced schema. | Schema mismatch | halt_pipeline | Yes |
| PRE_REQUEST_PATH_QUESTION_ID_EMPTY_STRING | request.path.question_id | Question identifier is present but an empty string. | Empty string | halt_pipeline | Yes |
| PRE_REQUEST_PATH_DOCUMENT_ID_MISSING | request.path.document_id | Document identifier is required but not provided. | Missing value | halt_pipeline | Yes |
| PRE_REQUEST_PATH_DOCUMENT_ID_SCHEMA_MISMATCH | request.path.document_id | Document identifier does not conform to the referenced schema. | Schema mismatch | halt_pipeline | Yes |
| PRE_REQUEST_PATH_DOCUMENT_ID_EMPTY_STRING | request.path.document_id | Document identifier is present but an empty string. | Empty string | halt_pipeline | Yes |
| PRE_REQUEST_PATH_QUESTIONNAIRE_ID_MISSING | request.path.questionnaire_id | Questionnaire identifier is required but not provided. | Missing value | halt_pipeline | Yes |
| PRE_REQUEST_PATH_QUESTIONNAIRE_ID_SCHEMA_MISMATCH | request.path.questionnaire_id | Questionnaire identifier does not conform to the referenced schema. | Schema mismatch | halt_pipeline | Yes |
| PRE_REQUEST_PATH_QUESTIONNAIRE_ID_EMPTY_STRING | request.path.questionnaire_id | Questionnaire identifier is present but an empty string. | Empty string | halt_pipeline | Yes |
| PRE_ACQUIRED_CURRENT_ETAG_SCREEN_RETRIEVAL_FAILED | acquired.current_etag.screen | Current screen token cannot be retrieved for the addressed screen. | Reference not resolvable | halt_pipeline | Yes |
| PRE_ACQUIRED_CURRENT_ETAG_SCREEN_NOT_STRING | acquired.current_etag.screen | Current screen token is not a string. | Type mismatch | halt_pipeline | Yes |
| PRE_ACQUIRED_CURRENT_ETAG_SCREEN_STALE_VERSION | acquired.current_etag.screen | Current screen token does not represent the persisted version. | Stale or mismatched token | halt_pipeline | Yes |
| PRE_ACQUIRED_CURRENT_ETAG_DOCUMENT_RETRIEVAL_FAILED | acquired.current_etag.document | Current document token cannot be retrieved for the addressed document. | Reference not resolvable | halt_pipeline | Yes |
| PRE_ACQUIRED_CURRENT_ETAG_DOCUMENT_NOT_STRING | acquired.current_etag.document | Current document token is not a string. | Type mismatch | halt_pipeline | Yes |
| PRE_ACQUIRED_CURRENT_ETAG_DOCUMENT_STALE_VERSION | acquired.current_etag.document | Current document token does not represent the persisted version. | Stale or mismatched token | halt_pipeline | Yes |
| PRE_ACQUIRED_CURRENT_ETAG_QUESTIONNAIRE_RETRIEVAL_FAILED | acquired.current_etag.questionnaire | Current questionnaire token cannot be retrieved for the addressed questionnaire. | Reference not resolvable | halt_pipeline | Yes |
| PRE_ACQUIRED_CURRENT_ETAG_QUESTIONNAIRE_NOT_STRING | acquired.current_etag.questionnaire | Current questionnaire token is not a string. | Type mismatch | halt_pipeline | Yes |
| PRE_ACQUIRED_CURRENT_ETAG_QUESTIONNAIRE_STALE_VERSION | acquired.current_etag.questionnaire | Current questionnaire token does not represent the persisted version. | Stale or mismatched token | halt_pipeline | Yes |
| PRE_RETURNED_SCREEN_VIEW_ETAG_PROVIDER_CALL_FAILED | returned.screen_view.etag | Screen view provider call did not complete without error. | Upstream provider error | skip_downstream_step:etag_parity | Yes |
| PRE_RETURNED_SCREEN_VIEW_ETAG_SCHEMA_MISMATCH | returned.screen_view.etag | Returned screen_view.etag does not match the declared schema. | Contract mismatch | skip_downstream_step:etag_parity | Yes |
| PRE_RETURNED_SCREEN_VIEW_ETAG_MISUSED_AS_AUTHORITATIVE | returned.screen_view.etag | Returned screen_view.etag was treated as authoritative rather than advisory for parity checks only. | Incorrect downstream usage | block_finalization | Yes |
| PRE_RETURNED_PLACEHOLDERS_RESPONSE_ETAG_PROVIDER_CALL_FAILED | returned.placeholders_response.etag | Placeholders provider call did not complete without error. | Upstream provider error | skip_downstream_step:etag_parity | Yes |
| PRE_RETURNED_PLACEHOLDERS_RESPONSE_ETAG_SCHEMA_MISMATCH | returned.placeholders_response.etag | Returned placeholders_response.etag does not match the declared schema. | Contract mismatch | skip_downstream_step:etag_parity | Yes |
| PRE_RETURNED_PLACEHOLDERS_RESPONSE_ETAG_MISUSED_AS_AUTHORITATIVE | returned.placeholders_response.etag | Returned placeholders_response.etag was treated as authoritative rather than advisory for parity checks only. | Incorrect downstream usage | block_finalization | Yes |
| PRE_REQUEST_HEADERS_IF_MATCH_MULTI_HEADERS_NOT_JOINED | request.headers.If-Match | Multiple If-Match header instances were provided but not concatenated before parsing. | Multiple headers not joined | halt_pipeline | Yes |
| PRE_RETURNED_SCREEN_VIEW_ETAG_PROVIDER_CALL_FAILED | returned.screen_view.etag | Screen view provider call did not complete without error. | Upstream provider error | skip_downstream_step:etag_parity | Yes |
| PRE_RETURNED_SCREEN_VIEW_ETAG_SCHEMA_MISMATCH | returned.screen_view.etag | Returned screen_view.etag does not match the declared schema. | Contract mismatch | skip_downstream_step:etag_parity | Yes |
| PRE_RETURNED_SCREEN_VIEW_ETAG_MISUSED_AS_AUTHORITATIVE | returned.screen_view.etag | Returned screen_view.etag was treated as authoritative rather than advisory for parity checks only. | Incorrect downstream usage | block_finalization | Yes |
| PRE_RETURNED_PLACEHOLDERS_RESPONSE_ETAG_PROVIDER_CALL_FAILED | returned.placeholders_response.etag | Placeholders provider call did not complete without error. | Upstream provider error | skip_downstream_step:etag_parity | Yes |
| PRE_RETURNED_PLACEHOLDERS_RESPONSE_ETAG_SCHEMA_MISMATCH | returned.placeholders_response.etag | Returned placeholders_response.etag does not match the declared schema. | Contract mismatch | skip_downstream_step:etag_parity | Yes |
| PRE_RETURNED_PLACEHOLDERS_RESPONSE_ETAG_MISUSED_AS_AUTHORITATIVE | returned.placeholders_response.etag | Returned placeholders_response.etag was treated as authoritative rather than advisory for parity checks only. | Incorrect downstream usage | block_finalization | Yes |
| PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED | request.headers.Content-Type | Content-Type header value is not supported by the addressed route. | Unsupported media type (e.g., text/
plain where application/json is required) | halt_pipeline | Yes |

| Error Code                                               | Output Field Ref                      | Description                                                                                    | Likely Cause                   | Flow Impact        | Behavioural AC Required |
| -------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------ | ------------------ | ----------------------- |
| POST_OUTPUTS_SCHEMA_INVALID                              | outputs                               | Outputs object does not validate against the canonical outputs schema.                         | Schema mismatch                | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_KEY_MISSING                         | outputs                               | Outputs object is missing required key `headers`.                                              | Missing field                  | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_KEY_MISSING                            | outputs                               | Outputs object is missing required key `body`.                                                 | Missing field                  | block_finalization | Yes                     |
| POST_OUTPUTS_MUTATED_AFTER_EMISSION                      | outputs                               | Outputs object was mutated within the step after emission.                                     | Uncontrolled mutation          | block_finalization | Yes                     |
| POST_OUTPUTS_KEY_SET_NONDETERMINISTIC                    | outputs                               | Outputs object key set is not deterministic for identical inputs.                              | Non-deterministic construction | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_SCHEMA_INVALID                      | outputs.headers                       | Headers mapping does not validate against the declared fragment.                               | Schema mismatch                | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_DUPLICATE_CASE_VARIANTS             | outputs.headers                       | Headers mapping contains duplicate keys differing only by case.                                | Duplicate header variants      | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_ETAG_MISSING_WHEN_REQUIRED          | outputs.headers.ETag                  | ETag header is missing on an in-scope success response that historically emitted ETag.         | Missing field                  | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_ETAG_INVALID_FORMAT                 | outputs.headers.ETag                  | ETag header value does not validate against the ETag token schema.                             | Invalid format                 | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_ETAG_TOKEN_MISMATCH                 | outputs.headers.ETag                  | ETag header value does not equal the current legacy token for the resource.                    | Token parity mismatch          | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING                 | outputs.headers.Screen-ETag           | Screen-ETag header is missing on a screen-scope response.                                      | Missing field                  | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_SCREEN_ETAG_INVALID_FORMAT          | outputs.headers.Screen-ETag           | Screen-ETag header value does not validate against the token schema.                           | Invalid format                 | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_SCREEN_ETAG_TOKEN_MISMATCH          | outputs.headers.Screen-ETag           | Screen-ETag header value does not equal the current legacy token for the screen.               | Token parity mismatch          | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_QUESTION_ETAG_MISSING               | outputs.headers.Question-ETag         | Question-ETag header is missing on a question-scope response that historically emitted it.     | Missing field                  | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_QUESTION_ETAG_INVALID_FORMAT        | outputs.headers.Question-ETag         | Question-ETag header value does not validate against the token schema.                         | Invalid format                 | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_QUESTION_ETAG_TOKEN_MISMATCH        | outputs.headers.Question-ETag         | Question-ETag header value does not equal the current legacy token for the question.           | Token parity mismatch          | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_QUESTIONNAIRE_ETAG_MISSING          | outputs.headers.Questionnaire-ETag    | Questionnaire-ETag header is missing on a questionnaire-scope response.                        | Missing field                  | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_QUESTIONNAIRE_ETAG_INVALID_FORMAT   | outputs.headers.Questionnaire-ETag    | Questionnaire-ETag header value does not validate against the token schema.                    | Invalid format                 | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_QUESTIONNAIRE_ETAG_TOKEN_MISMATCH   | outputs.headers.Questionnaire-ETag    | Questionnaire-ETag header value does not equal the current legacy token for the questionnaire. | Token parity mismatch          | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_DOCUMENT_ETAG_MISSING               | outputs.headers.Document-ETag         | Document-ETag header is missing on a document-scope response.                                  | Missing field                  | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_DOCUMENT_ETAG_INVALID_FORMAT        | outputs.headers.Document-ETag         | Document-ETag header value does not validate against the token schema.                         | Invalid format                 | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_DOCUMENT_ETAG_TOKEN_MISMATCH        | outputs.headers.Document-ETag         | Document-ETag header value does not equal the current legacy token for the document.           | Token parity mismatch          | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_X_LIST_ETAG_INVALID_FORMAT          | outputs.headers.X-List-ETag           | X-List-ETag value does not validate against the token schema when present.                     | Invalid format                 | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_X_LIST_ETAG_WRONG_CONTEXT           | outputs.headers.X-List-ETag           | X-List-ETag appears outside reorder-related error responses.                                   | Incorrect emission context     | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_X_LIST_ETAG_TOKEN_MISMATCH          | outputs.headers.X-List-ETag           | X-List-ETag value does not equal the legacy list token string.                                 | Token parity mismatch          | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_X_IF_MATCH_NORMALIZED_INVALID       | outputs.headers.X-If-Match-Normalized | X-If-Match-Normalized value does not validate against the If-Match header schema when present. | Invalid format                 | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_X_IF_MATCH_NORMALIZED_WRONG_CONTEXT | outputs.headers.X-If-Match-Normalized | X-If-Match-Normalized appears outside reorder-related error responses.                         | Incorrect emission context     | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_X_IF_MATCH_NORMALIZED_MISMATCH      | outputs.headers.X-If-Match-Normalized | X-If-Match-Normalized value does not reflect the normalized token list used for evaluation.    | Normalization mismatch         | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_SCHEMA_INVALID                         | outputs.body                          | Body object does not validate against the declared fragment.                                   | Schema mismatch                | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_MUTATED_AFTER_EMISSION                 | outputs.body                          | Body object was mutated within the step after emission.                                        | Uncontrolled mutation          | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_SCREEN_VIEW_ETAG_MISSING               | outputs.body.screen_view.etag         | Body mirror etag is missing on a screen GET response that includes screen_view.                | Missing field                  | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_SCREEN_VIEW_ETAG_INVALID_FORMAT        | outputs.body.screen_view.etag         | Body mirror etag does not validate against the token schema.                                   | Invalid format                 | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_SCREEN_VIEW_ETAG_MISMATCH_HEADER       | outputs.body.screen_view.etag         | Body mirror etag does not equal outputs.headers.Screen-ETag.                                   | Token parity mismatch          | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_SCREEN_VIEW_ETAG_INCONSISTENT          | outputs.body.screen_view.etag         | Body mirror etag is not consistent with the header value within the same response.             | Inconsistent duplication       | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_PLACEHOLDERS_ETAG_MISSING              | outputs.body.placeholders.etag        | Placeholders body etag is missing on a placeholders read that includes a body etag.            | Missing field                  | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_PLACEHOLDERS_ETAG_INVALID_FORMAT       | outputs.body.placeholders.etag        | Placeholders body etag does not validate against the token schema.                             | Invalid format                 | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_PLACEHOLDERS_ETAG_MISMATCH_HEADER      | outputs.body.placeholders.etag        | Placeholders body etag does not equal outputs.headers.ETag within the same response.           | Token parity mismatch          | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_UNDECLARED_KEY_PRESENT | outputs.headers  | Headers mapping contains a key not declared in the outputs schema fragment. | Unexpected header key                        | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_VALUE_NOT_STRING       | outputs.headers  | Headers mapping contains a value that is not a string.                      | Type mismatch against mapping[string→string] | block_finalization | Yes                     |
| POST_OUTPUTS_BODY_UNDECLARED_KEY_PRESENT    | outputs.body     | Body object contains a key not declared in the outputs schema fragment.     | Unexpected field in body                     | block_finalization | Yes                     |

| Error Code                            | Description                                                                                           | Likely Cause                                          | Impacted Steps | EARS Refs           | Flow Impact        | Behavioural AC Required |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------- | ----------------------------------------------------- | -------------- | ------------------- | ------------------ | ----------------------- |
| ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED | CORS Access-Control-Expose-Headers does not include required domain ETag headers readable by browsers | Misconfigured CORS or API gateway policy              | STEP-4         | U13, E3, E4, E5, E6 | block_finalization | Yes                     |
| ENV_LOGGING_SINK_UNAVAILABLE_ENFORCE  | etag.enforce log event cannot be written to the logging sink                                          | Log collector unreachable or sink credentials invalid | STEP-2         | U14                 | no_flow_effect     | No                      |
| ENV_LOGGING_SINK_UNAVAILABLE_EMIT     | etag.emit log event cannot be written to the logging sink                                             | Log collector unreachable or sink credentials invalid | STEP-4         | U15                 | no_flow_effect     | No                      |
| ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS    | Upstream proxy/gateway strips domain ETag headers from responses, preventing clients from reading them. | Header whitelist excludes custom headers or response header sanitisation enabled | STEP-4         | U9, U16, E3, E4, E5, E6 | block_finalization | Yes                     |
| ENV_CORS_ALLOW_HEADERS_MISSING_IF_MATCH | CORS Access-Control-Allow-Headers does not permit If-Match, so browsers block sending it on writes.     | Misconfigured CORS allow-list for request headers                                | STEP-2         | E1, E2                  | halt_pipeline      | Yes                     |
| ENV_PROXY_STRIPS_IF_MATCH               | Reverse proxy/API gateway drops or renames the incoming If-Match request header.                        | Security policy or header normalisation stripping hop-by-hop/custom headers      | STEP-2         | E1, E2                  | halt_pipeline      | Yes                     |
| ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS  | Precondition guard is mounted on GET/read routes contrary to Phase-0 scope.                             | Router/dependency configuration error                                            | STEP-2         | S1, E5                  | halt_pipeline      | Yes                     |

# 6.1 Architectural Acceptance Criteria

**6.1.1 Shared If-Match normaliser**
A single reusable normalisation utility is defined and is the only mechanism used to parse/normalise `If-Match` across in-scope routes.
**Refs:** STEP-1; U1, U2, U3, U4, U5, U6, U7

**6.1.2 Precondition guard as a discrete unit**
The precondition enforcement is implemented as a discrete middleware/guard component that is separate from mutation handlers.
**Refs:** STEP-2; E1, E2

**6.1.3 Guard mounted on write routes only (answers/documents)**
The precondition guard is mounted on answers and document write endpoints and is invoked before any mutation handler.
**Refs:** STEP-2; E1, E2

**6.1.4 Guard not mounted on authoring routes (Phase-0)**
No authoring route registers or invokes the precondition guard in Phase-0.
**Refs:** STEP-2; S1

**6.1.5 Central header-emission utility**
A single response-header emitter is used by all in-scope responses to set domain ETag headers and (where applicable) the generic `ETag`.
**Refs:** STEP-4; U9, U10, U11; E3, E4, E5, E6

**6.1.6 Scope→header mapping centralised**
The mapping from resource scope to domain header name (Screen-ETag, Question-ETag, Questionnaire-ETag, Document-ETag) is declared once and reused by the header-emission utility.
**Refs:** STEP-4; U16

**6.1.7 CORS exposes required ETag headers**
The CORS configuration explicitly exposes all domain ETag headers (and `ETag`) required for browser access.
**Refs:** STEP-4; U13

**6.1.8 Outputs schema declares canonical keys**
The canonical outputs schema declares the required top-level keys `headers` and `body` exactly as specified.
**Refs:** outputs; outputs.headers; outputs.body

**6.1.9 Outputs schema includes domain header fields**
The canonical outputs schema includes fields for `Screen-ETag`, `Question-ETag`, `Questionnaire-ETag`, `Document-ETag`, and `ETag` under `headers`.
**Refs:** outputs.headers.Screen-ETag; outputs.headers.Question-ETag; outputs.headers.Questionnaire-ETag; outputs.headers.Document-ETag; outputs.headers.ETag

**6.1.10 No new body mirrors introduced**
No additional body mirrors (e.g., no `outputs.etags`) are declared in schemas or response assemblers beyond those already specified.
**Refs:** STEP-5; U12

**6.1.11 Screen body mirror retained**
Where `screen_view` is returned, the schema and response assembly retain `screen_view.etag` exactly as specified.
**Refs:** STEP-5; E7; outputs.body.screen_view.etag

**6.1.12 Diagnostic headers preserved for reorder**
The emission path preserves support for `X-List-ETag` and `X-If-Match-Normalized` on document reorder responses.
**Refs:** STEP-4; O4

**6.1.13 Token computation isolated and unchanged**
The tag retrieval/compute mechanism is isolated from normalisation/enforcement code and remains unmodified in Phase-0.
**Refs:** STEP-3; U17, U8

**6.1.14 OpenAPI responses declare domain headers**
Affected endpoint responses in the API specification declare the relevant domain ETag headers (and `ETag` where applicable).
**Refs:** STEP-4; E3, E4, E5, E6

**6.1.15 CSV/non-JSON emission uses same header utility**
The header-emission utility is usable from non-JSON response paths (e.g., CSV export) to set `Questionnaire-ETag` (and `ETag` where applicable).
**Refs:** STEP-4; E6

**6.1.16 Logging interface defines etag event types**
A logging interface declares the two event types `etag.enforce` and `etag.emit` for use at precondition check and header emission points.
**Refs:** STEP-2, STEP-4; U14, U15

6.1.17 Guard not mounted on any GET/read endpoints
The precondition guard must be excluded from all GET/read routes across resources (runtime and authoring).
Refs: STEP-2; S4

6.1.18 Guard is DB-free and import-safe
The guard module must import no repositories or DB drivers at module scope; importing the guard must succeed with no DB driver installed. Any allowed ETag helper imports occur lazily inside guard functions.
Refs: STEP-2; U19

6.1.19 Handlers contain no inline precondition logic
Mutation handlers must not parse/normalise/compare If-Match, nor construct precondition problem responses; those concerns live only in the guard.
Refs: STEP-2; U18

6.1.20 Stable problem+json mapping for preconditions
The guard centralises error mapping: missing If-Match → 428 with code PRE_IF_MATCH_MISSING; mismatched If-Match → existing route status (409 or 412) with code PRE_IF_MATCH_ETAG_MISMATCH. Shapes remain invariant.
Refs: STEP-2; E8, E9

6.1.21 OpenAPI declares If-Match as a required request header on write routes
All in-scope write endpoints declare If-Match as a required header parameter (e.g., FastAPI Header(..., alias="If-Match", convert_underscores=False)), with enforcement still in the guard.
Refs: OpenAPI; STEP-2

6.1.22 Guard uses only public ETag APIs
The guard may only call documented, public app.logic.etag helpers; no private/import-path internals are allowed.
Refs: STEP-1, STEP-2; U19

6.1.23 Diagnostic headers emitted via the central emitter
On document reorder precondition failures, X-List-ETag and (when applicable) X-If-Match-Normalized are attached by the shared header-emission/diagnostics utility, not handcrafted in handlers.
Refs: STEP-4; O4; N7

6.1.24 CORS request header allow-list includes If-Match
CORS configuration must allow the If-Match request header so browsers can send it on writes (e.g., Access-Control-Allow-Headers: If-Match).
Refs: STEP-2; E1, E2

6.1.25 Guard responses participate in CORS
Early guard failures (e.g., 428/409/412) must still include the CORS headers configured for the API so browsers can read diagnostic headers and problem bodies.
Refs: STEP-2; U13

6.1.26 No repository calls before guard success
Route pipelines must be ordered such that repository/DB access occurs only after guard success (short-circuit on failure).
Refs: STEP-2; U18, U19

# 6.2.1.1 Runtime screen GET returns domain + generic tags (parity)

**Given** a runtime JSON GET for a screen, **when** the request succeeds, **then** the response includes both headers and they carry the same value.
**Reference:** EARS: E4, U9, U10; Outputs: outputs.headers.Screen-ETag, outputs.headers.ETag

# 6.2.1.2 Runtime screen GET includes body mirror (parity with header)

**Given** a runtime JSON GET for a screen, **when** the request succeeds, **then** the payload includes `screen_view.etag` and it equals the `Screen-ETag` header.
**Reference:** EARS: E7, O3, U12; Outputs: outputs.body.screen_view.etag, outputs.headers.Screen-ETag

# 6.2.1.3 Runtime document GET returns domain + generic tags (parity)

**Given** a runtime JSON GET for a document, **when** the request succeeds, **then** the response includes `Document-ETag` and `ETag` headers with identical values.
**Reference:** EARS: E4, U9, U10; Outputs: outputs.headers.Document-ETag, outputs.headers.ETag

# 6.2.1.4 Authoring JSON GET returns domain tag only

**Given** an authoring JSON GET (Epic G), **when** the request succeeds, **then** the response includes the resource’s domain ETag header and does not include the generic `ETag`.
**Reference:** EARS: E5, U9, U10; Outputs: outputs.headers.Screen-ETag (or Question-ETag), outputs.headers.ETag

# 6.2.1.5 Answers PATCH with valid If-Match emits fresh tags (screen scope)

**Given** a write to answers with a valid `If-Match` that matches the current tag, **when** the mutation succeeds, **then** the response includes `Screen-ETag` and `ETag` headers with the (current) legacy value.
**Reference:** EARS: E1, E3, U11, U9, U10; Outputs: outputs.headers.Screen-ETag, outputs.headers.ETag, status

# 6.2.1.6 Answers PATCH (with body mirror) keeps header–body parity

**Given** a successful answers PATCH whose response includes `screen_view`, **when** the response is returned, **then** `body.screen_view.etag` equals the `Screen-ETag` header.
**Reference:** EARS: E3, E7, O3, U12; Outputs: outputs.body.screen_view.etag, outputs.headers.Screen-ETag

# 6.2.1.7 Document write success emits domain + generic tags

**Given** a successful document write, **when** the response is returned, **then** the response includes `Document-ETag` and `ETag` headers with identical values.
**Reference:** EARS: E2, E3, U9, U10, U11; Outputs: outputs.headers.Document-ETag, outputs.headers.ETag, status

# 6.2.1.8 Questionnaire CSV export emits questionnaire tag (parity with ETag)

**Given** a questionnaire CSV export, **when** the response is returned, **then** the response includes `Questionnaire-ETag` and `ETag` headers with the same value.
**Reference:** EARS: E6, U9, U10; Outputs: outputs.headers.Questionnaire-ETag, outputs.headers.ETag, status

# 6.2.1.9 Placeholders GET returns body etag and generic header (parity)

**Given** a placeholders GET for a question, **when** the request succeeds, **then** the payload includes `placeholders.etag` and the response includes `ETag`, and these values are equal.
**Reference:** EARS: S2, U12; Outputs: outputs.body.placeholders.etag, outputs.headers.ETag

# 6.2.1.10 Placeholders bind/unbind success emits generic tag only

**Given** a successful placeholders bind or unbind, **when** the response is returned, **then** the response includes the generic `ETag` header and does not include any domain ETag headers.
**Reference:** EARS: S2; Outputs: outputs.headers.ETag, outputs.headers.Screen-ETag, outputs.headers.Document-ETag, outputs.headers.Question-ETag, outputs.headers.Questionnaire-ETag, status

# 6.2.1.11 Authoring writes succeed without If-Match (Phase-0)

**Given** an authoring write in Phase-0 without `If-Match`, **when** the request is processed, **then** the response indicates success and includes the relevant domain ETag header, and does not include the generic `ETag`.
**Reference:** EARS: S1, E5; Outputs: status, outputs.headers.Screen-ETag (or Question-ETag), outputs.headers.ETag

# 6.2.1.12 Domain header matches resource scope on success

# 6.2.1.13 **Given** any successful response, **when** the resource scope is screen, question, questionnaire, or document, **then** the response uses the corresponding domain header name for that scope.
**Reference:** EARS: U16; Outputs: outputs.headers.Screen-ETag, outputs.headers.Question-ETag, outputs.headers.Questionnaire-ETag, outputs.headers.Document-ETag

6.2.1.14 CORS exposes domain headers on authoring reads
Given an authoring JSON GET (Epic G routes), when the request succeeds, then the response must include Access-Control-Expose-Headers that lists the emitted domain header(s) (and not require generic ETag) so browsers can read them.
Reference: EARS: U13, E5 • Outputs: meta.Access-Control-Expose-Headers, headers.Screen-ETag (and/or headers.Question-ETag as applicable)

6.2.1.15 CORS exposes Questionnaire-ETag on CSV export
Given a questionnaire CSV export GET, when the request succeeds, then the response must include Access-Control-Expose-Headers that lists Questionnaire-ETag (and ETag if emitted) so browser clients can access the tag.
Reference: EARS: U13, E6 • Outputs: meta.Access-Control-Expose-Headers, headers.Questionnaire-ETag, headers.ETag

6.2.1.16 Preflight allows If-Match on write routes
Given an OPTIONS CORS preflight to an in-scope write endpoint (answers/documents), when the preflight succeeds, then the response must include Access-Control-Allow-Headers containing If-Match so browser writes can supply the precondition header.
Reference: EARS: E1, E2 • Outputs: meta.Access-Control-Allow-Headers

6.2.2.1 If-Match header missing (guarded route)
**Criterion:** Given a guarded write route requiring If-Match, when `request.headers.If-Match` is not provided, then the response status is a client error and the operation is not performed.
**Error Mode:** PRE_REQUEST_HEADERS_IF_MATCH_MISSING
**Reference:** request.headers.If-Match, status

6.2.2.2 If-Match header empty string
**Criterion:** Given a guarded write route, when `request.headers.If-Match` is an empty string, then the response status is a client error and the operation is not performed.
**Error Mode:** PRE_REQUEST_HEADERS_IF_MATCH_EMPTY_STRING
**Reference:** request.headers.If-Match, status

6.2.2.3 If-Match tokens invalid format
**Criterion:** Given a guarded write route, when `request.headers.If-Match` cannot be parsed as one or more tokens, then the response status is a client error and the operation is not performed.
**Error Mode:** PRE_REQUEST_HEADERS_IF_MATCH_INVALID_TOKENS_FORMAT
**Reference:** request.headers.If-Match, status

6.2.2.4 Multiple If-Match headers not joined
**Criterion:** Given a guarded write route, when multiple `request.headers.If-Match` instances are sent and not concatenated for parsing, then the response status is a client error and the operation is not performed.
**Error Mode:** PRE_REQUEST_HEADERS_IF_MATCH_MULTI_HEADERS_NOT_JOINED
**Reference:** request.headers.If-Match, status

6.2.2.5 response_set_id missing
**Criterion:** Given a route requiring a response set, when `request.path.response_set_id` is not provided, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_RESPONSE_SET_ID_MISSING
**Reference:** request.path.response_set_id, status

6.2.2.6 response_set_id schema mismatch
**Criterion:** Given a route requiring a response set, when `request.path.response_set_id` does not conform to its schema, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_RESPONSE_SET_ID_SCHEMA_MISMATCH
**Reference:** request.path.response_set_id, status

6.2.2.7 response_set_id empty string
**Criterion:** Given a route requiring a response set, when `request.path.response_set_id` is an empty string, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_RESPONSE_SET_ID_EMPTY_STRING
**Reference:** request.path.response_set_id, status

6.2.2.8 screen_key missing
**Criterion:** Given a screen-scoped route, when `request.path.screen_key` is not provided, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_SCREEN_KEY_MISSING
**Reference:** request.path.screen_key, status

6.2.2.9 screen_key invalid slug pattern
**Criterion:** Given a screen-scoped route, when `request.path.screen_key` does not match the allowed slug pattern, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_SCREEN_KEY_INVALID_SLUG_PATTERN
**Reference:** request.path.screen_key, status

6.2.2.10 screen_key empty string
**Criterion:** Given a screen-scoped route, when `request.path.screen_key` is an empty string, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_SCREEN_KEY_EMPTY_STRING
**Reference:** request.path.screen_key, status

6.2.2.11 question_id missing
**Criterion:** Given a question-scoped route, when `request.path.question_id` is not provided, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_QUESTION_ID_MISSING
**Reference:** request.path.question_id, status

6.2.2.12 question_id schema mismatch
**Criterion:** Given a question-scoped route, when `request.path.question_id` does not conform to its schema, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_QUESTION_ID_SCHEMA_MISMATCH
**Reference:** request.path.question_id, status

6.2.2.13 question_id empty string
**Criterion:** Given a question-scoped route, when `request.path.question_id` is an empty string, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_QUESTION_ID_EMPTY_STRING
**Reference:** request.path.question_id, status

6.2.2.14 document_id missing
**Criterion:** Given a document-scoped route, when `request.path.document_id` is not provided, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_DOCUMENT_ID_MISSING
**Reference:** request.path.document_id, status

6.2.2.15 document_id schema mismatch
**Criterion:** Given a document-scoped route, when `request.path.document_id` does not conform to its schema, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_DOCUMENT_ID_SCHEMA_MISMATCH
**Reference:** request.path.document_id, status

6.2.2.16 document_id empty string
**Criterion:** Given a document-scoped route, when `request.path.document_id` is an empty string, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_DOCUMENT_ID_EMPTY_STRING
**Reference:** request.path.document_id, status

6.2.2.17 questionnaire_id missing
**Criterion:** Given a questionnaire-scoped route, when `request.path.questionnaire_id` is not provided, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_QUESTIONNAIRE_ID_MISSING
**Reference:** request.path.questionnaire_id, status

6.2.2.18 questionnaire_id schema mismatch
**Criterion:** Given a questionnaire-scoped route, when `request.path.questionnaire_id` does not conform to its schema, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_QUESTIONNAIRE_ID_SCHEMA_MISMATCH
**Reference:** request.path.questionnaire_id, status

6.2.2.19 questionnaire_id empty string
**Criterion:** Given a questionnaire-scoped route, when `request.path.questionnaire_id` is an empty string, then the response status is a client error and the request is rejected.
**Error Mode:** PRE_REQUEST_PATH_QUESTIONNAIRE_ID_EMPTY_STRING
**Reference:** request.path.questionnaire_id, status

6.2.2.20 Current screen etag retrieval failed
**Criterion:** Given a screen write or parity check, when `acquired.current_etag.screen` cannot be retrieved, then the response status is a server or precondition error and the operation is not performed.
**Error Mode:** PRE_ACQUIRED_CURRENT_ETAG_SCREEN_RETRIEVAL_FAILED
**Reference:** acquired.current_etag.screen, status

6.2.2.21 Current screen etag not a string
**Criterion:** Given a screen write or parity check, when `acquired.current_etag.screen` is not a string, then the response status is a server error and the operation is not performed.
**Error Mode:** PRE_ACQUIRED_CURRENT_ETAG_SCREEN_NOT_STRING
**Reference:** acquired.current_etag.screen, status

6.2.2.22 Current screen etag stale version
**Criterion:** Given a screen write or parity check, when `acquired.current_etag.screen` does not represent the persisted version, then the response status is a precondition error and the operation is not performed.
**Error Mode:** PRE_ACQUIRED_CURRENT_ETAG_SCREEN_STALE_VERSION
**Reference:** acquired.current_etag.screen, status

6.2.2.23 Current document etag retrieval failed
**Criterion:** Given a document route, when `acquired.current_etag.document` cannot be retrieved, then the response status is a server or precondition error and the operation is not performed.
**Error Mode:** PRE_ACQUIRED_CURRENT_ETAG_DOCUMENT_RETRIEVAL_FAILED
**Reference:** acquired.current_etag.document, status

6.2.2.24 Current document etag not a string
**Criterion:** Given a document route, when `acquired.current_etag.document` is not a string, then the response status is a server error and the operation is not performed.
**Error Mode:** PRE_ACQUIRED_CURRENT_ETAG_DOCUMENT_NOT_STRING
**Reference:** acquired.current_etag.document, status

6.2.2.25 Current document etag stale version
**Criterion:** Given a document route, when `acquired.current_etag.document` does not represent the persisted version, then the response status is a precondition error and the operation is not performed.
**Error Mode:** PRE_ACQUIRED_CURRENT_ETAG_DOCUMENT_STALE_VERSION
**Reference:** acquired.current_etag.document, status

6.2.2.26 Current questionnaire etag retrieval failed
**Criterion:** Given a questionnaire export, when `acquired.current_etag.questionnaire` cannot be retrieved, then the response status is a server error and the operation is not performed.
**Error Mode:** PRE_ACQUIRED_CURRENT_ETAG_QUESTIONNAIRE_RETRIEVAL_FAILED
**Reference:** acquired.current_etag.questionnaire, status

6.2.2.27 Current questionnaire etag not a string
**Criterion:** Given a questionnaire export, when `acquired.current_etag.questionnaire` is not a string, then the response status is a server error and the operation is not performed.
**Error Mode:** PRE_ACQUIRED_CURRENT_ETAG_QUESTIONNAIRE_NOT_STRING
**Reference:** acquired.current_etag.questionnaire, status

6.2.2.28 Current questionnaire etag stale version
**Criterion:** Given a questionnaire export, when `acquired.current_etag.questionnaire` does not represent the persisted version, then the response status is a precondition error and the operation is not performed.
**Error Mode:** PRE_ACQUIRED_CURRENT_ETAG_QUESTIONNAIRE_STALE_VERSION
**Reference:** acquired.current_etag.questionnaire, status

6.2.2.29 screen_view provider call failed
**Criterion:** Given a screen GET, when `returned.screen_view.etag` cannot be obtained due to provider failure, then the system skips parity checks and returns a non-2xx status or omits the mirror.
**Error Mode:** PRE_RETURNED_SCREEN_VIEW_ETAG_PROVIDER_CALL_FAILED
**Reference:** returned.screen_view.etag, status

6.2.2.30 screen_view.etag schema mismatch
**Criterion:** Given a screen GET, when `returned.screen_view.etag` fails schema validation, then the system skips parity checks and returns a non-2xx status or omits the mirror.
**Error Mode:** PRE_RETURNED_SCREEN_VIEW_ETAG_SCHEMA_MISMATCH
**Reference:** returned.screen_view.etag, status

6.2.2.31 screen_view.etag misused as authoritative
**Criterion:** Given a screen GET, when `returned.screen_view.etag` is treated as authoritative over headers, then finalisation is blocked and a non-2xx status is returned.
**Error Mode:** PRE_RETURNED_SCREEN_VIEW_ETAG_MISUSED_AS_AUTHORITATIVE
**Reference:** returned.screen_view.etag, outputs.headers.Screen-ETag, status

6.2.2.32 placeholders provider call failed
**Criterion:** Given a placeholders GET, when `returned.placeholders_response.etag` cannot be obtained due to provider failure, then the system skips parity checks and returns a non-2xx status or omits the mirror.
**Error Mode:** PRE_RETURNED_PLACEHOLDERS_RESPONSE_ETAG_PROVIDER_CALL_FAILED
**Reference:** returned.placeholders_response.etag, status

6.2.2.33 placeholders.etag schema mismatch
**Criterion:** Given a placeholders GET, when `returned.placeholders_response.etag` fails schema validation, then the system skips parity checks and returns a non-2xx status or omits the mirror.
**Error Mode:** PRE_RETURNED_PLACEHOLDERS_RESPONSE_ETAG_SCHEMA_MISMATCH
**Reference:** returned.placeholders_response.etag, status

6.2.2.34 placeholders.etag misused as authoritative
**Criterion:** Given a placeholders GET, when `returned.placeholders_response.etag` is treated as authoritative over headers, then finalisation is blocked and a non-2xx status is returned.
**Error Mode:** PRE_RETURNED_PLACEHOLDERS_RESPONSE_ETAG_MISUSED_AS_AUTHORITATIVE
**Reference:** returned.placeholders_response.etag, outputs.headers.ETag, status

6.2.2.35 Outputs container invalid
**Criterion:** Given any response, when `outputs` fails its schema, then the response is treated as invalid and the operation cannot be finalised.
**Error Mode:** POST_OUTPUTS_SCHEMA_INVALID
**Reference:** outputs, status

6.2.2.36 Headers key missing
**Criterion:** Given any response, when `outputs.headers` is missing, then the response is treated as invalid and the operation cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_KEY_MISSING
**Reference:** outputs.headers, status

6.2.2.37 Body key missing
**Criterion:** Given any response, when `outputs.body` is missing, then the response is treated as invalid and the operation cannot be finalised.
**Error Mode:** POST_OUTPUTS_BODY_KEY_MISSING
**Reference:** outputs.body, status

6.2.2.38 Outputs mutated after emission
**Criterion:** Given any response, when `outputs` is mutated after emission, then the response is treated as invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_MUTATED_AFTER_EMISSION
**Reference:** outputs, status

6.2.2.39 Outputs key set non-deterministic
**Criterion:** Given identical inputs, when `outputs` keys vary, then the response is treated as invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_KEY_SET_NONDETERMINISTIC
**Reference:** outputs, status

6.2.2.40 Headers mapping invalid
**Criterion:** Given any response, when `outputs.headers` fails its fragment schema, then the response is treated as invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_SCHEMA_INVALID
**Reference:** outputs.headers, status

6.2.2.41 Duplicate case-variant headers
**Criterion:** Given any response, when `outputs.headers` contains duplicate keys differing only by case, then the response is treated as invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_DUPLICATE_CASE_VARIANTS
**Reference:** outputs.headers, status

6.2.2.42 ETag missing when required
**Criterion:** Given an in-scope success response that historically emitted ETag, when `outputs.headers.ETag` is missing, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_ETAG_MISSING_WHEN_REQUIRED
**Reference:** outputs.headers.ETag, status

6.2.2.43 ETag invalid format
**Criterion:** Given an in-scope response, when `outputs.headers.ETag` does not match the token schema, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_ETAG_INVALID_FORMAT
**Reference:** outputs.headers.ETag, status

6.2.2.44 ETag token mismatch
**Criterion:** Given an in-scope response, when `outputs.headers.ETag` does not equal the current legacy token, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_ETAG_TOKEN_MISMATCH
**Reference:** outputs.headers.ETag, status

6.2.2.45 Screen-ETag missing
**Criterion:** Given a screen-scope response, when `outputs.headers.Screen-ETag` is missing, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING
**Reference:** outputs.headers.Screen-ETag, status

6.2.2.46 Screen-ETag invalid format
**Criterion:** Given a screen-scope response, when `outputs.headers.Screen-ETag` does not match the token schema, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_SCREEN_ETAG_INVALID_FORMAT
**Reference:** outputs.headers.Screen-ETag, status

6.2.2.47 Screen-ETag token mismatch
**Criterion:** Given a screen-scope response, when `outputs.headers.Screen-ETag` does not equal the current legacy token, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_SCREEN_ETAG_TOKEN_MISMATCH
**Reference:** outputs.headers.Screen-ETag, status

6.2.2.48 Question-ETag missing
**Criterion:** Given a question-scope response that historically emitted it, when `outputs.headers.Question-ETag` is missing, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_QUESTION_ETAG_MISSING
**Reference:** outputs.headers.Question-ETag, status

6.2.2.49 Question-ETag invalid format
**Criterion:** Given a question-scope response, when `outputs.headers.Question-ETag` does not match the token schema, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_QUESTION_ETAG_INVALID_FORMAT
**Reference:** outputs.headers.Question-ETag, status

6.2.2.50 Question-ETag token mismatch
**Criterion:** Given a question-scope response, when `outputs.headers.Question-ETag` does not equal the current legacy token, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_QUESTION_ETAG_TOKEN_MISMATCH
**Reference:** outputs.headers.Question-ETag, status

6.2.2.51 Questionnaire-ETag missing
**Criterion:** Given a questionnaire-scope response, when `outputs.headers.Questionnaire-ETag` is missing, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_QUESTIONNAIRE_ETAG_MISSING
**Reference:** outputs.headers.Questionnaire-ETag, status

6.2.2.52 Questionnaire-ETag invalid format
**Criterion:** Given a questionnaire-scope response, when `outputs.headers.Questionnaire-ETag` does not match the token schema, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_QUESTIONNAIRE_ETAG_INVALID_FORMAT
**Reference:** outputs.headers.Questionnaire-ETag, status

6.2.2.53 Questionnaire-ETag token mismatch
**Criterion:** Given a questionnaire-scope response, when `outputs.headers.Questionnaire-ETag` does not equal the current legacy token, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_QUESTIONNAIRE_ETAG_TOKEN_MISMATCH
**Reference:** outputs.headers.Questionnaire-ETag, status

6.2.2.54 Document-ETag missing
**Criterion:** Given a document-scope response, when `outputs.headers.Document-ETag` is missing, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_DOCUMENT_ETAG_MISSING
**Reference:** outputs.headers.Document-ETag, status

6.2.2.55 Document-ETag invalid format
**Criterion:** Given a document-scope response, when `outputs.headers.Document-ETag` does not match the token schema, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_DOCUMENT_ETAG_INVALID_FORMAT
**Reference:** outputs.headers.Document-ETag, status

6.2.2.56 Document-ETag token mismatch
**Criterion:** Given a document-scope response, when `outputs.headers.Document-ETag` does not equal the current legacy token, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_DOCUMENT_ETAG_TOKEN_MISMATCH
**Reference:** outputs.headers.Document-ETag, status

6.2.2.57 X-List-ETag invalid format
**Criterion:** Given a reorder error response, when `outputs.headers.X-List-ETag` does not match the token schema, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_X_LIST_ETAG_INVALID_FORMAT
**Reference:** outputs.headers.X-List-ETag, status

6.2.2.58 X-List-ETag wrong context
**Criterion:** Given a non-reorder response, when `outputs.headers.X-List-ETag` is present, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_X_LIST_ETAG_WRONG_CONTEXT
**Reference:** outputs.headers.X-List-ETag, status

6.2.2.59 X-List-ETag token mismatch
**Criterion:** Given a reorder error response, when `outputs.headers.X-List-ETag` does not equal the legacy list token, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_X_LIST_ETAG_TOKEN_MISMATCH
**Reference:** outputs.headers.X-List-ETag, status

6.2.2.60 X-If-Match-Normalized invalid
**Criterion:** Given a reorder error response, when `outputs.headers.X-If-Match-Normalized` fails its schema, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_X_IF_MATCH_NORMALIZED_INVALID
**Reference:** outputs.headers.X-If-Match-Normalized, status

6.2.2.61 X-If-Match-Normalized wrong context
**Criterion:** Given a non-reorder response, when `outputs.headers.X-If-Match-Normalized` is present, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_X_IF_MATCH_NORMALIZED_WRONG_CONTEXT
**Reference:** outputs.headers.X-If-Match-Normalized, status

6.2.2.62 X-If-Match-Normalized mismatch
**Criterion:** Given a reorder error response, when `outputs.headers.X-If-Match-Normalized` does not reflect the normalised token list used, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_HEADERS_X_IF_MATCH_NORMALIZED_MISMATCH
**Reference:** outputs.headers.X-If-Match-Normalized, status

6.2.2.63 Body schema invalid
**Criterion:** Given any response, when `outputs.body` fails its fragment schema, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_BODY_SCHEMA_INVALID
**Reference:** outputs.body, status

6.2.2.64 Body mutated after emission
**Criterion:** Given any response, when `outputs.body` is mutated after emission, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_BODY_MUTATED_AFTER_EMISSION
**Reference:** outputs.body, status

6.2.2.65 screen_view.etag missing
**Criterion:** Given a screen GET that includes `screen_view`, when `outputs.body.screen_view.etag` is absent, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_BODY_SCREEN_VIEW_ETAG_MISSING
**Reference:** outputs.body.screen_view.etag, status

6.2.2.66 screen_view.etag invalid format
**Criterion:** Given a screen GET that includes `screen_view`, when `outputs.body.screen_view.etag` fails the token schema, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_BODY_SCREEN_VIEW_ETAG_INVALID_FORMAT
**Reference:** outputs.body.screen_view.etag, status

6.2.2.67 screen_view.etag mismatch header
**Criterion:** Given a screen GET, when `outputs.body.screen_view.etag` does not equal `outputs.headers.Screen-ETag`, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_BODY_SCREEN_VIEW_ETAG_MISMATCH_HEADER
**Reference:** outputs.body.screen_view.etag, outputs.headers.Screen-ETag, status

6.2.2.68 screen_view.etag inconsistent duplication
**Criterion:** Given a screen GET, when `outputs.body.screen_view.etag` is not consistent with the header within the same response, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_BODY_SCREEN_VIEW_ETAG_INCONSISTENT
**Reference:** outputs.body.screen_view.etag, outputs.headers.Screen-ETag, status

6.2.2.69 placeholders.etag missing
**Criterion:** Given a placeholders read that includes a body etag, when `outputs.body.placeholders.etag` is absent, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_BODY_PLACEHOLDERS_ETAG_MISSING
**Reference:** outputs.body.placeholders.etag, status

6.2.2.70 placeholders.etag invalid format
**Criterion:** Given a placeholders read that includes a body etag, when `outputs.body.placeholders.etag` fails the token schema, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_BODY_PLACEHOLDERS_ETAG_INVALID_FORMAT
**Reference:** outputs.body.placeholders.etag, status

6.2.2.71 placeholders.etag mismatch header
**Criterion:** Given a placeholders read that includes a body etag, when `outputs.body.placeholders.etag` does not equal `outputs.headers.ETag`, then the response is invalid and cannot be finalised.
**Error Mode:** POST_OUTPUTS_BODY_PLACEHOLDERS_ETAG_MISMATCH_HEADER
**Reference:** outputs.body.placeholders.etag, outputs.headers.ETag, status

6.2.2.72 Headers mapping contains undeclared key
Criterion: Given any response, when outputs.headers contains a key not declared in the outputs schema fragment, then the response is invalid and cannot be finalised.
Error Mode: POST_OUTPUTS_HEADERS_UNDECLARED_KEY_PRESENT
Reference: outputs.headers, status

6.2.2.73 Header value not a string
Criterion: Given any response, when any value in outputs.headers is not a string, then the response is invalid and cannot be finalised.
Error Mode: POST_OUTPUTS_HEADERS_VALUE_NOT_STRING
Reference: outputs.headers, status

6.2.2.74 Body contains undeclared key
Criterion: Given any response, when outputs.body contains a key not declared in the outputs schema fragment, then the response is invalid and cannot be finalised.
Error Mode: POST_OUTPUTS_BODY_UNDECLARED_KEY_PRESENT
Reference: outputs.body, status

6.2.2.75 CORS expose-headers misconfigured
Criterion: Given a response that should expose domain ETag headers, when Access-Control-Expose-Headers omits any required domain header (or ETag where applicable), then the response cannot be finalised for browser clients.
Error Mode: ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED
Reference: response.headers.Access-Control-Expose-Headers, outputs.headers, status

6.2.2.76 CORS allow-headers missing If-Match (preflight)
Criterion: Given an OPTIONS preflight to an in-scope write endpoint, when Access-Control-Allow-Headers does not include If-Match, then the browser write is blocked and no mutation occurs.
Error Mode: ENV_CORS_ALLOW_HEADERS_MISSING_IF_MATCH
Reference: response.headers.Access-Control-Allow-Headers, request.headers.If-Match, status

6.2.2.77 Upstream proxy strips If-Match
Criterion: Given a client write that includes If-Match, when an upstream proxy/gateway strips or renames the header so the guard observes it as missing, then the route responds as a missing-precondition error and no mutation occurs.
Error Mode: ENV_PROXY_STRIPS_IF_MATCH
Reference: request.headers.If-Match (as received by application), status

6.2.2.78 Upstream proxy strips domain ETag headers
Criterion: Given a response that includes domain ETag headers, when an upstream proxy removes those headers before the client receives them, then finalisation is blocked for contract compliance.
Error Mode: ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS
Reference: outputs.headers, response pipeline, status

6.2.2.79 Guard mounted on read endpoints (Phase-0)
Criterion: Given any GET/read endpoint in Phase-0, when the precondition guard is invoked (e.g., requiring If-Match), then this is treated as a configuration error; the request is rejected with a server error and no guard enforcement occurs.
Error Mode: ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS
Reference: route configuration, request.method=GET, status

6.2.2.80 Problem+JSON always includes a non-empty title
Given an error response is being constructed by the global handler for any 4xx or 5xx outcome, when the upstream exception or interim payload omits a title or provides a blank/non-string value, then set title to http.HTTPStatus(status).phrase and continue shaping Problem+JSON without changing status or headers beyond the global error-handling policy.
Reference: Standards; Behavior; Handler strategy; RFC7807 shaping in this epic.

6.2.2.81 Problem+JSON always includes a non-empty detail
Given an error response is being constructed by the global handler for any 4xx or 5xx outcome, when the upstream exception or interim payload omits detail or provides a blank/non-string value, then coerce detail to a safe non-sensitive default appropriate to the status and continue shaping Problem+JSON, avoiding stack traces or exception class names and without altering pass-through responses that already conform.
Reference: Standards; Behavior; Compatibility / Non-Goals; Handler strategy; RFC7807 shaping in this epic.

6.2.2.82 Upstream proxy strips If-Match

- Criterion: Given a client write that includes If-Match, when an upstream proxy/gateway strips or renames the header so the guard observes it as missing, then the route
responds as a missing-precondition error and no mutation occurs.
- Error Mode: ENV_PROXY_STRIPS_IF_MATCH
- Reference: request.headers.If-Match (as received by application), status

6.2.2.83 Upstream proxy strips domain ETag headers

- Criterion: Given a response that includes domain ETag headers, when an upstream proxy removes those headers before the client receives them, then finalisation is blocked for
contract compliance.
- Error Mode: ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS
- Reference: outputs.headers, response pipeline, status

6.2.2.84 Guard mounted on read endpoints (Phase-0)

- Criterion: Given any GET/read endpoint in Phase-0, when the precondition guard is invoked (e.g., requiring If-Match), then this is treated as a configuration error; the
request is rejected with a server error and no guard enforcement occurs.
- Error Mode: ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS
- Reference: route configuration, request.method=GET, status

6.2.2.85 Answers PATCH 409 conflict exposes refreshable tags

- Criterion: Given a PATCH to answers with a non-matching, well-formed If-Match token, when precondition enforcement returns a 409 conflict, then the response exposes both ETag
and Screen-ETag so the client can refresh state before retrying.
- Error Mode: POST_OUTPUTS_HEADERS_ETAG_MISSING_WHEN_REQUIRED, POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING
- Reference: outputs.headers.ETag, outputs.headers.Screen-ETag, Access-Control-Expose-Headers, status

6.2.2.86 Normalized-empty If-Match returns NO_VALID_TOKENS and exposes tags

- Criterion: Given a PATCH to answers where If-Match normalises to an empty token list (e.g., only commas/empty/weak-empty items), when the guard evaluates the precondition,
then the response is a conflict with code PRE_IF_MATCH_NO_VALID_TOKENS and exposes ETag and Screen-ETag.
- Error Mode: PRE_IF_MATCH_NO_VALID_TOKENS
- Reference: request.headers.If-Match (normalized tokens), outputs.headers.ETag, outputs.headers.Screen-ETag, status

6.2.2.87 Unsupported Content-Type validated before preconditions

- Criterion: Given a PATCH with an unsupported Content-Type for the route, when the request is evaluated, then media-type validation takes precedence and a 415 error is returned
without running If-Match enforcement.
- Error Mode: PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED
- Reference: request.headers.Content-Type, status

6.2.2.88 Documents reorder mismatch emits list diagnostics

- Criterion: Given a documents reorder PATCH with a stale/mismatched If-Match, when the precondition fails, then the response preserves the route’s mismatch status and emits
X-List-ETag and X-If-Match-Normalized diagnostic headers.
- Error Mode: PRE_IF_MATCH_ETAG_MISMATCH
- Reference: outputs.headers.X-List-ETag, outputs.headers.X-If-Match-Normalized, status

6.2.2.89 CORS exposes required ETag headers exactly once

- Criterion: Given any in-scope response that emits ETag and Screen-ETag, when observed by a browser client, then Access-Control-Expose-Headers contains both names exactly once
so the client can read them.
- Error Mode: ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED
- Reference: outputs.headers.Access-Control-Expose-Headers, outputs.headers.ETag, outputs.headers.Screen-ETag, status

# 6.2 Happy Path Contractual Acceptance Criteria

## 6.2.1.1 Runtime screen GET returns domain + generic tags (parity)
**Given** a runtime JSON GET for a screen, **when** the request succeeds, **then** the response includes both `Screen-ETag` and `ETag` headers and they carry the same value.  
**Reference:** EARS: E4, U9, U10; Outputs: meta.Screen-ETag, meta.ETag

## 6.2.1.2 Runtime screen GET includes body mirror (parity with header)
**Given** a runtime JSON GET for a screen, **when** the request succeeds, **then** the payload includes `screen_view.etag` and it equals the `Screen-ETag` header.  
**Reference:** EARS: E7, O3, U12; Outputs: body.screen_view.etag, meta.Screen-ETag

## 6.2.1.3 Runtime document GET returns domain + generic tags (parity)
**Given** a runtime JSON GET for a document, **when** the request succeeds, **then** the response includes `Document-ETag` and `ETag` headers with identical values.  
**Reference:** EARS: E4, U9, U10; Outputs: meta.Document-ETag, meta.ETag

## 6.2.1.4 Authoring JSON GET returns domain tag only
**Given** an authoring JSON GET (Epic G), **when** the request succeeds, **then** the response includes the resource’s domain ETag header and does not include the generic `ETag`.  
**Reference:** EARS: E5, U9, U10; Outputs: meta.Screen-ETag (or meta.Question-ETag)

## 6.2.1.5 Answers PATCH with valid If-Match emits fresh tags (screen scope)
**Given** a write to answers with a valid `If-Match` that matches the current tag, **when** the mutation succeeds, **then** the response includes `Screen-ETag` and `ETag` headers with the current legacy value.  
**Reference:** EARS: E1, E3, U11, U9, U10; Outputs: status, meta.Screen-ETag, meta.ETag

## 6.2.1.6 Answers PATCH (with body mirror) keeps header–body parity
**Given** a successful answers PATCH whose response includes `screen_view`, **when** the response is returned, **then** `body.screen_view.etag` equals the `Screen-ETag` header.  
**Reference:** EARS: E3, E7, O3, U12; Outputs: body.screen_view.etag, meta.Screen-ETag

## 6.2.1.7 Document write success emits domain + generic tags
**Given** a successful document write, **when** the response is returned, **then** the response includes `Document-ETag` and `ETag` headers with identical values.  
**Reference:** EARS: E2, E3, U9, U10, U11; Outputs: status, meta.Document-ETag, meta.ETag

## 6.2.1.8 Questionnaire CSV export emits questionnaire tag (parity with ETag)
**Given** a questionnaire CSV export, **when** the response is returned, **then** the response includes `Questionnaire-ETag` and `ETag` headers with the same value.  
**Reference:** EARS: E6, U9, U10; Outputs: status, meta.Questionnaire-ETag, meta.ETag

## 6.2.1.9 Placeholders GET returns body etag and generic header (parity)
**Given** a placeholders GET for a question, **when** the request succeeds, **then** the payload includes `placeholders.etag` and the response includes `ETag`, and these values are equal.  
**Reference:** EARS: S2, U12; Outputs: body.placeholders.etag, meta.ETag

## 6.2.1.10 Placeholders bind/unbind success emits generic tag only
**Given** a successful placeholders bind or unbind, **when** the response is returned, **then** the response includes the generic `ETag` header and does not include any domain ETag headers.  
**Reference:** EARS: S2; Outputs: status, meta.ETag

## 6.2.1.11 Authoring writes succeed without If-Match (Phase‑0)
**Given** an authoring write in Phase‑0 without `If-Match`, **when** the request is processed, **then** the response indicates success and includes the relevant domain ETag header, and does not include the generic `ETag`.  
**Reference:** EARS: S1, E5; Outputs: status, meta.Screen-ETag (or meta.Question-ETag)

## 6.2.1.12 Domain header matches resource scope on success
**Given** any successful response, **when** the resource scope is screen, question, questionnaire, or document, **then** the response uses the corresponding domain header name for that scope.  
**Reference:** EARS: U16; Outputs: meta.Screen-ETag, meta.Question-ETag, meta.Questionnaire-ETag, meta.Document-ETag

6.2.1.13 Answers POST with valid If-Match emits fresh tags (screen scope)

Given an answers POST with a valid If-Match matching the current tag, when the mutation succeeds, then the response includes Screen-ETag and ETag with the current legacy value.
Reference: EARS: E1, E3, U11, U9, U10 • Outputs: status, meta.Screen-ETag, meta.ETag

6.2.1.14 Answers DELETE with valid If-Match emits fresh tags (screen scope)

Given an answers DELETE with a valid If-Match, when the mutation succeeds, then the response includes Screen-ETag and ETag with the current legacy value (post-mutation).
Reference: EARS: E1, E3, U11, U9, U10 • Outputs: status, meta.Screen-ETag, meta.ETag

6.2.1.15 Document reorder success emits tags and omits diagnostics

Given a successful document reorder, when the response is returned, then it includes Document-ETag and ETag with identical values and does not include X-List-ETag nor X-If-Match-Normalized.
Reference: EARS: E2, E3, U11, U9, U10, O4 • Outputs: status, meta.Document-ETag, meta.ETag

6.2.1.16 Any-match semantics for multi-token If-Match (success path)

Given a write with If-Match containing multiple tokens, when at least one token equals the current tag, then the mutation succeeds and fresh tags are emitted per resource scope.
Reference: EARS: U1, U2, U3, U4, U5, U6, U7, E1/E2, U11 • Outputs: status, meta.*

6.2.1.17 Wildcard If-Match: * honoured where supported

Given a write to a route that accepts If-Match: *, when the resource-exists precondition passes, then the mutation succeeds and headers emit the current legacy tag(s).
Reference: EARS: O1, E1/E2, U11 • Outputs: status, meta.*

6.2.1.18 Runtime JSON responses expose emitted ETag headers via CORS

Given any successful in-scope runtime JSON response that emits domain and/or generic ETags, when read by a browser, then Access-Control-Expose-Headers lists those headers so they are readable.
Reference: EARS: U13, E4 • Outputs: meta.Access-Control-Expose-Headers, meta.*

6.2.1.19 Authoring JSON responses expose domain headers via CORS

Given any successful authoring JSON response, when it emits a domain header (no generic ETag in Phase-0), then Access-Control-Expose-Headers lists that domain header.
Reference: EARS: U13, E5 • Outputs: meta.Access-Control-Expose-Headers, meta.Screen-ETag or meta.Question-ETag

6.2.1.20 Non-JSON downloads emit tags; payload unchanged

Given a successful in-scope non-JSON download (e.g., CSV or other binary), when the response is returned, then the response includes the resource’s domain header and ETag with identical values (where applicable) and the payload bytes/Content-Type remain unchanged.
Reference: EARS: E6, U9, U10 • Outputs: status, meta.Questionnaire-ETag (or meta.Document-ETag), meta.ETag

6.2.1.21 Successful precondition check & emission are logged

Given any successful guarded write, when the request passes the guard and headers are emitted, then an etag.enforce event with matched:true and an etag.emit event are recorded.
Reference: EARS: U14, U15, E1/E2/E3 • Outputs: (telemetry) events.etag.enforce, events.etag.emit

6.2.1.22 Legacy token string preserved on success (parity)

Given an unchanged resource and request across builds, when a successful read returns tags, then the emitted legacy token string (including quoting and W/ strength) is exactly the same as before the refactor.
Reference: EARS: U8 • Outputs: meta.* (token value parity)

## 6.3.2.1
**Title:** CORS expose-headers misconfiguration blocks ETag visibility  
**Criterion:** Given a response ready for header emission (STEP-4 Header emission), when the CORS Access-Control-Expose-Headers configuration omits required ETag headers, then halt STEP-4 Header emission and stop propagation to response finalisation for client-visible meta headers, as required by the error mode’s Flow Impact.  
**Error Mode:** ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED  
**Reference:** Dependency: CORS/expose headers; Steps: STEP-4

6.3.2.2

Title: Logging sink unavailable during precondition check does not affect flow
Criterion: Given STEP-2 Precondition enforcement attempts to record an etag.enforce event, when the logging sink is unavailable, then the system proceeds without altering the response, mutation, or headers; only telemetry is degraded, as required by the error mode’s Flow Impact.
Error Mode: ENV_LOGGING_SINK_UNAVAILABLE_ENFORCE
Reference: Dependency: logging sink; Steps: STEP-2; EARS: U14

6.3.2.3

Title: Logging sink unavailable during header emission does not affect flow
Criterion: Given STEP-4 Header emission attempts to record an etag.emit event, when the logging sink is unavailable, then the system proceeds to finalisation with headers intact; only telemetry is degraded, as required by the error mode’s Flow Impact.
Error Mode: ENV_LOGGING_SINK_UNAVAILABLE_EMIT
Reference: Dependency: logging sink; Steps: STEP-4; EARS: U15

6.3.2.4

Title: Upstream proxy strips domain ETag headers (egress)
Criterion: Given STEP-4 Header emission has assembled domain ETag headers (and ETag where applicable), when the deployment environment or gateway policy is detected to strip those headers, then block finalisation for the response and surface an operational error per the error mode’s Flow Impact.
Error Mode: ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS
Reference: Dependency: API gateway/proxy egress policy; Steps: STEP-4; EARS: U9, U16, E3, E4, E5, E6

6.3.2.5

Title: CORS allow-headers does not permit If-Match on preflight
Criterion: Given an OPTIONS CORS preflight to an in-scope write endpoint (answers/documents), when Access-Control-Allow-Headers does not include If-Match, then treat the write as blocked for browser clients and halt the pipeline before STEP-2 (no guard, no mutation), as required by the error mode’s Flow Impact.
Error Mode: ENV_CORS_ALLOW_HEADERS_MISSING_IF_MATCH
Reference: Dependency: CORS/allow headers; Steps: STEP-2; EARS: E1, E2

6.3.2.6

Title: Upstream proxy strips If-Match (ingress)
Criterion: Given a write request sent with If-Match, when an upstream proxy removes or renames the header so the application receives no If-Match, then the guard responds with the contractually defined missing-precondition error (e.g., 428 with PRE_IF_MATCH_MISSING), no mutation occurs, and the pipeline halts at STEP-2, per the error mode’s Flow Impact.
Error Mode: ENV_PROXY_STRIPS_IF_MATCH
Reference: Dependency: API gateway/proxy ingress policy; Steps: STEP-2; EARS: E1, E2, U18

6.3.2.7

Title: Guard misapplied to read endpoints (Phase-0 scope breach)
Criterion: Given any GET/read endpoint during Phase-0, when the precondition guard is invoked (e.g., attempts to enforce If-Match), then treat this as a configuration error: halt the pipeline with a server error and do not emit domain or generic ETag headers, as required by the error mode’s Flow Impact.
Error Mode: ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS
Reference: Dependency: router/middleware wiring; Steps: STEP-2; EARS: S1, S4, E5

7.1.1 Shared If-Match normaliser exists and is single-source
Purpose: Verify that a single reusable normalisation utility is the only mechanism used to parse/normalise If-Match across in-scope routes.
Test Data: Project root (server codebase). Search scope: all source files. Target artefacts: any functions/utilities that parse or normalise the If-Match header.
Mocking: No mocking or stubbing is used. This is a static structural check over the real source tree; mocking would invalidate the result.
Assertions: (1) Exactly one module/function implements If-Match normalisation (single implementation in codebase); (2) All write-route guards import/use this utility; (3) No route or handler performs ad-hoc If-Match parsing.
AC-Ref: 6.1.1

7.1.2 Precondition guard implemented as discrete middleware
Purpose: Verify that precondition enforcement is implemented as a discrete middleware/guard component and not inlined in mutation handlers.
Test Data: Project root (server codebase). Search for route registration and middleware compositions for answers and documents write endpoints.
Mocking: No mocking; static inspection of route composition and handler source files.
Assertions: (1) A distinct guard/middleware unit is defined; (2) Mutation handlers contain no If-Match parsing/comparison logic; (3) Guard is referenced in route pipelines.
AC-Ref: 6.1.2

7.1.3 Guard mounted only on write routes (answers/documents)
Purpose: Ensure the precondition guard is mounted on answers/documents write endpoints and invoked before mutation handlers.
Test Data: Project root (server codebase). Route registration files for answers and document write endpoints.
Mocking: No mocking; static inspection of route registration order.
Assertions: (1) Guard is present on answers write routes; (2) Guard is present on document write routes; (3) Guard precedes the mutation handler in the pipeline.
AC-Ref: 6.1.3

7.1.4 Guard not mounted on authoring routes (Phase‑0)
Purpose: Ensure no authoring route registers the precondition guard during Phase‑0.
Test Data: Project root (server codebase). Route registration for authoring APIs (Epic G).
Mocking: No mocking; static inspection.
Assertions: (1) No authoring route imports the precondition guard; (2) No authoring route references the guard in its pipeline.
AC-Ref: 6.1.4

7.1.5 Central header‑emission utility is used
Purpose: Verify a single response‑header emitter sets domain ETag headers and generic ETag where applicable.
Test Data: Project root (server codebase). Source files for response assembly on in‑scope endpoints.
Mocking: Dynamic check with spies to observe delegation: wrap/export the emitter and assert callers invoke it during response assembly.
Assertions: (1) A single emitter module exists; (2) All in‑scope endpoints call the emitter; (3) No endpoint sets domain ETag/ETag headers directly.
AC-Ref: 6.1.5

7.1.6 Scope→header mapping centralised
Purpose: Verify mapping from resource scope to domain header name is declared once and reused by the emitter.
Test Data: Project root (server codebase). Emitter module and its dependencies.
Mocking: No mocking; static inspection of mapping definition and imports.
Assertions: (1) A central mapping of scopes→header names exists; (2) Emitter uses this mapping; (3) No hard‑coded domain header strings appear in callers.
AC-Ref: 6.1.6

7.1.7 CORS exposes required ETag headers
Purpose: Verify CORS configuration exposes Screen-ETag, Question-ETag, Questionnaire-ETag, Document-ETag, and ETag.
Test Data: Project root (server configuration). CORS configuration file or middleware initialiser.
Mocking: No mocking; static config inspection.
Assertions: (1) Access-Control-Expose-Headers includes all required header names; (2) No duplicates; (3) Configuration applies to in-scope routes.
AC-Ref: 6.1.7

7.1.8 Outputs schema declares canonical keys
Purpose: Verify canonical outputs schema declares top-level keys headers and body exactly.
Test Data: schemas/Outputs.schema.json (project root relative).
Mocking: No mocking; validate real schema file presence and structure.
Assertions: (1) File exists; (2) Schema defines properties.headers and properties.body; (3) No additional unexpected top-level required keys.
AC-Ref: 6.1.8

7.1.9 Outputs schema includes domain header fields
Purpose: Verify outputs.headers includes properties for Screen-ETag, Question-ETag, Questionnaire-ETag, Document-ETag, and ETag.
Test Data: schemas/Outputs.schema.json.
Mocking: No mocking; schema inspection.
Assertions: (1) properties.headers.properties contains the five domain keys; (2) Each property type matches token schema reference; (3) Requiredness matches contract.
AC-Ref: 6.1.9

7.1.10 No new body mirrors introduced
Purpose: Ensure no additional body mirrors (e.g., outputs.etags) are declared beyond those specified.
Test Data: Project root (server codebase) and schemas directory.
Mocking: No mocking; repository-wide search for “outputs.etags” and for new body mirror keys.
Assertions: (1) No schema or code defines outputs.etags; (2) No extra body mirrors beyond documented ones are present.
AC-Ref: 6.1.10

7.1.11 Screen body mirror retained
Purpose: Verify that screen_view.etag remains declared in schema and present in response assembly paths that include screen_view.
Test Data: schemas/Outputs.schema.json (body.screen_view.etag fragment) and server response assembly for screen GET/PATCH.
Mocking: Dynamic test with spy to ensure response composer reads/writes body.screen_view.etag when screen_view is included.
Assertions: (1) Schema contains body.screen_view.etag; (2) Response assembly includes body.screen_view.etag when screen_view is returned.
AC-Ref: 6.1.11

7.1.12 Diagnostic headers preserved for reorder
Purpose: Verify X-List-ETag and X-If-Match-Normalized remain emitted on document reorder responses.
Test Data: Server handler for document reorder error path; integration fixture triggering reorder precondition failure.
Mocking: Dynamic test using a simulated request causing reorder precondition failure; no stubbing of header emission.
Assertions: (1) Response includes X-List-ETag; (2) Response includes X-If-Match-Normalized; (3) Names match exactly; (4) Values are non-empty strings.
AC-Ref: 6.1.12

7.1.13 Token computation isolated and unchanged entry points
Purpose: Verify token retrieval/compute mechanism is isolated from normalisation/enforcement and exposes the same entry points.
Test Data: Project root (server codebase). Modules implementing tag retrieval/compute and the guard/normaliser.
Mocking: No mocking; static dependency inspection.
Assertions: (1) No dependency from normaliser/guard into token-compute internals (only stable interface use); (2) Public API surface of token-compute module unchanged (same exported function names/signatures).
AC-Ref: 6.1.13

7.1.14 OpenAPI responses declare domain headers
Purpose: Verify API specification declares relevant domain ETag headers (and ETag where applicable) on affected responses.
Test Data: Project OpenAPI specification file(s) (YAML/JSON) checked into the repo.
Mocking: No mocking; static spec inspection.
Assertions: (1) For runtime JSON GETs: headers include domain header and ETag; (2) For authoring JSON GETs: headers include domain header only; (3) For CSV export: headers include Questionnaire-ETag (and ETag).
AC-Ref: 6.1.14

7.1.15 CSV/non‑JSON uses the central header emitter
Purpose: Verify CSV export path uses the same header‑emission utility to set Questionnaire-ETag (and ETag where applicable).
Test Data: CSV export handler code path.
Mocking: Dynamic test with spy on the shared emitter to assert it is invoked during CSV response creation.
Assertions: (1) CSV path imports the emitter; (2) Emitter is called exactly once per response; (3) No direct header setting in CSV path.
AC-Ref: 6.1.15

7.1.16 Logging interface defines etag event types and is used
Purpose: Verify logging interface declares event types etag.enforce and etag.emit and that guard/emitter invoke them.
Test Data: Logging interface/module and usages in guard and emitter.
Mocking: Dynamic test with spy/fake logger to assert calls with event names etag.enforce and etag.emit.
Assertions: (1) Logger defines both event types; (2) Guard logs etag.enforce with matched:true|false; (3) Emitter logs etag.emit with route/scope context.
AC-Ref: 6.1.16

7.1.17 Guard not mounted on any GET/read endpoints
Purpose: Prove guard is excluded from all GET/read routes (runtime + authoring).
Test Data: Router wiring for every GET route.
Mocking: None; static inspection.
Assertions: (1) No GET pipeline references the guard; (2) Supplying If-Match on a GET does not invoke guard code paths (trace/log check).
AC-Ref: 6.1.17; EARS: S4, E5.

7.1.18 Guard is DB-free and import-safe
Purpose: Ensure the guard imports no repositories/DB drivers at module scope and can load without DB installed.
Test Data: Guard module; run import under env with DB libs removed.
Mocking: None.
Assertions: (1) No repo/driver imports at module scope; (2) Import succeeds; (3) Allowed ETag helpers imported lazily inside guard functions.
AC-Ref: 6.1.18; EARS: U19.

7.1.19 Handlers contain no inline precondition logic
Purpose: Enforce separation of concerns.
Test Data: All mutation handlers’ source.
Mocking: None.
Assertions: (1) No parsing/normalising/comparing If-Match; (2) No construction of precondition problem bodies.
AC-Ref: 6.1.19; EARS: U18.

7.1.20 Stable problem+json mapping for preconditions
Purpose: Centralised mapping from guard.
Test Data: Guard error mapping + one answers route (409/428) and one documents route (412/428).
Mocking: None.
Assertions: (1) Missing If-Match → 428 with code=PRE_IF_MATCH_MISSING; (2) Mismatch → route’s historic status (409 answers / 412 documents) with code=PRE_IF_MATCH_ETAG_MISMATCH; (3) Shapes invariant.
AC-Ref: 6.1.20; EARS: E8, E9.

7.1.21 OpenAPI declares If-Match as required on write routes
Purpose: Contract visibility in spec.
Test Data: OpenAPI document.
Mocking: None.
Assertions: (1) All in-scope writes declare If-Match as required header; (2) Error responses for 428 and 409/412 documented with stable codes.
AC-Ref: 6.1.21; EARS: U20.

7.1.22 Guard uses only public ETag APIs
Purpose: No coupling to internals.
Test Data: Guard imports + call sites.
Mocking: None.
Assertions: (1) Only app.logic.etag public helpers are referenced; (2) No private/import-path internals.
AC-Ref: 6.1.22.

7.1.23 Diagnostics emitted via central emitter
Purpose: Reorder diagnostics come from the shared header utility.
Test Data: Reorder failure path + emitter module.
Mocking: Spy on emitter; trigger reorder precondition fail.
Assertions: (1) Emitter invoked once; (2) X-List-ETag and optional X-If-Match-Normalized set by emitter, not handler.
AC-Ref: 6.1.23; EARS: O4, N7.

7.1.24 CORS allow-list includes If-Match
Purpose: Browsers can send If-Match.
Test Data: CORS config.
Mocking: None.
Assertions: Access-Control-Allow-Headers contains If-Match for in-scope writes.
AC-Ref: 6.1.24; EARS: E1, E2.

7.1.25 Guard failures include CORS headers
Purpose: Clients can read failure diagnostics.
Test Data: 428 + 409/412 responses from guard.
Mocking: None.
Assertions: CORS headers present on guard failures, including Access-Control-Expose-Headers (so diagnostics are visible).
AC-Ref: 6.1.25; EARS: U13.

7.1.26 No repository access before guard success
Purpose: Short-circuit ordering.
Test Data: Route pipelines + tracing.
Mocking: Repo spy to assert zero calls when guard fails 428/409/412.
Assertions: (1) No repo/DB access on guard failure; (2) Access only after guard success.
AC-Ref: 6.1.26; EARS: U18, U19.

7.1.27
Title: Guard file has no module-scope DB driver imports (static AST check)
Purpose: Prove that app/guards/precondition.py does not import psycopg2 (or submodules) at module scope, ensuring the guard is DB-free at import time.
Test Data: Source path: app/guards/precondition.py. Static analysis via AST of top-level Import/ImportFrom nodes. Denylist: psycopg2 (any submodule).
Mocking: None. This is a static structural inspection of the real file; mocking would invalidate the result.
Assertions: (1) No module-scope Import or ImportFrom references psycopg2 or any psycopg2.*; (2) If any such import exists, the test fails and reports offending line numbers; (3) No dynamic import disguises at module scope (e.g., __import__("psycopg2")).
AC-Ref: 6.1.18; EARS: U19.

7.1.28
Title: Guard file has no module-scope repository imports (static AST check)
Purpose: Ensure app/guards/precondition.py avoids importing repository layers at module scope, keeping the guard isolated from persistence concerns.
Test Data: Source path: app/guards/precondition.py. Static analysis via AST of top-level Import/ImportFrom nodes. Denylist pattern: app.logic.repository_* (any repo module).
Mocking: None. Static code inspection only.
Assertions: (1) No module-scope Import/ImportFrom targets any module matching app.logic.repository_*; (2) If any such import exists, the test fails and reports offending line numbers; (3) No indirect module-scope imports of repositories via wildcard or alias (e.g., from app.logic import repository_answers as repo).
AC-Ref: 6.1.18; EARS: U19.

7.2.1.1 Runtime screen GET returns domain + generic tags (parity)
Purpose: Verify that a runtime screen GET includes both Screen-ETag and ETag headers with identical values.
Test data: HTTP GET /api/v1/response-sets/rs_001/screens/welcome
Mocking: None. Exercise the live endpoint; no external boundaries mocked.
Assertions:
- Response HTTP status is 200.
- Header "Screen-ETag" exists and is a non-empty string.
- Header "ETag" exists and is a non-empty string.
- Header "Screen-ETag" equals header "ETag".
- Body is valid JSON (for this endpoint) and parseable.
AC-Ref: 6.2.1.1
EARS-Refs: E4, U9, U10

7.2.1.2 Runtime screen GET includes body mirror (parity with header)
Purpose: Verify that screen_view.etag in the body equals the Screen-ETag header on a successful screen GET.
Test data: HTTP GET /api/v1/response-sets/rs_001/screens/welcome
Mocking: None. Exercise the live endpoint; no external boundaries mocked.
Assertions:
- Response HTTP status is 200.
- Body JSON path "screen_view.etag" exists and is a non-empty string.
- Header "Screen-ETag" exists and is a non-empty string.
- Body "screen_view.etag" equals header "Screen-ETag".
AC-Ref: 6.2.1.2
EARS-Refs: E7, O3, U12

7.2.1.3 Runtime document GET returns domain + generic tags (parity)
Purpose: Verify that a runtime document GET includes both Document-ETag and ETag headers with identical values.
Test data: HTTP GET /api/v1/documents/doc_001
Mocking: None. Exercise the live endpoint; no external boundaries mocked.
Assertions:
- Response HTTP status is 200.
- Header "Document-ETag" exists and is a non-empty string.
- Header "ETag" exists and is a non-empty string.
- Header "Document-ETag" equals header "ETag".
AC-Ref: 6.2.1.3
EARS-Refs: E4, U9, U10

7.2.1.4 Authoring JSON GET returns domain tag only
Purpose: Verify that an authoring JSON GET includes the domain ETag header and omits the generic ETag header.
Test data: HTTP GET (Epic G authoring) for screen key "welcome" (exact path per Epic G)
Mocking: None. Exercise the live authoring endpoint; no external boundaries mocked.
Assertions:
- Response HTTP status is 200.
- Header "Screen-ETag" (or "Question-ETag" depending on resource) exists and is a non-empty string.
- Header "ETag" is absent.
AC-Ref: 6.2.1.4
EARS-Refs: E5, U9, U10

7.2.1.5 Answers PATCH with valid If-Match emits fresh tags (screen scope)
Purpose: Verify that a successful answers PATCH with a matching If-Match emits Screen-ETag and ETag and the tag changes from the pre-mutation value.
Test data:
- Baseline: GET /api/v1/response-sets/rs_001/screens/welcome → capture baseline_tag from header "ETag".
- Write: PATCH /api/v1/response-sets/rs_001/answers with body {"screen_key":"welcome","answers":[{"question_id":"q_001","value":"A"}]} and header If-Match: <baseline_tag>.
Mocking: None. Exercise live endpoints; no external boundaries mocked.
Assertions:
- PATCH response HTTP status is 200.
- Headers "Screen-ETag" and "ETag" exist and are non-empty strings.
- Header "Screen-ETag" equals header "ETag".
- Header "ETag" does not equal baseline_tag (fresh tag echoed).
AC-Ref: 6.2.1.5
EARS-Refs: E1, E3, U11, U9, U10

7.2.1.6 Answers PATCH (with body mirror) keeps header–body parity
Purpose: Verify that after a successful answers PATCH returning screen_view, the body mirror etag equals the Screen-ETag header.
Test data:
- PATCH /api/v1/response-sets/rs_001/answers with body {"screen_key":"welcome","answers":[{"question_id":"q_001","value":"B"}]} and header If-Match: W/"abc123"
Mocking: None. Exercise live endpoint; no external boundaries mocked.
Assertions:
- Response HTTP status is 200.
- Body JSON path "screen_view.etag" exists and is a non-empty string.
- Header "Screen-ETag" exists and is a non-empty string.
- Body "screen_view.etag" equals header "Screen-ETag".
AC-Ref: 6.2.1.6
EARS-Refs: E3, E7, O3, U12

7.2.1.7 Document write success emits domain + generic tags
Purpose: Verify that a successful document write emits Document-ETag and ETag with identical values.
Test data:
- PATCH /api/v1/documents/doc_001 with body {"title":"Revised"} and header If-Match: W/"docTag123"
Mocking: None. Exercise live endpoint; no external boundaries mocked.
Assertions:
- Response HTTP status is 200.
- Header "Document-ETag" exists and is a non-empty string.
- Header "ETag" exists and is a non-empty string.
- Header "Document-ETag" equals header "ETag".
AC-Ref: 6.2.1.7
EARS-Refs: E2, E3, U9, U10, U11

7.2.1.8 Questionnaire CSV export emits questionnaire tag (parity with ETag)
Purpose: Verify that questionnaire CSV export returns Questionnaire-ETag and ETag headers with the same value.
Test data: HTTP GET /api/v1/questionnaires/qq_001/export.csv
Mocking: None. Exercise live endpoint; no external boundaries mocked.
Assertions:
- Response HTTP status is 200.
- Header "Questionnaire-ETag" exists and is a non-empty string.
- Header "ETag" exists and is a non-empty string.
- Header "Questionnaire-ETag" equals header "ETag".
- Response Content-Type begins with "text/csv".
AC-Ref: 6.2.1.8
EARS-Refs: E6, U9, U10

7.2.1.9 Placeholders GET returns body etag and generic header (parity)
Purpose: Verify that placeholders GET returns both body etag and generic ETag header with equal values.
Test data: HTTP GET /api/v1/questions/q_123/placeholders
Mocking: None. Exercise live endpoint; no external boundaries mocked.
Assertions:
- Response HTTP status is 200.
- Body JSON path "placeholders.etag" exists and is a non-empty string.
- Header "ETag" exists and is a non-empty string.
- Body "placeholders.etag" equals header "ETag".
AC-Ref: 6.2.1.9
EARS-Refs: S2, U12

7.2.1.10 Placeholders bind/unbind success emits generic tag only
Purpose: Verify that placeholders bind/unbind success emits only the generic ETag and no domain headers.
Test data:
- POST /api/v1/placeholders/bind with body {"question_id":"q_123","placeholder_id":"ph_001"} and header If-Match: W/"phTag123"
Mocking: None. Exercise live endpoint; no external boundaries mocked.
Assertions:
- Response HTTP status is 200.
- Header "ETag" exists and is a non-empty string.
- Headers "Screen-ETag", "Question-ETag", "Questionnaire-ETag", and "Document-ETag" are all absent.
AC-Ref: 6.2.1.10
EARS-Refs: S2

7.2.1.11 Authoring writes succeed without If-Match (Phase‑0)
Purpose: Verify that authoring writes in Phase‑0 succeed without If-Match and emit the domain header only.
Test data: HTTP PATCH (Epic G authoring) to update screen "welcome" title to "Hello", no If-Match header
Mocking: None. Exercise live authoring endpoint; no external boundaries mocked.
Assertions:
- Response HTTP status is 200.
- Domain header appropriate to resource (e.g., "Screen-ETag" or "Question-ETag") exists and is a non-empty string.
- Header "ETag" is absent.
AC-Ref: 6.2.1.11
EARS-Refs: S1, E5

7.2.1.12 Domain header matches resource scope on success
Purpose: Verify that successful responses use the correct domain header name for the resource scope.
Test data:
- Screen GET: /api/v1/response-sets/rs_001/screens/welcome
- Question GET (authoring): (Epic G path per spec) for question_id "q_123"
- Questionnaire CSV: /api/v1/questionnaires/qq_001/export.csv
- Document GET: /api/v1/documents/doc_001
Mocking: None. Exercise live endpoints; no external boundaries mocked.
Assertions:
- Screen GET: header "Screen-ETag" present; headers "Question-ETag", "Questionnaire-ETag", "Document-ETag" absent.
- Question GET: header "Question-ETag" present; headers "Screen-ETag", "Questionnaire-ETag", "Document-ETag" absent.
- Questionnaire CSV: header "Questionnaire-ETag" present; headers "Screen-ETag", "Question-ETag", "Document-ETag" absent.
- Document GET: header "Document-ETag" present; headers "Screen-ETag", "Question-ETag", "Questionnaire-ETag" absent.
AC-Ref: 6.2.1.12
EARS-Refs: U16

7.2.1.13 CORS exposes domain headers on authoring reads

Purpose: Verify an authoring JSON GET exposes its domain header(s) via CORS in Access-Control-Expose-Headers (no generic ETag).
Test data: GET /api/v1/authoring/screens/welcome (Epic G path), no special headers.
Mocking: None — exercise the live authoring endpoint.
Assertions:

Status is 200.

Header Screen-ETag (or Question-ETag, depending on resource) exists and is a non-empty string.

Header ETag is absent.

Header Access-Control-Expose-Headers exists and (case-insensitively) includes the emitted domain header name (e.g., contains screen-etag when Screen-ETag is present).
AC-Ref: 6.2.1.14
EARS-Refs: U13, E5

7.2.1.14 CORS exposes Questionnaire-ETag on CSV export

Purpose: Verify questionnaire CSV export exposes Questionnaire-ETag (and ETag if emitted) via Access-Control-Expose-Headers.
Test data: GET /api/v1/questionnaires/qq_001/export.csv.
Mocking: None — exercise the live CSV export endpoint.
Assertions:

Status is 200.

Content-Type starts with text/csv.

Headers Questionnaire-ETag and ETag exist and are non-empty strings, and are equal.

Header Access-Control-Expose-Headers exists and (case-insensitively) includes questionnaire-etag and etag.
AC-Ref: 6.2.1.15
EARS-Refs: U13, E6, U9, U10

7.2.1.15 Preflight allows If-Match on write routes

Purpose: Verify CORS preflight for in-scope write endpoints allows the If-Match request header.
Test data:
Preflight request to answers write endpoint (e.g., /api/v1/response-sets/rs_001/answers):

Method: OPTIONS

Headers:

Origin: https://app.example.test

Access-Control-Request-Method: PATCH

Access-Control-Request-Headers: If-Match, Content-Type
Mocking: None — send a real preflight request.
Assertions:

Status is 204 (or the route’s preflight success status).

Header Access-Control-Allow-Methods includes PATCH.

Header Access-Control-Allow-Headers (case-insensitive parsing) includes if-match and content-type.

(Negative control in same test): preflight to an authoring GET route should still succeed but need not include if-match.
AC-Ref: 6.2.1.16
EARS-Refs: E1, E2, U13

# 7.2.2 Sad Path Contractual Tests (Complete)

**ID**: 7.2.2.1
**Title**: Sad path #01 for AC 6.2.2.1
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.1 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_IF_MATCH_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.1
**Error Mode**: PRE_IF_MATCH_MISSING

---

**ID**: 7.2.2.2
**Title**: Sad path #02 for AC 6.2.2.2
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.2 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_IF_MATCH_INVALID_FORMAT` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.2
**Error Mode**: PRE_IF_MATCH_INVALID_FORMAT

---

**ID**: 7.2.2.3
**Title**: Sad path #03 for AC 6.2.2.3
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.3 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_IF_MATCH_NO_VALID_TOKENS` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.3
**Error Mode**: PRE_IF_MATCH_NO_VALID_TOKENS

---

**ID**: 7.2.2.4
**Title**: Sad path #04 for AC 6.2.2.4
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.4 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_AUTHORIZATION_HEADER_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.4
**Error Mode**: PRE_AUTHORIZATION_HEADER_MISSING

---

**ID**: 7.2.2.5
**Title**: Sad path #05 for AC 6.2.2.5
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.5 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_REQUEST_BODY_INVALID_JSON` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.5
**Error Mode**: PRE_REQUEST_BODY_INVALID_JSON

---

**ID**: 7.2.2.6
**Title**: Sad path #06 for AC 6.2.2.6
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.6 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_REQUEST_BODY_SCHEMA_MISMATCH` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.6
**Error Mode**: PRE_REQUEST_BODY_SCHEMA_MISMATCH

---

**ID**: 7.2.2.7
**Title**: Sad path #07 for AC 6.2.2.7
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.7 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_PATH_PARAM_INVALID` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.7
**Error Mode**: PRE_PATH_PARAM_INVALID

---

**ID**: 7.2.2.8
**Title**: Sad path #08 for AC 6.2.2.8
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.8 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_QUERY_PARAM_INVALID` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.8
**Error Mode**: PRE_QUERY_PARAM_INVALID

---

**ID**: 7.2.2.9
**Title**: Sad path #09 for AC 6.2.2.9
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.9 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_RESOURCE_NOT_FOUND` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.9
**Error Mode**: PRE_RESOURCE_NOT_FOUND

---

**ID**: 7.2.2.10
**Title**: Sad path #10 for AC 6.2.2.10
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.10 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_IF_MATCH_NORMALIZATION_ERROR` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.10
**Error Mode**: RUN_IF_MATCH_NORMALIZATION_ERROR

---

**ID**: 7.2.2.11
**Title**: Sad path #11 for AC 6.2.2.11
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.11 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_PRECONDITION_CHECK_MISORDERED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.11
**Error Mode**: RUN_PRECONDITION_CHECK_MISORDERED

---

**ID**: 7.2.2.12
**Title**: Sad path #12 for AC 6.2.2.12
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.12 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_CONCURRENCY_CHECK_FAILED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.12
**Error Mode**: RUN_CONCURRENCY_CHECK_FAILED

---

**ID**: 7.2.2.13
**Title**: Sad path #13 for AC 6.2.2.13
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.13 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_DOMAIN_HEADER_EMISSION_FAILED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.13
**Error Mode**: RUN_DOMAIN_HEADER_EMISSION_FAILED

---

**ID**: 7.2.2.14
**Title**: Sad path #14 for AC 6.2.2.14
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.14 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_SCREEN_VIEW_MISSING_IN_BODY` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.14
**Error Mode**: RUN_SCREEN_VIEW_MISSING_IN_BODY

---

**ID**: 7.2.2.15
**Title**: Sad path #15 for AC 6.2.2.15
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.15 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_ETAG_PARITY_CALCULATION_FAILED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.15
**Error Mode**: RUN_ETAG_PARITY_CALCULATION_FAILED

---

**ID**: 7.2.2.16
**Title**: Sad path #16 for AC 6.2.2.16
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.16 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_SCREEN_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.16
**Error Mode**: POST_META_SCREEN_ETAG_MISSING

---

**ID**: 7.2.2.17
**Title**: Sad path #17 for AC 6.2.2.17
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.17 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.17
**Error Mode**: POST_META_ETAG_MISSING

---

**ID**: 7.2.2.18
**Title**: Sad path #18 for AC 6.2.2.18
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.18 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_DOCUMENT_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.18
**Error Mode**: POST_META_DOCUMENT_ETAG_MISSING

---

**ID**: 7.2.2.19
**Title**: Sad path #19 for AC 6.2.2.19
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.19 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_QUESTIONNAIRE_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.19
**Error Mode**: POST_META_QUESTIONNAIRE_ETAG_MISSING

---

**ID**: 7.2.2.20
**Title**: Sad path #20 for AC 6.2.2.20
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.20 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_HEADER_BODY_ETAG_MISMATCH` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.20
**Error Mode**: POST_HEADER_BODY_ETAG_MISMATCH

---

**ID**: 7.2.2.21
**Title**: Sad path #21 for AC 6.2.2.21
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.21 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_OUTPUTS_SCHEMA_MISMATCH` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.21
**Error Mode**: POST_OUTPUTS_SCHEMA_MISMATCH

---

**ID**: 7.2.2.22
**Title**: Sad path #22 for AC 6.2.2.22
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.22 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_BODY_SCREEN_VIEW_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.22
**Error Mode**: POST_BODY_SCREEN_VIEW_ETAG_MISSING

---

**ID**: 7.2.2.23
**Title**: Sad path #23 for AC 6.2.2.23
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.23 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_BINARY_CONTENT_TYPE_CHANGED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.23
**Error Mode**: POST_BINARY_CONTENT_TYPE_CHANGED

---

**ID**: 7.2.2.24
**Title**: Sad path #24 for AC 6.2.2.24
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.24 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_DIAGNOSTIC_HEADERS_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.24
**Error Mode**: POST_DIAGNOSTIC_HEADERS_MISSING

---

**ID**: 7.2.2.25
**Title**: Sad path #25 for AC 6.2.2.25
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.25 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_IF_MATCH_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.25
**Error Mode**: PRE_IF_MATCH_MISSING

---

**ID**: 7.2.2.26
**Title**: Sad path #26 for AC 6.2.2.26
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.26 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_IF_MATCH_INVALID_FORMAT` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.26
**Error Mode**: PRE_IF_MATCH_INVALID_FORMAT

---

**ID**: 7.2.2.27
**Title**: Sad path #27 for AC 6.2.2.27
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.27 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_IF_MATCH_NO_VALID_TOKENS` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.27
**Error Mode**: PRE_IF_MATCH_NO_VALID_TOKENS

---

**ID**: 7.2.2.28
**Title**: Sad path #28 for AC 6.2.2.28
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.28 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_AUTHORIZATION_HEADER_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.28
**Error Mode**: PRE_AUTHORIZATION_HEADER_MISSING

---

**ID**: 7.2.2.29
**Title**: Sad path #29 for AC 6.2.2.29
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.29 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_REQUEST_BODY_INVALID_JSON` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.29
**Error Mode**: PRE_REQUEST_BODY_INVALID_JSON

---

**ID**: 7.2.2.30
**Title**: Sad path #30 for AC 6.2.2.30
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.30 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_REQUEST_BODY_SCHEMA_MISMATCH` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.30
**Error Mode**: PRE_REQUEST_BODY_SCHEMA_MISMATCH

---

**ID**: 7.2.2.31
**Title**: Sad path #31 for AC 6.2.2.31
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.31 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_PATH_PARAM_INVALID` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.31
**Error Mode**: PRE_PATH_PARAM_INVALID

---

**ID**: 7.2.2.32
**Title**: Sad path #32 for AC 6.2.2.32
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.32 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_QUERY_PARAM_INVALID` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.32
**Error Mode**: PRE_QUERY_PARAM_INVALID

---

**ID**: 7.2.2.33
**Title**: Sad path #33 for AC 6.2.2.33
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.33 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_RESOURCE_NOT_FOUND` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.33
**Error Mode**: PRE_RESOURCE_NOT_FOUND

---

**ID**: 7.2.2.34
**Title**: Sad path #34 for AC 6.2.2.34
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.34 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_IF_MATCH_NORMALIZATION_ERROR` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.34
**Error Mode**: RUN_IF_MATCH_NORMALIZATION_ERROR

---

**ID**: 7.2.2.35
**Title**: Sad path #35 for AC 6.2.2.35
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.35 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_PRECONDITION_CHECK_MISORDERED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.35
**Error Mode**: RUN_PRECONDITION_CHECK_MISORDERED

---

**ID**: 7.2.2.36
**Title**: Sad path #36 for AC 6.2.2.36
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.36 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_CONCURRENCY_CHECK_FAILED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.36
**Error Mode**: RUN_CONCURRENCY_CHECK_FAILED

---

**ID**: 7.2.2.37
**Title**: Sad path #37 for AC 6.2.2.37
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.37 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_DOMAIN_HEADER_EMISSION_FAILED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.37
**Error Mode**: RUN_DOMAIN_HEADER_EMISSION_FAILED

---

**ID**: 7.2.2.38
**Title**: Sad path #38 for AC 6.2.2.38
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.38 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_SCREEN_VIEW_MISSING_IN_BODY` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.38
**Error Mode**: RUN_SCREEN_VIEW_MISSING_IN_BODY

---

**ID**: 7.2.2.39
**Title**: Sad path #39 for AC 6.2.2.39
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.39 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_ETAG_PARITY_CALCULATION_FAILED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.39
**Error Mode**: RUN_ETAG_PARITY_CALCULATION_FAILED

---

**ID**: 7.2.2.40
**Title**: Sad path #40 for AC 6.2.2.40
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.40 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_SCREEN_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.40
**Error Mode**: POST_META_SCREEN_ETAG_MISSING

---

**ID**: 7.2.2.41
**Title**: Sad path #41 for AC 6.2.2.41
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.41 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.41
**Error Mode**: POST_META_ETAG_MISSING

---

**ID**: 7.2.2.42
**Title**: Sad path #42 for AC 6.2.2.42
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.42 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_DOCUMENT_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.42
**Error Mode**: POST_META_DOCUMENT_ETAG_MISSING

---

**ID**: 7.2.2.43
**Title**: Sad path #43 for AC 6.2.2.43
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.43 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_QUESTIONNAIRE_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.43
**Error Mode**: POST_META_QUESTIONNAIRE_ETAG_MISSING

---

**ID**: 7.2.2.44
**Title**: Sad path #44 for AC 6.2.2.44
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.44 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_HEADER_BODY_ETAG_MISMATCH` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.44
**Error Mode**: POST_HEADER_BODY_ETAG_MISMATCH

---

**ID**: 7.2.2.45
**Title**: Sad path #45 for AC 6.2.2.45
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.45 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_OUTPUTS_SCHEMA_MISMATCH` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.45
**Error Mode**: POST_OUTPUTS_SCHEMA_MISMATCH

---

**ID**: 7.2.2.46
**Title**: Sad path #46 for AC 6.2.2.46
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.46 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_BODY_SCREEN_VIEW_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.46
**Error Mode**: POST_BODY_SCREEN_VIEW_ETAG_MISSING

---

**ID**: 7.2.2.47
**Title**: Sad path #47 for AC 6.2.2.47
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.47 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_BINARY_CONTENT_TYPE_CHANGED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.47
**Error Mode**: POST_BINARY_CONTENT_TYPE_CHANGED

---

**ID**: 7.2.2.48
**Title**: Sad path #48 for AC 6.2.2.48
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.48 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_DIAGNOSTIC_HEADERS_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.48
**Error Mode**: POST_DIAGNOSTIC_HEADERS_MISSING

---

**ID**: 7.2.2.49
**Title**: Sad path #49 for AC 6.2.2.49
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.49 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_IF_MATCH_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.49
**Error Mode**: PRE_IF_MATCH_MISSING

---

**ID**: 7.2.2.50
**Title**: Sad path #50 for AC 6.2.2.50
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.50 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_IF_MATCH_INVALID_FORMAT` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.50
**Error Mode**: PRE_IF_MATCH_INVALID_FORMAT

---

**ID**: 7.2.2.51
**Title**: Sad path #51 for AC 6.2.2.51
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.51 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_IF_MATCH_NO_VALID_TOKENS` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.51
**Error Mode**: PRE_IF_MATCH_NO_VALID_TOKENS

---

**ID**: 7.2.2.52
**Title**: Sad path #52 for AC 6.2.2.52
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.52 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_AUTHORIZATION_HEADER_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.52
**Error Mode**: PRE_AUTHORIZATION_HEADER_MISSING

---

**ID**: 7.2.2.53
**Title**: Sad path #53 for AC 6.2.2.53
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.53 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_REQUEST_BODY_INVALID_JSON` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.53
**Error Mode**: PRE_REQUEST_BODY_INVALID_JSON

---

**ID**: 7.2.2.54
**Title**: Sad path #54 for AC 6.2.2.54
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.54 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_REQUEST_BODY_SCHEMA_MISMATCH` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.54
**Error Mode**: PRE_REQUEST_BODY_SCHEMA_MISMATCH

---

**ID**: 7.2.2.55
**Title**: Sad path #55 for AC 6.2.2.55
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.55 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_PATH_PARAM_INVALID` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.55
**Error Mode**: PRE_PATH_PARAM_INVALID

---

**ID**: 7.2.2.56
**Title**: Sad path #56 for AC 6.2.2.56
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.56 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_QUERY_PARAM_INVALID` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.56
**Error Mode**: PRE_QUERY_PARAM_INVALID

---

**ID**: 7.2.2.57
**Title**: Sad path #57 for AC 6.2.2.57
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.57 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `PRE_RESOURCE_NOT_FOUND` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.57
**Error Mode**: PRE_RESOURCE_NOT_FOUND

---

**ID**: 7.2.2.58
**Title**: Sad path #58 for AC 6.2.2.58
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.58 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_IF_MATCH_NORMALIZATION_ERROR` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.58
**Error Mode**: RUN_IF_MATCH_NORMALIZATION_ERROR

---

**ID**: 7.2.2.59
**Title**: Sad path #59 for AC 6.2.2.59
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.59 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_PRECONDITION_CHECK_MISORDERED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.59
**Error Mode**: RUN_PRECONDITION_CHECK_MISORDERED

---

**ID**: 7.2.2.60
**Title**: Sad path #60 for AC 6.2.2.60
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.60 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_CONCURRENCY_CHECK_FAILED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.60
**Error Mode**: RUN_CONCURRENCY_CHECK_FAILED

---

**ID**: 7.2.2.61
**Title**: Sad path #61 for AC 6.2.2.61
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.61 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_DOMAIN_HEADER_EMISSION_FAILED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.61
**Error Mode**: RUN_DOMAIN_HEADER_EMISSION_FAILED

---

**ID**: 7.2.2.62
**Title**: Sad path #62 for AC 6.2.2.62
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.62 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_SCREEN_VIEW_MISSING_IN_BODY` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.62
**Error Mode**: RUN_SCREEN_VIEW_MISSING_IN_BODY

---

**ID**: 7.2.2.63
**Title**: Sad path #63 for AC 6.2.2.63
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.63 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `RUN_ETAG_PARITY_CALCULATION_FAILED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.63
**Error Mode**: RUN_ETAG_PARITY_CALCULATION_FAILED

---

**ID**: 7.2.2.64
**Title**: Sad path #64 for AC 6.2.2.64
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.64 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_SCREEN_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.64
**Error Mode**: POST_META_SCREEN_ETAG_MISSING

---

**ID**: 7.2.2.65
**Title**: Sad path #65 for AC 6.2.2.65
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.65 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.65
**Error Mode**: POST_META_ETAG_MISSING

---

**ID**: 7.2.2.66
**Title**: Sad path #66 for AC 6.2.2.66
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.66 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_DOCUMENT_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.66
**Error Mode**: POST_META_DOCUMENT_ETAG_MISSING

---

**ID**: 7.2.2.67
**Title**: Sad path #67 for AC 6.2.2.67
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.67 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_META_QUESTIONNAIRE_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.67
**Error Mode**: POST_META_QUESTIONNAIRE_ETAG_MISSING

---

**ID**: 7.2.2.68
**Title**: Sad path #68 for AC 6.2.2.68
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.68 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_HEADER_BODY_ETAG_MISMATCH` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.68
**Error Mode**: POST_HEADER_BODY_ETAG_MISMATCH

---

**ID**: 7.2.2.69
**Title**: Sad path #69 for AC 6.2.2.69
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.69 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_OUTPUTS_SCHEMA_MISMATCH` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.69
**Error Mode**: POST_OUTPUTS_SCHEMA_MISMATCH

---

**ID**: 7.2.2.70
**Title**: Sad path #70 for AC 6.2.2.70
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.70 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: W/"stale-tag"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_BODY_SCREEN_VIEW_ETAG_MISSING` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.70
**Error Mode**: POST_BODY_SCREEN_VIEW_ETAG_MISSING

---

**ID**: 7.2.2.71
**Title**: Sad path #71 for AC 6.2.2.71
**Purpose**: Verify contractual failure behaviour aligned to AC 6.2.2.71 with explicit error surface and externally observable contract.
**Test Data**: 
- HTTP method: PATCH
- URL: /api/v1/response-sets/resp_123/answers/q_456
- Headers: Authorization: Bearer dev-token; If-Match: "invalid"
- Body (JSON): { "value": "X" }
**Mocking**: 
- Mock persistence layer at the repository boundary to simulate the specific failure: return current tag 'W/"fresh-tag"' when asked; raise exceptions only where the error mode implies runtime failure; otherwise let real validation execute.
- Assert repository mock is invoked with question_id "q_456" and response_set_id "resp_123".
- Do not mock request normalisation or ETag comparison logic; execute real code to exercise contract surfaces.
**Assertions**:
- Status code equals one of 409, 412, or 428 as defined by contract for this AC.
- Response meta includes stable `request_id` and non-negative `latency_ms` when applicable.
- Error payload includes `code` equal to `POST_BINARY_CONTENT_TYPE_CHANGED` and a human-readable `message` mentioning the failing precondition or parity surface.
- No `output` field is present when `status = "error"`.
**AC-Ref**: 6.2.2.71
**Error Mode**: POST_BINARY_CONTENT_TYPE_CHANGED

---

**ID**: 7.2.2.72
**Title**: Outputs.headers contains an undeclared key (screen GET)
**Purpose**: Verify the response is rejected when `outputs.headers` includes a key not declared by the headers fragment schema.
**Test Data**:

* HTTP method: GET
* URL: `/api/v1/screens/scr_001`
* Request headers: `Authorization: Bearer dev-token`
  **Mocking**:
* Mock the **response finalisation layer** at the boundary (header composer) to add an extra header key `X-Random-Header: "foo"` that is **not** declared in the outputs schema fragment.
* Do **not** mock controller/handler logic; exercise real code through public HTTP entrypoint.
* Assert the header composer mock was invoked exactly once and injected `X-Random-Header` with value `"foo"`.
  **Assertions**:
* Status code: **500 Internal Server Error**.
* Problem JSON: `code = "POST_OUTPUTS_HEADERS_UNDECLARED_KEY_PRESENT"` with a message mentioning `outputs.headers` and the offending key name.
* No mutation/persistence calls made (it’s a GET).
  **AC-Ref**: 6.2.2.72
  **Error Mode**: POST_OUTPUTS_HEADERS_UNDECLARED_KEY_PRESENT

---

**ID**: 7.2.2.73
**Title**: Header value not a string (Screen-ETag numeric)
**Purpose**: Verify the response is rejected when any value in `outputs.headers` is not a string.
**Test Data**:

* HTTP method: GET
* URL: `/api/v1/screens/scr_002`
* Request headers: `Authorization: Bearer dev-token`
  **Mocking**:
* Mock the **header composer** to set `Screen-ETag: 12345` (number, not string) and a valid `ETag: "W/\"abc\""` string.
* Assert the mock was called with `Screen-ETag` value **as a number**.
  **Assertions**:
* Status code: **500 Internal Server Error**.
* Problem JSON: `code = "POST_OUTPUTS_HEADERS_VALUE_NOT_STRING"` and message indicating `Screen-ETag` is not a string.
* No persistence calls (GET).
  **AC-Ref**: 6.2.2.73
  **Error Mode**: POST_OUTPUTS_HEADERS_VALUE_NOT_STRING

---

**ID**: 7.2.2.74
**Title**: outputs.body contains undeclared key (spurious `etags` field)
**Purpose**: Ensure responses are rejected when `outputs.body` contains an undeclared property.
**Test Data**:

* HTTP method: GET
* URL: `/api/v1/screens/scr_003`
* Request headers: `Authorization: Bearer dev-token`
  **Mocking**:
* Mock the **body serializer** at the boundary to inject `outputs.body.etags = { "Screen-ETag": "W/\"abc\"" }` (undeclared).
* Assert serializer mock was called and produced the extra key.
  **Assertions**:
* Status code: **500 Internal Server Error**.
* Problem JSON: `code = "POST_OUTPUTS_BODY_UNDECLARED_KEY_PRESENT"` and message naming `body.etags`.
* No persistence calls (GET).
  **AC-Ref**: 6.2.2.74
  **Error Mode**: POST_OUTPUTS_BODY_UNDECLARED_KEY_PRESENT

---

**ID**: 7.2.2.75
**Title**: CORS expose-headers omits required domain headers
**Purpose**: Block finalisation when `Access-Control-Expose-Headers` does not expose required ETag/domain headers.
**Test Data**:

* HTTP method: GET
* URL: `/api/v1/screens/scr_004`
* Request headers: `Authorization: Bearer dev-token`, `Origin: https://example.app`
  **Mocking**:
* Mock the **CORS middleware config provider** to return `Access-Control-Expose-Headers: ETag` (omits `Screen-ETag`).
* Do not mock handler; allow normal header emission (handler sets `ETag` and `Screen-ETag`).
* Assert CORS provider mock used exactly once for this response.
  **Assertions**:
* Status code: **500 Internal Server Error** (response not finalised for browser clients).
* Problem JSON: `code = "ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED"`.
* Response must **not** be a 2xx; verify that no cacheable output is sent.
  **AC-Ref**: 6.2.2.75
  **Error Mode**: ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED

---

**ID**: 7.2.2.76
**Title**: CORS preflight missing `If-Match` in `Access-Control-Allow-Headers`
**Purpose**: Ensure misconfigured preflight blocks browser writes (no mutation).
**Test Data**:

* Step A — Preflight

  * HTTP method: OPTIONS
  * URL: `/api/v1/response-sets/resp_123/answers/q_456`
  * Request headers:

    * `Origin: https://example.app`
    * `Access-Control-Request-Method: PATCH`
    * `Access-Control-Request-Headers: if-match, authorization, content-type`
* Step B — (No actual browser PATCH occurs due to failed preflight; test harness does not send it.)
  **Mocking**:
* Mock the **CORS middleware config provider** to produce `Access-Control-Allow-Headers: authorization, content-type` (omits `If-Match`).
* Assert provider mock invoked once for OPTIONS.
* Spy the **answers repository** to ensure it is never called (no mutation).
  **Assertions**:
* OPTIONS response status: **500 Internal Server Error** (preflight cannot be satisfied).
* Problem JSON: `code = "ENV_CORS_ALLOW_HEADERS_MISSING_IF_MATCH"`.
* Verify the answers repository spy recorded **zero calls**.
  **AC-Ref**: 6.2.2.76
  **Error Mode**: ENV_CORS_ALLOW_HEADERS_MISSING_IF_MATCH

---

**ID**: 7.2.2.77
**Title**: Upstream proxy strips `If-Match` en route to app
**Purpose**: Treat a stripped `If-Match` as a missing-precondition scenario caused by the environment; no mutation allowed.
**Test Data**:

* Client-intended request (for traceability only): PATCH `/api/v1/response-sets/resp_123/answers/q_456` with `If-Match: W/"fresh-tag"` and body `{ "value": "X" }`.
* **Actual app-received** request (after proxy): same URL and body, but **no** `If-Match` header.
  **Mocking**:
* Mock the **edge gateway adapter** (boundary) to drop `If-Match` from the inbound headers before they reach the app.
* Assert adapter saw the client header and removed it (record original vs forwarded headers).
* Spy the **answers repository** to prove no mutation occurs.
  **Assertions**:
* App response status: **428 Precondition Required**.
* Problem JSON: `code = "PRE_REQUEST_HEADERS_IF_MATCH_MISSING"` (proxied cause), and **an environment diagnostic log/metric** tagged with `ENV_PROXY_STRIPS_IF_MATCH`.
* Repository spy: **zero calls**.
  **AC-Ref**: 6.2.2.77
  **Error Mode**: ENV_PROXY_STRIPS_IF_MATCH

---

**ID**: 7.2.2.78
**Title**: Upstream proxy strips domain ETag headers from success response
**Purpose**: Block finalisation when required domain headers are removed by a proxy.
**Test Data**:

* HTTP method: PATCH
* URL: `/api/v1/screens/scr_789`
* Request headers: `Authorization: Bearer dev-token; If-Match: W/"fresh-tag"`
* Body: `{ "title": "New Title" }`
  **Mocking**:
* Allow normal mutation and header emission in the app (it sets both `ETag` and `Screen-ETag`).
* Mock the **edge gateway response filter** to remove `Screen-ETag` (and optionally `ETag`) from the outgoing response.
* Assert the filter was invoked and stripped those headers.
  **Assertions**:
* Finalised response status observed by the client is **500 Internal Server Error** (contract cannot be satisfied).
* Problem JSON: `code = "ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS"`.
* Verify the app attempted to emit both headers prior to gateway filtering (via server-side log/spy).
  **AC-Ref**: 6.2.2.78
  **Error Mode**: ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS

---

**ID**: 7.2.2.79
**Title**: Guard misapplied to a read (GET) endpoint
**Purpose**: Misconfiguration: precondition guard mounted on a GET route must be treated as an environment/config error.
**Test Data**:

* HTTP method: GET
* URL: `/api/v1/screens/scr_555`
* Request headers: `Authorization: Bearer dev-token` (no `If-Match`, as reads don’t require it).
  **Mocking**:
* Mock **route wiring** (dependency injection) to mount `precondition_guard` on this GET route.
* Assert the guard was called on this GET request.
* Do **not** mock handler; it should not run due to misconfiguration failure.
  **Assertions**:
* Status code: **500 Internal Server Error** (guard misapplied).
* Problem JSON: `code = "ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS"`.
* Assert the real GET handler was **not** invoked and no persistence calls were made.
  **AC-Ref**: 6.2.2.79
  **Error Mode**: ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS

7.2.2.80 Problem+JSON title is present and surfaced to the user (404)
Purpose: Verify that when a request fails with a 404 and the Problem+JSON body arrives, the client surfaces a non-empty title string from the response (fallback to HTTPStatus phrase if needed), without navigating away or leaking secrets.
Test Data:
• Initial route: `/documents/view?docId=missing`
• User action: App auto-loads document on mount (no extra clicks)
• Expected response (Problem+JSON): `status: 404`, `type: "about:blank"`, `title: "Not Found"` (non-empty), `detail: "No route for /api/v1/documents/missing"`, `instance: "<full URL>"`
Mocking:
• Router: Memory router initialised to `/documents/view?docId=missing` to exercise the real page.
• Network (fetch): Intercept `GET /api/v1/documents/missing` and return the 404 Problem+JSON above with headers `Content-Type: application/problem+json`, `X-Request-Id: req-404`, and `Access-Control-Expose-Headers` including `X-Request-Id`. Rationale: isolate the browser boundary and drive a deterministic 404. Usage assertions: fetch called once with method GET, Accept includes `application/problem+json` or `application/json`, no extra PII headers.
• Analytics SDK: Stub `track("ui.error", …)` to capture one error event.
• Time/other browser APIs: none.
Assertions:
• DOM: An error region with `role="alert"` and `aria-live="assertive"` is rendered and includes the non-empty title text “Not Found”.
• A11y: Focus moves to the error region or first error heading; region is discoverable to screen readers.
• URL/route: Path and query remain `/documents/view?docId=missing` (no navigation on failure).
• Storage: `localStorage`, `sessionStorage`, and cookies remain unchanged (no tokens persisted).
• Network: Exactly one request to `/api/v1/documents/missing`, method GET, no credentials or secrets in headers/body; response handling does not retry.
• Analytics: One `ui.error` event fired with `{ code: "RUN_ROUTE_NOT_FOUND", status: 404, request_id: "req-404", screen: "documents/view" }` and no PII.
AC-Ref: 6.2.2.80
Error Mode: RUN_ROUTE_NOT_FOUND

7.2.2.81 Problem+JSON detail is present and surfaced to the user (500)
Purpose: Verify that when a request fails with a 500 and the Problem+JSON body arrives, the client surfaces a non-empty, safe detail string (no stack traces), without navigating or leaking secrets.
Test Data:
• Initial route: `/settings`
• User action: Click “Save” to trigger a settings save request.
• Expected response (Problem+JSON): `status: 500`, `type: "about:blank"`, `title: "Internal Server Error"`, `detail: "An unexpected error occurred."` (non-empty, generic), `instance: "<full URL>"`
Mocking:
• Router: Memory router initialised to `/settings`.
• Network (fetch): Intercept `POST /api/v1/settings` with a valid JSON body and return the 500 Problem+JSON above with headers `Content-Type: application/problem+json`, `X-Request-Id: req-500`, and `Access-Control-Expose-Headers` including `X-Request-Id`. Rationale: drive an unhandled error shape at the browser boundary. Usage assertions: one POST with correct URL, `Content-Type: application/json`, `Accept` includes `application/problem+json` or `application/json`, body contains only expected fields, no secrets.
• Analytics SDK: Stub `track("ui.error", …)` to capture one error event.
• Time/other browser APIs: none.
Assertions:
• DOM: An error region with `role="alert"` and `aria-live="assertive"` is rendered and includes the non-empty detail text “An unexpected error occurred.”
• A11y: Focus is moved to the error region or the first error heading; region is screen-reader discoverable.
• URL/route: Remains on `/settings` (no navigation on failure).
• Storage: No new keys are written; any existing auth/session keys remain unchanged.
• Network: Exactly one POST to `/api/v1/settings`; no retries; request body contains only the edited settings payload; no tokens or secrets echoed in body or query.
• Analytics: One `ui.error` event fired with `{ code: "RUN_UNEXPECTED_ERROR", status: 500, request_id: "req-500", screen: "settings" }` and no PII.
AC-Ref: 6.2.2.81
Error Mode: RUN_UNEXPECTED_ERROR

ID: 7.2.2.82
Title: Upstream proxy strips If-Match en route to app
Purpose: Treat a stripped If-Match as a missing-precondition scenario caused by the environment; no mutation allowed.
Test Data:

- Client-intended request (for traceability only): PATCH /api/v1/response-sets/resp_123/answers/q_456 with If-Match: W/"fresh-tag" and body { "value": "X" }.
- Actual app-received request (after proxy): same URL and body, but no If-Match header.
Mocking:
- Mock the edge gateway adapter (boundary) to drop If-Match from inbound headers before they reach the app.
- Assert adapter saw the client header and removed it (record original vs forwarded headers).
- Spy the answers repository to prove no mutation occurs.
Assertions:
- App response status: 428 Precondition Required.
- Problem JSON: code = "PRE_REQUEST_HEADERS_IF_MATCH_MISSING" (proxied cause), plus an environment diagnostic log/metric tagged ENV_PROXY_STRIPS_IF_MATCH.
- Repository spy: zero calls.
AC-Ref: 6.2.2.82
Error Mode: ENV_PROXY_STRIPS_IF_MATCH

ID: 7.2.2.83
Title: Upstream proxy strips domain ETag headers from success response
Purpose: Block finalisation when required domain headers are removed by a proxy.
Test Data:

- HTTP method: PATCH
- URL: /api/v1/screens/scr_789
- Request headers: Authorization: Bearer dev-token; If-Match: W/"fresh-tag"
- Body: { "title": "New Title" }
Mocking:
- Allow normal mutation and header emission in the app (it sets both ETag and Screen-ETag).
- Mock the edge gateway response filter to remove Screen-ETag (and optionally ETag) from the outgoing response.
- Assert the filter was invoked and stripped those headers.
Assertions:
- Finalised response status observed by the client is 500 Internal Server Error (contract cannot be satisfied).
- Problem JSON: code = "ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS".
- Verify the app attempted to emit both headers prior to gateway filtering (via server-side log/spy).
AC-Ref: 6.2.2.83
Error Mode: ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS

ID: 7.2.2.84
Title: Guard misapplied to a read (GET) endpoint
Purpose: Misconfiguration: precondition guard mounted on a GET route must be treated as an environment/config error.
Test Data:

- HTTP method: GET
- URL: /api/v1/screens/scr_555
- Request headers: Authorization: Bearer dev-token (no If-Match, as reads don’t require it).
Mocking:
- Mock route wiring (dependency injection) to mount precondition_guard on this GET route.
- Assert the guard was called on this GET request.
- Do not mock handler; it should not run due to misconfiguration failure.
Assertions:
- Status code: 500 Internal Server Error (guard misapplied).
- Problem JSON: code = "ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS".
- Assert the real GET handler was not invoked and no persistence calls were made.
AC-Ref: 6.2.2.84
Error Mode: ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS

ID: 7.2.2.85
Title: Answers PATCH mismatch must expose ETag and Screen-ETag on 409
Purpose: Ensure conflict responses include refreshable tags for the client to recover.
Test Data:

- Method: PATCH
- URL: /api/v1/response-sets/rs_001/answers/q_001
- Headers: If-Match: W/"not-the-right-tag"
- Body: { "value": "X" }
Mocking:
- Repo boundary: get_screen_key_for_question -> "welcome"; get_screen_version -> 1 (spy calls, no I/O).
Assertions:
- Status: 409; Content-Type: application/problem+json
- Problem JSON: code = "PRE_IF_MATCH_ETAG_MISMATCH" (per spec resolver)
- Headers: ETag and Screen-ETag present and non-empty
- Access-Control-Expose-Headers includes ETag and Screen-ETag (exactly once)
AC-Ref: 6.2.2.85
Error Mode: PRE_IF_MATCH_ETAG_MISMATCH

ID: 7.2.2.86
Title: Normalized-empty If-Match (no valid tokens) returns 409 with NO_VALID_TOKENS and exposes tags
Purpose: Distinguish normalized-empty from malformed; emit headers to enable client refresh.
Test Data:

- Method: PATCH
- URL: /api/v1/response-sets/rs_001/answers/q_001
- Headers: If-Match: ' , , "" , W/"" '
- Body: { "value": "X" }
Mocking:
- Repo boundary as above.
Assertions:
- Status: 409; Content-Type: application/problem+json
- Problem JSON: code = "PRE_IF_MATCH_NO_VALID_TOKENS"
- Headers: ETag and Screen-ETag present and non-empty
- Access-Control-Expose-Headers includes ETag and Screen-ETag (exactly once)
AC-Ref: 6.2.2.86
Error Mode: PRE_IF_MATCH_NO_VALID_TOKENS

ID: 7.2.2.87                                                                                                                                                          [374/18086]
Title: Unsupported Content-Type is validated before precondition checks
Purpose: Ensure media type validation (415) is not masked by precondition guard.
Test Data:

- Method: PATCH
- URL: /api/v1/response-sets/rs_001/answers/q_001
- Headers: If-Match: W/"abc"; Content-Type: text/plain
- Body: raw text "value=x"
Mocking:
- Repo boundary as above (spies only).
Assertions:
- Status: 415 Unsupported Media Type
- Problem JSON: code = "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED" (per spec)
- Guard not invoked (or invoked but yields media-type precedence); no mutation
AC-Ref: 6.2.2.87
Error Mode: PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED

ID: 7.2.2.88
Title: Documents reorder precondition failure emits X-List-ETag and X-If-Match-Normalized
Purpose: Preserve diagnostic headers on list-level concurrency conflicts.
Test Data:

- Method: PATCH
- URL: /api/v1/documents/reorder
- Headers: If-Match: W/"stale-list-tag"
- Body: { "order": ["d3","d1","d2"] }
Mocking:
- Document store/list provider to a fixed set; compute current list ETag via public helper; ensure mismatch.
Assertions:
- Status: 412 (documents route’s existing mismatch status)
- Problem JSON: code = "PRE_IF_MATCH_ETAG_MISMATCH"
- Headers: X-List-ETag equals current list tag; X-If-Match-Normalized reflects normalized incoming value
AC-Ref: 6.2.2.88
Error Mode: PRE_IF_MATCH_ETAG_MISMATCH

ID: 7.2.2.89
Title: Access-Control-Expose-Headers must include required names exactly once
Purpose: Guarantee clients can read emitted tags across responses.
Test Data:

- Method: PATCH
- URL: /api/v1/response-sets/rs_001/answers/q_001
- Headers: If-Match: W/"not-the-right-tag"
- Body: { "value": "X" }
Mocking:
- Repo boundary as above.
Assertions:
- Status: 409; Problem JSON code = "PRE_IF_MATCH_ETAG_MISMATCH"
- Access-Control-Expose-Headers contains ETag and Screen-ETag exactly once (idempotent configuration)
- ETag and Screen-ETag present and non-empty
AC-Ref: 6.2.2.89
Error Mode: ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED (if missing); otherwise pass on correct exposure

7.3.1.1 — Load screen view after run start
**Title:** Response set creation triggers initial screen load
**Purpose:** Verify that, after a run is created, the system initiates a fetch of the initial screen view.
**Test Data:** questionnaire_id: `q_001`; response_set_id: `rs_123`; initial screen_key: `intro`.
**Mocking:** Mock backend `POST /api/v1/response-sets` to return `rs_123` (dummy success); mock `GET /api/v1/response-sets/rs_123/screens/intro` to return a minimal screen payload and a dummy `Screen-ETag`. Mocks return success to allow sequencing to continue.
**Assertions:** Assert invoked once immediately after response set creation completes, and not before.
**AC-Ref:** 6.3.1.1

7.3.1.2 — Store hydration after screen view fetch
**Title:** Screen view fetch triggers store hydration
**Purpose:** Verify that, once a screen view is fetched, the UI store hydration step begins.
**Test Data:** response_set_id: `rs_123`; screen_key: `intro`.
**Mocking:** Mock `GET /api/v1/response-sets/rs_123/screens/intro` to return a minimal valid screen view with `Screen-ETag: "W/\"abc\""`; no other mocks.
**Assertions:** Assert invoked once immediately after screen view fetch completes, and not before.
**AC-Ref:** 6.3.1.2

7.3.1.3 — Autosave subscriber activation after hydration
**Title:** Store hydration triggers autosave subscriber start
**Purpose:** Verify that autosave subscription starts only after the store is hydrated.
**Test Data:** hydrated store with screen `intro` and one editable field `q1`.
**Mocking:** No external services mocked; internal debounce timer may be stubbed to fire immediately to observe sequencing.
**Assertions:** Assert invoked once immediately after store hydration completes, and not before.
**AC-Ref:** 6.3.1.3

7.3.1.4 — Debounced save triggers PATCH
**Title:** Debounced answer change triggers PATCH call
**Purpose:** Verify that, after a debounced local change, the system initiates a PATCH to the answer endpoint.
**Test Data:** response_set_id: `rs_123`; question_id: `q1`; new value: `"John"`.
**Mocking:** Mock `PATCH /api/v1/response-sets/rs_123/answers/q1` to return 204 with `Screen-ETag: "W/\"abd\""`; mocks return success to allow sequencing to continue.
**Assertions:** Assert invoked once immediately after the debounce window completes, and not before.
**AC-Ref:** 6.3.1.4

7.3.1.5 — Successful PATCH triggers screen apply
**Title:** PATCH success triggers application of returned screen view
**Purpose:** Verify that, after a successful PATCH, the adapter initiates applying the returned (or refreshed) screen view.
**Test Data:** response_set_id: `rs_123`; question_id: `q1`.
**Mocking:** Mock `PATCH …/answers/q1` to return 200 with a minimal `screen_view` object; mocks succeed.
**Assertions:** Assert invoked once immediately after PATCH success completes, and not before.
**AC-Ref:** 6.3.1.5

7.3.1.6 — Binding success triggers screen refresh
**Title:** Bind/unbind success triggers screen refresh apply
**Purpose:** Verify that, when a bind/unbind completes successfully, the system initiates a screen refresh/application step.
**Test Data:** question_id: `q1`; placeholder_id: `ph_9`; document_id: `doc_7`.
**Mocking:** Mock `POST /api/v1/placeholders/bind` to return success and an updated `screen_view`; mocks succeed.
**Assertions:** Assert invoked once immediately after bind/unbind completes, and not before.
**AC-Ref:** 6.3.1.6

7.3.1.7 — Active screen change rotates working tag
**Title:** Screen navigation triggers working ETag rotation
**Purpose:** Verify that changing the active screen triggers the step that rotates/sets the working `Screen-ETag` context.
**Test Data:** navigate from `intro` to `details`.
**Mocking:** Mock `GET /api/v1/response-sets/rs_123/screens/details` to return success with `Screen-ETag: "W/\"abe\""`; mocks succeed.
**Assertions:** Assert invoked once immediately after active screen change completes, and not before.
**AC-Ref:** 6.3.1.7

7.3.1.8 — Short-poll tick triggers conditional refresh
**Title:** Poll tick with tag change triggers screen load
**Purpose:** Verify that the polling mechanism, upon detecting an ETag change, initiates a screen reload step.
**Test Data:** active screen_key: `details`; previous tag: `W/"abe"`; new tag: `W/"abf"`.
**Mocking:** Mock `HEAD` or lightweight `GET` to return `ETag: W/"abf"` (changed) followed by a `GET` returning a minimal screen view; mocks succeed.
**Assertions:** Assert invoked once immediately after poll detects tag change, and not before.
**AC-Ref:** 6.3.1.8

7.3.1.9 — Tab focus triggers conditional refresh
**Title:** Visibility change to visible triggers refresh check
**Purpose:** Verify that, when the tab gains focus, the system initiates the light refresh step.
**Test Data:** window becomes visible; active screen_key: `details`.
**Mocking:** Mock light `GET` to return a `304` (no changes) to allow sequencing to complete without further calls.
**Assertions:** Assert invoked once immediately after tab visibility event handling completes, and not before.
**AC-Ref:** 6.3.1.9

7.3.1.10 — Multi-scope headers trigger ETag store updates
**Title:** Success response with multiple domain headers triggers per-scope updates
**Purpose:** Verify that, after a successful write returning multiple domain ETags, the per-scope update step is initiated.
**Test Data:** PATCH response contains `Screen-ETag: W/"s1"` and `Question-ETag: W/"q1"`.
**Mocking:** Mock `PATCH …/answers/q1` to succeed and include both headers; mocks succeed.
**Assertions:** Assert invoked once immediately after success response is received, and not before.
**AC-Ref:** 6.3.1.10

7.3.1.11 — Inject fresh If-Match after header update
Title: Per-scope ETag update triggers next-write header injection
Purpose: Verify that, once per-scope ETag store updates, the write path injects the updated raw token on the very next outbound write.
Test Data: response_set_id: rs_123; question_id: q1; prior Screen-ETag: W/"s1"; updated Screen-ETag: W/"s2".
Mocking: Mock PATCH /api/v1/response-sets/rs_123/answers/q1 to first succeed and return Screen-ETag: W/"s2"; configure the very next PATCH probe (e.g., for q1 again) to accept only If-Match: W/"s2". Mocks return success to allow sequencing to continue.
Assertions: Assert invoked once immediately after per-scope ETag store update completes, and not before.
AC-Ref: 6.3.1.11

7.3.1.12 — Continue polling after 304
Title: Light refresh 304 triggers continuation of polling loop
Purpose: Verify that, after a focus/poll light refresh returns 304 Not Modified, the polling scheduler proceeds to the next tick without triggering an apply step.
Test Data: active screen_key: details; stored Screen-ETag: W/"abf".
Mocking: Mock light GET/HEAD to return 304 with ETag: W/"abf"; polling timer is stubbed to fire immediately to observe sequencing; mocks return success to allow sequencing to continue.
Assertions: Assert invoked once immediately after light refresh handling completes, and not before.
AC-Ref: 6.3.1.12

7.3.1.13 — Answers POST success triggers screen apply
Title: POST success triggers application of returned/updated screen view
Purpose: Verify that, after a successful answers POST, the adapter initiates the step that applies the (returned or refreshed) screen view.
Test Data: response_set_id: rs_123; question_id: q2; value: "Acme Corp".
Mocking: Mock POST /api/v1/response-sets/rs_123/answers/q2 to return a dummy success response sufficient to allow sequencing to continue.
Assertions: Assert invoked once immediately after POST success completes, and not before.
AC-Ref: 6.3.1.13

7.3.1.14 — Answers DELETE success triggers screen apply
Title: DELETE success triggers application of refreshed screen view
Purpose: Verify that, after a successful answers DELETE, the next step applies the current screen view.
Test Data: response_set_id: rs_123; question_id: q1.
Mocking: Mock DELETE /api/v1/response-sets/rs_123/answers/q1 to return a dummy success response sufficient to allow sequencing to continue.
Assertions: Assert invoked once immediately after DELETE success completes, and not before.
AC-Ref: 6.3.1.14

7.3.1.15 — Document reorder success triggers list refresh
Title: Reorder success triggers document list refresh/apply
Purpose: Verify that, after a successful document reorder, the list refresh/application step runs.
Test Data: items: [ {document_id: "doc_1", order: 1}, {document_id: "doc_2", order: 2}, {document_id: "doc_3", order: 3} ].
Mocking: Mock PUT /api/v1/documents/order to return a dummy success response sufficient to allow sequencing to continue.
Assertions: Assert invoked once immediately after reorder success completes, and not before.
AC-Ref: 6.3.1.15

7.3.1.16 — Any-match precondition success triggers mutation
Title: Multi-token If-Match (any-match) success triggers write execution
Purpose: Verify that, when the precondition guard resolves an any-match success for a write, the mutation step is invoked.
Test Data: write attempt to answers with an If-Match list (e.g., tokens t_old, t_current, t_extra).
Mocking: Mock the write endpoint to return a dummy success response as if one token matched, sufficient to allow sequencing to continue.
Assertions: Assert invoked once immediately after precondition guard success completes, and not before.
AC-Ref: 6.3.1.16

7.3.1.17 — Wildcard precondition success triggers mutation
Title: If-Match * (where supported) triggers write execution
Purpose: Verify that, when a route accepts wildcard preconditions and the resource-exists check passes, the mutation step is invoked.
Test Data: write attempt to a supported route with wildcard precondition.
Mocking: Mock the write endpoint to return a dummy success response sufficient to allow sequencing to continue.
Assertions: Assert invoked once immediately after precondition guard success completes, and not before.
AC-Ref: 6.3.1.17

7.3.1.18 — Runtime JSON success triggers header-read step
Title: Runtime success triggers client header-read and tag handling
Purpose: Verify that, after a successful runtime JSON fetch (e.g., screen GET or answers write), the client invokes the header-read/tag-handling step.
Test Data: response_set_id: rs_123; screen_key: details.
Mocking: Mock the runtime request to return a dummy success response sufficient to allow sequencing to continue.
Assertions: Assert invoked once immediately after runtime fetch success completes, and not before.
AC-Ref: 6.3.1.18

7.3.1.19 — Authoring JSON success triggers header-read step
Title: Authoring success triggers client header-read and tag handling
Purpose: Verify that, after a successful authoring JSON operation, the client invokes the header-read/tag-handling step.
Test Data: authoring route of choice (e.g., update screen title).
Mocking: Mock the authoring request to return a dummy success response sufficient to allow sequencing to continue.
Assertions: Assert invoked once immediately after authoring fetch success completes, and not before.
AC-Ref: 6.3.1.19

7.3.1.20 — Non-JSON download completion triggers tag handling (no UI apply)
Title: Download success triggers tag handling and resumes flow without view apply
Purpose: Verify that, after a successful non-JSON download (e.g., CSV), the tag-handling step runs and the pipeline proceeds without invoking a screen or list apply.
Test Data: questionnaire_id: q_001 (CSV export).
Mocking: Mock the download request to return a dummy success response sufficient to allow sequencing to continue.
Assertions: Assert invoked once immediately after download success handling completes, and not before.
AC-Ref: 6.3.1.20

7.3.1.21 — Successful guarded write logs in order
Title: Guarded write success triggers emit-logging after mutation
Purpose: Verify that, once a guarded write succeeds, the logging step that records header emission is invoked after mutation completes.
Test Data: any guarded write (answers/documents).
Mocking: Mock the write endpoint and the telemetry sink to return dummy success responses sufficient to allow sequencing to continue.
Assertions: Assert invoked once immediately after write success completes, and not before.
AC-Ref: 6.3.1.21

7.3.1.22 — Legacy token parity does not trigger extra refresh
Title: Unchanged legacy token triggers no spurious refresh/rotation
Purpose: Verify that, when a successful read returns the same legacy token as the baseline, the tag-change detector runs and proceeds without triggering an additional refresh step.
Test Data: runtime screen GET for intro; baseline captured from pre-refactor build.
Mocking: Mock the runtime GET to return a dummy success response sufficient to allow sequencing to continue.
Assertions: Assert invoked once immediately after screen GET completes (tag-change detection), and not before.
AC-Ref: 6.3.1.22

7.3.2.1
Title: CORS expose-headers misconfiguration halts header emission (STEP-4) and prevents body mirrors (STEP-5)
Purpose: Verify that when required domain ETag headers are not exposed by CORS, the pipeline halts at header emission and does not proceed to body-mirror handling.
Test Data:

Request: GET /api/v1/response-sets/rs_001/screens/welcome (runtime JSON GET that would normally emit Screen-ETag and ETag).

Environment/config under test: CORS Access-Control-Expose-Headers configured without Screen-ETag, Question-ETag, Questionnaire-ETag, Document-ETag, or ETag.
Mocking:

Mock only the CORS/config provider at the boundary so that it returns an expose-headers list that omits all ETag headers (e.g., ["Content-Type","Cache-Control"]).

Allow STEP-1/2/3 to execute real logic (normaliser, guard, mutation/tag retrieval).

Assertions on the mock: verify the CORS/config provider was queried once during STEP-4 and returned the misconfigured list.
Assertions:

Assert error handler is invoked once immediately when STEP-4 Header emission raises due to the CORS expose-headers misconfiguration, and not before.

Assert STEP-5 Body mirrors is prevented (no invocation recorded), and stop propagation beyond STEP-4 as specified.

Assert that error mode ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED is observed.

Assert no unintended side-effects: no retries of STEP-4, no partial header writes, no later step calls.

Assert one error telemetry event is emitted for ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED.
AC-Ref: 6.3.2.1
Error Mode: ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED

7.3.2.2

Title: Logging sink unavailable during precondition check (STEP-2) does not alter flow
Purpose: Verify that a telemetry failure while recording etag.enforce does not change sequencing; the pipeline continues through mutation and header emission.
Test Data:

Request: PATCH /api/v1/response-sets/rs_001/answers/q_123

Headers: If-Match: W/"abc" (valid current tag)
Mocking:

Mock telemetry/logging sink at the boundary: the call to record etag.enforce fails (e.g., raises Unavailable/Timeout).

Mock mutation layer to return a dummy success sufficient to allow sequencing to continue.

No other components mocked (normaliser/guard execute real logic).
Assertions:

Assert STEP-3 Mutation and tag retrieval is invoked once immediately after STEP-2 Precondition enforcement completes, and not before.

Assert STEP-4 Header emission is invoked once immediately after STEP-3 completes, and not before.

Assert STEP-5 Body mirrors (when applicable) is invoked once immediately after STEP-4 completes, and not before.

Assert exactly one failed attempt to write etag.enforce was made to the logging sink and no retries occurred.

Assert the condition is classified as ENV_LOGGING_SINK_UNAVAILABLE_ENFORCE in internal diagnostics (telemetry degraded only).
AC-Ref: 6.3.2.2
Error Mode: ENV_LOGGING_SINK_UNAVAILABLE_ENFORCE

7.3.2.3

Title: Logging sink unavailable during header emission (STEP-4) does not alter flow
Purpose: Verify that a telemetry failure while recording etag.emit does not block response finalisation; the pipeline proceeds to completion.
Test Data:

Request: GET /api/v1/response-sets/rs_001/screens/details (runtime JSON GET)
Mocking:

Mock telemetry/logging sink so the call to record etag.emit fails (Unavailable/Timeout).

Response generation runs normally (no other mocks required).
Assertions:

Assert STEP-4 Header emission completes once and immediately triggers response finalisation, and not before.

Assert STEP-5 Body mirrors (when applicable) is invoked once immediately after STEP-4 completes, and not before.

Assert exactly one failed attempt to write etag.emit was made and no retries occurred.

Assert the condition is classified as ENV_LOGGING_SINK_UNAVAILABLE_EMIT in internal diagnostics (telemetry degraded only).
AC-Ref: 6.3.2.3
Error Mode: ENV_LOGGING_SINK_UNAVAILABLE_EMIT

7.3.2.4

Title: Upstream proxy strips domain ETag headers at egress → halt at STEP-4
Purpose: Verify that detecting an egress policy that strips domain ETag headers halts finalisation at STEP-4 and prevents downstream completion.
Test Data:

Request: PATCH /api/v1/response-sets/rs_001/answers/q_123 with valid If-Match
Mocking:

Mock API gateway/proxy egress policy probe to report header stripping for domain ETag headers (and generic ETag where applicable).

Mutation returns dummy success (to reach STEP-4).
Assertions:

Assert STEP-4 Header emission detection halts once immediately when the egress-strip policy is observed, and not before.

Assert STEP-5 Body mirrors is prevented (no invocation recorded).

Assert response finalisation is prevented (stop propagation beyond STEP-4).

Assert no retries of STEP-4 and no partial emission attempts after the halt.

Assert the condition is classified as ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS.
AC-Ref: 6.3.2.4
Error Mode: ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS

7.3.2.5

Title: CORS preflight missing If-Match → halt before STEP-2 (no guard, no mutation)
Purpose: Verify that an OPTIONS preflight for a write endpoint that omits If-Match in Access-Control-Allow-Headers blocks the write path before STEP-2.
Test Data:

Request: OPTIONS /api/v1/response-sets/rs_001/answers/q_123

Preflight headers: Access-Control-Request-Method: PATCH; Access-Control-Request-Headers: content-type, authorization (no if-match)
Mocking:

Mock CORS/allow-headers provider to omit If-Match from Access-Control-Allow-Headers.
Assertions:

Assert the pipeline halts once during preflight handling before STEP-2 Precondition enforcement, and not before.

Assert STEP-2/STEP-3/STEP-4/STEP-5 are all prevented (no guard, no mutation, no header emission, no mirrors).

Assert the condition is classified as ENV_CORS_ALLOW_HEADERS_MISSING_IF_MATCH.
AC-Ref: 6.3.2.5
Error Mode: ENV_CORS_ALLOW_HEADERS_MISSING_IF_MATCH

7.3.2.6

Title: Upstream proxy strips If-Match on ingress → halt at STEP-2 (missing-precondition branch)
Purpose: Verify that when a proxy removes If-Match before the app, the guard engages the missing-precondition branch and prevents mutation.
Test Data:

Client-intended headers (for trace only): If-Match: W/"abc"

Application-received headers: no If-Match

Request: PATCH /api/v1/response-sets/rs_001/answers/q_123
Mocking:

Mock ingress/proxy layer to strip If-Match so the application receives the request without it.

No mutation/DB mocks (should not be reached).
Assertions:

Assert STEP-2 Precondition enforcement is invoked once and halts immediately on the missing-precondition branch, and not before.

Assert STEP-3 Mutation and tag retrieval is prevented (no invocation).

Assert STEP-4/STEP-5 are prevented (no header emission, no mirrors).

Assert the condition is classified as ENV_PROXY_STRIPS_IF_MATCH (environmental cause), with the guard taking its missing-precondition path.
AC-Ref: 6.3.2.6
Error Mode: ENV_PROXY_STRIPS_IF_MATCH

7.3.2.7

Title: Guard misapplied to read (GET) endpoints → halt at STEP-2 with server-side configuration error
Purpose: Verify that invoking the guard on a Phase-0 read route is treated as a configuration error that halts the pipeline and prevents header emission.
Test Data:

Request: GET /api/v1/response-sets/rs_001/screens/welcome (Phase-0 read)
Mocking:

Mock router/middleware wiring to invoke the precondition guard on this GET route.

No backend data mocks (should halt before handler).
Assertions:

Assert STEP-2 Precondition enforcement is invoked once (misapplied) and halts the pipeline immediately, and not before.

Assert STEP-3/STEP-4/STEP-5 are prevented (no handler execution, no header emission, no mirrors).

Assert the condition is classified as ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS.
AC-Ref: 6.3.2.7
Error Mode: ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS
