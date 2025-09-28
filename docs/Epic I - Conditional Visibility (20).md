# Epic I — Conditional Visibility (placeholder)

## Purpose

Make the backend authoritative for conditional visibility: hide child questions when their parent condition is not met, and reveal them immediately when it is, without requiring the client to reload the whole screen.

## Data prerequisites

* We rely on fields already introduced in Epic A.1 on `QuestionnaireQuestion`:

  * `parent_question_id` (nullable)
  * `visible_if_value` (nullable, string literal to compare against the parent’s current value; applies to the parent’s canonical value, e.g., for `enum_single` the selected option’s `value`).
* No additional schema is required for this placeholder.

## GET filter behaviour

### GET `/response-sets/{response_set_id}/screens/{screen_id}`

* **Load** all questions for `screen_id` plus current answers for `response_set_id`.
* **Evaluate** visibility:

  * If `parent_question_id` is null → **visible** (base question).
  * Else, **visible** iff the parent’s current canonical answer equals `visible_if_value`.
  * If parent unanswered → **hidden** by default.
* **Return** only the **visible** questions (children that fail the check are **omitted**), alongside current answers for those questions.
* **Do not** return rules or hidden questions in this endpoint (keep payload minimal and deterministic).

## Autosave-driven updates

### PATCH `/response-sets/{response_set_id}/answers/{question_id}`

* **Persist** the single-field change (idempotent; honors concurrency headers as per Epic B).
* **Re-evaluate impacted subtree**:

  * Walk direct and transitive children where `parent_question_id` links to the changed `question_id` (BFS/DFS until fixpoint).
  * For each child, recompute visibility via the same equality check.
* **Respond with deltas** (so the client doesn’t reload the whole screen):

  ```json
  {
    "saved": { "question_id": "…", "state_version": 42 },
    "visibility_delta": {
      "now_visible": ["q_child_1", "q_grandchild_3"],
      "now_hidden": ["q_child_2"]
    },
    "suppressed_answers": ["q_child_2"]   // if any hidden questions had stored answers
  }
  ```
* **Suppression policy**: answers to newly hidden questions are **retained but ignored** by downstream logic; server returns their IDs so the UI can clear inputs locally if desired. (No cascaded deletes.)

## Notes & boundaries

* **Equality only**: the first cut supports simple equality against `visible_if_value`. (This matches the current templates and avoids over-engineering.)
* **Type handling**: comparison is against the parent’s **canonical stored value** (e.g., the `value` of an `enum_single` option). Booleans/number strings are normalized before comparison.
* **No FE rules**: the frontend does not carry or evaluate rules; it relies on server filtering in GET and **deltas** in PATCH responses.
* **Performance**: subtree re-evaluation is limited to descendants of the changed node; no full-screen recompute or reload.

This is enough to slot into the other epic’s functional outline later, and it stays aligned with what we already agreed: backend filtering on GET, and minimal **delta** updates on autosave.

### 1. Scope  

#### 1.1 Purpose  
Enable conditional visibility of questionnaire questions so that only relevant follow-up questions are shown to the user, improving clarity and reducing input errors.  

#### 1.2 Inclusions  
- Server-side control of when a question is displayed, based on the answer to its parent question.  
- Automatic hiding of child questions when the parent condition is not met.  
- Automatic showing of child questions when the parent condition is satisfied.  
- Return of only visible questions in screen responses.  
- Delta updates to inform the client when visibility changes after an answer is saved.  
- Notification to the client when hidden questions have existing answers that should be suppressed locally.  

#### 1.3 Exclusions  
- Complex conditional logic such as ranges, multi-value checks, or cross-screen dependencies.  
- Client-side evaluation of visibility rules.  
- Deletion or permanent removal of suppressed answers.  
- Performance optimisations beyond those needed for screen-level evaluation.  

#### 1.4 Context  
This story builds on the existing questionnaire service, extending Epic B’s screen retrieval and autosave features to include conditional visibility. It ensures that the backend is the single source of truth for which questions are presented, while the frontend remains a simple renderer of server output. It interacts only with the questionnaire API; no additional systems or integrations are required. This function ensures consistency across clients and prepares the platform for broader rule handling in future epics.

### 2.2. EARS Functionality

#### 2.2.1 Ubiquitous requirements

* **U1** The system will evaluate question visibility based on `parent_question_id` and `visible_if_value`.
* **U2** The system will normalise parent answers to canonical values before comparison.
* **U3** The system will omit hidden questions from screen responses.
* **U4** The system will ensure suppressed answers are retained in storage but ignored in downstream logic.
* **U5** The system will preserve deterministic behaviour by returning the same visible set for the same state.

#### 2.2.2 Event-driven requirements

* **E1** When a client requests a screen, the system will load all questions and current answers for that screen.
* **E2** When a client requests a screen, the system will compute visibility for each question and return only those marked visible.
* **E3** When an answer is patched, the system will persist the new value.
* **E4** When an answer is patched, the system will re-evaluate visibility for all descendant questions of the changed answer.
* **E5** When an answer is patched, the system will return a visibility_delta containing lists of now-visible and now-hidden questions.
* **E6** When an answer is patched, the system will return identifiers of suppressed answers linked to newly hidden questions.
* **E7** When an answer is patched, the system will include the updated `etag` in the response.

#### 2.2.3 State-driven requirements

* **S1** While a parent question is unanswered, the system will keep all its children hidden.
* **S2** While a parent’s canonical value equals the child’s `visible_if_value`, the system will keep the child visible.
* **S3** While a parent’s canonical value differs from the child’s `visible_if_value`, the system will keep the child hidden.

#### 2.2.4 Optional-feature requirements

* **O1** Where `enum_single` is the parent’s answer kind, the system will compare visibility using the selected option’s canonical `value`.
* **O2** Where the parent answer kind is boolean or number, the system will normalise values before comparison.
* **O3** Where the parent answer kind is short_string or long_text, the system will compare trimmed case-sensitive strings.

#### 2.2.5 Unwanted-behaviour requirements

* **N1** If a PATCH request includes an invalid type, the system will reject it with error 422.
* **N2** If a PATCH request includes a stale `If-Match` header, the system will reject it with error 409.
* **N3** If a GET or PATCH references an unknown question ID, the system will reject it with error 404.

#### 2.2.6 Step Index

* **STEP-GET-1** Load questions and answers → E1

* **STEP-GET-2** Compute visibility and return visible questions → U1, U2, U3, E2, S1, S2, S3, O1, O2, O3, U5

* **STEP-PATCH-1** Persist answer change → E3

* **STEP-PATCH-2** Re-evaluate descendant visibility → E4

* **STEP-PATCH-3** Return visibility_delta (now-visible and now-hidden) → E5

* **STEP-PATCH-4** Return suppressed answers → U4, E6

* **STEP-PATCH-5** Return updated etag → E7

* **STEP-ERROR-1** Invalid type handling → N1

* **STEP-ERROR-2** Concurrency mismatch → N2

* **STEP-ERROR-3** Unknown question ID → N3

| Field                                    | Description                                                         | Type                   | Schema / Reference                                                       | Notes                                              | Pre-Conditions                                                                                                                                             | Origin   |
| ---------------------------------------- | ------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------ | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| response_set_id                          | Identifier of the response set whose answers are in scope           | string (uuid)          | schemas/ResponseSetId.schema.json                                        | None                                               | Field is required and must be provided; Value must be a valid UUID; Value must correspond to an existing response set                                      | provided |
| screen_id                                | Identifier of the screen to render                                  | string                 | schemas/ScreenId.schema.json                                             | None                                               | Field is required and must be provided; Value must conform to the declared schema; Value must correspond to a known screen key                             | provided |
| question_id                              | Identifier of the question being updated (PATCH)                    | string (uuid)          | schemas/QuestionId.schema.json                                           | None                                               | Field is required and must be provided; Value must be a valid UUID; Value must reference an existing question                                              | provided |
| answer                                   | Request body for autosave of a single answer (PATCH)                | object                 | schemas/AnswerUpsert.schema.json                                         | Reuses Epic B payload to avoid duplication         | Field is required and must be provided; Document must parse as valid JSON; Document must conform to the referenced schema                                  | provided |
| Idempotency-Key                          | Header to ensure idempotent PATCH processing                        | string                 | openapi.yaml#/components/parameters/IdempotencyKey                       | Refer to Epic B OpenAPI parameter                  | Field is required and must be provided; Value must be a non-empty string; Value must be unique per logical PATCH attempt                                   | provided |
| If-Match                                 | Header carrying the current ETag for optimistic concurrency         | string                 | openapi.yaml#/components/parameters/IfMatch                              | Refer to Epic B OpenAPI parameter                  | Field is required and must be provided; Value must match the latest ETag for the response set state; Value must be a non-empty string                      | provided |
| QuestionnaireQuestion.parent_question_id | Reference to the parent question controlling visibility             | string (uuid)          | schemas/QuestionnaireQuestion.schema.json#/properties/parent_question_id | None                                               | Reference must resolve to an existing question_id; Value may be null when the question is a base question; Value must be a valid UUID when present         | acquired |
| QuestionnaireQuestion.visible_if_value   | Value(s) of the parent answer that make this question visible       | string or list[string] | schemas/QuestionnaireQuestion.schema.json#/properties/visible_if_value   | Accepts scalar or array per Epic I                 | Value must be null or a string or an array of strings; Each string must be a canonical parent answer value; Array order does not affect semantics          | acquired |
| Response.option_id                       | Stored option identifier for enum_single answers used in evaluation | string (uuid)          | schemas/Response.schema.json#/properties/option_id (provisional)         | Provisional JSON Schema to mirror ERD Response     | Resource must exist and be readable by the process; Value must be a valid UUID; Reference must resolve to an existing AnswerOption for the parent question | acquired |
| Response.value_bool                      | Stored boolean answer value used in evaluation                      | boolean                | schemas/Response.schema.json#/properties/value_bool (provisional)        | Provisional JSON Schema to mirror ERD Response     | Resource must exist and be readable by the process; Document must conform to the referenced schema; Value must be true or false when present               | acquired |
| Response.value_number                    | Stored numeric answer value used in evaluation                      | number                 | schemas/Response.schema.json#/properties/value_number (provisional)      | Provisional JSON Schema to mirror ERD Response     | Resource must exist and be readable by the process; Document must conform to the referenced schema; Value must be a finite number when present             | acquired |
| Response.value_text                      | Stored text answer value used in evaluation                         | string                 | schemas/Response.schema.json#/properties/value_text (provisional)        | Provisional JSON Schema to mirror ERD Response     | Resource must exist and be readable by the process; Document must conform to the referenced schema; Value must be a string when present                    | acquired |
| AnswerOption.value                       | Canonical option value token used for comparison                    | string                 | schemas/AnswerOption.schema.json#/properties/value (provisional)         | Provisional JSON Schema to mirror ERD AnswerOption | Resource must exist and be readable by the process; Document must conform to the referenced schema; Value must be present for every option                 | acquired |

| Field                                                  | Description                                                                                               | Type         | Schema / Reference                                                                                         | Notes                                                                                                                                | Post-Conditions                                                                                                                                                                                          |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- | ------------ | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| outputs                                                | Canonical container for the feature’s result (projections of API responses)                               | object       | schemas/FeatureOutputs.schema.json                                                                         | Provisional top-level container to group projections; child rows reference existing API schemas under the “exception for reuse” rule | Object validates against the referenced schema; Key set is deterministic for identical inputs; Object may omit properties not relevant to the invoked operation                                          |
| outputs.screen_view                                    | Projection of the Screen GET result containing only currently visible questions and their current answers | object       | schemas/ScreenView.schema.json                                                                             | Exception: references an existing API schema (ScreenView) rather than the provisional outputs schema                                 | Value validates against the referenced schema; Value contains only questions whose visibility condition is satisfied; Value omits all hidden questions; Field is optional and present only for GET       |
| outputs.autosave_result                                | Projection of the PATCH autosave response                                                                 | object       | schemas/AutosaveResult.schema.json                                                                         | Exception: references an existing API schema (AutosaveResult) rather than the provisional outputs schema                             | Value validates against the referenced schema; Field is optional and present only for PATCH                                                                                                              |
| outputs.autosave_result.saved                          | Indicator that the single-field change was persisted                                                      | boolean      | schemas/AutosaveResult.schema.json#/properties/saved                                                       | Reuses field defined in AutosaveResult                                                                                               | Value is a boolean; Value reflects persistence status; Field is required when outputs.autosave_result is present                                                                                         |
| outputs.autosave_result.etag                           | Version token representing the current state after the save                                               | string       | schemas/AutosaveResult.schema.json#/properties/etag                                                        | Reuses field defined in AutosaveResult                                                                                               | Value is a non-empty string; Value equals the latest state version token; Field is required when outputs.autosave_result is present                                                                      |
| outputs.autosave_result.visibility_delta               | Object describing which questions changed visibility due to this save                                     | object       | schemas/AutosaveResult.schema.json#/properties/visibility_delta (provisional)                              | **Epic I addition**: to be added as an optional property on AutosaveResult                                                           | Value validates against the schema fragment once added; Field is optional and present only when any visibility changes occur                                                                             |
| outputs.autosave_result.visibility_delta.now_visible[] | Question identifiers that became visible as a result of the change                                        | list[string] | schemas/AutosaveResult.schema.json#/properties/visibility_delta/properties/now_visible/items (provisional) | Elements are `question_id` values                                                                                                    | Array may be empty; Each element is a valid question identifier; Order of elements is not significant                                                                                                    |
| outputs.autosave_result.visibility_delta.now_hidden[]  | Question identifiers that became hidden as a result of the change                                         | list[string] | schemas/AutosaveResult.schema.json#/properties/visibility_delta/properties/now_hidden/items (provisional)  | Elements are `question_id` values                                                                                                    | Array may be empty; Each element is a valid question identifier; Order of elements is not significant                                                                                                    |
| outputs.autosave_result.suppressed_answers[]           | Question identifiers with stored answers that are now ignored because the questions are hidden            | list[string] | schemas/AutosaveResult.schema.json#/properties/suppressed_answers/items (provisional)                      | **Epic I addition**: to be added as an optional property on AutosaveResult                                                           | Array may be empty; Each element is a valid question identifier; Values correspond to questions newly evaluated as hidden in this save; Field is optional and present only when any suppression occurred |

