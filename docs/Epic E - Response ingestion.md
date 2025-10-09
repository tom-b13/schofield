# epic e - response ingestion api

## purpose

Capture, validate, and persist questionnaire answers entered by a user into a response set. Provide a safe, concurrency-controlled write path that other epics can rely on for visibility evaluation and later document generation.

## relationships

* epic a provides the data model for questions, options, response sets, responses, and related entities.
* epic b defines questionnaire authoring, screen reads, and baseline autosave semantics. epic e implements and hardens the runtime ingestion layer used by the ui.
* epic d ensures questions have a consistent answer model derived from bound placeholders. epic e enforces that model at write time.
* epic i evaluates conditional visibility. epic e uses existing helpers directly: repository_screens.get_visibility_rules_for_screen + visibility_rules.compute_visible_set for reads, and visibility_delta.compute_visibility_delta for post-write deltas; epic e filters out hidden questions in GET responses and includes deltas (now_visible, now_hidden, suppressed_answers) in PATCH responses.
* epic f consumes a complete response set to populate placeholders during document generation.

## scope

in scope

* single answer upsert for one (response_set_id, question_id) per request.
* type aware validation against the question model and its answer options.
* canonicalisation for numbers (finiteness) and enum option resolution; text is stored verbatim; booleans must be true/false.
* safe clearing of answers.
* optimistic concurrency using ETag with If-Match. no server-side idempotency store.
* structured errors using application/problem+json.

out of scope

* questionnaire authoring and import-export.
* conditional visibility algorithms and delta computation.
* document generation and placeholder merge.
* role based access control.
* multi-value enumeration.

## domain references

* response set represents one run of a questionnaire. it is the top-level container for answers.
* response holds the stored answer for a question within a response set. exactly one unique row per (response_set_id, question_id).
* for enum single questions, option_id identifies the selected AnswerOption and its canonical value is used as the stored truth for comparisons.
* placeholders (defined in epic d) may map many-to-one onto a single question; epic f uses that mapping to replace all associated placeholders with the saved answer for that question.

## api surface v1

base path: /api/v1

1. post /response-sets

   * purpose: create a new response set.
   * request: { name: string }

     * name: required human readable label for identification.
   * responses:

     * 201 created { response_set_id, name, etag, created_at }

2. get /response-sets/{response_set_id}/screens/{screen_key}

   * purpose: return the renderable screen definition (from Epic B) together with any saved answers (from this epic), filtered by conditional visibility from Epic I.
   * ownership: implemented in Epic E. Epic B supplies the question/screen structure; Epic E hydrates answers and invokes Epic I.
   * behaviour:

     * loads the screen layout and question metadata defined by Epic B (types, options, ordering, grouping).
     * joins in the current answers for those question_ids from the responses table for response_set_id.
     * calls Epic I to evaluate visibility; returns only the questions that are currently visible. Hidden questions are omitted from this payload.
   * response shape (illustrative):

     * { screen_key, name, etag, questions: [{ question_id, kind, label, options?, ui, answer?: { value|option_id|bool|number|text } }] }

3. patch /response-sets/{response_set_id}/answers/{question_id}

   * purpose: atomic single answer upsert with optimistic concurrency.
   * headers: Content-Type application/json. If-Match is required on all writes; clients obtain the latest ETag via the screen GET.
   * request bodies by answer kind:

     * short_string or long_text: { value?: string | null, clear?: boolean }
     * number: { value?: number | null, clear?: boolean }
     * boolean: { value?: boolean | null, clear?: boolean }
     * enum_single: { option_id?: uuid, value?: string, label?: string, allow_new_label?: boolean, clear?: boolean }

       * value is the canonical option value token when option_id is not supplied. label is preserved when provided but never used for comparisons.
   * behaviour:

     * default: missing fields and explicit null values are treated as no-op unless clear is true.
     * to clear an answer: client sets clear: true; server removes any option_id and nulls all value fields for the response row.
     * for enum_single, resolve option_id from value when only value is given. reject if not a member of the question option set.
     * apply canonicalisation: resolve enums to `option_id`; numbers must be finite; booleans must be literal true/false.
     * upsert into Response, enforcing the unique key per response set and question. return the new etag and state_version.
   * responses:

     * 200 ok { response_set_id, saved: { question_id, state_version }, etag, visibility_delta?, suppressed_answers? }

       * visibility_delta.now_visible: array of { question: { id, kind, label, ui, options? }, answer }
       * visibility_delta.now_hidden: array of question ids
       * suppressed_answers: array of question ids whose stored answers should be ignored while hidden
     * also include screen_view with the same shape as GET /response-sets/{response_set_id}/screens/{screen_key}; add Screen-ETag header reflecting the returned screen_view.

4. delete /response-sets/{response_set_id}/answers/{question_id}

   * purpose: explicit clear of an answer where the client prefers a delete over a null value patch.
   * headers: If-Match required.
   * behaviour: explicit clear only; patch with value null is a no-op unless clear=true. idempotent by design via ETag.
   * responses: 204 no content with updated ETag in header.

5. post /response-sets/{response_set_id}/answers:batch

   * purpose: administrative or importer bulk upsert. not used by interactive autosave. 
   * options: { update_strategy: "merge"|"replace" = "merge", clear_missing?: boolean = false }
   * behaviour:

     * merge: ignores null and missing fields by default; per item clear:true explicitly clears that answer.
     * replace: explicit clear only; null is a no-op unless clear=true. questions not present in the payload are left unchanged.
     * concurrency: each item must include the latest ETag for its target answer; items with stale ETags are rejected with 409.
     * stream process items, stop on hard schema violations, accumulate per item success or error. transactional boundary may be per item.

6. delete /response-sets/{response_set_id}

   * purpose: delete an entire response set and all its answers in one call.
   * headers: If-Match required.
   * behaviour: hard delete of the response set with cascading removal of all associated answers. if the resource does not exist, return 404. no partial deletes.
   * responses: 204 no content.
   * failures: 409 on ETag mismatch; 404 not found.

## validation and canonical rules

* short_string and long_text: accept string and store exactly as provided. no trimming. empty string is a real value and is stored as empty; null is a no-op unless clear=true.
* number: must be finite. reject NaN and Infinity. store in value_number.
* boolean: must be true or false when present. store in value_bool.
* enum_single: either option_id or canonical value must resolve to an existing AnswerOption for the question. store option_id and leave value_text null.
* mandatory questions are allowed to be temporarily empty during entry; gating for generation occurs elsewhere.

## concurrency

* each response row carries a state_version integer used to compute a strong etag for If-Match. increment on every successful write.
* clients must include If-Match for updates to prevent accidental overwrite. the server rejects stale writes with 409 and returns the current etag.
* for first write, clients must GET the screen to retrieve the current etag and include it in If-Match; missing or stale If-Match results in 409 with the current etag.
* etag is per response row for write paths and per screen for reads.

## events and hooks

* on successful save, emit domain event response.saved with { response_set_id, question_id, state_version }.
* when epic i is active, the handler also computes the visibility delta for descendants and includes it in the patch response.
* on successful delete of a response set, emit domain event response_set.deleted with { response_set_id }.

## interaction with epic i

* consumption: in-process function calls, not HTTP.
* direct helpers (no wrapper service):

  * app/logic/repository_screens.get_visibility_rules_for_screen(screen_key)
  * app/logic/visibility_rules.compute_visible_set(rules, parent_values)
  * app/logic/visibility_delta.compute_visibility_delta(pre_visible, post_visible, has_answer)
  * app/logic/repository_answers.get_existing_answer(response_set_id, question_id)
  * app/logic/repository_screens.list_questions_for_screen(screen_key)
  * app/logic/etag.compute_screen_etag(response_set_id, screen_key)
* read: epic e hydrates answers, loads rules via get_visibility_rules_for_screen, computes visible ids with compute_visible_set, filters to those questions, and returns only visible ones.
* write: after saving an answer, epic e recomputes pre/post visible sets and calls compute_visibility_delta; items in now_visible include { question, answer } (no per-item etag). response also includes screen_view and a Screen-ETag header representing the whole screen state.

# 1. Scope

## 1.1 Purpose

Provide a simple, reliable API for capturing and maintaining users’ questionnaire answers in a named response set. Enable smooth autosave and screen rendering by returning current answers and visibility-driven updates.

## 1.2 Inclusions

* Create a new, named response set.
* Read a screen: return its visible questions (as defined in the questionnaire) with any existing answers.
* Save a single answer for a question within a response set; support explicit clear of an answer.
* After saving, return the visibility changes and an updated screen so the UI can refresh immediately.
* Administrative batch upsert of answers (non-interactive use).
* Delete a single answer; delete an entire response set and all of its answers.

## 1.3 Exclusions

* Defining questionnaires, screens, question types, options, or UI metadata (handled elsewhere).
* Computing conditional visibility rules (consumed, not defined here).
* Generating documents or merging placeholders with answers.
* Authentication and authorisation concerns.
* Multi-value enumeration and advanced transformation logic.

## 1.4 Context

This API sits between questionnaire definition and document generation: it persists answers against a response set, reads screens with current answers, and applies visibility outcomes provided by the visibility component. It relies on existing question/screen definitions and visibility evaluation, and its outputs are consumed by the document generation service. No third-party systems are involved; it integrates with internal services for questionnaire structure and visibility.

## 2.2. EARS Functionality

### 2.2.1 Ubiquitous requirements

* **U1** The system will create a named response set.
* **U2** The system will persist the response set and expose its response_set_id.
* **U3** The system will accept a single-answer upsert for a question within a response set.
* **U4** The system will persist the saved answer.
* **U5** The system will link each saved answer to its response_set_id and question_id.
* **U6** The system will store short and long text exactly as provided.
* **U7** The system will store numbers only when finite.
* **U8** The system will store booleans only when they are literal true or false.
* **U9** The system will resolve enum submissions to a known option and store the option_id.
* **U10** The system will support explicit clearing of an answer.
* **U11** The system will assemble a screen_view containing only visible questions and any existing answers.
* **U12** The system will expose the screen_view to the client.
* **U13** The system will emit a response.saved event after a successful answer save.
* **U14** The system will delete an entire response set and all associated answers when requested.
* **U15** The system will emit a response_set.deleted event after a successful response-set delete.
* **U16** The system will support administrative batch upsert of multiple answers.

### 2.2.2 Event-driven requirements

* **E1** When a screen is requested, the system will evaluate conditional visibility and filter out hidden questions before building the screen_view.
* **E2** When an answer is saved, the system will compute and return a visibility_delta containing now_visible, now_hidden, and suppressed_answers.
* **E3** When questions become newly visible, the system will include each newly visible question with its metadata and any existing answer in the save response.
* **E4** When a batch payload is processed, the system will produce per-item outcomes for success or failure.
* **E5** When a response-set delete is requested, the system will cascade-delete all its answers.

### 2.2.3 State-driven requirements

* **S1** While a question is hidden, the system will retain any stored answer but exclude it from the screen_view.
* **S2** While a clear flag is present for a question, the system will remove the stored value for that question.
* **S3** While a question is mandatory, the system will allow it to be temporarily empty during entry.

### 2.2.4 Optional-feature requirements

* **O1** Where batch “merge” is used, the system will ignore null and missing fields unless clear is true.
* **O2** Where batch “replace” is used, the system will treat null as a no-op unless clear is true and will leave questions absent from the payload unchanged.
* **O3** Where visibility evaluation is enabled, the system will include visibility_delta in save responses and an updated screen_view.

### 2.2.5 Unwanted-behaviour requirements

* **N1** If a submitted value does not match the question’s answer kind, the system will reject the write.
* **N2** If an enum submission does not resolve to a known option, the system will reject the write.
* **N3** If a number is NaN or Infinity, the system will reject the write.
* **N4** If a write is attempted without the required concurrency precondition, the system will reject the write with a conflict.
* **N5** If a referenced response set or question does not exist, the system will return not found.
* **N6** If a delete is attempted without the required concurrency precondition, the system will reject the delete with a conflict.

### 2.2.6 Step Index

* **STEP-1** Create response set → U1, U2
* **STEP-2** Read screen → U11, U12, E1, S1
* **STEP-3** Save single answer → U3, U4, U5, U6, U7, U8, U9, E2, N1, N2, N3, N4, S3, U13
* **STEP-4** Apply visibility changes after save → E3, O3, U12
* **STEP-5** Clear an answer → U10, S2, N4
* **STEP-6** Batch upsert answers → U16, O1, O2, E4, N1, N2, N3, N4, N5
* **STEP-7** Delete response set → U14, U15, E5, N5, N6

| Field                                  | Description                                                      | Type                             | Schema / Reference                                                          | Notes                                                    | Pre-Conditions                                                                                                                                                           | Origin   |
| -------------------------------------- | ---------------------------------------------------------------- | -------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- |
| response_set_id                        | Identifier of the response set targeted by the operation         | string (uuid)                    | #/components/schemas/ResponseSetId                                          | None.                                                    | Identifier is required and must be provided; Identifier must be a valid UUID format; Identifier must refer to an existing response set record.                           | provided |
| screen_key                             | Key of the questionnaire screen to read or update against        | string                           | #/components/schemas/ScreenKey                                              | None.                                                    | Field is required and must be provided; Value must match a known screen key; Reference must resolve to a defined screen.                                                 | provided |
| question_id                            | Identifier of the question being answered or cleared             | string (uuid)                    | #/components/schemas/QuestionId                                             | None.                                                    | Identifier is required and must be provided; Identifier must be a valid UUID format; Identifier must refer to an existing question.                                      | provided |
| name                                   | Human-readable name to create a response set                     | string                           | #/components/schemas/ResponseSetCreate/properties/name                      | Used in POST /response-sets.                             | Field is required and must be provided; Value must be non-empty after normal user input; Value must not exceed product name length limits.                               | provided |
| if_match                               | Concurrency precondition for writes and deletes (ETag)           | string                           | #/components/schemas/ETag                                                   | Header for PATCH/DELETE.                                 | Header is required and must be provided; Value must equal the latest entity ETag; Value must be treated as opaque token.                                                 | provided |
| answerPatch                            | Request body for saving a single answer                          | object                           | #/components/schemas/AnswerPatchBody                                        | Used in PATCH /response-sets/{id}/answers/{question_id}. | Body must be provided for PATCH requests; Body must conform to the declared schema; Body must contain only permitted fields for the question kind.                       | provided |
| answerPatch.value                      | Submitted value for text/number/boolean kinds                    | string | number | boolean | null | #/components/schemas/AnswerPatchBody/properties/value                       | Null is a no-op unless clear is true.                    | Value must be of the correct primitive type for the question; Number value must be finite; Boolean value must be literal true or false.                                  | provided |
| answerPatch.option_id                  | Selected option identifier for enum_single                       | string (uuid)                    | #/components/schemas/AnswerPatchBody/properties/option_id                   | Mutually exclusive with value token.                     | Identifier must be a valid UUID format; Identifier must resolve to a known option for the question.                                                                      | provided |
| answerPatch.value_token                | Canonical option value token for enum_single                     | string                           | #/components/schemas/AnswerPatchBody/properties/value                       | Use when option_id is not supplied.                      | At least one of option_id or value_token must be provided; Token must resolve to a known option for the question; Token must be case and space normalised per catalogue. | provided |
| answerPatch.label                      | Display label supplied by client (optional)                      | string                           | #/components/schemas/AnswerPatchBody/properties/label                       | Preserved for UX; not used for comparisons.              | When present, value must be a string; Value must not exceed label length limits; Value must be UTF-8 encodable.                                                          | provided |
| answerPatch.allow_new_label            | Flag to accept an unknown label (if enabled)                     | boolean                          | #/components/schemas/AnswerPatchBody/properties/allow_new_label             | Only meaningful for enum_single UX.                      | When present, value must be boolean; Flag must be ignored where new labels are not allowed.                                                                              | provided |
| answerPatch.clear                      | Explicit clear of the stored answer                              | boolean                          | #/components/schemas/AnswerPatchBody/properties/clear                       | Overrides null handling.                                 | When true, server must treat value fields as cleared; When present, value must be boolean; Clear must only target existing question identifiers.                         | provided |
| batch.request                          | Batch upsert request envelope                                    | object                           | #/components/schemas/BatchUpsertRequest                                     | Used in POST /response-sets/{id}/answers:batch.          | Body must be provided for batch; Envelope must include options and items.                                                                                                | provided |
| batch.request.update_strategy          | Batch write behaviour: merge or replace                          | string (enum)                    | #/components/schemas/BatchUpsertRequest/properties/update_strategy          | Allowed: "merge", "replace".                             | Field is required and must be provided; Value must be one of the allowed literals; Strategy must be applied consistently to all items.                                   | provided |
| batch.request.clear_missing            | Whether to clear items not present (replace only)                | boolean                          | #/components/schemas/BatchUpsertRequest/properties/clear_missing            | Ignored for merge strategy.                              | When present, value must be boolean; Field must be false for merge strategy; Clearing behaviour must be documented to caller.                                            | provided |
| batch.request.items                    | Collection of item updates                                       | list[object]                     | #/components/schemas/BatchUpsertRequest/properties/items                    | Each item targets one question.                          | Field is required and must be provided; List must contain at least one item; Each item must conform to the declared item schema.                                         | provided |
| batch.request.items[].question_id      | Target question identifier for this item                         | string (uuid)                    | #/components/schemas/BatchUpsertItem/properties/question_id                 | None.                                                    | Identifier is required and must be provided; Identifier must be a valid UUID format; Identifier must refer to an existing question.                                      | provided |
| batch.request.items[].etag             | Concurrency token for the target answer                          | string                           | #/components/schemas/BatchUpsertItem/properties/etag                        | Equivalent to If-Match per item.                         | Field is required and must be provided; Value must equal the latest entity ETag; Value must be treated as opaque token.                                                  | provided |
| batch.request.items[].body             | Item answer payload                                              | object                           | #/components/schemas/BatchUpsertItem/properties/body                        | Same structure as AnswerPatchBody.                       | Body must conform to the declared schema; Body must contain only permitted fields for the question kind; Clear semantics must follow single-item rules.                  | provided |
| screen.definition                      | Screen structure (questions, order, UI metadata)                 | object                           | #/components/schemas/ScreenDefinition                                       | Acquired from questionnaire service.                     | Resource must exist and be readable by the process; Document must parse as valid JSON; Document must conform to the referenced schema.                                   | acquired |
| visibility.rules                       | Visibility ruleset for the screen                                | object                           | #/components/schemas/VisibilityRules                                        | Derived from screen metadata.                            | Resource must exist and be readable by the process; Document must parse as valid JSON; Rules must conform to the referenced schema.                                      | acquired |
| existing_answer                        | Current stored answer for a question (if any)                    | object | null                    | #/components/schemas/AnswerRecord                                           | Used to hydrate saves and deltas.                        | Lookup must complete without error; When present, record must match the declared schema; When absent, null must be handled without failure.                              | acquired |
| existing_answers_for_screen            | Current answers for all questions on a screen                    | list[object]                     | #/components/schemas/AnswerRecordList                                       | Used to hydrate GET screen.                              | Query must complete without error; Each record must match the declared schema; Collection must be iterable without side effects.                                         | acquired |
| visibility_result.visible_question_ids | IDs determined visible for the requested screen                  | list[string (uuid)]              | #/components/schemas/ScreenVisibilityResult/properties/visible_question_ids | Provider: Epic I evaluate_screen.                        | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                               | returned |
| visibility_delta.now_visible           | Question IDs that became visible after a save                    | list[string (uuid)]              | #/components/schemas/VisibilityDelta/properties/now_visible                 | Provider: Epic I compute_visibility_delta.               | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                               | returned |
| visibility_delta.now_hidden            | Question IDs that became hidden after a save                     | list[string (uuid)]              | #/components/schemas/VisibilityDelta/properties/now_hidden                  | Provider: Epic I compute_visibility_delta.               | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                               | returned |
| visibility_delta.suppressed_answers    | Question IDs whose stored answers should be ignored while hidden | list[string (uuid)]              | #/components/schemas/VisibilityDelta/properties/suppressed_answers          | Provider: Epic I compute_visibility_delta.               | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                               | returned |

| Field                                                   | Description                                                               | Type                | Schema / Reference                                                                                                                 | Notes                                                                                                  | Post-Conditions                                                                                                                                     | Origin   |
| ------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| outputs.response_set_id                                 | Identifier of the response set returned by create or save operations      | string (uuid)       | #/components/schemas/Outputs/properties/response_set_id                                                                            | Returned on POST and PATCH responses                                                                   | Value must validate as UUID; Field must be present on successful POST and PATCH responses; Value must refer to the same response set as the request | returned |
| outputs.name                                            | Human-readable name of the response set                                   | string              | #/components/schemas/Outputs/properties/name                                                                                       | Returned on POST create                                                                                | Field must be present on POST create responses; Value must be identical to persisted response set name                                              | returned |
| outputs.etag                                            | Current ETag for the saved answer (single-answer operations)              | string              | #/components/schemas/Outputs/properties/etag                                                                                       | Returned in PATCH body                                                                                 | Field must be present on successful PATCH; Value must be an opaque token; Value must change when the target answer changes                          | returned |
| outputs.created_at                                      | Creation timestamp of the response set                                    | string (date-time)  | #/components/schemas/Outputs/properties/created_at                                                                                 | Returned on POST create                                                                                | Field must be present on POST create responses; Timestamp must be RFC 3339 UTC format; Timestamp must match persisted creation time                 | returned |
| outputs.screen_view                                     | Screen payload containing only visible questions and any existing answers | object              | #/components/schemas/Outputs/properties/screen_view                                                                                | Returned by GET screen and PATCH save                                                                  | Field must be present on successful GET screen; Field must be present on successful PATCH save; Object must validate against Screen View sub-schema | returned |
| outputs.screen_view.screen_key                          | Identifier of the screen                                                  | string              | #/components/schemas/Outputs/properties/screen_view/properties/screen_key                                                          | None.                                                                                                  | Field must be present; Value must equal requested screen key; Value must be stable for identical input                                              | returned |
| outputs.screen_view.name                                | Display name of the screen                                                | string              | #/components/schemas/Outputs/properties/screen_view/properties/name                                                                | None.                                                                                                  | Field must be present; Value must be a non-empty string; Value must reflect screen definition                                                       | returned |
| outputs.screen_view.etag                                | ETag representing the current screen view                                 | string              | #/components/schemas/Outputs/properties/screen_view/properties/etag                                                                | Mirrors Screen-ETag header                                                                             | Field must be present; Value must change when any included question/answer changes; Value must be an opaque token                                   | returned |
| outputs.screen_view.questions[]                         | Collection of visible questions on the screen                             | list[object]        | #/components/schemas/Outputs/properties/screen_view/properties/questions/items                                                     | Order reflects screen definition                                                                       | Array may be empty; Each item must validate against Question sub-schema; Iteration order must follow screen ordering                                | returned |
| outputs.screen_view.questions[].question_id             | Identifier of the question                                                | string (uuid)       | #/components/schemas/Outputs/properties/screen_view/properties/questions/items/properties/question_id                              | None.                                                                                                  | Field must be present; Value must validate as UUID; Value must belong to the requested screen                                                       | returned |
| outputs.screen_view.questions[].kind                    | Question kind/type                                                        | string              | #/components/schemas/Outputs/properties/screen_view/properties/questions/items/properties/kind                                     | E.g., short_string, long_text, number, boolean, enum_single                                            | Field must be present; Value must be one of the defined kinds; Value must match the question model                                                  | returned |
| outputs.screen_view.questions[].label                   | Display label for the question                                            | string              | #/components/schemas/Outputs/properties/screen_view/properties/questions/items/properties/label                                    | None.                                                                                                  | Field must be present; Value must be a non-empty string; Value must reflect question definition                                                     | returned |
| outputs.screen_view.questions[].options                 | Options for choice questions                                              | list[object]        | #/components/schemas/Outputs/properties/screen_view/properties/questions/items/properties/options/items                            | Present only for enum_single                                                                           | Field is optional; When present, each item must validate against the Options sub-schema; List may be empty                                          | returned |
| outputs.screen_view.questions[].ui                      | UI metadata for rendering                                                 | object              | #/components/schemas/Outputs/properties/screen_view/properties/questions/items/properties/ui                                       | Pass-through from questionnaire definition                                                             | Field is optional; When present, object must validate against UI sub-schema; Contents must be render metadata only                                  | returned |
| outputs.screen_view.questions[].answer                  | Current stored answer for this question, if any                           | object              | #/components/schemas/Outputs/properties/screen_view/properties/questions/items/properties/answer                                   | For enum_single the object contains option_id; for other kinds it contains the appropriate value field | Field is optional; When present, object must validate against Answer sub-schema; Object must represent the latest persisted value                   | returned |
| outputs.saved                                           | Envelope describing the saved entity in a PATCH                           | object              | #/components/schemas/Outputs/properties/saved                                                                                      | Returned by PATCH                                                                                      | Field must be present on successful PATCH; Object must validate against Saved sub-schema                                                            | returned |
| outputs.saved.question_id                               | Identifier of the question just saved                                     | string (uuid)       | #/components/schemas/Outputs/properties/saved/properties/question_id                                                               | None.                                                                                                  | Field must be present on successful PATCH; Value must validate as UUID; Value must match the request question_id                                    | returned |
| outputs.saved.state_version                             | Monotonic version of the saved answer                                     | integer             | #/components/schemas/Outputs/properties/saved/properties/state_version                                                             | Increments on each successful write                                                                    | Field must be present on successful PATCH; Value must be a non-negative integer; Value must increase when the answer changes                        | returned |
| outputs.visibility_delta                                | Delta of visibility changes following a save                              | object              | #/components/schemas/Outputs/properties/visibility_delta                                                                           | Returned by PATCH                                                                                      | Field is optional; When present, object must validate against Visibility Delta sub-schema; Object must be consistent with current answers           | returned |
| outputs.visibility_delta.now_visible[]                  | Questions that became visible                                             | list[object]        | #/components/schemas/Outputs/properties/visibility_delta/properties/now_visible/items                                              | Each item includes question metadata and any existing answer                                           | Array may be empty; Each item must validate against NowVisibleItem sub-schema; Item set must reflect evaluator output deterministically             | returned |
| outputs.visibility_delta.now_visible[].question.id      | Identifier of the newly visible question                                  | string (uuid)       | #/components/schemas/Outputs/properties/visibility_delta/properties/now_visible/items/properties/question/properties/id            | None.                                                                                                  | Field must be present; Value must validate as UUID; Value must reference a question on the requested screen                                         | returned |
| outputs.visibility_delta.now_visible[].question.kind    | Kind of the newly visible question                                        | string              | #/components/schemas/Outputs/properties/visibility_delta/properties/now_visible/items/properties/question/properties/kind          | None.                                                                                                  | Field must be present; Value must match the question model; Value must be one of the defined kinds                                                  | returned |
| outputs.visibility_delta.now_visible[].question.label   | Label of the newly visible question                                       | string              | #/components/schemas/Outputs/properties/visibility_delta/properties/now_visible/items/properties/question/properties/label         | None.                                                                                                  | Field must be present; Value must be a non-empty string; Value must reflect question definition                                                     | returned |
| outputs.visibility_delta.now_visible[].question.ui      | UI metadata for the newly visible question                                | object              | #/components/schemas/Outputs/properties/visibility_delta/properties/now_visible/items/properties/question/properties/ui            | Pass-through from questionnaire definition                                                             | Field is optional; When present, object must validate against UI sub-schema                                                                         | returned |
| outputs.visibility_delta.now_visible[].question.options | Options for the newly visible question                                    | list[object]        | #/components/schemas/Outputs/properties/visibility_delta/properties/now_visible/items/properties/question/properties/options/items | Present only for enum_single                                                                           | Field is optional; When present, list must validate against Options sub-schema                                                                      | returned |
| outputs.visibility_delta.now_visible[].answer           | Existing stored answer for the newly visible question, if any             | object              | #/components/schemas/Outputs/properties/visibility_delta/properties/now_visible/items/properties/answer                            | None.                                                                                                  | Field is optional; When present, object must validate against Answer sub-schema; Object must match the persisted value at the save time             | returned |
| outputs.visibility_delta.now_hidden[]                   | Questions that became hidden                                              | list[string (uuid)] | #/components/schemas/Outputs/properties/visibility_delta/properties/now_hidden/items                                               | None.                                                                                                  | Array may be empty; Each value must validate as UUID; Set must equal evaluator output deterministically                                             | returned |
| outputs.suppressed_answers[]                            | Question IDs whose answers should be ignored while hidden                 | list[string (uuid)] | #/components/schemas/Outputs/properties/suppressed_answers/items                                                                   | None.                                                                                                  | Array may be empty; Each value must validate as UUID; Set must be a subset of now_hidden IDs                                                        | returned |
| outputs.headers.etag                                    | ETag header returned by DELETE answer (updated entity tag)                | string              | #/components/schemas/Outputs/properties/headers/properties/etag                                                                    | Projection of HTTP header ETag                                                                         | Field is optional; When present, value must be an opaque token; Value must change when the target answer changes                                    | returned |
| outputs.headers.screen_etag                             | Screen-ETag header accompanying screen_view                               | string              | #/components/schemas/Outputs/properties/headers/properties/screen_etag                                                             | Projection of HTTP header Screen-ETag                                                                  | Field must be present on GET screen; Field must be present on successful PATCH; Value must match screen_view.etag                                   | returned |
| outputs.batch_result                                    | Envelope of per-item outcomes for batch upsert                            | object              | #/components/schemas/Outputs/properties/batch_result                                                                               | Returned by POST answers:batch                                                                         | Field is optional; When present, object must validate against Batch Result sub-schema                                                               | returned |
| outputs.batch_result.items[]                            | Items containing per-question outcomes                                    | list[object]        | #/components/schemas/Outputs/properties/batch_result/properties/items/items                                                        | Items correspond one-to-one with submitted items                                                       | Array may be empty; Each item must validate against Batch Result Item sub-schema; Item order must correspond to submitted order                     | returned |
| outputs.batch_result.items[].question_id                | Identifier of the question targeted by the item                           | string (uuid)       | #/components/schemas/Outputs/properties/batch_result/properties/items/items/properties/question_id                                 | None.                                                                                                  | Field must be present for each item; Value must validate as UUID; Value must correspond to a submitted item question_id                             | returned |
| outputs.batch_result.items[].outcome                    | Outcome for this batch item                                               | string (enum)       | #/components/schemas/Outputs/properties/batch_result/properties/items/items/properties/outcome                                     | Allowed: success, error                                                                                | Field must be present for each item; Value must be one of the allowed literals; Value must reflect persistence result deterministically             | returned |
| outputs.events[]                                        | Stream of domain events emitted by this operation                         | list[object]        | #/components/schemas/Outputs/properties/events/items                                                                               | Includes response.saved and response_set.deleted                                                       | Array may be empty; Each item must validate against Event sub-schema; Events list must be immutable after response                                  | returned |
| outputs.events[].type                                   | Event name                                                                | string              | #/components/schemas/Outputs/properties/events/items/properties/type                                                               | Allowed: response.saved, response_set.deleted                                                          | Field must be present; Value must be one of the allowed literals; Value must match emitted event type                                               | returned |
| outputs.events[].payload                                | Event payload                                                             | object              | #/components/schemas/Outputs/properties/events/items/properties/payload                                                            | Shape depends on event                                                                                 | Field must be present; Object must validate against the specific Event Payload sub-schema; Object must include required identifiers                 | returned |
| outputs.events[].payload.response_set_id                | Response set identifier associated with the event                         | string (uuid)       | #/components/schemas/Outputs/properties/events/items/properties/payload/properties/response_set_id                                 | Present for all events listed here                                                                     | Field must be present; Value must validate as UUID; Value must match the response set impacted by the operation                                     | returned |
| outputs.events[].payload.question_id                    | Question identifier (for response.saved only)                             | string (uuid)       | #/components/schemas/Outputs/properties/events/items/properties/payload/properties/question_id                                     | Present only for response.saved                                                                        | Field is optional; When present, value must validate as UUID; Value must match the saved question identifier                                        | returned |
| outputs.events[].payload.state_version                  | Saved answer version (for response.saved only)                            | integer             | #/components/schemas/Outputs/properties/events/items/properties/payload/properties/state_version                                   | Present only for response.saved                                                                        | Field is optional; When present, value must be a non-negative integer; Value must equal outputs.saved.state_version                                 | returned |