| Error Code                                                | Field Reference                          | Description                                                                                          | Likely Cause                                  | Flow Impact | Behavioural AC Required |
| --------------------------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------- | ----------- | ----------------------- |
| PRE_RESPONSE_SET_ID_MISSING                               | response_set_id                          | Pre-condition failed: response_set_id is required and was not provided                               | Missing value in request path or parameters   | halt_page   | Yes                     |
| PRE_RESPONSE_SET_ID_INVALID_UUID                          | response_set_id                          | Pre-condition failed: response_set_id is not a valid UUID                                            | Malformed identifier format                   | halt_page   | Yes                     |
| PRE_RESPONSE_SET_ID_UNKNOWN                               | response_set_id                          | Pre-condition failed: response_set_id does not correspond to an existing response set                | Identifier not found                          | halt_page   | Yes                     |
| PRE_SCREEN_ID_MISSING                                     | screen_id                                | Pre-condition failed: screen_id is required and was not provided                                     | Missing value in request path or parameters   | halt_page   | Yes                     |
| PRE_SCREEN_ID_SCHEMA_MISMATCH                             | screen_id                                | Pre-condition failed: screen_id does not conform to the declared schema                              | Wrong datatype or pattern                     | halt_page   | Yes                     |
| PRE_SCREEN_ID_UNKNOWN                                     | screen_id                                | Pre-condition failed: screen_id does not correspond to a known screen key                            | Unknown or decommissioned screen key          | halt_page   | Yes                     |
| PRE_QUESTION_ID_MISSING                                   | question_id                              | Pre-condition failed: question_id is required and was not provided                                   | Missing value in request path or parameters   | halt_page   | Yes                     |
| PRE_QUESTION_ID_INVALID_UUID                              | question_id                              | Pre-condition failed: question_id is not a valid UUID                                                | Malformed identifier format                   | halt_page   | Yes                     |
| PRE_QUESTION_ID_UNKNOWN                                   | question_id                              | Pre-condition failed: question_id does not reference an existing question                            | Identifier not found                          | halt_page   | Yes                     |
| PRE_ANSWER_MISSING                                        | answer                                   | Pre-condition failed: answer is required and was not provided                                        | Missing request body                          | halt_page   | Yes                     |
| PRE_ANSWER_INVALID_JSON                                   | answer                                   | Pre-condition failed: answer does not parse as valid JSON                                            | Malformed JSON payload                        | halt_page   | Yes                     |
| PRE_ANSWER_SCHEMA_MISMATCH                                | answer                                   | Pre-condition failed: answer does not conform to schemas/AnswerUpsert.schema.json                    | Payload fields missing or wrong types         | halt_page   | Yes                     |
| PRE_IDEMPOTENCY_KEY_MISSING                               | Idempotency-Key                          | Pre-condition failed: Idempotency-Key is required and was not provided                               | Header absent                                 | halt_page   | Yes                     |
| PRE_IDEMPOTENCY_KEY_EMPTY                                 | Idempotency-Key                          | Pre-condition failed: Idempotency-Key is an empty string                                             | Empty header value                            | halt_page   | Yes                     |
| PRE_IDEMPOTENCY_KEY_NOT_UNIQUE                            | Idempotency-Key                          | Pre-condition failed: Idempotency-Key is not unique for this logical PATCH attempt                   | Reused key for a different payload or context | halt_page   | Yes                     |
| PRE_IF_MATCH_MISSING                                      | If-Match                                 | Pre-condition failed: If-Match is required and was not provided                                      | Header absent                                 | halt_page   | Yes                     |
| PRE_IF_MATCH_STALE                                        | If-Match                                 | Pre-condition failed: If-Match does not match the latest ETag for the response set state             | Client used stale ETag                        | halt_page   | Yes                     |
| PRE_IF_MATCH_EMPTY                                        | If-Match                                 | Pre-condition failed: If-Match is an empty string                                                    | Empty header value                            | halt_page   | Yes                     |
| PRE_QUESTIONNAIREQUESTION_PARENT_QUESTION_ID_NOT_FOUND    | QuestionnaireQuestion.parent_question_id | Pre-condition failed: parent_question_id does not resolve to an existing question_id                 | FK target missing or wrong                    | halt_page   | Yes                     |
| PRE_QUESTIONNAIREQUESTION_PARENT_QUESTION_ID_INVALID_UUID | QuestionnaireQuestion.parent_question_id | Pre-condition failed: parent_question_id is not a valid UUID when present                            | Malformed identifier format                   | halt_page   | Yes                     |
| PRE_QUESTIONNAIREQUESTION_VISIBLE_IF_VALUE_TYPE           | QuestionnaireQuestion.visible_if_value   | Pre-condition failed: visible_if_value is not null, a string, or an array of strings                 | Wrong datatype (e.g., object or number)       | halt_page   | Yes                     |
| PRE_QUESTIONNAIREQUESTION_VISIBLE_IF_VALUE_NONCANONICAL   | QuestionnaireQuestion.visible_if_value   | Pre-condition failed: one or more values are not canonical parent answer values                      | Values do not match allowed tokens            | halt_page   | Yes                     |
| PRE_RESPONSE_OPTION_ID_RESOURCE_UNAVAILABLE               | Response.option_id                       | Pre-condition failed: Response resource is not accessible for option_id                              | Storage or permissions issue                  | halt_page   | Yes                     |
| PRE_RESPONSE_OPTION_ID_INVALID_UUID                       | Response.option_id                       | Pre-condition failed: option_id is not a valid UUID                                                  | Malformed identifier format                   | halt_page   | Yes                     |
| PRE_RESPONSE_OPTION_ID_UNKNOWN                            | Response.option_id                       | Pre-condition failed: option_id does not resolve to an existing AnswerOption for the parent question | FK target missing or mismatched question      | halt_page   | Yes                     |
| PRE_RESPONSE_VALUE_BOOL_RESOURCE_UNAVAILABLE              | Response.value_bool                      | Pre-condition failed: Response resource is not accessible for value_bool                             | Storage or permissions issue                  | halt_page   | Yes                     |
| PRE_RESPONSE_VALUE_BOOL_SCHEMA_MISMATCH                   | Response.value_bool                      | Pre-condition failed: stored value_bool does not conform to the referenced schema                    | Wrong datatype or nullability                 | halt_page   | Yes                     |
| PRE_RESPONSE_VALUE_BOOL_NOT_BOOLEAN                       | Response.value_bool                      | Pre-condition failed: value_bool is not true or false when present                                   | Non-boolean stored value                      | halt_page   | Yes                     |
| PRE_RESPONSE_VALUE_NUMBER_RESOURCE_UNAVAILABLE            | Response.value_number                    | Pre-condition failed: Response resource is not accessible for value_number                           | Storage or permissions issue                  | halt_page   | Yes                     |
| PRE_RESPONSE_VALUE_NUMBER_SCHEMA_MISMATCH                 | Response.value_number                    | Pre-condition failed: stored value_number does not conform to the referenced schema                  | Wrong datatype or nullability                 | halt_page   | Yes                     |
| PRE_RESPONSE_VALUE_NUMBER_NOT_FINITE                      | Response.value_number                    | Pre-condition failed: value_number is not a finite number when present                               | NaN, Infinity, or non-numeric                 | halt_page   | Yes                     |
| PRE_RESPONSE_VALUE_TEXT_RESOURCE_UNAVAILABLE              | Response.value_text                      | Pre-condition failed: Response resource is not accessible for value_text                             | Storage or permissions issue                  | halt_page   | Yes                     |
| PRE_RESPONSE_VALUE_TEXT_SCHEMA_MISMATCH                   | Response.value_text                      | Pre-condition failed: stored value_text does not conform to the referenced schema                    | Wrong datatype or nullability                 | halt_page   | Yes                     |
| PRE_RESPONSE_VALUE_TEXT_NOT_STRING                        | Response.value_text                      | Pre-condition failed: value_text is not a string when present                                        | Non-string stored value                       | halt_page   | Yes                     |
| PRE_ANSWEROPTION_VALUE_RESOURCE_UNAVAILABLE               | AnswerOption.value                       | Pre-condition failed: AnswerOption resource is not accessible for value                              | Storage or permissions issue                  | halt_page   | Yes                     |
| PRE_ANSWEROPTION_VALUE_SCHEMA_MISMATCH                    | AnswerOption.value                       | Pre-condition failed: AnswerOption document does not conform to the referenced schema                | Missing or wrong field type                   | halt_page   | Yes                     |
| PRE_ANSWEROPTION_VALUE_MISSING                            | AnswerOption.value                       | Pre-condition failed: value is not present for an option                                             | Missing canonical value token                 | halt_page   | Yes                     |

| Error Code                               | Output Field Ref                                       | Description                                                                                | Likely Cause                                        | Flow Impact        | Behavioural AC Required |
| ---------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------ | --------------------------------------------------- | ------------------ | ----------------------- |
| POST_OUTPUTS_SCHEMA_INVALID              | outputs                                                | outputs does not validate against the declared schema                                      | Schema mismatch in container structure              | block_finalization | Yes                     |
| POST_OUTPUTS_KEYS_NOT_DETERMINISTIC      | outputs                                                | outputs key set is not deterministic for identical inputs                                  | Non-deterministic inclusion or ordering             | block_finalization | Yes                     |
| POST_SCREEN_VIEW_SCHEMA_INVALID          | outputs.screen_view                                    | outputs.screen_view does not validate against the ScreenView schema                        | Structure or types deviate from ScreenView contract | block_finalization | Yes                     |
| POST_SCREEN_VIEW_CONTAINS_HIDDEN         | outputs.screen_view                                    | outputs.screen_view contains questions that are not currently visible                      | Visibility evaluation or filtering error            | block_finalization | Yes                     |
| POST_AUTOSAVE_RESULT_SCHEMA_INVALID      | outputs.autosave_result                                | outputs.autosave_result does not validate against the AutosaveResult schema                | Structure or field types deviate from contract      | block_finalization | Yes                     |
| POST_SAVED_MISSING                       | outputs.autosave_result.saved                          | outputs.autosave_result.saved is missing when autosave_result is present                   | Required field omitted from response body           | block_finalization | Yes                     |
| POST_SAVED_NOT_BOOLEAN                   | outputs.autosave_result.saved                          | outputs.autosave_result.saved is not a boolean                                             | Serialization or typing error                       | block_finalization | Yes                     |
| POST_ETAG_MISSING                        | outputs.autosave_result.etag                           | outputs.autosave_result.etag is missing when autosave_result is present                    | Required field omitted from response body           | block_finalization | Yes                     |
| POST_ETAG_EMPTY                          | outputs.autosave_result.etag                           | outputs.autosave_result.etag is an empty string                                            | ETag not generated or cleared incorrectly           | block_finalization | Yes                     |
| POST_ETAG_NOT_LATEST                     | outputs.autosave_result.etag                           | outputs.autosave_result.etag does not equal the latest state version token                 | Stale or mismatched version token emitted           | block_finalization | Yes                     |
| POST_VISIBILITY_DELTA_SCHEMA_INVALID     | outputs.autosave_result.visibility_delta               | outputs.autosave_result.visibility_delta does not validate against the declared schema     | Invalid delta object structure                      | block_finalization | Yes                     |
| POST_VISIBILITY_DELTA_MISSING            | outputs.autosave_result.visibility_delta               | outputs.autosave_result.visibility_delta is missing when autosave_result is present        | Delta object omitted from response body             | block_finalization | Yes                     |
| POST_NOW_VISIBLE_INVALID_ID              | outputs.autosave_result.visibility_delta.now_visible[] | now_visible contains an element that is not a valid question identifier                    | Invalid identifier format or unknown ID             | block_finalization | Yes                     |
| POST_NOW_HIDDEN_INVALID_ID               | outputs.autosave_result.visibility_delta.now_hidden[]  | now_hidden contains an element that is not a valid question identifier                     | Invalid identifier format or unknown ID             | block_finalization | Yes                     |
| POST_SUPPRESSED_ANSWERS_INVALID_ID       | outputs.autosave_result.suppressed_answers[]           | suppressed_answers contains an element that is not a valid question identifier             | Invalid identifier format or unknown ID             | block_finalization | Yes                     |
| POST_SUPPRESSED_ANSWERS_NOT_NEWLY_HIDDEN | outputs.autosave_result.suppressed_answers[]           | suppressed_answers includes a question that was not newly evaluated as hidden in this save | Incorrect suppression set derivation                | block_finalization | Yes                     |

| Error Code                            | Description                                                                      | Likely Cause                                                           | Source (Step in Section 2.x)                                                             | Step ID (from Section 2.2.6) | Reachability Rationale                                                                     | Flow Impact                                  | Behavioural AC Required |
| ------------------------------------- | -------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ---------------------------- | ------------------------------------------------------------------------------------------ | -------------------------------------------- | ----------------------- |
| RUN_LOAD_SCREEN_DATA_FAILED           | Loading questions and current answers for the requested screen failed at runtime | Data store read error or timeout                                       | 2.2 – Load questions and answers                                                         | STEP-GET-1                   | E1 requires the system to load all questions and current answers; a runtime fetch can fail | halt_page                                    | Yes                     |
| RUN_COMPUTE_VISIBILITY_FAILED         | Computing visibility for questions on the screen failed                          | Null reference, type cast, or rule evaluation exception                | 2.2 – Compute visibility and return visible questions                                    | STEP-GET-2                   | U1/U2/E2 require server-side visibility computation; internal evaluation may throw         | halt_page                                    | Yes                     |
| RUN_RETURN_VISIBLE_SET_BUILD_FAILED   | Building the visible-only screen projection failed                               | Projection/selection error or data shaping exception                   | 2.2 – Compute visibility and return visible questions                                    | STEP-GET-2                   | U3/E2 require returning only visible questions; assembling the projection can fail         | halt_page                                    | Yes                     |
| RUN_PERSIST_ANSWER_FAILED             | Persisting the single-field answer change failed                                 | Transaction failure or write conflict outside pre-condition checks     | 2.2 – Persist answer change                                                              | STEP-PATCH-1                 | E3 requires persisting the new value; the write can fail at runtime                        | block_finalization                           | Yes                     |
| RUN_REEVALUATE_DESCENDANTS_FAILED     | Re-evaluating visibility for descendant questions failed                         | Graph traversal error or stack/queue processing exception              | 2.2 – Re-evaluate descendant visibility                                                  | STEP-PATCH-2                 | E4 mandates subtree re-evaluation; traversal or evaluation may fail                        | block_finalization                           | Yes                     |
| RUN_BUILD_VISIBILITY_DELTA_FAILED     | Constructing the visibility_delta object failed                                  | Set-diff or collection build error                                     | 2.2 – Return visibility_delta (now-visible and now-hidden)                               | STEP-PATCH-3                 | E5 requires returning a delta; building the two lists may fail                             | block_finalization                           | Yes                     |
| RUN_SUPPRESSION_SET_BUILD_FAILED      | Building the suppressed_answers list failed                                      | Lookup of newly hidden questions with stored answers failed            | 2.2 – Return suppressed answers                                                          | STEP-PATCH-4                 | U4/E6 require listing suppressed_answers; deriving that list can fail                      | block_finalization                           | Yes                     |
| RUN_ETAG_COMPUTE_FAILED               | Computing the updated ETag after save failed                                     | Version hashing or state versioning routine threw                      | 2.2 – Return updated etag                                                                | STEP-PATCH-5                 | E7 requires including an updated etag; version computation may fail                        | block_finalization                           | Yes                     |
| RUN_CANONICAL_VALUE_RESOLUTION_FAILED | Resolving a parent’s canonical value for comparison failed                       | Missing option resolution for enum_single or inconsistent stored value | 2.2 – Compute visibility and return visible questions; Re-evaluate descendant visibility | STEP-GET-2 / STEP-PATCH-2    | O1/O2/O3 and S2/S3 require canonical value comparison; resolving that value can fail       | halt_page (GET) / block_finalization (PATCH) | Yes                     |
| RUN_RESPONSE_SERIALIZATION_FAILED     | Serializing the response body for the selected operation failed                  | JSON serialization error due to unexpected value                       | 2.2 – Compute visibility and return visible questions; Return autosave response          | STEP-GET-2 / STEP-PATCH-3–5  | Both GET and PATCH must emit structured responses; serialization may fail                  | block_finalization                           | Yes                     |

| Error Code                             | Description                                                                                                | Likely Cause                                 | Impacted Steps           | EARS Refs  | Flow Impact        | Behavioural AC Required |
| -------------------------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------- | ------------------------ | ---------- | ------------------ | ----------------------- |
| ENV_DATABASE_UNAVAILABLE_LOAD          | Data store is unavailable when loading questions and answers for a screen                                  | Database cluster offline or node down        | STEP-GET-1               | E1         | halt_page          | Yes                     |
| ENV_DATABASE_UNAVAILABLE_COMPUTE       | Data store is unavailable during visibility computation that requires reads (e.g., parent values, options) | Database outage mid-request                  | STEP-GET-2               | U1, U2, E2 | halt_page          | Yes                     |
| ENV_DATABASE_UNAVAILABLE_PERSIST       | Data store is unavailable when persisting an autosave                                                      | Database outage or failover                  | STEP-PATCH-1             | E3         | block_finalization | Yes                     |
| ENV_DATABASE_UNAVAILABLE_REEVAL        | Data store is unavailable during subtree re-evaluation reads                                               | Database outage mid-evaluation               | STEP-PATCH-2             | U1, U2, E4 | block_finalization | Yes                     |
| ENV_DATABASE_PERMISSION_DENIED_LOAD    | Data store denies access while loading screen data                                                         | Missing role/grant for read                  | STEP-GET-1               | E1         | halt_page          | Yes                     |
| ENV_DATABASE_PERMISSION_DENIED_PERSIST | Data store denies access while saving an answer                                                            | Missing role/grant for write                 | STEP-PATCH-1             | E3         | block_finalization | Yes                     |
| ENV_NETWORK_UNREACHABLE_DB_LOAD        | Network to the data store is unreachable during screen load                                                | Network partition or VPC route issue         | STEP-GET-1               | E1         | halt_page          | Yes                     |
| ENV_NETWORK_UNREACHABLE_DB_PERSIST     | Network to the data store is unreachable during autosave                                                   | Network partition or security group block    | STEP-PATCH-1             | E3         | block_finalization | Yes                     |
| ENV_DNS_RESOLUTION_FAILED_DB           | DNS resolution for the data store endpoint fails                                                           | Misconfigured DNS or host not published      | STEP-GET-1, STEP-PATCH-1 | E1, E3     | halt_page          | Yes                     |
| ENV_TLS_HANDSHAKE_FAILED_DB            | TLS handshake to the data store fails                                                                      | Invalid certificate or protocol mismatch     | STEP-GET-1, STEP-PATCH-1 | E1, E3     | halt_page          | Yes                     |
| ENV_RUNTIME_CONFIG_MISSING_DB_URI      | Required runtime configuration for data store connection is missing                                        | Absent connection string or credentials      | STEP-GET-1, STEP-PATCH-1 | E1, E3     | halt_page          | Yes                     |
| ENV_SECRET_INVALID_DB_CREDENTIALS      | Stored credentials for the data store are invalid                                                          | Expired password or rotated key not deployed | STEP-GET-1, STEP-PATCH-1 | E1, E3     | halt_page          | Yes                     |

### 6.1 Architectural Acceptance Criteria

**6.1.1 Visibility evaluation fields must exist**
The codebase must define `parent_question_id` and `visible_if_value` as properties of `QuestionnaireQuestion`, with types and nullability as described.
*Reference: U1, STEP-GET-2, STEP-PATCH-2*

**6.1.2 Canonical value fields must exist**
The codebase must include canonical value fields on `Response` (`option_id`, `value_bool`, `value_number`, `value_text`) and on `AnswerOption` (`value`), to enable equality comparison during visibility checks.
*Reference: U2, O1, O2, O3, STEP-GET-2, STEP-PATCH-2*

**6.1.3 Screen responses must exclude hidden questions**
The implementation of the `ScreenView` schema must ensure that hidden questions are not returned in the GET `/screens/{screen_id}` response.
*Reference: U3, S1, S2, S3, STEP-GET-2, outputs.screen_view*

**6.1.4 Suppressed answers must be structurally represented**
The `AutosaveResult` schema must define a `suppressed_answers[]` property that lists identifiers of hidden-but-answered questions.
*Reference: U4, E6, STEP-PATCH-4, outputs.autosave_result.suppressed_answers[]*

**6.1.5 Visibility deltas must be structurally represented**
The `AutosaveResult` schema must define a `visibility_delta` object containing `now_visible[]` and `now_hidden[]`.
*Reference: E5, STEP-PATCH-3, outputs.autosave_result.visibility_delta*

**6.1.6 Deterministic key sets must be enforced**
The `outputs` container must always return a deterministic key set for identical inputs, ensuring stable schema validation.
*Reference: U5, outputs*

**6.1.7 Concurrency control fields must be present**
The `AutosaveResult` schema must include an `etag` property, and PATCH requests must accept an `If-Match` header, both required for optimistic concurrency.
*Reference: E7, STEP-PATCH-5, outputs.autosave_result.etag*

**6.1.8 Idempotency key must be enforced at entrypoint**
The PATCH endpoint must require and process the `Idempotency-Key` header, as declared in the OpenAPI parameter.
*Reference: Inputs.Idempotency-Key, N1–N3 error handling*

**6.1.9 Error handling must be schema-based**
The implementation must structurally reject invalid requests with HTTP error codes (`422`, `409`, `404`) and problem+json bodies, aligned to the defined PRE_* error modes.
*Reference: N1, N2, N3, STEP-ERROR-1 to STEP-ERROR-3*

### 6.2.1 Happy Path Contractual Acceptance Criteria

**6.2.1.1 Parent-based visibility evaluation**
Given a questionnaire with parent and child questions, when the parent’s canonical value matches the child’s `visible_if_value`, then the child question must be included in the visible screen output.
*Reference: U1, S2, outputs.screen_view*

**6.2.1.2 Canonical value normalisation**
Given a stored parent answer, when visibility is evaluated, then the parent’s answer must be normalised to its canonical value before comparison.
*Reference: U2, O1, O2, O3, outputs.screen_view*

**6.2.1.3 Exclusion of hidden questions**
Given a GET screen request, when hidden questions exist, then they must be omitted from the `outputs.screen_view`.
*Reference: U3, S1, S3, outputs.screen_view*

**6.2.1.4 Retention of suppressed answers**
Given a PATCH request hides a question with an existing answer, when suppression occurs, then the `outputs.autosave_result.suppressed_answers[]` must list that question’s identifier.
*Reference: U4, E6, outputs.autosave_result.suppressed_answers[]*

**6.2.1.5 Deterministic outputs**
Given identical inputs, when screen evaluation completes, then the `outputs` object must return the same deterministic set of keys.
*Reference: U5, outputs*

**6.2.1.6 Screen data retrieval**
Given a GET screen request, when executed, then the system must return both questions and current answers within `outputs.screen_view`.
*Reference: E1, outputs.screen_view*

**6.2.1.7 Server-side visibility filtering**
Given a GET screen request, when executed, then the system must compute and apply visibility rules before returning `outputs.screen_view`.
*Reference: E2, outputs.screen_view*

**6.2.1.8 Answer persistence**
Given a PATCH request with a valid answer, when processed, then the system must persist the new value and reflect it in `outputs.autosave_result.saved`.
*Reference: E3, outputs.autosave_result.saved*

**6.2.1.9 Subtree re-evaluation**
Given a PATCH request changes a parent answer, when visibility is recomputed, then all descendant questions must be re-evaluated for visibility.
*Reference: E4, outputs.autosave_result.visibility_delta*

**6.2.1.10 Visibility delta reporting**
Given a PATCH request changes visibility, when the response is returned, then `outputs.autosave_result.visibility_delta` must contain lists of now-visible and now-hidden question IDs.
*Reference: E5, outputs.autosave_result.visibility_delta.now_visible[], outputs.autosave_result.visibility_delta.now_hidden[]*

**6.2.1.11 Suppression identifiers**
Given a PATCH request hides answered questions, when the response is returned, then `outputs.autosave_result.suppressed_answers[]` must identify those questions.
*Reference: E6, outputs.autosave_result.suppressed_answers[]*

**6.2.1.12 Updated etag return**
Given a PATCH request completes, when the response is returned, then `outputs.autosave_result.etag` must contain the latest state version token.
*Reference: E7, outputs.autosave_result.etag*

**6.2.1.13 Enum_single value comparison**
Given a parent question of type `enum_single`, when visibility is computed, then the comparison must use the canonical `AnswerOption.value`.
*Reference: O1, outputs.screen_view*

**6.2.1.14 Boolean and number comparison**
Given a parent answer of type boolean or number, when visibility is computed, then the value must be normalised before comparison.
*Reference: O2, outputs.screen_view*

**6.2.1.15 Text value comparison**
Given a parent answer of type short_string or long_text, when visibility is computed, then the system must compare trimmed, case-sensitive strings.
*Reference: O3, outputs.screen_view*

### 6.2.2 Sad Path Contractual Acceptance Criteria

**6.2.2.1 Response set ID missing**
Given a GET or PATCH request without `response_set_id`, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_RESPONSE_SET_ID_MISSING
*Reference:* response_set_id

**6.2.2.2 Response set ID invalid format**
Given a request with `response_set_id` that is not a valid UUID, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_RESPONSE_SET_ID_INVALID_UUID
*Reference:* response_set_id

**6.2.2.3 Response set ID unknown**
Given a request with `response_set_id` that does not correspond to an existing response set, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_RESPONSE_SET_ID_UNKNOWN
*Reference:* response_set_id

**6.2.2.4 Screen ID missing**
Given a GET request without `screen_id`, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_SCREEN_ID_MISSING
*Reference:* screen_id

**6.2.2.5 Screen ID schema mismatch**
Given a GET request where `screen_id` does not conform to its schema, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_SCREEN_ID_SCHEMA_MISMATCH
*Reference:* screen_id

**6.2.2.6 Screen ID unknown**
Given a GET request with `screen_id` not matching any known screen, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_SCREEN_ID_UNKNOWN
*Reference:* screen_id

**6.2.2.7 Question ID missing**
Given a PATCH request without `question_id`, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_QUESTION_ID_MISSING
*Reference:* question_id

**6.2.2.8 Question ID invalid format**
Given a PATCH request with `question_id` that is not a valid UUID, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_QUESTION_ID_INVALID_UUID
*Reference:* question_id

**6.2.2.9 Question ID unknown**
Given a PATCH request with `question_id` not referencing an existing question, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_QUESTION_ID_UNKNOWN
*Reference:* question_id

**6.2.2.10 Answer body missing**
Given a PATCH request without an `answer` body, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_ANSWER_MISSING
*Reference:* answer

**6.2.2.11 Answer body invalid JSON**
Given a PATCH request where the `answer` body is not valid JSON, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_ANSWER_INVALID_JSON
*Reference:* answer

**6.2.2.12 Answer body schema mismatch**
Given a PATCH request where the `answer` body does not conform to `AnswerUpsert.schema.json`, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_ANSWER_SCHEMA_MISMATCH
*Reference:* answer

**6.2.2.13 Idempotency key missing**
Given a PATCH request without `Idempotency-Key`, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_IDEMPOTENCY_KEY_MISSING
*Reference:* Idempotency-Key

**6.2.2.14 Idempotency key empty**
Given a PATCH request with `Idempotency-Key` that is empty, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_IDEMPOTENCY_KEY_EMPTY
*Reference:* Idempotency-Key

**6.2.2.15 Idempotency key not unique**
Given a PATCH request with `Idempotency-Key` reused across different payloads, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_IDEMPOTENCY_KEY_NOT_UNIQUE
*Reference:* Idempotency-Key

**6.2.2.16 If-Match header missing**
Given a PATCH request without `If-Match`, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_IF_MATCH_MISSING
*Reference:* If-Match

**6.2.2.17 If-Match header empty**
Given a PATCH request with `If-Match` that is empty, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_IF_MATCH_EMPTY
*Reference:* If-Match

**6.2.2.18 If-Match header stale**
Given a PATCH request with `If-Match` that does not match the latest ETag, when the request is processed, then the system must reject it with an error.
*Error Mode:* PRE_IF_MATCH_STALE
*Reference:* If-Match

**6.2.2.19 Parent question ID invalid**
Given a stored `parent_question_id` that is not a valid UUID, when visibility is evaluated, then the system must reject it with an error.
*Error Mode:* PRE_QUESTIONNAIREQUESTION_PARENT_QUESTION_ID_INVALID_UUID
*Reference:* QuestionnaireQuestion.parent_question_id

**6.2.2.20 Parent question ID not found**
Given a stored `parent_question_id` referencing a non-existent question, when visibility is evaluated, then the system must reject it with an error.
*Error Mode:* PRE_QUESTIONNAIREQUESTION_PARENT_QUESTION_ID_NOT_FOUND
*Reference:* QuestionnaireQuestion.parent_question_id

**6.2.2.21 Visible-if value type invalid**
Given a stored `visible_if_value` that is not null, a string, or an array of strings, when visibility is evaluated, then the system must reject it with an error.
*Error Mode:* PRE_QUESTIONNAIREQUESTION_VISIBLE_IF_VALUE_TYPE
*Reference:* QuestionnaireQuestion.visible_if_value

**6.2.2.22 Visible-if value not canonical**
Given a stored `visible_if_value` containing non-canonical values, when visibility is evaluated, then the system must reject it with an error.
*Error Mode:* PRE_QUESTIONNAIREQUESTION_VISIBLE_IF_VALUE_NONCANONICAL
*Reference:* QuestionnaireQuestion.visible_if_value

**6.2.2.23 Response option ID invalid format**
Given a stored `option_id` that is not a valid UUID, when visibility is evaluated, then the system must reject it with an error.
*Error Mode:* PRE_RESPONSE_OPTION_ID_INVALID_UUID
*Reference:* Response.option_id

**6.2.2.24 Response option ID unknown**
Given a stored `option_id` not resolving to an existing AnswerOption, when visibility is evaluated, then the system must reject it with an error.
*Error Mode:* PRE_RESPONSE_OPTION_ID_UNKNOWN
*Reference:* Response.option_id