| Error Code                                       | Field Reference                        | Description                                                          | Likely Cause                   | Flow Impact                       | Behavioural AC Required |
| ------------------------------------------------ | -------------------------------------- | -------------------------------------------------------------------- | ------------------------------ | --------------------------------- | ----------------------- |
| PRE_RESPONSE_SET_ID_MISSING                      | response_set_id                        | response_set_id is required but not provided                         | Missing value                  | halt_pipeline                     | Yes                     |
| PRE_RESPONSE_SET_ID_INVALID_UUID                 | response_set_id                        | response_set_id is not a valid UUID                                  | Invalid format                 | halt_pipeline                     | Yes                     |
| PRE_RESPONSE_SET_ID_UNKNOWN                      | response_set_id                        | response_set_id does not refer to an existing response set           | Unknown reference              | halt_pipeline                     | Yes                     |
| PRE_SCREEN_KEY_MISSING                           | screen_key                             | screen_key is required but not provided                              | Missing value                  | halt_pipeline                     | Yes                     |
| PRE_SCREEN_KEY_UNKNOWN_KEY                       | screen_key                             | screen_key does not match a known screen key                         | Unknown reference              | halt_pipeline                     | Yes                     |
| PRE_SCREEN_KEY_UNDEFINED_SCREEN                  | screen_key                             | screen_key does not resolve to a defined screen                      | Undefined reference            | halt_pipeline                     | Yes                     |
| PRE_QUESTION_ID_MISSING                          | question_id                            | question_id is required but not provided                             | Missing value                  | halt_pipeline                     | Yes                     |
| PRE_QUESTION_ID_INVALID_UUID                     | question_id                            | question_id is not a valid UUID                                      | Invalid format                 | halt_pipeline                     | Yes                     |
| PRE_QUESTION_ID_UNKNOWN                          | question_id                            | question_id does not refer to an existing question                   | Unknown reference              | halt_pipeline                     | Yes                     |
| PRE_NAME_MISSING                                 | name                                   | name is required but not provided                                    | Missing value                  | halt_pipeline                     | Yes                     |
| PRE_NAME_EMPTY_AFTER_INPUT                       | name                                   | name is empty after normal user input                                | Empty value                    | halt_pipeline                     | Yes                     |
| PRE_NAME_EXCEEDS_MAX_LENGTH                      | name                                   | name exceeds product name length limits                              | Value too long                 | halt_pipeline                     | Yes                     |
| PRE_IF_MATCH_MISSING                             | if_match                               | If-Match header is required but not provided                         | Missing header                 | halt_pipeline                     | Yes                     |
| PRE_IF_MATCH_ETAG_MISMATCH                       | if_match                               | If-Match value does not equal the latest entity ETag                 | Stale or incorrect ETag        | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_BODY_MISSING                    | answerPatch                            | PATCH body is required but not provided                              | Missing body                   | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_SCHEMA_INVALID                  | answerPatch                            | PATCH body does not conform to the declared schema                   | Schema violation               | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_FIELDS_NOT_PERMITTED            | answerPatch                            | PATCH body contains fields not permitted for the question kind       | Disallowed fields              | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_VALUE_WRONG_TYPE                | answerPatch.value                      | value is not of the correct primitive type for the question          | Type mismatch                  | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_VALUE_NUMBER_NOT_FINITE         | answerPatch.value                      | value is a non-finite number (NaN or Infinity)                       | Out-of-range numeric           | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_VALUE_NOT_BOOLEAN_LITERAL       | answerPatch.value                      | value is not a literal true or false                                 | Type mismatch                  | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_OPTION_ID_INVALID_UUID          | answerPatch.option_id                  | option_id is not a valid UUID                                        | Invalid format                 | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_OPTION_ID_UNKNOWN               | answerPatch.option_id                  | option_id does not resolve to a known option for the question        | Unknown reference              | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_VALUE_TOKEN_IDENTIFIERS_MISSING | answerPatch.value_token                | neither option_id nor value_token is provided                        | Missing identifier             | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_VALUE_TOKEN_UNKNOWN             | answerPatch.value_token                | value_token does not resolve to a known option for the question      | Unknown reference              | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_VALUE_TOKEN_NOT_NORMALISED      | answerPatch.value_token                | value_token is not case and space normalised per catalogue           | Normalisation failure          | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_LABEL_NOT_STRING                | answerPatch.label                      | label is present but not a string                                    | Type mismatch                  | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_LABEL_TOO_LONG                  | answerPatch.label                      | label exceeds allowed length limits                                  | Value too long                 | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_LABEL_NOT_UTF8                  | answerPatch.label                      | label is not UTF-8 encodable                                         | Encoding error                 | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_ALLOW_NEW_LABEL_NOT_BOOLEAN     | answerPatch.allow_new_label            | allow_new_label is present but not boolean                           | Type mismatch                  | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_CLEAR_NOT_BOOLEAN               | answerPatch.clear                      | clear is present but not boolean                                     | Type mismatch                  | halt_pipeline                     | Yes                     |
| PRE_ANSWER_PATCH_CLEAR_TARGET_UNKNOWN            | answerPatch.clear                      | clear targets a question identifier that does not exist              | Unknown reference              | halt_pipeline                     | Yes                     |
| PRE_BATCH_REQUEST_BODY_MISSING                   | batch.request                          | Batch request body is required but not provided                      | Missing body                   | halt_pipeline                     | Yes                     |
| PRE_BATCH_REQUEST_ENVELOPE_FIELDS_MISSING        | batch.request                          | Batch envelope does not include required options and items           | Missing fields                 | halt_pipeline                     | Yes                     |
| PRE_BATCH_UPDATE_STRATEGY_MISSING                | batch.request.update_strategy          | update_strategy is required but not provided                         | Missing value                  | halt_pipeline                     | Yes                     |
| PRE_BATCH_UPDATE_STRATEGY_INVALID                | batch.request.update_strategy          | update_strategy is not one of the allowed literals                   | Invalid value                  | halt_pipeline                     | Yes                     |
| PRE_BATCH_UPDATE_STRATEGY_INCONSISTENT           | batch.request.update_strategy          | update_strategy is not applied consistently to all items             | Inconsistent configuration     | halt_pipeline                     | Yes                     |
| PRE_BATCH_CLEAR_MISSING_NOT_BOOLEAN              | batch.request.clear_missing            | clear_missing is present but not boolean                             | Type mismatch                  | halt_pipeline                     | Yes                     |
| PRE_BATCH_CLEAR_MISSING_DISALLOWED_FOR_MERGE     | batch.request.clear_missing            | clear_missing is true when merge strategy is used                    | Disallowed setting             | halt_pipeline                     | Yes                     |
| PRE_BATCH_ITEMS_MISSING                          | batch.request.items                    | items list is required but not provided                              | Missing list                   | halt_pipeline                     | Yes                     |
| PRE_BATCH_ITEMS_EMPTY                            | batch.request.items                    | items list is empty                                                  | Empty collection               | halt_pipeline                     | Yes                     |
| PRE_BATCH_ITEMS_SCHEMA_INVALID                   | batch.request.items                    | one or more items do not conform to the declared item schema         | Schema violation               | halt_pipeline                     | Yes                     |
| PRE_BATCH_ITEM_QUESTION_ID_MISSING               | batch.request.items[].question_id      | question_id is required but not provided for an item                 | Missing value                  | skip_downstream_step:persist_item | Yes                     |
| PRE_BATCH_ITEM_QUESTION_ID_INVALID_UUID          | batch.request.items[].question_id      | question_id is not a valid UUID for an item                          | Invalid format                 | skip_downstream_step:persist_item | Yes                     |
| PRE_BATCH_ITEM_QUESTION_ID_UNKNOWN               | batch.request.items[].question_id      | question_id does not refer to an existing question for an item       | Unknown reference              | skip_downstream_step:persist_item | Yes                     |
| PRE_BATCH_ITEM_ETAG_MISSING                      | batch.request.items[].etag             | etag is required but not provided for an item                        | Missing header                 | skip_downstream_step:persist_item | Yes                     |
| PRE_BATCH_ITEM_ETAG_MISMATCH                     | batch.request.items[].etag             | etag does not equal the latest entity ETag for an item               | Stale or incorrect ETag        | skip_downstream_step:persist_item | Yes                     |
| PRE_BATCH_ITEM_BODY_SCHEMA_INVALID               | batch.request.items[].body             | item body does not conform to the declared schema                    | Schema violation               | skip_downstream_step:persist_item | Yes                     |
| PRE_BATCH_ITEM_BODY_FIELDS_NOT_PERMITTED         | batch.request.items[].body             | item body contains fields not permitted for the question kind        | Disallowed fields              | skip_downstream_step:persist_item | Yes                     |
| PRE_BATCH_ITEM_BODY_CLEAR_SEMANTICS_INVALID      | batch.request.items[].body             | item clear semantics do not follow single-item rules                 | Invalid clear usage            | skip_downstream_step:persist_item | Yes                     |
| PRE_SCREEN_DEFINITION_NOT_ACCESSIBLE             | screen.definition                      | screen definition resource does not exist or is not readable         | Missing or unreadable resource | halt_pipeline                     | Yes                     |
| PRE_SCREEN_DEFINITION_INVALID_JSON               | screen.definition                      | screen definition does not parse as valid JSON                       | Parse error                    | halt_pipeline                     | Yes                     |
| PRE_SCREEN_DEFINITION_SCHEMA_INVALID             | screen.definition                      | screen definition does not conform to the referenced schema          | Schema violation               | halt_pipeline                     | Yes                     |
| PRE_VISIBILITY_RULES_NOT_ACCESSIBLE              | visibility.rules                       | visibility rules resource does not exist or is not readable          | Missing or unreadable resource | halt_pipeline                     | Yes                     |
| PRE_VISIBILITY_RULES_INVALID_JSON                | visibility.rules                       | visibility rules do not parse as valid JSON                          | Parse error                    | halt_pipeline                     | Yes                     |
| PRE_VISIBILITY_RULES_SCHEMA_INVALID              | visibility.rules                       | visibility rules do not conform to the referenced schema             | Schema violation               | halt_pipeline                     | Yes                     |
| PRE_EXISTING_ANSWER_LOOKUP_FAILED                | existing_answer                        | existing answer lookup did not complete without error                | Lookup failure                 | halt_pipeline                     | Yes                     |
| PRE_EXISTING_ANSWER_SCHEMA_INVALID               | existing_answer                        | existing answer record does not match the declared schema            | Schema violation               | halt_pipeline                     | Yes                     |
| PRE_EXISTING_ANSWERS_FOR_SCREEN_QUERY_FAILED     | existing_answers_for_screen            | existing answers query did not complete without error                | Query failure                  | halt_pipeline                     | Yes                     |
| PRE_EXISTING_ANSWERS_FOR_SCREEN_SCHEMA_INVALID   | existing_answers_for_screen            | one or more existing answer records do not match the declared schema | Schema violation               | halt_pipeline                     | Yes                     |
| PRE_EXISTING_ANSWERS_FOR_SCREEN_NOT_ITERABLE     | existing_answers_for_screen            | existing answers collection is not iterable without side effects     | Non-iterable collection        | halt_pipeline                     | Yes                     |
| PRE_VISIBLE_QUESTION_IDS_CALL_FAILED             | visibility_result.visible_question_ids | visibility evaluation call did not complete without error            | External call failure          | halt_pipeline                     | Yes                     |
| PRE_VISIBLE_QUESTION_IDS_SCHEMA_INVALID          | visibility_result.visible_question_ids | visible_question_ids does not match the declared schema              | Schema violation               | halt_pipeline                     | Yes                     |
| PRE_VISIBILITY_NOW_VISIBLE_CALL_FAILED           | visibility_delta.now_visible           | visibility delta call did not complete without error                 | External call failure          | halt_pipeline                     | Yes                     |
| PRE_VISIBILITY_NOW_VISIBLE_SCHEMA_INVALID        | visibility_delta.now_visible           | now_visible does not match the declared schema                       | Schema violation               | halt_pipeline                     | Yes                     |
| PRE_VISIBILITY_NOW_HIDDEN_CALL_FAILED            | visibility_delta.now_hidden            | visibility delta call did not complete without error                 | External call failure          | halt_pipeline                     | Yes                     |
| PRE_VISIBILITY_NOW_HIDDEN_SCHEMA_INVALID         | visibility_delta.now_hidden            | now_hidden does not match the declared schema                        | Schema violation               | halt_pipeline                     | Yes                     |
| PRE_VISIBILITY_SUPPRESSED_ANSWERS_CALL_FAILED    | visibility_delta.suppressed_answers    | visibility delta call did not complete without error                 | External call failure          | halt_pipeline                     | Yes                     |
| PRE_VISIBILITY_SUPPRESSED_ANSWERS_SCHEMA_INVALID | visibility_delta.suppressed_answers    | suppressed_answers does not match the declared schema                | Schema violation               | halt_pipeline                     | Yes                     |

| Error Code                                                     | Output Field Ref                                        | Description                                                                                                    | Likely Cause                                | Flow Impact        | Behavioural AC Required |
| -------------------------------------------------------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------- | ------------------ | ----------------------- |
| POST_OUTPUTS_RESPONSE_SET_ID_INVALID_UUID                      | outputs.response_set_id                                 | outputs.response_set_id does not validate as a UUID                                                            | Formatting error                            | block_finalization | Yes                     |
| POST_OUTPUTS_RESPONSE_SET_ID_MISSING                           | outputs.response_set_id                                 | outputs.response_set_id is missing on a successful POST or PATCH                                               | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_RESPONSE_SET_ID_MISMATCH_REQUEST                  | outputs.response_set_id                                 | outputs.response_set_id does not refer to the same response set as the request                                 | Incorrect identifier mapping                | block_finalization | Yes                     |
| POST_OUTPUTS_NAME_MISSING_ON_CREATE                            | outputs.name                                            | outputs.name is missing on POST create response                                                                | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_NAME_MISMATCH_PERSISTED                           | outputs.name                                            | outputs.name is not identical to the persisted response set name                                               | Persistence mismatch                        | block_finalization | Yes                     |
| POST_OUTPUTS_ETAG_MISSING_ON_PATCH                             | outputs.etag                                            | outputs.etag is missing on successful PATCH                                                                    | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_ETAG_NOT_OPAQUE                                   | outputs.etag                                            | outputs.etag is not treated as an opaque token                                                                 | Incorrect token handling                    | block_finalization | Yes                     |
| POST_OUTPUTS_ETAG_NOT_CHANGED_ON_UPDATE                        | outputs.etag                                            | outputs.etag did not change when the target answer changed                                                     | Versioning defect                           | block_finalization | Yes                     |
| POST_OUTPUTS_CREATED_AT_MISSING_ON_CREATE                      | outputs.created_at                                      | outputs.created_at is missing on POST create response                                                          | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_CREATED_AT_INVALID_FORMAT                         | outputs.created_at                                      | outputs.created_at is not RFC 3339 UTC format                                                                  | Formatting error                            | block_finalization | Yes                     |
| POST_OUTPUTS_CREATED_AT_MISMATCH_PERSISTED                     | outputs.created_at                                      | outputs.created_at does not match the persisted creation time                                                  | Persistence mismatch                        | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_MISSING_ON_GET                        | outputs.screen_view                                     | outputs.screen_view is missing on successful GET screen                                                        | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_MISSING_ON_PATCH                      | outputs.screen_view                                     | outputs.screen_view is missing on successful PATCH save                                                        | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_SCHEMA_INVALID                        | outputs.screen_view                                     | outputs.screen_view does not validate against the Screen View sub-schema                                       | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_SCREEN_KEY_MISSING                    | outputs.screen_view.screen_key                          | outputs.screen_view.screen_key is missing                                                                      | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_SCREEN_KEY_MISMATCH_REQUEST           | outputs.screen_view.screen_key                          | outputs.screen_view.screen_key does not equal the requested screen key                                         | Incorrect key propagation                   | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_SCREEN_KEY_NOT_STABLE                 | outputs.screen_view.screen_key                          | outputs.screen_view.screen_key is not stable for identical input                                               | Non-deterministic value                     | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_NAME_MISSING                          | outputs.screen_view.name                                | outputs.screen_view.name is missing                                                                            | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_NAME_EMPTY                            | outputs.screen_view.name                                | outputs.screen_view.name is not a non-empty string                                                             | Empty value                                 | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_NAME_MISMATCH_DEFINITION              | outputs.screen_view.name                                | outputs.screen_view.name does not reflect the screen definition                                                | Source-of-truth divergence                  | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_ETAG_MISSING                          | outputs.screen_view.etag                                | outputs.screen_view.etag is missing                                                                            | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_ETAG_NOT_CHANGED_ON_UPDATE            | outputs.screen_view.etag                                | outputs.screen_view.etag did not change when included question or answer changed                               | Versioning defect                           | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_ETAG_NOT_OPAQUE                       | outputs.screen_view.etag                                | outputs.screen_view.etag is not an opaque token                                                                | Incorrect token handling                    | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_QUESTIONS_ITEMS_SCHEMA_INVALID        | outputs.screen_view.questions[]                         | outputs.screen_view.questions[] contains item(s) that do not validate against the Question sub-schema          | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_QUESTIONS_ORDER_MISMATCH              | outputs.screen_view.questions[]                         | outputs.screen_view.questions[] iteration order does not follow screen ordering                                | Ordering defect                             | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_QUESTION_ID_MISSING                   | outputs.screen_view.questions[].question_id             | outputs.screen_view.questions[].question_id is missing                                                         | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_QUESTION_ID_INVALID_UUID              | outputs.screen_view.questions[].question_id             | outputs.screen_view.questions[].question_id is not a valid UUID                                                | Formatting error                            | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_QUESTION_ID_NOT_IN_SCREEN             | outputs.screen_view.questions[].question_id             | outputs.screen_view.questions[].question_id does not belong to the requested screen                            | Incorrect membership                        | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_KIND_MISSING                          | outputs.screen_view.questions[].kind                    | outputs.screen_view.questions[].kind is missing                                                                | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_KIND_INVALID                          | outputs.screen_view.questions[].kind                    | outputs.screen_view.questions[].kind is not one of the defined kinds                                           | Invalid literal                             | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_KIND_MISMATCH_MODEL                   | outputs.screen_view.questions[].kind                    | outputs.screen_view.questions[].kind does not match the question model                                         | Model mismatch                              | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_LABEL_MISSING                         | outputs.screen_view.questions[].label                   | outputs.screen_view.questions[].label is missing                                                               | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_LABEL_EMPTY                           | outputs.screen_view.questions[].label                   | outputs.screen_view.questions[].label is empty                                                                 | Empty value                                 | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_LABEL_MISMATCH_DEFINITION             | outputs.screen_view.questions[].label                   | outputs.screen_view.questions[].label does not reflect the question definition                                 | Source-of-truth divergence                  | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_OPTIONS_SCHEMA_INVALID                | outputs.screen_view.questions[].options                 | outputs.screen_view.questions[].options contains item(s) that do not validate against Options sub-schema       | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_UI_SCHEMA_INVALID                     | outputs.screen_view.questions[].ui                      | outputs.screen_view.questions[].ui does not validate against UI sub-schema                                     | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_UI_CONTAINS_NON_RENDER_DATA           | outputs.screen_view.questions[].ui                      | outputs.screen_view.questions[].ui contains non-render metadata content                                        | Extraneous metadata                         | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_ANSWER_SCHEMA_INVALID                 | outputs.screen_view.questions[].answer                  | outputs.screen_view.questions[].answer does not validate against Answer sub-schema                             | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_VIEW_ANSWER_NOT_LATEST                     | outputs.screen_view.questions[].answer                  | outputs.screen_view.questions[].answer does not represent the latest persisted value                           | Stale data                                  | block_finalization | Yes                     |
| POST_OUTPUTS_SAVED_MISSING_ON_PATCH                            | outputs.saved                                           | outputs.saved is missing on successful PATCH                                                                   | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SAVED_SCHEMA_INVALID                              | outputs.saved                                           | outputs.saved does not validate against Saved sub-schema                                                       | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_SAVED_QUESTION_ID_MISSING                         | outputs.saved.question_id                               | outputs.saved.question_id is missing on successful PATCH                                                       | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SAVED_QUESTION_ID_INVALID_UUID                    | outputs.saved.question_id                               | outputs.saved.question_id does not validate as UUID                                                            | Formatting error                            | block_finalization | Yes                     |
| POST_OUTPUTS_SAVED_QUESTION_ID_MISMATCH_REQUEST                | outputs.saved.question_id                               | outputs.saved.question_id does not match the request question_id                                               | Incorrect identifier mapping                | block_finalization | Yes                     |
| POST_OUTPUTS_SAVED_STATE_VERSION_MISSING                       | outputs.saved.state_version                             | outputs.saved.state_version is missing on successful PATCH                                                     | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_SAVED_STATE_VERSION_INVALID                       | outputs.saved.state_version                             | outputs.saved.state_version is not a non-negative integer                                                      | Type or range error                         | block_finalization | Yes                     |
| POST_OUTPUTS_SAVED_STATE_VERSION_NOT_INCREMENTED               | outputs.saved.state_version                             | outputs.saved.state_version did not increase when the answer changed                                           | Versioning defect                           | block_finalization | Yes                     |
| POST_OUTPUTS_VISIBILITY_DELTA_SCHEMA_INVALID                   | outputs.visibility_delta                                | outputs.visibility_delta does not validate against Visibility Delta sub-schema                                 | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_VISIBILITY_DELTA_INCONSISTENT_WITH_ANSWERS        | outputs.visibility_delta                                | outputs.visibility_delta is not consistent with current answers                                                | Inconsistent evaluator linkage              | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_ITEMS_SCHEMA_INVALID                  | outputs.visibility_delta.now_visible[]                  | outputs.visibility_delta.now_visible[] contains item(s) that do not validate against NowVisibleItem sub-schema | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_SET_MISMATCH_EVALUATOR                | outputs.visibility_delta.now_visible[]                  | outputs.visibility_delta.now_visible[] does not reflect evaluator output deterministically                     | Non-deterministic or stale evaluator result | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_ID_MISSING                   | outputs.visibility_delta.now_visible[].question.id      | outputs.visibility_delta.now_visible[].question.id is missing                                                  | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_ID_INVALID_UUID              | outputs.visibility_delta.now_visible[].question.id      | outputs.visibility_delta.now_visible[].question.id is not a valid UUID                                         | Formatting error                            | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_ID_NOT_IN_SCREEN             | outputs.visibility_delta.now_visible[].question.id      | outputs.visibility_delta.now_visible[].question.id does not reference a question on the requested screen       | Incorrect membership                        | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_KIND_MISSING                 | outputs.visibility_delta.now_visible[].question.kind    | outputs.visibility_delta.now_visible[].question.kind is missing                                                | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_KIND_MISMATCH_MODEL          | outputs.visibility_delta.now_visible[].question.kind    | outputs.visibility_delta.now_visible[].question.kind does not match the question model                         | Model mismatch                              | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_KIND_INVALID                 | outputs.visibility_delta.now_visible[].question.kind    | outputs.visibility_delta.now_visible[].question.kind is not one of the defined kinds                           | Invalid literal                             | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_LABEL_MISSING                | outputs.visibility_delta.now_visible[].question.label   | outputs.visibility_delta.now_visible[].question.label is missing                                               | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_LABEL_EMPTY                  | outputs.visibility_delta.now_visible[].question.label   | outputs.visibility_delta.now_visible[].question.label is empty                                                 | Empty value                                 | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_LABEL_MISMATCH_DEFINITION    | outputs.visibility_delta.now_visible[].question.label   | outputs.visibility_delta.now_visible[].question.label does not reflect the question definition                 | Source-of-truth divergence                  | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_UI_SCHEMA_INVALID            | outputs.visibility_delta.now_visible[].question.ui      | outputs.visibility_delta.now_visible[].question.ui does not validate against UI sub-schema                     | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_QUESTION_OPTIONS_SCHEMA_INVALID       | outputs.visibility_delta.now_visible[].question.options | outputs.visibility_delta.now_visible[].question.options list does not validate against Options sub-schema      | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_ANSWER_SCHEMA_INVALID                 | outputs.visibility_delta.now_visible[].answer           | outputs.visibility_delta.now_visible[].answer does not validate against Answer sub-schema                      | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_VISIBLE_ANSWER_NOT_MATCH_SAVE_TIME            | outputs.visibility_delta.now_visible[].answer           | outputs.visibility_delta.now_visible[].answer does not match the persisted value at save time                  | Stale data                                  | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_HIDDEN_VALUES_INVALID_UUID                    | outputs.visibility_delta.now_hidden[]                   | outputs.visibility_delta.now_hidden[] contains value(s) that are not valid UUIDs                               | Formatting error                            | block_finalization | Yes                     |
| POST_OUTPUTS_NOW_HIDDEN_SET_MISMATCH_EVALUATOR                 | outputs.visibility_delta.now_hidden[]                   | outputs.visibility_delta.now_hidden[] does not equal evaluator output deterministically                        | Non-deterministic or stale evaluator result | block_finalization | Yes                     |
| POST_OUTPUTS_SUPPRESSED_ANSWERS_VALUES_INVALID_UUID            | outputs.suppressed_answers[]                            | outputs.suppressed_answers[] contains value(s) that are not valid UUIDs                                        | Formatting error                            | block_finalization | Yes                     |
| POST_OUTPUTS_SUPPRESSED_ANSWERS_NOT_SUBSET                     | outputs.suppressed_answers[]                            | outputs.suppressed_answers[] is not a subset of now_hidden IDs                                                 | Consistency error                           | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_ETAG_NOT_OPAQUE                           | outputs.headers.etag                                    | outputs.headers.etag is not an opaque token                                                                    | Incorrect token handling                    | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_ETAG_NOT_CHANGED_ON_UPDATE                | outputs.headers.etag                                    | outputs.headers.etag did not change when the target answer changed                                             | Versioning defect                           | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING_ON_GET                | outputs.headers.screen_etag                             | outputs.headers.screen_etag is missing on GET screen                                                           | Omitted header projection                   | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING_ON_PATCH              | outputs.headers.screen_etag                             | outputs.headers.screen_etag is missing on successful PATCH                                                     | Omitted header projection                   | block_finalization | Yes                     |
| POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISMATCH_VIEW                 | outputs.headers.screen_etag                             | outputs.headers.screen_etag does not match outputs.screen_view.etag                                            | Inconsistent ETag values                    | block_finalization | Yes                     |
| POST_OUTPUTS_BATCH_RESULT_SCHEMA_INVALID                       | outputs.batch_result                                    | outputs.batch_result does not validate against Batch Result sub-schema                                         | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_BATCH_RESULT_ITEMS_SCHEMA_INVALID                 | outputs.batch_result.items[]                            | outputs.batch_result.items[] contains item(s) that do not validate against Batch Result Item sub-schema        | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_BATCH_RESULT_ITEMS_ORDER_MISMATCH                 | outputs.batch_result.items[]                            | outputs.batch_result.items[] order does not correspond to submitted order                                      | Ordering defect                             | block_finalization | Yes                     |
| POST_OUTPUTS_BATCH_RESULT_ITEM_QUESTION_ID_MISSING             | outputs.batch_result.items[].question_id                | outputs.batch_result.items[].question_id is missing                                                            | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_BATCH_RESULT_ITEM_QUESTION_ID_INVALID_UUID        | outputs.batch_result.items[].question_id                | outputs.batch_result.items[].question_id is not a valid UUID                                                   | Formatting error                            | block_finalization | Yes                     |
| POST_OUTPUTS_BATCH_RESULT_ITEM_QUESTION_ID_MISMATCH_SUBMITTED  | outputs.batch_result.items[].question_id                | outputs.batch_result.items[].question_id does not correspond to a submitted item question_id                   | Incorrect identifier mapping                | block_finalization | Yes                     |
| POST_OUTPUTS_BATCH_RESULT_ITEM_OUTCOME_MISSING                 | outputs.batch_result.items[].outcome                    | outputs.batch_result.items[].outcome is missing                                                                | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_BATCH_RESULT_ITEM_OUTCOME_INVALID_LITERAL         | outputs.batch_result.items[].outcome                    | outputs.batch_result.items[].outcome is not one of the allowed literals                                        | Invalid literal                             | block_finalization | Yes                     |
| POST_OUTPUTS_BATCH_RESULT_ITEM_OUTCOME_NOT_REFLECT_PERSISTENCE | outputs.batch_result.items[].outcome                    | outputs.batch_result.items[].outcome does not reflect the persistence result deterministically                 | Incorrect outcome mapping                   | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_ITEMS_SCHEMA_INVALID                       | outputs.events[]                                        | outputs.events[] contains item(s) that do not validate against Event sub-schema                                | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_LIST_MUTABLE                               | outputs.events[]                                        | outputs.events[] list is mutable after response                                                                | Post-response mutation                      | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_TYPE_MISSING                               | outputs.events[].type                                   | outputs.events[].type is missing                                                                               | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_TYPE_INVALID_LITERAL                       | outputs.events[].type                                   | outputs.events[].type is not one of the allowed literals                                                       | Invalid literal                             | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_TYPE_MISMATCH_EMITTED                      | outputs.events[].type                                   | outputs.events[].type does not match the emitted event type                                                    | Inconsistent event typing                   | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_PAYLOAD_MISSING                            | outputs.events[].payload                                | outputs.events[].payload is missing                                                                            | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_PAYLOAD_SCHEMA_INVALID                     | outputs.events[].payload                                | outputs.events[].payload does not validate against the specific Event Payload sub-schema                       | Schema mismatch                             | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_PAYLOAD_MISSING_IDENTIFIERS                | outputs.events[].payload                                | outputs.events[].payload does not include required identifiers                                                 | Missing identifiers                         | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_PAYLOAD_RESPONSE_SET_ID_MISSING            | outputs.events[].payload.response_set_id                | outputs.events[].payload.response_set_id is missing                                                            | Omitted field                               | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_PAYLOAD_RESPONSE_SET_ID_INVALID_UUID       | outputs.events[].payload.response_set_id                | outputs.events[].payload.response_set_id does not validate as UUID                                             | Formatting error                            | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_PAYLOAD_RESPONSE_SET_ID_MISMATCH_OPERATION | outputs.events[].payload.response_set_id                | outputs.events[].payload.response_set_id does not match the response set impacted by the operation             | Incorrect identifier mapping                | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_PAYLOAD_QUESTION_ID_INVALID_UUID           | outputs.events[].payload.question_id                    | outputs.events[].payload.question_id is present but not a valid UUID                                           | Formatting error                            | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_PAYLOAD_QUESTION_ID_MISMATCH_SAVED         | outputs.events[].payload.question_id                    | outputs.events[].payload.question_id does not match the saved question identifier                              | Incorrect identifier mapping                | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_PAYLOAD_STATE_VERSION_INVALID              | outputs.events[].payload.state_version                  | outputs.events[].payload.state_version is present but not a non-negative integer                               | Type or range error                         | block_finalization | Yes                     |
| POST_OUTPUTS_EVENTS_PAYLOAD_STATE_VERSION_MISMATCH_SAVED       | outputs.events[].payload.state_version                  | outputs.events[].payload.state_version does not equal outputs.saved.state_version                              | Inconsistent version linkage                | block_finalization | Yes                     |

| Error Code                               | Description                                              | Likely Cause                                   | Source (Step in Section 2.x)                        | Step ID (from Section 2.2.6)               | Reachability Rationale                                                                 | Flow Impact                       | Behavioural AC Required |
| ---------------------------------------- | -------------------------------------------------------- | ---------------------------------------------- | --------------------------------------------------- | ------------------------------------------ | -------------------------------------------------------------------------------------- | --------------------------------- | ----------------------- |
| RUN_CREATE_RESPONSE_SET_FAILED           | Creation of a new response set failed during execution   | Repository insert failure or transaction error | 2.2 – Create response set (U1)                      | STEP-1 Create response set                 | U1 requires creating a named response set; the create operation can fail at runtime    | halt_pipeline                     | Yes                     |
| RUN_PERSIST_RESPONSE_SET_FAILED          | Persisting and exposing the new response_set_id failed   | Commit failure or ID retrieval error           | 2.2 – Create response set (U2)                      | STEP-1 Create response set                 | U2 requires persisting and exposing response_set_id; persistence can fail after create | halt_pipeline                     | Yes                     |
| RUN_LIST_SCREEN_QUESTIONS_FAILED         | Loading screen questions for a screen_view failed        | Repository read error                          | 2.2 – Read screen (U11)                             | STEP-2 Read screen                         | U11 assembles a screen_view; this needs listing questions for the screen               | halt_pipeline                     | Yes                     |
| RUN_LOAD_VISIBILITY_RULES_FAILED         | Loading visibility rules for the screen failed           | Rules repository access error                  | 2.2 – Read screen (E1)                              | STEP-2 Read screen                         | E1 requires evaluating conditional visibility which starts by loading rules            | halt_pipeline                     | Yes                     |
| RUN_COMPUTE_VISIBLE_SET_FAILED           | Computing the set of visible questions failed            | Helper computation error or null state         | 2.2 – Read screen (E1)                              | STEP-2 Read screen                         | E1 mandates computing visibility; compute_visible_set may fail                         | halt_pipeline                     | Yes                     |
| RUN_HYDRATE_EXISTING_ANSWERS_FAILED      | Hydrating existing answers for the screen failed         | Answer repository query failure                | 2.2 – Read screen (U11)                             | STEP-2 Read screen                         | U11 assembles questions “with any existing answers”; hydration can fail                | halt_pipeline                     | Yes                     |
| RUN_ASSEMBLE_SCREEN_VIEW_FAILED          | Building the screen_view object failed                   | Composition error or serialization fault       | 2.2 – Read screen (U11, U12)                        | STEP-2 Read screen                         | U11/U12 require assembling and exposing screen_view; assembly may fail                 | halt_pipeline                     | Yes                     |
| RUN_COMPUTE_SCREEN_ETAG_FAILED           | Computing the Screen-ETag failed                         | ETag helper error                              | 2.2 – Read screen (U12)                             | STEP-2 Read screen                         | U12 exposes screen_view; spec returns a Screen-ETag header representing the view       | halt_pipeline                     | Yes                     |
| RUN_SAVE_ANSWER_UPSERT_FAILED            | Upserting a single answer failed                         | Repository upsert or transaction error         | 2.2 – Save single answer (U3, U4)                   | STEP-3 Save single answer                  | U3/U4 require accepting and persisting an answer; upsert can fail at runtime           | halt_pipeline                     | Yes                     |
| RUN_RESOLVE_ENUM_OPTION_FAILED           | Resolving enum option during save failed                 | Lookup helper or repository read error         | 2.2 – Save single answer (U9)                       | STEP-3 Save single answer                  | U9 requires resolving enum submissions to an option; resolution can fail               | halt_pipeline                     | Yes                     |
| RUN_COMPUTE_VISIBILITY_DELTA_FAILED      | Computing visibility_delta after save failed             | Helper computation error                       | 2.2 – Save single answer (E2)                       | STEP-3 Save single answer                  | E2 mandates computing a visibility_delta after a save                                  | halt_pipeline                     | Yes                     |
| RUN_INCLUDE_NOW_VISIBLE_HYDRATION_FAILED | Hydrating question+answer for newly visible items failed | Question or answer fetch failure               | 2.2 – Apply visibility changes after save (E3)      | STEP-4 Apply visibility changes after save | E3 requires including newly visible questions with metadata and any existing answer    | halt_pipeline                     | Yes                     |
| RUN_ASSEMBLE_SCREEN_VIEW_FAILED          | Building the updated screen_view failed                  | Composition error or serialization fault       | 2.2 – Apply visibility changes after save (O3, U12) | STEP-4 Apply visibility changes after save | O3/U12 require updated screen_view after save; building it can fail                    | halt_pipeline                     | Yes                     |
| RUN_COMPUTE_SCREEN_ETAG_FAILED           | Computing updated Screen-ETag failed                     | ETag helper error                              | 2.2 – Apply visibility changes after save (O3)      | STEP-4 Apply visibility changes after save | O3 notes returning updated screen_view with Screen-ETag                                | halt_pipeline                     | Yes                     |
| RUN_CLEAR_ANSWER_FAILED                  | Clearing a stored answer failed                          | Repository update/delete failure               | 2.2 – Clear an answer (U10, S2)                     | STEP-5 Clear an answer                     | U10/S2 require removing the stored value when clear is present                         | halt_pipeline                     | Yes                     |
| RUN_BATCH_PROCESS_ITEM_FAILED            | Processing a batch item failed and item was skipped      | Item-level execution error                     | 2.2 – Batch upsert answers (E4)                     | STEP-6 Batch upsert answers                | E4 requires per-item outcomes; individual item processing may fail                     | skip_downstream_step:persist_item | Yes                     |
| RUN_SAVE_ANSWER_UPSERT_FAILED            | Upserting an answer within batch failed                  | Repository upsert or transaction error         | 2.2 – Batch upsert answers (U16)                    | STEP-6 Batch upsert answers                | U16 supports batch upsert; per-item upsert can fail                                    | skip_downstream_step:persist_item | Yes                     |
| RUN_RESOLVE_ENUM_OPTION_FAILED           | Enum option resolution within batch failed               | Lookup helper or repository read error         | 2.2 – Batch upsert answers (O1, O2)                 | STEP-6 Batch upsert answers                | O1/O2 govern batch strategies; enum resolution during items can fail                   | skip_downstream_step:persist_item | Yes                     |
| RUN_DELETE_RESPONSE_SET_FAILED           | Deleting the response set failed                         | Repository delete or transaction error         | 2.2 – Delete response set (U14)                     | STEP-7 Delete response set                 | U14 requires deleting the response set; delete can fail                                | halt_pipeline                     | Yes                     |
| RUN_CASCADE_DELETE_ANSWERS_FAILED        | Cascading deletion of answers failed                     | Constraint or cascade failure                  | 2.2 – Delete response set (E5)                      | STEP-7 Delete response set                 | E5 mandates cascade-delete of all answers; cascade may fail                            | halt_pipeline                     | Yes                     |
| RUN_EMIT_RESPONSE_SAVED_FAILED           | Emitting response.saved event failed                     | Event bus/publisher error                      | 2.2 – Save single answer (U13)                      | STEP-3 Save single answer                  | U13 requires emitting response.saved after save                                        | block_finalization                | Yes                     |
| RUN_EMIT_RESPONSE_SET_DELETED_FAILED     | Emitting response_set.deleted event failed               | Event bus/publisher error                      | 2.2 – Delete response set (U15)                     | STEP-7 Delete response set                 | U15 requires emitting response_set.deleted after delete                                | block_finalization                | Yes                     |

| Error Code                              | Description                                                     | Likely Cause                                          | Impacted Steps                                         | EARS Refs                                                                                           | Flow Impact        | Behavioural AC Required |
| --------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------- | ------------------ | ----------------------- |
| ENV_DATABASE_UNAVAILABLE                | Database service is unreachable during read or write operations | Network outage, host down, connection refused         | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | U1, U2, U3, U4, U5, U6, U7, U8, U9, U10, U11, U12, U14, U16, E1, E2, E3, E4, E5, O1, O2, O3, S1, S2 | halt_pipeline      | Yes                     |
| ENV_DATABASE_DNS_FAILURE                | Database hostname cannot be resolved                            | DNS misconfiguration, upstream DNS failure            | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | U1, U2, U3, U4, U5, U6, U7, U8, U9, U10, U11, U12, U14, U16, E1, E2, E3, E4, E5, O1, O2, O3, S1, S2 | halt_pipeline      | Yes                     |
| ENV_DATABASE_TLS_HANDSHAKE_FAILED       | TLS/SSL handshake with database fails                           | Invalid certificate, protocol mismatch, expired CA    | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | U1, U2, U3, U4, U5, U6, U7, U8, U9, U10, U11, U12, U14, U16, E1, E2, E3, E4, E5, O1, O2, O3, S1, S2 | halt_pipeline      | Yes                     |
| ENV_DATABASE_PERMISSION_DENIED          | Database rejects credentials or lacks required privileges       | Wrong password, missing role, revoked grant           | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | U1, U2, U3, U4, U5, U6, U7, U8, U9, U10, U11, U12, U14, U16, E1, E2, E3, E4, E5, O1, O2, O3, S1, S2 | halt_pipeline      | Yes                     |
| ENV_DB_CONFIG_MISSING                   | Runtime configuration for database is missing                   | Absent connection URI, missing host/port settings     | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | U1, U2, U3, U4, U5, U6, U7, U8, U9, U10, U11, U12, U14, U16, E1, E2, E3, E4, E5, O1, O2, O3, S1, S2 | halt_pipeline      | Yes                     |
| ENV_DB_SECRET_MISSING                   | Required database secret is unavailable                         | Missing password/SSL key in secrets store             | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | U1, U2, U3, U4, U5, U6, U7, U8, U9, U10, U11, U12, U14, U16, E1, E2, E3, E4, E5, O1, O2, O3, S1, S2 | halt_pipeline      | Yes                     |
| ENV_MESSAGE_BROKER_UNAVAILABLE          | Message broker is unreachable for event emission                | Network outage, broker down, connection refused       | STEP-3, STEP-7                                         | U13, U15                                                                                            | block_finalization | Yes                     |
| ENV_MESSAGE_BROKER_DNS_FAILURE          | Message broker hostname cannot be resolved                      | DNS misconfiguration, upstream DNS failure            | STEP-3, STEP-7                                         | U13, U15                                                                                            | block_finalization | Yes                     |
| ENV_MESSAGE_BROKER_TLS_HANDSHAKE_FAILED | TLS/SSL handshake with message broker fails                     | Invalid certificate, protocol mismatch, expired CA    | STEP-3, STEP-7                                         | U13, U15                                                                                            | block_finalization | Yes                     |
| ENV_MESSAGE_BROKER_PERMISSION_DENIED    | Message broker rejects credentials or lacks publish rights      | Wrong credentials, missing publish ACL, revoked grant | STEP-3, STEP-7                                         | U13, U15                                                                                            | block_finalization | Yes                     |
| ENV_BROKER_RATE_LIMIT_EXCEEDED          | Broker publish rate limit or quota is exceeded                  | Per-topic or global rate limit hit                    | STEP-3, STEP-7                                         | U13, U15                                                                                            | block_finalization | Yes                     |
| ENV_BROKER_CONFIG_MISSING               | Runtime configuration for message broker is missing             | Absent broker URI, topic/exchange not configured      | STEP-3, STEP-7                                         | U13, U15                                                                                            | block_finalization | Yes                     |
| ENV_BROKER_SECRET_MISSING               | Required message broker secret is unavailable                   | Missing API key/password in secrets store             | STEP-3, STEP-7                                         | U13, U15                                                                                            | block_finalization | Yes                     |

### 6.1.1 Route exists for creating response sets

The codebase must declare an HTTP route `POST /response-sets` as a distinct handler.
**Refs:** STEP-1; U1, U2.

### 6.1.2 Route exists for reading a screen

The codebase must declare an HTTP route `GET /response-sets/{response_set_id}/screens/{screen_key}` as a distinct handler.
**Refs:** STEP-2; U11, U12, E1.

### 6.1.3 Route exists for single-answer save

The codebase must declare an HTTP route `PATCH /response-sets/{response_set_id}/answers/{question_id}` as a distinct handler.
**Refs:** STEP-3; U3, U4, U5.

### 6.1.4 Route exists for explicit clear of an answer

The codebase must declare an HTTP route `DELETE /response-sets/{response_set_id}/answers/{question_id}` as a distinct handler.
**Refs:** STEP-5; U10.

### 6.1.5 Route exists for batch upsert

The codebase must declare an HTTP route `POST /response-sets/{response_set_id}/answers:batch` as a distinct handler.
**Refs:** STEP-6; U16.

### 6.1.6 Route exists for deleting a response set

The codebase must declare an HTTP route `DELETE /response-sets/{response_set_id}` as a distinct handler.
**Refs:** STEP-7; U14.

### 6.1.7 Screen assembly is implemented as a reusable builder

A single, reusable screen_view assembly function/module must be used by both the screen read flow and the post-save refresh flow.
**Refs:** STEP-2, STEP-4; U11, U12, E3.

### 6.1.8 Visibility evaluation is called via in-process helpers

The codebase must import and call internal visibility helpers to compute visible sets and deltas, rather than invoking any HTTP client.
**Refs:** STEP-2, STEP-3, STEP-4; E1, E2, E3.

### 6.1.9 Answer hydration uses repository helpers

The screen read and post-save flows must hydrate existing answers by calling repository helpers dedicated to answers, not by inlining SQL in the route handlers.
**Refs:** STEP-2, STEP-4; U11.

### 6.1.10 Screen definition retrieval uses repository helpers

The screen read and post-save flows must obtain question definitions through repository helpers dedicated to screens, not by inlining SQL in the route handlers.
**Refs:** STEP-2, STEP-4; U11.

### 6.1.11 Unique constraint on (response_set_id, question_id)

The persistence layer must enforce a uniqueness constraint for responses on the composite key (response_set_id, question_id).
**Refs:** STEP-3; U5.

### 6.1.12 Response state_version column exists

The Response persistence model must include an integer field named state_version for versioning.
**Refs:** STEP-3; U4.

### 6.1.13 Screen-level ETag computed in a dedicated component

A distinct component/function must compute the screen_view ETag and be invoked by both screen reads and post-save responses.
**Refs:** STEP-2, STEP-4; U12.

### 6.1.14 Write endpoints declare If-Match as a required header

The route specifications for PATCH answer, DELETE answer, and DELETE response set must statically declare the HTTP header If-Match as required.
**Refs:** STEP-3, STEP-5, STEP-7; N4, N6.

### 6.1.15 No idempotency persistence is referenced by write paths

The write handlers must not reference any idempotency store or token persistence; concurrency control relies solely on ETag/If-Match.
**Refs:** STEP-3, STEP-5, STEP-6, STEP-7; N4.

### 6.1.16 Enum resolution implemented as a dedicated mapping call

Enum_single handling must use a callable that resolves submissions to option identifiers, separate from route and persistence code.
**Refs:** STEP-3, STEP-6; U9.

### 6.1.17 Text answers pass through unchanged in the persistence model

The persistence model and serializers must expose fields for short_string and long_text answers without trimming or normalising logic attached.
**Refs:** STEP-3; U6.

### 6.1.18 Number and boolean canonicalisation implemented in validation layer

Number finiteness checks and boolean literal checks must reside in a validation/canonicalisation module invoked before persistence.
**Refs:** STEP-3; U7, U8.

### 6.1.19 Domain events are declared as named constants/enums

The event types response.saved and response_set.deleted must be defined as named constants/enums in a single place in the codebase.
**Refs:** STEP-3, STEP-7; U13, U15.

### 6.1.20 Event emission is confined to save and delete flows

Only the single-answer save flow and the response-set delete flow may call the event publisher for the above event types.
**Refs:** STEP-3, STEP-7; U13, U15.

### 6.1.21 Outputs schema types exist for response bodies

Serialisable types must exist for outputs.screen_view, outputs.saved, outputs.visibility_delta, outputs.batch_result, and outputs.events.
**Refs:** STEP-2, STEP-3, STEP-4, STEP-6; Outputs table entries: outputs.screen_view, outputs.saved, outputs.visibility_delta, outputs.batch_result, outputs.events.

### 6.1.22 Now-visible item type is defined once and reused

A single serialisable type for visibility_delta.now_visible[] items (containing question metadata and optional answer) must be defined and reused.
**Refs:** STEP-3, STEP-4; Outputs table entries: outputs.visibility_delta.now_visible[].

### 6.1.23 Headers include Screen-ETag projection where screen_view is returned

Handlers that return a screen_view must also set a Screen-ETag HTTP header derived from the screen_view ETag.
**Refs:** STEP-2, STEP-4; U12; Outputs table entry: outputs.headers.screen_etag.

### 6.1.24 Batch result envelope is defined with ordered items

A serialisable batch_result with an items[] collection preserving submitted order must be defined and used by the batch route.
**Refs:** STEP-6; E4; Outputs table entries: outputs.batch_result, outputs.batch_result.items[].

### 6.1.25 Question kind enumeration excludes multi-value kinds

The question kind enumeration used by Epic E must include only the kinds referenced in Section 2 (short_string, long_text, number, boolean, enum_single).
**Refs:** STEP-3; U6, U7, U8, U9.

### 6.1.26 Screen read filters to visible questions via a dedicated filter step

The code must include a discrete step that filters questions to the visible set before assembling screen_view.
**Refs:** STEP-2; E1, U11.

### 6.1.27 Post-save response uses the same screen assembly path as GET

The save flow must call the same screen assembly function used by GET to build the updated screen_view.
**Refs:** STEP-4; E3, O3, U12.

### 6.2.1.1 Create response set returns identifier

**Given** a valid request to create a response set, **when** the client calls POST /response-sets, **then** the response includes the created identifier.
**Reference:** EARS U1, U2; Outputs fields: outputs.response_set_id.

### 6.2.1.2 Create response set echoes name

**Given** a valid request containing a name, **when** the client calls POST /response-sets, **then** the response returns that name.
**Reference:** EARS U1; Outputs fields: outputs.name.

### 6.2.1.3 Create response set returns creation timestamp

**Given** a valid create request, **when** POST /response-sets succeeds, **then** the response includes a creation timestamp.
**Reference:** EARS U2; Outputs fields: outputs.created_at.

### 6.2.1.4 Create response set returns entity ETag

**Given** a valid create request, **when** POST /response-sets succeeds, **then** the response includes the entity ETag.
**Reference:** EARS U2; Outputs fields: outputs.etag.

### 6.2.1.5 Read screen returns screen_view

**Given** an existing response set and screen key, **when** the client calls GET /response-sets/{id}/screens/{screen_key}, **then** the response includes a screen_view object.
**Reference:** EARS U11, U12; Outputs fields: outputs.screen_view.

### 6.2.1.6 Read screen provides Screen-ETag matching the view

**Given** a successful GET screen, **when** the response is returned, **then** Screen-ETag equals the screen_view.etag value.
**Reference:** EARS U12; Outputs fields: outputs.headers.screen_etag, outputs.screen_view.etag.

### 6.2.1.7 Screen contains only visible questions

**Given** a request to read a screen, **when** conditional visibility is evaluated, **then** only visible questions appear in screen_view.questions[].
**Reference:** EARS E1, S1; Outputs fields: outputs.screen_view.questions[].

### 6.2.1.8 Save single answer returns saved envelope

**Given** a valid single-answer save, **when** PATCH /response-sets/{id}/answers/{question_id} succeeds, **then** the response includes a saved envelope with the question identifier.
**Reference:** EARS U3, U4, U5; Outputs fields: outputs.saved, outputs.saved.question_id.

### 6.2.1.9 Save single answer returns updated entity ETag

**Given** a valid single-answer save, **when** PATCH succeeds, **then** the response includes an updated entity ETag.
**Reference:** EARS U4; Outputs fields: outputs.etag.

### 6.2.1.10 Save single answer returns updated screen_view

**Given** a valid single-answer save, **when** PATCH succeeds, **then** the response includes an updated screen_view.
**Reference:** EARS O3, U12; Outputs fields: outputs.screen_view.

### 6.2.1.11 Save single answer provides updated Screen-ETag

**Given** a successful PATCH save that returns screen_view, **when** the response is returned, **then** Screen-ETag equals the returned screen_view.etag.
**Reference:** EARS O3, U12; Outputs fields: outputs.headers.screen_etag, outputs.screen_view.etag.

### 6.2.1.12 Saved answer links to request identifiers

**Given** a successful PATCH save, **when** the response is returned, **then** response_set_id matches the path set and saved.question_id matches the path question_id.
**Reference:** EARS U5; Outputs fields: outputs.response_set_id, outputs.saved.question_id.

### 6.2.1.13 Finite number saves succeed

**Given** a number-kind question with a finite value, **when** the client saves the value, **then** the response returns saved and updated ETag.
**Reference:** EARS U7; Outputs fields: outputs.saved, outputs.etag.

### 6.2.1.14 Boolean literal saves succeed

**Given** a boolean-kind question with a true/false value, **when** the client saves the value, **then** the response returns saved and updated ETag.
**Reference:** EARS U8; Outputs fields: outputs.saved, outputs.etag.

### 6.2.1.15 Enum selection is represented by option_id

**Given** an enum_single question with a valid submission, **when** the client saves the selection, **then** the returned screen_view answer represents the selection with option_id.
**Reference:** EARS U9; Outputs fields: outputs.screen_view.questions[].answer.

### 6.2.1.16 Text answers round-trip unchanged

**Given** a short_string or long_text answer, **when** the client saves the value, **then** the returned screen_view shows that answer value unchanged.
**Reference:** EARS U6; Outputs fields: outputs.screen_view.questions[].answer.

### 6.2.1.17 Clear via DELETE returns updated ETag

**Given** an existing answer, **when** the client calls DELETE /response-sets/{id}/answers/{question_id}, **then** the response returns an updated entity ETag.
**Reference:** EARS U10; Outputs fields: outputs.headers.etag.

### 6.2.1.18 Clear via PATCH removes the answer from the view

**Given** an existing answer and clear=true in PATCH, **when** the save succeeds, **then** the returned screen_view omits the answer for that question.
**Reference:** EARS U10, S2; Outputs fields: outputs.screen_view.questions[].answer.

### 6.2.1.19 Mandatory question may be temporarily empty

**Given** a mandatory question with an empty entry during data entry, **when** the client saves that entry, **then** the response returns saved without additional blocking content requirements.
**Reference:** EARS S3; Outputs fields: outputs.saved.

### 6.2.1.20 Save returns visibility_delta container

**Given** an answer save, **when** PATCH succeeds, **then** the response includes a visibility_delta object (which may be empty).
**Reference:** EARS E2; Outputs fields: outputs.visibility_delta.

### 6.2.1.21 Newly visible questions are listed by identifier

**Given** saving an answer causes questions to become visible, **when** PATCH returns, **then** now_visible[] contains each newly visible question’s identifier.
**Reference:** EARS E2, E3; Outputs fields: outputs.visibility_delta.now_visible[].question.id.

### 6.2.1.22 Newly visible questions include metadata

**Given** saving an answer causes questions to become visible, **when** PATCH returns, **then** each now_visible item includes kind and label metadata.
**Reference:** EARS E3; Outputs fields: outputs.visibility_delta.now_visible[].question.kind, outputs.visibility_delta.now_visible[].question.label.