**6.2.2.25 Response value bool not boolean**
Given a stored `value_bool` that is not true or false, when visibility is evaluated, then the system must reject it with an error.
*Error Mode:* PRE_RESPONSE_VALUE_BOOL_NOT_BOOLEAN
*Reference:* Response.value_bool

**6.2.2.26 Response value number not finite**
Given a stored `value_number` that is not finite, when visibility is evaluated, then the system must reject it with an error.
*Error Mode:* PRE_RESPONSE_VALUE_NUMBER_NOT_FINITE
*Reference:* Response.value_number

**6.2.2.27 Response value text not string**
Given a stored `value_text` that is not a string, when visibility is evaluated, then the system must reject it with an error.
*Error Mode:* PRE_RESPONSE_VALUE_TEXT_NOT_STRING
*Reference:* Response.value_text

**6.2.2.28 AnswerOption value missing**
Given an `AnswerOption` without a canonical `value`, when visibility is evaluated, then the system must reject it with an error.
*Error Mode:* PRE_ANSWEROPTION_VALUE_MISSING
*Reference:* AnswerOption.value

**6.2.2.29 Outputs schema invalid**
Given processing completes, when the system builds `outputs`, then it must reject the result if the object does not validate against its schema.
*Error Mode:* POST_OUTPUTS_SCHEMA_INVALID
*Reference:* outputs

**6.2.2.30 Outputs keys not deterministic**
Given identical inputs, when `outputs` are built, then the system must reject the result if its keys differ across runs.
*Error Mode:* POST_OUTPUTS_KEYS_NOT_DETERMINISTIC
*Reference:* outputs

**6.2.2.31 ScreenView schema invalid**
Given a GET request, when `outputs.screen_view` is built, then the system must reject the result if it does not validate against `ScreenView`.
*Error Mode:* POST_SCREEN_VIEW_SCHEMA_INVALID
*Reference:* outputs.screen_view

**6.2.2.32 ScreenView contains hidden questions**
Given a GET request, when `outputs.screen_view` includes hidden questions, then the system must reject the result.
*Error Mode:* POST_SCREEN_VIEW_CONTAINS_HIDDEN
*Reference:* outputs.screen_view

**6.2.2.33 AutosaveResult schema invalid**
Given a PATCH request, when `outputs.autosave_result` is built, then the system must reject the result if it does not validate against its schema.
*Error Mode:* POST_AUTOSAVE_RESULT_SCHEMA_INVALID
*Reference:* outputs.autosave_result

**6.2.2.34 Saved missing**
Given a PATCH request, when `outputs.autosave_result.saved` is missing, then the system must reject the result.
*Error Mode:* POST_SAVED_MISSING
*Reference:* outputs.autosave_result.saved

**6.2.2.35 Saved not boolean**
Given a PATCH request, when `outputs.autosave_result.saved` is not boolean, then the system must reject the result.
*Error Mode:* POST_SAVED_NOT_BOOLEAN
*Reference:* outputs.autosave_result.saved

**6.2.2.36 ETag missing**
Given a PATCH request, when `outputs.autosave_result.etag` is missing, then the system must reject the result.
*Error Mode:* POST_ETAG_MISSING
*Reference:* outputs.autosave_result.etag

**6.2.2.37 ETag empty**
Given a PATCH request, when `outputs.autosave_result.etag` is empty, then the system must reject the result.
*Error Mode:* POST_ETAG_EMPTY
*Reference:* outputs.autosave_result.etag

**6.2.2.38 ETag not latest**
Given a PATCH request, when `outputs.autosave_result.etag` does not equal the latest version, then the system must reject the result.
*Error Mode:* POST_ETAG_NOT_LATEST
*Reference:* outputs.autosave_result.etag

**6.2.2.39 Visibility delta schema invalid**
Given a PATCH request, when `outputs.autosave_result.visibility_delta` does not validate against its schema, then the system must reject the result.
*Error Mode:* POST_VISIBILITY_DELTA_SCHEMA_INVALID
*Reference:* outputs.autosave_result.visibility_delta

**6.2.2.40 Visibility delta missing**
Given a PATCH request with visibility changes, when `outputs.autosave_result.visibility_delta` is missing, then the system must reject the result.
*Error Mode:* POST_VISIBILITY_DELTA_MISSING
*Reference:* outputs.autosave_result.visibility_delta

**6.2.2.41 Now-visible contains invalid ID**
Given a PATCH request with `now_visible[]`, when the list contains an invalid identifier, then the system must reject the result.
*Error Mode:* POST_NOW_VISIBLE_INVALID_ID
*Reference:* outputs.autosave_result.visibility_delta.now_visible[]

**6.2.2.42 Now-hidden contains invalid ID**
Given a PATCH request with `now_hidden[]`, when the list contains an invalid identifier, then the system must reject the result.
*Error Mode:* POST_NOW_HIDDEN_INVALID_ID
*Reference:* outputs.autosave_result.visibility_delta.now_hidden[]

**6.2.2.43 Suppressed answers invalid ID**
Given a PATCH request with `suppressed_answers[]`, when the list contains an invalid identifier, then the system must reject the result.
*Error Mode:* POST_SUPPRESSED_ANSWERS_INVALID_ID
*Reference:* outputs.autosave_result.suppressed_answers[]

**6.2.2.44 Suppressed answers not newly hidden**
Given a PATCH request with `suppressed_answers[]`, when the list contains questions not newly hidden in this save, then the system must reject the result.
*Error Mode:* POST_SUPPRESSED_ANSWERS_NOT_NEWLY_HIDDEN
*Reference:* outputs.autosave_result.suppressed_answers[]

### 6.3.1.1 Screen request starts data load

**Criterion:**
Given a GET `/response-sets/{response_set_id}/screens/{screen_id}` request is received,
When the request is accepted,
Then the system must initiate loading of questions and current answers for the target screen.
**Reference:** E1, STEP-GET-1

### 6.3.1.2 Data load triggers visibility computation

**Criterion:**
Given screen questions and answers have been loaded,
When STEP-GET-1 completes successfully,
Then the system must proceed to compute visibility for each question on the screen.
**Reference:** E2, STEP-GET-2

### 6.3.1.3 PATCH request starts answer persistence

**Criterion:**
Given a PATCH `/response-sets/{response_set_id}/answers/{question_id}` request is received,
When the request is accepted,
Then the system must initiate persistence of the single-field answer change.
**Reference:** E3, STEP-PATCH-1

### 6.3.1.4 Persistence triggers descendant re-evaluation

**Criterion:**
Given the answer change has been persisted,
When STEP-PATCH-1 completes successfully,
Then the system must trigger re-evaluation of visibility for all descendants of the changed question.
**Reference:** E4, STEP-PATCH-2

### 6.3.1.5 Re-evaluation triggers delta build

**Criterion:**
Given descendant visibility has been re-evaluated,
When STEP-PATCH-2 completes successfully,
Then the system must proceed to build the visibility delta (now-visible and now-hidden lists).
**Reference:** E5, STEP-PATCH-3

### 6.3.1.6 Delta build triggers suppression set derivation

**Criterion:**
Given the visibility delta has been built,
When STEP-PATCH-3 completes successfully,
Then the system must proceed to derive the list of suppressed answers for questions that just became hidden.
**Reference:** U4, E6, STEP-PATCH-4

### 6.3.1.7 Suppression set derivation triggers ETag update

**Criterion:**
Given the suppression list has been derived,
When STEP-PATCH-4 completes successfully,
Then the system must proceed to compute the updated ETag for the response.
**Reference:** E7, STEP-PATCH-5

### 6.3.1.8 Unanswered parent enforces hidden branch

**Criterion:**
Given a parent question is unanswered,
While this state persists,
Then the system must keep all of that parent’s children on the hidden branch of the visibility pipeline.
**Reference:** S1, STEP-GET-2

### 6.3.1.9 Matching canonical value routes child to visible branch

**Criterion:**
Given a parent’s canonical value equals a child’s `visible_if_value`,
While this state persists,
Then the system must route that child through the visible branch of the visibility pipeline.
**Reference:** S2, STEP-GET-2, STEP-PATCH-2

### 6.3.1.10 Non-matching canonical value routes child to hidden branch

**Criterion:**
Given a parent’s canonical value differs from a child’s `visible_if_value`,
While this state persists,
Then the system must route that child through the hidden branch of the visibility pipeline.
**Reference:** S3, STEP-GET-2, STEP-PATCH-2

#### 6.3.2.1

**Title:** Halt GET flow when loading screen data fails
**Criterion:** Given the system is executing STEP-GET-1, when `RUN_LOAD_SCREEN_DATA_FAILED` occurs, then halt STEP-GET-1 and stop propagation to STEP-GET-2, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_LOAD_SCREEN_DATA_FAILED
**Reference:** (step: STEP-GET-1 → STEP-GET-2)

#### 6.3.2.2

**Title:** Halt GET visibility computation on evaluation failure
**Criterion:** Given the system is executing STEP-GET-2, when `RUN_COMPUTE_VISIBILITY_FAILED` occurs, then halt STEP-GET-2 and stop propagation to response dispatch, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_COMPUTE_VISIBILITY_FAILED
**Reference:** (step: STEP-GET-2)

#### 6.3.2.3

**Title:** Halt GET projection build on visible-set construction failure
**Criterion:** Given the system is executing STEP-GET-2, when `RUN_RETURN_VISIBLE_SET_BUILD_FAILED` occurs, then halt STEP-GET-2 and stop propagation to response dispatch, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_RETURN_VISIBLE_SET_BUILD_FAILED
**Reference:** (step: STEP-GET-2)

#### 6.3.2.4

**Title:** Block PATCH subtree re-evaluation when persistence fails
**Criterion:** Given the system is executing STEP-PATCH-1, when `RUN_PERSIST_ANSWER_FAILED` occurs, then halt STEP-PATCH-1 and stop propagation to STEP-PATCH-2, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_PERSIST_ANSWER_FAILED
**Reference:** (step: STEP-PATCH-1 → STEP-PATCH-2)

#### 6.3.2.5

**Title:** Block delta build when descendant re-evaluation fails
**Criterion:** Given the system is executing STEP-PATCH-2, when `RUN_REEVALUATE_DESCENDANTS_FAILED` occurs, then halt STEP-PATCH-2 and stop propagation to STEP-PATCH-3, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_REEVALUATE_DESCENDANTS_FAILED
**Reference:** (step: STEP-PATCH-2 → STEP-PATCH-3)

#### 6.3.2.6

**Title:** Block suppression derivation when delta build fails
**Criterion:** Given the system is executing STEP-PATCH-3, when `RUN_BUILD_VISIBILITY_DELTA_FAILED` occurs, then halt STEP-PATCH-3 and stop propagation to STEP-PATCH-4, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_BUILD_VISIBILITY_DELTA_FAILED
**Reference:** (step: STEP-PATCH-3 → STEP-PATCH-4)

#### 6.3.2.7

**Title:** Block ETag update when suppression derivation fails
**Criterion:** Given the system is executing STEP-PATCH-4, when `RUN_SUPPRESSION_SET_BUILD_FAILED` occurs, then halt STEP-PATCH-4 and stop propagation to STEP-PATCH-5, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_SUPPRESSION_SET_BUILD_FAILED
**Reference:** (step: STEP-PATCH-4 → STEP-PATCH-5)

#### 6.3.2.8

**Title:** Halt finalisation when ETag computation fails
**Criterion:** Given the system is executing STEP-PATCH-5, when `RUN_ETAG_COMPUTE_FAILED` occurs, then halt STEP-PATCH-5 and stop propagation to response dispatch, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_ETAG_COMPUTE_FAILED
**Reference:** (step: STEP-PATCH-5)

#### 6.3.2.9

**Title:** Halt GET flow when canonical value resolution fails
**Criterion:** Given the system is executing STEP-GET-2, when `RUN_CANONICAL_VALUE_RESOLUTION_FAILED` occurs, then halt STEP-GET-2 and stop propagation to response dispatch, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_CANONICAL_VALUE_RESOLUTION_FAILED
**Reference:** (step: STEP-GET-2)

#### 6.3.2.10

**Title:** Block PATCH flow when canonical value resolution fails
**Criterion:** Given the system is executing STEP-PATCH-2, when `RUN_CANONICAL_VALUE_RESOLUTION_FAILED` occurs, then halt STEP-PATCH-2 and stop propagation to STEP-PATCH-3, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_CANONICAL_VALUE_RESOLUTION_FAILED
**Reference:** (step: STEP-PATCH-2 → STEP-PATCH-3)

#### 6.3.2.11

**Title:** Block finalisation when response serialization fails (GET)
**Criterion:** Given the system has completed STEP-GET-2 and is serializing the response, when `RUN_RESPONSE_SERIALIZATION_FAILED` occurs, then halt serialization and stop propagation to response dispatch, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_RESPONSE_SERIALIZATION_FAILED
**Reference:** (step: STEP-GET-2 → response dispatch)

#### 6.3.2.12

**Title:** Block finalisation when response serialization fails (PATCH)
**Criterion:** Given the system has completed STEP-PATCH-3–STEP-PATCH-5 and is serializing the response, when `RUN_RESPONSE_SERIALIZATION_FAILED` occurs, then halt serialization and stop propagation to response dispatch, as required by the error mode’s Flow Impact.
**Error Mode:** RUN_RESPONSE_SERIALIZATION_FAILED
**Reference:** (step: STEP-PATCH-3/4/5 → response dispatch)

#### 6.3.2.13

**Title:** Halt GET load when database is unavailable
**Criterion:** Given the system is executing STEP-GET-1 with a database dependency, when ENV_DATABASE_UNAVAILABLE_LOAD occurs, then halt STEP-GET-1 and stop propagation to STEP-GET-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DATABASE_UNAVAILABLE_LOAD
**Reference:** database (steps: STEP-GET-1 → STEP-GET-2)

#### 6.3.2.14

**Title:** Halt GET visibility compute when database becomes unavailable
**Criterion:** Given the system is executing STEP-GET-2 and requires database reads, when ENV_DATABASE_UNAVAILABLE_COMPUTE occurs, then halt STEP-GET-2 and stop propagation to response dispatch, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DATABASE_UNAVAILABLE_COMPUTE
**Reference:** database (step: STEP-GET-2 → response dispatch)

#### 6.3.2.15

**Title:** Block PATCH persistence when database is unavailable
**Criterion:** Given the system is executing STEP-PATCH-1 with a write dependency, when ENV_DATABASE_UNAVAILABLE_PERSIST occurs, then halt STEP-PATCH-1 and stop propagation to STEP-PATCH-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DATABASE_UNAVAILABLE_PERSIST
**Reference:** database (steps: STEP-PATCH-1 → STEP-PATCH-2)

#### 6.3.2.16

**Title:** Block subtree re-evaluation when database becomes unavailable
**Criterion:** Given the system is executing STEP-PATCH-2 and requires reads, when ENV_DATABASE_UNAVAILABLE_REEVAL occurs, then halt STEP-PATCH-2 and stop propagation to STEP-PATCH-3, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DATABASE_UNAVAILABLE_REEVAL
**Reference:** database (steps: STEP-PATCH-2 → STEP-PATCH-3)

#### 6.3.2.17

**Title:** Halt GET load on database permission denied
**Criterion:** Given the system is executing STEP-GET-1 and authenticates to the database, when ENV_DATABASE_PERMISSION_DENIED_LOAD occurs, then halt STEP-GET-1 and stop propagation to STEP-GET-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DATABASE_PERMISSION_DENIED_LOAD
**Reference:** database permissions (steps: STEP-GET-1 → STEP-GET-2)

#### 6.3.2.18

**Title:** Block PATCH persistence on database permission denied
**Criterion:** Given the system is executing STEP-PATCH-1 with write privileges required, when ENV_DATABASE_PERMISSION_DENIED_PERSIST occurs, then halt STEP-PATCH-1 and stop propagation to STEP-PATCH-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DATABASE_PERMISSION_DENIED_PERSIST
**Reference:** database permissions (steps: STEP-PATCH-1 → STEP-PATCH-2)

#### 6.3.2.19

**Title:** Halt GET load when network to database is unreachable
**Criterion:** Given the system is executing STEP-GET-1 and must reach the database endpoint, when ENV_NETWORK_UNREACHABLE_DB_LOAD occurs, then halt STEP-GET-1 and stop propagation to STEP-GET-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_NETWORK_UNREACHABLE_DB_LOAD
**Reference:** network path to database (steps: STEP-GET-1 → STEP-GET-2)

#### 6.3.2.20

**Title:** Block PATCH persistence when network to database is unreachable
**Criterion:** Given the system is executing STEP-PATCH-1 and must reach the database endpoint, when ENV_NETWORK_UNREACHABLE_DB_PERSIST occurs, then halt STEP-PATCH-1 and stop propagation to STEP-PATCH-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_NETWORK_UNREACHABLE_DB_PERSIST
**Reference:** network path to database (steps: STEP-PATCH-1 → STEP-PATCH-2)

#### 6.3.2.21

**Title:** Halt GET load on DNS resolution failure for database
**Criterion:** Given the system is executing STEP-GET-1 and must resolve the database hostname, when ENV_DNS_RESOLUTION_FAILED_DB occurs, then halt STEP-GET-1 and stop propagation to STEP-GET-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DNS_RESOLUTION_FAILED_DB
**Reference:** DNS for database (steps: STEP-GET-1 → STEP-GET-2)

#### 6.3.2.22

**Title:** Block PATCH persistence on DNS resolution failure for database
**Criterion:** Given the system is executing STEP-PATCH-1 and must resolve the database hostname, when ENV_DNS_RESOLUTION_FAILED_DB occurs, then halt STEP-PATCH-1 and stop propagation to STEP-PATCH-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DNS_RESOLUTION_FAILED_DB
**Reference:** DNS for database (steps: STEP-PATCH-1 → STEP-PATCH-2)

#### 6.3.2.23

**Title:** Halt GET load on TLS handshake failure with database
**Criterion:** Given the system is executing STEP-GET-1 and negotiates TLS to the database, when ENV_TLS_HANDSHAKE_FAILED_DB occurs, then halt STEP-GET-1 and stop propagation to STEP-GET-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_TLS_HANDSHAKE_FAILED_DB
**Reference:** TLS to database (steps: STEP-GET-1 → STEP-GET-2)

#### 6.3.2.24

**Title:** Block PATCH persistence on TLS handshake failure with database
**Criterion:** Given the system is executing STEP-PATCH-1 and negotiates TLS to the database, when ENV_TLS_HANDSHAKE_FAILED_DB occurs, then halt STEP-PATCH-1 and stop propagation to STEP-PATCH-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_TLS_HANDSHAKE_FAILED_DB
**Reference:** TLS to database (steps: STEP-PATCH-1 → STEP-PATCH-2)

#### 6.3.2.25

**Title:** Halt GET load when runtime configuration for DB URI is missing
**Criterion:** Given the system is executing STEP-GET-1 and requires a configured database URI, when ENV_RUNTIME_CONFIG_MISSING_DB_URI occurs, then halt STEP-GET-1 and stop propagation to STEP-GET-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_RUNTIME_CONFIG_MISSING_DB_URI
**Reference:** runtime configuration (steps: STEP-GET-1 → STEP-GET-2)

#### 6.3.2.26

**Title:** Block PATCH persistence when runtime configuration for DB URI is missing
**Criterion:** Given the system is executing STEP-PATCH-1 and requires a configured database URI, when ENV_RUNTIME_CONFIG_MISSING_DB_URI occurs, then halt STEP-PATCH-1 and stop propagation to STEP-PATCH-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_RUNTIME_CONFIG_MISSING_DB_URI
**Reference:** runtime configuration (steps: STEP-PATCH-1 → STEP-PATCH-2)

#### 6.3.2.27

**Title:** Halt GET load on invalid database credentials
**Criterion:** Given the system is executing STEP-GET-1 and authenticates using stored credentials, when ENV_SECRET_INVALID_DB_CREDENTIALS occurs, then halt STEP-GET-1 and stop propagation to STEP-GET-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_SECRET_INVALID_DB_CREDENTIALS
**Reference:** secrets for database (steps: STEP-GET-1 → STEP-GET-2)

#### 6.3.2.28

**Title:** Block PATCH persistence on invalid database credentials
**Criterion:** Given the system is executing STEP-PATCH-1 and authenticates using stored credentials, when ENV_SECRET_INVALID_DB_CREDENTIALS occurs, then halt STEP-PATCH-1 and stop propagation to STEP-PATCH-2, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_SECRET_INVALID_DB_CREDENTIALS
**Reference:** secrets for database (steps: STEP-PATCH-1 → STEP-PATCH-2)

7.1.1 — QuestionnaireQuestion visibility fields exist
**Purpose:** Verify presence and typing of `parent_question_id` and `visible_if_value` in the QuestionnaireQuestion schema.
**Test Data:** schemas/QuestionnaireQuestion.schema.json (project root)
**Mocking:** None — static schema inspection only; mocking would invalidate structural checks.
**Assertions:**

* File exists and is readable.
* JSON parses successfully.
* `properties.parent_question_id.type` is `"string"` and `format` is `"uuid"`; schema allows null (via `nullable: true` or `type: ["string","null"]`).
* `properties.visible_if_value` permits exactly: null, string, or array of strings (via `oneOf` or `type` composition).
  **AC-Ref:** 6.1.1

7.1.2 — Response canonical value fields exist
**Purpose:** Verify Response schema exposes canonical fields required for visibility evaluation.
**Test Data:** schemas/Response.schema.json
**Mocking:** None — static schema inspection.
**Assertions:**

* File exists and is readable; JSON parses.
* `properties.option_id` is `"string"` with `format: "uuid"` (nullable allowed).
* `properties.value_bool` is `"boolean"` (nullable allowed).
* `properties.value_number` is `"number"` (nullable allowed).
* `properties.value_text` is `"string"` (nullable allowed).
  **AC-Ref:** 6.1.2

7.1.3 — AnswerOption canonical value field exists
**Purpose:** Verify AnswerOption schema exposes canonical `value`.
**Test Data:** schemas/AnswerOption.schema.json
**Mocking:** None — static schema inspection.
**Assertions:**

* File exists and is readable; JSON parses.
* `properties.value.type` is `"string"` and is required (present in `required` array).
  **AC-Ref:** 6.1.2

7.1.4 — ScreenView excludes rule/hidden containers
**Purpose:** Verify ScreenView schema structurally represents visible questions only (no rule or hidden containers).
**Test Data:** schemas/ScreenView.schema.json
**Mocking:** None — static schema inspection.
**Assertions:**

* File exists and is readable; JSON parses.
* Schema defines a collection for questions (e.g., `properties.questions` with `items` referencing question view).
* Schema does **not** define `hidden_questions`, `visibility_rules`, or similarly named properties (`properties` must not contain these keys).
  **AC-Ref:** 6.1.3

7.1.5 — AutosaveResult.suppressed_answers[] defined
**Purpose:** Verify AutosaveResult schema defines `suppressed_answers` as an array of question IDs.
**Test Data:** schemas/AutosaveResult.schema.json
**Mocking:** None — static schema inspection.
**Assertions:**

* File exists and is readable; JSON parses.
* `properties.suppressed_answers.type` is `"array"`; `items.type` is `"string"` with `format: "uuid"` (or references `QuestionId`).
* `suppressed_answers` is optional (not mandated in `required`).
  **AC-Ref:** 6.1.4

7.1.6 — AutosaveResult.visibility_delta.* defined
**Purpose:** Verify visibility delta object with `now_visible[]` and `now_hidden[]`.
**Test Data:** schemas/AutosaveResult.schema.json
**Mocking:** None — static schema inspection.
**Assertions:**

* `properties.visibility_delta.type` is `"object"`.
* `properties.visibility_delta.properties.now_visible.type` is `"array"`; `items` are string UUIDs (or `QuestionId`).
* `properties.visibility_delta.properties.now_hidden.type` is `"array"`; `items` are string UUIDs (or `QuestionId`).
* `visibility_delta` is optional (not mandated in `required`).
  **AC-Ref:** 6.1.5

7.1.7 — FeatureOutputs schema enforces deterministic keys
**Purpose:** Verify the outputs container schema fixes its key set.
**Test Data:** schemas/FeatureOutputs.schema.json
**Mocking:** None — static schema inspection.
**Assertions:**

* File exists and is readable; JSON parses.
* Schema sets `"additionalProperties": false` at the top level.
* Top-level `properties` enumerate only the allowed keys (e.g., `screen_view`, `autosave_result`) with no patternProperties.
  **AC-Ref:** 6.1.6

7.1.8 — AutosaveResult includes etag
**Purpose:** Verify presence and typing of `etag` in AutosaveResult schema.
**Test Data:** schemas/AutosaveResult.schema.json
**Mocking:** None — static schema inspection.
**Assertions:**

* `properties.etag.type` is `"string"`.
* `etag` appears in `required` when applicable (if schema variants exist, assert the variant used for PATCH responses requires `etag`).
  **AC-Ref:** 6.1.7

7.1.9 — OpenAPI defines If-Match parameter for PATCH
**Purpose:** Verify OpenAPI declares and applies `If-Match` header to the PATCH endpoint.
**Test Data:** openapi.yaml (project root)
**Mocking:** None — static contract inspection.
**Assertions:**

* File exists and is readable; YAML parses.
* `components.parameters.IfMatch` exists with `in: header`, `name: If-Match`, and `schema.type: string`.
* PATCH `/response-sets/{response_set_id}/answers/{question_id}` operation references `#/components/parameters/IfMatch`.
  **AC-Ref:** 6.1.7

7.1.10 — OpenAPI defines Idempotency-Key parameter for PATCH
**Purpose:** Verify OpenAPI declares and applies `Idempotency-Key` header to the PATCH endpoint.
**Test Data:** openapi.yaml
**Mocking:** None — static contract inspection.
**Assertions:**

* `components.parameters.IdempotencyKey` exists with `in: header`, `name: Idempotency-Key`, `schema.type: string`.
* PATCH `/response-sets/{response_set_id}/answers/{question_id}` operation references `#/components/parameters/IdempotencyKey`.
  **AC-Ref:** 6.1.8

7.1.11 — OpenAPI error responses use problem+json
**Purpose:** Verify OpenAPI declares schema-based error responses for 404, 409, and 422.
**Test Data:** openapi.yaml; schemas/Problem.schema.json
**Mocking:** None — static contract inspection.
**Assertions:**

* `components.schemas.Problem` (or external `$ref` to schemas/Problem.schema.json) is present.
* GET `/response-sets/{response_set_id}/screens/{screen_id}` and PATCH `/response-sets/{response_set_id}/answers/{question_id}` each define responses for `404`, `409` (PATCH only), and `422` with `content.application/problem+json.schema` referencing the Problem schema.
  **AC-Ref:** 6.1.9

## 7.2.1 Happy path contractual tests

### 7.2.1.1 — Child visible when parent matches

**Purpose:** Verify that a child question becomes visible when its parent’s canonical value matches `visible_if_value`.
**Test Data:**

* Parent question `q1` with `visible_if_value = "yes"`.
* Stored answer: `{ question_id: "q1", value_text: "yes" }`.
* GET `/response-sets/rs1/screens/s1`.
  **Mocking:** None — test uses live evaluation of screen response.
  **Assertions:**
* `outputs.screen_view.questions[].id` includes `"q_child"`.
* Hidden children not matching remain absent.
  **AC-Ref:** 6.2.1.1
  **EARS-Refs:** U1, S2

---

### 7.2.1.2 — Canonical value normalisation

**Purpose:** Verify parent answer values are normalised before visibility comparison.
**Test Data:**

* Parent question `q1` of type boolean.
* Stored answer: `{ question_id: "q1", value_text: "TRUE" }`.
* Child has `visible_if_value = "true"`.
  **Mocking:** None.
  **Assertions:**
* Child question `"q_child"` appears in `outputs.screen_view`.
* Normalisation applied (case insensitive for canonical values).
  **AC-Ref:** 6.2.1.2
  **EARS-Refs:** U2, O1, O2, O3

---

### 7.2.1.3 — Hidden questions excluded from ScreenView

**Purpose:** Verify that hidden questions never appear in `outputs.screen_view`.
**Test Data:**

* Parent question unanswered.
* GET `/response-sets/rs1/screens/s1`.
  **Mocking:** None.
  **Assertions:**
* `outputs.screen_view.questions[]` does not contain `"q_child"`.
  **AC-Ref:** 6.2.1.3
  **EARS-Refs:** U3, S1, S3

---

### 7.2.1.4 — Suppressed answers retained

**Purpose:** Verify suppressed answers are returned in `suppressed_answers` when a visible question becomes hidden.
**Test Data:**

* PATCH answer: set parent `q1` from `"yes"` to `"no"`.
* Child `q_child` had stored answer.
  **Mocking:** None.
  **Assertions:**
* `outputs.autosave_result.suppressed_answers[]` includes `"q_child"`.
* `outputs.autosave_result.saved == true`.
  **AC-Ref:** 6.2.1.4
  **EARS-Refs:** U4, E6

---

### 7.2.1.5 — Deterministic outputs

**Purpose:** Verify identical inputs yield identical outputs key sets.
**Test Data:**

* Two identical GET requests to `/response-sets/rs1/screens/s1`.
  **Mocking:** None.
  **Assertions:**
* Key set of `outputs` object identical across runs.
* Compare deep-equal JSON key order ignoring value differences.
  **AC-Ref:** 6.2.1.5
  **EARS-Refs:** U5

---

### 7.2.1.6 — Screen retrieval returns questions and answers