### 6.2.1.23 Newly visible questions include any existing answer

**Given** a newly visible question has a stored answer, **when** PATCH returns, **then** the corresponding now_visible item includes that answer.
**Reference:** EARS E3; Outputs fields: outputs.visibility_delta.now_visible[].answer.

### 6.2.1.24 Newly hidden questions are listed

**Given** saving an answer causes questions to become hidden, **when** PATCH returns, **then** now_hidden[] lists those question identifiers.
**Reference:** EARS E2; Outputs fields: outputs.visibility_delta.now_hidden[].

### 6.2.1.25 Suppressed answers identify hidden questions to ignore

**Given** saving an answer causes questions to become hidden, **when** PATCH returns, **then** suppressed_answers[] lists question identifiers whose answers should be ignored while hidden.
**Reference:** EARS E2; Outputs fields: outputs.suppressed_answers[].

### 6.2.1.26 Batch upsert returns batch_result envelope

**Given** an administrative batch request, **when** POST answers:batch succeeds, **then** the response includes a batch_result object.
**Reference:** EARS U16, E4; Outputs fields: outputs.batch_result.

### 6.2.1.27 Batch items preserve submission order

**Given** a batch submission with multiple items, **when** POST answers:batch returns, **then** batch_result.items[] preserves the submitted item order.
**Reference:** EARS U16, E4; Outputs fields: outputs.batch_result.items[].

### 6.2.1.28 Batch per-item outcome is reported

**Given** a batch submission, **when** POST answers:batch returns, **then** each items[] entry contains an outcome literal indicating success or error.
**Reference:** EARS E4; Outputs fields: outputs.batch_result.items[].outcome.

### 6.2.1.29 Save emits response.saved event in response stream

**Given** a successful single-answer save, **when** PATCH returns, **then** the events[] stream contains an event of type response.saved with payload identifiers.
**Reference:** EARS U13; Outputs fields: outputs.events[], outputs.events[].type, outputs.events[].payload.response_set_id, outputs.events[].payload.question_id, outputs.events[].payload.state_version.

### 6.2.1.30 Delete response set emits response_set.deleted event

**Given** a successful response-set deletion, **when** DELETE /response-sets/{id} returns, **then** the events[] stream contains an event of type response_set.deleted with the response_set_id.
**Reference:** EARS U15, E5; Outputs fields: outputs.events[], outputs.events[].type, outputs.events[].payload.response_set_id.

### 6.2.2.1 response_set_id missing

**Criterion:** Given a request that targets a response set, when response_set_id is not provided, then the system returns a contract error.
**Error Mode:** PRE_RESPONSE_SET_ID_MISSING
**Reference:** Inputs: response_set_id

### 6.2.2.2 response_set_id invalid UUID

**Criterion:** Given a request with response_set_id, when the identifier is not a valid UUID, then the system returns a contract error.
**Error Mode:** PRE_RESPONSE_SET_ID_INVALID_UUID
**Reference:** Inputs: response_set_id

### 6.2.2.3 response_set_id unknown

**Criterion:** Given a request with response_set_id, when the identifier does not refer to an existing response set, then the system returns a contract error.
**Error Mode:** PRE_RESPONSE_SET_ID_UNKNOWN
**Reference:** Inputs: response_set_id

### 6.2.2.4 screen_key missing

**Criterion:** Given a screen read request, when screen_key is not provided, then the system returns a contract error.
**Error Mode:** PRE_SCREEN_KEY_MISSING
**Reference:** Inputs: screen_key

### 6.2.2.5 screen_key unknown

**Criterion:** Given a screen read request, when screen_key does not match any known screen, then the system returns a contract error.
**Error Mode:** PRE_SCREEN_KEY_UNKNOWN_KEY
**Reference:** Inputs: screen_key

### 6.2.2.6 screen definition undefined

**Criterion:** Given a screen read request, when screen_key cannot be resolved to a defined screen, then the system returns a contract error.
**Error Mode:** PRE_SCREEN_KEY_UNDEFINED_SCREEN
**Reference:** Inputs: screen_key

### 6.2.2.7 question_id missing

**Criterion:** Given a save or delete answer request, when question_id is not provided, then the system returns a contract error.
**Error Mode:** PRE_QUESTION_ID_MISSING
**Reference:** Inputs: question_id

### 6.2.2.8 question_id invalid UUID

**Criterion:** Given a save or delete answer request, when question_id is not a valid UUID, then the system returns a contract error.
**Error Mode:** PRE_QUESTION_ID_INVALID_UUID
**Reference:** Inputs: question_id

### 6.2.2.9 question_id unknown

**Criterion:** Given a save or delete answer request, when question_id does not refer to an existing question, then the system returns a contract error.
**Error Mode:** PRE_QUESTION_ID_UNKNOWN
**Reference:** Inputs: question_id

### 6.2.2.10 name missing

**Criterion:** Given a create response set request, when name is not provided, then the system returns a contract error.
**Error Mode:** PRE_NAME_MISSING
**Reference:** Inputs: name

### 6.2.2.11 name empty

**Criterion:** Given a create response set request, when name is provided but empty, then the system returns a contract error.
**Error Mode:** PRE_NAME_EMPTY_AFTER_INPUT
**Reference:** Inputs: name

### 6.2.2.12 name too long

**Criterion:** Given a create response set request, when name exceeds the allowed length, then the system returns a contract error.
**Error Mode:** PRE_NAME_EXCEEDS_MAX_LENGTH
**Reference:** Inputs: name

### 6.2.2.13 If-Match missing

**Criterion:** Given a write that requires concurrency control, when the If-Match header is absent, then the system returns a conflict error.
**Error Mode:** PRE_IF_MATCH_MISSING
**Reference:** Inputs: if_match

### 6.2.2.14 If-Match mismatch

**Criterion:** Given a write with If-Match, when the ETag does not match the latest entity tag, then the system returns a conflict error.
**Error Mode:** PRE_IF_MATCH_ETAG_MISMATCH
**Reference:** Inputs: if_match

### 6.2.2.15 PATCH body missing

**Criterion:** Given a save answer request, when the PATCH body is absent, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_BODY_MISSING
**Reference:** Inputs: answerPatch

### 6.2.2.16 PATCH schema invalid

**Criterion:** Given a save answer request, when the PATCH body violates the declared schema for the question kind, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_SCHEMA_INVALID
**Reference:** Inputs: answerPatch

### 6.2.2.17 PATCH fields not permitted

**Criterion:** Given a save answer request, when the PATCH body includes fields not permitted for the question kind, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_FIELDS_NOT_PERMITTED
**Reference:** Inputs: answerPatch

### 6.2.2.18 value wrong type

**Criterion:** Given a save answer request, when value is not of the correct primitive type for the question, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_VALUE_WRONG_TYPE
**Reference:** Inputs: answerPatch.value

### 6.2.2.19 number not finite

**Criterion:** Given a number-kind save, when value is NaN or Infinity, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_VALUE_NUMBER_NOT_FINITE
**Reference:** Inputs: answerPatch.value

### 6.2.2.20 value not boolean literal

**Criterion:** Given a boolean-kind save, when value is not literal true or false, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_VALUE_NOT_BOOLEAN_LITERAL
**Reference:** Inputs: answerPatch.value

### 6.2.2.21 option_id invalid UUID

**Criterion:** Given an enum_single save, when option_id is malformed, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_OPTION_ID_INVALID_UUID
**Reference:** Inputs: answerPatch.option_id

### 6.2.2.22 option_id unknown

**Criterion:** Given an enum_single save, when option_id does not resolve to a known option for the question, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_OPTION_ID_UNKNOWN
**Reference:** Inputs: answerPatch.option_id

### 6.2.2.23 enum submission missing identifier

**Criterion:** Given an enum_single save, when neither option_id nor value-token is supplied, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_VALUE_TOKEN_IDENTIFIERS_MISSING
**Reference:** Inputs: answerPatch.value (canonical token)

### 6.2.2.24 enum value token unknown

**Criterion:** Given an enum_single save by value token, when the token does not resolve to a known option, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_VALUE_TOKEN_UNKNOWN
**Reference:** Inputs: answerPatch.value (canonical token)

### 6.2.2.25 label not string

**Criterion:** Given a save with a label field, when label is not a string, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_LABEL_NOT_STRING
**Reference:** Inputs: answerPatch.label

### 6.2.2.26 label too long

**Criterion:** Given a save with label, when label exceeds the allowed length, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_LABEL_TOO_LONG
**Reference:** Inputs: answerPatch.label

### 6.2.2.27 allow_new_label not boolean

**Criterion:** Given a save with allow_new_label, when the value is not boolean, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_ALLOW_NEW_LABEL_NOT_BOOLEAN
**Reference:** Inputs: answerPatch.allow_new_label

### 6.2.2.28 clear not boolean

**Criterion:** Given a save with clear flag, when clear is not boolean, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_CLEAR_NOT_BOOLEAN
**Reference:** Inputs: answerPatch.clear

### 6.2.2.29 clear targets unknown question

**Criterion:** Given a clear operation, when the targeted question does not exist, then the system returns a contract error.
**Error Mode:** PRE_ANSWER_PATCH_CLEAR_TARGET_UNKNOWN
**Reference:** Inputs: question_id

### 6.2.2.30 batch body missing

**Criterion:** Given a batch upsert request, when the request body is absent, then the system returns a contract error.
**Error Mode:** PRE_BATCH_REQUEST_BODY_MISSING
**Reference:** Inputs: batch.request

### 6.2.2.31 batch envelope fields missing

**Criterion:** Given a batch upsert request, when required envelope fields are missing, then the system returns a contract error.
**Error Mode:** PRE_BATCH_REQUEST_ENVELOPE_FIELDS_MISSING
**Reference:** Inputs: batch.request

### 6.2.2.32 update_strategy missing

**Criterion:** Given a batch upsert request, when update_strategy is not provided, then the system returns a contract error.
**Error Mode:** PRE_BATCH_UPDATE_STRATEGY_MISSING
**Reference:** Inputs: batch.request.update_strategy

### 6.2.2.33 update_strategy invalid

**Criterion:** Given a batch upsert request, when update_strategy is not one of the allowed literals, then the system returns a contract error.
**Error Mode:** PRE_BATCH_UPDATE_STRATEGY_INVALID
**Reference:** Inputs: batch.request.update_strategy

### 6.2.2.34 clear_missing not boolean

**Criterion:** Given a batch upsert request, when clear_missing is present and not boolean, then the system returns a contract error.
**Error Mode:** PRE_BATCH_CLEAR_MISSING_NOT_BOOLEAN
**Reference:** Inputs: batch.request.clear_missing

### 6.2.2.35 items missing

**Criterion:** Given a batch upsert request, when items are not provided, then the system returns a contract error.
**Error Mode:** PRE_BATCH_ITEMS_MISSING
**Reference:** Inputs: batch.request.items

### 6.2.2.36 items empty

**Criterion:** Given a batch upsert request, when items are provided but empty, then the system returns a contract error.
**Error Mode:** PRE_BATCH_ITEMS_EMPTY
**Reference:** Inputs: batch.request.items

### 6.2.2.37 items schema invalid

**Criterion:** Given a batch upsert request, when one or more items violate the declared item schema, then the system returns a contract error.
**Error Mode:** PRE_BATCH_ITEMS_SCHEMA_INVALID
**Reference:** Inputs: batch.request.items[]

### 6.2.2.38 batch item question_id missing

**Criterion:** Given a batch item, when question_id is absent, then that item is reported as an error outcome.
**Error Mode:** PRE_BATCH_ITEM_QUESTION_ID_MISSING
**Reference:** Inputs: batch.request.items[].question_id; Outputs: outputs.batch_result.items[].outcome

### 6.2.2.39 batch item question_id invalid

**Criterion:** Given a batch item, when question_id is not a valid UUID, then that item is reported as an error outcome.
**Error Mode:** PRE_BATCH_ITEM_QUESTION_ID_INVALID_UUID
**Reference:** Inputs: batch.request.items[].question_id; Outputs: outputs.batch_result.items[].outcome

### 6.2.2.40 batch item question_id unknown

**Criterion:** Given a batch item, when question_id does not resolve to a known question, then that item is reported as an error outcome.
**Error Mode:** PRE_BATCH_ITEM_QUESTION_ID_UNKNOWN
**Reference:** Inputs: batch.request.items[].question_id; Outputs: outputs.batch_result.items[].outcome

### 6.2.2.41 batch item etag missing

**Criterion:** Given a batch item, when etag is not provided, then that item is reported as an error outcome.
**Error Mode:** PRE_BATCH_ITEM_ETAG_MISSING
**Reference:** Inputs: batch.request.items[].etag; Outputs: outputs.batch_result.items[].outcome

### 6.2.2.42 batch item etag mismatch

**Criterion:** Given a batch item, when etag does not match the latest entity tag, then that item is reported as an error outcome.
**Error Mode:** PRE_BATCH_ITEM_ETAG_MISMATCH
**Reference:** Inputs: batch.request.items[].etag; Outputs: outputs.batch_result.items[].outcome

### 6.2.2.43 batch item body schema invalid

**Criterion:** Given a batch item, when the body violates the declared schema, then that item is reported as an error outcome.
**Error Mode:** PRE_BATCH_ITEM_BODY_SCHEMA_INVALID
**Reference:** Inputs: batch.request.items[].body; Outputs: outputs.batch_result.items[].outcome

### 6.2.2.44 batch item disallowed fields

**Criterion:** Given a batch item, when body contains fields not permitted for its question kind, then that item is reported as an error outcome.
**Error Mode:** PRE_BATCH_ITEM_BODY_FIELDS_NOT_PERMITTED
**Reference:** Inputs: batch.request.items[].body; Outputs: outputs.batch_result.items[].outcome

### 6.2.2.45 screen definition inaccessible

**Criterion:** Given a screen read, when the screen definition resource cannot be accessed, then the system returns a contract error.
**Error Mode:** PRE_SCREEN_DEFINITION_NOT_ACCESSIBLE
**Reference:** Inputs: screen.definition

### 6.2.2.46 screen definition invalid JSON

**Criterion:** Given a screen read, when the screen definition does not parse as valid JSON, then the system returns a contract error.
**Error Mode:** PRE_SCREEN_DEFINITION_INVALID_JSON
**Reference:** Inputs: screen.definition

### 6.2.2.47 screen definition schema invalid

**Criterion:** Given a screen read, when the screen definition violates its schema, then the system returns a contract error.
**Error Mode:** PRE_SCREEN_DEFINITION_SCHEMA_INVALID
**Reference:** Inputs: screen.definition

### 6.2.2.48 visibility rules inaccessible

**Criterion:** Given a screen read, when visibility rules cannot be accessed, then the system returns a contract error.
**Error Mode:** PRE_VISIBILITY_RULES_NOT_ACCESSIBLE
**Reference:** Inputs: visibility.rules

### 6.2.2.49 visibility rules invalid JSON

**Criterion:** Given a screen read, when visibility rules do not parse as JSON, then the system returns a contract error.
**Error Mode:** PRE_VISIBILITY_RULES_INVALID_JSON
**Reference:** Inputs: visibility.rules

### 6.2.2.50 visibility rules schema invalid

**Criterion:** Given a screen read, when visibility rules violate the expected schema, then the system returns a contract error.
**Error Mode:** PRE_VISIBILITY_RULES_SCHEMA_INVALID
**Reference:** Inputs: visibility.rules

### 6.2.2.51 existing answer lookup failed

**Criterion:** Given a read or save that hydrates an answer, when the existing answer query fails, then the system returns a contract error.
**Error Mode:** PRE_EXISTING_ANSWER_LOOKUP_FAILED
**Reference:** Inputs: existing_answer

### 6.2.2.52 existing answers for screen query failed

**Criterion:** Given a screen read, when the existing answers query fails, then the system returns a contract error.
**Error Mode:** PRE_EXISTING_ANSWERS_FOR_SCREEN_QUERY_FAILED
**Reference:** Inputs: existing_answers_for_screen

### 6.2.2.53 visible ids call failed

**Criterion:** Given a screen read, when the visibility evaluation call fails to return visible_question_ids, then the system returns a contract error.
**Error Mode:** PRE_VISIBLE_QUESTION_IDS_CALL_FAILED
**Reference:** Inputs: visibility_result.visible_question_ids

### 6.2.2.54 visibility now_visible call failed

**Criterion:** Given a save operation, when the delta computation fails to return now_visible, then the system returns a contract error.
**Error Mode:** PRE_VISIBILITY_NOW_VISIBLE_CALL_FAILED
**Reference:** Inputs: visibility_delta.now_visible

### 6.2.2.55 visibility now_hidden call failed

**Criterion:** Given a save operation, when the delta computation fails to return now_hidden, then the system returns a contract error.
**Error Mode:** PRE_VISIBILITY_NOW_HIDDEN_CALL_FAILED
**Reference:** Inputs: visibility_delta.now_hidden

### 6.2.2.56 visibility suppressed_answers call failed

**Criterion:** Given a save operation, when the delta computation fails to return suppressed_answers, then the system returns a contract error.
**Error Mode:** PRE_VISIBILITY_SUPPRESSED_ANSWERS_CALL_FAILED
**Reference:** Inputs: visibility_delta.suppressed_answers

### 6.2.2.57 Create response set failed at runtime

**Criterion:** Given a valid create request, when the repository insert fails, then the system returns a runtime contract error.
**Error Mode:** RUN_CREATE_RESPONSE_SET_FAILED
**Reference:** Inputs: name

### 6.2.2.58 Persist response_set_id failed at runtime

**Criterion:** Given a valid create request, when persistence or ID retrieval fails post-insert, then the system returns a runtime contract error.
**Error Mode:** RUN_PERSIST_RESPONSE_SET_FAILED
**Reference:** Inputs: name

### 6.2.2.59 List screen questions failed

**Criterion:** Given a screen read, when loading questions fails, then the system returns a runtime contract error.
**Error Mode:** RUN_LIST_SCREEN_QUESTIONS_FAILED
**Reference:** Inputs: screen_key

### 6.2.2.60 Load visibility rules failed

**Criterion:** Given a screen read, when loading visibility rules fails, then the system returns a runtime contract error.
**Error Mode:** RUN_LOAD_VISIBILITY_RULES_FAILED
**Reference:** Inputs: screen_key

### 6.2.2.61 Compute visible set failed

**Criterion:** Given a screen read, when computing the visible set fails, then the system returns a runtime contract error.
**Error Mode:** RUN_COMPUTE_VISIBLE_SET_FAILED
**Reference:** Inputs: screen_key

### 6.2.2.62 Hydrate existing answers failed

**Criterion:** Given a screen read, when hydrating existing answers fails, then the system returns a runtime contract error.
**Error Mode:** RUN_HYDRATE_EXISTING_ANSWERS_FAILED
**Reference:** Inputs: response_set_id

### 6.2.2.63 Assemble screen_view failed

**Criterion:** Given a screen read, when assembling the screen_view fails, then the system returns a runtime contract error.
**Error Mode:** RUN_ASSEMBLE_SCREEN_VIEW_FAILED
**Reference:** Outputs: outputs.screen_view

### 6.2.2.64 Compute screen ETag failed

**Criterion:** Given a screen read, when computing Screen-ETag fails, then the system returns a runtime contract error.
**Error Mode:** RUN_COMPUTE_SCREEN_ETAG_FAILED
**Reference:** Outputs: outputs.screen_view.etag, outputs.headers.screen_etag

### 6.2.2.65 Save upsert failed

**Criterion:** Given a valid single-answer save, when the upsert fails, then the system returns a runtime contract error.
**Error Mode:** RUN_SAVE_ANSWER_UPSERT_FAILED
**Reference:** Inputs: response_set_id, question_id

### 6.2.2.66 Resolve enum option failed

**Criterion:** Given an enum_single save, when resolving the option fails, then the system returns a runtime contract error.
**Error Mode:** RUN_RESOLVE_ENUM_OPTION_FAILED
**Reference:** Inputs: answerPatch.option_id, answerPatch.value

### 6.2.2.67 Compute visibility_delta failed

**Criterion:** Given a successful write, when computing visibility_delta fails, then the system returns a runtime contract error.
**Error Mode:** RUN_COMPUTE_VISIBILITY_DELTA_FAILED
**Reference:** Outputs: outputs.visibility_delta

### 6.2.2.68 Hydrate newly visible items failed

**Criterion:** Given newly visible questions after save, when hydrating their question+answer fails, then the system returns a runtime contract error.
**Error Mode:** RUN_INCLUDE_NOW_VISIBLE_HYDRATION_FAILED
**Reference:** Outputs: outputs.visibility_delta.now_visible[]

### 6.2.2.69 Re-assemble updated screen_view failed

**Criterion:** Given a post-save refresh, when assembling the updated screen_view fails, then the system returns a runtime contract error.
**Error Mode:** RUN_ASSEMBLE_SCREEN_VIEW_FAILED
**Reference:** Outputs: outputs.screen_view

### 6.2.2.70 Compute updated Screen-ETag failed

**Criterion:** Given a post-save refresh, when computing the new Screen-ETag fails, then the system returns a runtime contract error.
**Error Mode:** RUN_COMPUTE_SCREEN_ETAG_FAILED
**Reference:** Outputs: outputs.screen_view.etag, outputs.headers.screen_etag

### 6.2.2.71 Clear answer failed

**Criterion:** Given a clear operation, when clearing the stored value fails, then the system returns a runtime contract error.
**Error Mode:** RUN_CLEAR_ANSWER_FAILED
**Reference:** Inputs: response_set_id, question_id

### 6.2.2.72 Batch item processing failed

**Criterion:** Given a batch upsert, when an individual item processing fails, then that item is returned with an error outcome.
**Error Mode:** RUN_BATCH_PROCESS_ITEM_FAILED
**Reference:** Outputs: outputs.batch_result.items[].outcome

### 6.2.2.73 Batch upsert item save failed

**Criterion:** Given a batch upsert, when an item’s upsert fails, then that item is returned with an error outcome.
**Error Mode:** RUN_SAVE_ANSWER_UPSERT_FAILED
**Reference:** Outputs: outputs.batch_result.items[].outcome

### 6.2.2.74 Batch enum resolution failed

**Criterion:** Given a batch upsert, when an item’s enum resolution fails, then that item is returned with an error outcome.
**Error Mode:** RUN_RESOLVE_ENUM_OPTION_FAILED
**Reference:** Outputs: outputs.batch_result.items[].outcome

### 6.2.2.75 Delete response set failed

**Criterion:** Given a delete response set request, when the delete operation fails, then the system returns a runtime contract error.
**Error Mode:** RUN_DELETE_RESPONSE_SET_FAILED
**Reference:** Inputs: response_set_id

### 6.2.2.76 Cascade delete answers failed

**Criterion:** Given a delete response set request, when cascading the answers delete fails, then the system returns a runtime contract error.
**Error Mode:** RUN_CASCADE_DELETE_ANSWERS_FAILED
**Reference:** Inputs: response_set_id

### 6.2.2.77 Emit response.saved event failed

**Criterion:** Given a successful save, when emitting response.saved fails, then the system returns a runtime contract error that blocks finalisation.
**Error Mode:** RUN_EMIT_RESPONSE_SAVED_FAILED
**Reference:** Outputs: outputs.events[]

### 6.2.2.78 Emit response_set.deleted event failed

**Criterion:** Given a successful response set delete, when emitting response_set.deleted fails, then the system returns a runtime contract error that blocks finalisation.
**Error Mode:** RUN_EMIT_RESPONSE_SET_DELETED_FAILED
**Reference:** Outputs: outputs.events[]

### 6.2.2.79 outputs.response_set_id missing

**Criterion:** Given a successful POST or PATCH, when outputs.response_set_id is absent, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_RESPONSE_SET_ID_MISSING
**Reference:** Outputs: outputs.response_set_id

### 6.2.2.80 outputs.response_set_id invalid

**Criterion:** Given a successful POST or PATCH, when outputs.response_set_id is not a UUID, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_RESPONSE_SET_ID_INVALID_UUID
**Reference:** Outputs: outputs.response_set_id

### 6.2.2.81 outputs.response_set_id mismatch

**Criterion:** Given a successful operation, when outputs.response_set_id does not match the affected response set, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_RESPONSE_SET_ID_MISMATCH_REQUEST
**Reference:** Outputs: outputs.response_set_id

### 6.2.2.82 outputs.name missing on create

**Criterion:** Given a successful POST create, when outputs.name is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_NAME_MISSING_ON_CREATE
**Reference:** Outputs: outputs.name

### 6.2.2.83 outputs.etag missing on PATCH

**Criterion:** Given a successful PATCH, when outputs.etag is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_ETAG_MISSING_ON_PATCH
**Reference:** Outputs: outputs.etag

### 6.2.2.84 outputs.created_at missing on create

**Criterion:** Given a successful POST create, when outputs.created_at is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_CREATED_AT_MISSING_ON_CREATE
**Reference:** Outputs: outputs.created_at

### 6.2.2.85 outputs.screen_view missing on GET

**Criterion:** Given a successful screen GET, when outputs.screen_view is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SCREEN_VIEW_MISSING_ON_GET
**Reference:** Outputs: outputs.screen_view

### 6.2.2.86 outputs.screen_view missing on PATCH

**Criterion:** Given a successful PATCH, when outputs.screen_view is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SCREEN_VIEW_MISSING_ON_PATCH
**Reference:** Outputs: outputs.screen_view

### 6.2.2.87 outputs.screen_view.etag missing

**Criterion:** Given a successful GET or PATCH that returns screen_view, when screen_view.etag is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SCREEN_VIEW_ETAG_MISSING
**Reference:** Outputs: outputs.screen_view.etag

### 6.2.2.88 outputs.screen_view.questions schema invalid

**Criterion:** Given a successful screen response, when any questions[] item violates its schema, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SCREEN_VIEW_QUESTIONS_ITEMS_SCHEMA_INVALID
**Reference:** Outputs: outputs.screen_view.questions[]

### 6.2.2.89 outputs.screen_view.question_id missing

**Criterion:** Given a successful screen response, when a question lacks question_id, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SCREEN_VIEW_QUESTION_ID_MISSING
**Reference:** Outputs: outputs.screen_view.questions[].question_id

### 6.2.2.90 outputs.screen_view.kind missing

**Criterion:** Given a successful screen response, when a question lacks kind, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SCREEN_VIEW_KIND_MISSING
**Reference:** Outputs: outputs.screen_view.questions[].kind

### 6.2.2.91 outputs.screen_view.label missing

**Criterion:** Given a successful screen response, when a question lacks label, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SCREEN_VIEW_LABEL_MISSING
**Reference:** Outputs: outputs.screen_view.questions[].label

### 6.2.2.92 outputs.screen_view.answer schema invalid

**Criterion:** Given a successful screen response, when an answer object violates the Answer sub-schema, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SCREEN_VIEW_ANSWER_SCHEMA_INVALID
**Reference:** Outputs: outputs.screen_view.questions[].answer

### 6.2.2.93 outputs.saved missing on PATCH

**Criterion:** Given a successful PATCH, when outputs.saved is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SAVED_MISSING_ON_PATCH
**Reference:** Outputs: outputs.saved

### 6.2.2.94 outputs.saved.question_id missing

**Criterion:** Given a successful PATCH, when outputs.saved.question_id is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SAVED_QUESTION_ID_MISSING
**Reference:** Outputs: outputs.saved.question_id

### 6.2.2.95 outputs.saved.state_version missing

**Criterion:** Given a successful PATCH, when outputs.saved.state_version is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SAVED_STATE_VERSION_MISSING
**Reference:** Outputs: outputs.saved.state_version

### 6.2.2.96 outputs.visibility_delta schema invalid

**Criterion:** Given a successful PATCH with delta, when outputs.visibility_delta violates its schema, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_VISIBILITY_DELTA_SCHEMA_INVALID
**Reference:** Outputs: outputs.visibility_delta

### 6.2.2.97 outputs.visibility_delta.now_visible schema invalid

**Criterion:** Given a successful PATCH with delta, when any now_visible[] item violates its schema, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_NOW_VISIBLE_ITEMS_SCHEMA_INVALID
**Reference:** Outputs: outputs.visibility_delta.now_visible[]

### 6.2.2.98 outputs.visibility_delta.now_hidden UUIDs invalid

**Criterion:** Given a successful PATCH with delta, when now_hidden[] contains non-UUIDs, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_NOW_HIDDEN_VALUES_INVALID_UUID
**Reference:** Outputs: outputs.visibility_delta.now_hidden[]

### 6.2.2.99 outputs.suppressed_answers UUIDs invalid

**Criterion:** Given a successful PATCH with delta, when suppressed_answers[] contains non-UUIDs, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_SUPPRESSED_ANSWERS_VALUES_INVALID_UUID
**Reference:** Outputs: outputs.suppressed_answers[]

### 6.2.2.100 outputs.headers.screen_etag missing on GET

**Criterion:** Given a successful screen GET, when outputs.headers.screen_etag is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING_ON_GET
**Reference:** Outputs: outputs.headers.screen_etag