**Purpose:** Verify GET screen returns visible questions and their current answers.
**Test Data:**

* GET `/response-sets/rs1/screens/s1`.
  **Mocking:** None.
  **Assertions:**
* Each entry in `outputs.screen_view.questions[]` has corresponding answer from `Response`.
  **AC-Ref:** 6.2.1.6
  **EARS-Refs:** E1

---

### 7.2.1.7 — Server-side visibility filtering

**Purpose:** Verify server applies visibility rules before returning questions.
**Test Data:**

* Parent `q1` = `"no"`, child requires `"yes"`.
  **Mocking:** None.
  **Assertions:**
* `outputs.screen_view` omits `"q_child"`.
  **AC-Ref:** 6.2.1.7
  **EARS-Refs:** E2

---

### 7.2.1.8 — Answer persistence reflected in saved flag

**Purpose:** Verify PATCH persists answer and sets `saved=true`.
**Test Data:**

* PATCH `/response-sets/rs1/answers/q1` with `{ value_text: "hello" }`.
  **Mocking:** None.
  **Assertions:**
* `outputs.autosave_result.saved == true`.
* Persisted answer retrievable via subsequent GET.
  **AC-Ref:** 6.2.1.8
  **EARS-Refs:** E3

---

### 7.2.1.9 — Subtree re-evaluation

**Purpose:** Verify that changing a parent triggers re-evaluation of all descendants.
**Test Data:**

* PATCH parent `q1` from `"yes"` to `"no"`.
* Child and grandchild questions dependent.
  **Mocking:** None.
  **Assertions:**
* `outputs.autosave_result.visibility_delta.now_hidden[]` includes `"q_child"` and `"q_grandchild"`.
  **AC-Ref:** 6.2.1.9
  **EARS-Refs:** E4

---

### 7.2.1.10 — Visibility delta reporting

**Purpose:** Verify delta object contains lists of now-visible and now-hidden IDs.
**Test Data:**

* PATCH toggles parent answer.
  **Mocking:** None.
  **Assertions:**
* `outputs.autosave_result.visibility_delta.now_visible[]` lists questions revealed.
* `outputs.autosave_result.visibility_delta.now_hidden[]` lists questions hidden.
  **AC-Ref:** 6.2.1.10
  **EARS-Refs:** E5

---

### 7.2.1.11 — Suppression identifiers included

**Purpose:** Verify suppression identifiers included when answers are hidden.
**Test Data:**

* Child `q_child` answered then hidden via PATCH.
  **Mocking:** None.
  **Assertions:**
* `outputs.autosave_result.suppressed_answers[]` contains `"q_child"`.
  **AC-Ref:** 6.2.1.11
  **EARS-Refs:** E6

---

### 7.2.1.12 — Updated etag returned

**Purpose:** Verify PATCH response contains updated etag token.
**Test Data:**

* PATCH `/response-sets/rs1/answers/q1`.
  **Mocking:** None.
  **Assertions:**
* `outputs.autosave_result.etag` is non-empty string.
* ETag changes across sequential PATCH requests.
  **AC-Ref:** 6.2.1.12
  **EARS-Refs:** E7

---

### 7.2.1.13 — Enum_single value comparison

**Purpose:** Verify enum_single visibility uses canonical option `value`.
**Test Data:**

* Parent `q1` enum_single with selected option `{ option_id: "o1", value: "YES" }`.
* Child requires `visible_if_value = "YES"`.
  **Mocking:** None.
  **Assertions:**
* Child `"q_child"` appears in `outputs.screen_view`.
  **AC-Ref:** 6.2.1.13
  **EARS-Refs:** O1

---

### 7.2.1.14 — Boolean and number comparison

**Purpose:** Verify boolean/number values normalised before comparison.
**Test Data:**

* Parent `q1` numeric with `value_number = 10.0`.
* Child requires `"10"`.
  **Mocking:** None.
  **Assertions:**
* Child visible in `outputs.screen_view`.
  **AC-Ref:** 6.2.1.14
  **EARS-Refs:** O2

---

### 7.2.1.15 — Text value comparison

**Purpose:** Verify short_string/long_text comparisons use trimmed, case-sensitive match.
**Test Data:**

* Parent `q1` text with `value_text = " Yes "`.
* Child requires `"Yes"`.
  **Mocking:** None.
  **Assertions:**
* After trimming, match succeeds; child appears in `outputs.screen_view`.
* Changing to `"yes"` (lowercase) excludes child.
  **AC-Ref:** 6.2.1.15
  **EARS-Refs:** O3

7.2.2.1 — Reject missing response_set_id
**Purpose:** Verify requests without response_set_id are rejected with the correct error code.
**Test Data:** CLI: `GET /response-sets//screens/s1` (missing `response_set_id`).
**Mocking:** Mock router to invoke handler with `response_set_id = undefined`; no internal logic mocked; asserts handler is called with empty param.
**Assertions:** HTTP 400/422-style contract body emitted; `error.code == "PRE_RESPONSE_SET_ID_MISSING"`; no `outputs` object present.
**AC-Ref:** 6.2.2.1
**Error Mode:** PRE_RESPONSE_SET_ID_MISSING

7.2.2.2 — Reject invalid UUID response_set_id
**Purpose:** Verify invalid UUID in response_set_id is rejected.
**Test Data:** CLI: `GET /response-sets/not-a-uuid/screens/s1`.
**Mocking:** Mock UUID validator to real behaviour (no mocks on internal flow); mock datastore not called (assert zero calls).
**Assertions:** `error.code == "PRE_RESPONSE_SET_ID_INVALID_UUID"`; datastore load function not invoked.
**AC-Ref:** 6.2.2.2
**Error Mode:** PRE_RESPONSE_SET_ID_INVALID_UUID

7.2.2.3 — Reject unknown response_set_id
**Purpose:** Verify unknown response_set_id returns the expected error.
**Test Data:** CLI: `GET /response-sets/11111111-1111-1111-1111-111111111111/screens/s1`.
**Mocking:** Mock datastore `getResponseSet` to return `null`; assert called with provided UUID.
**Assertions:** `error.code == "PRE_RESPONSE_SET_ID_UNKNOWN"`; `outputs` absent.
**AC-Ref:** 6.2.2.3
**Error Mode:** PRE_RESPONSE_SET_ID_UNKNOWN

7.2.2.4 — Reject missing screen_id
**Purpose:** Verify missing screen_id is rejected.
**Test Data:** CLI: `GET /response-sets/rs1/screens/` (empty segment).
**Mocking:** Router passes `screen_id = ""`; datastore not called (assert).
**Assertions:** `error.code == "PRE_SCREEN_ID_MISSING"`.
**AC-Ref:** 6.2.2.4
**Error Mode:** PRE_SCREEN_ID_MISSING

7.2.2.5 — Reject screen_id schema mismatch
**Purpose:** Verify non-conforming screen_id is rejected.
**Test Data:** CLI: `GET /response-sets/rs1/screens/INVALID SPACE`.
**Mocking:** Schema validator real; datastore not called (assert).
**Assertions:** `error.code == "PRE_SCREEN_ID_SCHEMA_MISMATCH"`.
**AC-Ref:** 6.2.2.5
**Error Mode:** PRE_SCREEN_ID_SCHEMA_MISMATCH

7.2.2.6 — Reject unknown screen_id
**Purpose:** Verify unknown screen key is rejected.
**Test Data:** CLI: `GET /response-sets/rs1/screens/no-such-screen`.
**Mocking:** Mock `getScreenComposition("no-such-screen")` to return `null`.
**Assertions:** `error.code == "PRE_SCREEN_ID_UNKNOWN"`; no visibility computation invoked.
**AC-Ref:** 6.2.2.6
**Error Mode:** PRE_SCREEN_ID_UNKNOWN

7.2.2.7 — Reject missing question_id on PATCH
**Purpose:** Verify PATCH without question_id is rejected.
**Test Data:** CLI: `PATCH /response-sets/rs1/answers/` with body `{ "value_text":"x" }`.
**Mocking:** Router supplies empty `question_id`; persistence not called (assert).
**Assertions:** `error.code == "PRE_QUESTION_ID_MISSING"`.
**AC-Ref:** 6.2.2.7
**Error Mode:** PRE_QUESTION_ID_MISSING

7.2.2.8 — Reject non-UUID question_id
**Purpose:** Verify invalid question_id format is rejected.
**Test Data:** CLI: `PATCH /response-sets/rs1/answers/not-uuid` body `{ "value_text":"x" }`.
**Mocking:** UUID validator real; repo not called (assert).
**Assertions:** `error.code == "PRE_QUESTION_ID_INVALID_UUID"`.
**AC-Ref:** 6.2.2.8
**Error Mode:** PRE_QUESTION_ID_INVALID_UUID

7.2.2.9 — Reject unknown question_id
**Purpose:** Verify PATCH referencing unknown question is rejected.
**Test Data:** `PATCH /response-sets/rs1/answers/00000000-0000-0000-0000-000000000000`.
**Mocking:** Mock `getQuestionById` returns `null`; assert called with UUID.
**Assertions:** `error.code == "PRE_QUESTION_ID_UNKNOWN"`.
**AC-Ref:** 6.2.2.9
**Error Mode:** PRE_QUESTION_ID_UNKNOWN

7.2.2.10 — Reject missing answer body
**Purpose:** Verify missing PATCH body is rejected.
**Test Data:** `PATCH …/answers/q1` with empty body.
**Mocking:** HTTP layer presents `undefined` body; schema validator invoked.
**Assertions:** `error.code == "PRE_ANSWER_MISSING"`.
**AC-Ref:** 6.2.2.10
**Error Mode:** PRE_ANSWER_MISSING

7.2.2.11 — Reject invalid JSON body
**Purpose:** Verify invalid JSON body is rejected.
**Test Data:** Raw body: `{ value_text: "x" }` (missing quotes on key).
**Mocking:** Mock body parser to raise JSON parse error; persistence not called.
**Assertions:** `error.code == "PRE_ANSWER_INVALID_JSON"`.
**AC-Ref:** 6.2.2.11
**Error Mode:** PRE_ANSWER_INVALID_JSON

7.2.2.12 — Reject AnswerUpsert schema mismatch
**Purpose:** Verify schema mismatch in PATCH body is rejected.
**Test Data:** Body `{ "value_number": "not-a-number" }`.
**Mocking:** Schema validator real; persistence not called.
**Assertions:** `error.code == "PRE_ANSWER_SCHEMA_MISMATCH"`.
**AC-Ref:** 6.2.2.12
**Error Mode:** PRE_ANSWER_SCHEMA_MISMATCH

7.2.2.13 — Reject missing Idempotency-Key
**Purpose:** Verify missing header is rejected.
**Test Data:** Headers omit `Idempotency-Key`.
**Mocking:** Request context supplies headers; idempotency service not called.
**Assertions:** `error.code == "PRE_IDEMPOTENCY_KEY_MISSING"`.
**AC-Ref:** 6.2.2.13
**Error Mode:** PRE_IDEMPOTENCY_KEY_MISSING

7.2.2.14 — Reject empty Idempotency-Key
**Purpose:** Verify empty header value is rejected.
**Test Data:** `Idempotency-Key: ""`.
**Mocking:** Idempotency checker not invoked (assert).
**Assertions:** `error.code == "PRE_IDEMPOTENCY_KEY_EMPTY"`.
**AC-Ref:** 6.2.2.14
**Error Mode:** PRE_IDEMPOTENCY_KEY_EMPTY

7.2.2.15 — Reject reused Idempotency-Key for different payload
**Purpose:** Verify duplicate key across different payloads is rejected.
**Test Data:** First PATCH with key `k-123` body `{ "value_text":"a" }`; second PATCH with same key and body `{ "value_text":"b" }`.
**Mocking:** Mock idempotency store to recognise key with prior hash; comparator returns “mismatch”.
**Assertions:** `error.code == "PRE_IDEMPOTENCY_KEY_NOT_UNIQUE"`.
**AC-Ref:** 6.2.2.15
**Error Mode:** PRE_IDEMPOTENCY_KEY_NOT_UNIQUE

7.2.2.16 — Reject missing If-Match
**Purpose:** Verify missing `If-Match` header is rejected.
**Test Data:** Headers include `Idempotency-Key` but omit `If-Match`.
**Mocking:** Concurrency service not invoked (assert).
**Assertions:** `error.code == "PRE_IF_MATCH_MISSING"`.
**AC-Ref:** 6.2.2.16
**Error Mode:** PRE_IF_MATCH_MISSING

7.2.2.17 — Reject empty If-Match
**Purpose:** Verify empty `If-Match` value is rejected.
**Test Data:** `If-Match: ""`.
**Mocking:** Version comparator not called (assert).
**Assertions:** `error.code == "PRE_IF_MATCH_EMPTY"`.
**AC-Ref:** 6.2.2.17
**Error Mode:** PRE_IF_MATCH_EMPTY

7.2.2.18 — Reject stale If-Match
**Purpose:** Verify stale ETag is rejected.
**Test Data:** `If-Match: "v1"` while latest is `"v2"`.
**Mocking:** Mock state version service returns `"v2"`; comparator detects mismatch.
**Assertions:** `error.code == "PRE_IF_MATCH_STALE"`.
**AC-Ref:** 6.2.2.18
**Error Mode:** PRE_IF_MATCH_STALE

7.2.2.19 — Reject invalid parent_question_id format
**Purpose:** Ensure invalid UUID for parent_question_id is rejected at evaluation time.
**Test Data:** Question record has `parent_question_id: "bad-id"`.
**Mocking:** Mock question repository to return this malformed record; evaluation proceeds.
**Assertions:** `error.code == "PRE_QUESTIONNAIREQUESTION_PARENT_QUESTION_ID_INVALID_UUID"`.
**AC-Ref:** 6.2.2.19
**Error Mode:** PRE_QUESTIONNAIREQUESTION_PARENT_QUESTION_ID_INVALID_UUID

7.2.2.20 — Reject parent_question_id not found
**Purpose:** Ensure non-existent parent_question_id is rejected.
**Test Data:** `parent_question_id: "11111111-1111-1111-1111-111111111111"` with no matching question.
**Mocking:** Repo `getQuestionById` returns `null` for that UUID; assert call.
**Assertions:** `error.code == "PRE_QUESTIONNAIREQUESTION_PARENT_QUESTION_ID_NOT_FOUND"`.
**AC-Ref:** 6.2.2.20
**Error Mode:** PRE_QUESTIONNAIREQUESTION_PARENT_QUESTION_ID_NOT_FOUND

7.2.2.21 — Reject invalid visible_if_value type
**Purpose:** Ensure visible_if_value type violations are rejected.
**Test Data:** Question has `visible_if_value: { "eq": "yes" }` (object).
**Mocking:** Repo returns this record; evaluator reads field.
**Assertions:** `error.code == "PRE_QUESTIONNAIREQUESTION_VISIBLE_IF_VALUE_TYPE"`.
**AC-Ref:** 6.2.2.21
**Error Mode:** PRE_QUESTIONNAIREQUESTION_VISIBLE_IF_VALUE_TYPE

7.2.2.22 — Reject non-canonical visible_if_value
**Purpose:** Ensure non-canonical tokens are rejected.
**Test Data:** `visible_if_value: ["NOT_A_TOKEN"]` where parent’s canonical set is `["YES","NO"]`.
**Mocking:** Mock options repo to return canonical set; validator compares.
**Assertions:** `error.code == "PRE_QUESTIONNAIREQUESTION_VISIBLE_IF_VALUE_NONCANONICAL"`.
**AC-Ref:** 6.2.2.22
**Error Mode:** PRE_QUESTIONNAIREQUESTION_VISIBLE_IF_VALUE_NONCANONICAL

7.2.2.23 — Reject non-UUID Response.option_id
**Purpose:** Ensure invalid stored option_id is rejected.
**Test Data:** Response `{ option_id: "xyz" }`.
**Mocking:** Response store returns this document; options repo not called.
**Assertions:** `error.code == "PRE_RESPONSE_OPTION_ID_INVALID_UUID"`.
**AC-Ref:** 6.2.2.23
**Error Mode:** PRE_RESPONSE_OPTION_ID_INVALID_UUID

7.2.2.24 — Reject unknown Response.option_id
**Purpose:** Ensure unknown option_id is rejected.
**Test Data:** Response `{ option_id: "22222222-2222-2222-2222-222222222222" }`.
**Mocking:** Options repo `getOptionById` returns `null`; assert called.
**Assertions:** `error.code == "PRE_RESPONSE_OPTION_ID_UNKNOWN"`.
**AC-Ref:** 6.2.2.24
**Error Mode:** PRE_RESPONSE_OPTION_ID_UNKNOWN

7.2.2.25 — Reject non-boolean value_bool
**Purpose:** Ensure non-boolean stored value_bool is rejected.
**Test Data:** Response `{ value_bool: "true" }` (string).
**Mocking:** Response store returns document; type checker runs.
**Assertions:** `error.code == "PRE_RESPONSE_VALUE_BOOL_NOT_BOOLEAN"`.
**AC-Ref:** 6.2.2.25
**Error Mode:** PRE_RESPONSE_VALUE_BOOL_NOT_BOOLEAN

7.2.2.26 — Reject non-finite value_number
**Purpose:** Ensure non-finite numeric values are rejected.
**Test Data:** Response `{ value_number: Infinity }`.
**Mocking:** Response store returns document; numeric validator runs.
**Assertions:** `error.code == "PRE_RESPONSE_VALUE_NUMBER_NOT_FINITE"`.
**AC-Ref:** 6.2.2.26
**Error Mode:** PRE_RESPONSE_VALUE_NUMBER_NOT_FINITE

7.2.2.27 — Reject non-string value_text
**Purpose:** Ensure non-string texts are rejected.
**Test Data:** Response `{ value_text: 123 }`.
**Mocking:** Response store returns document.
**Assertions:** `error.code == "PRE_RESPONSE_VALUE_TEXT_NOT_STRING"`.
**AC-Ref:** 6.2.2.27
**Error Mode:** PRE_RESPONSE_VALUE_TEXT_NOT_STRING

7.2.2.28 — Reject missing AnswerOption.value
**Purpose:** Ensure options without canonical value are rejected.
**Test Data:** Option record `{ id:"o1", value: null }`.
**Mocking:** Options repo returns record; validator checks required field.
**Assertions:** `error.code == "PRE_ANSWEROPTION_VALUE_MISSING"`.
**AC-Ref:** 6.2.2.28
**Error Mode:** PRE_ANSWEROPTION_VALUE_MISSING

7.2.2.29 — Reject invalid outputs container schema
**Purpose:** Ensure outputs object failing schema validation is rejected.
**Test Data:** Handler returns `{ outputs: { extra_key: {} } }`.
**Mocking:** Mock final response builder to inject `extra_key`; schema validator real.
**Assertions:** `error.code == "POST_OUTPUTS_SCHEMA_INVALID"`.
**AC-Ref:** 6.2.2.29
**Error Mode:** POST_OUTPUTS_SCHEMA_INVALID

7.2.2.30 — Reject non-deterministic outputs keys
**Purpose:** Ensure key set determinism is enforced.
**Test Data:** Two identical GET runs returning `outputs` with/without `autosave_result`.
**Mocking:** Mock builder to randomly include `autosave_result`; run twice.
**Assertions:** `error.code == "POST_OUTPUTS_KEYS_NOT_DETERMINISTIC"` on detection of differing keys.
**AC-Ref:** 6.2.2.30
**Error Mode:** POST_OUTPUTS_KEYS_NOT_DETERMINISTIC

7.2.2.31 — Reject invalid ScreenView schema
**Purpose:** Ensure screen_view structure must validate.
**Test Data:** `outputs.screen_view` missing required `questions` array.
**Mocking:** Response builder emits malformed object.
**Assertions:** `error.code == "POST_SCREEN_VIEW_SCHEMA_INVALID"`.
**AC-Ref:** 6.2.2.31
**Error Mode:** POST_SCREEN_VIEW_SCHEMA_INVALID

7.2.2.32 — Reject ScreenView containing hidden questions
**Purpose:** Ensure hidden questions cannot appear in screen_view.
**Test Data:** screen_view includes `q_hidden` known to be invisible for state.
**Mocking:** Visibility service returns hidden set containing `q_hidden`; projector includes it anyway.
**Assertions:** `error.code == "POST_SCREEN_VIEW_CONTAINS_HIDDEN"`.
**AC-Ref:** 6.2.2.32
**Error Mode:** POST_SCREEN_VIEW_CONTAINS_HIDDEN

7.2.2.33 — Reject invalid AutosaveResult schema
**Purpose:** Ensure autosave_result must validate.
**Test Data:** `outputs.autosave_result` lacks both `saved` and `etag`.
**Mocking:** Builder emits malformed object.
**Assertions:** `error.code == "POST_AUTOSAVE_RESULT_SCHEMA_INVALID"`.
**AC-Ref:** 6.2.2.33
**Error Mode:** POST_AUTOSAVE_RESULT_SCHEMA_INVALID

7.2.2.34 — Reject missing saved flag
**Purpose:** Ensure `saved` is required when autosave_result present.
**Test Data:** `outputs.autosave_result` without `saved`.
**Mocking:** Builder omits field.
**Assertions:** `error.code == "POST_SAVED_MISSING"`.
**AC-Ref:** 6.2.2.34
**Error Mode:** POST_SAVED_MISSING

7.2.2.35 — Reject non-boolean saved
**Purpose:** Ensure saved is boolean.
**Test Data:** `saved: "true"`.
**Mocking:** Builder emits wrong type.
**Assertions:** `error.code == "POST_SAVED_NOT_BOOLEAN"`.
**AC-Ref:** 6.2.2.35
**Error Mode:** POST_SAVED_NOT_BOOLEAN

7.2.2.36 — Reject missing etag
**Purpose:** Ensure etag is required when autosave_result present.
**Test Data:** `outputs.autosave_result` without `etag`.
**Mocking:** Builder omits field.
**Assertions:** `error.code == "POST_ETAG_MISSING"`.
**AC-Ref:** 6.2.2.36
**Error Mode:** POST_ETAG_MISSING

7.2.2.37 — Reject empty etag
**Purpose:** Ensure etag must be non-empty.
**Test Data:** `etag: ""`.
**Mocking:** Builder sets empty string.
**Assertions:** `error.code == "POST_ETAG_EMPTY"`.
**AC-Ref:** 6.2.2.37
**Error Mode:** POST_ETAG_EMPTY

7.2.2.38 — Reject non-latest etag
**Purpose:** Ensure returned etag equals latest state token.
**Test Data:** Returned `etag: "v1"` while latest is `"v2"`.
**Mocking:** Version service returns `"v2"`; comparator detects mismatch.
**Assertions:** `error.code == "POST_ETAG_NOT_LATEST"`.
**AC-Ref:** 6.2.2.38
**Error Mode:** POST_ETAG_NOT_LATEST

7.2.2.39 — Reject invalid visibility_delta schema
**Purpose:** Ensure visibility_delta must validate.
**Test Data:** `visibility_delta: { "now_visible": "q1" }` (wrong type).
**Mocking:** Builder emits invalid object.
**Assertions:** `error.code == "POST_VISIBILITY_DELTA_SCHEMA_INVALID"`.
**AC-Ref:** 6.2.2.39
**Error Mode:** POST_VISIBILITY_DELTA_SCHEMA_INVALID

7.2.2.40 — Reject missing visibility_delta when changes occurred
**Purpose:** Ensure delta is present when visibility changes.
**Test Data:** PATCH flips parent answer; builder returns `autosave_result` without `visibility_delta`.
**Mocking:** Visibility engine marks differences; builder omits delta.
**Assertions:** `error.code == "POST_VISIBILITY_DELTA_MISSING"`.
**AC-Ref:** 6.2.2.40
**Error Mode:** POST_VISIBILITY_DELTA_MISSING

7.2.2.41 — Reject now_visible[] invalid ID
**Purpose:** Ensure IDs in now_visible are valid question IDs.
**Test Data:** `now_visible: ["not-a-uuid"]`.
**Mocking:** Builder emits invalid element.
**Assertions:** `error.code == "POST_NOW_VISIBLE_INVALID_ID"`.
**AC-Ref:** 6.2.2.41
**Error Mode:** POST_NOW_VISIBLE_INVALID_ID

7.2.2.42 — Reject now_hidden[] invalid ID
**Purpose:** Ensure IDs in now_hidden are valid question IDs.
**Test Data:** `now_hidden: [123]`.
**Mocking:** Builder emits number element.
**Assertions:** `error.code == "POST_NOW_HIDDEN_INVALID_ID"`.
**AC-Ref:** 6.2.2.42
**Error Mode:** POST_NOW_HIDDEN_INVALID_ID

7.2.2.43 — Reject suppressed_answers[] invalid ID
**Purpose:** Ensure suppressed_answers contain valid question IDs.
**Test Data:** `suppressed_answers: ["  "]`.
**Mocking:** Builder emits blank string.
**Assertions:** `error.code == "POST_SUPPRESSED_ANSWERS_INVALID_ID"`.
**AC-Ref:** 6.2.2.43
**Error Mode:** POST_SUPPRESSED_ANSWERS_INVALID_ID

7.2.2.44 — Reject suppressed_answers that are not newly hidden
**Purpose:** Ensure suppression set only includes newly hidden questions.
**Test Data:** Visibility_delta shows no change for `qX`; builder still lists `qX` in `suppressed_answers`.
**Mocking:** Delta engine returns `now_hidden: []`; builder injects `["qX"]`.
**Assertions:** `error.code == "POST_SUPPRESSED_ANSWERS_NOT_NEWLY_HIDDEN"`.
**AC-Ref:** 6.2.2.44
**Error Mode:** POST_SUPPRESSED_ANSWERS_NOT_NEWLY_HIDDEN

### 7.3.1.1 — Screen request initiates data load (STEP-GET-1)

**Purpose:** Verify that accepting a GET screen request immediately triggers the screen data load step.
**Test Data:** `GET /response-sets/11111111-1111-1111-1111-111111111111/screens/s-main` (valid IDs).
**Mocking:** Mock datastore client to return a minimal “screen questions + current answers” payload on first call; all other dependencies stubbed to no-op successes to allow flow observation.
**Assertions:** Assert invoked once immediately after request acceptance and not before: `STEP-GET-1 (Load questions and answers)`.
**AC-Ref:** 6.3.1.1

---

### 7.3.1.2 — Data load completion triggers visibility computation (STEP-GET-2)

**Purpose:** Verify that completing the load step triggers server-side visibility computation.
**Test Data:** Same request as 7.3.1.1.
**Mocking:** Datastore returns valid questions/answers (success); visibility engine mock returns a dummy “ok to compute” signal.
**Assertions:** Assert invoked once immediately after `STEP-GET-1` completes, and not before: `STEP-GET-2 (Compute visibility)`.
**AC-Ref:** 6.3.1.2

---

### 7.3.1.3 — PATCH request initiates answer persistence (STEP-PATCH-1)

**Purpose:** Verify that accepting a PATCH answer request triggers the persistence step.
**Test Data:** `PATCH /response-sets/11111111-1111-1111-1111-111111111111/answers/00000000-0000-0000-0000-000000000001` with body `{ "value_text": "alpha" }`, headers `If-Match: "v1"`, `Idempotency-Key: "k-1"`.
**Mocking:** Persistence repository mock returns success; all other dependencies stubbed to succeed.
**Assertions:** Assert invoked once immediately after request acceptance and not before: `STEP-PATCH-1 (Persist answer change)`.
**AC-Ref:** 6.3.1.3

---

### 7.3.1.4 — Persistence completion triggers descendant re-evaluation (STEP-PATCH-2)

**Purpose:** Verify that completing persistence triggers subtree re-evaluation.
**Test Data:** Same PATCH as 7.3.1.3.
**Mocking:** Persistence success; graph traversal evaluator mock prepared to receive a call.
**Assertions:** Assert invoked once immediately after `STEP-PATCH-1` completes, and not before: `STEP-PATCH-2 (Re-evaluate descendant visibility)`.
**AC-Ref:** 6.3.1.4

---

### 7.3.1.5 — Re-evaluation completion triggers delta build (STEP-PATCH-3)

**Purpose:** Verify that completing subtree re-evaluation triggers delta construction.
**Test Data:** Same PATCH as 7.3.1.3.
**Mocking:** Re-evaluation mock returns a minimal “changed set” marker; delta builder mock prepared to receive a call.
**Assertions:** Assert invoked once immediately after `STEP-PATCH-2` completes, and not before: `STEP-PATCH-3 (Build visibility_delta)`.
**AC-Ref:** 6.3.1.5

---

### 7.3.1.6 — Delta build completion triggers suppression derivation (STEP-PATCH-4)

**Purpose:** Verify that completing delta build triggers derivation of the suppression set.
**Test Data:** Same PATCH as 7.3.1.3.
**Mocking:** Delta builder returns dummy now-visible/now-hidden lists; suppression derivation mock prepared to receive a call.
**Assertions:** Assert invoked once immediately after `STEP-PATCH-3` completes, and not before: `STEP-PATCH-4 (Derive suppressed answers)`.
**AC-Ref:** 6.3.1.6

---

### 7.3.1.7 — Suppression derivation completion triggers ETag update (STEP-PATCH-5)

**Purpose:** Verify that completing suppression derivation triggers the ETag computation step.
**Test Data:** Same PATCH as 7.3.1.3.
**Mocking:** Suppression derivation returns a dummy list; ETag service mock prepared to receive a call.
**Assertions:** Assert invoked once immediately after `STEP-PATCH-4` completes, and not before: `STEP-PATCH-5 (Compute updated ETag)`.
**AC-Ref:** 6.3.1.7