### 6.2.2.101 outputs.headers.screen_etag missing on PATCH

**Criterion:** Given a successful PATCH that returns screen_view, when outputs.headers.screen_etag is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING_ON_PATCH
**Reference:** Outputs: outputs.headers.screen_etag

### 6.2.2.102 outputs.batch_result schema invalid

**Criterion:** Given a successful batch operation, when outputs.batch_result violates its schema, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_BATCH_RESULT_SCHEMA_INVALID
**Reference:** Outputs: outputs.batch_result

### 6.2.2.103 outputs.batch_result.items schema invalid

**Criterion:** Given a successful batch operation, when any batch_result.items[] violates its schema, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_BATCH_RESULT_ITEMS_SCHEMA_INVALID
**Reference:** Outputs: outputs.batch_result.items[]

### 6.2.2.104 outputs.batch_result.items[].question_id missing

**Criterion:** Given a successful batch operation, when an item lacks question_id, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_BATCH_RESULT_ITEM_QUESTION_ID_MISSING
**Reference:** Outputs: outputs.batch_result.items[].question_id

### 6.2.2.105 outputs.batch_result.items[].outcome missing

**Criterion:** Given a successful batch operation, when an item lacks outcome, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_BATCH_RESULT_ITEM_OUTCOME_MISSING
**Reference:** Outputs: outputs.batch_result.items[].outcome

### 6.2.2.106 outputs.events schema invalid

**Criterion:** Given a successful operation that emits events, when outputs.events[] violates its schema, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_EVENTS_ITEMS_SCHEMA_INVALID
**Reference:** Outputs: outputs.events[]

### 6.2.2.107 outputs.events[].type missing

**Criterion:** Given an emitted event, when type is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_EVENTS_TYPE_MISSING
**Reference:** Outputs: outputs.events[].type

### 6.2.2.108 outputs.events[].payload missing

**Criterion:** Given an emitted event, when payload is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_EVENTS_PAYLOAD_MISSING
**Reference:** Outputs: outputs.events[].payload

### 6.2.2.109 outputs.events[].payload.response_set_id missing

**Criterion:** Given an emitted event, when payload.response_set_id is missing, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_EVENTS_PAYLOAD_RESPONSE_SET_ID_MISSING
**Reference:** Outputs: outputs.events[].payload.response_set_id

### 6.2.2.110 outputs.events[].payload.question_id invalid

**Criterion:** Given a response.saved event, when payload.question_id is present but not a valid UUID, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_EVENTS_PAYLOAD_QUESTION_ID_INVALID_UUID
**Reference:** Outputs: outputs.events[].payload.question_id

### 6.2.2.111 outputs.events[].payload.state_version invalid

**Criterion:** Given a response.saved event, when payload.state_version is present but not a non-negative integer, then the system returns a contract error.
**Error Mode:** POST_OUTPUTS_EVENTS_PAYLOAD_STATE_VERSION_INVALID
**Reference:** Outputs: outputs.events[].payload.state_version

6.3.1.1 Evaluate visibility before assembly
**Given** a screen is requested, **when** the request is received, **then** the system must initiate computation of the visible question set before any screen assembly begins.
**Reference:** E1

6.3.1.2 Filter questions to the visible set
**Given** the visible set has been computed, **when** preparing the screen payload, **then** the system must initiate filtering to include only questions in the visible set.
**Reference:** E1

6.3.1.3 Hydrate answers after filtering
**Given** the visible question set is known, **when** preparing the screen payload, **then** the system must initiate hydration of existing answers only for those visible questions.
**Reference:** E1, S1

6.3.1.4 Assemble screen after hydration
**Given** visible questions and their hydrated answers, **when** building the response, **then** the system must initiate construction of the screen view.
**Reference:** E1

6.3.1.5 Compute visibility delta after save
**Given** a single-answer save completes successfully, **when** post-write processing starts, **then** the system must initiate computation of the visibility delta.
**Reference:** E2

6.3.1.6 Hydrate newly visible items after delta
**Given** the visibility delta identifies newly visible questions, **when** applying the delta, **then** the system must initiate hydration of each newly visible question’s metadata and any existing answer.
**Reference:** E3

6.3.1.7 Rebuild screen after applying delta
**Given** visibility changes have been applied, **when** finalising the save response, **then** the system must initiate assembly of the updated screen view for the same screen.
**Reference:** E3

6.3.1.8 Omit hidden questions during assembly
**Given** a question is hidden, **when** assembling a screen, **then** the system must initiate omission of that question from the assembled screen.
**Reference:** S1

6.3.1.9 Clear before delta when clear=true
**Given** an answer clear flag is present, **when** processing the write, **then** the system must initiate removal of the stored value prior to computing the visibility delta.
**Reference:** S2, E2

6.3.1.10 Mandatory questions do not block flow
**Given** a question is mandatory, **when** an empty value is saved during data entry, **then** the system must proceed to initiate visibility delta computation and subsequent screen assembly without gating.
**Reference:** S3, E2

6.3.1.11 Batch processes items sequentially
**Given** a valid batch request, **when** an item finishes (success), **then** the system must initiate processing of the next item until all items are evaluated.
**Reference:** E4

6.3.1.12 Batch continues after item failure
**Given** a batch item fails, **when** its outcome is recorded, **then** the system must initiate processing of the next item without aborting subsequent items.
**Reference:** E4

6.3.1.13 Cascade delete answers after set delete
**Given** a response-set delete is requested, **when** the top-level delete succeeds, **then** the system must initiate cascade deletion of all associated answers.
**Reference:** E5

#### 6.3.2.1

**Title:** Create response set failure halts pipeline
**Criterion:** Given a valid create request, when the create operation fails at runtime, then halt STEP-1 (Create response set) and stop propagation to STEP-2 (Read screen).
**Error Mode:** `RUN_CREATE_RESPONSE_SET_FAILED`
**Reference:** (step: STEP-1)

#### 6.3.2.2

**Title:** Persisting new identifier failure halts pipeline
**Criterion:** Given a created response set, when persisting/exposing its identifier fails at runtime, then halt STEP-1 (Create response set) and stop propagation to STEP-2 (Read screen).
**Error Mode:** `RUN_PERSIST_RESPONSE_SET_FAILED`
**Reference:** (step: STEP-1)

#### 6.3.2.3

**Title:** Listing screen questions failure halts pipeline
**Criterion:** Given a screen read request, when loading questions for the screen fails, then halt STEP-2 (Read screen) and stop propagation to STEP-3 (Save single answer).
**Error Mode:** `RUN_LIST_SCREEN_QUESTIONS_FAILED`
**Reference:** (step: STEP-2)

#### 6.3.2.4

**Title:** Loading visibility rules failure halts pipeline
**Criterion:** Given a screen read request, when loading visibility rules fails, then halt STEP-2 (Read screen) and stop propagation to STEP-3 (Save single answer).
**Error Mode:** `RUN_LOAD_VISIBILITY_RULES_FAILED`
**Reference:** (step: STEP-2)

#### 6.3.2.5

**Title:** Computing visible set failure halts pipeline
**Criterion:** Given a screen read request, when computing the visible question set fails, then halt STEP-2 (Read screen) and stop propagation to STEP-3 (Save single answer).
**Error Mode:** `RUN_COMPUTE_VISIBLE_SET_FAILED`
**Reference:** (step: STEP-2)

#### 6.3.2.6

**Title:** Hydrating existing answers failure halts pipeline
**Criterion:** Given a screen read request, when hydrating existing answers fails, then halt STEP-2 (Read screen) and stop propagation to STEP-3 (Save single answer).
**Error Mode:** `RUN_HYDRATE_EXISTING_ANSWERS_FAILED`
**Reference:** (step: STEP-2)

#### 6.3.2.7

**Title:** Assembling screen view failure halts pipeline
**Criterion:** Given a screen read request, when assembling the screen view fails, then halt STEP-2 (Read screen) and stop propagation to STEP-3 (Save single answer).
**Error Mode:** `RUN_ASSEMBLE_SCREEN_VIEW_FAILED`
**Reference:** (step: STEP-2)

#### 6.3.2.8

**Title:** Computing Screen-ETag failure halts pipeline
**Criterion:** Given a screen read request, when computing the Screen-ETag fails, then halt STEP-2 (Read screen) and stop propagation to STEP-3 (Save single answer).
**Error Mode:** `RUN_COMPUTE_SCREEN_ETAG_FAILED`
**Reference:** (step: STEP-2)

#### 6.3.2.9

**Title:** Saving single answer upsert failure halts pipeline
**Criterion:** Given a single-answer save, when the upsert fails, then halt STEP-3 (Save single answer) and stop propagation to STEP-4 (Apply visibility changes after save).
**Error Mode:** `RUN_SAVE_ANSWER_UPSERT_FAILED`
**Reference:** (step: STEP-3)

#### 6.3.2.10

**Title:** Enum option resolution failure halts pipeline
**Criterion:** Given a single-answer save for an enum question, when resolving the option fails, then halt STEP-3 (Save single answer) and stop propagation to STEP-4 (Apply visibility changes after save).
**Error Mode:** `RUN_RESOLVE_ENUM_OPTION_FAILED`
**Reference:** (step: STEP-3)

#### 6.3.2.11

**Title:** Computing visibility delta failure halts pipeline
**Criterion:** Given a successful write, when computing the visibility delta fails, then halt STEP-3 (Save single answer) and stop propagation to STEP-4 (Apply visibility changes after save).
**Error Mode:** `RUN_COMPUTE_VISIBILITY_DELTA_FAILED`
**Reference:** (step: STEP-3)

#### 6.3.2.12

**Title:** Hydrating newly visible items failure halts pipeline
**Criterion:** Given a post-save delta with newly visible questions, when hydrating those items fails, then halt STEP-4 (Apply visibility changes after save) and stop propagation to STEP-4 final screen assembly.
**Error Mode:** `RUN_INCLUDE_NOW_VISIBLE_HYDRATION_FAILED`
**Reference:** (step: STEP-4)

#### 6.3.2.13

**Title:** Clearing an answer failure halts pipeline
**Criterion:** Given a clear operation, when removing the stored value fails, then halt STEP-5 (Clear an answer) and stop propagation to returning the DELETE success outcome.
**Error Mode:** `RUN_CLEAR_ANSWER_FAILED`
**Reference:** (step: STEP-5)

#### 6.3.2.14

**Title:** Batch item processing failure skips item persistence
**Criterion:** Given a batch upsert, when an item processing fails, then skip persisting that item and stop propagation to the item’s persist step within STEP-6 (Batch upsert answers).
**Error Mode:** `RUN_BATCH_PROCESS_ITEM_FAILED`
**Reference:** (step: STEP-6)

#### 6.3.2.15

**Title:** Deleting response set failure halts pipeline
**Criterion:** Given a delete request for a response set, when the delete operation fails, then halt STEP-7 (Delete response set) and stop propagation to cascade deletion of answers.
**Error Mode:** `RUN_DELETE_RESPONSE_SET_FAILED`
**Reference:** (step: STEP-7)

#### 6.3.2.16

**Title:** Cascade deleting answers failure halts pipeline
**Criterion:** Given a response-set delete, when cascading deletion of answers fails, then halt STEP-7 (Delete response set) and stop propagation to completing the delete operation.
**Error Mode:** `RUN_CASCADE_DELETE_ANSWERS_FAILED`
**Reference:** (step: STEP-7)

#### 6.3.2.17

**Title:** Emitting response.saved failure blocks finalisation
**Criterion:** Given a successful single-answer save, when emitting the response.saved event fails, then prevent finalisation of STEP-3 (Save single answer) and stop propagation to returning the success response until the failure is handled.
**Error Mode:** `RUN_EMIT_RESPONSE_SAVED_FAILED`
**Reference:** (step: STEP-3)

#### 6.3.2.18

**Title:** Emitting response_set.deleted failure blocks finalisation
**Criterion:** Given a successful response-set delete, when emitting the response_set.deleted event fails, then prevent finalisation of STEP-7 (Delete response set) and stop propagation to returning the success response until the failure is handled.
**Error Mode:** `RUN_EMIT_RESPONSE_SET_DELETED_FAILED`
**Reference:** (step: STEP-7)

#### 6.3.2.19

**Title:** Database unreachable halts the pipeline
**Criterion:** Given any pipeline step requires database access, when the database is unreachable, then halt the active step (one of STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7) and stop propagation to all later steps (if halted at STEP-1: prevent STEP-2–STEP-7; at STEP-2: prevent STEP-3–STEP-7; …), as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_DATABASE_UNAVAILABLE`
**Reference:** database connectivity (steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7)

#### 6.3.2.20

**Title:** Database DNS failure halts the pipeline
**Criterion:** Given any pipeline step requires database access, when database hostname resolution fails, then halt the active step (one of STEP-1–STEP-7) and stop propagation to all later steps as enumerated above, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_DATABASE_DNS_FAILURE`
**Reference:** database DNS resolution (steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7)

#### 6.3.2.21

**Title:** Database TLS handshake failure halts the pipeline
**Criterion:** Given secure database connections are required, when the TLS/SSL handshake with the database fails, then halt the active step (one of STEP-1–STEP-7) and stop propagation to all later steps as enumerated above, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_DATABASE_TLS_HANDSHAKE_FAILED`
**Reference:** database TLS (steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7)

#### 6.3.2.22

**Title:** Database permission denied halts the pipeline
**Criterion:** Given database credentials are required, when the database rejects authentication or privileges, then halt the active step (one of STEP-1–STEP-7) and stop propagation to all later steps as enumerated above, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_DATABASE_PERMISSION_DENIED`
**Reference:** database authentication/authorisation (steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7)

#### 6.3.2.23

**Title:** Missing database configuration halts the pipeline
**Criterion:** Given runtime configuration is required for database access, when required database configuration is missing, then halt the active step (one of STEP-1–STEP-7) and stop propagation to all later steps as enumerated above, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_DB_CONFIG_MISSING`
**Reference:** database runtime configuration (steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7)

#### 6.3.2.24

**Title:** Missing database secret halts the pipeline
**Criterion:** Given secrets are required for database access, when the required database secret is unavailable, then halt the active step (one of STEP-1–STEP-7) and stop propagation to all later steps as enumerated above, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_DB_SECRET_MISSING`
**Reference:** database secrets (steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7)

#### 6.3.2.25

**Title:** Message broker unreachable blocks finalisation of emitting steps
**Criterion:** Given domain events must be published, when the message broker is unreachable, then prevent finalisation of the emitting step (STEP-3 or STEP-7 as applicable) and stop propagation to returning a success outcome from that step, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_MESSAGE_BROKER_UNAVAILABLE`
**Reference:** message broker publish (steps: STEP-3, STEP-7)

#### 6.3.2.26

**Title:** Message broker DNS failure blocks finalisation of emitting steps
**Criterion:** Given domain events must be published, when the broker hostname cannot be resolved, then prevent finalisation of the emitting step (STEP-3 or STEP-7) and stop propagation to returning a success outcome from that step, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_MESSAGE_BROKER_DNS_FAILURE`
**Reference:** message broker DNS (steps: STEP-3, STEP-7)

#### 6.3.2.27

**Title:** Message broker TLS handshake failure blocks finalisation of emitting steps
**Criterion:** Given secure broker connections are required, when the TLS/SSL handshake with the broker fails, then prevent finalisation of the emitting step (STEP-3 or STEP-7) and stop propagation to returning a success outcome from that step, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_MESSAGE_BROKER_TLS_HANDSHAKE_FAILED`
**Reference:** message broker TLS (steps: STEP-3, STEP-7)

#### 6.3.2.28

**Title:** Message broker permission denied blocks finalisation of emitting steps
**Criterion:** Given broker credentials/permissions are required, when the broker denies authentication or publish rights, then prevent finalisation of the emitting step (STEP-3 or STEP-7) and stop propagation to returning a success outcome from that step, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_MESSAGE_BROKER_PERMISSION_DENIED`
**Reference:** message broker authentication/authorisation (steps: STEP-3, STEP-7)

#### 6.3.2.29

**Title:** Broker rate limit exceeded blocks finalisation of emitting steps
**Criterion:** Given event publishing must respect quotas, when the broker rate limit/quota is exceeded, then prevent finalisation of the emitting step (STEP-3 or STEP-7) and stop propagation to returning a success outcome from that step, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_BROKER_RATE_LIMIT_EXCEEDED`
**Reference:** message broker quotas (steps: STEP-3, STEP-7)

#### 6.3.2.30

**Title:** Missing broker configuration blocks finalisation of emitting steps
**Criterion:** Given runtime configuration is required for broker publishing, when required broker configuration is missing, then prevent finalisation of the emitting step (STEP-3 or STEP-7) and stop propagation to returning a success outcome from that step, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_BROKER_CONFIG_MISSING`
**Reference:** message broker runtime configuration (steps: STEP-3, STEP-7)

#### 6.3.2.31

**Title:** Missing broker secret blocks finalisation of emitting steps
**Criterion:** Given secrets are required for broker publishing, when the required broker secret is unavailable, then prevent finalisation of the emitting step (STEP-3 or STEP-7) and stop propagation to returning a success outcome from that step, as required by the error mode’s Flow Impact.
**Error Mode:** `ENV_BROKER_SECRET_MISSING`
**Reference:** message broker secrets (steps: STEP-3, STEP-7)

7.1.1 Route: POST /response-sets exists
Purpose: Verify a distinct handler is declared for creating response sets.
Test Data: Application routing registry; base path /api/v1.
Mocking: None. These checks introspect the real router; mocking would hide missing routes.
Assertions: Routing table contains an entry with method POST and path /api/v1/response-sets; the handler is a distinct function (unique callable reference).
AC-Ref: 6.1.1

7.1.2 Route: GET /response-sets/{response_set_id}/screens/{screen_key} exists
Purpose: Verify a distinct handler is declared for reading a screen.
Test Data: Application routing registry; base path /api/v1.
Mocking: None. Uses the real router.
Assertions: Routing table contains an entry with method GET and templated path /api/v1/response-sets/{response_set_id}/screens/{screen_key}; callable is defined.
AC-Ref: 6.1.2

7.1.3 Route: PATCH /response-sets/{response_set_id}/answers/{question_id} exists
Purpose: Verify a distinct handler is declared for single-answer save.
Test Data: Application routing registry; base path /api/v1.
Mocking: None. Uses real router.
Assertions: Routing table contains an entry with method PATCH and templated path /api/v1/response-sets/{response_set_id}/answers/{question_id}; callable is defined.
AC-Ref: 6.1.3

7.1.4 Route: DELETE /response-sets/{response_set_id}/answers/{question_id} exists
Purpose: Verify a distinct handler is declared for explicit clear.
Test Data: Application routing registry; base path /api/v1.
Mocking: None. Uses real router.
Assertions: Routing table contains an entry with method DELETE and templated path /api/v1/response-sets/{response_set_id}/answers/{question_id}; callable is defined.
AC-Ref: 6.1.4

7.1.5 Route: POST /response-sets/{response_set_id}/answers:batch exists
Purpose: Verify a distinct handler is declared for batch upsert.
Test Data: Application routing registry; base path /api/v1.
Mocking: None. Uses real router.
Assertions: Routing table contains an entry with method POST and path /api/v1/response-sets/{response_set_id}/answers:batch; callable is defined.
AC-Ref: 6.1.5

7.1.6 Route: DELETE /response-sets/{response_set_id} exists
Purpose: Verify a distinct handler is declared for deleting a response set.
Test Data: Application routing registry; base path /api/v1.
Mocking: None. Uses real router.
Assertions: Routing table contains an entry with method DELETE and templated path /api/v1/response-sets/{response_set_id}; callable is defined.
AC-Ref: 6.1.6

7.1.7 Reusable screen_view assembly component is shared
Purpose: Ensure one screen assembly function/module is used by both screen read and post-save.
Test Data: Source modules implementing GET screen and PATCH save handlers; import path under app/ (project root).
Mocking: Spies required. Wrap the assembly function with a spy to observe calls from both handlers.
Assertions: A single function (e.g., assemble/build of screen_view) is imported by both handlers; invoking GET screen calls this function once; invoking PATCH save calls the same function during post-save.
AC-Ref: 6.1.7

7.1.8 Visibility helpers used via in-process calls (no HTTP)
Purpose: Verify in-process visibility helpers are imported and called.
Test Data: app/logic/visibility_rules.py (compute_visible_set), app/logic/visibility_delta.py (compute_visibility_delta), app/logic/repository_screens.py (get_visibility_rules_for_screen).
Mocking: Spies required to assert call sites; no HTTP client mocks should appear.
Assertions: GET screen and save flows import and call the above helpers; no HTTP client modules (e.g., requests/httpx/fetch) are imported for visibility; calls occur in-process.
AC-Ref: 6.1.8

7.1.9 Answer hydration uses repository helpers
Purpose: Ensure hydration reads use repository helpers, not inline SQL in handlers.
Test Data: app/logic/repository_answers.py (get_existing_answer); GET screen and post-save handler modules.
Mocking: Spies required to confirm delegation; no database mocking for structure checks.
Assertions: Handlers import and call repository_answers.get_existing_answer (and/or equivalent list retrieval); handler files contain no direct SQL strings for hydration.
AC-Ref: 6.1.9

7.1.10 Screen definition retrieval uses repository helpers
Purpose: Ensure question definitions are obtained via repository_screens helpers.
Test Data: app/logic/repository_screens.py (list_questions_for_screen); GET screen and post-save handler modules.
Mocking: Spies required to confirm delegation.
Assertions: Handlers import and call repository_screens.list_questions_for_screen; handler files contain no direct SQL strings for screen definitions.
AC-Ref: 6.1.10

7.1.11 DB uniqueness on (response_set_id, question_id)
Purpose: Verify a unique constraint exists on the Response persistence model.
Test Data: ORM metadata/schema inspection (Response table) in the live codebase.
Mocking: None. Uses real schema metadata; mocking would invalidate the check.
Assertions: The Response table defines a unique constraint or composite primary key over (response_set_id, question_id).
AC-Ref: 6.1.11

7.1.12 Response.state_version column exists and is integer
Purpose: Ensure versioning column exists on the Response model.
Test Data: ORM metadata/schema inspection (Response table).
Mocking: None. Uses real schema metadata.
Assertions: A column named state_version exists; its type is integer; it is included in the ORM model mapping.
AC-Ref: 6.1.12

7.1.13 Screen-ETag computed via dedicated component
Purpose: Verify a distinct etag component is used to compute screen ETags.
Test Data: app/logic/etag.py (compute_screen_etag); GET screen and post-save modules.
Mocking: Spies required to assert both handlers call compute_screen_etag.
Assertions: compute_screen_etag exists; both handlers import and call it; no ad-hoc hashing logic exists in handlers.
AC-Ref: 6.1.13

7.1.14 If-Match declared as required on write routes
Purpose: Ensure write endpoints require If-Match.
Test Data: Routing/OpenAPI metadata for PATCH/DELETE answer and DELETE response set.
Mocking: None. Introspection of real route metadata.
Assertions: Each write route declares a required header parameter named If-Match in the route/ OpenAPI definition.
AC-Ref: 6.1.14

7.1.15 No idempotency store referenced by write paths
Purpose: Assert write handlers do not depend on idempotency persistence.
Test Data: Search across project root for identifiers: “idempotency”, “idempotent”, “idempotency_key”, “idempotency_store”.
Mocking: None. Static analysis of real codebase.
Assertions: No imports or references to idempotency storage in write handlers; no modules named *idempotency* imported under write paths.
AC-Ref: 6.1.15

7.1.16 Enum resolution via dedicated callable
Purpose: Ensure enum_single resolution is implemented as a distinct callable and used by save/batch.
Test Data: Project root search for a function whose purpose is enum option resolution (e.g., resolve_enum_option / resolve_option_id); PATCH save and batch modules.
Mocking: Spies required to confirm delegation from handlers to the callable.
Assertions: A single callable is defined for resolution; both save and batch handlers import and call it; handlers do not inline option lookups.
AC-Ref: 6.1.16

7.1.17 Text answers pass through unchanged (no trimming in model/serialisers)
Purpose: Ensure no trimming/normalising logic is attached to text answer fields.
Test Data: Persistence model and serializers for short_string/long_text; project-wide search for .strip(), .trim() in write paths.
Mocking: None. Static analysis only.
Assertions: No pre-save hooks or serializer logic trims/normalises text fields; no .strip()/trim-like operations on text answers in write code paths.
AC-Ref: 6.1.17