---

### 7.3.1.8 — Unanswered parent routes children to hidden branch (behavioural routing)

**Purpose:** Verify that an unanswered parent causes routing into the “hidden branch” of the visibility pipeline.
**Test Data:** GET for a screen where parent `q1` has no stored answer and child `q_child` has `visible_if_value = "YES"`.
**Mocking:** Visibility pipeline exposes branch hooks; mock the branch router to record “hidden branch” vs “visible branch” invocations.
**Assertions:** Assert invoked once immediately after visibility evaluation starts for `q_child`, and not before: route to **hidden branch**; assert **no** invocation of visible branch for `q_child`.
**AC-Ref:** 6.3.1.8

---

### 7.3.1.9 — Matching canonical value routes child to visible branch (behavioural routing)

**Purpose:** Verify that a matching canonical value causes routing into the “visible branch”.
**Test Data:** GET with parent `q1` canonical value `"YES"`; child `q_child` requires `visible_if_value = "YES"`.
**Mocking:** Branch router records branch invocations; canonical value resolver returns `"YES"`.
**Assertions:** Assert invoked once immediately after visibility evaluation starts for `q_child`, and not before: route to **visible branch**; assert **no** invocation of hidden branch for `q_child`.
**AC-Ref:** 6.3.1.9

---

### 7.3.1.10 — Non-matching canonical value routes child to hidden branch (behavioural routing)

**Purpose:** Verify that a non-matching canonical value causes routing into the “hidden branch”.
**Test Data:** GET with parent `q1` canonical value `"NO"`; child `q_child` requires `visible_if_value = "YES"`.
**Mocking:** Branch router records branch invocations; canonical resolver returns `"NO"`.
**Assertions:** Assert invoked once immediately after visibility evaluation starts for `q_child`, and not before: route to **hidden branch**; assert **no** invocation of visible branch for `q_child`.
**AC-Ref:** 6.3.1.10

### 7.3.2.13 — Halt GET load when database is unavailable

**Purpose:** Validate that screen data loading halts and no downstream steps run when the database is unavailable during GET.
**Test Data:** Invoke `GET /response-sets/rs-123/screens/s-abc`.
**Mocking:** Mock the DB client used in **STEP-GET-1** to raise a `DatabaseUnavailableError` on first call; assert the client is called exactly once with `response_set_id="rs-123"` and `screen_id="s-abc"`. No other dependencies mocked.
**Assertions:** Assert error handler is invoked once immediately when **STEP-GET-1** raises due to database unavailability, and not before. Assert **STEP-GET-1** halts and stop propagation to **STEP-GET-2**. Assert that error mode `ENV_DATABASE_UNAVAILABLE_LOAD` is observed. Assert no retries without backoff, no partial state mutations, and no side-effects. Assert one error telemetry event is emitted.
**AC-Ref:** 6.3.2.13
**Error Mode:** ENV_DATABASE_UNAVAILABLE_LOAD

---

### 7.3.2.14 — Halt GET visibility compute when database becomes unavailable

**Purpose:** Validate that visibility computation halts when the DB goes unavailable mid-request.
**Test Data:** Invoke `GET /response-sets/rs-123-same/screens/s-abc-same`.
**Mocking:** Allow **STEP-GET-1** DB calls to succeed; mock the DB client used in **STEP-GET-2** to raise `DatabaseUnavailableError` on read of parent answers/options.
**Assertions:** Assert error handler is invoked once immediately when **STEP-GET-2** raises due to database unavailability. Assert **STEP-GET-2** halts and stop propagation to response dispatch. Assert error mode `ENV_DATABASE_UNAVAILABLE_COMPUTE` is observed. Assert no further DB calls occur after the failure. Assert one telemetry event is emitted.
**AC-Ref:** 6.3.2.14
**Error Mode:** ENV_DATABASE_UNAVAILABLE_COMPUTE

---

### 7.3.2.15 — Block PATCH persistence when database is unavailable

**Purpose:** Validate that answer persistence stops and no re-evaluation occurs when DB is unavailable.
**Test Data:** Invoke `PATCH /response-sets/rs-200/answers/00000000-0000-0000-0000-000000000001` with body `{ "value_text": "X" }`.
**Mocking:** Mock the DB client used in **STEP-PATCH-1** to raise `DatabaseUnavailableError` on write.
**Assertions:** Assert error handler is invoked once when **STEP-PATCH-1** raises due to database unavailability. Assert halt of **STEP-PATCH-1** and stop propagation to **STEP-PATCH-2**. Assert error mode `ENV_DATABASE_UNAVAILABLE_PERSIST` is observed. Assert no subtree re-evaluation or delta building attempts occur. Assert one telemetry event.
**AC-Ref:** 6.3.2.15
**Error Mode:** ENV_DATABASE_UNAVAILABLE_PERSIST

---

### 7.3.2.16 — Block subtree re-evaluation when database becomes unavailable

**Purpose:** Validate that re-evaluation stops and downstream delta building is skipped on DB outage during PATCH.
**Test Data:** Invoke `PATCH /response-sets/rs-201/answers/00000000-0000-0000-0000-000000000002` with body `{ "value_text": "Y" }`.
**Mocking:** Allow **STEP-PATCH-1** to succeed; mock DB reads in **STEP-PATCH-2** to raise `DatabaseUnavailableError`.
**Assertions:** Assert error handler is invoked once immediately when **STEP-PATCH-2** raises due to database unavailability. Assert halt of **STEP-PATCH-2** and stop propagation to **STEP-PATCH-3**. Assert error mode `ENV_DATABASE_UNAVAILABLE_REEVAL` is observed. Assert no delta or suppression derivation occurs. Assert one telemetry event.
**AC-Ref:** 6.3.2.16
**Error Mode:** ENV_DATABASE_UNAVAILABLE_REEVAL

---

### 7.3.2.17 — Halt GET load on database permission denied

**Purpose:** Validate GET load halts on DB permission denial.
**Test Data:** `GET /response-sets/rs-300/screens/s-main`.
**Mocking:** Mock DB client in **STEP-GET-1** to raise `PermissionDeniedError` on first read.
**Assertions:** Assert error handler invoked once when **STEP-GET-1** raises due to permission denial. Assert halt of **STEP-GET-1** and stop propagation to **STEP-GET-2**. Assert error mode `ENV_DATABASE_PERMISSION_DENIED_LOAD` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.17
**Error Mode:** ENV_DATABASE_PERMISSION_DENIED_LOAD

---

### 7.3.2.18 — Block PATCH persistence on database permission denied

**Purpose:** Validate PATCH persistence halts on DB permission denial and prevents re-evaluation.
**Test Data:** `PATCH /response-sets/rs-301/answers/00000000-0000-0000-0000-000000000003` with `{ "value_text": "Z" }`.
**Mocking:** Mock DB client in **STEP-PATCH-1** to raise `PermissionDeniedError` on write.
**Assertions:** Assert error handler invoked once when **STEP-PATCH-1** raises due to permission denial. Assert halt of **STEP-PATCH-1** and stop propagation to **STEP-PATCH-2**. Assert error mode `ENV_DATABASE_PERMISSION_DENIED_PERSIST` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.18
**Error Mode:** ENV_DATABASE_PERMISSION_DENIED_PERSIST

---

### 7.3.2.19 — Halt GET load when network to database is unreachable

**Purpose:** Validate GET load halts and no downstream work happens on network unreachable.
**Test Data:** `GET /response-sets/rs-net/screens/s-net`.
**Mocking:** Mock network layer used by **STEP-GET-1** DB client to raise `NetworkUnreachableError` on connect.
**Assertions:** Assert error handler invoked once when **STEP-GET-1** raises due to network unreachable. Assert halt of **STEP-GET-1** and stop propagation to **STEP-GET-2**. Assert error mode `ENV_NETWORK_UNREACHABLE_DB_LOAD` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.19
**Error Mode:** ENV_NETWORK_UNREACHABLE_DB_LOAD

---

### 7.3.2.20 — Block PATCH persistence when network to database is unreachable

**Purpose:** Validate PATCH persistence halts on network unreachable and prevents re-evaluation.
**Test Data:** `PATCH /response-sets/rs-net2/answers/00000000-0000-0000-0000-000000000004` with `{ "value_text": "net" }`.
**Mocking:** Mock network layer for **STEP-PATCH-1** DB client to raise `NetworkUnreachableError` on write.
**Assertions:** Assert error handler invoked once when **STEP-PATCH-1** raises due to network unreachable. Assert halt of **STEP-PATCH-1** and stop propagation to **STEP-PATCH-2**. Assert error mode `ENV_NETWORK_UNREACHABLE_DB_PERSIST` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.20
**Error Mode:** ENV_NETWORK_UNREACHABLE_DB_PERSIST

---

### 7.3.2.21 — Halt GET load on DNS resolution failure for database

**Purpose:** Validate GET load halts on DNS failure.
**Test Data:** `GET /response-sets/rs-dns/screens/s-dns`.
**Mocking:** Mock DNS resolver used by **STEP-GET-1** DB client to raise `DnsResolutionError` for the DB host.
**Assertions:** Assert error handler invoked once when **STEP-GET-1** raises due to DNS resolution failure. Assert halt of **STEP-GET-1** and stop propagation to **STEP-GET-2**. Assert error mode `ENV_DNS_RESOLUTION_FAILED_DB` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.21
**Error Mode:** ENV_DNS_RESOLUTION_FAILED_DB

---

### 7.3.2.22 — Block PATCH persistence on DNS resolution failure for database

**Purpose:** Validate PATCH persistence halts on DNS failure and no re-evaluation occurs.
**Test Data:** `PATCH /response-sets/rs-dns2/answers/00000000-0000-0000-0000-000000000005` with `{ "value_text": "dns" }`.
**Mocking:** Mock DNS resolver for **STEP-PATCH-1** DB client to raise `DnsResolutionError` on connect.
**Assertions:** Assert error handler invoked once when **STEP-PATCH-1** raises due to DNS failure. Assert halt of **STEP-PATCH-1** and stop propagation to **STEP-PATCH-2**. Assert error mode `ENV_DNS_RESOLUTION_FAILED_DB` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.22
**Error Mode:** ENV_DNS_RESOLUTION_FAILED_DB

---

### 7.3.2.23 — Halt GET load on TLS handshake failure with database

**Purpose:** Validate GET load halts on TLS handshake failure.
**Test Data:** `GET /response-sets/rs-tls/screens/s-tls`.
**Mocking:** Mock TLS layer for **STEP-GET-1** DB client to raise `TlsHandshakeError` during negotiation.
**Assertions:** Assert error handler invoked once when **STEP-GET-1** raises due to TLS failure. Assert halt of **STEP-GET-1** and stop propagation to **STEP-GET-2**. Assert error mode `ENV_TLS_HANDSHAKE_FAILED_DB` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.23
**Error Mode:** ENV_TLS_HANDSHAKE_FAILED_DB

---

### 7.3.2.24 — Block PATCH persistence on TLS handshake failure with database

**Purpose:** Validate PATCH persistence halts on TLS failure and prevents re-evaluation.
**Test Data:** `PATCH /response-sets/rs-tls2/answers/00000000-0000-0000-0000-000000000006` with `{ "value_text": "tls" }`.
**Mocking:** Mock TLS layer for **STEP-PATCH-1** DB client to raise `TlsHandshakeError` during connect.
**Assertions:** Assert error handler invoked once when **STEP-PATCH-1** raises due to TLS failure. Assert halt of **STEP-PATCH-1** and stop propagation to **STEP-PATCH-2**. Assert error mode `ENV_TLS_HANDSHAKE_FAILED_DB` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.24
**Error Mode:** ENV_TLS_HANDSHAKE_FAILED_DB

---

### 7.3.2.25 — Halt GET load when runtime configuration for DB URI is missing

**Purpose:** Validate GET load halts when required DB URI config is absent.
**Test Data:** `GET /response-sets/rs-cfg/screens/s-cfg`.
**Mocking:** Mock runtime config in **STEP-GET-1** to return `None`/missing for DB URI; DB client is never instantiated (assert).
**Assertions:** Assert error handler invoked once when **STEP-GET-1** detects missing DB URI. Assert halt of **STEP-GET-1** and stop propagation to **STEP-GET-2**. Assert error mode `ENV_RUNTIME_CONFIG_MISSING_DB_URI` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.25
**Error Mode:** ENV_RUNTIME_CONFIG_MISSING_DB_URI

---

### 7.3.2.26 — Block PATCH persistence when runtime configuration for DB URI is missing

**Purpose:** Validate PATCH persistence halts when DB URI config is absent and prevents re-evaluation.
**Test Data:** `PATCH /response-sets/rs-cfg2/answers/00000000-0000-0000-0000-000000000007` with `{ "value_text": "cfg" }`.
**Mocking:** Mock runtime config in **STEP-PATCH-1** to return `None` for DB URI; assert DB client not constructed.
**Assertions:** Assert error handler invoked once when **STEP-PATCH-1** detects missing DB URI. Assert halt of **STEP-PATCH-1** and stop propagation to **STEP-PATCH-2**. Assert error mode `ENV_RUNTIME_CONFIG_MISSING_DB_URI` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.26
**Error Mode:** ENV_RUNTIME_CONFIG_MISSING_DB_URI

---

### 7.3.2.27 — Halt GET load on invalid database credentials

**Purpose:** Validate GET load halts when stored DB credentials are invalid.
**Test Data:** `GET /response-sets/rs-sec/screens/s-sec`.
**Mocking:** Mock secrets provider in **STEP-GET-1** to supply invalid credentials; mock DB client to raise `AuthenticationError` on connect.
**Assertions:** Assert error handler invoked once when **STEP-GET-1** raises due to invalid credentials. Assert halt of **STEP-GET-1** and stop propagation to **STEP-GET-2**. Assert error mode `ENV_SECRET_INVALID_DB_CREDENTIALS` is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.27
**Error Mode:** ENV_SECRET_INVALID_DB_CREDENTIALS

---

### 7.3.2.28 — Block PATCH persistence on invalid database credentials

**Purpose:** Validate PATCH persistence halts when DB credentials are invalid and prevents re-evaluation.
**Test Data:** `PATCH /response-sets/rs-sec2/answers/00000000-0000-0000-0000-000000000008` with `{ "value_text": "sec" }`.
**Mocking:** Mock secrets provider in **STEP-PATCH-1** to supply invalid credentials; mock DB client to raise `AuthenticationError` on write.
**Assertions:** Assert error handler invoked once when **STEP-PATCH-1** raises due to invalid credentials. Assert halt of **STEP-PATCH-1** and stop propagation to **STEP-PATCH-2**. Assert error mode `ENV_SECRET_INVALID_DB_CREDENTIALS` is observed. Assert no unintended side-effects. Assert one telemetry event.
**AC-Ref:** 6.3.2.28
**Error Mode:** ENV_SECRET_INVALID_DB_CREDENTIALS