7.1.18 Number/boolean canonicalisation resides in validation layer
Purpose: Ensure finiteness and boolean checks are implemented in a validation/canonicalisation module and used by handlers.
Test Data: Validation/canonicalisation module under app/logic/*; write handler modules.
Mocking: Spies required to confirm handlers call validation functions.
Assertions: Validation functions for numeric finiteness and boolean literals exist in a dedicated module; handlers import and call them; handlers contain no inline isfinite/boolean coercion logic.
AC-Ref: 6.1.18

7.1.19 Domain event types defined once as constants/enums
Purpose: Ensure response.saved and response_set.deleted are declared centrally.
Test Data: Project-wide search for “response.saved” and “response_set.deleted”.
Mocking: None. Static analysis only.
Assertions: Exactly one module defines these names as constants or enum members; other modules reference them via import; no scattered string literals in publishers.
AC-Ref: 6.1.19

7.1.20 Event emission confined to save and delete flows
Purpose: Ensure only save and delete handlers publish the two domain events.
Test Data: Event publisher module; all route/service modules.
Mocking: Spies required on the publisher to capture call sites when running handler-level unit tests; static scan for publisher calls elsewhere.
Assertions: Publisher is called only from PATCH save and DELETE response-set code paths for the specified event types; no other module invokes these events.
AC-Ref: 6.1.20

7.1.21 Output schema types exist for response bodies
Purpose: Verify serialisable types exist for outputs.screen_view, outputs.saved, outputs.visibility_delta, outputs.batch_result, outputs.events.
Test Data: Schema/type definitions (e.g., Pydantic/dataclasses) under app/*; OpenAPI schema if generated.
Mocking: None. Static inspection.
Assertions: Types/classes exist for each named structure; they are referenced by route response models or serializer bindings.
AC-Ref: 6.1.21

7.1.22 Single reusable type for now_visible items
Purpose: Ensure one serialisable type models visibility_delta.now_visible[] items and is reused.
Test Data: Type definitions; modules building visibility_delta in save/post-save.
Mocking: None for type presence; Spies optional to confirm import reuse.
Assertions: A single class/type defines fields {question:…, answer:?}; both save and post-save code import/reference this type; no duplicate inlined item shapes.
AC-Ref: 6.1.22

7.1.23 Screen-ETag header projected wherever screen_view is returned
Purpose: Ensure handlers that return screen_view also set Screen-ETag from its etag.
Test Data: GET screen and PATCH save handler modules.
Mocking: None for static header-setting location; optional lightweight stub of response object to inspect header assignment.
Assertions: Both handlers assign a Screen-ETag HTTP header and its value is taken from the computed screen_view.etag variable (no recomputation inline).
AC-Ref: 6.1.23

7.1.24 Batch result envelope defined with ordered items
Purpose: Verify a batch_result type exists with items[] preserving submission order.
Test Data: Type definition for batch_result; batch handler module.
Mocking: None for structure; dynamic order tests are behavioural and out-of-scope here.
Assertions: batch_result type exists with an items field declared as a list; handler code constructs items[] using the incoming order (no sorting calls present).
AC-Ref: 6.1.24

7.1.25 Question kind enumeration excludes multi-value kinds
Purpose: Ensure the enumeration used in Epic E only includes {short_string, long_text, number, boolean, enum_single}.
Test Data: Question kind enum/type definition used by Epic E modules.
Mocking: None. Static inspection.
Assertions: Enum contains exactly the allowed literals; no multi-value kinds present; Epic E modules import this enum.
AC-Ref: 6.1.25

7.1.26 Dedicated filter step for visible questions before assembly
Purpose: Verify a discrete function filters to the visible set prior to screen assembly.
Test Data: Module implementing screen assembly; visibility_rules usage site.
Mocking: Spies required to confirm the filter function is called before the assembly function.
Assertions: A named filter function exists and is invoked to subset questions using the visible set result; assembly function receives already-filtered questions.
AC-Ref: 6.1.26

7.1.27 Post-save uses same screen assembly as GET
Purpose: Ensure the save flow reuses the same assembly function to build the updated screen_view.
Test Data: Screen assembly component; PATCH save handler module.
Mocking: Spies required; invoke the PATCH save handler’s core function and assert the assembly function is called.
Assertions: The identical assembly callable used by GET is imported and invoked by the post-save flow; no duplicate assembly logic exists in the save path.
AC-Ref: 6.1.27

**7.2.1.1**
**Title:** Create response set returns identifier
**Purpose:** Verify POST /response-sets returns a UUID identifier for the created response set.
**Test data:**

* Request: `POST /api/v1/response-sets` with JSON body `{ "name": "Onboarding—Run A" }`
* Expected new id shape: UUID v4 (e.g., not all-zeroes; matches `^[0-9a-f-]{36}$`).
  **Mocking:** None. Execute against a test database with empty state. No internal orchestration is mocked.
  **Assertions:**

1. Status = 201.
2. Body includes `outputs.response_set_id` and it matches UUID format.
3. `outputs.response_set_id` is non-empty and stable within the response body (if echoed elsewhere).
   **AC-Ref:** 6.2.1.1
   **EARS-Refs:** U1, U2

---

**7.2.1.2**
**Title:** Create response set echoes name
**Purpose:** Verify the create response echoes the provided name.
**Test data:**

* Request: `POST /api/v1/response-sets` with `{ "name": "Onboarding—Run B" }`
  **Mocking:** None.
  **Assertions:**

1. Status = 201.
2. Body includes `outputs.name` == `"Onboarding—Run B"`.
   **AC-Ref:** 6.2.1.2
   **EARS-Refs:** U1

---

**7.2.1.3**
**Title:** Create response set returns creation timestamp
**Purpose:** Ensure a creation timestamp is returned in RFC 3339 UTC.
**Test data:**

* Request: `POST /api/v1/response-sets` with `{ "name": "Run C" }`
  **Mocking:** None.
  **Assertions:**

1. Status = 201.
2. Body includes `outputs.created_at` matching RFC3339 UTC (ends with `Z` and parseable).
   **AC-Ref:** 6.2.1.3
   **EARS-Refs:** U2

---

**7.2.1.4**
**Title:** Create response set returns entity ETag
**Purpose:** Verify the create response includes an opaque ETag token.
**Test data:**

* Request: `POST /api/v1/response-sets` with `{ "name": "Run D" }`
  **Mocking:** None.
  **Assertions:**

1. Status = 201.
2. Body includes `outputs.etag` as a non-empty opaque string (no structural assumptions; just non-empty).
   **AC-Ref:** 6.2.1.4
   **EARS-Refs:** U2

---

**7.2.1.5**
**Title:** Read screen returns screen_view
**Purpose:** Ensure GET screen returns a `screen_view` object.
**Test data:**

* Seed: response_set_id `11111111-1111-1111-1111-111111111111`; screen_key `"screen_main"` defined with at least one visible question.
* Request: `GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/screen_main`
  **Mocking:** None. Use real visibility helpers and repositories with seeded data.
  **Assertions:**

1. Status = 200.
2. Body includes `outputs.screen_view` (object) and `outputs.screen_view.screen_key == "screen_main"`.
   **AC-Ref:** 6.2.1.5
   **EARS-Refs:** U11, U12

---

**7.2.1.6**
**Title:** Read screen provides Screen-ETag matching the view
**Purpose:** Confirm Screen-ETag mirrors `screen_view.etag`.
**Test data:**

* Same as 7.2.1.5.
  **Mocking:** None.
  **Assertions:**

1. Body includes `outputs.headers.screen_etag` and `outputs.screen_view.etag`.
2. `outputs.headers.screen_etag == outputs.screen_view.etag`.
3. HTTP header `Screen-ETag` (if exposed) equals `outputs.headers.screen_etag`.
   **AC-Ref:** 6.2.1.6
   **EARS-Refs:** U12

---

**7.2.1.7**
**Title:** Screen contains only visible questions
**Purpose:** Validate filtering to visible questions.
**Test data:**

* Seed:

  * Q_BOOL: `cccccccc-cccc-cccc-cccc-cccccccccccc` (boolean, label “Show dependent?”).
  * Q_DEP:  `eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee` (short_string, label “Dependent field”), rule: visible only when Q_BOOL == true.
  * Initial answers: none; thus Q_DEP hidden.
* Request: GET as 7.2.1.5.
  **Mocking:** None.
  **Assertions:**

1. `outputs.screen_view.questions[]` does not contain `eeeeeeee-...` (Q_DEP).
2. Contains Q_BOOL’s id.
   **AC-Ref:** 6.2.1.7
   **EARS-Refs:** E1, S1

---

**7.2.1.8**
**Title:** Save single answer returns saved envelope
**Purpose:** Verify PATCH returns a `saved` object with question id.
**Test data:**

* Path: `/api/v1/response-sets/1111...1111/answers/cccccccc-cccc-cccc-cccc-cccccccccccc`
* Headers: `If-Match: "W/\"ans-1\""` (latest for this row from prior GET).
* Body: `{ "value": true }`
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. Body includes `outputs.saved` with `outputs.saved.question_id == "cccccccc-cccc-cccc-cccc-cccccccccccc"`.
   **AC-Ref:** 6.2.1.8
   **EARS-Refs:** U3, U4, U5

---

**7.2.1.9**
**Title:** Save single answer returns updated entity ETag
**Purpose:** Ensure PATCH returns a new ETag when value changes.
**Test data:**

* First PATCH Q_BOOL true → capture `etag1 = outputs.etag`.
* Second PATCH Q_BOOL false (flip) → capture `etag2`.
  **Mocking:** None.
  **Assertions:**

1. Both PATCH calls 200.
2. `etag2` is present and `etag2 != etag1`.
   **AC-Ref:** 6.2.1.9
   **EARS-Refs:** U4

---

**7.2.1.10**
**Title:** Save single answer returns updated screen_view
**Purpose:** Confirm PATCH includes a refreshed `screen_view`.
**Test data:**

* PATCH same as 7.2.1.8.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. Body includes `outputs.screen_view` (object) with `screen_key == "screen_main"`.
   **AC-Ref:** 6.2.1.10
   **EARS-Refs:** O3, U12

---

**7.2.1.11**
**Title:** Save single answer provides updated Screen-ETag
**Purpose:** Check returned Screen-ETag equals `screen_view.etag`.
**Test data:**

* PATCH as 7.2.1.10.
  **Mocking:** None.
  **Assertions:**

1. `outputs.headers.screen_etag` present.
2. `outputs.headers.screen_etag == outputs.screen_view.etag`.
   **AC-Ref:** 6.2.1.11
   **EARS-Refs:** O3, U12

---

**7.2.1.12**
**Title:** Saved answer links to request identifiers
**Purpose:** Ensure identifiers in response match the request path.
**Test data:**

* response_set_id: `1111...1111`
* question_id: `cccc...cccc`
* PATCH body `{ "value": true }`
  **Mocking:** None.
  **Assertions:**

1. `outputs.response_set_id == "11111111-1111-1111-1111-111111111111"`.
2. `outputs.saved.question_id == "cccccccc-cccc-cccc-cccc-cccccccccccc"`.
   **AC-Ref:** 6.2.1.12
   **EARS-Refs:** U5

---

**7.2.1.13**
**Title:** Finite number saves succeed
**Purpose:** Accept a finite number and acknowledge with saved + ETag.
**Test data:**

* Q_NUM: `bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb` (number).
* PATCH `{ "value": 42.5 }` with valid `If-Match`.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. `outputs.saved.question_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"`.
3. `outputs.etag` present (non-empty).
   **AC-Ref:** 6.2.1.13
   **EARS-Refs:** U7

---

**7.2.1.14**
**Title:** Boolean literal saves succeed
**Purpose:** Accept boolean literals only.
**Test data:**

* Q_BOOL as above; PATCH `{ "value": true }`.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. `outputs.saved.question_id == Q_BOOL`.
3. `outputs.etag` present.
   **AC-Ref:** 6.2.1.14
   **EARS-Refs:** U8

---

**7.2.1.15**
**Title:** Enum selection is represented by option_id
**Purpose:** Ensure enum save is represented via `option_id` in the view.
**Test data:**

* Q_ENUM: `dddddddd-dddd-dddd-dddd-dddddddddddd` (enum_single).
* Options seeded:

  * APAC: id `0f0f0f0f-0000-0000-0000-000000000002`, token `"APAC"`
  * EMEA: id `0f0f0f0f-0000-0000-0000-000000000001`, token `"EMEA"`
* PATCH body `{ "value": "EMEA" }`.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. In `outputs.screen_view.questions[]` entry for Q_ENUM, `answer.option_id == "0f0f0f0f-0000-0000-0000-000000000001"`.
   **AC-Ref:** 6.2.1.15
   **EARS-Refs:** U9

---

**7.2.1.16**
**Title:** Text answers round-trip unchanged
**Purpose:** Verify text stored verbatim (no trimming/normalising).
**Test data:**

* Q_TEXT: `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa` (short_string).
* PATCH `{ "value": "  Hello  " }`.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. In `outputs.screen_view` for Q_TEXT, `answer.value == "  Hello  "`.
   **AC-Ref:** 6.2.1.16
   **EARS-Refs:** U6

---

**7.2.1.17**
**Title:** Clear via DELETE returns updated ETag
**Purpose:** Verify DELETE clears and returns updated entity ETag.
**Test data:**

* Pre: Save any value for Q_TEXT and note previous ETag `etag_prev`.
* Request: `DELETE /api/v1/response-sets/1111...1111/answers/aaaaaaaa-....` with `If-Match: etag_prev`.
  **Mocking:** None.
  **Assertions:**

1. Status = 204.
2. Response header `ETag` present and not equal to `etag_prev`.
   **AC-Ref:** 6.2.1.17
   **EARS-Refs:** U10

---

**7.2.1.18**
**Title:** Clear via PATCH removes the answer from the view
**Purpose:** Ensure `clear:true` removes stored value and view omits answer.
**Test data:**

* PATCH Q_TEXT `{ "clear": true }` with valid `If-Match`.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. In `outputs.screen_view` for Q_TEXT, the `answer` field is absent.
   **AC-Ref:** 6.2.1.18
   **EARS-Refs:** U10, S2

---

**7.2.1.19**
**Title:** Mandatory question may be temporarily empty
**Purpose:** Verify mandatory questions can be empty during entry.
**Test data:**

* Mark Q_TEXT as mandatory in definition.
* PATCH `{ "value": "" }` with valid `If-Match`.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. Body includes `outputs.saved` (no blocking content checks).
   **AC-Ref:** 6.2.1.19
   **EARS-Refs:** S3

---

**7.2.1.20**
**Title:** Save returns visibility_delta container
**Purpose:** Ensure save includes `visibility_delta` object (may be empty).
**Test data:**

* PATCH any valid change that triggers re-evaluation.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. Body includes `outputs.visibility_delta` (object present).
   **AC-Ref:** 6.2.1.20
   **EARS-Refs:** E2

---

**7.2.1.21**
**Title:** Newly visible questions are listed by identifier
**Purpose:** Verify `now_visible[].question.id` includes newly visible Q_DEP.
**Test data:**

* Pre: Q_BOOL currently false; Q_DEP hidden; store `Q_DEP` id.
* PATCH Q_BOOL `{ "value": true }`.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. `outputs.visibility_delta.now_visible[].question.id` contains `"eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"`.
   **AC-Ref:** 6.2.1.21
   **EARS-Refs:** E2, E3

---

**7.2.1.22**
**Title:** Newly visible questions include metadata
**Purpose:** Confirm each `now_visible` item has `kind` and `label`.
**Test data:**

* Follow-on from 7.2.1.21 (same PATCH).
  **Mocking:** None.
  **Assertions:**

1. For the item with question.id == Q_DEP, fields `question.kind` and `question.label` are present and non-empty; `kind` matches model.
   **AC-Ref:** 6.2.1.22
   **EARS-Refs:** E3

---

**7.2.1.23**
**Title:** Newly visible questions include any existing answer
**Purpose:** If Q_DEP had an existing stored answer while hidden, it appears in `now_visible[].answer`.
**Test data:**

* Pre-seed stored answer for Q_DEP (e.g., `"Previously entered"`).
* PATCH Q_BOOL `{ "value": true }`.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. For Q_DEP in `now_visible[]`, `answer.value == "Previously entered"`.
   **AC-Ref:** 6.2.1.23
   **EARS-Refs:** E3

---

**7.2.1.24**
**Title:** Newly hidden questions are listed
**Purpose:** Verify `now_hidden[]` lists identifiers that became hidden.
**Test data:**

* Pre: With Q_BOOL true, Q_DEP visible.
* PATCH Q_BOOL `{ "value": false }`.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. `outputs.visibility_delta.now_hidden[]` contains `"eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"`.
   **AC-Ref:** 6.2.1.24
   **EARS-Refs:** E2

---

**7.2.1.25**
**Title:** Suppressed answers identify hidden questions to ignore
**Purpose:** Confirm `suppressed_answers[]` lists hidden question ids to ignore.
**Test data:**

* Continue from 7.2.1.24.
  **Mocking:** None.
  **Assertions:**

1. Status = 200.
2. `outputs.suppressed_answers[]` contains `"eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"`.
   **AC-Ref:** 6.2.1.25
   **EARS-Refs:** E2

---

**7.2.1.26**
**Title:** Batch upsert returns batch_result envelope
**Purpose:** Verify batch endpoint returns `batch_result`.
**Test data:**

* Request: `POST /api/v1/response-sets/1111...1111/answers:batch`
* Body:

  ```json
  {
    "update_strategy": "merge",
    "items": [
      { "question_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "body": { "value": "Name X" }, "etag": "W/\"ans-7\"" },
      { "question_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "body": { "value": 7 }, "etag": "W/\"ans-9\"" }
    ]
  }
  ```

**Mocking:** None.
**Assertions:**

1. Status = 200.
2. Body includes `outputs.batch_result` (object).
   **AC-Ref:** 6.2.1.26
   **EARS-Refs:** U16, E4

---

**7.2.1.27**
**Title:** Batch items preserve submission order
**Purpose:** Ensure `batch_result.items[]` order matches submission.
**Test data:**

* Use the two-item submission from 7.2.1.26.
  **Mocking:** None.
  **Assertions:**

1. `outputs.batch_result.items[0].question_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"`.
2. `outputs.batch_result.items[1].question_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"`.
   **AC-Ref:** 6.2.1.27
   **EARS-Refs:** U16, E4

---

**7.2.1.28**
**Title:** Batch per-item outcome is reported
**Purpose:** Confirm each item has an `outcome` literal.
**Test data:**

* Use 7.2.1.26 submission; both items valid.
  **Mocking:** None.
  **Assertions:**

1. `outputs.batch_result.items[0].outcome == "success"`.
2. `outputs.batch_result.items[1].outcome == "success"`.
   **AC-Ref:** 6.2.1.28
   **EARS-Refs:** E4

---

**7.2.1.29**
**Title:** Save emits response.saved event in response stream
**Purpose:** Verify the save response includes a `response.saved` event with identifiers.
**Test data:**

* PATCH Q_TEXT `{ "value": "Alice" }`.
  **Mocking:** None (black-box checks response stream; broker boundary not exercised here).
  **Assertions:**

1. `outputs.events[]` contains an item where `type == "response.saved"`.
2. That item’s `payload.response_set_id == "11111111-1111-1111-1111-111111111111"`.
3. `payload.question_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"`.
4. `payload.state_version` present and non-negative integer.
   **AC-Ref:** 6.2.1.29
   **EARS-Refs:** U13

---

**7.2.1.30**
**Title:** Delete response set emits response_set.deleted event
**Purpose:** Verify the delete operation emits a `response_set.deleted` event in the response stream.
**Test data:**

* Request: `DELETE /api/v1/response-sets/11111111-1111-1111-1111-111111111111` with valid `If-Match`.
  **Mocking:** None (assert on response body’s events stream if returned alongside 204-equivalent contract; if body is empty by transport, use the contract projection field as provided by the implementation).
  **Assertions:**

1. Operation completes per contract and returns `outputs.events[]` (as per spec’s projection) containing an item where `type == "response_set.deleted"`.
2. That item’s `payload.response_set_id == "11111111-1111-1111-1111-111111111111"`.
   **AC-Ref:** 6.2.1.30
   **EARS-Refs:** U15, E5

---

**Notes common to all tests (pattern checks):**

* Capability echo, status enum, output/error conditionality, and latency metadata: **N/A** (not part of Epic E’s contract in Section 2).
* Schema validation (happy path only): where applicable above (screen structures, events, etc.), include a positive validation against the referenced sub-schema; no negative/error-path checks are included in this happy path suite.

ID: 7.2.2.1
Title: response_set_id missing
Purpose: Verify that the system surfaces `PRE_RESPONSE_SET_ID_MISSING` when response_set_id missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_RESPONSE_SET_ID_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.1
Error Mode: PRE_RESPONSE_SET_ID_MISSING

ID: 7.2.2.2
Title: response_set_id invalid UUID
Purpose: Verify that the system surfaces `PRE_RESPONSE_SET_ID_INVALID_UUID` when response_set_id invalid uuid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_RESPONSE_SET_ID_INVALID_UUID`.
- HTTP status == 400.
AC-Ref: 6.2.2.2
Error Mode: PRE_RESPONSE_SET_ID_INVALID_UUID

ID: 7.2.2.3
Title: response_set_id unknown
Purpose: Verify that the system surfaces `PRE_RESPONSE_SET_ID_UNKNOWN` when response_set_id unknown.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_RESPONSE_SET_ID_UNKNOWN`.
- HTTP status == 404.
AC-Ref: 6.2.2.3
Error Mode: PRE_RESPONSE_SET_ID_UNKNOWN

ID: 7.2.2.4
Title: screen_key missing
Purpose: Verify that the system surfaces `PRE_SCREEN_KEY_MISSING` when screen_key missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_SCREEN_KEY_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.4
Error Mode: PRE_SCREEN_KEY_MISSING

ID: 7.2.2.5
Title: screen_key unknown
Purpose: Verify that the system surfaces `PRE_SCREEN_KEY_UNKNOWN_KEY` when screen_key unknown.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_SCREEN_KEY_UNKNOWN_KEY`.
- HTTP status == 404.
AC-Ref: 6.2.2.5
Error Mode: PRE_SCREEN_KEY_UNKNOWN_KEY

ID: 7.2.2.6
Title: screen definition undefined
Purpose: Verify that the system surfaces `PRE_SCREEN_KEY_UNDEFINED_SCREEN` when screen definition undefined.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_SCREEN_KEY_UNDEFINED_SCREEN`.
- HTTP status == 400.
AC-Ref: 6.2.2.6
Error Mode: PRE_SCREEN_KEY_UNDEFINED_SCREEN

ID: 7.2.2.7
Title: question_id missing
Purpose: Verify that the system surfaces `PRE_QUESTION_ID_MISSING` when question_id missing.
Test Data: HTTP DELETE /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_QUESTION_ID_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.7
Error Mode: PRE_QUESTION_ID_MISSING

ID: 7.2.2.8
Title: question_id invalid UUID
Purpose: Verify that the system surfaces `PRE_QUESTION_ID_INVALID_UUID` when question_id invalid uuid.
Test Data: HTTP DELETE /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_QUESTION_ID_INVALID_UUID`.
- HTTP status == 400.
AC-Ref: 6.2.2.8
Error Mode: PRE_QUESTION_ID_INVALID_UUID

ID: 7.2.2.9
Title: question_id unknown
Purpose: Verify that the system surfaces `PRE_QUESTION_ID_UNKNOWN` when question_id unknown.
Test Data: HTTP DELETE /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_QUESTION_ID_UNKNOWN`.
- HTTP status == 404.
AC-Ref: 6.2.2.9
Error Mode: PRE_QUESTION_ID_UNKNOWN

ID: 7.2.2.10
Title: name missing
Purpose: Verify that the system surfaces `PRE_NAME_MISSING` when name missing.
Test Data: HTTP POST /api/v1/response-sets; Headers: {"Content-Type": "application/json"}; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_NAME_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.10
Error Mode: PRE_NAME_MISSING

ID: 7.2.2.11
Title: name empty
Purpose: Verify that the system surfaces `PRE_NAME_EMPTY_AFTER_INPUT` when name empty.
Test Data: HTTP POST /api/v1/response-sets; Headers: {"Content-Type": "application/json"}; Body: {"name": ""}
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_NAME_EMPTY_AFTER_INPUT`.
- HTTP status == 400.
AC-Ref: 6.2.2.11
Error Mode: PRE_NAME_EMPTY_AFTER_INPUT

ID: 7.2.2.12
Title: name too long
Purpose: Verify that the system surfaces `PRE_NAME_EXCEEDS_MAX_LENGTH` when name too long.
Test Data: HTTP POST /api/v1/response-sets; Headers: {"Content-Type": "application/json"}; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_NAME_EXCEEDS_MAX_LENGTH`.
- HTTP status == 400.
AC-Ref: 6.2.2.12
Error Mode: PRE_NAME_EXCEEDS_MAX_LENGTH

ID: 7.2.2.13
Title: If-Match missing
Purpose: Verify that the system surfaces `PRE_IF_MATCH_MISSING` when if-match missing.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: {"If-Match": "\"sv-3\"", "Content-Type": "application/json"}; Body: {"value": "any"}
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_IF_MATCH_MISSING`.
- HTTP status == 409.
- Upsert or delete operation is not attempted (assert persistence helpers not called).
AC-Ref: 6.2.2.13
Error Mode: PRE_IF_MATCH_MISSING

ID: 7.2.2.14
Title: If-Match mismatch
Purpose: Verify that the system surfaces `PRE_IF_MATCH_ETAG_MISMATCH` when if-match mismatch.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: {"If-Match": "\"sv-2\"", "Content-Type": "application/json"}; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_IF_MATCH_ETAG_MISMATCH`.
- HTTP status == 409.
- Upsert or delete operation is not attempted (assert persistence helpers not called).
AC-Ref: 6.2.2.14
Error Mode: PRE_IF_MATCH_ETAG_MISMATCH

ID: 7.2.2.15
Title: PATCH body missing
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_BODY_MISSING` when patch body missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_BODY_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.15
Error Mode: PRE_ANSWER_PATCH_BODY_MISSING

ID: 7.2.2.16
Title: PATCH schema invalid
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_SCHEMA_INVALID` when patch schema invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_SCHEMA_INVALID`.
- HTTP status == 400.
AC-Ref: 6.2.2.16
Error Mode: PRE_ANSWER_PATCH_SCHEMA_INVALID

ID: 7.2.2.17
Title: PATCH fields not permitted
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_FIELDS_NOT_PERMITTED` when patch fields not permitted.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_FIELDS_NOT_PERMITTED`.
- HTTP status == 400.
AC-Ref: 6.2.2.17
Error Mode: PRE_ANSWER_PATCH_FIELDS_NOT_PERMITTED

ID: 7.2.2.18
Title: value wrong type
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_VALUE_WRONG_TYPE` when value wrong type.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_VALUE_WRONG_TYPE`.
- HTTP status == 400.
AC-Ref: 6.2.2.18
Error Mode: PRE_ANSWER_PATCH_VALUE_WRONG_TYPE

ID: 7.2.2.19
Title: number not finite
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_VALUE_NUMBER_NOT_FINITE` when number not finite.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: {"value": Infinity}
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_VALUE_NUMBER_NOT_FINITE`.
- HTTP status == 400.
AC-Ref: 6.2.2.19
Error Mode: PRE_ANSWER_PATCH_VALUE_NUMBER_NOT_FINITE

ID: 7.2.2.20
Title: value not boolean literal
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_VALUE_NOT_BOOLEAN_LITERAL` when value not boolean literal.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: {"value": "truthy"}
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_VALUE_NOT_BOOLEAN_LITERAL`.
- HTTP status == 400.
AC-Ref: 6.2.2.20
Error Mode: PRE_ANSWER_PATCH_VALUE_NOT_BOOLEAN_LITERAL

ID: 7.2.2.21
Title: option_id invalid UUID
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_OPTION_ID_INVALID_UUID` when option_id invalid uuid.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: {"value": "NON_EXISTENT_VALUE"}
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_OPTION_ID_INVALID_UUID`.
- HTTP status == 400.
AC-Ref: 6.2.2.21
Error Mode: PRE_ANSWER_PATCH_OPTION_ID_INVALID_UUID

ID: 7.2.2.22
Title: option_id unknown
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_OPTION_ID_UNKNOWN` when option_id unknown.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: {"value": "NON_EXISTENT_VALUE"}
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_OPTION_ID_UNKNOWN`.
- HTTP status == 404.
AC-Ref: 6.2.2.22
Error Mode: PRE_ANSWER_PATCH_OPTION_ID_UNKNOWN

ID: 7.2.2.23
Title: enum submission missing identifier
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_VALUE_TOKEN_IDENTIFIERS_MISSING` when enum submission missing identifier.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_VALUE_TOKEN_IDENTIFIERS_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.23
Error Mode: PRE_ANSWER_PATCH_VALUE_TOKEN_IDENTIFIERS_MISSING

ID: 7.2.2.24
Title: enum value token unknown
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_VALUE_TOKEN_UNKNOWN` when enum value token unknown.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_VALUE_TOKEN_UNKNOWN`.
- HTTP status == 404.
AC-Ref: 6.2.2.24
Error Mode: PRE_ANSWER_PATCH_VALUE_TOKEN_UNKNOWN

ID: 7.2.2.25
Title: label not string
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_LABEL_NOT_STRING` when label not string.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_LABEL_NOT_STRING`.
- HTTP status == 400.
AC-Ref: 6.2.2.25
Error Mode: PRE_ANSWER_PATCH_LABEL_NOT_STRING

ID: 7.2.2.26
Title: label too long
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_LABEL_TOO_LONG` when label too long.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_LABEL_TOO_LONG`.
- HTTP status == 400.
AC-Ref: 6.2.2.26
Error Mode: PRE_ANSWER_PATCH_LABEL_TOO_LONG

ID: 7.2.2.27
Title: allow_new_label not boolean
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_ALLOW_NEW_LABEL_NOT_BOOLEAN` when allow_new_label not boolean.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: {"value": "truthy"}
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_ALLOW_NEW_LABEL_NOT_BOOLEAN`.
- HTTP status == 400.
AC-Ref: 6.2.2.27
Error Mode: PRE_ANSWER_PATCH_ALLOW_NEW_LABEL_NOT_BOOLEAN

ID: 7.2.2.28
Title: clear not boolean
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_CLEAR_NOT_BOOLEAN` when clear not boolean.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: {"value": "truthy"}
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_CLEAR_NOT_BOOLEAN`.
- HTTP status == 400.
AC-Ref: 6.2.2.28
Error Mode: PRE_ANSWER_PATCH_CLEAR_NOT_BOOLEAN

ID: 7.2.2.29
Title: clear targets unknown question
Purpose: Verify that the system surfaces `PRE_ANSWER_PATCH_CLEAR_TARGET_UNKNOWN` when clear targets unknown question.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_ANSWER_PATCH_CLEAR_TARGET_UNKNOWN`.
- HTTP status == 404.
AC-Ref: 6.2.2.29
Error Mode: PRE_ANSWER_PATCH_CLEAR_TARGET_UNKNOWN

ID: 7.2.2.30
Title: batch body missing
Purpose: Verify that the system surfaces `PRE_BATCH_REQUEST_BODY_MISSING` when batch body missing.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_REQUEST_BODY_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.30
Error Mode: PRE_BATCH_REQUEST_BODY_MISSING

ID: 7.2.2.31
Title: batch envelope fields missing
Purpose: Verify that the system surfaces `PRE_BATCH_REQUEST_ENVELOPE_FIELDS_MISSING` when batch envelope fields missing.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_REQUEST_ENVELOPE_FIELDS_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.31
Error Mode: PRE_BATCH_REQUEST_ENVELOPE_FIELDS_MISSING

ID: 7.2.2.32
Title: update_strategy missing
Purpose: Verify that the system surfaces `PRE_BATCH_UPDATE_STRATEGY_MISSING` when update_strategy missing.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_UPDATE_STRATEGY_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.32
Error Mode: PRE_BATCH_UPDATE_STRATEGY_MISSING

ID: 7.2.2.33
Title: update_strategy invalid
Purpose: Verify that the system surfaces `PRE_BATCH_UPDATE_STRATEGY_INVALID` when update_strategy invalid.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_UPDATE_STRATEGY_INVALID`.
- HTTP status == 400.
AC-Ref: 6.2.2.33
Error Mode: PRE_BATCH_UPDATE_STRATEGY_INVALID

ID: 7.2.2.34
Title: clear_missing not boolean
Purpose: Verify that the system surfaces `PRE_BATCH_CLEAR_MISSING_NOT_BOOLEAN` when clear_missing not boolean.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: {"value": "truthy"}
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_CLEAR_MISSING_NOT_BOOLEAN`.
- HTTP status == 400.
AC-Ref: 6.2.2.34
Error Mode: PRE_BATCH_CLEAR_MISSING_NOT_BOOLEAN

ID: 7.2.2.35
Title: items missing
Purpose: Verify that the system surfaces `PRE_BATCH_ITEMS_MISSING` when items missing.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_ITEMS_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.35
Error Mode: PRE_BATCH_ITEMS_MISSING

ID: 7.2.2.36
Title: items empty
Purpose: Verify that the system surfaces `PRE_BATCH_ITEMS_EMPTY` when items empty.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_ITEMS_EMPTY`.
- HTTP status == 400.
AC-Ref: 6.2.2.36
Error Mode: PRE_BATCH_ITEMS_EMPTY

ID: 7.2.2.37
Title: items schema invalid
Purpose: Verify that the system surfaces `PRE_BATCH_ITEMS_SCHEMA_INVALID` when items schema invalid.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: {"items": [{"question_id": "22222222-2222-2222-2222-222222222222", "value": 1}], "extra": true}
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_ITEMS_SCHEMA_INVALID`.
- HTTP status == 400.
AC-Ref: 6.2.2.37
Error Mode: PRE_BATCH_ITEMS_SCHEMA_INVALID

ID: 7.2.2.38
Title: batch item question_id missing
Purpose: Verify that the system surfaces `PRE_BATCH_ITEM_QUESTION_ID_MISSING` when batch item question_id missing.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_ITEM_QUESTION_ID_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.38
Error Mode: PRE_BATCH_ITEM_QUESTION_ID_MISSING

ID: 7.2.2.39
Title: batch item question_id invalid
Purpose: Verify that the system surfaces `PRE_BATCH_ITEM_QUESTION_ID_INVALID_UUID` when batch item question_id invalid.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_ITEM_QUESTION_ID_INVALID_UUID`.
- HTTP status == 400.
AC-Ref: 6.2.2.39
Error Mode: PRE_BATCH_ITEM_QUESTION_ID_INVALID_UUID

ID: 7.2.2.40
Title: batch item question_id unknown
Purpose: Verify that the system surfaces `PRE_BATCH_ITEM_QUESTION_ID_UNKNOWN` when batch item question_id unknown.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_ITEM_QUESTION_ID_UNKNOWN`.
- HTTP status == 404.
AC-Ref: 6.2.2.40
Error Mode: PRE_BATCH_ITEM_QUESTION_ID_UNKNOWN

ID: 7.2.2.41
Title: batch item etag missing
Purpose: Verify that the system surfaces `PRE_BATCH_ITEM_ETAG_MISSING` when batch item etag missing.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_ITEM_ETAG_MISSING`.
- HTTP status == 400.
AC-Ref: 6.2.2.41
Error Mode: PRE_BATCH_ITEM_ETAG_MISSING

ID: 7.2.2.42
Title: batch item etag mismatch
Purpose: Verify that the system surfaces `PRE_BATCH_ITEM_ETAG_MISMATCH` when batch item etag mismatch.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_ITEM_ETAG_MISMATCH`.
- HTTP status == 400.
AC-Ref: 6.2.2.42
Error Mode: PRE_BATCH_ITEM_ETAG_MISMATCH

ID: 7.2.2.43
Title: batch item body schema invalid
Purpose: Verify that the system surfaces `PRE_BATCH_ITEM_BODY_SCHEMA_INVALID` when batch item body schema invalid.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: {"items": [{"question_id": "22222222-2222-2222-2222-222222222222", "value": 1}], "extra": true}
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_ITEM_BODY_SCHEMA_INVALID`.
- HTTP status == 400.
AC-Ref: 6.2.2.43
Error Mode: PRE_BATCH_ITEM_BODY_SCHEMA_INVALID

ID: 7.2.2.44
Title: batch item disallowed fields
Purpose: Verify that the system surfaces `PRE_BATCH_ITEM_BODY_FIELDS_NOT_PERMITTED` when batch item disallowed fields.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_BATCH_ITEM_BODY_FIELDS_NOT_PERMITTED`.
- HTTP status == 400.
AC-Ref: 6.2.2.44
Error Mode: PRE_BATCH_ITEM_BODY_FIELDS_NOT_PERMITTED

ID: 7.2.2.45
Title: screen definition inaccessible
Purpose: Verify that the system surfaces `PRE_SCREEN_DEFINITION_NOT_ACCESSIBLE` when screen definition inaccessible.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_SCREEN_DEFINITION_NOT_ACCESSIBLE`.
- HTTP status == 400.
AC-Ref: 6.2.2.45
Error Mode: PRE_SCREEN_DEFINITION_NOT_ACCESSIBLE

ID: 7.2.2.46
Title: screen definition invalid JSON
Purpose: Verify that the system surfaces `PRE_SCREEN_DEFINITION_INVALID_JSON` when screen definition invalid json.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_SCREEN_DEFINITION_INVALID_JSON`.
- HTTP status == 400.
AC-Ref: 6.2.2.46
Error Mode: PRE_SCREEN_DEFINITION_INVALID_JSON

ID: 7.2.2.47
Title: screen definition schema invalid
Purpose: Verify that the system surfaces `PRE_SCREEN_DEFINITION_SCHEMA_INVALID` when screen definition schema invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_SCREEN_DEFINITION_SCHEMA_INVALID`.
- HTTP status == 400.
AC-Ref: 6.2.2.47
Error Mode: PRE_SCREEN_DEFINITION_SCHEMA_INVALID

ID: 7.2.2.48
Title: visibility rules inaccessible
Purpose: Verify that the system surfaces `PRE_VISIBILITY_RULES_NOT_ACCESSIBLE` when visibility rules inaccessible.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_VISIBILITY_RULES_NOT_ACCESSIBLE`.
- HTTP status == 400.
AC-Ref: 6.2.2.48
Error Mode: PRE_VISIBILITY_RULES_NOT_ACCESSIBLE

ID: 7.2.2.49
Title: visibility rules invalid JSON
Purpose: Verify that the system surfaces `PRE_VISIBILITY_RULES_INVALID_JSON` when visibility rules invalid json.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_VISIBILITY_RULES_INVALID_JSON`.
- HTTP status == 400.
AC-Ref: 6.2.2.49
Error Mode: PRE_VISIBILITY_RULES_INVALID_JSON

ID: 7.2.2.50
Title: visibility rules schema invalid
Purpose: Verify that the system surfaces `PRE_VISIBILITY_RULES_SCHEMA_INVALID` when visibility rules schema invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_VISIBILITY_RULES_SCHEMA_INVALID`.
- HTTP status == 400.
AC-Ref: 6.2.2.50
Error Mode: PRE_VISIBILITY_RULES_SCHEMA_INVALID

ID: 7.2.2.51
Title: existing answer lookup failed
Purpose: Verify that the system surfaces `PRE_EXISTING_ANSWER_LOOKUP_FAILED` when existing answer lookup failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_EXISTING_ANSWER_LOOKUP_FAILED`.
- HTTP status == 400.
AC-Ref: 6.2.2.51
Error Mode: PRE_EXISTING_ANSWER_LOOKUP_FAILED

ID: 7.2.2.52
Title: existing answers for screen query failed
Purpose: Verify that the system surfaces `PRE_EXISTING_ANSWERS_FOR_SCREEN_QUERY_FAILED` when existing answers for screen query failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_EXISTING_ANSWERS_FOR_SCREEN_QUERY_FAILED`.
- HTTP status == 400.
AC-Ref: 6.2.2.52
Error Mode: PRE_EXISTING_ANSWERS_FOR_SCREEN_QUERY_FAILED

ID: 7.2.2.53
Title: visible ids call failed
Purpose: Verify that the system surfaces `PRE_VISIBLE_QUESTION_IDS_CALL_FAILED` when visible ids call failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.get_visibility_rules_for_screen` to not called; reason: failure is detected at contract validation before repository is invoked; usage: assert_not_called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_VISIBLE_QUESTION_IDS_CALL_FAILED`.
- HTTP status == 400.
AC-Ref: 6.2.2.53
Error Mode: PRE_VISIBLE_QUESTION_IDS_CALL_FAILED

ID: 7.2.2.54
Title: visibility now_visible call failed
Purpose: Verify that the system surfaces `PRE_VISIBILITY_NOW_VISIBLE_CALL_FAILED` when visibility now_visible call failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_VISIBILITY_NOW_VISIBLE_CALL_FAILED`.
- HTTP status == 400.
AC-Ref: 6.2.2.54
Error Mode: PRE_VISIBILITY_NOW_VISIBLE_CALL_FAILED

ID: 7.2.2.55
Title: visibility now_hidden call failed
Purpose: Verify that the system surfaces `PRE_VISIBILITY_NOW_HIDDEN_CALL_FAILED` when visibility now_hidden call failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_VISIBILITY_NOW_HIDDEN_CALL_FAILED`.
- HTTP status == 400.
AC-Ref: 6.2.2.55
Error Mode: PRE_VISIBILITY_NOW_HIDDEN_CALL_FAILED

ID: 7.2.2.56
Title: visibility suppressed_answers call failed
Purpose: Verify that the system surfaces `PRE_VISIBILITY_SUPPRESSED_ANSWERS_CALL_FAILED` when visibility suppressed_answers call failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `PRE_VISIBILITY_SUPPRESSED_ANSWERS_CALL_FAILED`.
- HTTP status == 400.
AC-Ref: 6.2.2.56
Error Mode: PRE_VISIBILITY_SUPPRESSED_ANSWERS_CALL_FAILED

ID: 7.2.2.57
Title: Create response set failed at runtime
Purpose: Verify that the system surfaces `RUN_CREATE_RESPONSE_SET_FAILED` when create response set failed at runtime.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_CREATE_RESPONSE_SET_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.57
Error Mode: RUN_CREATE_RESPONSE_SET_FAILED

ID: 7.2.2.58
Title: Persist response_set_id failed at runtime
Purpose: Verify that the system surfaces `RUN_PERSIST_RESPONSE_SET_FAILED` when persist response_set_id failed at runtime.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_PERSIST_RESPONSE_SET_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.58
Error Mode: RUN_PERSIST_RESPONSE_SET_FAILED

ID: 7.2.2.59
Title: List screen questions failed
Purpose: Verify that the system surfaces `RUN_LIST_SCREEN_QUESTIONS_FAILED` when list screen questions failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_LIST_SCREEN_QUESTIONS_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.59
Error Mode: RUN_LIST_SCREEN_QUESTIONS_FAILED

ID: 7.2.2.60
Title: Load visibility rules failed
Purpose: Verify that the system surfaces `RUN_LOAD_VISIBILITY_RULES_FAILED` when load visibility rules failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_LOAD_VISIBILITY_RULES_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.60
Error Mode: RUN_LOAD_VISIBILITY_RULES_FAILED

ID: 7.2.2.61
Title: Compute visible set failed
Purpose: Verify that the system surfaces `RUN_COMPUTE_VISIBLE_SET_FAILED` when compute visible set failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_COMPUTE_VISIBLE_SET_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.61
Error Mode: RUN_COMPUTE_VISIBLE_SET_FAILED

ID: 7.2.2.62
Title: Hydrate existing answers failed
Purpose: Verify that the system surfaces `RUN_HYDRATE_EXISTING_ANSWERS_FAILED` when hydrate existing answers failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_HYDRATE_EXISTING_ANSWERS_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.62
Error Mode: RUN_HYDRATE_EXISTING_ANSWERS_FAILED

ID: 7.2.2.63
Title: Assemble screen_view failed
Purpose: Verify that the system surfaces `RUN_ASSEMBLE_SCREEN_VIEW_FAILED` when assemble screen_view failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_ASSEMBLE_SCREEN_VIEW_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.63
Error Mode: RUN_ASSEMBLE_SCREEN_VIEW_FAILED

ID: 7.2.2.64
Title: Compute screen ETag failed
Purpose: Verify that the system surfaces `RUN_COMPUTE_SCREEN_ETAG_FAILED` when compute screen etag failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_COMPUTE_SCREEN_ETAG_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.64
Error Mode: RUN_COMPUTE_SCREEN_ETAG_FAILED

ID: 7.2.2.65
Title: Save upsert failed
Purpose: Verify that the system surfaces `RUN_SAVE_ANSWER_UPSERT_FAILED` when save upsert failed.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: {"If-Match": "\"sv-3\"", "Content-Type": "application/json"}; Body: {"value": "ok"}
Mocking:
- Mock `app.logic.repository_answers.upsert` to raise RuntimeError('db write failed'); reason: simulate persistence failure; usage: assert_called_once.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_SAVE_ANSWER_UPSERT_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.65
Error Mode: RUN_SAVE_ANSWER_UPSERT_FAILED

ID: 7.2.2.66
Title: Resolve enum option failed
Purpose: Verify that the system surfaces `RUN_RESOLVE_ENUM_OPTION_FAILED` when resolve enum option failed.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: {"value": "NON_EXISTENT_VALUE"}
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_RESOLVE_ENUM_OPTION_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.66
Error Mode: RUN_RESOLVE_ENUM_OPTION_FAILED

ID: 7.2.2.67
Title: Compute visibility_delta failed
Purpose: Verify that the system surfaces `RUN_COMPUTE_VISIBILITY_DELTA_FAILED` when compute visibility_delta failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_COMPUTE_VISIBILITY_DELTA_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.67
Error Mode: RUN_COMPUTE_VISIBILITY_DELTA_FAILED

ID: 7.2.2.68
Title: Hydrate newly visible items failed
Purpose: Verify that the system surfaces `RUN_INCLUDE_NOW_VISIBLE_HYDRATION_FAILED` when hydrate newly visible items failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_INCLUDE_NOW_VISIBLE_HYDRATION_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.68
Error Mode: RUN_INCLUDE_NOW_VISIBLE_HYDRATION_FAILED

ID: 7.2.2.69
Title: Re-assemble updated screen_view failed
Purpose: Verify that the system surfaces `RUN_ASSEMBLE_SCREEN_VIEW_FAILED` when re-assemble updated screen_view failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_ASSEMBLE_SCREEN_VIEW_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.69
Error Mode: RUN_ASSEMBLE_SCREEN_VIEW_FAILED

ID: 7.2.2.70
Title: Compute updated Screen-ETag failed
Purpose: Verify that the system surfaces `RUN_COMPUTE_SCREEN_ETAG_FAILED` when compute updated screen-etag failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_COMPUTE_SCREEN_ETAG_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.70
Error Mode: RUN_COMPUTE_SCREEN_ETAG_FAILED

ID: 7.2.2.71
Title: Clear answer failed
Purpose: Verify that the system surfaces `RUN_CLEAR_ANSWER_FAILED` when clear answer failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_CLEAR_ANSWER_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.71
Error Mode: RUN_CLEAR_ANSWER_FAILED

ID: 7.2.2.72
Title: Batch item processing failed
Purpose: Verify that the system surfaces `RUN_BATCH_PROCESS_ITEM_FAILED` when batch item processing failed.
Test Data: HTTP POST /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers:batch; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_answers.bulk_upsert_stream` to raise RuntimeError('bulk write failed'); reason: simulate persistence failure; usage: assert_called_once.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_BATCH_PROCESS_ITEM_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.72
Error Mode: RUN_BATCH_PROCESS_ITEM_FAILED

ID: 7.2.2.73
Title: Batch upsert item save failed
Purpose: Verify that the system surfaces `RUN_SAVE_ANSWER_UPSERT_FAILED` when batch upsert item save failed.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: {"If-Match": "\"sv-3\"", "Content-Type": "application/json"}; Body: {"value": "ok"}
Mocking:
- Mock `app.logic.repository_answers.upsert` to raise RuntimeError('db write failed'); reason: simulate persistence failure; usage: assert_called_once.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_SAVE_ANSWER_UPSERT_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.73
Error Mode: RUN_SAVE_ANSWER_UPSERT_FAILED

ID: 7.2.2.74
Title: Batch enum resolution failed
Purpose: Verify that the system surfaces `RUN_RESOLVE_ENUM_OPTION_FAILED` when batch enum resolution failed.
Test Data: HTTP PATCH /api/v1/response-sets/11111111-1111-1111-1111-111111111111/answers/22222222-2222-2222-2222-222222222222; Headers: None; Body: {"value": "NON_EXISTENT_VALUE"}
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_RESOLVE_ENUM_OPTION_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.74
Error Mode: RUN_RESOLVE_ENUM_OPTION_FAILED

ID: 7.2.2.75
Title: Delete response set failed
Purpose: Verify that the system surfaces `RUN_DELETE_RESPONSE_SET_FAILED` when delete response set failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_DELETE_RESPONSE_SET_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.75
Error Mode: RUN_DELETE_RESPONSE_SET_FAILED

ID: 7.2.2.76
Title: Cascade delete answers failed
Purpose: Verify that the system surfaces `RUN_CASCADE_DELETE_ANSWERS_FAILED` when cascade delete answers failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_CASCADE_DELETE_ANSWERS_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.76
Error Mode: RUN_CASCADE_DELETE_ANSWERS_FAILED

ID: 7.2.2.77
Title: Emit response.saved event failed
Purpose: Verify that the system surfaces `RUN_EMIT_RESPONSE_SAVED_FAILED` when emit response.saved event failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_EMIT_RESPONSE_SAVED_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.77
Error Mode: RUN_EMIT_RESPONSE_SAVED_FAILED

ID: 7.2.2.78
Title: Emit response_set.deleted event failed
Purpose: Verify that the system surfaces `RUN_EMIT_RESPONSE_SET_DELETED_FAILED` when emit response_set.deleted event failed.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking: None (boundary calls must not be invoked on this error); assert repository and visibility helpers are not called.
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `RUN_EMIT_RESPONSE_SET_DELETED_FAILED`.
- HTTP status == 500.
- Boundary mock asserted for runtime failure as specified.
AC-Ref: 6.2.2.78
Error Mode: RUN_EMIT_RESPONSE_SET_DELETED_FAILED

ID: 7.2.2.79
Title: outputs.response_set_id missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_RESPONSE_SET_ID_MISSING` when outputs.response_set_id missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_RESPONSE_SET_ID_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.79
Error Mode: POST_OUTPUTS_RESPONSE_SET_ID_MISSING

ID: 7.2.2.80
Title: outputs.response_set_id invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_RESPONSE_SET_ID_INVALID_UUID` when outputs.response_set_id invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_RESPONSE_SET_ID_INVALID_UUID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.80
Error Mode: POST_OUTPUTS_RESPONSE_SET_ID_INVALID_UUID

ID: 7.2.2.81
Title: outputs.response_set_id mismatch
Purpose: Verify that the system surfaces `POST_OUTPUTS_RESPONSE_SET_ID_MISMATCH_REQUEST` when outputs.response_set_id mismatch.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_RESPONSE_SET_ID_MISMATCH_REQUEST`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.81
Error Mode: POST_OUTPUTS_RESPONSE_SET_ID_MISMATCH_REQUEST

ID: 7.2.2.82
Title: outputs.name missing on create
Purpose: Verify that the system surfaces `POST_OUTPUTS_NAME_MISSING_ON_CREATE` when outputs.name missing on create.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_NAME_MISSING_ON_CREATE`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.82
Error Mode: POST_OUTPUTS_NAME_MISSING_ON_CREATE

ID: 7.2.2.83
Title: outputs.etag missing on PATCH
Purpose: Verify that the system surfaces `POST_OUTPUTS_ETAG_MISSING_ON_PATCH` when outputs.etag missing on patch.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_ETAG_MISSING_ON_PATCH`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.83
Error Mode: POST_OUTPUTS_ETAG_MISSING_ON_PATCH

ID: 7.2.2.84
Title: outputs.created_at missing on create
Purpose: Verify that the system surfaces `POST_OUTPUTS_CREATED_AT_MISSING_ON_CREATE` when outputs.created_at missing on create.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_CREATED_AT_MISSING_ON_CREATE`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.84
Error Mode: POST_OUTPUTS_CREATED_AT_MISSING_ON_CREATE

ID: 7.2.2.85
Title: outputs.screen_view missing on GET
Purpose: Verify that the system surfaces `POST_OUTPUTS_SCREEN_VIEW_MISSING_ON_GET` when outputs.screen_view missing on get.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SCREEN_VIEW_MISSING_ON_GET`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.85
Error Mode: POST_OUTPUTS_SCREEN_VIEW_MISSING_ON_GET

ID: 7.2.2.86
Title: outputs.screen_view missing on PATCH
Purpose: Verify that the system surfaces `POST_OUTPUTS_SCREEN_VIEW_MISSING_ON_PATCH` when outputs.screen_view missing on patch.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SCREEN_VIEW_MISSING_ON_PATCH`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.86
Error Mode: POST_OUTPUTS_SCREEN_VIEW_MISSING_ON_PATCH

ID: 7.2.2.87
Title: outputs.screen_view.etag missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_SCREEN_VIEW_ETAG_MISSING` when outputs.screen_view.etag missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.etag.compute_screen_etag` to return None; reason: force missing Screen-ETag; usage: assert_called_once_with('11111111-1111-1111-1111-111111111111', 'employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SCREEN_VIEW_ETAG_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.87
Error Mode: POST_OUTPUTS_SCREEN_VIEW_ETAG_MISSING

ID: 7.2.2.88
Title: outputs.screen_view.questions schema invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_SCREEN_VIEW_QUESTIONS_ITEMS_SCHEMA_INVALID` when outputs.screen_view.questions schema invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SCREEN_VIEW_QUESTIONS_ITEMS_SCHEMA_INVALID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.88
Error Mode: POST_OUTPUTS_SCREEN_VIEW_QUESTIONS_ITEMS_SCHEMA_INVALID

ID: 7.2.2.89
Title: outputs.screen_view.question_id missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_SCREEN_VIEW_QUESTION_ID_MISSING` when outputs.screen_view.question_id missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SCREEN_VIEW_QUESTION_ID_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.89
Error Mode: POST_OUTPUTS_SCREEN_VIEW_QUESTION_ID_MISSING

ID: 7.2.2.90
Title: outputs.screen_view.kind missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_SCREEN_VIEW_KIND_MISSING` when outputs.screen_view.kind missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SCREEN_VIEW_KIND_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.90
Error Mode: POST_OUTPUTS_SCREEN_VIEW_KIND_MISSING

ID: 7.2.2.91
Title: outputs.screen_view.label missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_SCREEN_VIEW_LABEL_MISSING` when outputs.screen_view.label missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SCREEN_VIEW_LABEL_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.91
Error Mode: POST_OUTPUTS_SCREEN_VIEW_LABEL_MISSING

ID: 7.2.2.92
Title: outputs.screen_view.answer schema invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_SCREEN_VIEW_ANSWER_SCHEMA_INVALID` when outputs.screen_view.answer schema invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SCREEN_VIEW_ANSWER_SCHEMA_INVALID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.92
Error Mode: POST_OUTPUTS_SCREEN_VIEW_ANSWER_SCHEMA_INVALID

ID: 7.2.2.93
Title: outputs.saved missing on PATCH
Purpose: Verify that the system surfaces `POST_OUTPUTS_SAVED_MISSING_ON_PATCH` when outputs.saved missing on patch.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SAVED_MISSING_ON_PATCH`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.93
Error Mode: POST_OUTPUTS_SAVED_MISSING_ON_PATCH

ID: 7.2.2.94
Title: outputs.saved.question_id missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_SAVED_QUESTION_ID_MISSING` when outputs.saved.question_id missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SAVED_QUESTION_ID_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.94
Error Mode: POST_OUTPUTS_SAVED_QUESTION_ID_MISSING

ID: 7.2.2.95
Title: outputs.saved.state_version missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_SAVED_STATE_VERSION_MISSING` when outputs.saved.state_version missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SAVED_STATE_VERSION_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.95
Error Mode: POST_OUTPUTS_SAVED_STATE_VERSION_MISSING

ID: 7.2.2.96
Title: outputs.visibility_delta schema invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_VISIBILITY_DELTA_SCHEMA_INVALID` when outputs.visibility_delta schema invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_VISIBILITY_DELTA_SCHEMA_INVALID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.96
Error Mode: POST_OUTPUTS_VISIBILITY_DELTA_SCHEMA_INVALID

ID: 7.2.2.97
Title: outputs.visibility_delta.now_visible schema invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_NOW_VISIBLE_ITEMS_SCHEMA_INVALID` when outputs.visibility_delta.now_visible schema invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_NOW_VISIBLE_ITEMS_SCHEMA_INVALID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.97
Error Mode: POST_OUTPUTS_NOW_VISIBLE_ITEMS_SCHEMA_INVALID

ID: 7.2.2.98
Title: outputs.visibility_delta.now_hidden UUIDs invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_NOW_HIDDEN_VALUES_INVALID_UUID` when outputs.visibility_delta.now_hidden uuids invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_NOW_HIDDEN_VALUES_INVALID_UUID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.98
Error Mode: POST_OUTPUTS_NOW_HIDDEN_VALUES_INVALID_UUID

ID: 7.2.2.99
Title: outputs.suppressed_answers UUIDs invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_SUPPRESSED_ANSWERS_VALUES_INVALID_UUID` when outputs.suppressed_answers uuids invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_SUPPRESSED_ANSWERS_VALUES_INVALID_UUID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.99
Error Mode: POST_OUTPUTS_SUPPRESSED_ANSWERS_VALUES_INVALID_UUID

ID: 7.2.2.100
Title: outputs.headers.screen_etag missing on GET
Purpose: Verify that the system surfaces `POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING_ON_GET` when outputs.headers.screen_etag missing on get.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING_ON_GET`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.100
Error Mode: POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING_ON_GET

ID: 7.2.2.101
Title: outputs.headers.screen_etag missing on PATCH
Purpose: Verify that the system surfaces `POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING_ON_PATCH` when outputs.headers.screen_etag missing on patch.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING_ON_PATCH`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.101
Error Mode: POST_OUTPUTS_HEADERS_SCREEN_ETAG_MISSING_ON_PATCH

ID: 7.2.2.102
Title: outputs.batch_result schema invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_BATCH_RESULT_SCHEMA_INVALID` when outputs.batch_result schema invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_BATCH_RESULT_SCHEMA_INVALID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.102
Error Mode: POST_OUTPUTS_BATCH_RESULT_SCHEMA_INVALID

ID: 7.2.2.103
Title: outputs.batch_result.items schema invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_BATCH_RESULT_ITEMS_SCHEMA_INVALID` when outputs.batch_result.items schema invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_BATCH_RESULT_ITEMS_SCHEMA_INVALID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.103
Error Mode: POST_OUTPUTS_BATCH_RESULT_ITEMS_SCHEMA_INVALID

ID: 7.2.2.104
Title: outputs.batch_result.items[].question_id missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_BATCH_RESULT_ITEM_QUESTION_ID_MISSING` when outputs.batch_result.items[].question_id missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_BATCH_RESULT_ITEM_QUESTION_ID_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.104
Error Mode: POST_OUTPUTS_BATCH_RESULT_ITEM_QUESTION_ID_MISSING

ID: 7.2.2.105
Title: outputs.batch_result.items[].outcome missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_BATCH_RESULT_ITEM_OUTCOME_MISSING` when outputs.batch_result.items[].outcome missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_BATCH_RESULT_ITEM_OUTCOME_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.105
Error Mode: POST_OUTPUTS_BATCH_RESULT_ITEM_OUTCOME_MISSING

ID: 7.2.2.106
Title: outputs.events schema invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_EVENTS_ITEMS_SCHEMA_INVALID` when outputs.events schema invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_EVENTS_ITEMS_SCHEMA_INVALID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.106
Error Mode: POST_OUTPUTS_EVENTS_ITEMS_SCHEMA_INVALID

ID: 7.2.2.107
Title: outputs.events[].type missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_EVENTS_TYPE_MISSING` when outputs.events[].type missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_EVENTS_TYPE_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.107
Error Mode: POST_OUTPUTS_EVENTS_TYPE_MISSING

ID: 7.2.2.108
Title: outputs.events[].payload missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_EVENTS_PAYLOAD_MISSING` when outputs.events[].payload missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_EVENTS_PAYLOAD_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.108
Error Mode: POST_OUTPUTS_EVENTS_PAYLOAD_MISSING

ID: 7.2.2.109
Title: outputs.events[].payload.response_set_id missing
Purpose: Verify that the system surfaces `POST_OUTPUTS_EVENTS_PAYLOAD_RESPONSE_SET_ID_MISSING` when outputs.events[].payload.response_set_id missing.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_EVENTS_PAYLOAD_RESPONSE_SET_ID_MISSING`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.109
Error Mode: POST_OUTPUTS_EVENTS_PAYLOAD_RESPONSE_SET_ID_MISSING

ID: 7.2.2.110
Title: outputs.events[].payload.question_id invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_EVENTS_PAYLOAD_QUESTION_ID_INVALID_UUID` when outputs.events[].payload.question_id invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_EVENTS_PAYLOAD_QUESTION_ID_INVALID_UUID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.110
Error Mode: POST_OUTPUTS_EVENTS_PAYLOAD_QUESTION_ID_INVALID_UUID

ID: 7.2.2.111
Title: outputs.events[].payload.state_version invalid
Purpose: Verify that the system surfaces `POST_OUTPUTS_EVENTS_PAYLOAD_STATE_VERSION_INVALID` when outputs.events[].payload.state_version invalid.
Test Data: HTTP GET /api/v1/response-sets/11111111-1111-1111-1111-111111111111/screens/employment; Headers: None; Body: None
Mocking:
- Mock `app.logic.repository_screens.list_questions_for_screen` to return [{'id': 'bad', 'kind': 'x'}]; reason: force serializer inconsistency to trigger contract validator; usage: assert_called_once_with('employment').
Assertions:
- Response Content-Type is `application/problem+json`.
- Response body `code` == `POST_OUTPUTS_EVENTS_PAYLOAD_STATE_VERSION_INVALID`.
- HTTP status == 500.
- Contract validator triggers and no partial payload is emitted beyond minimal problem details.
AC-Ref: 6.2.2.111
Error Mode: POST_OUTPUTS_EVENTS_PAYLOAD_STATE_VERSION_INVALID

Here are the **7.3 Happy Path Behavioural Tests**, one-for-one with the behavioural ACs in section 6.3.1, in the same order.

**7.3.1.1 — Evaluate visibility before assembly**

* **Title:** Visibility evaluation precedes screen assembly
* **Purpose:** Verify that visible question computation is invoked before any screen assembly work begins.
* **Test Data:** `response_set_id="11111111-1111-1111-1111-111111111111"`, `screen_key="eligibility"`
* **Mocking:**
  Mock `repository_screens.get_visibility_rules_for_screen(screen_key)` to return a minimal rule set; mock `visibility_rules.compute_visible_set(rules, parent_values)` to return `{"q1","q2"}`; mock a screen assembler function (e.g., `screen_builder.assemble(...)`) to no-op. Mocks return dummy successes to allow sequencing.
* **Assertions:** Assert `visibility_rules.compute_visible_set` is invoked once immediately after `get_visibility_rules_for_screen` returns; assert `screen_builder.assemble` is not invoked until after `compute_visible_set` completes; assert no calls to `assemble` occur prior to visibility evaluation.
* **AC-Ref:** 6.3.1.1

**7.3.1.2 — Filter questions to the visible set**

* **Title:** Filtering occurs immediately after visibility computation
* **Purpose:** Verify that question filtering is triggered using the computed visible IDs before hydration begins.
* **Test Data:** Same IDs as 7.3.1.1; `visible_ids={"q1","q2"}`; repository screens questions `["q1","q2","q3"]`.
* **Mocking:**
  Mock `repository_screens.list_questions_for_screen(screen_key)` to return `["q1","q2","q3"]`; mock `filter.apply_visible_filter(all_questions, visible_ids)` to return `["q1","q2"]`; mock `repository_answers.get_existing_answer(...)` to no-op success.
* **Assertions:** Assert `filter.apply_visible_filter` is invoked once immediately after `compute_visible_set` completes, and not before; assert `repository_answers.get_existing_answer` is not invoked until after filtering completes.
* **AC-Ref:** 6.3.1.2

**7.3.1.3 — Hydrate answers after filtering**

* **Title:** Hydration starts only after filtering completes
* **Purpose:** Verify that answer hydration triggers after filtering and not before.
* **Test Data:** Same IDs; filtered questions `["q1","q2"]`.
* **Mocking:**
  Mock `repository_answers.get_existing_answer(response_set_id, question_id)` to return dummy records; mocks return success to allow flow.
* **Assertions:** Assert `repository_answers.get_existing_answer` for `"q1"` and `"q2"` are each invoked once immediately after `filter.apply_visible_filter` completes, and not before; assert no hydration call happens for `"q3"`.
* **AC-Ref:** 6.3.1.3

**7.3.1.4 — Assemble screen after hydration**

* **Title:** Assembly begins after hydration finishes
* **Purpose:** Verify that screen assembly is initiated only after all required hydrations complete.
* **Test Data:** Same IDs; filtered questions `["q1","q2"]`.
* **Mocking:**
  Mock `screen_builder.assemble(screen_key, questions_with_answers)` to no-op success. Other mocks as above to allow flow.
* **Assertions:** Assert `screen_builder.assemble` is invoked once immediately after the last `repository_answers.get_existing_answer` completes, and not before; assert assembly receives only hydrated visible questions.
* **AC-Ref:** 6.3.1.4

**7.3.1.5 — Compute visibility delta after save**

* **Title:** Post-save delta computation is triggered
* **Purpose:** Verify that after a single-answer save, visibility delta calculation is invoked.
* **Test Data:** `response_set_id="1111..."`, `screen_key="eligibility"`, `question_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"`
* **Mocking:**
  Mock `repository_answers.upsert(...)` to succeed; mock pre/post visible sets acquisition helpers to return `{"q1"}` pre and `{"q1","q2"}` post; mock `visibility_delta.compute_visibility_delta(pre, post, has_answer)` to no-op success.
* **Assertions:** Assert `visibility_delta.compute_visibility_delta` is invoked once immediately after the save completes, and not before.
* **AC-Ref:** 6.3.1.5

**7.3.1.6 — Hydrate newly visible items after delta**

* **Title:** Hydration for now-visible items follows delta
* **Purpose:** Verify that hydration for `now_visible` questions starts right after delta computation.
* **Test Data:** `now_visible=["q2","q4"]`
* **Mocking:**
  Mock `visibility_delta.compute_visibility_delta` to return `now_visible=["q2","q4"]`; mock `repository_answers.get_existing_answer` to success.
* **Assertions:** Assert `repository_answers.get_existing_answer` for `"q2"` and `"q4"` are each invoked once immediately after `compute_visibility_delta` completes, and not before.
* **AC-Ref:** 6.3.1.6

**7.3.1.7 — Rebuild screen after applying delta**

* **Title:** Screen rebuild triggers after delta hydration
* **Purpose:** Verify that a screen rebuild is initiated after hydrating `now_visible` items.
* **Test Data:** Same as 7.3.1.6.
* **Mocking:**
  Mock `screen_builder.assemble(...)` to no-op success; hydration mocks as above.
* **Assertions:** Assert `screen_builder.assemble` is invoked once immediately after the last hydration of `now_visible` completes, and not before.
* **AC-Ref:** 6.3.1.7

**7.3.1.8 — Omit hidden questions during assembly**

* **Title:** Assembly does not initiate for hidden items
* **Purpose:** Verify that assembly excludes any `now_hidden` items and does not trigger assembly work for them.
* **Test Data:** `visible_ids={"q1","q3"}`, `now_hidden=["q2"]`
* **Mocking:**
  Mock `visibility_rules.compute_visible_set` to return `{"q1","q3"}`; mock `screen_builder.assemble` to capture the question IDs it assembles.
* **Assertions:** Assert `screen_builder.assemble` is invoked once immediately after hydration completes, and not before; assert the invocation excludes `"q2"` and includes only `"q1","q3"`.
* **AC-Ref:** 6.3.1.8

**7.3.1.9 — Clear before delta when clear=true**

* **Title:** Clear operation precedes delta computation
* **Purpose:** Verify that when `clear=true`, the clear persists before delta is computed.
* **Test Data:** `response_set_id="1111..."`, `question_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"`, `clear=true`
* **Mocking:**
  Mock `repository_answers.clear(response_set_id, question_id)` to success; mock `visibility_delta.compute_visibility_delta` to success.
* **Assertions:** Assert `repository_answers.clear` is invoked once immediately after request validation completes; assert `visibility_delta.compute_visibility_delta` is not invoked until after `clear` completes.
* **AC-Ref:** 6.3.1.9

**7.3.1.10 — Mandatory questions do not block flow**

* **Title:** Flow proceeds despite unanswered mandatory items
* **Purpose:** Verify that assembly proceeds even if a mandatory question is unanswered.
* **Test Data:** Screen contains mandatory `"q1"` without an answer; `visible_ids={"q1"}`
* **Mocking:**
  Mock hydration to return “no answer” for `"q1"`; mock `screen_builder.assemble` to succeed.
* **Assertions:** Assert `screen_builder.assemble` is invoked once immediately after hydration completes, and not before; assert no precondition prevents assembly due to missing answer.
* **AC-Ref:** 6.3.1.10

**7.3.1.11 — Batch processes items sequentially**

* **Title:** Batch processes answers strictly in sequence
* **Purpose:** Verify that, in batch mode, the next item starts only after the previous item completes.
* **Test Data:** Two items: `[{question_id:"q1"}, {question_id:"q2"}]`
* **Mocking:**
  Mock `batch_processor.process_item(i)` to succeed; instrument to capture call order; no parallelism introduced by mocks.
* **Assertions:** Assert `process_item("q1")` is invoked once; assert `process_item("q2")` is invoked once immediately after `process_item("q1")` completes, and not before.
* **AC-Ref:** 6.3.1.11

**7.3.1.12 — Batch continues after item failure**

* **Title:** Batch continues to next item after a failure
* **Purpose:** Verify that a failed item does not prevent the next item from starting.
* **Test Data:** Three items: `["q1","q2","q3"]`
* **Mocking:**
  Mock `process_item("q1")` to succeed, `process_item("q2")` to raise a handled item error, `process_item("q3")` to succeed; mocks only at the boundary to observe sequencing.
* **Assertions:** Assert `process_item("q2")` failure occurs; assert `process_item("q3")` is invoked once immediately after handling the failure of `"q2"`, and not before; assert overall batch controller continues sequencing.
* **AC-Ref:** 6.3.1.12

**7.3.1.13 — Cascade delete answers after set delete**

* **Title:** Deleting a response set triggers answer deletions
* **Purpose:** Verify that answer deletion is triggered immediately after the response set deletion succeeds.
* **Test Data:** `response_set_id="22222222-2222-2222-2222-222222222222"`
* **Mocking:**
  Mock `repository_response_sets.delete(response_set_id)` to succeed; mock `repository_answers.delete_all_for_set(response_set_id)` to succeed; mocks return success to allow flow.
* **Assertions:** Assert `repository_answers.delete_all_for_set` is invoked once immediately after `repository_response_sets.delete` completes, and not before.
* **AC-Ref:** 6.3.1.13

**7.3.2.1**
**Title:** Document ETag mismatch prevents content update
**Purpose:** Prevent content persistence when the document ETag check fails.
**Test Data:** `PUT /documents/{D}/content` with header `If-Match: W/"doc-v1"` while current is `W/"doc-v2"`.
**Mocking:** Spy the content persistence component; mock the ETag checker to return a mismatch (no other mocks).
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Inclusions (content concurrency check)** raises, and not before. Assert content persistence is not invoked following the failure. Assert that error mode `RUN_DOCUMENT_ETAG_MISMATCH` is observed.
**AC-Ref:** 6.3.2.7. 
**Error Mode:** RUN_DOCUMENT_ETAG_MISMATCH

---

**7.3.2.2**
**Title:** State retention failure halts metadata access
**Purpose:** Stop downstream retrieval when a state read fails.
**Test Data:** `GET /documents/{D}` for an existing ID.
**Mocking:** Mock `repository.read({D})` to raise a state corruption/read error; expose serializer/response builder as spy-only.
**Assertions:** Assert error handler is invoked once immediately when **STEP-4 Context (metadata read)** raises, and not before. Assert downstream retrieval/serialization is not invoked following the failure. Assert that error mode `RUN_STATE_RETENTION_FAILURE` is observed.
**AC-Ref:** 6.3.2.8. 
**Error Mode:** RUN_STATE_RETENTION_FAILURE

---

**7.3.2.3**
**Title:** Stitched access failure halts external supply
**Purpose:** Prevent stitched-response flow when ordered-doc supply fails.
**Test Data:** External orchestrator call that requests ordered documents for stitching.
**Mocking:** Mock the “supply ordered docs” gateway to raise an access failure; stitched response builder as spy-only.
**Assertions:** Assert error handler is invoked once immediately when **STEP-4 Context (stitched access)** raises, and not before. Assert stitched response builder is not invoked following the failure. Assert that error mode `RUN_OPTIONAL_STITCH_ACCESS_FAILURE` is observed.
**AC-Ref:** 6.3.2.9. 
**Error Mode:** RUN_OPTIONAL_STITCH_ACCESS_FAILURE

---

**7.3.2.4**
**Title:** Ingestion interface unavailable halts ingestion flow
**Purpose:** Prevent gating call and any further flow when the ingestion interface cannot be constructed.
**Test Data:** Internal call `IngestionInterface.upsertAnswers([...])`.
**Mocking:** Mock interface client construction to raise `RUN_INGESTION_INTERFACE_UNAVAILABLE`; assert attempted once.
**Assertions:** Assert error handler is invoked once immediately when **STEP-5: Interfaces for ingestion and generation** raises, and not before. Assert no gating call is attempted. Assert error mode `RUN_INGESTION_INTERFACE_UNAVAILABLE` is observed.
**AC-Ref:** 6.3.2.11. 
**Error Mode:** RUN_INGESTION_INTERFACE_UNAVAILABLE

---

**7.3.2.5**
**Title:** Generation gate call failure blocks finalisation
**Purpose:** Stop generation flow when the gating check call fails.
**Test Data:** `POST /generation/start` triggers internal `GatingClient.regenerateCheck(...)`.
**Mocking:** Mock `GatingClient.regenerateCheck` to raise `RUN_GENERATION_GATE_CALL_FAILED`; assert called.
**Assertions:** Assert error handler is invoked once immediately when **STEP-5** gating call raises, and not before. Assert no generation proceeds. Assert error mode `RUN_GENERATION_GATE_CALL_FAILED` is observed.
**AC-Ref:** 6.3.2.12. 
**Error Mode:** RUN_GENERATION_GATE_CALL_FAILED

---

**7.3.2.6**
**Title:** Autosave DB write failure halts autosave
**Purpose:** Ensure autosave stops immediately when the answer upsert write fails.
**Test Data:** `PATCH /response-sets/{RS}/answers/{Q}` with body `{ "value": "Acme Ltd" }`, headers `If-Match: "v3"`.
**Mocking:** Mock `AnswerRepository.upsert(...)` to raise `RUN_ANSWER_UPSERT_DB_WRITE_FAILED`; assert called with `(response_set_id, question_id, value)`.
**Assertions:** Assert error handler is invoked once immediately when **STEP-6: Autosave per answer** raises, and not before. Assert no idempotency/ETag steps run. Assert error mode `RUN_ANSWER_UPSERT_DB_WRITE_FAILED` is observed.
**AC-Ref:** 6.3.2.13. 
**Error Mode:** RUN_ANSWER_UPSERT_DB_WRITE_FAILED

---

**7.3.2.7**
**Title:** Idempotency store unavailable halts autosave
**Purpose:** Block response emission when idempotency persistence fails.
**Test Data:** Same PATCH as 7.3.2.6 with `Idempotency-Key: "K1"`.
**Mocking:** Allow `AnswerRepository.upsert` to succeed; mock `IdempotencyStore.record(key, fingerprint, result)` to raise `RUN_IDEMPOTENCY_STORE_UNAVAILABLE`; assert called with `"K1"`.
**Assertions:** Assert error handler is invoked once immediately when **STEP-6** idempotency persistence raises, and not before. Assert response not returned. Assert error mode `RUN_IDEMPOTENCY_STORE_UNAVAILABLE` is observed.
**AC-Ref:** 6.3.2.14. 
**Error Mode:** RUN_IDEMPOTENCY_STORE_UNAVAILABLE

---

**7.3.2.8**
**Title:** ETag compute failure blocks finalisation of autosave
**Purpose:** Prevent finalisation when ETag computation fails.
**Test Data:** Same PATCH as 7.3.2.6.
**Mocking:** Mock `Etag.compute(payload)` to raise `RUN_ETAG_COMPUTE_FAILED`; assert called once.
**Assertions:** Assert error handler is invoked once immediately when **STEP-6** ETag computation raises, and not before. Assert response not committed. Assert error mode `RUN_ETAG_COMPUTE_FAILED` is observed.
**AC-Ref:** 6.3.2.15. 
**Error Mode:** RUN_ETAG_COMPUTE_FAILED

---

**7.3.2.9**
**Title:** Concurrency token generation failure blocks autosave finalisation
**Purpose:** Stop finalisation when version/concurrency token cannot be produced.
**Test Data:** Same PATCH as 7.3.2.6.
**Mocking:** Mock `VersioningToken.issue(question_id, response_set_id)` to raise `RUN_CONCURRENCY_TOKEN_GENERATION_FAILED`; assert called.
**Assertions:** Assert error handler is invoked once immediately when **STEP-6** token generation raises, and not before. Assert response not sent. Assert error mode `RUN_CONCURRENCY_TOKEN_GENERATION_FAILED` is observed.
**AC-Ref:** 6.3.2.16. 
**Error Mode:** RUN_CONCURRENCY_TOKEN_GENERATION_FAILED

---

**7.3.2.10**
**Title:** Import stream read failure halts import
**Purpose:** Stop import processing when CSV stream reading fails.
**Test Data:** `POST /questionnaires/import` with a mocked stream “broken pipe”.
**Mocking:** Mock `CsvStream.readChunk()` to raise `RUN_IMPORT_STREAM_READ_FAILED` on first read; assert called once.
**Assertions:** Assert error handler is invoked once immediately when **STEP-7: Bulk import and export** read raises, and not before. Assert no transaction is started. Assert error mode `RUN_IMPORT_STREAM_READ_FAILED` is observed.
**AC-Ref:** 6.3.2.17. 
**Error Mode:** RUN_IMPORT_STREAM_READ_FAILED

---

**7.3.2.11**
**Title:** Import transaction failure halts import
**Purpose:** Stop import when the commit/transaction fails.
**Test Data:** Same POST with minimal valid CSV rows.
**Mocking:** Allow parsing; mock `ImportUnitOfWork.commit()` to raise `RUN_IMPORT_TRANSACTION_FAILED`; assert called once.
**Assertions:** Assert error handler is invoked once immediately when **STEP-7** transaction commit raises, and not before. Assert no success summary is produced. Assert error mode `RUN_IMPORT_TRANSACTION_FAILED` is observed.
**AC-Ref:** 6.3.2.18. 
**Error Mode:** RUN_IMPORT_TRANSACTION_FAILED

---

**7.3.2.12**
**Title:** Export snapshot query failure halts export
**Purpose:** Prevent export streaming when snapshot query fails.
**Test Data:** `GET /questionnaires/{id}/export`.
**Mocking:** Mock `ExportRepository.buildRowset(questionnaire_id)` to raise `RUN_EXPORT_SNAPSHOT_QUERY_FAILED`; assert called with id.
**Assertions:** Assert error handler is invoked once immediately when **STEP-7** query raises, and not before. Assert no streaming begins. Assert error mode `RUN_EXPORT_SNAPSHOT_QUERY_FAILED` is observed.
**AC-Ref:** 6.3.2.19. 
**Error Mode:** RUN_EXPORT_SNAPSHOT_QUERY_FAILED

---

**7.3.2.13**
**Title:** Export row projection failure blocks finalisation
**Purpose:** Stop export finalisation when row projection/formatting fails.
**Test Data:** Same `GET /questionnaires/{id}/export`.
**Mocking:** Let query succeed; mock `ExportProjector.project(row)` to raise `RUN_EXPORT_ROW_PROJECTION_FAILED` for first row; assert called.
**Assertions:** Assert error handler is invoked once immediately when **STEP-7** row projection raises, and not before. Assert no export finalisation occurs. Assert error mode `RUN_EXPORT_ROW_PROJECTION_FAILED` is observed.
**AC-Ref:** 6.3.2.20. 
**Error Mode:** RUN_EXPORT_ROW_PROJECTION_FAILED

**7.3.2.22**
**Title:** Network unreachable halts DB write and prevents downstream steps
**Purpose:** Verify the pipeline halts at the DB write step and prevents visibility delta and response assembly when the network is unreachable.
**Test Data:** PATCH `/api/v1/response-sets/RS1/answers/Q1` with `If-Match: "W/\"123\""` and body `{ "value": true }`.
**Mocking:** Mock the DB connector used by **STEP-3 Upsert answer** to raise `OSError("Network is unreachable")` on connect; no other mocks. Assert the connector’s `connect()` called once with configured host/port.
**Assertions:** Assert error handler is invoked once immediately when **STEP-3** raises, and not before. Assert **STEP-5 Compute visibility delta** and **STEP-6 Build screen_view + Screen-ETag** are not invoked following the failure. Assert that error mode **ENV_NETWORK_UNREACHABLE** is observed. Assert no unintended retries and one error telemetry event is emitted.
**AC-Ref:** 6.3.2.19
**Error Mode:** ENV_NETWORK_UNREACHABLE

---

**7.3.2.23**
**Title:** DNS failure halts DB write and stops propagation
**Purpose:** Verify name-resolution failure at the DB boundary halts the pipeline before any downstream work.
**Test Data:** PATCH same as 7.3.2.22.
**Mocking:** Patch `socket.getaddrinfo()` used by the DB driver in **STEP-3 Upsert answer** to raise `socket.gaierror("Name or service not known")`.
**Assertions:** Assert error handler is invoked once immediately when **STEP-3** raises, and not before. Assert **STEP-5** and **STEP-6** are not invoked. Assert **ENV_DNS_FAILURE** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.20
**Error Mode:** ENV_DNS_FAILURE

---

**7.3.2.24**
**Title:** TLS handshake failure halts DB write and prevents downstream steps
**Purpose:** Ensure TLS failure at the DB boundary stops the flow prior to delta calculation and response assembly.
**Test Data:** PATCH as above.
**Mocking:** Mock DB driver’s SSL handshake in **STEP-3** to raise `ssl.SSLError("TLS handshake failed")`.
**Assertions:** Assert error handler invoked once when **STEP-3** raises. Assert **STEP-5** and **STEP-6** not invoked. Assert **ENV_TLS_HANDSHAKE_FAILED** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.21
**Error Mode:** ENV_TLS_HANDSHAKE_FAILED

---

**7.3.2.25**
**Title:** Missing runtime configuration halts screen read initialisation
**Purpose:** Verify missing mandatory config (e.g., DB URL) halts at the first screen read initialisation step.
**Test Data:** GET `/api/v1/response-sets/RS1/screens/personal_details`.
**Mocking:** Mock config loader used by **STEP-1 Screen read (hydrate & rules load)** to raise `KeyError("DATABASE_URL")`.
**Assertions:** Assert error handler invoked once when **STEP-1** raises, and not before. Assert **STEP-2 Evaluate visibility** is not invoked. Assert **ENV_CONFIG_MISSING** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.22
**Error Mode:** ENV_CONFIG_MISSING

---

**7.3.2.26**
**Title:** Secret manager access denied halts initialisation
**Purpose:** Verify denial from secret manager stops the flow before any DB or visibility work.
**Test Data:** GET as above.
**Mocking:** Mock secret provider used by **STEP-1 Screen read** to raise `PermissionError("access denied")`. Assert called once for the required secret name.
**Assertions:** Assert error handler invoked once when **STEP-1** raises. Assert **STEP-2** not invoked. Assert **ENV_SECRET_ACCESS_DENIED** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.23
**Error Mode:** ENV_SECRET_ACCESS_DENIED

---

**7.3.2.27**
**Title:** Message broker unavailable prevents event emission but allows degraded completion
**Purpose:** Ensure event emission failure does not cascade; flow continues without publishing.
**Test Data:** PATCH as 7.3.2.22 (valid answer).
**Mocking:** Mock message broker client used by **STEP-7 Emit response.saved** to raise `ConnectionError("broker down")` on `publish`.
**Assertions:** Assert error handler invoked once when **STEP-7** raises, and not before. Assert no retry loop; Assert **STEP-7** is not re-invoked; Assert no downstream steps depend on publish and execution does not backtrack (flow continues as already-completed). Assert **ENV_MESSAGE_BROKER_UNAVAILABLE** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.24
**Error Mode:** ENV_MESSAGE_BROKER_UNAVAILABLE

---

**7.3.2.28**
**Title:** Database unavailable halts write path and prevents visibility delta/response build
**Purpose:** Verify DB outage during write stops subsequent steps.
**Test Data:** PATCH as above.
**Mocking:** Mock DB pool acquisition in **STEP-3 Upsert answer** to raise `TimeoutError("pool exhausted")` (or driver-specific “connection refused”).
**Assertions:** Assert error handler invoked once when **STEP-3** raises. Assert **STEP-5** and **STEP-6** not invoked. Assert **ENV_DATABASE_UNAVAILABLE** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.25
**Error Mode:** ENV_DATABASE_UNAVAILABLE

---

**7.3.2.29**
**Title:** Filesystem becomes read-only during ETag/materialisation step halts response assembly
**Purpose:** Verify local FS immutability prevents screen_view/ETag materialisation phase.
**Test Data:** PATCH as above (assume prior steps pass).
**Mocking:** Mock temp file creation used by **STEP-6 Build screen_view + Screen-ETag** to raise `OSError("Read-only file system")`.
**Assertions:** Assert error handler invoked once when **STEP-6** raises. Assert no subsequent finalisation steps execute; Assert **ENV_FILESYSTEM_READONLY** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.29
**Error Mode:** ENV_FILESYSTEM_READONLY

---

**7.3.2.30**
**Title:** Disk space exhaustion halts response assembly
**Purpose:** Ensure lack of disk space stops at the assembly step without partial continuation.
**Test Data:** PATCH as above.
**Mocking:** Mock write in **STEP-6** to raise `OSError("No space left on device")`.
**Assertions:** Assert error handler invoked once when **STEP-6** raises. Assert downstream steps are not invoked. Assert **ENV_DISK_SPACE_EXHAUSTED** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.30
**Error Mode:** ENV_DISK_SPACE_EXHAUSTED

---

**7.3.2.31**
**Title:** Temp directory unavailable halts response assembly
**Purpose:** Verify absence of temp dir blocks assembly without subsequent calls.
**Test Data:** PATCH as above.
**Mocking:** Mock temp dir resolver used by **STEP-6** to raise `FileNotFoundError("temp dir missing")`.
**Assertions:** Assert error handler invoked once when **STEP-6** raises. Assert no downstream steps execute. Assert **ENV_TEMP_DIR_UNAVAILABLE** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.31
**Error Mode:** ENV_TEMP_DIR_UNAVAILABLE

---

**7.3.2.32**
**Title:** Rate limit exceeded on broker send prevents emission and stops propagation to retries
**Purpose:** Confirm rate-limit on broker send prevents emission and does not trigger unbounded retries.
**Test Data:** PATCH as above.
**Mocking:** Mock message broker client in **STEP-7** to raise a typed `RateLimitError("429")`.
**Assertions:** Assert error handler invoked once when **STEP-7** raises. Assert **STEP-7** not re-invoked; Assert no retry without backoff; Assert **ENV_RATE_LIMIT_EXCEEDED** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.32
**Error Mode:** ENV_RATE_LIMIT_EXCEEDED

---

**7.3.2.33**
**Title:** Quota exceeded on DB prevents write and downstream steps
**Purpose:** Verify provider quota block halts write and prevents delta/response assembly.
**Test Data:** PATCH as above.
**Mocking:** Mock DB driver in **STEP-3** to raise driver-specific `QuotaExceeded("quota exceeded")`.
**Assertions:** Assert error handler invoked once when **STEP-3** raises. Assert **STEP-5** and **STEP-6** not invoked. Assert **ENV_QUOTA_EXCEEDED** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.33
**Error Mode:** ENV_QUOTA_EXCEEDED

---

**7.3.2.34**
**Title:** System time skew detected blocks ETag-gated flow
**Purpose:** Ensure time synchronisation failure blocks operations that depend on clock monotonicity for ETag gating.
**Test Data:** GET then PATCH sequence with `If-Match` from GET.
**Mocking:** Mock time source used by **STEP-6 Build screen_view + Screen-ETag** (and/or ETag validator) to return skewed values triggering a `TimeSkewError("clock skew")`.
**Assertions:** Assert error handler invoked once when **STEP-6** raises due to skew. Assert no further steps execute. Assert **ENV_TIME_SKEW_DETECTED** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.34
**Error Mode:** ENV_TIME_SKEW_DETECTED

---

**7.3.2.35**
**Title:** Object storage unavailable prevents any optional offload step and stops propagation
**Purpose:** If an optional offload exists, ensure storage outage prevents that step and stops further storage-dependent work.
**Test Data:** PATCH as above (triggering the optional offload path if present).
**Mocking:** Mock object storage client used by **STEP-6** (if offload sub-step exists) to raise `ConnectionError("S3 unreachable")`.
**Assertions:** Assert error handler invoked once when the offload sub-step of **STEP-6** raises. Assert no further storage sub-steps run. Assert **ENV_OBJECT_STORAGE_UNAVAILABLE** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.35
**Error Mode:** ENV_OBJECT_STORAGE_UNAVAILABLE

---

**7.3.2.36**
**Title:** Object storage permission denied prevents offload and stops propagation
**Purpose:** Ensure permission errors at storage boundary stop storage sub-steps without retries.
**Test Data:** PATCH as above (offload path).
**Mocking:** Mock object storage client in **STEP-6** to raise `PermissionError("AccessDenied")`.
**Assertions:** Assert error handler invoked once when the storage sub-step of **STEP-6** raises. Assert no retries; Assert no subsequent storage calls. Assert **ENV_OBJECT_STORAGE_PERMISSION_DENIED** observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.36
**Error Mode:** ENV_OBJECT_STORAGE_PERMISSION_DENIED