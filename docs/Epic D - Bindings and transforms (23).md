# epic d – placeholders, bindings and transforms

## objective

Define APIs and behaviour to accept isolated placeholders from the frontend, propose answer-kind transforms for each placeholder, and bind selected placeholder–transform pairs to existing questions. Transforms are evaluated independently from binding. Placeholders are only persisted when bound to a question.

## problem statement

Previously, binding and transforms were conflated. Epic C clarifies that placeholders are detected during ingestion, but not stored globally. Editors need a way to try transforms on a placeholder, see the suggested answer kind and options, then bind the chosen transform to a question. Multiple placeholders may bind to the same question, but all bound placeholders for that question must resolve to the same answer kind and option set.

## scope

in scope

* Stateless transform suggestion

* Binding API that accepts a placeholder, selected transform, and target question id, creates a Placeholder row scoped to the question, and applies the transform’s answer options to that question.

* Consistency guard that prevents binding if it would change the question’s answer kind or option set from what is already enforced by a previous binding.

* Read API to list bound placeholders per question.

* Idempotency for binding operations.

* Cleanup of placeholders and bindings when a document is deleted (hooked into Epic C lifecycle).

* Unbinding of placeholders from questions, with clearing of answer model if no placeholders remain.

out of scope

* Conditional visibility rules (Epic I).
* Questionnaire CRUD and base answer validation (Epic B).
* Document merge and generation.

## definitions

* placeholder: a structured token extracted from a source document that represents where a value should be injected.
* transform: a deterministic function that maps a placeholder to an answer kind and a canonical option set (if enumerated).
* binding: the act of associating a placeholder with an existing question and applying the transform’s declared answer model to that question.

## user journeys

1. explore and decide

* user selects a detected placeholder in the UI.
* UI calls transform suggestion API to preview proposed answer kind and options.
* user picks a transform from suggestions.

2. bind

* UI submits placeholder payload, selected transform id, and question id to binding API with Idempotency-Key and If-Match for the question.
* backend creates a placeholder bound to the question and asserts model consistency.
* backend applies or verifies the question’s answer kind and options.
* backend returns the updated question model and a binding receipt.

3. inspect

* user lists bound placeholders for a question for the current document only.

### transform suggestions

This section provides conceptual and behavioural context for the transform suggestion process rather than endpoint specifications, which are detailed separately in *Epic D – API Endpoints*.

The transform suggestion flow describes how the frontend, backend, and database coordinate when a user inspects and binds placeholders. It focuses on why these APIs exist and how they fit together, rather than on the API payloads themselves.

#### conceptual overview

1. **Initiation** – When a user selects a placeholder in the editor, the frontend sends a request to the backend to analyse the placeholder’s content and context. This is achieved through the `POST /api/v1/transforms/suggest` endpoint.
2. **Backend analysis** – The backend tokenises and interprets the placeholder text, applies deterministic rules, and proposes the most likely `answer_kind` and any associated `options`.
3. **Response** – The backend responds with a `TransformSuggestion` that includes an encapsulated `PlaceholderProbe` object containing both client-supplied and backend-derived data. This object holds all contextual metadata needed to bind the placeholder later, ensuring the frontend does not need to perform additional lookups.

#### placeholderprobe schema

The `PlaceholderProbe` represents the contextual and structural information of a placeholder during both suggestion and binding stages.

| Field Type Direction Description |                                         |                 |                                                                                                                    |
| -------------------------------- | --------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------ |
| `raw_text`                       | string                                  | client → server | The literal placeholder text extracted from the document.                                                          |
| `context.document_id`            | uuid                                    | both            | The unique document the placeholder originates from.                                                               |
| `context.clause_path`            | string                                  | both            | The hierarchical path to the clause or section within the document.                                                |
| `context.span`                   | object `{ start: number, end: number }` | both            | Character indices marking the placeholder’s position in the source document.                                       |
| `context.doc_etag`               | string                                  | both            | Optional checksum used to verify the document’s version.                                                           |
| `resolved_span`                  | object `{ start: number, end: number }` | server → client | The normalised span validated by the backend.                                                                      |
| `placeholder_key`                | string                                  | server → client | Parsed identifier from within the placeholder text (e.g., `POSITION` from `[POSITION]`).                           |
| `probe_hash`                     | string                                  | server → client | A hash of key attributes (document ID, clause path, resolved span, and raw text) used to verify binding integrity. |

The same object is used in both suggestion and binding calls. During **suggest**, only the client fields are populated. During **bind**, the server fields returned in the suggestion response (`resolved_span`, `placeholder_key`, `probe_hash`) must be echoed back for validation.

#### design intent

* The `PlaceholderProbe` encapsulates both client-provided and server-derived information in one reusable object, ensuring consistency and reducing duplication between `/transforms/suggest` and `/placeholders/bind`.
* The `probe_hash` ensures that the binding step references exactly the same placeholder instance analysed earlier.
* Because the backend returns a validated `resolved_span`, the frontend never has to re-identify placeholder positions.
* The approach supports idempotent bindings and accurate nested placeholder resolution.

This conceptual model provides the logical basis for the concrete API endpoints described in *Epic D – API Endpoints*. It defines what data moves between systems and why, ensuring consistency across the entire placeholder lifecycle.

## transforms

### detection rules & precedence (backend)

* tokenisation (minimal):

  * bracketed segments → placeholder_token (e.g. [POSITION])
  * the word OR (case-insensitive) between tokens → or_operator
  * remaining non-bracket text → literal_token

* deterministic rules (first match wins):

  1. single placeholder_token only → short_string
  2. exactly one literal_token + one placeholder_token separated by OR → enum_single with options: { LITERAL_VALUE, PLACEHOLDER_KEY }
  3. one or more literal_tokens separated by OR (no placeholders) → enum_single with canonicalised values
  4. binary control placeholders expressing "Yes/No", "True/False", or similar toggles that determine conditional inclusion of surrounding or following text → boolean

     * Used to decide whether a clause is displayed, not to capture a visible Yes/No answer.
  5. numeric pattern present (digits, currency, units) and not matched above → number
  6. otherwise if length/linebreak heuristic exceeded → long_text

* canonicalisation:

  * literals are mapped to UPPER_SNAKE_CASE `value` while preserving the original literal text as `label`
  * nested placeholder option uses `value = PLACEHOLDER_KEY` and carries `placeholder_key`
  * example: `[Yes]` directly preceding a clause block → boolean (controls clause visibility).
  * example: "Manager OR [POSITION]" → enum_single with `HR_MANAGER` and `POSITION`. & precedence (backend)

* tokenisation (minimal):

  * bracketed segments → placeholder_token (e.g. [POSITION])
  * the word OR (case-insensitive) between tokens → or_operator
  * remaining non-bracket text → literal_token

* deterministic rules (first match wins):

  1. single placeholder_token only → short_string
  2. exactly one literal_token + one placeholder_token separated by OR → enum_single with options: { LITERAL_VALUE, PLACEHOLDER_KEY }
  3. one or more literal_tokens separated by OR (no placeholders) → enum_single with canonicalised values
  4. boolean synonyms only (yes/no) → boolean
  5. numeric pattern present (digits, currency, units) and not matched above → number
  6. otherwise if length/linebreak heuristic exceeded → long_text

* canonicalisation:

  * literals are mapped to UPPER_SNAKE_CASE `value` plus friendly `label`
  * nested placeholder option uses `value = PLACEHOLDER_KEY` and carries `placeholder_key`

* rationale (optional): template strings aligned to the rule fired, e.g. "Detected literal–placeholder OR pattern (2 options)."

## Transform Types

### short_string

purpose

* free text placeholders like [POSITION], [DETAILS].

suggestion

* return answer_kind short_string with high confidence based on backend tokenisation of raw_text.
* include rationale: single token free text.

binding behaviour

* store no options.
* answer validation: max length and optional regex rules defined server-side or per policy.

examples

* "The HR Manager OR [POSITION]" pairs with enum_single option POSITION when used in a mixed case.

### long_text

purpose

* multi sentence fields such as incident descriptions.

suggestion

* return answer_kind long_text when backend analysis of raw_text indicates multi-line content or long-form free text.

binding behaviour

* store no options.
* answer validation: length thresholds only.

### boolean

purpose

* Used to control whether a body of text or policy clause is included or hidden, based on a yes/true answer.

suggestion

* Return `answer_kind: boolean` when the placeholder represents a binary condition controlling the visibility of a clause or text block (e.g., `[Yes]` or `[No]`). The UI treats this as a toggle for inclusion, not as a displayed Yes/No answer.

binding behaviour

* No options are stored.
* When the answer is true, dependent text blocks are included in generated documents; when false, they are omitted.
* Validation: coerce common synonyms (yes/y, true/✓) at import; the UI enforces strict toggle semantics.

### number

purpose

* numeric entries such as counts, percentages, or monetary amounts.

suggestion

* return answer_kind number when backend tokenisation detects numeric patterns (digits, units, currency symbols) in raw_text.

binding behaviour

* store no options.
* validation: integer or decimal as hinted; optional min and max; optional unit recorded separately as metadata.

### enum_single

purpose

Finite choice from literals or mixed literal + short text placeholder.

## Binding Suggestion

This phase corresponds to the `POST /api/v1/transforms/suggest` endpoint defined in *Epic D – API Endpoints*. It is triggered when the user selects a placeholder in the editor and the system analyses it to propose the most appropriate answer kind and options before any binding occurs. APIs that take a placeholder payload and return a proposed answer kind and options.

Pure literal list: return enum_single with canonical value tokens and friendly labels.

Friendly labels always use the original literal text (e.g., “The HR Manager”) even though canonical values are upper-snake (e.g., `HR_MANAGER`). Labels use the original literal text from the document; user edits may override but do not affect the canonical `value`.

Mixed literal + short text placeholder: return enum_single with two options, one for the literal and one whose value equals the nested placeholder key (e.g. POSITION). Do not require that the nested placeholder is already bound.

## Placeholder Binding 

This phase occurs when the user decides to actually bind a placeholder to a question. It corresponds to the `POST /api/v1/placeholders/bind` endpoint defined in *Epic D – API Endpoints*. The frontend sends the selected transform, placeholder probe data, and target question ID to this endpoint so the backend can validate and persist the binding.

Insert missing AnswerOption rows with canonical values; ensure uniqueness by value.

For options that represent nested placeholders:

Persist the parent placeholder against its question as normal.

Set option.value to the nested placeholder key (e.g. POSITION) and store option.placeholder_key = "POSITION".

If the nested placeholder is already bound, also set option.placeholder_id = <nested Placeholder.id>.

If the nested placeholder is not yet bound, leave option.placeholder_id null; the link will be back-filled later.

Retrospective linking (no user action required): whenever any placeholder is bound, the backend checks same-document, clause, and span containment; if the newly bound placeholder sits inside a previously saved parent placeholder, update the matching parent option to populate placeholder_id (canonical value remains unchanged).

behavioural

* option canonicalisation preserves values and stable ordering.
* on document replacement or deletion, remove the affected placeholders; if a question ends up with zero bound placeholders, clear its answer_kind and remove all canonical AnswerOption rows. if one or more placeholders remain, the model is retained only if all remaining bindings agree on answer_kind and option set; otherwise surface a conflict that requires re-binding.
* when the last placeholder is unbound from a question, the system clears the question’s answer_kind and removes all canonical AnswerOption rows for that question.
* unbind operations update the question etag.

## integration with epic c and b

* epic c supplies parsed placeholder payloads to the UI; no storage until binding.
* epic c also emits document lifecycle events that epic d consumes for cleanup.
* epic b provides questionnaires and answers; epic d updates question model and options via binding.

## operational rule for document deletion

* a document replacement event clears all bound placeholders for that document. after removal, if any question has zero remaining bound placeholders, its answer_kind and AnswerOption set are cleared. if a question retains one or more placeholders, keep the model if one or more placeholders remain.

## cleanup on document deletion

trigger

* when epic c deletes a document, epic d must remove all placeholders bound to that document.

behaviour

* delete placeholder rows for that document id. for each affected question: if zero bound placeholders remain, clear answer_kind and delete all AnswerOption rows; if one or more placeholders remain, keep the model only if they agree; otherwise surface a conflict and require re-binding.
* cleanup is idempotent. repeated delete events for the same document have no effect.

api and events

* epic c calls an internal endpoint: POST /documents/{document_id}/bindings:purge or publishes a domain event document.deleted that epic d subscribes to.
* response includes count of deleted placeholders for observability.

data model

* placeholder has document_id uuid not null with fk to documents(id) and on delete cascade.

acceptance criteria

* given a document is deleted, when cleanup runs, then all placeholders for that document are removed; for any question with no remaining bound placeholders, the question’s answer_kind and AnswerOption rows are cleared.
* given a document is replaced, when cleanup runs, then placeholders are removed; for questions left with zero placeholders, clear the model; for questions with remaining placeholders that disagree, surface a conflict requiring re-binding.
* given cleanup runs twice for the same document, then the second run deletes zero ro


# api endpoints for epic d – placeholders, bindings and transforms

## transform suggestion (stateless)

**POST ****`/api/v1/transforms/suggest`**
Propose the single best transform for an isolated placeholder (no persistence).

* **Headers**

  * `Content-Type: application/json`

* **Body**

  * `PlaceholderProbe`:

    * `raw_text: string` (required)
    * `context: {`

      * `document_id: uuid` (required)
      * `clause_path: string` (required)
      * `span?: { start: number, end: number }` (optional; FE passes selection if known)
      * `doc_etag?: string` (optional; for drift detection)
      * `}`

* **Response 200**

  * `TransformSuggestion`:

    * `transform_id: string`
    * `name: string`
    * `answer_kind: "short_string" | "long_text" | "boolean" | "number" | "enum_single"`
    * `options?: OptionSpec[]` (only for `enum_single`)

      * `OptionSpec`: `{ value: string, label?: string, placeholder_key?: string, placeholder_id?: uuid }`
    * `confidence: number` (0..1)
    * `probe: ProbeReceipt` (encapsulates resolved_span, placeholder_key, doc_etag if present, and probe_hash)

* **ProbeReceipt**

  * `{ document_id: uuid, clause_path: string, resolved_span: { start: number, end: number }, placeholder_key?: string, doc_etag?: string, probe_hash: string }`

* **Errors**

  * 400 invalid payload
  * 422 unrecognised pattern (no viable transform)
  * 500 internal

Notes:

* Returns a **single** top candidate only.
* `label` preserves the original literal text (when present); `value` is canonical (UPPER_SNAKE_CASE or placeholder key).
* FE can directly reuse `probe.resolved_span` and `probe.placeholder_key` for bind; no re-lookup needed.

---

**POST ****`/api/v1/placeholders/unbind`**
Remove a bound placeholder from a question.

* **Headers**

  * `Content-Type: application/json`
  * `If-Match: <question-etag>` (required)

* **Body**

  * `placeholder_id: uuid` (required)

* **Processing**

  * Deletes the placeholder.
  * If zero placeholders remain: clear the question’s `answer_kind` and remove all canonical `AnswerOption`s.
  * If one or more remain: keep model as-is.

* **Response 200**

  * `{ ok: true, question_id, etag }`

* **Errors**

  * 404 not found
  * 412 precondition failed (If-Match mismatch)
  * 500 internal

---

## read/list

**GET ****`/api/v1/questions/{question_id}/placeholders`**
List bound placeholders for a question, optionally filtered by document.

* **Query params**

  * `document_id?: uuid`

* **Response 200**

  * `{ items: Placeholder[], etag?: string }`

    * `Placeholder`: `{ id, document_id, clause_path, text_span {start,end}, question_id, transform_id, payload_json, created_at }`

* **Errors**

  * 404 question not found
  * 500 internal

---

## cleanup (document lifecycle)

**POST ****`/api/v1/documents/{document_id}/bindings:purge`**  *(internal or event-driven)*
Remove all placeholders bound to a deleted document and tidy dependent questions.

* **Headers**

  * `Content-Type: application/json`

* **Body**

  * `{ reason?: "deleted" }` (optional)

* **Processing**

  * Delete all placeholders for `document_id`.
  * For each affected question:

    * If zero remain: clear `answer_kind` and delete canonical `AnswerOption`s.
    * If ≥1 remain: retain model.

* **Response 200**

  * `{ deleted_placeholders: number, updated_questions: number, etag?: string }`

* **Errors**

  * 404 document not found (optional; or treat as idempotent no-op)
  * 500 internal

Notes: this may also be triggered asynchronously via a `document.deleted` event.

---

## Helpers

**GET ****`/api/v1/transforms/catalog`**
List supported transforms and their capabilities (for front-end and QA use).

* **Response 200**

  * `{ items: [{ transform_id, name, answer_kind, supports_options: boolean, notes?: string }] }`

**POST ****`/api/v1/transforms/preview`**
Preview how a transform canonicalises literal lists without binding (for dev tooling).

* **Body**

  * `{ raw_text: string }` or `{ literals: string[] }`

* **Response 200**

  * `{ answer_kind, options?: OptionSpec[] }`

---

## cross-cutting conventions

* **Auth**: none (no authentication required at this time).
* **Content types**: `application/json` for payloads; `application/problem+json` for errors.
* **Idempotency**: `/bind` supports `Idempotency-Key`; identical payload + key = same result.
* **Concurrency**: write endpoints require `If-Match` with current question ETag.
* **Validation**:

  * `answer_kind ∈ { short_string, long_text, boolean, number, enum_single }`
  * `OptionSpec.value` canonical; `OptionSpec.label` preserves original literal text.
* **Nested linkage**:

  * For `enum_single`, an option representing a nested placeholder stores `placeholder_key` immediately; `placeholder_id` is populated when/if that child placeholder is later bound.
* **Errors (common)**:

  * 400 invalid payload
  * 401/403 auth/permission
  * 404 missing resource
  * 409 model conflict (bind)
  * 412 precondition failed (ETag)
  * 422 unprocessable (bad transform)
  * 429 rate limit
  * 500 internal

## 1. Scope

### 1.1 Purpose

Enable editors to analyse, transform, and bind placeholders from uploaded documents to existing questionnaire questions. This ensures consistent answer models across documents while keeping transforms and bindings logically separate.

### 1.2 Inclusions

* Suggest the most appropriate transform for an isolated placeholder via `/api/v1/transforms/suggest`.
* Bind placeholders to existing questions through `/api/v1/placeholders/bind`, enforcing answer model consistency.
* Unbind placeholders using `/api/v1/placeholders/unbind`, clearing question models when no bindings remain.
* List placeholders bound to a question using `/api/v1/questions/{id}/placeholders`.
* Automatically clean up placeholder bindings when a document is deleted through `/api/v1/documents/{id}/bindings:purge`.
* Support idempotency, version checks, and nested placeholder linking.

### 1.3 Exclusions

* Document ingestion and placeholder extraction (handled by Epic C).
* Questionnaire CRUD, base validation, and answer persistence (handled by Epic B).
* Conditional visibility logic (Epic I) and document generation.
* Any user authentication or permission enforcement.

### 1.4 Context

Epic D forms the bridge between document parsing (Epic C) and questionnaire management (Epic B). It defines how placeholders identified in parsed documents are transformed and persistently bound to the correct question models. It interacts with the backend through stateless APIs and event-driven cleanup, ensuring a unified and consistent placeholder lifecycle across the system.

## 2.2 EARS Functionality

---

### 2.2.1 Ubiquitous requirements

* **U1** The system will accept a `PlaceholderProbe` containing document, clause, and span context from the frontend.
* **U2** The system will tokenise and analyse the placeholder text to determine the most probable `answer_kind`.
* **U3** The system will apply deterministic transform rules to map the placeholder into one of the supported answer kinds: short_string, long_text, boolean, number, or enum_single.
* **U4** The system will return a single `TransformSuggestion` with canonicalised options.
* **U5** The system will generate and return a `probe_hash` to guarantee idempotence between suggest and bind operations.
* **U6** The system will persist a placeholder only when it is explicitly bound to a question.
* **U7** The system will enforce answer model consistency by preventing changes to `answer_kind` or option sets once a question has existing bindings.
* **U8** The system will ensure idempotent operations by using `Idempotency-Key` headers.
* **U9** The system will provide APIs to bind, read, list, unbind, and purge placeholder bindings.
* **U10** The system will ensure canonicalisation of literal values and preservation of original labels for user-facing text.

---

### 2.2.2 Event-driven requirements

* **E1** When the user selects a placeholder in the editor, the system will call the transform suggestion endpoint and return a transform proposal.
* **E2** When the user confirms a transform selection and binds it to a question, the system will validate the binding against existing models and persist the placeholder.
* **E3** When a placeholder is bound to a question that has no existing bindings, the system will set the question’s `answer_kind` and canonical `AnswerOption` set from the transform definition.
* **E4** When a placeholder is bound to a question that already has `answer_kind` and canonical `AnswerOption` set, the system will verify the transform matches the existing model and will not modify the model.
* **E5** When a placeholder being bound is located within the span of an already-bound parent placeholder, the system will update the parent’s corresponding option so that its `placeholder_id` points to the newly bound child.
* **E6** When a document is deleted, the system will remove all placeholders associated with that document.
* **E7** When a document deletion event is processed multiple times, the system will perform no additional deletions beyond the first (idempotent cleanup).
* **E8** When a question’s last placeholder is unbound, the system will clear the question’s `answer_kind` and remove associated options.
* **E9** When the user requests to unbind a specific placeholder, the system will delete that placeholder record.
* **E10** When the client requests the transforms catalog, the system will return the list of supported transforms with their capabilities.
* **E11** When the client submits a transforms preview request, the system will return the previewed `answer_kind` and canonicalised options without persisting anything.
* **E12** When bindings for a document are purged, the system will clear a question’s `answer_kind` and delete its canonical `AnswerOption` set where the question has zero remaining placeholders.
* **E13** When processing a bind request, the system will verify that the supplied `probe_hash` matches the original suggestion context before persisting.
* **E14** When the client requests the list of placeholders for a question, the system will return the list and the current question ETag.

---

### 2.2.3 State-driven requirements

* **S1** While a question has at least one bound placeholder, the system will retain its answer model provided all bindings agree on `answer_kind` and option set.
* **S2** While placeholders remain bound to a question, the system will prevent conflicting bindings that would introduce inconsistent models.
* **S3** While a document exists, the system will maintain placeholder references through the document ID and clause path.

---

### 2.2.4 Optional-feature requirements

* **O1** Where the placeholder contains both literals and a nested placeholder, the system will generate an `enum_single` transform containing both canonicalised literal values and a nested placeholder key option.
* **O2** Where a placeholder expresses binary inclusion or exclusion (e.g., `[Yes]`, `[No]`), the system will produce a `boolean` transform controlling clause visibility instead of a Yes/No answer.
* **O3** Where numeric patterns are detected, the system will return a `number` transform with validation metadata (e.g., min/max, units).
* **O4** Where an `enum_single` option represents a nested placeholder without a `placeholder_id`, the system will expose the canonical token as the display label until the child is bound.

---

### 2.2.5 Unwanted-behaviour requirements

* **N1** If a binding request would alter an existing question’s `answer_kind` or option set, the system will reject the operation with a model conflict error.
* **N2** If an unrecognised placeholder format is submitted, the system will return a 422 unprocessable error.
* **N3** If a binding or unbinding request references a document or question that no longer exists, the system will return a 404 error.
* **N4** If a placeholder is bound twice with identical data, the system will treat the request as idempotent and not create duplicates.
* **N5** If a placeholder probe hash does not match the original suggestion, the system will reject the binding to prevent mismatched context.
* **N6** If an unbind request fails the `If-Match` precondition, the system will return a 412 precondition failed error.
* **N7** If a transforms preview request contains an invalid payload, the system will return a 400 invalid payload error.
* **N8** If a bind request fails the `If-Match` precondition, the system will return a 412 precondition failed error.
* **N9** If a transform suggestion request contains an invalid payload, the system will return a 400 invalid payload error.

---

### 2.2.6 Step Index

* **STEP-1** Explore and decide → U1, U2, U3, U4, U5, E1, E10, E11, O1, O2, O3, N2, N7, N9
* **STEP-2** Bind → U6, U7, U8, U9, U10, E2, E3, E4, E5, E13, N1, N3, N4, N5, N8
* **STEP-3** Inspect → U9, S1, S2, S3, E9, E14, O4, N6
* **STEP-4** Cleanup on document deletion → U9, E6, E7, E12, S3, N3


# Deterministic Transform Logic

## 1) Goals & scope

* Convert an **isolated placeholder selection** from the editor into exactly one `answer_kind` with a stable option model (if applicable).
* Ensure **stable canonical values** (UPPER_SNAKE_CASE), while **preserving original literal text as labels**.
* Support **nested placeholder** options by using `placeholder_key` immediately and back-filling `placeholder_id` after the child is bound.
* Produce **one** best suggestion deterministically for the same input (`raw_text` + context).

---

## 2) Tokenisation & normalisation (deterministic)

Given `raw_text` of the isolated selection:

1. **Trim & collapse** spaces; preserve original whitespace for labels.
2. **Bracket extraction**: `[TOKEN]` → `placeholder_token` with `placeholder_key = TOKEN` (strip surrounding brackets only; do not alter case for label).
3. **Literal segments**: any non-placeholder text becomes `literal_token` segments.
4. **List separators**:

   * `OR`, `or`, `Or`, commas with a final `or` → split into alternatives.
   * `AND/OR`, `and/or` → treat as **OR** (single-choice model; see §5.3).
5. **Punctuation in literals**: retain for the **label**; canonical **value** is derived by:

   * lowercasing, removing non-alphanumerics except spaces and hyphens, collapsing spaces, then upper-snake (`"The HR Manager"` → `HR_MANAGER`; `"board of directors (the Board)"` → `BOARD_OF_DIRECTORS`).
6. **Length heuristics** (for short vs long text):

   * **Short text (`short_string`)**: must contain *no line breaks* and fewer than ~120 characters after normalisation.
   * **Long text (`long_text`)**: any placeholder with one or more line breaks, or ≥120 characters after normalisation, and no list structure.

---

## 3) Classification precedence (first match wins)

1. **Mixed list (literal + placeholder)** → `enum_single` with:

   * one option per literal alternative;
   * one option whose `value = placeholder_key` and `placeholder_key` recorded.
2. **Pure literal finite list (2+ alternatives)** → `enum_single` with canonicalised literal options.
3. **Pure placeholder (single)** → `short_string` (free-text answer captured separately).
4. **Boolean inclusion** (single bracketed clause containing a body of text with no `OR` separators) → `boolean` controlling inclusion or omission of that text based on the question’s answer.
5. **Numeric capture** (explicit `[NUMBER]` or digit patterns with units) → `number` (no options).
6. **Free text (no list; under/over length threshold)** → `short_string` / `long_text` per §2.6.
7. **Otherwise** → reject as unrecognised (422).

---

## 4) Canonicalisation rules

* **Option values**

  * Literals → UPPER_SNAKE_CASE (stable identifiers).
  * Placeholder-backed options → `value = placeholder_key` (stable and linkable).
* **Option labels**

  * **Always** the original literal segment as seen in the document (punctuation/case preserved).
  * For placeholder-backed options where the child is **not yet bound**, display the **canonical token** (the `value`).
* **Uniqueness**

  * De-duplicate by `value`. If collision, keep first occurrence; subsequent duplicates are ignored at bind.

---

## 5) Pattern catalogue (exhaustive constructions)

### 5.1 Mixed literal + placeholder (two-way)

* **Source**: `[The HR Manager OR [POSITION]]`
* **Kind**: `enum_single`
* **Options**:

  * `{ value: HR_MANAGER, label: "The HR Manager" }`
  * `{ value: POSITION, placeholder_key: "POSITION" }`

### 5.2 Mixed literal + placeholder (N-way)

* **Source**: `[The Human Resources Department OR [DEPARTMENT] OR [POSITION]]`
* **Kind**: `enum_single`
* **Options**:

  * `HUMAN_RESOURCES_DEPARTMENT` (label preserved)
  * `DEPARTMENT` (placeholder_key)
  * `POSITION` (placeholder_key)

### 5.3 AND/OR normalisation

* **Source**: `[your line manager AND/OR the Human Resources Department OR [POSITION]]`
* **Rule**: Normalise `AND/OR` to **OR** for **single-choice** (`enum_single`) models.
* **Kind**: `enum_single`
* **Options**: `YOUR_LINE_MANAGER`, `HUMAN_RESOURCES_DEPARTMENT`, `POSITION`.

### 5.4 Pure literal list (2+)

* **Source**: `[each year OR regularly]`
* **Kind**: `enum_single`
* **Options**: `EACH_YEAR`, `REGULARLY`.

### 5.5 Literal list with commas + final OR

* **Source**: `[regular OR quarterly OR annual]` or `[A, B or C]`
* **Kind**: `enum_single`
* **Options**: `REGULAR`, `QUARTERLY`, `ANNUAL` (comma segments are split, trimmed, canonicalised).

### 5.6 Literal with parenthetical gloss

* **Source**: `[board of directors (the Board) OR [COMMITTEE]]`
* **Kind**: `enum_single`
* **Options**:

  * `BOARD_OF_DIRECTORS` (label retains “board of directors (the Board)”)
  * `COMMITTEE` (placeholder_key)

### 5.7 Placeholder-only

* **Source**: `[POSITION]`, `[DEPARTMENT]`, `[DETAILS]`
* **Kind**: `short_string` (unless long-text heuristics trigger `long_text`)
* **Options**: none.

### 5.8 Numeric capture

* **Source**: `within [NUMBER] days` or a bracketed digit segment `[28]` adjacent to a unit
* **Kind**: `number`
* **Options**: none.
* **Metadata (if derivable)**: `unit = "days"`; optional `min/max` if present in context.

### 5.9 Boolean inclusion

* **Source pattern:** a **single bracketed clause** containing a **body of text** (no `OR` separators) — for example:
  `[Employees must not share confidential information with unauthorised persons.]`
* **Rule:** treat the entire bracketed text as a **conditional clause** that is **included only if the associated question’s answer is `true`**.
* **Kind:** `boolean`
* **Semantics:**

  * `true` → include the clause or text block in the rendered or generated output.
  * `false` → omit the clause or text block entirely.
* **Detection conditions:**

  * Bracketed text contains one contiguous phrase or sentence with **no list delimiters** (`OR`, `AND/OR`, commas separating alternatives).
  * Text length exceeds the short-text threshold (i.e. represents meaningful policy content rather than a placeholder token).
* **Options:** none.
* **Purpose:** used to conditionally reveal or hide large text segments (e.g. policy statements, disclaimers, or exceptions) rather than to display “Yes/No” values.

### 5.10 Long free text

* **Source:** a **single bracketed sentence or clause** indicating a large, descriptive text area — for example:
  `[GENERAL DETAILS ABOUT THE EMPLOYER AND ITS BUSINESS.]`
* **Kind:** `long_text` (line break present or ≥120 characters after normalisation, or recognised as an editorial instruction rather than a short token).
* **Options:** none.
* **Purpose:** to capture extended narrative answers where the user will provide freeform content rather than a short factual value.

---

## 6) Nested placeholder linkage (parent↔child)

* If an option in a parent `enum_single` represents a **nested placeholder** (via `placeholder_key`) and the child is later bound, the system **back-fills** the parent option’s `placeholder_id` (value remains the placeholder key).
* If the child is **not yet bound**, the parent option shows the canonical token (`value`) as its label at runtime.

---

## 7) Determinism & idempotence

* The suggestion result is a **pure function** of `(raw_text, document_id, clause_path, resolved_span)`; identical inputs must yield identical `answer_kind`, options, and tokens.
* A `probe_hash` of these inputs is produced at suggest and must be echoed at bind for verification.

---

## 8) Failure taxonomy (exhaustive)

* **Unrecognised or malformed selection** → 422.
* **Empty enum option set after parsing** → 422.
* **Conflicting bind (would change `answer_kind` or option set)** → 409.
* **ETag/If-Match failure** on bind/unbind → 412.
* **Hash/context mismatch** between suggest and bind → 409/422 (per API).
* **Numeric parse failure** (e.g., non-numeric where `number` inferred) → 422.

---

## 9) Worked examples (from the template)

| Source text (excerpt)                                                            | Outcome                                                                       |
| -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `[The HR Manager OR [POSITION]]`                                                 | `enum_single` → `HR_MANAGER`, `POSITION` (placeholder_key)                    |
| `[on the intranet OR [DETAILS]]`                                                 | `enum_single` → `INTRANET`, `DETAILS` (placeholder_key)                       |
| `[your line manager AND/OR the Human Resources Department OR [POSITION]]`        | `enum_single` → `YOUR_LINE_MANAGER`, `HUMAN_RESOURCES_DEPARTMENT`, `POSITION` |
| `[each year OR regularly]`                                                       | `enum_single` → `EACH_YEAR`, `REGULARLY`                                      |
| `[board of directors (the Board) OR [COMMITTEE]]`                                | `enum_single` → `BOARD_OF_DIRECTORS`, `COMMITTEE` (placeholder_key)           |
| `[POSITION]`                                                                     | `short_string`                                                                |
| `within [NUMBER] days`                                                           | `number` (+ unit `days`)                                                      |
| `[Employees must not share confidential information with unauthorised persons.]` | `boolean` (include text when true)                                            |
| `[GENERAL DETAILS ABOUT THE EMPLOYER AND ITS BUSINESS.]`                         | `long_text` (freeform descriptive input)                                      |

| Field                                     | Description                                                                     | Type          | Schema / Reference                                           | Notes                                                                                         | Pre-Conditions                                                                                                                                                                    | Origin   |
| ----------------------------------------- | ------------------------------------------------------------------------------- | ------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| Idempotency-Key                           | Idempotency key header for safe retries on bind.                                | string        | schemas/HttpHeaders.json#/properties/Idempotency-Key         | Used only with POST /api/v1/placeholders/bind.                                                | Field is required and must be provided for idempotent bind; Value must be a non-empty opaque string; Value must be reused verbatim on safe retries.                               | provided |
| If-Match                                  | Concurrency control header carrying the current question ETag.                  | string        | schemas/HttpHeaders.json#/properties/If-Match                | Used with POST /api/v1/placeholders/bind and POST /api/v1/placeholders/unbind.                | Field is required and must be provided for write operations; Value must be a non-empty opaque string; Value must equal the latest ETag for the target question.                   | provided |
| question_id                               | Target question identifier (path or body depending on endpoint).                | string (uuid) | schemas/BindRequest.json#/properties/question_id             | Used by bind and list endpoints.                                                              | Field is required and must be provided; Value must be a well-formed UUID string; Reference must resolve to an existing question.                                                  | provided |
| transform_id                              | Selected transform identifier to apply at bind.                                 | string        | schemas/BindRequest.json#/properties/transform_id            | Sourced from the transforms catalog or suggest output.                                        | Field is required and must be provided; Value must reference a known transform; Reference must resolve to an enabled transform.                                                   | provided |
| apply_mode                                | Bind execution mode.                                                            | string (enum) | schemas/BindRequest.json#/properties/apply_mode              | Values: verify, apply.                                                                        | Field is optional; When provided, value must be either verify or apply; When omitted, default must be apply.                                                                      | provided |
| option_labelling                          | Option labelling mode for enum_single upserts.                                  | string (enum) | schemas/BindRequest.json#/properties/option_labelling        | Values: value, value_label.                                                                   | Field is optional; When provided, value must be either value or value_label.                                                                                                      | provided |
| probe_hash                                | Hash verifying the suggest→bind continuity when sending PlaceholderProbe.       | string        | schemas/BindRequest.json#/properties/probe_hash              | Alternative to sending a ProbeReceipt object.                                                 | Field is optional but must be provided when probe is not provided; Value must equal the hash returned by suggest for the same span and context; Value must be a non-empty string. | provided |
| placeholder                               | PlaceholderProbe object supplied to bind (one variant).                         | object        | schemas/PlaceholderProbe.json                                | Use either (placeholder + probe_hash) or (probe).                                             | Field is optional but must be provided when probe is not provided; Object must match the referenced schema.                                                                       | provided |
| placeholder.raw_text                      | Exact isolated placeholder text selected in the editor.                         | string        | schemas/PlaceholderProbe.json#/properties/raw_text           | None.                                                                                         | Field is required and must be provided; Value must be a non-empty string; Value must correspond to the resolved span characters.                                                  | provided |
| placeholder.context                       | Context object describing where the placeholder was selected.                   | object        | schemas/PlaceholderProbe.json#/properties/context            | None.                                                                                         | Field is required and must be provided; Object must match the referenced schema.                                                                                                  | provided |
| placeholder.context.document_id           | Document identifier containing the placeholder.                                 | string (uuid) | schemas/PlaceholderProbeContext.json#/properties/document_id | None.                                                                                         | Field is required and must be provided; Value must be a well-formed UUID string; Reference must resolve to an existing document.                                                  | provided |
| placeholder.context.clause_path           | Hierarchical path to the clause/section.                                        | string        | schemas/PlaceholderProbeContext.json#/properties/clause_path | Example: “1/3/2”.                                                                             | Field is required and must be provided; Value must be a non-empty string; Reference must resolve to a known clause path within the document.                                      | provided |
| placeholder.context.span                  | Character span of the selection in the source.                                  | object        | schemas/PlaceholderProbeContext.json#/properties/span        | Optional from FE; backend will resolve final span.                                            | Field is optional; When provided, object must match Span schema; Start must be an integer ≥ 0; End must be an integer ≥ Start.                                                    | provided |
| placeholder.context.doc_etag              | ETag of the document to detect drift.                                           | string        | schemas/PlaceholderProbeContext.json#/properties/doc_etag    | None.                                                                                         | Field is optional; When provided, value must be a non-empty string; Value must correspond to the document’s current version ETag.                                                 | provided |
| probe                                     | ProbeReceipt object returned by suggest and echoed to bind (alternate variant). | object        | schemas/ProbeReceipt.json                                    | Use either (probe) or (placeholder + probe_hash).                                             | Field is optional but must be provided when placeholder is not provided; Object must match the referenced schema; Object must originate from the suggest response.                | provided |
| probe.document_id                         | Document identifier captured at suggest time.                                   | string (uuid) | schemas/ProbeReceipt.json#/properties/document_id            | None.                                                                                         | Field is required and must be present; Value must be a well-formed UUID string; Value must match the intended bind target document.                                               | provided |
| probe.clause_path                         | Clause path captured at suggest time.                                           | string        | schemas/ProbeReceipt.json#/properties/clause_path            | None.                                                                                         | Field is required and must be present; Value must be a non-empty string; Value must match the intended bind target clause path.                                                   | provided |
| probe.resolved_span                       | Backend-validated span for the selection.                                       | object        | schemas/ProbeReceipt.json#/properties/resolved_span          | None.                                                                                         | Field is required and must be present; Object must match Span schema; Start must be an integer ≥ 0; End must be an integer ≥ Start.                                               | provided |
| probe.resolved_span.start                 | Start index of the validated span.                                              | integer       | schemas/Span.json#/properties/start                          | None.                                                                                         | Field is required and must be present; Value must be an integer ≥ 0.                                                                                                              | provided |
| probe.resolved_span.end                   | End index of the validated span.                                                | integer       | schemas/Span.json#/properties/end                            | None.                                                                                         | Field is required and must be present; Value must be an integer ≥ 0; Value must be ≥ start.                                                                                       | provided |
| probe.placeholder_key                     | Extracted key if the selection is a placeholder token.                          | string        | schemas/ProbeReceipt.json#/properties/placeholder_key        | None.                                                                                         | Field is optional; When provided, value must be a non-empty string; Value must equal the parsed token from the resolved span.                                                     | provided |
| probe.doc_etag                            | Document ETag captured at suggest time.                                         | string        | schemas/ProbeReceipt.json#/properties/doc_etag               | None.                                                                                         | Field is optional; When provided, value must be a non-empty string; Value must match the document’s version at suggest time.                                                      | provided |
| probe.probe_hash                          | Hash binding the selection and context across calls.                            | string        | schemas/ProbeReceipt.json#/properties/probe_hash             | None.                                                                                         | Field is required and must be present; Value must be a non-empty string; Value must equal the hash computed at suggest time.                                                      | provided |
| document_id                               | Document identifier used in list filter or purge path.                          | string (uuid) | schemas/PurgeRequest.json#/properties/reason                 | Used by GET /questions/{id}/placeholders?document_id and POST /documents/{id}/bindings:purge. | Field is required and must be provided when used as a path parameter; Value must be a well-formed UUID string; Reference must resolve to an existing document.                    | provided |
| reason                                    | Informational reason for purge.                                                 | string (enum) | schemas/PurgeRequest.json#/properties/reason                 | Allowed value: deleted.                                                                       | Field is optional; When provided, value must equal deleted.                                                                                                                       | provided |
| literals[]                                | Literal options to preview without parsing free text.                           | list[string]  | schemas/TransformsPreviewRequest.json#/properties/literals   | Mutually exclusive with raw_text.                                                             | Field is optional; When provided, list must contain at least one non-empty string; Exactly one of raw_text or literals must be provided.                                          | provided |
| raw_text                                  | Raw text to preview or suggest from.                                            | string        | schemas/TransformsPreviewRequest.json#/properties/raw_text   | Used by suggest and preview.                                                                  | Field is optional for preview and required for suggest; Value must be a non-empty string; Value must represent an isolated selection.                                             | provided |
| SuggestResponse.probe                     | ProbeReceipt returned by suggest for later bind.                                | object        | schemas/SuggestResponse.json#/properties/probe               | Provider: POST /api/v1/transforms/suggest.                                                    | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |
| SuggestResponse.probe.document_id         | Document identifier from suggest.                                               | string (uuid) | schemas/ProbeReceipt.json#/properties/document_id            | Provider: POST /api/v1/transforms/suggest.                                                    | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |
| SuggestResponse.probe.clause_path         | Clause path from suggest.                                                       | string        | schemas/ProbeReceipt.json#/properties/clause_path            | Provider: POST /api/v1/transforms/suggest.                                                    | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |
| SuggestResponse.probe.resolved_span.start | Start index from suggest.                                                       | integer       | schemas/Span.json#/properties/start                          | Provider: POST /api/v1/transforms/suggest.                                                    | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |
| SuggestResponse.probe.resolved_span.end   | End index from suggest.                                                         | integer       | schemas/Span.json#/properties/end                            | Provider: POST /api/v1/transforms/suggest.                                                    | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |
| SuggestResponse.probe.placeholder_key     | Placeholder key from suggest.                                                   | string        | schemas/ProbeReceipt.json#/properties/placeholder_key        | Provider: POST /api/v1/transforms/suggest.                                                    | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |
| SuggestResponse.probe.doc_etag            | Document ETag from suggest.                                                     | string        | schemas/ProbeReceipt.json#/properties/doc_etag               | Provider: POST /api/v1/transforms/suggest.                                                    | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |
| SuggestResponse.probe.probe_hash          | Probe hash from suggest.                                                        | string        | schemas/ProbeReceipt.json#/properties/probe_hash             | Provider: POST /api/v1/transforms/suggest.                                                    | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |
| BindResult.etag                           | New question ETag returned after bind.                                          | string        | schemas/BindResult.json#/properties/etag                     | Provider: POST /api/v1/placeholders/bind.                                                     | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |
| UnbindResponse.etag                       | New question ETag returned after unbind.                                        | string        | schemas/UnbindResponse.json#/properties/etag                 | Provider: POST /api/v1/placeholders/unbind.                                                   | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |
| ListPlaceholdersResponse.etag             | Current question ETag returned when listing placeholders.                       | string        | schemas/ListPlaceholdersResponse.json#/properties/etag       | Provider: GET /api/v1/questions/{id}/placeholders.                                            | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step.                                        | returned |

| Field                       | Description                                                                          | Type         | Schema / Reference                                       | Notes                                                                                            | Post-Conditions                                                                                                                                                                                                                       |
| --------------------------- | ------------------------------------------------------------------------------------ | ------------ | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| suggestion                  | Transform proposal for an isolated placeholder (suggest endpoint).                   | object       | schemas/SuggestResponse.json#/properties/suggestion      | Provider: POST /api/v1/transforms/suggest; conforms to `schemas/TransformSuggestion.json`.       | Field must be present on 200 from suggest; Object must validate against `TransformSuggestion.json`; Option values must be canonical and deterministic for identical probes.                                                           |
| probe                       | Probe receipt echoing resolved span and hash for bind continuity (suggest endpoint). | object       | schemas/SuggestResponse.json#/properties/probe           | Provider: POST /api/v1/transforms/suggest; conforms to `schemas/ProbeReceipt.json`.              | Field must be present on 200 from suggest; Object must validate against `ProbeReceipt.json`; `probe_hash` must be stable for identical inputs; `resolved_span` must match analysed selection.                                         |
| bind_result                 | Result of a successful bind operation.                                               | object       | schemas/BindResult.json                                  | Provider: POST /api/v1/placeholders/bind.                                                        | Object must validate against `BindResult.json`; `bound` must equal true; `etag` must be a new opaque value; `question_id` and `placeholder_id` must be valid UUID strings.                                                            |
| bind_result.bound           | Boolean flag indicating bind success.                                                | boolean      | schemas/BindResult.json#/properties/bound                | None.                                                                                            | Field must be present and equal true on successful bind; Value must be boolean.                                                                                                                                                       |
| bind_result.question_id     | Target question identifier.                                                          | string       | schemas/BindResult.json#/properties/question_id          | UUID.                                                                                            | Field must be present; Value must be a well-formed UUID string.                                                                                                                                                                       |
| bind_result.placeholder_id  | Newly persisted placeholder identifier.                                              | string       | schemas/BindResult.json#/properties/placeholder_id       | UUID.                                                                                            | Field must be present; Value must be a well-formed UUID string; Value must reference a persisted placeholder row.                                                                                                                     |
| bind_result.answer_kind     | Answer kind set/verified by bind.                                                    | string       | schemas/BindResult.json#/properties/answer_kind          | Enum defined in `schemas/AnswerKind.json`.                                                       | Field must be present; Value must be one of `short_string`, `long_text`, `boolean`, `number`, `enum_single`.                                                                                                                          |
| bind_result.options         | Canonical option set for enum_single (if applicable).                                | list[object] | schemas/BindResult.json#/properties/options              | Items conform to `schemas/OptionSpec.json`.                                                      | Field must be present only when `answer_kind = enum_single`; Array may be empty only if suggestion produced none (should normally be ≥1); Each item must validate against `OptionSpec.json`; Option values must be unique by `value`. |
| bind_result.etag            | New question ETag after bind.                                                        | string       | schemas/BindResult.json#/properties/etag                 | Opaque concurrency token.                                                                        | Field must be present; Value must be a non-empty string; Value must represent the latest state after bind.                                                                                                                            |
| unbind                      | Result of a successful unbind operation.                                             | object       | (projection)                                             | Provider: POST /api/v1/placeholders/unbind; projection `{ ok, question_id, etag }`.              | Object must contain keys `ok`, `question_id`, `etag`; `ok` must equal true; `question_id` must be a valid UUID; `etag` must be a non-empty string representing latest state.                                                          |
| placeholders                | List of placeholders bound to the question (list endpoint).                          | list[object] | schemas/ListPlaceholdersResponse.json#/properties/items  | Provider: GET /api/v1/questions/{id}/placeholders; items conform to `schemas/Placeholder.json`.  | Field must be present on 200 from list; Array may be empty; Each item must validate against `Placeholder.json`; Item order must be deterministic for identical inputs.                                                                |
| placeholders[].id           | Identifier of a persisted placeholder.                                               | string       | schemas/Placeholder.json#/properties/id                  | UUID.                                                                                            | Field must be present in each item; Value must be a well-formed UUID string; Value must uniquely identify a placeholder.                                                                                                              |
| placeholders[].document_id  | Identifier of the source document.                                                   | string       | schemas/Placeholder.json#/properties/document_id         | UUID.                                                                                            | Field must be present in each item; Value must be a well-formed UUID string.                                                                                                                                                          |
| placeholders[].clause_path  | Hierarchical clause path within the document.                                        | string       | schemas/Placeholder.json#/properties/clause_path         | None.                                                                                            | Field must be present in each item; Value must be a non-empty string following the agreed path convention.                                                                                                                            |
| placeholders[].text_span    | Start/end character positions of the placeholder.                                    | object       | schemas/Placeholder.json#/properties/text_span           | Conforms to `schemas/Span.json`.                                                                 | Field must be present in each item; Object must validate against `Span.json`; `start` must be ≥ 0; `end` must be ≥ `start`.                                                                                                           |
| placeholders[].question_id  | Question the placeholder is bound to.                                                | string       | schemas/Placeholder.json#/properties/question_id         | UUID.                                                                                            | Field must be present in each item; Value must be a well-formed UUID string.                                                                                                                                                          |
| placeholders[].transform_id | Identifier of the transform applied at bind.                                         | string       | schemas/Placeholder.json#/properties/transform_id        | None.                                                                                            | Field must be present in each item; Value must be a non-empty string.                                                                                                                                                                 |
| placeholders[].payload_json | Persisted transform payload details.                                                 | dict         | schemas/Placeholder.json#/properties/payload_json        | None.                                                                                            | Field may be present or omitted; When present, value must be valid JSON object.                                                                                                                                                       |
| placeholders[].created_at   | Creation timestamp for the placeholder row.                                          | string       | schemas/Placeholder.json#/properties/created_at          | RFC3339 date-time, UTC.                                                                          | Field must be present in each item; Value must be a valid RFC3339 date-time string; Value must represent UTC time.                                                                                                                    |
| list_etag                   | Current question ETag associated with the listing response.                          | string       | schemas/ListPlaceholdersResponse.json#/properties/etag   | None.                                                                                            | Field must be present when returned; Value must be a non-empty string representing the current model state at list time.                                                                                                              |
| purge_result                | Summary of placeholders cleanup for a document.                                      | object       | schemas/PurgeResponse.json                               | Provider: POST /api/v1/documents/{id}/bindings:purge.                                            | Object must validate against `PurgeResponse.json`; `deleted_placeholders` must be an integer ≥ 0; `updated_questions` must be an integer ≥ 0; `etag` may be present and must be a non-empty string when emitted.                      |
| catalog                     | Supported transforms catalog.                                                        | list[object] | schemas/TransformsCatalogResponse.json#/properties/items | Provider: GET /api/v1/transforms/catalog; items conform to `schemas/TransformsCatalogItem.json`. | Field must be present on 200 from catalog; Array may be empty; Each item must validate against `TransformsCatalogItem.json`; Item order must be deterministic for identical inputs.                                                   |
| preview                     | Preview of how a transform would canonicalise options without binding.               | object       | schemas/TransformsPreviewResponse.json                   | Provider: POST /api/v1/transforms/preview.                                                       | Object must validate against `TransformsPreviewResponse.json`; `answer_kind` must be one of the declared enum values; `options` must be present only for `enum_single`.                                                               |
| problem                     | Problem Details object for error responses.                                          | object       | schemas/ProblemDetails.json                              | Returned on non-2xx responses across endpoints.                                                  | Object must validate against `ProblemDetails.json`; `status` must be an HTTP status code; `type` and `title` must describe the error condition.                                                                                       |

| Error Code                                           | Field Reference                           | Description                                                                   | Likely Cause                                     | Flow Impact   | Behavioural AC Required |
| ---------------------------------------------------- | ----------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------ | ------------- | ----------------------- |
| PRE_idempotency_key_MISSING                          | Idempotency-Key                           | Required Idempotency-Key header is missing for idempotent bind.               | Header omitted by caller.                        | halt_pipeline | Yes                     |
| PRE_idempotency_key_EMPTY                            | Idempotency-Key                           | Idempotency-Key value is empty.                                               | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_idempotency_key_NOT_REUSED_ON_RETRY              | Idempotency-Key                           | Idempotency-Key not reused verbatim on safe retry.                            | New or altered key on retry.                     | halt_pipeline | Yes                     |
| PRE_if_match_MISSING                                 | If-Match                                  | Required If-Match header is missing for write operation.                      | Header omitted by caller.                        | halt_pipeline | Yes                     |
| PRE_if_match_EMPTY                                   | If-Match                                  | If-Match value is empty.                                                      | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_if_match_ETAG_MISMATCH                           | If-Match                                  | If-Match value does not equal latest ETag for target question.                | Stale client ETag or concurrent update.          | halt_pipeline | Yes                     |
| PRE_question_id_MISSING                              | question_id                               | Required question_id is missing.                                              | Field omitted by caller.                         | halt_pipeline | Yes                     |
| PRE_question_id_INVALID_UUID                         | question_id                               | question_id is not a well-formed UUID string.                                 | Bad format or wrong type.                        | halt_pipeline | Yes                     |
| PRE_question_id_NOT_FOUND                            | question_id                               | question_id does not resolve to an existing question.                         | Unknown or deleted question.                     | halt_pipeline | Yes                     |
| PRE_transform_id_MISSING                             | transform_id                              | Required transform_id is missing.                                             | Field omitted by caller.                         | halt_pipeline | Yes                     |
| PRE_transform_id_UNKNOWN                             | transform_id                              | transform_id does not reference a known transform.                            | Typo or decommissioned transform.                | halt_pipeline | Yes                     |
| PRE_transform_id_DISABLED                            | transform_id                              | transform_id does not resolve to an enabled transform.                        | Transform disabled by config.                    | halt_pipeline | Yes                     |
| PRE_apply_mode_INVALID_ENUM                          | apply_mode                                | apply_mode is not one of verify or apply.                                     | Unsupported enum value.                          | halt_pipeline | Yes                     |
| PRE_option_labelling_INVALID_ENUM                    | option_labelling                          | option_labelling is not one of value or value_label.                          | Unsupported enum value.                          | halt_pipeline | Yes                     |
| PRE_probe_hash_REQUIRED_WHEN_NO_PROBE                | probe_hash                                | probe_hash must be provided when probe is not provided.                       | Neither probe nor probe_hash present.            | halt_pipeline | Yes                     |
| PRE_probe_hash_EMPTY                                 | probe_hash                                | probe_hash value is empty.                                                    | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_probe_hash_MISMATCH                              | probe_hash                                | probe_hash does not equal hash returned by suggest for same span and context. | Stale or tampered hash.                          | halt_pipeline | Yes                     |
| PRE_placeholder_REQUIRED_WHEN_NO_PROBE               | placeholder                               | placeholder object must be provided when probe is not provided.               | Missing placeholder in this variant.             | halt_pipeline | Yes                     |
| PRE_placeholder_SCHEMA_MISMATCH                      | placeholder                               | placeholder object does not match PlaceholderProbe schema.                    | Missing or wrong fields.                         | halt_pipeline | Yes                     |
| PRE_placeholder_raw_text_MISSING                     | placeholder.raw_text                      | placeholder.raw_text is required and missing.                                 | Field omitted in object.                         | halt_pipeline | Yes                     |
| PRE_placeholder_raw_text_EMPTY                       | placeholder.raw_text                      | placeholder.raw_text is empty.                                                | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_placeholder_raw_text_SPAN_MISMATCH               | placeholder.raw_text                      | placeholder.raw_text does not correspond to characters in resolved span.      | Selection drift or mismatch.                     | halt_pipeline | Yes                     |
| PRE_placeholder_context_MISSING                      | placeholder.context                       | placeholder.context is required and missing.                                  | Context object omitted.                          | halt_pipeline | Yes                     |
| PRE_placeholder_context_SCHEMA_MISMATCH              | placeholder.context                       | placeholder.context does not match PlaceholderProbeContext schema.            | Wrong structure or types.                        | halt_pipeline | Yes                     |
| PRE_placeholder_context_document_id_MISSING          | placeholder.context.document_id           | Document identifier is required and missing.                                  | Field omitted.                                   | halt_pipeline | Yes                     |
| PRE_placeholder_context_document_id_INVALID_UUID     | placeholder.context.document_id           | Document identifier is not a well-formed UUID.                                | Bad format.                                      | halt_pipeline | Yes                     |
| PRE_placeholder_context_document_id_NOT_FOUND        | placeholder.context.document_id           | Document identifier does not resolve to an existing document.                 | Unknown or deleted document.                     | halt_pipeline | Yes                     |
| PRE_placeholder_context_clause_path_MISSING          | placeholder.context.clause_path           | Clause path is required and missing.                                          | Field omitted.                                   | halt_pipeline | Yes                     |
| PRE_placeholder_context_clause_path_EMPTY            | placeholder.context.clause_path           | Clause path value is empty.                                                   | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_placeholder_context_clause_path_UNRESOLVED       | placeholder.context.clause_path           | Clause path does not resolve within the document.                             | Invalid path reference.                          | halt_pipeline | Yes                     |
| PRE_placeholder_context_span_SCHEMA_MISMATCH         | placeholder.context.span                  | Provided span does not match Span schema.                                     | Wrong types or keys.                             | halt_pipeline | Yes                     |
| PRE_placeholder_context_span_start_OUT_OF_RANGE      | placeholder.context.span                  | Start must be an integer ≥ 0.                                                 | Negative or non-integer start.                   | halt_pipeline | Yes                     |
| PRE_placeholder_context_span_end_OUT_OF_RANGE        | placeholder.context.span                  | End must be an integer ≥ 0.                                                   | Negative or non-integer end.                     | halt_pipeline | Yes                     |
| PRE_placeholder_context_span_BOUNDS_INVALID          | placeholder.context.span                  | End must be greater than or equal to start.                                   | Reversed or invalid bounds.                      | halt_pipeline | Yes                     |
| PRE_placeholder_context_doc_etag_EMPTY               | placeholder.context.doc_etag              | doc_etag provided but empty.                                                  | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_placeholder_context_doc_etag_VERSION_MISMATCH    | placeholder.context.doc_etag              | doc_etag does not correspond to document’s current version ETag.              | Document changed since selection.                | halt_pipeline | Yes                     |
| PRE_probe_REQUIRED_WHEN_NO_PLACEHOLDER               | probe                                     | probe object must be provided when placeholder is not provided.               | Missing probe in this variant.                   | halt_pipeline | Yes                     |
| PRE_probe_SCHEMA_MISMATCH                            | probe                                     | probe object does not match ProbeReceipt schema.                              | Wrong structure or types.                        | halt_pipeline | Yes                     |
| PRE_probe_NOT_ORIGINATED_FROM_SUGGEST                | probe                                     | probe must originate from prior suggest response.                             | Fabricated or stale probe.                       | halt_pipeline | Yes                     |
| PRE_probe_document_id_MISSING                        | probe.document_id                         | Document identifier in probe is missing.                                      | Field omitted.                                   | halt_pipeline | Yes                     |
| PRE_probe_document_id_INVALID_UUID                   | probe.document_id                         | Document identifier in probe is not a well-formed UUID.                       | Bad format.                                      | halt_pipeline | Yes                     |
| PRE_probe_document_id_TARGET_MISMATCH                | probe.document_id                         | Document identifier in probe does not match bind target.                      | Cross-document mismatch.                         | halt_pipeline | Yes                     |
| PRE_probe_clause_path_MISSING                        | probe.clause_path                         | Clause path in probe is missing.                                              | Field omitted.                                   | halt_pipeline | Yes                     |
| PRE_probe_clause_path_EMPTY                          | probe.clause_path                         | Clause path in probe is empty.                                                | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_probe_clause_path_TARGET_MISMATCH                | probe.clause_path                         | Clause path in probe does not match bind target clause path.                  | Cross-clause mismatch.                           | halt_pipeline | Yes                     |
| PRE_probe_resolved_span_MISSING                      | probe.resolved_span                       | Resolved span in probe is missing.                                            | Field omitted.                                   | halt_pipeline | Yes                     |
| PRE_probe_resolved_span_SCHEMA_MISMATCH              | probe.resolved_span                       | Resolved span does not match Span schema.                                     | Wrong structure or types.                        | halt_pipeline | Yes                     |
| PRE_probe_resolved_span_start_OUT_OF_RANGE           | probe.resolved_span.start                 | Start in resolved span is not ≥ 0.                                            | Negative or non-integer.                         | halt_pipeline | Yes                     |
| PRE_probe_resolved_span_end_OUT_OF_RANGE             | probe.resolved_span.end                   | End in resolved span is not ≥ 0.                                              | Negative or non-integer.                         | halt_pipeline | Yes                     |
| PRE_probe_resolved_span_BOUNDS_INVALID               | probe.resolved_span                       | End in resolved span is less than start.                                      | Reversed bounds.                                 | halt_pipeline | Yes                     |
| PRE_probe_placeholder_key_EMPTY                      | probe.placeholder_key                     | placeholder_key provided but empty.                                           | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_probe_placeholder_key_TOKEN_MISMATCH             | probe.placeholder_key                     | placeholder_key does not equal parsed token from resolved span.               | Parsing mismatch or tampering.                   | halt_pipeline | Yes                     |
| PRE_probe_doc_etag_EMPTY                             | probe.doc_etag                            | doc_etag in probe provided but empty.                                         | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_probe_doc_etag_VERSION_MISMATCH                  | probe.doc_etag                            | doc_etag in probe does not match document version at suggest time.            | Document changed between calls.                  | halt_pipeline | Yes                     |
| PRE_probe_probe_hash_MISSING                         | probe.probe_hash                          | probe_hash in probe is missing.                                               | Field omitted.                                   | halt_pipeline | Yes                     |
| PRE_probe_probe_hash_EMPTY                           | probe.probe_hash                          | probe_hash in probe is empty.                                                 | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_probe_probe_hash_CONTEXT_MISMATCH                | probe.probe_hash                          | probe_hash does not equal hash computed at suggest time.                      | Stale or invalid hash.                           | halt_pipeline | Yes                     |
| PRE_document_id_MISSING                              | document_id                               | Path or query document_id is required and missing.                            | Parameter omitted.                               | halt_pipeline | Yes                     |
| PRE_document_id_INVALID_UUID                         | document_id                               | document_id is not a well-formed UUID string.                                 | Bad format.                                      | halt_pipeline | Yes                     |
| PRE_document_id_NOT_FOUND                            | document_id                               | document_id does not resolve to an existing document.                         | Unknown or deleted document.                     | halt_pipeline | Yes                     |
| PRE_reason_INVALID_ENUM                              | reason                                    | reason provided but not equal to deleted.                                     | Unsupported value.                               | halt_pipeline | Yes                     |
| PRE_literals_LIST_EMPTY                              | literals[]                                | literals list provided but contains no items.                                 | Empty array supplied.                            | halt_pipeline | Yes                     |
| PRE_literals_ITEM_EMPTY                              | literals[]                                | literals list contains an empty string item.                                  | Blank list element.                              | halt_pipeline | Yes                     |
| PRE_literals_EXCLUSIVE_WITH_raw_text                 | literals[]                                | literals provided when raw_text also provided; exactly one must be supplied.  | Both inputs present.                             | halt_pipeline | Yes                     |
| PRE_raw_text_REQUIRED_FOR_SUGGEST                    | raw_text                                  | raw_text is required for suggest and missing.                                 | Field omitted by caller.                         | halt_pipeline | Yes                     |
| PRE_raw_text_EMPTY                                   | raw_text                                  | raw_text is empty.                                                            | Empty string supplied.                           | halt_pipeline | Yes                     |
| PRE_raw_text_NOT_ISOLATED_SELECTION                  | raw_text                                  | raw_text does not represent an isolated selection.                            | Surrounding context included or multiple tokens. | halt_pipeline | Yes                     |
| PRE_raw_text_EXCLUSIVE_WITH_literals                 | raw_text                                  | raw_text provided when literals also provided; exactly one must be supplied.  | Both inputs present.                             | halt_pipeline | Yes                     |
| PRE_suggestresponse_probe_PROVIDER_ERROR             | SuggestResponse.probe                     | Prior suggest call did not complete without error.                            | Upstream error in suggest.                       | halt_pipeline | Yes                     |
| PRE_suggestresponse_probe_SCHEMA_MISMATCH            | SuggestResponse.probe                     | Returned probe does not match declared schema.                                | Contract drift or corruption.                    | halt_pipeline | Yes                     |
| PRE_suggestresponse_probe_IMMUTABILITY_VIOLATION     | SuggestResponse.probe                     | Returned probe was not treated as immutable within this step.                 | Client mutated probe before bind.                | halt_pipeline | Yes                     |
| PRE_suggestresponse_probe_document_id_SCHEMA         | SuggestResponse.probe.document_id         | Returned document_id does not match schema constraints.                       | Wrong type or format.                            | halt_pipeline | Yes                     |
| PRE_suggestresponse_probe_clause_path_SCHEMA         | SuggestResponse.probe.clause_path         | Returned clause_path does not match schema constraints.                       | Wrong type or empty.                             | halt_pipeline | Yes                     |
| PRE_suggestresponse_probe_resolved_span_start_SCHEMA | SuggestResponse.probe.resolved_span.start | Returned start does not match Span schema constraints.                        | Wrong type or negative.                          | halt_pipeline | Yes                     |
| PRE_suggestresponse_probe_resolved_span_end_SCHEMA   | SuggestResponse.probe.resolved_span.end   | Returned end does not match Span schema constraints.                          | Wrong type or negative.                          | halt_pipeline | Yes                     |
| PRE_suggestresponse_probe_placeholder_key_SCHEMA     | SuggestResponse.probe.placeholder_key     | Returned placeholder_key does not match schema constraints.                   | Wrong type or empty.                             | halt_pipeline | Yes                     |
| PRE_suggestresponse_probe_doc_etag_SCHEMA            | SuggestResponse.probe.doc_etag            | Returned doc_etag does not match schema constraints.                          | Wrong type or empty.                             | halt_pipeline | Yes                     |
| PRE_suggestresponse_probe_probe_hash_SCHEMA          | SuggestResponse.probe.probe_hash          | Returned probe_hash does not match schema constraints.                        | Wrong type or empty.                             | halt_pipeline | Yes                     |
| PRE_bindresult_etag_PROVIDER_ERROR                   | BindResult.etag                           | Bind call did not complete without error.                                     | Upstream error during bind.                      | halt_pipeline | Yes                     |
| PRE_bindresult_etag_SCHEMA_MISMATCH                  | BindResult.etag                           | Returned etag does not match declared schema.                                 | Wrong type or missing.                           | halt_pipeline | Yes                     |
| PRE_unbindresponse_etag_PROVIDER_ERROR               | UnbindResponse.etag                       | Unbind call did not complete without error.                                   | Upstream error during unbind.                    | halt_pipeline | Yes                     |
| PRE_unbindresponse_etag_SCHEMA_MISMATCH              | UnbindResponse.etag                       | Returned etag does not match declared schema.                                 | Wrong type or missing.                           | halt_pipeline | Yes                     |
| PRE_listplaceholdersresponse_etag_PROVIDER_ERROR     | ListPlaceholdersResponse.etag             | List call did not complete without error.                                     | Upstream error during list.                      | halt_pipeline | Yes                     |
| PRE_listplaceholdersresponse_etag_SCHEMA_MISMATCH    | ListPlaceholdersResponse.etag             | Returned etag does not match declared schema.                                 | Wrong type or missing.                           | halt_pipeline | Yes                     |

| Error Code                                      | Output Field Ref            | Description                                                                | Likely Cause                                                        | Flow Impact        | Behavioural AC Required |
| ----------------------------------------------- | --------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------ | ----------------------- |
| POST_suggestion_MISSING                         | suggestion                  | suggestion field is missing on a successful suggest response.              | Field omitted from payload.                                         | block_finalization | Yes                     |
| POST_suggestion_SCHEMA_INVALID                  | suggestion                  | suggestion object does not validate against TransformSuggestion schema.    | Contract drift or serialization error.                              | block_finalization | Yes                     |
| POST_suggestion_OPTIONS_NOT_CANONICAL           | suggestion                  | suggestion option values are not canonical UPPER_SNAKE_CASE.               | Incorrect canonicalisation logic.                                   | block_finalization | Yes                     |
| POST_suggestion_OPTIONS_NON_DETERMINISTIC       | suggestion                  | suggestion option values are not deterministic for identical probes.       | Non-pure transform function or unstable sorting.                    | block_finalization | Yes                     |
| POST_probe_MISSING                              | probe                       | probe field is missing on a successful suggest response.                   | Field omitted from payload.                                         | block_finalization | Yes                     |
| POST_probe_SCHEMA_INVALID                       | probe                       | probe object does not validate against ProbeReceipt schema.                | Contract drift or serialization error.                              | block_finalization | Yes                     |
| POST_probe_HASH_NOT_STABLE                      | probe                       | probe.probe_hash is not stable for identical inputs.                       | Hash excludes required attributes or uses non-deterministic source. | block_finalization | Yes                     |
| POST_probe_RESOLVED_SPAN_MISMATCH               | probe                       | probe.resolved_span does not match the analysed selection.                 | Span normalization bug or index misalignment.                       | block_finalization | Yes                     |
| POST_bind_result_SCHEMA_INVALID                 | bind_result                 | bind_result object does not validate against BindResult schema.            | Contract drift or serialization error.                              | block_finalization | Yes                     |
| POST_bind_result_ETAG_NOT_NEW                   | bind_result.etag            | bind_result.etag is not a new opaque value compared to prior state.        | ETag not regenerated or reused erroneously.                         | block_finalization | Yes                     |
| POST_bind_result_ETAG_EMPTY                     | bind_result.etag            | bind_result.etag is empty instead of a non-empty token.                    | Serialization or header propagation error.                          | block_finalization | Yes                     |
| POST_bind_result_BOUND_NOT_TRUE                 | bind_result.bound           | bind_result.bound is not true on successful bind.                          | Incorrect success flag setting.                                     | block_finalization | Yes                     |
| POST_bind_result_BOUND_MISSING                  | bind_result.bound           | bind_result.bound field is missing on successful bind.                     | Field omitted from payload.                                         | block_finalization | Yes                     |
| POST_bind_result_QUESTION_ID_INVALID            | bind_result.question_id     | bind_result.question_id is not a well-formed UUID string.                  | Formatting or type error.                                           | block_finalization | Yes                     |
| POST_bind_result_QUESTION_ID_MISSING            | bind_result.question_id     | bind_result.question_id field is missing.                                  | Field omitted from payload.                                         | block_finalization | Yes                     |
| POST_bind_result_PLACEHOLDER_ID_INVALID         | bind_result.placeholder_id  | bind_result.placeholder_id is not a well-formed UUID string.               | Formatting or type error.                                           | block_finalization | Yes                     |
| POST_bind_result_PLACEHOLDER_ID_MISSING         | bind_result.placeholder_id  | bind_result.placeholder_id field is missing.                               | Field omitted from payload.                                         | block_finalization | Yes                     |
| POST_bind_result_PLACEHOLDER_ID_NOT_PERSISTED   | bind_result.placeholder_id  | bind_result.placeholder_id does not reference a persisted placeholder row. | Stale reference or failed write.                                    | block_finalization | Yes                     |
| POST_bind_result_ANSWER_KIND_INVALID            | bind_result.answer_kind     | bind_result.answer_kind is not one of the declared enum values.            | Serialization or mapping error.                                     | block_finalization | Yes                     |
| POST_bind_result_ANSWER_KIND_MISSING            | bind_result.answer_kind     | bind_result.answer_kind field is missing.                                  | Field omitted from payload.                                         | block_finalization | Yes                     |
| POST_bind_result_OPTIONS_PRESENT_WHEN_NOT_ENUM  | bind_result.options         | bind_result.options is present when answer_kind is not enum_single.        | Conditional emission bug.                                           | block_finalization | Yes                     |
| POST_bind_result_OPTIONS_MISSING_FOR_ENUM       | bind_result.options         | bind_result.options is missing when answer_kind is enum_single.            | Conditional emission bug.                                           | block_finalization | Yes                     |
| POST_bind_result_OPTIONS_SCHEMA_INVALID         | bind_result.options         | One or more options do not validate against OptionSpec schema.             | Malformed option objects.                                           | block_finalization | Yes                     |
| POST_bind_result_OPTIONS_VALUES_NOT_UNIQUE      | bind_result.options         | Option values are not unique by value.                                     | Duplicate canonical values after normalisation.                     | block_finalization | Yes                     |
| POST_bind_result_OPTIONS_EMPTY_WHEN_EXPECTED    | bind_result.options         | Option array is empty when suggestion produced a non-empty set.            | Lost options during bind or mapping error.                          | block_finalization | Yes                     |
| POST_unbind_KEYS_MISSING                        | unbind                      | unbind result does not contain required keys ok, question_id, and etag.    | Partial projection or serialization issue.                          | block_finalization | Yes                     |
| POST_unbind_OK_NOT_TRUE                         | unbind                      | unbind.ok is not true for a successful unbind.                             | Incorrect success flag setting.                                     | block_finalization | Yes                     |
| POST_unbind_QUESTION_ID_INVALID                 | unbind                      | unbind.question_id is not a valid UUID.                                    | Formatting or type error.                                           | block_finalization | Yes                     |
| POST_unbind_ETAG_EMPTY                          | unbind                      | unbind.etag is empty instead of a non-empty token.                         | Serialization or regeneration error.                                | block_finalization | Yes                     |
| POST_placeholders_MISSING                       | placeholders                | placeholders field is missing on a successful list response.               | Field omitted from payload.                                         | block_finalization | Yes                     |
| POST_placeholders_SCHEMA_INVALID                | placeholders                | One or more items do not validate against Placeholder schema.              | Contract drift or serialization error.                              | block_finalization | Yes                     |
| POST_placeholders_ORDER_NON_DETERMINISTIC       | placeholders                | Item order is not deterministic for identical inputs.                      | Unstable sort or non-deterministic data source.                     | block_finalization | Yes                     |
| POST_placeholders_ID_MISSING                    | placeholders[].id           | Placeholder id field is missing in an item.                                | Field omitted from item.                                            | block_finalization | Yes                     |
| POST_placeholders_ID_INVALID                    | placeholders[].id           | Placeholder id is not a well-formed UUID string.                           | Formatting or type error.                                           | block_finalization | Yes                     |
| POST_placeholders_ID_DUPLICATE                  | placeholders[].id           | Placeholder id is not unique across items.                                 | Duplicate persistence or projection.                                | block_finalization | Yes                     |
| POST_placeholders_DOCUMENT_ID_INVALID           | placeholders[].document_id  | document_id is not a well-formed UUID string.                              | Formatting or type error.                                           | block_finalization | Yes                     |
| POST_placeholders_DOCUMENT_ID_MISSING           | placeholders[].document_id  | document_id field is missing in an item.                                   | Field omitted from item.                                            | block_finalization | Yes                     |
| POST_placeholders_CLAUSE_PATH_EMPTY             | placeholders[].clause_path  | clause_path is empty or missing.                                           | Omitted or blank value.                                             | block_finalization | Yes                     |
| POST_placeholders_TEXT_SPAN_MISSING             | placeholders[].text_span    | text_span field is missing in an item.                                     | Field omitted from item.                                            | block_finalization | Yes                     |
| POST_placeholders_TEXT_SPAN_SCHEMA_INVALID      | placeholders[].text_span    | text_span does not validate against Span schema.                           | Malformed object or types.                                          | block_finalization | Yes                     |
| POST_placeholders_TEXT_SPAN_START_OUT_OF_RANGE  | placeholders[].text_span    | text_span.start is negative or not an integer.                             | Indexing or serialization error.                                    | block_finalization | Yes                     |
| POST_placeholders_TEXT_SPAN_END_OUT_OF_RANGE    | placeholders[].text_span    | text_span.end is negative or not an integer.                               | Indexing or serialization error.                                    | block_finalization | Yes                     |
| POST_placeholders_TEXT_SPAN_BOUNDS_INVALID      | placeholders[].text_span    | text_span.end is less than text_span.start.                                | Reversed or invalid bounds.                                         | block_finalization | Yes                     |
| POST_placeholders_QUESTION_ID_INVALID           | placeholders[].question_id  | question_id is not a well-formed UUID string.                              | Formatting or type error.                                           | block_finalization | Yes                     |
| POST_placeholders_QUESTION_ID_MISSING           | placeholders[].question_id  | question_id field is missing in an item.                                   | Field omitted from item.                                            | block_finalization | Yes                     |
| POST_placeholders_TRANSFORM_ID_EMPTY            | placeholders[].transform_id | transform_id is empty or missing in an item.                               | Omitted or blank value.                                             | block_finalization | Yes                     |
| POST_placeholders_PAYLOAD_JSON_INVALID          | placeholders[].payload_json | payload_json is present but not a valid JSON object.                       | Serialization error or wrong type.                                  | block_finalization | Yes                     |
| POST_placeholders_CREATED_AT_INVALID            | placeholders[].created_at   | created_at is not a valid RFC3339 UTC timestamp.                           | Formatting or timezone error.                                       | block_finalization | Yes                     |
| POST_list_etag_MISSING                          | list_etag                   | list_etag is missing when placeholders are returned.                       | Field omitted from payload.                                         | block_finalization | Yes                     |
| POST_list_etag_EMPTY                            | list_etag                   | list_etag is empty instead of a non-empty token.                           | Serialization error.                                                | block_finalization | Yes                     |
| POST_list_etag_NOT_CURRENT_STATE                | list_etag                   | list_etag does not represent the current model state at list time.         | Stale ETag or race condition.                                       | block_finalization | Yes                     |
| POST_purge_result_SCHEMA_INVALID                | purge_result                | purge_result object does not validate against P urgeResponse schema.       | Contract drift or serialization error.                              | block_finalization | Yes                     |
| POST_purge_result_DELETED_PLACEHOLDERS_NEGATIVE | purge_result                | deleted_placeholders is negative.                                          | Counter underflow or wrong aggregation.                             | block_finalization | Yes                     |
| POST_purge_result_UPDATED_QUESTIONS_NEGATIVE    | purge_result                | updated_questions is negative.                                             | Counter underflow or wrong aggregation.                             | block_finalization | Yes                     |
| POST_purge_result_ETAG_EMPTY_WHEN_PRESENT       | purge_result                | etag is present but empty.                                                 | Serialization error.                                                | block_finalization | Yes                     |
| POST_catalog_MISSING                            | catalog                     | catalog field is missing on a successful catalog response.                 | Field omitted from payload.                                         | block_finalization | Yes                     |
| POST_catalog_SCHEMA_INVALID                     | catalog                     | One or more items do not validate against TransformsCatalogItem schema.    | Contract drift or serialization error.                              | block_finalization | Yes                     |
| POST_catalog_ORDER_NON_DETERMINISTIC            | catalog                     | Catalog item order is not deterministic for identical inputs.              | Unstable ordering.                                                  | block_finalization | Yes                     |
| POST_preview_SCHEMA_INVALID                     | preview                     | preview object does not validate against TransformsPreviewResponse schema. | Contract drift or serialization error.                              | block_finalization | Yes                     |
| POST_preview_ANSWER_KIND_INVALID                | preview                     | preview.answer_kind is not one of the declared enum values.                | Mapping or serialization error.                                     | block_finalization | Yes                     |
| POST_preview_OPTIONS_PRESENT_WHEN_NOT_ENUM      | preview                     | preview.options is present when answer_kind is not enum_single.            | Conditional emission bug.                                           | block_finalization | Yes                     |
| POST_preview_OPTIONS_MISSING_FOR_ENUM           | preview                     | preview.options is missing when answer_kind is enum_single.                | Conditional emission bug.                                           | block_finalization | Yes                     |
| POST_problem_SCHEMA_INVALID                     | problem                     | problem object does not validate against ProblemDetails schema.            | Contract drift or serialization error.                              | block_finalization | Yes                     |
| POST_problem_STATUS_INVALID_CODE                | problem                     | problem.status is not a valid HTTP status code.                            | Wrong type or out-of-range value.                                   | block_finalization | Yes                     |
| POST_problem_TYPE_MISSING_OR_INVALID            | problem                     | problem.type is missing or not a valid URI/identifier.                     | Omitted or malformed value.                                         | block_finalization | Yes                     |
| POST_problem_TITLE_MISSING_OR_EMPTY             | problem                     | problem.title is missing or empty.                                         | Omitted or blank value.                                             | block_finalization | Yes                     |

| Error Code                              | Description                                                                    | Likely Cause                                                                     | Source (Step in Section 2.x)         | Step ID (from Section 2.2.6)                                                                   | Reachability Rationale                                                                | Flow Impact        | Behavioural AC Required |
| --------------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------ | ----------------------- |
| RUN_CREATE_ENTITY_DB_WRITE_FAILED       | Persisting a new bound placeholder failed at write time                        | Database constraint violation or write failure                                   | 2.2 – Bind (persist placeholder)     | STEP-2 Bind                                                                                    | E2 requires persisting a placeholder on bind; DB writes can fail at runtime.          | halt_pipeline      | Yes                     |
| RUN_UPDATE_ENTITY_DB_WRITE_FAILED       | Updating question model (answer_kind/options) during first-bind failed         | Database write failure or concurrent update conflict                             | 2.2 – Bind (set model on first bind) | STEP-2 Bind                                                                                    | E3 sets answer_kind and options on first bind; this involves updates that may fail.   | halt_pipeline      | Yes                     |
| RUN_DELETE_ENTITY_DB_WRITE_FAILED       | Deleting a bound placeholder during unbind failed                              | DB constraint or transaction failure                                             | 2.2 – Unbind placeholder             | STEP-3 Inspect                                                                                 | E9 deletes a placeholder record; delete can fail at runtime.                          | halt_pipeline      | Yes                     |
| RUN_RETRIEVE_ENTITY_DB_READ_FAILED      | Listing placeholders for a question failed to read                             | Read timeout or connection error                                                 | 2.2 – Read/list placeholders         | STEP-3 Inspect                                                                                 | S1/S3 with E9 imply reads to list placeholders by question/document; reads can fail.  | halt_pipeline      | Yes                     |
| RUN_IDEMPOTENCY_STORE_UNAVAILABLE       | Idempotency check during bind unavailable                                      | Idempotency backing store or cache unavailable                                   | 2.2 – Bind (idempotent apply)        | STEP-2 Bind                                                                                    | U8 requires idempotent operations; idempotency backend may be unavailable.            | halt_pipeline      | Yes                     |
| RUN_ETAG_COMPUTE_FAILED                 | Computing the updated question ETag after bind/unbind failed                   | Version hashing routine error                                                    | 2.2 – Bind/Unbind (return etag)      | STEP-2 Bind / STEP-3 Inspect                                                                   | E2/E9 return updated ETags; ETag computation can fail at runtime.                     | block_finalization | Yes                     |
| RUN_CONCURRENCY_TOKEN_GENERATION_FAILED | Generating concurrency token for If-Match workflow failed                      | Token generation routine error                                                   | 2.2 – Bind/Unbind (If-Match)         | STEP-2 Bind / STEP-3 Inspect                                                                   | U8 mandates concurrency control via If-Match; token generation may fail.              | block_finalization | Yes                     |
| RUN_PROBLEM_JSON_ENCODING_FAILED        | Serialising problem+json error response failed                                 | Problem+JSON marshalling failure                                                 | 2.2 – Any endpoint error handling    | STEP-1 Explore and decide / STEP-2 Bind / STEP-3 Inspect / STEP-4 Cleanup on document deletion | Section 2 implies consistent problem+json responses; runtime serialisation can fail.  | block_finalization | Yes                     |
| RUN_LINKAGE_RELATION_ENFORCEMENT_FAILED | Setting parent→child placeholder linkage failed                                | FK or relation lookup failure when linking nested option to child placeholder_id | 2.2 – Bind (nested linkage)          | STEP-2 Bind                                                                                    | E5 updates parent option’s placeholder_id; linkage enforcement can fail.              | halt_pipeline      | Yes                     |
| RUN_DELETE_ENTITY_DB_WRITE_FAILED       | Purging all placeholders for a deleted document failed                         | Transaction failure during cascade delete                                        | 2.2 – Cleanup on document deletion   | STEP-4 Cleanup on document deletion                                                            | E6/E7 purge placeholders on document delete; batched deletions can fail.              | halt_pipeline      | Yes                     |
| RUN_UNIDENTIFIED_ERROR                  | An otherwise unspecified runtime failure occurred during a Section 2 operation | Unhandled exception or unexpected state                                          | 2.2 – Any step                       | STEP-1 / STEP-2 / STEP-3 / STEP-4                                                              | Catch-all for unforeseen runtime failures across defined operations.                  | halt_pipeline      | Yes                     |

| Error Code                          | Description                                                                     | Likely Cause                                              | Impacted Steps                 | EARS Refs                                                          | Flow Impact   | Behavioural AC Required |
| ----------------------------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------ | ------------- | ----------------------- |
| ENV_NETWORK_UNREACHABLE             | Service cannot reach required backends (DB, cache, event bus) over the network. | Network unreachable or gateway routing failure.           | STEP-1, STEP-2, STEP-3, STEP-4 | U8, U9, E1, E2, E3, E4, E5, E9, E10, E11, E12, E14, S1, S2, S3, O4 | halt_pipeline | Yes                     |
| ENV_DNS_RESOLUTION_FAILED           | Hostname lookups for DB/cache/event bus fail.                                   | DNS server outage or misconfiguration.                    | STEP-1, STEP-2, STEP-3, STEP-4 | U8, U9, E1, E2, E3, E4, E5, E9, E10, E11, E12, E14, S1, S2, S3, O4 | halt_pipeline | Yes                     |
| ENV_TLS_HANDSHAKE_FAILED            | TLS handshake to secured backends fails.                                        | Invalid certificate, clock skew, or TLS version mismatch. | STEP-1, STEP-2, STEP-3, STEP-4 | U8, U9, E1, E2, E3, E4, E5, E9, E10, E11, E12, E14, S1, S2, S3     | halt_pipeline | Yes                     |
| ENV_CONFIG_MISSING                  | Critical runtime configuration is absent.                                       | Missing DB connection string, cache URL, or event topic.  | STEP-1, STEP-2, STEP-3, STEP-4 | U8, U9, E1, E2, E3, E4, E5, E9, E10, E11, E12, E14                 | halt_pipeline | Yes                     |
| ENV_SECRET_MISSING                  | Required secret not available to the service.                                   | Missing DB credentials or cache auth token.               | STEP-2, STEP-3, STEP-4         | U8, E2, E3, E4, E5, E9, E12, E14                                   | halt_pipeline | Yes                     |
| ENV_DATABASE_UNAVAILABLE            | Database not accepting connections or unhealthy.                                | Outage, maintenance window, or failover in progress.      | STEP-2, STEP-3, STEP-4         | U6, U7, E2, E3, E4, E5, E9, E12, E14, S1, S2, S3                   | halt_pipeline | Yes                     |
| ENV_DATABASE_PERMISSION_DENIED      | Database rejects authentication/authorisation.                                  | Invalid credentials or revoked role.                      | STEP-2, STEP-3, STEP-4         | U6, U7, E2, E3, E4, E5, E9, E12, E14, S1, S2, S3                   | halt_pipeline | Yes                     |
| ENV_DB_CONNECTION_LIMIT_EXCEEDED    | Database connection quota exhausted.                                            | Too many concurrent connections.                          | STEP-2, STEP-3, STEP-4         | U6, U7, E2, E3, E4, E5, E9, E12, E14                               | halt_pipeline | Yes                     |
| ENV_IDEMPOTENCY_STORE_UNAVAILABLE   | Idempotency backing store cannot be reached.                                    | Cache service outage or network partition.                | STEP-2                         | U8, E2                                                             | halt_pipeline | Yes                     |
| ENV_CACHE_PERMISSION_DENIED         | Cache/idempotency store rejects access.                                         | Wrong token or ACL policy.                                | STEP-2                         | U8, E2                                                             | halt_pipeline | Yes                     |
| ENV_EVENT_BUS_UNAVAILABLE           | Event bus for document deletion events is unavailable.                          | Broker outage or topic missing.                           | STEP-4                         | E6, E7, E12                                                        | halt_pipeline | Yes                     |
| ENV_EVENT_BUS_PERMISSION_DENIED     | Publish/subscribe to deletion topic is forbidden.                               | Missing permission or invalid principal.                  | STEP-4                         | E6, E7, E12                                                        | halt_pipeline | Yes                     |
| ENV_EVENT_BUS_QUOTA_EXCEEDED        | Event bus quota/rate for topic exceeded.                                        | Topic throughput limit reached.                           | STEP-4                         | E6, E7, E12                                                        | halt_pipeline | Yes                     |
| ENV_API_GATEWAY_RATE_LIMIT_EXCEEDED | Incoming API call rejected by gateway rate limits.                              | Client exceeded per-route or per-user rate.               | STEP-1, STEP-2, STEP-3, STEP-4 | U9, E1, E2, E9, E10, E11, E12, E14                                 | halt_pipeline | Yes                     |
| ENV_API_GATEWAY_QUOTA_EXCEEDED      | API quota exhausted for the period.                                             | Daily/monthly quota reached.                              | STEP-1, STEP-2, STEP-3, STEP-4 | U9, E1, E2, E9, E10, E11, E12, E14                                 | halt_pipeline | Yes                     |

6.1 Architectural acceptance criteria

6.1.1 modular separation of suggestion and binding
The system must maintain distinct modules for transform suggestion and placeholder binding, each exposed through its own API entry point.
References: STEP-1, STEP-2, U3, U6, E1, E2

6.1.2 schema reuse for placeholderprobe
Both suggest and bind flows must consume and produce data conforming to the same PlaceholderProbe schema file to ensure type consistency.
References: STEP-1, STEP-2, U1, U5, E1, E13

6.1.3 stateless design of suggestion endpoint
The `/api/v1/transforms/suggest` endpoint must perform a pure analysis of the provided payload without writing to persistence.
References: STEP-1, U6, E1

6.1.4 persistent entity isolation for placeholders
Placeholder records created at bind time must be stored in a dedicated table with foreign keys to questions and documents and cascade delete behaviour.
References: STEP-2, STEP-4, U6, E2, E6

6.1.5 deterministic transform rules
Transform classification logic must be implemented as a deterministic function returning identical output for identical input tuples `(raw_text, document_id, clause_path, resolved_span)`.
References: STEP-1, U2, U3, E1

6.1.6 canonical value enforcement
All literal options generated by transform logic must be converted to uppercase snake case before persistence or response.
References: STEP-1, STEP-2, U10, E3

6.1.7 stable ordering of options
Enum options within `enum_single` transforms must be returned and persisted in stable order across identical invocations.
References: STEP-1, STEP-2, U10, E3

6.1.8 probe hash verification mechanism
The binding workflow must validate that the incoming probe hash equals the value issued during the suggest phase.
References: STEP-2, U5, E13, N5

6.1.9 idempotency enforcement
The bind operation must record and verify `Idempotency-Key` headers to prevent duplicate placeholder creation for identical payloads.
References: STEP-2, U8, E2, N4

6.1.10 etag-based concurrency control
All write endpoints must require and validate the `If-Match` header corresponding to the latest question ETag.
References: STEP-2, STEP-3, U8, N8

6.1.11 consistent schema references
Every request and response object must validate against its declared JSON schema under `schemas/` and use matching property definitions.
References: STEP-1, STEP-2, STEP-3, U9, E9, E10, E11, E14

6.1.12 cascade cleanup on document deletion
Deleting a document must trigger removal of all related placeholders via a cascade or event-driven purge, updating affected questions accordingly.
References: STEP-4, U9, E6, E12, S3

6.1.13 idempotent cleanup execution
Repeated purge events for the same document must perform no additional deletions after the first.
References: STEP-4, E7, S3

6.1.14 consistent model enforcement across bindings
When multiple placeholders bind to one question, the architecture must include a guard ensuring all share identical answer_kind and option set.
References: STEP-2, S1, S2, N1

6.1.15 nested placeholder linkage integrity
Parent–child relationships between placeholders must be represented by foreign keys linking parent option placeholder_id to child placeholder.id.
References: STEP-2, E5, S3, O4

6.1.16 retry-safe API headers
All endpoints performing mutation must include validation for `Idempotency-Key` and `If-Match` headers as defined in HttpHeaders.json.
References: STEP-2, STEP-3, U8, E2, E9

6.1.17 consistent error object structure
Every non-2xx response must return an object validating against `ProblemDetails.json` and use `application/problem+json`.
References: STEP-1, STEP-2, STEP-3, STEP-4, U9

6.1.18 transform catalog discoverability
The transforms catalog must be exposed as a read-only endpoint returning a deterministic, schema-validated list of supported transforms.
References: STEP-1, U9, E10

6.1.19 preview isolation
The preview endpoint must use the same canonicalisation pipeline as suggestion but without touching persistence or affecting runtime state.
References: STEP-1, U3, E11

6.1.20 schema-validated event payloads
Internal or event-driven calls such as document deletion must emit and consume JSON payloads matching their declared schema (`PurgeRequest.json`, `PurgeResponse.json`).
References: STEP-4, E6, E7, E12, S3

6.1.21 separation of read and write models
Read operations (`list`, `catalog`, `preview`) must not share transactional contexts with write operations (`bind`, `unbind`, `purge`).
References: STEP-1, STEP-2, STEP-3, STEP-4, U9

6.1.22 stable etag regeneration
After every bind or unbind, the system must regenerate a new opaque ETag token representing the updated question state.
References: STEP-2, STEP-3, E2, E9, S1

6.1.23 canonical directory structure for schemas
All JSON schema definitions referenced in this epic must reside under the `schemas/` directory at repository root, with paths matching those in Section 3 and 4 tables.
References: STEP-1, STEP-2, STEP-3, U9

6.1.24 statically defined transform enumeration
Supported transform identifiers must be declared in a single static registry file loaded by the transform suggestion module.
References: STEP-1, U3, E10

6.1.25 consistent timestamp format
All persisted entities and responses containing timestamps must use RFC3339 UTC format validated against schema.
References: STEP-3, U9, E14

6.1.26 immutability of probe receipts
ProbeReceipt objects returned from suggest must be treated as immutable and echoed exactly in bind requests.
References: STEP-1, STEP-2, U5, E13, N5

6.1.27 enforcement of schema validation on responses
Every response emitted by endpoints defined in this epic must undergo automatic schema validation before transmission.
References: STEP-1, STEP-2, STEP-3, STEP-4, U9

6.1.28 consistent enum validation for answer_kind
Values of answer_kind must always match the enumerated constants defined in `AnswerKind.json`.
References: STEP-2, U3, E3

6.1.29 purge idempotence and observability
The purge operation must return counts of deleted placeholders and updated questions, matching integer ≥0 constraints in schema.
References: STEP-4, E6, E12

6.1.30 transform engine testability
The transform detection logic must be implemented as a discrete service or module whose outputs can be unit tested independently from API transport.
References: STEP-1, U3, O1, O2, O3, N2

6.2 Happy Path Contractual Acceptance Criteria

6.2.1.1 Suggest returns single transform proposal
**Given** a valid `PlaceholderProbe` is submitted, **when** the client calls the transform suggestion endpoint, **then** the response includes exactly one transform proposal.
**Reference:** EARS U3, E1; Outputs: `suggestion`.

6.2.1.2 Suggest returns probe receipt for bind continuity
**Given** a valid `PlaceholderProbe` is submitted, **when** suggestion completes successfully, **then** the response includes a probe receipt for later bind continuity.
**Reference:** EARS U5, E1; Outputs: `probe`.

6.2.1.3 Suggest proposal exposes answer kind
**Given** a valid `PlaceholderProbe`, **when** suggestion completes, **then** the proposal specifies the answer kind for the placeholder.
**Reference:** EARS U2, U3, E1; Outputs: `suggestion.answer_kind`.

6.2.1.4 Suggest proposal canonicalises options
**Given** a placeholder that resolves to `enum_single`, **when** suggestion completes, **then** the options are present with canonical `value`s and preserved original `label`s.
**Reference:** EARS U3, U10, E1; Outputs: `suggestion.options[]`.

6.2.1.5 Suggest returns stable probe hash
**Given** a valid `PlaceholderProbe`, **when** suggestion completes, **then** the probe receipt includes a `probe_hash`.
**Reference:** EARS U5, E1; Outputs: `probe.probe_hash`.

6.2.1.6 Bind returns success result
**Given** a selected transform and associated probe/probe_hash, **when** the placeholder is bound to a question, **then** the response indicates a successful bind.
**Reference:** EARS U6, E2; Outputs: `bind_result.bound`.

6.2.1.7 Bind returns persisted placeholder identifier
**Given** a successful bind, **when** the response is returned, **then** it includes the identifier of the persisted placeholder.
**Reference:** EARS U6, E2; Outputs: `bind_result.placeholder_id`.

6.2.1.8 Bind sets/returns the question answer kind
**Given** a first binding for a question, **when** bind completes, **then** the response specifies the question’s answer kind.
**Reference:** EARS U7, E3; Outputs: `bind_result.answer_kind`.

6.2.1.9 Bind returns canonical option set for enum_single
**Given** a first binding yields `enum_single`, **when** bind completes, **then** the response includes the canonical option set.
**Reference:** EARS U7, E3; Outputs: `bind_result.options[]`.

6.2.1.10 Bind maintains model consistency on subsequent binds
**Given** a question already has an answer model, **when** a consistent placeholder is bound, **then** the response reflects the existing answer kind.
**Reference:** EARS U7, E4, S1; Outputs: `bind_result.answer_kind`.

6.2.1.11 Nested linkage is reflected in parent option
**Given** a parent option references a nested placeholder key, **when** the child placeholder is later bound, **then** the parent option in the response includes the child `placeholder_id`.
**Reference:** EARS E5, S3; Outputs: `bind_result.options[].placeholder_id`.

6.2.1.12 Bind returns updated concurrency token
**Given** a successful bind, **when** the response is returned, **then** it includes a new question ETag.
**Reference:** EARS U8, E2; Outputs: `bind_result.etag`.

6.2.1.13 Unbind returns success projection
**Given** a specific placeholder identifier, **when** unbind completes successfully, **then** the response projection indicates success and returns the updated ETag.
**Reference:** EARS E9; Outputs: `unbind.ok`, `unbind.etag`.

6.2.1.14 List returns placeholders for a question
**Given** a question identifier (optionally filtered by document), **when** the list endpoint succeeds, **then** the response returns the placeholders for that question.
**Reference:** EARS U9, S3; Outputs: `placeholders[]`.

6.2.1.15 List includes stable question ETag
**Given** a successful list response, **when** placeholders are returned, **then** the response includes the current question ETag.
**Reference:** EARS U9; Outputs: `list_etag`.

6.2.1.16 Purge returns deletion summary
**Given** a document deletion cleanup is requested, **when** purge completes successfully, **then** the response includes counts of deleted placeholders and updated questions.
**Reference:** EARS U9, E6, E7; Outputs: `purge_result.deleted_placeholders`, `purge_result.updated_questions`.

6.2.1.17 Catalog returns supported transforms
**Given** a catalog request, **when** it succeeds, **then** the response includes the list of supported transforms.
**Reference:** EARS U9, E10; Outputs: `catalog[]`.

6.2.1.18 Preview returns answer kind
**Given** a preview request with `raw_text` or `literals`, **when** preview completes, **then** the response includes the inferred answer kind.
**Reference:** EARS U3, E11; Outputs: `preview.answer_kind`.

6.2.1.19 Preview returns canonical options for enum_single
**Given** a preview that resolves to `enum_single`, **when** preview completes, **then** the response includes the canonical option set.
**Reference:** EARS U3, E11; Outputs: `preview.options[]`.

6.2.1.20 Listing preserves document and clause references
**Given** placeholders are listed, **when** the response is returned, **then** each placeholder includes its `document_id` and `clause_path`.
**Reference:** EARS S3; Outputs: `placeholders[].document_id`, `placeholders[].clause_path`.

6.2.1.21 Listing includes span coordinates
**Given** placeholders are listed, **when** the response is returned, **then** each placeholder includes its start and end character indices.
**Reference:** EARS S3; Outputs: `placeholders[].text_span.start`, `placeholders[].text_span.end`.

6.2.1.22 Idempotent bind returns same placeholder identifier
**Given** the same bind request is retried with the same `Idempotency-Key`, **when** bind completes, **then** the response contains the same `placeholder_id` as the original success.
**Reference:** EARS U8, E2; Outputs: `bind_result.placeholder_id`.

6.2.1.23 Suggest is stateless with no persistence side-effects
**Given** a suggestion request, **when** it completes successfully, **then** no persisted placeholder is created and only the proposal and probe are returned.
**Reference:** EARS U6, E1; Outputs: `suggestion`, `probe` (and absence of `bind_result` on this endpoint).

6.2.1.24 Purge idempotence reflected in counts
**Given** a purge is called for a document that has already been cleaned, **when** purge completes, **then** the response shows zero additional deletions.
**Reference:** EARS E7; Outputs: `purge_result.deleted_placeholders`.

6.2.1.25 Consistent listing after unbind of last placeholder
**Given** a question whose last placeholder has been unbound, **when** placeholders are listed, **then** the response contains an empty array.
**Reference:** EARS E8; Outputs: `placeholders[]`.

**6.2.2.1 Idempotency key missing**
**Given** a bind request is sent without an `Idempotency-Key`, **when** the request is processed, **then** the system returns a contract error for the missing idempotency header.
**Error Mode:** PRE_idempotency_key_MISSING
**Reference:** Inputs: `Idempotency-Key`

**6.2.2.2 Idempotency key empty**
**Given** a bind request includes an empty `Idempotency-Key`, **when** the request is processed, **then** the system returns a contract error for an empty idempotency value.
**Error Mode:** PRE_idempotency_key_EMPTY
**Reference:** Inputs: `Idempotency-Key`

**6.2.2.3 Idempotency key not reused on retry**
**Given** a safe retry of a prior bind uses a different `Idempotency-Key`, **when** the request is processed, **then** the system returns a contract error for non-reused idempotency key.
**Error Mode:** PRE_idempotency_key_NOT_REUSED_ON_RETRY
**Reference:** Inputs: `Idempotency-Key`

**6.2.2.4 If-Match header missing**
**Given** a write request omits `If-Match`, **when** the request is processed, **then** the system returns a contract error for missing concurrency header.
**Error Mode:** PRE_if_match_MISSING
**Reference:** Inputs: `If-Match`

**6.2.2.5 If-Match header empty**
**Given** a write request sends an empty `If-Match`, **when** processed, **then** the system returns a contract error for empty concurrency token.
**Error Mode:** PRE_if_match_EMPTY
**Reference:** Inputs: `If-Match`

**6.2.2.6 If-Match ETag mismatch**
**Given** a write request includes a stale `If-Match` ETag, **when** processed, **then** the system returns a contract error for ETag mismatch.
**Error Mode:** PRE_if_match_ETAG_MISMATCH
**Reference:** Inputs: `If-Match`

**6.2.2.7 question_id missing**
**Given** a request requiring `question_id` omits it, **when** processed, **then** the system returns a contract error for missing question identifier.
**Error Mode:** PRE_question_id_MISSING
**Reference:** Inputs: `question_id`

**6.2.2.8 question_id invalid UUID**
**Given** a request provides a non-UUID `question_id`, **when** processed, **then** the system returns a contract error for invalid identifier format.
**Error Mode:** PRE_question_id_INVALID_UUID
**Reference:** Inputs: `question_id`

**6.2.2.9 question_id not found**
**Given** a request references a non-existent `question_id`, **when** processed, **then** the system returns a contract error for unknown question.
**Error Mode:** PRE_question_id_NOT_FOUND
**Reference:** Inputs: `question_id`

**6.2.2.10 transform_id missing**
**Given** a bind request omits `transform_id`, **when** processed, **then** the system returns a contract error for missing transform.
**Error Mode:** PRE_transform_id_MISSING
**Reference:** Inputs: `transform_id`

**6.2.2.11 transform_id unknown**
**Given** a bind request specifies an unknown `transform_id`, **when** processed, **then** the system returns a contract error for unknown transform.
**Error Mode:** PRE_transform_id_UNKNOWN
**Reference:** Inputs: `transform_id`

**6.2.2.12 transform_id disabled**
**Given** a bind request uses a disabled `transform_id`, **when** processed, **then** the system returns a contract error for disabled transform.
**Error Mode:** PRE_transform_id_DISABLED
**Reference:** Inputs: `transform_id`

**6.2.2.13 apply_mode invalid enum**
**Given** a bind request provides an unsupported `apply_mode`, **when** processed, **then** the system returns a contract error for invalid enum value.
**Error Mode:** PRE_apply_mode_INVALID_ENUM
**Reference:** Inputs: `apply_mode`

**6.2.2.14 option_labelling invalid enum**
**Given** a bind request provides an unsupported `option_labelling`, **when** processed, **then** the system returns a contract error for invalid enum value.
**Error Mode:** PRE_option_labelling_INVALID_ENUM
**Reference:** Inputs: `option_labelling`

**6.2.2.15 probe_hash required when no probe**
**Given** a bind request sends `placeholder` but no `probe`, **when** processed, **then** the system returns a contract error if `probe_hash` is missing.
**Error Mode:** PRE_probe_hash_REQUIRED_WHEN_NO_PROBE
**Reference:** Inputs: `probe_hash`, `placeholder`, `probe`

**6.2.2.16 probe_hash empty**
**Given** a bind request includes an empty `probe_hash`, **when** processed, **then** the system returns a contract error for empty hash.
**Error Mode:** PRE_probe_hash_EMPTY
**Reference:** Inputs: `probe_hash`

**6.2.2.17 probe_hash mismatch**
**Given** a bind request includes a `probe_hash` that does not match suggest, **when** processed, **then** the system returns a contract error for mismatched hash.
**Error Mode:** PRE_probe_hash_MISMATCH
**Reference:** Inputs: `probe_hash`

**6.2.2.18 placeholder required when no probe**
**Given** a bind request sends `probe_hash` but no `probe`, **when** processed, **then** the system returns a contract error if `placeholder` is missing.
**Error Mode:** PRE_placeholder_REQUIRED_WHEN_NO_PROBE
**Reference:** Inputs: `placeholder`, `probe`, `probe_hash`

**6.2.2.19 placeholder schema mismatch**
**Given** a bind request includes a malformed `placeholder` object, **when** processed, **then** the system returns a contract error for schema mismatch.
**Error Mode:** PRE_placeholder_SCHEMA_MISMATCH
**Reference:** Inputs: `placeholder` (schemas/PlaceholderProbe.json)

**6.2.2.20 placeholder.raw_text missing**
**Given** a `placeholder` omits `raw_text`, **when** processed, **then** the system returns a contract error for missing selection text.
**Error Mode:** PRE_placeholder_raw_text_MISSING
**Reference:** Inputs: `placeholder.raw_text`

**6.2.2.21 placeholder.raw_text empty**
**Given** a `placeholder.raw_text` is empty, **when** processed, **then** the system returns a contract error for empty selection text.
**Error Mode:** PRE_placeholder_raw_text_EMPTY
**Reference:** Inputs: `placeholder.raw_text`

**6.2.2.22 placeholder.raw_text span mismatch**
**Given** a `placeholder.raw_text` that does not match the resolved span, **when** processed, **then** the system returns a contract error for text–span mismatch.
**Error Mode:** PRE_placeholder_raw_text_SPAN_MISMATCH
**Reference:** Inputs: `placeholder.raw_text`, `placeholder.context.span` (or `probe.resolved_span`)

**6.2.2.23 placeholder.context missing**
**Given** a `placeholder` omits `context`, **when** processed, **then** the system returns a contract error for missing context.
**Error Mode:** PRE_placeholder_context_MISSING
**Reference:** Inputs: `placeholder.context`

**6.2.2.24 placeholder.context schema mismatch**
**Given** a malformed `placeholder.context`, **when** processed, **then** the system returns a contract error for context schema mismatch.
**Error Mode:** PRE_placeholder_context_SCHEMA_MISMATCH
**Reference:** Inputs: `placeholder.context`

**6.2.2.25 context.document_id missing**
**Given** a `placeholder.context` omits `document_id`, **when** processed, **then** the system returns a contract error for missing document identifier.
**Error Mode:** PRE_placeholder_context_document_id_MISSING
**Reference:** Inputs: `placeholder.context.document_id`

**6.2.2.26 context.document_id invalid UUID**
**Given** a non-UUID `context.document_id`, **when** processed, **then** the system returns a contract error for invalid identifier format.
**Error Mode:** PRE_placeholder_context_document_id_INVALID_UUID
**Reference:** Inputs: `placeholder.context.document_id`

**6.2.2.27 context.document_id not found**
**Given** an unknown `context.document_id`, **when** processed, **then** the system returns a contract error for unknown document.
**Error Mode:** PRE_placeholder_context_document_id_NOT_FOUND
**Reference:** Inputs: `placeholder.context.document_id`

**6.2.2.28 context.clause_path missing**
**Given** a `placeholder.context` omits `clause_path`, **when** processed, **then** the system returns a contract error for missing clause path.
**Error Mode:** PRE_placeholder_context_clause_path_MISSING
**Reference:** Inputs: `placeholder.context.clause_path`

**6.2.2.29 context.clause_path empty**
**Given** an empty `clause_path`, **when** processed, **then** the system returns a contract error for empty path.
**Error Mode:** PRE_placeholder_context_clause_path_EMPTY
**Reference:** Inputs: `placeholder.context.clause_path`

**6.2.2.30 context.clause_path unresolved**
**Given** a `clause_path` that does not resolve within the document, **when** processed, **then** the system returns a contract error for unresolved path.
**Error Mode:** PRE_placeholder_context_clause_path_UNRESOLVED
**Reference:** Inputs: `placeholder.context.clause_path`

**6.2.2.31 context.span schema mismatch**
**Given** a malformed `context.span`, **when** processed, **then** the system returns a contract error for span schema mismatch.
**Error Mode:** PRE_placeholder_context_span_SCHEMA_MISMATCH
**Reference:** Inputs: `placeholder.context.span`

**6.2.2.32 context.span.start out of range**
**Given** `span.start` is negative or non-integer, **when** processed, **then** the system returns a contract error for invalid start bound.
**Error Mode:** PRE_placeholder_context_span_start_OUT_OF_RANGE
**Reference:** Inputs: `placeholder.context.span.start`

**6.2.2.33 context.span.end out of range**
**Given** `span.end` is negative or non-integer, **when** processed, **then** the system returns a contract error for invalid end bound.
**Error Mode:** PRE_placeholder_context_span_end_OUT_OF_RANGE
**Reference:** Inputs: `placeholder.context.span.end`

**6.2.2.34 context.span bounds invalid**
**Given** `span.end < span.start`, **when** processed, **then** the system returns a contract error for invalid span bounds.
**Error Mode:** PRE_placeholder_context_span_BOUNDS_INVALID
**Reference:** Inputs: `placeholder.context.span`

**6.2.2.35 context.doc_etag empty**
**Given** `doc_etag` is present but empty, **when** processed, **then** the system returns a contract error for empty document ETag.
**Error Mode:** PRE_placeholder_context_doc_etag_EMPTY
**Reference:** Inputs: `placeholder.context.doc_etag`

**6.2.2.36 context.doc_etag version mismatch**
**Given** `doc_etag` does not match the document’s current version, **when** processed, **then** the system returns a contract error for version mismatch.
**Error Mode:** PRE_placeholder_context_doc_etag_VERSION_MISMATCH
**Reference:** Inputs: `placeholder.context.doc_etag`

**6.2.2.37 probe required when no placeholder**
**Given** a bind request sends no `placeholder`, **when** processed, **then** the system returns a contract error if `probe` is also absent.
**Error Mode:** PRE_probe_REQUIRED_WHEN_NO_PLACEHOLDER
**Reference:** Inputs: `probe`, `placeholder`

**6.2.2.38 probe schema mismatch**
**Given** a malformed `probe` object, **when** processed, **then** the system returns a contract error for probe schema mismatch.
**Error Mode:** PRE_probe_SCHEMA_MISMATCH
**Reference:** Inputs: `probe` (schemas/ProbeReceipt.json)

**6.2.2.39 probe not originated from suggest**
**Given** a `probe` that was not returned by suggest, **when** processed, **then** the system returns a contract error for invalid probe origin.
**Error Mode:** PRE_probe_NOT_ORIGINATED_FROM_SUGGEST
**Reference:** Inputs: `probe`

**6.2.2.40 probe.document_id missing**
**Given** a `probe` without `document_id`, **when** processed, **then** the system returns a contract error for missing probe document id.
**Error Mode:** PRE_probe_document_id_MISSING
**Reference:** Inputs: `probe.document_id`

**6.2.2.41 probe.document_id invalid UUID**
**Given** a non-UUID `probe.document_id`, **when** processed, **then** the system returns a contract error for invalid identifier format.
**Error Mode:** PRE_probe_document_id_INVALID_UUID
**Reference:** Inputs: `probe.document_id`

**6.2.2.42 probe.document_id target mismatch**
**Given** a `probe.document_id` that does not match the bind target, **when** processed, **then** the system returns a contract error for target mismatch.
**Error Mode:** PRE_probe_document_id_TARGET_MISMATCH
**Reference:** Inputs: `probe.document_id`

**6.2.2.43 probe.clause_path missing**
**Given** a `probe` without `clause_path`, **when** processed, **then** the system returns a contract error for missing probe clause path.
**Error Mode:** PRE_probe_clause_path_MISSING
**Reference:** Inputs: `probe.clause_path`

**6.2.2.44 probe.clause_path empty**
**Given** an empty `probe.clause_path`, **when** processed, **then** the system returns a contract error for empty probe clause path.
**Error Mode:** PRE_probe_clause_path_EMPTY
**Reference:** Inputs: `probe.clause_path`

**6.2.2.45 probe.clause_path target mismatch**
**Given** a `probe.clause_path` that does not match the bind target, **when** processed, **then** the system returns a contract error for clause mismatch.
**Error Mode:** PRE_probe_clause_path_TARGET_MISMATCH
**Reference:** Inputs: `probe.clause_path`

**6.2.2.46 probe.resolved_span missing**
**Given** a `probe` without `resolved_span`, **when** processed, **then** the system returns a contract error for missing resolved span.
**Error Mode:** PRE_probe_resolved_span_MISSING
**Reference:** Inputs: `probe.resolved_span`

**6.2.2.47 probe.resolved_span schema mismatch**
**Given** a malformed `probe.resolved_span`, **when** processed, **then** the system returns a contract error for span schema mismatch.
**Error Mode:** PRE_probe_resolved_span_SCHEMA_MISMATCH
**Reference:** Inputs: `probe.resolved_span`

**6.2.2.48 probe.resolved_span.start out of range**
**Given** a negative or non-integer `resolved_span.start`, **when** processed, **then** the system returns a contract error for invalid start bound.
**Error Mode:** PRE_probe_resolved_span_start_OUT_OF_RANGE
**Reference:** Inputs: `probe.resolved_span.start`

**6.2.2.49 probe.resolved_span.end out of range**
**Given** a negative or non-integer `resolved_span.end`, **when** processed, **then** the system returns a contract error for invalid end bound.
**Error Mode:** PRE_probe_resolved_span_end_OUT_OF_RANGE
**Reference:** Inputs: `probe.resolved_span.end`

**6.2.2.50 probe.resolved_span bounds invalid**
**Given** `resolved_span.end < resolved_span.start`, **when** processed, **then** the system returns a contract error for invalid span bounds.
**Error Mode:** PRE_probe_resolved_span_BOUNDS_INVALID
**Reference:** Inputs: `probe.resolved_span`

**6.2.2.51 probe.placeholder_key empty**
**Given** `probe.placeholder_key` is present but empty, **when** processed, **then** the system returns a contract error for empty placeholder key.
**Error Mode:** PRE_probe_placeholder_key_EMPTY
**Reference:** Inputs: `probe.placeholder_key`

**6.2.2.52 probe.placeholder_key token mismatch**
**Given** `probe.placeholder_key` does not match the parsed token, **when** processed, **then** the system returns a contract error for token mismatch.
**Error Mode:** PRE_probe_placeholder_key_TOKEN_MISMATCH
**Reference:** Inputs: `probe.placeholder_key`

**6.2.2.53 probe.doc_etag empty**
**Given** `probe.doc_etag` is present but empty, **when** processed, **then** the system returns a contract error for empty document ETag.
**Error Mode:** PRE_probe_doc_etag_EMPTY
**Reference:** Inputs: `probe.doc_etag`

**6.2.2.54 probe.doc_etag version mismatch**
**Given** `probe.doc_etag` does not match the document version at suggest time, **when** processed, **then** the system returns a contract error for version mismatch.
**Error Mode:** PRE_probe_doc_etag_VERSION_MISMATCH
**Reference:** Inputs: `probe.doc_etag`

**6.2.2.55 probe.probe_hash missing**
**Given** a `probe` without `probe_hash`, **when** processed, **then** the system returns a contract error for missing probe hash.
**Error Mode:** PRE_probe_probe_hash_MISSING
**Reference:** Inputs: `probe.probe_hash`

**6.2.2.56 probe.probe_hash empty**
**Given** an empty `probe.probe_hash`, **when** processed, **then** the system returns a contract error for empty probe hash.
**Error Mode:** PRE_probe_probe_hash_EMPTY
**Reference:** Inputs: `probe.probe_hash`

**6.2.2.57 probe.probe_hash context mismatch**
**Given** `probe.probe_hash` does not match suggest context, **when** processed, **then** the system returns a contract error for context mismatch.
**Error Mode:** PRE_probe_probe_hash_CONTEXT_MISMATCH
**Reference:** Inputs: `probe.probe_hash`

**6.2.2.58 document_id missing**
**Given** a path/query `document_id` is required but omitted, **when** processed, **then** the system returns a contract error for missing document id.
**Error Mode:** PRE_document_id_MISSING
**Reference:** Inputs: `document_id`

**6.2.2.59 document_id invalid UUID**
**Given** a non-UUID `document_id`, **when** processed, **then** the system returns a contract error for invalid identifier format.
**Error Mode:** PRE_document_id_INVALID_UUID
**Reference:** Inputs: `document_id`

**6.2.2.60 document_id not found**
**Given** a `document_id` that does not resolve, **when** processed, **then** the system returns a contract error for unknown document.
**Error Mode:** PRE_document_id_NOT_FOUND
**Reference:** Inputs: `document_id`

**6.2.2.61 reason invalid enum**
**Given** a purge request provides an unsupported `reason`, **when** processed, **then** the system returns a contract error for invalid reason.
**Error Mode:** PRE_reason_INVALID_ENUM
**Reference:** Inputs: `reason`

**6.2.2.62 literals list empty**
**Given** a preview request provides `literals` as an empty list, **when** processed, **then** the system returns a contract error for empty literals.
**Error Mode:** PRE_literals_LIST_EMPTY
**Reference:** Inputs: `literals[]`

**6.2.2.63 literals contains empty item**
**Given** a preview request’s `literals` includes an empty string, **when** processed, **then** the system returns a contract error for empty list item.
**Error Mode:** PRE_literals_ITEM_EMPTY
**Reference:** Inputs: `literals[]`

**6.2.2.64 literals exclusive with raw_text**
**Given** a preview request provides both `literals` and `raw_text`, **when** processed, **then** the system returns a contract error for mutual exclusivity violation.
**Error Mode:** PRE_literals_EXCLUSIVE_WITH_raw_text
**Reference:** Inputs: `literals[]`, `raw_text`

**6.2.2.65 raw_text required for suggest**
**Given** a suggest request omits `raw_text`, **when** processed, **then** the system returns a contract error for missing raw text.
**Error Mode:** PRE_raw_text_REQUIRED_FOR_SUGGEST
**Reference:** Inputs: `raw_text`

**6.2.2.66 raw_text empty**
**Given** `raw_text` is empty, **when** processed, **then** the system returns a contract error for empty raw text.
**Error Mode:** PRE_raw_text_EMPTY
**Reference:** Inputs: `raw_text`

**6.2.2.67 raw_text not isolated selection**
**Given** `raw_text` is not an isolated selection, **when** processed, **then** the system returns a contract error for invalid selection.
**Error Mode:** PRE_raw_text_NOT_ISOLATED_SELECTION
**Reference:** Inputs: `raw_text`

**6.2.2.68 raw_text exclusive with literals**
**Given** a preview request provides both `raw_text` and `literals`, **when** processed, **then** the system returns a contract error for mutual exclusivity violation.
**Error Mode:** PRE_raw_text_EXCLUSIVE_WITH_literals
**Reference:** Inputs: `raw_text`, `literals[]`

**6.2.2.69 Suggest probe provider error**
**Given** the prior suggest call failed, **when** its `probe` is consumed, **then** the system returns a contract error indicating upstream provider error.
**Error Mode:** PRE_suggestresponse_probe_PROVIDER_ERROR
**Reference:** Inputs: `SuggestResponse.probe`

**6.2.2.70 Suggest probe schema mismatch**
**Given** the returned `SuggestResponse.probe` violates schema, **when** consumed, **then** the system returns a contract error for schema mismatch.
**Error Mode:** PRE_suggestresponse_probe_SCHEMA_MISMATCH
**Reference:** Inputs: `SuggestResponse.probe`

**6.2.2.71 Suggest probe immutability violation**
**Given** the client mutated `SuggestResponse.probe`, **when** consumed, **then** the system returns a contract error for immutability violation.
**Error Mode:** PRE_suggestresponse_probe_IMMUTABILITY_VIOLATION
**Reference:** Inputs: `SuggestResponse.probe`

**6.2.2.72 Suggest probe document_id schema**
**Given** `SuggestResponse.probe.document_id` violates schema, **when** consumed, **then** the system returns a contract error for identifier schema failure.
**Error Mode:** PRE_suggestresponse_probe_document_id_SCHEMA
**Reference:** Inputs: `SuggestResponse.probe.document_id`

**6.2.2.73 Suggest probe clause_path schema**
**Given** `SuggestResponse.probe.clause_path` violates schema, **when** consumed, **then** the system returns a contract error for clause path schema failure.
**Error Mode:** PRE_suggestresponse_probe_clause_path_SCHEMA
**Reference:** Inputs: `SuggestResponse.probe.clause_path`

**6.2.2.74 Suggest probe resolved_span.start schema**
**Given** `SuggestResponse.probe.resolved_span.start` violates schema, **when** consumed, **then** the system returns a contract error for start index schema failure.
**Error Mode:** PRE_suggestresponse_probe_resolved_span_start_SCHEMA
**Reference:** Inputs: `SuggestResponse.probe.resolved_span.start`

**6.2.2.75 Suggest probe resolved_span.end schema**
**Given** `SuggestResponse.probe.resolved_span.end` violates schema, **when** consumed, **then** the system returns a contract error for end index schema failure.
**Error Mode:** PRE_suggestresponse_probe_resolved_span_end_SCHEMA
**Reference:** Inputs: `SuggestResponse.probe.resolved_span.end`

**6.2.2.76 Suggest probe placeholder_key schema**
**Given** `SuggestResponse.probe.placeholder_key` violates schema, **when** consumed, **then** the system returns a contract error for placeholder key schema failure.
**Error Mode:** PRE_suggestresponse_probe_placeholder_key_SCHEMA
**Reference:** Inputs: `SuggestResponse.probe.placeholder_key`

**6.2.2.77 Suggest probe doc_etag schema**
**Given** `SuggestResponse.probe.doc_etag` violates schema, **when** consumed, **then** the system returns a contract error for document ETag schema failure.
**Error Mode:** PRE_suggestresponse_probe_doc_etag_SCHEMA
**Reference:** Inputs: `SuggestResponse.probe.doc_etag`

**6.2.2.78 Suggest probe probe_hash schema**
**Given** `SuggestResponse.probe.probe_hash` violates schema, **when** consumed, **then** the system returns a contract error for probe hash schema failure.
**Error Mode:** PRE_suggestresponse_probe_probe_hash_SCHEMA
**Reference:** Inputs: `SuggestResponse.probe.probe_hash`

**6.2.2.79 BindResult etag provider error**
**Given** the bind operation failed upstream, **when** `BindResult.etag` is expected, **then** the system returns a contract error indicating provider error.
**Error Mode:** PRE_bindresult_etag_PROVIDER_ERROR
**Reference:** Inputs: `BindResult.etag` (returned)

**6.2.2.80 BindResult etag schema mismatch**
**Given** `BindResult.etag` violates schema, **when** consumed, **then** the system returns a contract error for ETag schema failure.
**Error Mode:** PRE_bindresult_etag_SCHEMA_MISMATCH
**Reference:** Inputs: `BindResult.etag` (returned)

**6.2.2.81 UnbindResponse etag provider error**
**Given** the unbind operation failed upstream, **when** `UnbindResponse.etag` is expected, **then** the system returns a contract error indicating provider error.
**Error Mode:** PRE_unbindresponse_etag_PROVIDER_ERROR
**Reference:** Inputs: `UnbindResponse.etag` (returned)

**6.2.2.82 UnbindResponse etag schema mismatch**
**Given** `UnbindResponse.etag` violates schema, **when** consumed, **then** the system returns a contract error for ETag schema failure.
**Error Mode:** PRE_unbindresponse_etag_SCHEMA_MISMATCH
**Reference:** Inputs: `UnbindResponse.etag` (returned)

**6.2.2.83 ListPlaceholdersResponse etag provider error**
**Given** the list operation failed upstream, **when** `ListPlaceholdersResponse.etag` is expected, **then** the system returns a contract error indicating provider error.
**Error Mode:** PRE_listplaceholdersresponse_etag_PROVIDER_ERROR
**Reference:** Inputs: `ListPlaceholdersResponse.etag` (returned)

**6.2.2.84 ListPlaceholdersResponse etag schema mismatch**
**Given** `ListPlaceholdersResponse.etag` violates schema, **when** consumed, **then** the system returns a contract error for ETag schema failure.
**Error Mode:** PRE_listplaceholdersresponse_etag_SCHEMA_MISMATCH
**Reference:** Inputs: `ListPlaceholdersResponse.etag` (returned)

**6.2.2.85 Suggestion missing**
**Given** a successful suggest call, **when** the payload lacks `suggestion`, **then** the system returns a contract error for missing suggestion object.
**Error Mode:** POST_suggestion_MISSING
**Reference:** Outputs: `suggestion`

**6.2.2.86 Suggestion schema invalid**
**Given** a suggest response, **when** `suggestion` violates schema, **then** the system returns a contract error for invalid suggestion object.
**Error Mode:** POST_suggestion_SCHEMA_INVALID
**Reference:** Outputs: `suggestion`

**6.2.2.87 Suggestion options not canonical**
**Given** a suggest response with `enum_single`, **when** `suggestion.options[].value` are not canonical, **then** the system returns a contract error for non-canonical options.
**Error Mode:** POST_suggestion_OPTIONS_NOT_CANONICAL
**Reference:** Outputs: `suggestion.options[]`

**6.2.2.88 Suggestion options non-deterministic**
**Given** identical probes produce differing `suggestion.options`, **when** compared, **then** the system returns a contract error for non-deterministic options.
**Error Mode:** POST_suggestion_OPTIONS_NON_DETERMINISTIC
**Reference:** Outputs: `suggestion.options[]`

**6.2.2.89 Probe missing**
**Given** a successful suggest call, **when** the payload lacks `probe`, **then** the system returns a contract error for missing probe.
**Error Mode:** POST_probe_MISSING
**Reference:** Outputs: `probe`

**6.2.2.90 Probe schema invalid**
**Given** a suggest response, **when** `probe` violates schema, **then** the system returns a contract error for invalid probe.
**Error Mode:** POST_probe_SCHEMA_INVALID
**Reference:** Outputs: `probe`

**6.2.2.91 Probe hash not stable**
**Given** identical probes result in different `probe.probe_hash`, **when** compared, **then** the system returns a contract error for unstable probe hash.
**Error Mode:** POST_probe_HASH_NOT_STABLE
**Reference:** Outputs: `probe.probe_hash`

**6.2.2.92 Probe resolved span mismatch**
**Given** `probe.resolved_span` does not match analysed selection, **when** verified, **then** the system returns a contract error for span mismatch.
**Error Mode:** POST_probe_RESOLVED_SPAN_MISMATCH
**Reference:** Outputs: `probe.resolved_span.start`, `probe.resolved_span.end`

**6.2.2.93 BindResult schema invalid**
**Given** a bind response, **when** `bind_result` violates schema, **then** the system returns a contract error for invalid bind result.
**Error Mode:** POST_bind_result_SCHEMA_INVALID
**Reference:** Outputs: `bind_result`

**6.2.2.94 BindResult etag not new**
**Given** a bind response, **when** `bind_result.etag` equals the prior ETag, **then** the system returns a contract error for non-updated ETag.
**Error Mode:** POST_bind_result_ETAG_NOT_NEW
**Reference:** Outputs: `bind_result.etag`

**6.2.2.95 BindResult etag empty**
**Given** a bind response, **when** `bind_result.etag` is empty, **then** the system returns a contract error for empty ETag.
**Error Mode:** POST_bind_result_ETAG_EMPTY
**Reference:** Outputs: `bind_result.etag`

**6.2.2.96 BindResult bound not true**
**Given** a successful bind, **when** `bind_result.bound` is not true, **then** the system returns a contract error for incorrect success flag.
**Error Mode:** POST_bind_result_BOUND_NOT_TRUE
**Reference:** Outputs: `bind_result.bound`

**6.2.2.97 BindResult bound missing**
**Given** a bind response, **when** `bind_result.bound` is missing, **then** the system returns a contract error for missing bound flag.
**Error Mode:** POST_bind_result_BOUND_MISSING
**Reference:** Outputs: `bind_result.bound`

**6.2.2.98 BindResult question_id invalid**
**Given** a bind response, **when** `bind_result.question_id` is not a UUID, **then** the system returns a contract error for invalid question id.
**Error Mode:** POST_bind_result_QUESTION_ID_INVALID
**Reference:** Outputs: `bind_result.question_id`

**6.2.2.99 BindResult question_id missing**
**Given** a bind response, **when** `bind_result.question_id` is missing, **then** the system returns a contract error for missing question id.
**Error Mode:** POST_bind_result_QUESTION_ID_MISSING
**Reference:** Outputs: `bind_result.question_id`

**6.2.2.100 BindResult placeholder_id invalid**
**Given** a bind response, **when** `bind_result.placeholder_id` is not a UUID, **then** the system returns a contract error for invalid placeholder id.
**Error Mode:** POST_bind_result_PLACEHOLDER_ID_INVALID
**Reference:** Outputs: `bind_result.placeholder_id`

**6.2.2.101 BindResult placeholder_id missing**
**Given** a bind response, **when** `bind_result.placeholder_id` is missing, **then** the system returns a contract error for missing placeholder id.
**Error Mode:** POST_bind_result_PLACEHOLDER_ID_MISSING
**Reference:** Outputs: `bind_result.placeholder_id`

**6.2.2.102 BindResult placeholder_id not persisted**
**Given** a bind response, **when** `bind_result.placeholder_id` does not reference a persisted row, **then** the system returns a contract error for non-persisted id.
**Error Mode:** POST_bind_result_PLACEHOLDER_ID_NOT_PERSISTED
**Reference:** Outputs: `bind_result.placeholder_id`

**6.2.2.103 BindResult answer_kind invalid**
**Given** a bind response, **when** `bind_result.answer_kind` is outside the declared enum, **then** the system returns a contract error for invalid answer kind.
**Error Mode:** POST_bind_result_ANSWER_KIND_INVALID
**Reference:** Outputs: `bind_result.answer_kind`

**6.2.2.104 BindResult answer_kind missing**
**Given** a bind response, **when** `bind_result.answer_kind` is missing, **then** the system returns a contract error for missing answer kind.
**Error Mode:** POST_bind_result_ANSWER_KIND_MISSING
**Reference:** Outputs: `bind_result.answer_kind`

**6.2.2.105 BindResult options present when not enum**
**Given** a bind response with non-enum answer kind, **when** `bind_result.options` is present, **then** the system returns a contract error for conditional emission breach.
**Error Mode:** POST_bind_result_OPTIONS_PRESENT_WHEN_NOT_ENUM
**Reference:** Outputs: `bind_result.options`

**6.2.2.106 BindResult options missing for enum**
**Given** a bind response with `enum_single`, **when** `bind_result.options` is missing, **then** the system returns a contract error for missing options.
**Error Mode:** POST_bind_result_OPTIONS_MISSING_FOR_ENUM
**Reference:** Outputs: `bind_result.options`

**6.2.2.107 BindResult options schema invalid**
**Given** a bind response, **when** an item in `bind_result.options` violates schema, **then** the system returns a contract error for invalid option object.
**Error Mode:** POST_bind_result_OPTIONS_SCHEMA_INVALID
**Reference:** Outputs: `bind_result.options[]`

**6.2.2.108 BindResult options values not unique**
**Given** a bind response, **when** `bind_result.options[].value` contain duplicates, **then** the system returns a contract error for non-unique option values.
**Error Mode:** POST_bind_result_OPTIONS_VALUES_NOT_UNIQUE
**Reference:** Outputs: `bind_result.options[]`

**6.2.2.109 BindResult options empty when expected**
**Given** a bind response where options were expected, **when** `bind_result.options` is empty, **then** the system returns a contract error for empty options set.
**Error Mode:** POST_bind_result_OPTIONS_EMPTY_WHEN_EXPECTED
**Reference:** Outputs: `bind_result.options[]`

**6.2.2.110 Unbind keys missing**
**Given** an unbind response, **when** any of `ok`, `question_id`, or `etag` is absent, **then** the system returns a contract error for missing keys.
**Error Mode:** POST_unbind_KEYS_MISSING
**Reference:** Outputs: `unbind.ok`, `unbind.question_id`, `unbind.etag`

**6.2.2.111 Unbind ok not true**
**Given** a successful unbind, **when** `unbind.ok` is not true, **then** the system returns a contract error for incorrect success flag.
**Error Mode:** POST_unbind_OK_NOT_TRUE
**Reference:** Outputs: `unbind.ok`

**6.2.2.112 Unbind question_id invalid**
**Given** an unbind response, **when** `unbind.question_id` is not a valid UUID, **then** the system returns a contract error for invalid question id.
**Error Mode:** POST_unbind_QUESTION_ID_INVALID
**Reference:** Outputs: `unbind.question_id`

**6.2.2.113 Unbind etag empty**
**Given** an unbind response, **when** `unbind.etag` is empty, **then** the system returns a contract error for empty ETag.
**Error Mode:** POST_unbind_ETAG_EMPTY
**Reference:** Outputs: `unbind.etag`

**6.2.2.114 Placeholders missing**
**Given** a successful list call, **when** `placeholders` is missing, **then** the system returns a contract error for missing result array.
**Error Mode:** POST_placeholders_MISSING
**Reference:** Outputs: `placeholders[]`

**6.2.2.115 Placeholders schema invalid**
**Given** a list response, **when** any item violates `Placeholder` schema, **then** the system returns a contract error for invalid list item.
**Error Mode:** POST_placeholders_SCHEMA_INVALID
**Reference:** Outputs: `placeholders[]`

**6.2.2.116 Placeholders order non-deterministic**
**Given** identical list requests, **when** item order differs, **then** the system returns a contract error for unstable ordering.
**Error Mode:** POST_placeholders_ORDER_NON_DETERMINISTIC
**Reference:** Outputs: `placeholders[]`

**6.2.2.117 Placeholder id missing**
**Given** a list item, **when** `id` is absent, **then** the system returns a contract error for missing placeholder id.
**Error Mode:** POST_placeholders_ID_MISSING
**Reference:** Outputs: `placeholders[].id`

**6.2.2.118 Placeholder id invalid**
**Given** a list item, **when** `id` is not a valid UUID, **then** the system returns a contract error for invalid placeholder id.
**Error Mode:** POST_placeholders_ID_INVALID
**Reference:** Outputs: `placeholders[].id`

**6.2.2.119 Placeholder id duplicate**
**Given** a list response, **when** two items share the same `id`, **then** the system returns a contract error for duplicate ids.
**Error Mode:** POST_placeholders_ID_DUPLICATE
**Reference:** Outputs: `placeholders[].id`

**6.2.2.120 Placeholder document_id invalid**
**Given** a list item, **when** `document_id` is not a valid UUID, **then** the system returns a contract error for invalid document id.
**Error Mode:** POST_placeholders_DOCUMENT_ID_INVALID
**Reference:** Outputs: `placeholders[].document_id`

**6.2.2.121 Placeholder document_id missing**
**Given** a list item, **when** `document_id` is missing, **then** the system returns a contract error for missing document id.
**Error Mode:** POST_placeholders_DOCUMENT_ID_MISSING
**Reference:** Outputs: `placeholders[].document_id`

**6.2.2.122 Placeholder clause_path empty**
**Given** a list item, **when** `clause_path` is empty or missing, **then** the system returns a contract error for invalid clause path.
**Error Mode:** POST_placeholders_CLAUSE_PATH_EMPTY
**Reference:** Outputs: `placeholders[].clause_path`

**6.2.2.123 Placeholder text_span missing**
**Given** a list item, **when** `text_span` is missing, **then** the system returns a contract error for missing span.
**Error Mode:** POST_placeholders_TEXT_SPAN_MISSING
**Reference:** Outputs: `placeholders[].text_span`

**6.2.2.124 Placeholder text_span schema invalid**
**Given** a list item, **when** `text_span` violates schema, **then** the system returns a contract error for invalid span object.
**Error Mode:** POST_placeholders_TEXT_SPAN_SCHEMA_INVALID
**Reference:** Outputs: `placeholders[].text_span`

**6.2.2.125 Placeholder text_span.start out of range**
**Given** a list item, **when** `text_span.start` is negative or non-integer, **then** the system returns a contract error for invalid start index.
**Error Mode:** POST_placeholders_TEXT_SPAN_START_OUT_OF_RANGE
**Reference:** Outputs: `placeholders[].text_span.start`

**6.2.2.126 Placeholder text_span.end out of range**
**Given** a list item, **when** `text_span.end` is negative or non-integer, **then** the system returns a contract error for invalid end index.
**Error Mode:** POST_placeholders_TEXT_SPAN_END_OUT_OF_RANGE
**Reference:** Outputs: `placeholders[].text_span.end`

**6.2.2.127 Placeholder text_span bounds invalid**
**Given** a list item, **when** `text_span.end < text_span.start`, **then** the system returns a contract error for invalid span bounds.
**Error Mode:** POST_placeholders_TEXT_SPAN_BOUNDS_INVALID
**Reference:** Outputs: `placeholders[].text_span`

**6.2.2.128 Placeholder question_id invalid**
**Given** a list item, **when** `question_id` is not a valid UUID, **then** the system returns a contract error for invalid question id.
**Error Mode:** POST_placeholders_QUESTION_ID_INVALID
**Reference:** Outputs: `placeholders[].question_id`

**6.2.2.129 Placeholder question_id missing**
**Given** a list item, **when** `question_id` is missing, **then** the system returns a contract error for missing question id.
**Error Mode:** POST_placeholders_QUESTION_ID_MISSING
**Reference:** Outputs: `placeholders[].question_id`

**6.2.2.130 Placeholder transform_id empty**
**Given** a list item, **when** `transform_id` is empty or missing, **then** the system returns a contract error for invalid transform id.
**Error Mode:** POST_placeholders_TRANSFORM_ID_EMPTY
**Reference:** Outputs: `placeholders[].transform_id`

**6.2.2.131 Placeholder payload_json invalid**
**Given** a list item, **when** `payload_json` is not a valid object, **then** the system returns a contract error for invalid payload.
**Error Mode:** POST_placeholders_PAYLOAD_JSON_INVALID
**Reference:** Outputs: `placeholders[].payload_json`

**6.2.2.132 Placeholder created_at invalid**
**Given** a list item, **when** `created_at` is not RFC3339 UTC, **then** the system returns a contract error for invalid timestamp.
**Error Mode:** POST_placeholders_CREATED_AT_INVALID
**Reference:** Outputs: `placeholders[].created_at`

**6.2.2.133 List ETag missing**
**Given** a successful list response, **when** `list_etag` is missing, **then** the system returns a contract error for missing list ETag.
**Error Mode:** POST_list_etag_MISSING
**Reference:** Outputs: `list_etag`

**6.2.2.134 List ETag empty**
**Given** a list response, **when** `list_etag` is empty, **then** the system returns a contract error for empty list ETag.
**Error Mode:** POST_list_etag_EMPTY
**Reference:** Outputs: `list_etag`

**6.2.2.135 List ETag not current**
**Given** a list response, **when** `list_etag` does not represent current state, **then** the system returns a contract error for stale list ETag.
**Error Mode:** POST_list_etag_NOT_CURRENT_STATE
**Reference:** Outputs: `list_etag`

**6.2.2.136 PurgeResponse schema invalid**
**Given** a purge response, **when** `purge_result` violates schema, **then** the system returns a contract error for invalid purge result.
**Error Mode:** POST_purge_result_SCHEMA_INVALID
**Reference:** Outputs: `purge_result`

**6.2.2.137 Purge deleted_placeholders negative**
**Given** a purge response, **when** `deleted_placeholders` is negative, **then** the system returns a contract error for invalid deletion count.
**Error Mode:** POST_purge_result_DELETED_PLACEHOLDERS_NEGATIVE
**Reference:** Outputs: `purge_result.deleted_placeholders`

**6.2.2.138 Purge updated_questions negative**
**Given** a purge response, **when** `updated_questions` is negative, **then** the system returns a contract error for invalid update count.
**Error Mode:** POST_purge_result_UPDATED_QUESTIONS_NEGATIVE
**Reference:** Outputs: `purge_result.updated_questions`

**6.2.2.139 Purge etag empty when present**
**Given** a purge response, **when** `purge_result.etag` is present but empty, **then** the system returns a contract error for empty ETag.
**Error Mode:** POST_purge_result_ETAG_EMPTY_WHEN_PRESENT
**Reference:** Outputs: `purge_result.etag`

**6.2.2.140 Catalog missing**
**Given** a successful catalog call, **when** `catalog` is missing, **then** the system returns a contract error for missing catalog list.
**Error Mode:** POST_catalog_MISSING
**Reference:** Outputs: `catalog[]`

**6.2.2.141 Catalog schema invalid**
**Given** a catalog response, **when** any item violates schema, **then** the system returns a contract error for invalid catalog item.
**Error Mode:** POST_catalog_SCHEMA_INVALID
**Reference:** Outputs: `catalog[]`

**6.2.2.142 Catalog order non-deterministic**
**Given** identical catalog requests, **when** item order differs, **then** the system returns a contract error for unstable ordering.
**Error Mode:** POST_catalog_ORDER_NON_DETERMINISTIC
**Reference:** Outputs: `catalog[]`

**6.2.2.143 Preview schema invalid**
**Given** a preview response, **when** `preview` violates schema, **then** the system returns a contract error for invalid preview.
**Error Mode:** POST_preview_SCHEMA_INVALID
**Reference:** Outputs: `preview`

**6.2.2.144 Preview answer_kind invalid**
**Given** a preview response, **when** `preview.answer_kind` is outside the enum, **then** the system returns a contract error for invalid answer kind.
**Error Mode:** POST_preview_ANSWER_KIND_INVALID
**Reference:** Outputs: `preview.answer_kind`

**6.2.2.145 Preview options present when not enum**
**Given** a preview with non-enum answer kind, **when** `preview.options` is present, **then** the system returns a contract error for conditional emission breach.
**Error Mode:** POST_preview_OPTIONS_PRESENT_WHEN_NOT_ENUM
**Reference:** Outputs: `preview.options`

**6.2.2.146 Preview options missing for enum**
**Given** a preview with `enum_single`, **when** `preview.options` is missing, **then** the system returns a contract error for missing options.
**Error Mode:** POST_preview_OPTIONS_MISSING_FOR_ENUM
**Reference:** Outputs: `preview.options`

**6.2.2.147 Problem schema invalid**
**Given** an error response, **when** `problem` violates schema, **then** the system returns a contract error for invalid Problem Details.
**Error Mode:** POST_problem_SCHEMA_INVALID
**Reference:** Outputs: `problem`

**6.2.2.148 Problem status invalid code**
**Given** an error response, **when** `problem.status` is not a valid HTTP status code, **then** the system returns a contract error for invalid status.
**Error Mode:** POST_problem_STATUS_INVALID_CODE
**Reference:** Outputs: `problem.status`

**6.2.2.149 Problem type missing or invalid**
**Given** an error response, **when** `problem.type` is missing or not a valid identifier/URI, **then** the system returns a contract error for invalid type.
**Error Mode:** POST_problem_TYPE_MISSING_OR_INVALID
**Reference:** Outputs: `problem.type`

**6.2.2.150 Problem title missing or empty**
**Given** an error response, **when** `problem.title` is missing or empty, **then** the system returns a contract error for invalid title.
**Error Mode:** POST_problem_TITLE_MISSING_OR_EMPTY
**Reference:** Outputs: `problem.title`

**6.2.2.151 Runtime: create entity DB write failed (bind)**
**Given** a bind operation attempts to persist a placeholder, **when** the database write fails, **then** the system returns a contract error reflecting the runtime write failure.
**Error Mode:** RUN_CREATE_ENTITY_DB_WRITE_FAILED
**Reference:** Outputs: `problem`

**6.2.2.152 Runtime: update entity DB write failed (set model)**
**Given** a first bind attempts to set the answer model, **when** the database update fails, **then** the system returns a contract error reflecting the runtime update failure.
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED
**Reference:** Outputs: `problem`

**6.2.2.153 Runtime: delete entity DB write failed (unbind)**
**Given** an unbind attempts to delete a placeholder, **when** the database delete fails, **then** the system returns a contract error reflecting the runtime delete failure.
**Error Mode:** RUN_DELETE_ENTITY_DB_WRITE_FAILED
**Reference:** Outputs: `problem`

**6.2.2.154 Runtime: delete entity DB write failed (purge)**
**Given** a purge attempts to delete placeholders for a document, **when** the batched delete fails, **then** the system returns a contract error reflecting the runtime delete failure.
**Error Mode:** RUN_DELETE_ENTITY_DB_WRITE_FAILED
**Reference:** Outputs: `problem`

**6.2.2.155 Runtime: retrieve entity DB read failed (list)**
**Given** a request to list placeholders, **when** the database read fails, **then** the system returns a contract error reflecting the runtime read failure.
**Error Mode:** RUN_RETRIEVE_ENTITY_DB_READ_FAILED
**Reference:** Outputs: `problem`

**6.2.2.156 Runtime: idempotency store unavailable**
**Given** a bind request with idempotency semantics, **when** the idempotency backend is unavailable, **then** the system returns a contract error reflecting the idempotency runtime failure.
**Error Mode:** RUN_IDEMPOTENCY_STORE_UNAVAILABLE
**Reference:** Outputs: `problem`

**6.2.2.157 Runtime: ETag compute failed**
**Given** a successful mutation requires ETag regeneration, **when** ETag computation fails, **then** the system returns a contract error reflecting the runtime ETag failure.
**Error Mode:** RUN_ETAG_COMPUTE_FAILED
**Reference:** Outputs: `problem`

**6.2.2.158 Runtime: concurrency token generation failed**
**Given** a write requires a concurrency token, **when** token generation fails, **then** the system returns a contract error reflecting the runtime token failure.
**Error Mode:** RUN_CONCURRENCY_TOKEN_GENERATION_FAILED
**Reference:** Outputs: `problem`

**6.2.2.159 Runtime: problem+json encoding failed**
**Given** an error must be returned, **when** serialising `application/problem+json` fails, **then** the system returns a contract error reflecting the runtime encoding failure.
**Error Mode:** RUN_PROBLEM_JSON_ENCODING_FAILED
**Reference:** Outputs: `problem`

**6.2.2.160 Runtime: nested linkage relation enforcement failed**
**Given** a child placeholder bind must link a parent option, **when** the relation update fails, **then** the system returns a contract error reflecting the linkage failure.
**Error Mode:** RUN_LINKAGE_RELATION_ENFORCEMENT_FAILED
**Reference:** Outputs: `problem`

**6.2.2.161 Runtime: unidentified error**
**Given** any Epic D operation occurs, **when** an unhandled execution error arises, **then** the system returns a contract error reflecting an unidentified runtime failure.
**Error Mode:** RUN_UNIDENTIFIED_ERROR
**Reference:** Outputs: `problem`

Great question — short answer: **both**.

* We **do** define **contractual ACs** for transform logic wherever the behaviour is externally observable at the API boundary (e.g., `/transforms/suggest` and `/transforms/preview` returning `answer_kind`, canonicalised `options`, stable `probe.probe_hash`).
* We keep **behavioural tests** for the internal rule engine sequencing and branching (e.g., tokenisation steps, precedence order), as those are implementation details not visible to a black-box client.

Below are **all Happy Path Contractual ACs in one place**, each tied to EARS references and Outputs fields.

6.2.1.1 Suggest returns single transform proposal
**Given** a valid `PlaceholderProbe` is submitted, **when** the client calls the transform suggestion endpoint, **then** the response includes exactly one transform proposal.
**Reference:** EARS U3, E1; Outputs: `suggestion`.

6.2.1.2 Suggest returns probe receipt for bind continuity
**Given** a valid `PlaceholderProbe` is submitted, **when** suggestion completes successfully, **then** the response includes a probe receipt for later bind continuity.
**Reference:** EARS U5, E1; Outputs: `probe`.

6.2.1.3 Suggest proposal exposes answer kind
**Given** a valid `PlaceholderProbe`, **when** suggestion completes, **then** the proposal specifies the answer kind for the placeholder.
**Reference:** EARS U2, U3, E1; Outputs: `suggestion.answer_kind`.

6.2.1.4 Suggest proposal canonicalises options
**Given** a placeholder that resolves to `enum_single`, **when** suggestion completes, **then** the options are present with canonical `value`s and preserved original `label`s.
**Reference:** EARS U3, U10, E1; Outputs: `suggestion.options[]`.

6.2.1.5 Suggest returns stable probe hash
**Given** a valid `PlaceholderProbe`, **when** suggestion completes, **then** the probe receipt includes a `probe_hash`.
**Reference:** EARS U5, E1; Outputs: `probe.probe_hash`.

6.2.1.6 Bind returns success result
**Given** a selected transform and associated probe/probe_hash, **when** the placeholder is bound to a question, **then** the response indicates a successful bind.
**Reference:** EARS U6, E2; Outputs: `bind_result.bound`.

6.2.1.7 Bind returns persisted placeholder identifier
**Given** a successful bind, **when** the response is returned, **then** it includes the identifier of the persisted placeholder.
**Reference:** EARS U6, E2; Outputs: `bind_result.placeholder_id`.

6.2.1.8 Bind sets/returns the question answer kind
**Given** a first binding for a question, **when** bind completes, **then** the response specifies the question’s answer kind.
**Reference:** EARS U7, E3; Outputs: `bind_result.answer_kind`.

6.2.1.9 Bind returns canonical option set for enum_single
**Given** a first binding yields `enum_single`, **when** bind completes, **then** the response includes the canonical option set.
**Reference:** EARS U7, E3; Outputs: `bind_result.options[]`.

6.2.1.10 Bind maintains model consistency on subsequent binds
**Given** a question already has an answer model, **when** a consistent placeholder is bound, **then** the response reflects the existing answer kind.
**Reference:** EARS U7, E4, S1; Outputs: `bind_result.answer_kind`.

6.2.1.11 Nested linkage is reflected in parent option
**Given** a parent option references a nested placeholder key, **when** the child placeholder is later bound, **then** the parent option in the response includes the child `placeholder_id`.
**Reference:** EARS E5, S3; Outputs: `bind_result.options[].placeholder_id`.

6.2.1.12 Bind returns updated concurrency token
**Given** a successful bind, **when** the response is returned, **then** it includes a new question ETag.
**Reference:** EARS U8, E2; Outputs: `bind_result.etag`.

6.2.1.13 Unbind returns success projection
**Given** a specific placeholder identifier, **when** unbind completes successfully, **then** the response projection indicates success and returns the updated ETag.
**Reference:** EARS E9; Outputs: `unbind.ok`, `unbind.etag`.

6.2.1.14 List returns placeholders for a question
**Given** a question identifier (optionally filtered by document), **when** the list endpoint succeeds, **then** the response returns the placeholders for that question.
**Reference:** EARS U9, S3; Outputs: `placeholders[]`.

6.2.1.15 List includes stable question ETag
**Given** a successful list response, **when** placeholders are returned, **then** the response includes the current question ETag.
**Reference:** EARS U9, E14; Outputs: `list_etag`.

6.2.1.16 Purge returns deletion summary
**Given** a document deletion cleanup is requested, **when** purge completes successfully, **then** the response includes counts of deleted placeholders and updated questions.
**Reference:** EARS U9, E6, E12; Outputs: `purge_result.deleted_placeholders`, `purge_result.updated_questions`.

6.2.1.17 Catalog returns supported transforms
**Given** a catalog request, **when** it succeeds, **then** the response includes the list of supported transforms.
**Reference:** EARS U9, E10; Outputs: `catalog[]`.

6.2.1.18 Preview returns answer kind
**Given** a preview request with `raw_text` or `literals`, **when** preview completes, **then** the response includes the inferred answer kind.
**Reference:** EARS U3, E11; Outputs: `preview.answer_kind`.

6.2.1.19 Preview returns canonical options for enum_single
**Given** a preview that resolves to `enum_single`, **when** preview completes, **then** the response includes the canonical option set.
**Reference:** EARS U3, E11; Outputs: `preview.options[]`.

6.2.1.20 Listing preserves document and clause references
**Given** placeholders are listed, **when** the response is returned, **then** each placeholder includes its `document_id` and `clause_path`.
**Reference:** EARS S3; Outputs: `placeholders[].document_id`, `placeholders[].clause_path`.

6.2.1.21 Listing includes span coordinates
**Given** placeholders are listed, **when** the response is returned, **then** each placeholder includes its start and end character indices.
**Reference:** EARS S3; Outputs: `placeholders[].text_span.start`, `placeholders[].text_span.end`.

6.2.1.22 Idempotent bind returns same placeholder identifier
**Given** the same bind request is retried with the same `Idempotency-Key`, **when** bind completes, **then** the response contains the same `placeholder_id` as the original success.
**Reference:** EARS U8, E2; Outputs: `bind_result.placeholder_id`.

6.2.1.23 Suggest is stateless with no persistence side-effects
**Given** a suggestion request, **when** it completes successfully, **then** no persisted placeholder is created and only the proposal and probe are returned.
**Reference:** EARS U6, E1; Outputs: `suggestion`, `probe`.

6.2.1.24 Purge idempotence reflected in counts
**Given** a purge is called for a document that has already been cleaned, **when** purge completes, **then** the response shows zero additional deletions.
**Reference:** EARS E7; Outputs: `purge_result.deleted_placeholders`.

6.2.1.25 Consistent listing after unbind of last placeholder
**Given** a question whose last placeholder has been unbound, **when** placeholders are listed, **then** the response contains an empty array.
**Reference:** EARS E8; Outputs: `placeholders[]`.

**6.2.1.26 Suggest → short_string**
**Given** a placeholder that matches the short text pattern, **when** suggestion completes, **then** the proposal reports `answer_kind = "short_string"` and no options are present.
**Reference:** EARS U3, E1; Outputs: `suggestion.answer_kind`, absence of `suggestion.options`.

**6.2.1.27 Suggest → long_text**
**Given** a placeholder that matches the long text pattern (no line breaks allowed for short; length exceeds short threshold), **when** suggestion completes, **then** the proposal reports `answer_kind = "long_text"` and no options are present.
**Reference:** EARS U3, E1; Outputs: `suggestion.answer_kind`, absence of `suggestion.options`.

**6.2.1.28 Suggest → number**
**Given** a placeholder that matches a numeric pattern, **when** suggestion completes, **then** the proposal reports `answer_kind = "number"` and no options are present.
**Reference:** EARS U3, E1; Outputs: `suggestion.answer_kind`, absence of `suggestion.options`.

**6.2.1.29 Suggest → boolean (inclusion toggle)**
**Given** a placeholder that expresses binary inclusion/exclusion, **when** suggestion completes, **then** the proposal reports `answer_kind = "boolean"` and no options are present.
**Reference:** EARS U3, E1; Outputs: `suggestion.answer_kind`, absence of `suggestion.options`.

**6.2.1.30 Suggest → enum_single (literal-only)**
**Given** a placeholder that is a finite literal list, **when** suggestion completes, **then** the proposal reports `answer_kind = "enum_single"` with options whose `value` are canonical UPPER_SNAKE_CASE and whose `label` preserves the original literal text.
**Reference:** EARS U3, U10, E1; Outputs: `suggestion.answer_kind`, `suggestion.options[].value`, `suggestion.options[].label`.

**6.2.1.31 Suggest → enum_single (literal + nested placeholder)**
**Given** a placeholder that mixes literals and a nested placeholder, **when** suggestion completes, **then** the proposal includes one option per literal (canonicalised) and one option whose `value` equals the nested `placeholder_key` with `placeholder_id = null`.
**Reference:** EARS O1, E1; Outputs: `suggestion.options[].value`, `suggestion.options[].placeholder_id`, `suggestion.options[].placeholder_key`.

**6.2.1.32 Suggest labels for nested placeholder option**
**Given** a suggestion with a nested placeholder option, **when** the option is returned with `placeholder_id = null`, **then** the option’s `label` uses the canonical token as the display value.
**Reference:** EARS O1, E1; Outputs: `suggestion.options[].label`, `suggestion.options[].placeholder_id`.

**6.2.1.33 Suggest determinism (kind + options order)**
**Given** two identical probes, **when** suggestion is called, **then** `suggestion.answer_kind` and the order of `suggestion.options[]` are identical across calls.
**Reference:** EARS U3, E1; Outputs: `suggestion.answer_kind`, `suggestion.options[]` (ordering).

**6.2.1.34 Bind (first) → non-enum types omit options**
**Given** a first binding that sets `answer_kind` to a non-enum type, **when** bind completes, **then** `bind_result.options` is omitted.
**Reference:** EARS E3; Outputs: absence of `bind_result.options`, `bind_result.answer_kind`.

**6.2.1.35 Bind (first) → enum_single literal-only**
**Given** a first binding for an enum literal-only suggestion, **when** bind completes, **then** `bind_result.options[]` equals the canonical option set returned by suggestion.
**Reference:** EARS E3, S1; Outputs: `bind_result.options[]`.

**6.2.1.36 Bind (first) → enum_single with nested placeholder (child not yet bound)**
**Given** a first binding for a parent enum that includes a nested placeholder option and the child is not yet bound, **when** bind completes, **then** the parent’s nested option carries `placeholder_key` and `placeholder_id = null`.
**Reference:** EARS E3, E5, S3; Outputs: `bind_result.options[].placeholder_key`, `bind_result.options[].placeholder_id`.

**6.2.1.37 Bind (subsequent) → nested linkage update**
**Given** a child placeholder within a previously bound parent enum option is now bound, **when** bind completes, **then** the parent option for that key has `placeholder_id` populated.
**Reference:** EARS E5, S3; Outputs: `bind_result.options[].placeholder_id`.

**6.2.1.38 Preview mirrors suggestion (kind + options)**
**Given** a preview request equivalent to a suggestion probe, **when** preview completes, **then** `preview.answer_kind` and (if enum) `preview.options[]` follow the same canonicalisation and ordering rules as suggestion.
**Reference:** EARS E11, U3; Outputs: `preview.answer_kind`, `preview.options[]`.

**6.2.1.39 List reflects latest nested linkage state**
**Given** parent/child bindings occurred in sequence, **when** placeholders are listed, **then** any parent enum option that targets a now-bound child reflects the populated `placeholder_id`.
**Reference:** EARS E5, S3; Outputs: `placeholders[]` (via stored option payloads where exposed), or `bind_result.options[]` immediately post-bind.

#### 6.3.2.1

**Title:** Bind write fails halts binding flow
**Criterion:** Given a valid bind request is executing, when persisting a new placeholder row fails at write time, then halt STEP-2 Bind and stop propagation to STEP-3 Inspect.
**Error Mode:** `RUN_CREATE_ENTITY_DB_WRITE_FAILED`
**Reference:** (step: STEP-2 Bind)

#### 6.3.2.2

**Title:** First-bind model update fails halts binding flow
**Criterion:** Given a first binding is setting `answer_kind` and options, when the question model update fails, then halt STEP-2 Bind and stop propagation to STEP-3 Inspect.
**Error Mode:** `RUN_UPDATE_ENTITY_DB_WRITE_FAILED`
**Reference:** (step: STEP-2 Bind)

#### 6.3.2.3

**Title:** Unbind delete fails halts inspection flow
**Criterion:** Given an unbind operation is in progress, when deleting the placeholder row fails, then halt STEP-3 Inspect and stop propagation to STEP-4 Cleanup on document deletion.
**Error Mode:** `RUN_DELETE_ENTITY_DB_WRITE_FAILED`
**Reference:** (step: STEP-3 Inspect)

#### 6.3.2.4

**Title:** Listing read fails halts inspection flow
**Criterion:** Given placeholders are being listed for a question, when the database read fails, then halt STEP-3 Inspect and stop propagation to STEP-4 Cleanup on document deletion.
**Error Mode:** `RUN_RETRIEVE_ENTITY_DB_READ_FAILED`
**Reference:** (step: STEP-3 Inspect)

#### 6.3.2.5

**Title:** Idempotency backend unavailable halts binding flow
**Criterion:** Given bind is verifying idempotency, when the idempotency store is unavailable, then halt STEP-2 Bind and stop propagation to STEP-3 Inspect.
**Error Mode:** `RUN_IDEMPOTENCY_STORE_UNAVAILABLE`
**Reference:** (step: STEP-2 Bind)

#### 6.3.2.6

**Title:** ETag computation failure blocks completion of write step
**Criterion:** Given a bind or unbind operation has otherwise succeeded, when ETag computation fails, then block finalization of STEP-2/STEP-3 and stop propagation to STEP-3 Inspect.
**Error Mode:** `RUN_ETAG_COMPUTE_FAILED`
**Reference:** (step: STEP-2 Bind, STEP-3 Inspect)

#### 6.3.2.7

**Title:** Concurrency token generation failure blocks completion of write step
**Criterion:** Given a bind or unbind operation requires a new concurrency token, when token generation fails, then block finalization of STEP-2/STEP-3 and stop propagation to STEP-3 Inspect.
**Error Mode:** `RUN_CONCURRENCY_TOKEN_GENERATION_FAILED`
**Reference:** (step: STEP-2 Bind, STEP-3 Inspect)

#### 6.3.2.8

**Title:** Problem+JSON serialisation failure blocks response
**Criterion:** Given any Epic D endpoint is returning an error, when problem+json encoding fails, then block finalization of the current step and stop propagation to its downstream step (STEP-1→STEP-2, STEP-2→STEP-3, STEP-3→STEP-4).
**Error Mode:** `RUN_PROBLEM_JSON_ENCODING_FAILED`
**Reference:** (step: STEP-1 Explore and decide, STEP-2 Bind, STEP-3 Inspect, STEP-4 Cleanup on document deletion)

#### 6.3.2.9

**Title:** Parent–child linkage enforcement fails halts binding flow
**Criterion:** Given a nested placeholder link is being established during bind, when enforcing the parent option’s `placeholder_id` linkage fails, then halt STEP-2 Bind and stop propagation to STEP-3 Inspect.
**Error Mode:** `RUN_LINKAGE_RELATION_ENFORCEMENT_FAILED`
**Reference:** (step: STEP-2 Bind)

#### 6.3.2.10

**Title:** Purge delete fails halts cleanup flow
**Criterion:** Given document-level purge is removing placeholders, when the deletion batch fails, then halt STEP-4 Cleanup on document deletion and stop propagation to pipeline completion.
**Error Mode:** `RUN_DELETE_ENTITY_DB_WRITE_FAILED`
**Reference:** (step: STEP-4 Cleanup on document deletion)

#### 6.3.2.11

**Title:** Unidentified runtime failure halts current step
**Criterion:** Given any Epic D step is executing, when an unidentified runtime error is raised, then halt the current step and stop propagation to its downstream step (STEP-1→STEP-2, STEP-2→STEP-3, STEP-3→STEP-4).
**Error Mode:** `RUN_UNIDENTIFIED_ERROR`
**Reference:** (step: STEP-1 Explore and decide, STEP-2 Bind, STEP-3 Inspect, STEP-4 Cleanup on document deletion)

---

#### 6.3.2.12

**Title:** Suggestion response build failure blocks transform flow
**Criterion:** Given a transform suggestion is being returned, when the error response cannot be encoded as problem+json, then block finalization of STEP-1 Explore and decide and stop propagation to STEP-2 Bind.
**Error Mode:** `RUN_PROBLEM_JSON_ENCODING_FAILED`
**Reference:** (step: STEP-1 Explore and decide)

#### 6.3.2.13

**Title:** Option linkage set-up failure halts transform-backed bind
**Criterion:** Given a transform with a nested placeholder option is being applied, when establishing the option→child `placeholder_id` link fails, then halt STEP-2 Bind and stop propagation to STEP-3 Inspect.
**Error Mode:** `RUN_LINKAGE_RELATION_ENFORCEMENT_FAILED`
**Reference:** (step: STEP-2 Bind)

#### 6.3.2.14

**Title:** Deterministic model update write failure halts transform application
**Criterion:** Given a transform application is updating `answer_kind` and options on first bind, when the write fails, then halt STEP-2 Bind and stop propagation to STEP-3 Inspect.
**Error Mode:** `RUN_UPDATE_ENTITY_DB_WRITE_FAILED`
**Reference:** (step: STEP-2 Bind)

#### 6.3.2.15

**Title:** Idempotent transform application cannot verify key halts bind
**Criterion:** Given a transform application is verifying idempotency, when the idempotency store is unavailable, then halt STEP-2 Bind and stop propagation to STEP-3 Inspect.
**Error Mode:** `RUN_IDEMPOTENCY_STORE_UNAVAILABLE`
**Reference:** (step: STEP-2 Bind)

#### 6.3.2.16

**Title:** Suggestion engine runtime failure halts exploration flow
**Criterion:** Given a transform suggestion is being computed, when an internal runtime failure occurs in the suggestion engine, then halt STEP-1 Explore and decide and stop propagation to STEP-2 Bind.
**Error Mode:** `RUN_UNIDENTIFIED_ERROR`
**Reference:** (step: STEP-1 Explore and decide)

#### 6.3.2.17

**Title:** Preview transform runtime failure halts exploration flow
**Criterion:** Given a transform preview is being computed, when an internal runtime failure occurs in the preview path, then halt STEP-1 Explore and decide and stop propagation to STEP-2 Bind.
**Error Mode:** `RUN_UNIDENTIFIED_ERROR`
**Reference:** (step: STEP-1 Explore and decide)

#### 6.3.2.18

**Title:** Database unavailable halts binding and inspection
**Criterion:** Given persistence requires the primary database, when the database becomes unavailable, then halt STEP-2 Bind and stop propagation to STEP-3 Inspect.
**Error Mode:** `ENV_DB_UNAVAILABLE`
**Reference:** (dependency: database; steps: STEP-2 Bind → STEP-3 Inspect)

#### 6.3.2.19

**Title:** Database permission denied halts mutation flow
**Criterion:** Given binding requires write access to the database, when permission is denied, then halt STEP-2 Bind and stop propagation to STEP-3 Inspect.
**Error Mode:** `ENV_DB_PERMISSION_DENIED`
**Reference:** (dependency: database IAM/roles; steps: STEP-2 Bind → STEP-3 Inspect)

#### 6.3.2.20

**Title:** Cache backend unavailable does not block bind; skips cache usage
**Criterion:** Given suggestion or list would use a cache, when the cache backend is unavailable, then bypass cache in STEP-1 Explore and decide and continue to STEP-2 Bind.
**Error Mode:** `ENV_CACHE_UNAVAILABLE`
**Reference:** (dependency: cache; steps: STEP-1 Explore and decide → continue to STEP-2 Bind)

#### 6.3.2.21

**Title:** Message broker unavailable halts cleanup eventing
**Criterion:** Given cleanup publishes document-deleted events, when the message broker is unavailable, then halt STEP-4 Cleanup on document deletion and stop propagation to pipeline completion.
**Error Mode:** `ENV_MESSAGE_BROKER_UNAVAILABLE`
**Reference:** (dependency: message broker; steps: STEP-4 Cleanup on document deletion)

#### 6.3.2.22

**Title:** Object storage unavailable halts purge
**Criterion:** Given purge must delete document-scoped artefacts in object storage, when object storage is unavailable, then halt STEP-4 Cleanup on document deletion and stop propagation to pipeline completion.
**Error Mode:** `ENV_OBJECT_STORAGE_UNAVAILABLE`
**Reference:** (dependency: object storage; steps: STEP-4 Cleanup on document deletion)

#### 6.3.2.23

**Title:** Object storage permission denied prevents purge
**Criterion:** Given purge requires deletion privileges in object storage, when permission is denied, then halt STEP-4 Cleanup on document deletion and stop propagation to pipeline completion.
**Error Mode:** `ENV_OBJECT_STORAGE_PERMISSION_DENIED`
**Reference:** (dependency: object storage IAM; steps: STEP-4 Cleanup on document deletion)

#### 6.3.2.24

**Title:** Network unreachable halts suggestion and listing
**Criterion:** Given suggestion or listing requires network calls, when the network is unreachable, then halt STEP-1 Explore and decide and stop propagation to STEP-2 Bind.
**Error Mode:** `ENV_NETWORK_UNREACHABLE`
**Reference:** (dependency: network; steps: STEP-1 Explore and decide → STEP-2 Bind)

#### 6.3.2.25

**Title:** DNS resolution failure halts suggestion path
**Criterion:** Given suggestion depends on resolving service endpoints, when DNS resolution fails, then halt STEP-1 Explore and decide and stop propagation to STEP-2 Bind.
**Error Mode:** `ENV_DNS_RESOLUTION_FAILED`
**Reference:** (dependency: DNS; steps: STEP-1 Explore and decide → STEP-2 Bind)

#### 6.3.2.26

**Title:** TLS handshake failure halts API calls
**Criterion:** Given endpoints require TLS, when the TLS handshake fails, then halt STEP-1 Explore and decide and stop propagation to STEP-2 Bind.
**Error Mode:** `ENV_TLS_HANDSHAKE_FAILED`
**Reference:** (dependency: TLS/PKI; steps: STEP-1 Explore and decide → STEP-2 Bind)

#### 6.3.2.27

**Title:** Disk space exhausted blocks write finalisation
**Criterion:** Given binding and purge write to storage, when local disk space is exhausted, then block finalization of STEP-2 Bind or STEP-4 Cleanup on document deletion and stop propagation to their downstream steps.
**Error Mode:** `ENV_DISK_SPACE_EXHAUSTED`
**Reference:** (dependency: filesystem/disk; steps: STEP-2 Bind, STEP-4 Cleanup on document deletion)

#### 6.3.2.28

**Title:** Temp directory unavailable halts suggestion preprocessing
**Criterion:** Given suggestion requires temporary workspace, when the temp directory is unavailable, then halt STEP-1 Explore and decide and stop propagation to STEP-2 Bind.
**Error Mode:** `ENV_TEMP_DIR_UNAVAILABLE`
**Reference:** (dependency: filesystem/tmp; steps: STEP-1 Explore and decide → STEP-2 Bind)

#### 6.3.2.29

**Title:** AI endpoint unavailable halts suggestion
**Criterion:** Given suggestion uses an AI endpoint for tokenisation or heuristics, when the AI endpoint is unavailable, then halt STEP-1 Explore and decide and stop propagation to STEP-2 Bind.
**Error Mode:** `ENV_AI_ENDPOINT_UNAVAILABLE`
**Reference:** (dependency: AI service; steps: STEP-1 Explore and decide → STEP-2 Bind)

#### 6.3.2.30

**Title:** GPU resources unavailable halts suggestion compute
**Criterion:** Given the suggestion path requires GPU acceleration, when GPU resources are unavailable, then halt STEP-1 Explore and decide and stop propagation to STEP-2 Bind.
**Error Mode:** `ENV_GPU_RESOURCES_UNAVAILABLE`
**Reference:** (dependency: GPU runtime; steps: STEP-1 Explore and decide → STEP-2 Bind)

#### 6.3.2.31

**Title:** API rate limit exceeded skips non-critical cache refresh
**Criterion:** Given cache priming is non-critical during listing, when the upstream rate limit is exceeded, then skip cache refresh in STEP-1 Explore and decide and continue to STEP-2 Bind.
**Error Mode:** `ENV_API_RATE_LIMIT_EXCEEDED`
**Reference:** (dependency: upstream API; steps: STEP-1 Explore and decide → continue to STEP-2 Bind)

#### 6.3.2.32

**Title:** API quota exceeded halts suggestion
**Criterion:** Given suggestion depends on an upstream quota, when the quota is exceeded, then halt STEP-1 Explore and decide and stop propagation to STEP-2 Bind.
**Error Mode:** `ENV_API_QUOTA_EXCEEDED`
**Reference:** (dependency: upstream API; steps: STEP-1 Explore and decide → STEP-2 Bind)

#### 6.3.2.33

**Title:** Time synchronisation failed blocks idempotency validation
**Criterion:** Given idempotency validation relies on time-ordered tokens, when system time is unsynchronised, then block finalization of STEP-2 Bind and stop propagation to STEP-3 Inspect.
**Error Mode:** `ENV_TIME_SYNCHRONISATION_FAILED`
**Reference:** (dependency: system clock/NTP; steps: STEP-2 Bind → STEP-3 Inspect)

7.1.1 Distinct modules for suggestion and binding
Purpose: Verify that transform suggestion and placeholder binding are implemented in separate modules exposed via distinct route handlers.
Test Data: Application routing registry (runtime object); project root.
Mocking: No mocking for static check of handler module origins; use runtime router introspection to obtain handler module paths/names.
Assertions:

* Router contains handler for `/api/v1/transforms/suggest`;
* Router contains handler for `/api/v1/placeholders/bind`;
* The two handlers originate from different modules (module identifiers not equal).
  AC-Ref: 6.1.1

7.1.2 Suggest endpoint has no persistence imports (stateless)
Purpose: Ensure the suggestion handler module does not import persistence or ORM/database layers.
Test Data: Module object for suggestion handler resolved from routing registry.
Mocking: No mocking; static import graph inspection of the module’s dependencies.
Assertions:

* Import graph for suggestion handler module does not include persistence/ORM/DB modules (e.g., repositories, transaction managers, migrations).
  AC-Ref: 6.1.3

7.1.3 Preview endpoint has no persistence imports (isolation)
Purpose: Ensure the preview handler module is isolated from persistence.
Test Data: Module object for `/api/v1/transforms/preview`.
Mocking: No mocking; static import graph inspection.
Assertions:

* Import graph for preview handler module excludes persistence/ORM/DB modules.
  AC-Ref: 6.1.19

7.1.4 Bind and unbind handlers require concurrency & idempotency headers
Purpose: Ensure write endpoints validate `If-Match` and (for bind) `Idempotency-Key` headers via shared schema.
Test Data: schemas/HttpHeaders.json; route metadata for bind and unbind validators.
Mocking: No mocking; file-system read of schema and inspection of validator wiring.
Assertions:

* File `schemas/HttpHeaders.json` exists and is readable;
* Schema defines `Idempotency-Key` and `If-Match` properties;
* Bind validator references `schemas/HttpHeaders.json` and marks `Idempotency-Key` required;
* Bind and unbind validators reference `If-Match` as required.
  AC-Ref: 6.1.10, 6.1.16

7.1.5 PlaceholderProbe schema is reused by suggest and bind
Purpose: Ensure both flows use the same PlaceholderProbe schema.
Test Data: schemas/PlaceholderProbe.json; suggest and bind request validator metadata.
Mocking: No mocking; file-system read plus validator wiring inspection.
Assertions:

* File `schemas/PlaceholderProbe.json` exists;
* Suggest validator references `schemas/PlaceholderProbe.json` for the probe structure;
* Bind validator references `schemas/PlaceholderProbe.json` (directly or via ProbeReceipt linkage).
  AC-Ref: 6.1.2

7.1.6 ProbeReceipt schema present and referenced
Purpose: Ensure ProbeReceipt is defined and referenced by suggestion response and bind request.
Test Data: schemas/ProbeReceipt.json; schemas/SuggestResponse.json; bind request validator wiring.
Mocking: No mocking.
Assertions:

* Files `schemas/ProbeReceipt.json` and `schemas/SuggestResponse.json` exist;
* `schemas/SuggestResponse.json` includes a `probe` property `$ref` to `schemas/ProbeReceipt.json`;
* Bind validator accepts `probe` via `$ref` to `schemas/ProbeReceipt.json`.
  AC-Ref: 6.1.2

7.1.7 TransformSuggestion schema defines answer_kind and options
Purpose: Ensure `TransformSuggestion` exposes `answer_kind` and `options` with correct typing.
Test Data: schemas/TransformSuggestion.json.
Mocking: No mocking.
Assertions:

* File exists;
* `answer_kind` property present and constrained by `$ref: schemas/AnswerKind.json` or inline enum;
* `options` property present (array) with `items` `$ref: schemas/OptionSpec.json`.
  AC-Ref: 6.1.11

7.1.8 AnswerKind enumeration contains all supported kinds
Purpose: Ensure canonical enum set is centrally declared.
Test Data: schemas/AnswerKind.json.
Mocking: No mocking.
Assertions:

* File exists;
* Enum includes exactly: `short_string`, `long_text`, `boolean`, `number`, `enum_single`.
  AC-Ref: 6.1.28

7.1.9 OptionSpec enforces canonical value form
Purpose: Enforce uppercase snake-case values at schema level where possible.
Test Data: schemas/OptionSpec.json.
Mocking: No mocking.
Assertions:

* File exists;
* `properties.value` is a string and includes a `pattern` or equivalent constraint compatible with `^[A-Z0-9_]+$`;
* `properties.label` is an optional string;
* `properties.placeholder_key` is an optional string.
  AC-Ref: 6.1.6

7.1.10 Stable ordering validation hook present in response path
Purpose: Ensure API response pipeline contains an ordered emission step for enum options.
Test Data: Response serialization middleware/utility module used by suggest and bind handlers.
Mocking: No mocking; static inspection of response builder to verify a sorting step by canonical `value`.
Assertions:

* Common response path includes an explicit sort or deterministic order step for `options` arrays.
  AC-Ref: 6.1.7

7.1.11 ProblemDetails schema exists and is wired for all endpoints
Purpose: Ensure non-2xx responses use a consistent `application/problem+json` schema.
Test Data: schemas/ProblemDetails.json; global error middleware configuration.
Mocking: No mocking.
Assertions:

* File exists;
* Error middleware serializes errors using `schemas/ProblemDetails.json`;
* Content-Type for error responses is `application/problem+json`.
  AC-Ref: 6.1.17

7.1.12 All referenced schemas reside under root `schemas/` directory
Purpose: Enforce canonical schema directory location.
Test Data: File system under project root.
Mocking: No mocking.
Assertions:

* The following files exist at the exact paths:

  * schemas/PlaceholderProbe.json
  * schemas/ProbeReceipt.json
  * schemas/TransformSuggestion.json
  * schemas/OptionSpec.json
  * schemas/AnswerKind.json
  * schemas/SuggestResponse.json
  * schemas/BindRequest.json
  * schemas/BindResult.json
  * schemas/UnbindResponse.json
  * schemas/ListPlaceholdersResponse.json
  * schemas/Placeholder.json
  * schemas/Span.json
  * schemas/TransformsCatalogResponse.json
  * schemas/TransformsCatalogItem.json
  * schemas/TransformsPreviewRequest.json
  * schemas/TransformsPreviewResponse.json
  * schemas/PurgeRequest.json
  * schemas/PurgeResponse.json
  * schemas/ProblemDetails.json
  * schemas/HttpHeaders.json
    AC-Ref: 6.1.23, 6.1.11

7.1.13 Purge request/response schemas present
Purpose: Validate event-driven purge payload contracts exist.
Test Data: schemas/PurgeRequest.json, schemas/PurgeResponse.json.
Mocking: No mocking.
Assertions:

* Both files exist and are readable;
* `PurgeResponse.json` defines integer `deleted_placeholders` and `updated_questions` (≥0 via schema constraints).
  AC-Ref: 6.1.20, 6.1.29

7.1.14 Placeholders list item schema includes required identifiers and timestamps
Purpose: Ensure list response items carry IDs, document linkage, clause path, span, and UTC timestamps.
Test Data: schemas/Placeholder.json; schemas/ListPlaceholdersResponse.json; schemas/Span.json.
Mocking: No mocking.
Assertions:

* `Placeholder.json` defines `id`, `document_id`, `clause_path`, `text_span` (`$ref: schemas/Span.json`), `question_id`, `transform_id`, `created_at`;
* `created_at` has `format: date-time`;
* `ListPlaceholdersResponse.json` `items` reference `schemas/Placeholder.json`.
  AC-Ref: 6.1.25, 6.1.11

7.1.15 Read vs write model separation (imports)
Purpose: Ensure read handlers do not share transactional/write-layer dependencies used by write handlers.
Test Data: Module objects for list (`GET /api/v1/questions/{id}/placeholders`), catalog, preview, and for bind/unbind/purge.
Mocking: No mocking; import graph inspection.
Assertions:

* Read handler modules (list, catalog, preview) import no transaction manager/write repositories;
* Write handler modules (bind, unbind, purge) may import write layers; ensure no reverse import from read modules into write modules.
  AC-Ref: 6.1.21

7.1.16 ETag regeneration function invoked after bind and unbind
Purpose: Ensure a dedicated ETag generation utility is called by both bind and unbind flows.
Test Data: Bind and unbind handler modules; etag utility module.
Mocking: Use spies to intercept calls to the ETag utility; mocking is required to observe runtime invocation without performing actual writes.
Assertions:

* Bind handler calls ETag utility exactly once per successful bind;
* Unbind handler calls ETag utility exactly once per successful unbind.
  AC-Ref: 6.1.22

7.1.17 Transform registry is static and used by catalog
Purpose: Ensure transform identifiers are provided by a single static registry used by the catalog endpoint.
Test Data: Transform registry module (static constant); catalog handler module.
Mocking: No mocking for static presence; optional spy to verify catalog reads from the registry.
Assertions:

* A single module exposes a constant registry of supported transform IDs;
* Catalog handler imports that registry and maps it directly to response (no dynamic DB reads).
  AC-Ref: 6.1.24, 6.1.18

7.1.18 Response schema validation middleware is enabled globally
Purpose: Ensure all epic endpoints validate responses against their schemas before transmission.
Test Data: Global middleware configuration; per-route response schema bindings.
Mocking: No mocking; inspect router/middleware wiring.
Assertions:

* Response-validation middleware is registered globally;
* Each Epic D route declares a response schema reference under `schemas/…`;
* Middleware is positioned after handlers and before response write.
  AC-Ref: 6.1.27, 6.1.11

7.1.19 Deterministic transform engine exposed as a discrete service
Purpose: Ensure transform detection is implemented in a standalone service that can be unit-tested independently.
Test Data: Transform engine service module; suggestion/preview handlers.
Mocking: No mocking for structural presence; verify handlers depend on the service via import.
Assertions:

* A single transform engine service module exists and exports a pure `classify/canonicalise` API;
* Suggestion and preview handlers import and call this service;
* Service module has no imports from web transport layers.
  AC-Ref: 6.1.30, 6.1.5

7.1.20 Canonical value enforcement present in validation layer
Purpose: Ensure canonicalisation is enforced via schema or explicit validator hook before persistence/response.
Test Data: Option validation utility (or JSON schema with pattern as in 7.1.9); bind/suggest response builders.
Mocking: No mocking for static presence; if validator is a function, use spy to confirm it is called by builders.
Assertions:

* Either schema-level pattern exists on `OptionSpec.value` (see 7.1.9), or a validator function enforces uppercase snake-case;
* Builders invoke the validator prior to emitting responses.
  AC-Ref: 6.1.6

7.1.21 Nested placeholder linkage represented by FK
Purpose: Ensure parent option linkage to child placeholder uses a foreign key field.
Test Data: ORM models metadata for placeholder entities and option linkage.
Mocking: No mocking; inspect model metadata/reflection.
Assertions:

* Parent option structure includes a `placeholder_id` field;
* There is a foreign-key relation from `placeholder_id` to the placeholder primary key;
* Relation is nullable to allow deferred linking.
  AC-Ref: 6.1.15

7.1.22 Placeholder persistence has FKs and cascade semantics
Purpose: Ensure placeholder rows link to questions/documents with cascade delete behaviour.
Test Data: ORM model metadata or migration DDL for Placeholder table.
Mocking: No mocking.
Assertions:

* Placeholder table defines `question_id` and `document_id` foreign keys;
* `document_id` FK is configured with `ON DELETE CASCADE` (or equivalent ORM cascade setting).
  AC-Ref: 6.1.4, 6.1.12

7.1.23 Catalog response schemas present and deterministic
Purpose: Ensure catalog schemas exist and ordering is deterministic.
Test Data: schemas/TransformsCatalogResponse.json, schemas/TransformsCatalogItem.json; catalog handler.
Mocking: No mocking.
Assertions:

* Both schema files exist and are referenced by the catalog handler;
* Catalog handler applies explicit, deterministic ordering (e.g., by id or name) before emission.
  AC-Ref: 6.1.18, 6.1.7

7.1.24 Timestamp format enforcement in schemas
Purpose: Ensure all timestamped responses use RFC3339 UTC via schema constraints.
Test Data: schemas/Placeholder.json, schemas/ListPlaceholdersResponse.json (for any timestamp fields).
Mocking: No mocking.
Assertions:

* `created_at` in `schemas/Placeholder.json` has `format: date-time`;
* No alternative timestamp fields omit the `format: date-time`.
  AC-Ref: 6.1.25

7.1.25 Response projection for unbind is schema-validated
Purpose: Ensure unbind uses a defined projection or schema and includes required keys.
Test Data: schemas/UnbindResponse.json (or documented projection contract); unbind handler wiring.
Mocking: No mocking.
Assertions:

* If `schemas/UnbindResponse.json` exists, handler references it;
* Otherwise, handler projection includes keys `ok`, `question_id`, `etag` with expected types.
  AC-Ref: 6.1.11, 6.1.22

7.1.26 Probe immutability guard present on bind
Purpose: Ensure bind code treats `ProbeReceipt` as immutable and verifies it rather than mutating it.
Test Data: Bind handler module.
Mocking: No mocking; static inspection of code to confirm no writes to `probe` object occur and a verification call is made.
Assertions:

* No assignments modify `probe` fields;
* Bind handler calls a verification routine that checks `probe_hash` and span/keys.
  AC-Ref: 6.1.26, 6.1.8

7.1.27 Global schema validation enabled for all Epic D endpoints
Purpose: Ensure every Epic D route is wired to a response schema (not just some).
Test Data: Router definitions for Epic D endpoints; schema binding configuration.
Mocking: No mocking.
Assertions:

* `/api/v1/transforms/suggest` → `schemas/SuggestResponse.json`;
* `/api/v1/transforms/preview` → `schemas/TransformsPreviewResponse.json`;
* `/api/v1/transforms/catalog` → `schemas/TransformsCatalogResponse.json`;
* `/api/v1/placeholders/bind` → `schemas/BindResult.json`;
* `/api/v1/placeholders/unbind` → `schemas/UnbindResponse.json`;
* `/api/v1/questions/{id}/placeholders` → `schemas/ListPlaceholdersResponse.json`;
* `/api/v1/documents/{id}/bindings:purge` → `schemas/PurgeResponse.json`.
  AC-Ref: 6.1.27, 6.1.11

**7.2.1.1**
**Title:** Suggest returns single transform proposal
**Purpose:** Verify `/api/v1/transforms/suggest` returns exactly one proposal on valid probe.
**Test data:**

* Request JSON:

  ```json
  {
    "raw_text": "The HR Manager OR [POSITION]",
    "context": { "document_id": "11111111-1111-1111-1111-111111111111", "clause_path": "1.2.3" }
  }
  ```

**Mocking:** None (stateless endpoint; no external calls required for happy path).
**Assertions:**

* Response HTTP 200.
* Body contains object `suggestion` (or top-level fields per endpoint spec) with exactly one transform proposal (`answer_kind` present).
* No array of multiple proposals is present.
  **AC-Ref:** 6.2.1.1
  **EARS-Refs:** U3, E1

---

**7.2.1.2**
**Title:** Suggest returns probe receipt for bind continuity
**Purpose:** Verify suggestion response contains `probe` with `probe_hash` and span/keys for bind continuity.
**Test data:** Use request from 7.2.1.1.
**Mocking:** None.
**Assertions:**

* Response includes `probe` object with: `document_id`, `clause_path`, `resolved_span.start` (integer), `resolved_span.end` (integer), and `probe_hash` (non-empty hex/base64-like string).
* `probe.document_id` equals request `context.document_id`.
* `probe.clause_path` equals request `context.clause_path`.
  **AC-Ref:** 6.2.1.2
  **EARS-Refs:** U5, E1

---

**7.2.1.3**
**Title:** Suggest proposal exposes answer kind
**Purpose:** Verify `answer_kind` is present and one of the allowed values.
**Test data:** Use request from 7.2.1.1.
**Mocking:** None.
**Assertions:**

* `suggestion.answer_kind` ∈ { "short_string", "long_text", "boolean", "number", "enum_single" }.
  **AC-Ref:** 6.2.1.3
  **EARS-Refs:** U2, U3, E1

---

**7.2.1.4**
**Title:** Suggest canonicalises enum options
**Purpose:** Verify enum options have canonical values and preserved labels.
**Test data:**

```json
{ "raw_text": "The HR Manager OR The COO",
  "context": { "document_id": "11111111-1111-1111-1111-111111111111", "clause_path": "1.2.4" } }
```

**Mocking:** None.
**Assertions:**

* `suggestion.answer_kind` = "enum_single".
* `suggestion.options` is an array with items having `value` and `label`.
* Each `value` matches `^[A-Z0-9_]+$` and for inputs above includes `HR_MANAGER` and `THE_COO`.
* Each `label` equals original literal text: "The HR Manager", "The COO".
  **AC-Ref:** 6.2.1.4
  **EARS-Refs:** U3, U10, E1

---

**7.2.1.5**
**Title:** Suggest returns stable probe hash
**Purpose:** Verify `probe.probe_hash` present and stable across identical calls.
**Test data:** Same request executed twice.
**Mocking:** None.
**Assertions:**

* Both responses contain non-empty `probe.probe_hash`.
* Hash from call #1 equals hash from call #2.
  **AC-Ref:** 6.2.1.5
  **EARS-Refs:** U5, E1

---

**7.2.1.6**
**Title:** Bind returns success result
**Purpose:** Verify `/api/v1/placeholders/bind` indicates success on valid bind.
**Test data:**

* `question_id`: `22222222-2222-2222-2222-222222222222`
* `transform_id`: from 7.2.1.1 response
* `probe`: from 7.2.1.2 response
* Headers: `Idempotency-Key: test-bind-001`, `If-Match: "q-etag-1"`
  **Mocking:** Database repository mocked at boundary to accept writes and return IDs (assert called exactly once).
  **Assertions:**
* HTTP 200; `bind_result.bound` is `true`.
  **AC-Ref:** 6.2.1.6
  **EARS-Refs:** U6, E2

---

**7.2.1.7**
**Title:** Bind returns persisted placeholder_id
**Purpose:** Ensure bind response includes new placeholder identifier.
**Test data:** Use 7.2.1.6 request.
**Mocking:** DB mock returns `placeholder_id = "33333333-3333-3333-3333-333333333333"`.
**Assertions:**

* `bind_result.placeholder_id` equals the mocked ID.
  **AC-Ref:** 6.2.1.7
  **EARS-Refs:** U6, E2

---

**7.2.1.8**
**Title:** First bind sets answer_kind on question
**Purpose:** Verify first binding sets the question’s `answer_kind`.
**Test data:** Use a question with no prior bindings; enum suggestion.
**Mocking:** DB mock confirms question model updated with `answer_kind="enum_single"`.
**Assertions:**

* `bind_result.answer_kind` = "enum_single".
  **AC-Ref:** 6.2.1.8
  **EARS-Refs:** U7, E3

---

**7.2.1.9**
**Title:** First bind returns canonical option set for enum
**Purpose:** Verify options are returned for enum on first bind.
**Test data:** As 7.2.1.8 with options {"HR_MANAGER","THE_COO"}.
**Mocking:** DB mock persists the canonical option set.
**Assertions:**

* `bind_result.options[].value` contains `HR_MANAGER`, `THE_COO`; `label` preserves originals.
  **AC-Ref:** 6.2.1.9
  **EARS-Refs:** U7, E3

---

**7.2.1.10**
**Title:** Subsequent bind preserves existing answer model
**Purpose:** Verify second binding does not alter `answer_kind`.
**Test data:** Bind a second placeholder to same question (current model = "enum_single").
**Mocking:** DB mock asserts no update to question `answer_kind` or option set.
**Assertions:**

* `bind_result.answer_kind` remains "enum_single".
  **AC-Ref:** 6.2.1.10
  **EARS-Refs:** U7, E4, S1

---

**7.2.1.11**
**Title:** Nested linkage populates parent option on child bind
**Purpose:** Verify parent option’s `placeholder_id` is set when child later binds.
**Test data:**

* Parent enum option has `placeholder_key="POSITION"` and `placeholder_id=null`.
* Bind child `[POSITION]` now.
  **Mocking:** DB mock updates parent option to set `placeholder_id="44444444-4444-4444-4444-444444444444"`.
  **Assertions:**
* `bind_result.options[]` entry for `POSITION` has `placeholder_id` equal to mocked ID.
  **AC-Ref:** 6.2.1.11
  **EARS-Refs:** E5, S3

---

**7.2.1.12**
**Title:** Bind response includes new question ETag
**Purpose:** Ensure bind returns updated concurrency token.
**Test data:** As 7.2.1.6.
**Mocking:** ETag generator mocked to return `"q-etag-2"`.
**Assertions:**

* `bind_result.etag` = `"q-etag-2"`.
  **AC-Ref:** 6.2.1.12
  **EARS-Refs:** U8, E2

---

**7.2.1.13**
**Title:** Unbind returns success projection and ETag
**Purpose:** Verify `/api/v1/placeholders/unbind` returns `{ ok: true, etag }`.
**Test data:** `placeholder_id="33333333-3333-3333-3333-333333333333"`, header `If-Match: "q-etag-2"`.
**Mocking:** DB mock deletes record; ETag generator returns `"q-etag-3"`.
**Assertions:**

* HTTP 200; body `ok=true`; `etag="q-etag-3"`.
  **AC-Ref:** 6.2.1.13
  **EARS-Refs:** E9

---

**7.2.1.14**
**Title:** List returns placeholders for question
**Purpose:** Verify listing returns array of placeholders.
**Test data:** `GET /api/v1/questions/2222…/placeholders?document_id=1111…`
**Mocking:** DB mock returns two placeholder rows.
**Assertions:**

* HTTP 200; `items` is an array with length 2; each item has `id`, `document_id`, `clause_path`, `text_span.start/end`.
  **AC-Ref:** 6.2.1.14
  **EARS-Refs:** U9, S3

---

**7.2.1.15**
**Title:** List includes stable question ETag
**Purpose:** Ensure list response returns current ETag.
**Test data:** As 7.2.1.14.
**Mocking:** ETag generator returns `"q-etag-3"`.
**Assertions:**

* Response `etag="q-etag-3"`.
  **AC-Ref:** 6.2.1.15
  **EARS-Refs:** U9

---

**7.2.1.16**
**Title:** Purge returns deletion summary counts
**Purpose:** Verify purge response includes `deleted_placeholders` and `updated_questions`.
**Test data:** `POST /api/v1/documents/1111…/bindings:purge` body `{ "reason": "deleted" }`.
**Mocking:** DB mock deletes 2 placeholders; updates 1 question model.
**Assertions:**

* `deleted_placeholders=2`; `updated_questions=1`.
  **AC-Ref:** 6.2.1.16
  **EARS-Refs:** U9, E6

---

**7.2.1.17**
**Title:** Catalog returns supported transforms
**Purpose:** Verify catalog returns list of transforms.
**Test data:** `GET /api/v1/transforms/catalog`.
**Mocking:** Transform registry mocked to expose `{ id:"enum_single", name:"Enum Single", answer_kind:"enum_single" }`.
**Assertions:**

* HTTP 200; `items` array contains an object with `transform_id`, `name`, `answer_kind`.
  **AC-Ref:** 6.2.1.17
  **EARS-Refs:** U9, E10

---

**7.2.1.18**
**Title:** Preview returns answer kind
**Purpose:** Verify `/api/v1/transforms/preview` infers `answer_kind`.
**Test data:** Body `{ "raw_text":"The HR Manager OR The COO" }`.
**Mocking:** None.
**Assertions:**

* HTTP 200; `answer_kind="enum_single"`.
  **AC-Ref:** 6.2.1.18
  **EARS-Refs:** U3, E11

---

**7.2.1.19**
**Title:** Preview returns canonical options for enum
**Purpose:** Verify preview options canonicalisation.
**Test data:** As 7.2.1.18.
**Mocking:** None.
**Assertions:**

* `options[].value` contains `HR_MANAGER`, `THE_COO`; labels preserve originals.
  **AC-Ref:** 6.2.1.19
  **EARS-Refs:** U3, E11

---

**7.2.1.20**
**Title:** Listing preserves document and clause references
**Purpose:** Ensure listed placeholders keep `document_id` and `clause_path`.
**Test data:** As 7.2.1.14.
**Mocking:** DB rows include these fields.
**Assertions:**

* For each item, `document_id="1111…"`, `clause_path` equals expected (e.g., "1.2.3").
  **AC-Ref:** 6.2.1.20
  **EARS-Refs:** S3

---

**7.2.1.21**
**Title:** Listing includes span coordinates
**Purpose:** Ensure start/end character indices returned.
**Test data:** As 7.2.1.14.
**Mocking:** DB rows include `text_span.start=15`, `end=42`.
**Assertions:**

* Each item has integer `text_span.start>=0`, `end>start`.
  **AC-Ref:** 6.2.1.21
  **EARS-Refs:** S3

---

**7.2.1.22**
**Title:** Idempotent bind returns same placeholder_id
**Purpose:** Ensure same `Idempotency-Key` yields same result.
**Test data:** Repeat 7.2.1.6 request with identical payload and `Idempotency-Key: test-bind-001`.
**Mocking:** Idempotency store mock returns original result.
**Assertions:**

* Both responses have identical `placeholder_id`.
  **AC-Ref:** 6.2.1.22
  **EARS-Refs:** U8, E2

---

**7.2.1.23**
**Title:** Suggest is stateless (no persistence)
**Purpose:** Ensure suggestion does not create placeholder records.
**Test data:** As 7.2.1.1.
**Mocking:** DB mock asserts zero writes during suggest.
**Assertions:**

* No DB write operations observed; only response contents present.
  **AC-Ref:** 6.2.1.23
  **EARS-Refs:** U6, E1

---

**7.2.1.24**
**Title:** Purge idempotence yields zero additional deletions
**Purpose:** Verify second purge shows no extra work.
**Test data:** Call purge twice for same document.
**Mocking:** First call deletes 2; second call finds none.
**Assertions:**

* First response: `deleted_placeholders=2`.
* Second response: `deleted_placeholders=0`.
  **AC-Ref:** 6.2.1.24
  **EARS-Refs:** E7

---

**7.2.1.25**
**Title:** Listing empty after last placeholder unbound
**Purpose:** Ensure list shows empty array once last binding removed.
**Test data:** Unbind last placeholder (7.2.1.13), then list.
**Mocking:** DB mock returns zero rows post-unbind.
**Assertions:**

* `items` is `[]`.
  **AC-Ref:** 6.2.1.25
  **EARS-Refs:** E8

---

**7.2.1.26**
**Title:** Suggest resolves short_string placeholders
**Purpose:** Ensure short text yields `short_string` with no options.
**Test data:**

```json
{ "raw_text": "[POSITION]", "context": { "document_id": "1111…", "clause_path": "2.1" } }
```

**Mocking:** None.
**Assertions:**

* `answer_kind="short_string"`; `options` is absent or empty.
  **AC-Ref:** 6.2.1.26
  **EARS-Refs:** U3, E1

---

**7.2.1.27**
**Title:** Suggest resolves long_text placeholders
**Purpose:** Ensure long text (exceeds short threshold / multi-line) yields `long_text`.
**Test data:**

```json
{ "raw_text": "[GENERAL DETAILS ABOUT THE EMPLOYER AND ITS BUSINESS.]", "context": { "document_id": "1111…", "clause_path": "2.2" } }
```

**Mocking:** None.
**Assertions:**

* `answer_kind="long_text"`; no `options`.
  **AC-Ref:** 6.2.1.27
  **EARS-Refs:** U3, E1

---

**7.2.1.28**
**Title:** Suggest resolves number placeholders
**Purpose:** Ensure numeric patterns yield `number`.
**Test data:**

```json
{ "raw_text": "[30 DAYS]", "context": { "document_id": "1111…", "clause_path": "2.3" } }
```

**Mocking:** None.
**Assertions:**

* `answer_kind="number"`; no `options`.
  **AC-Ref:** 6.2.1.28
  **EARS-Refs:** U3, E1

---

**7.2.1.29**
**Title:** Suggest resolves boolean inclusion placeholders
**Purpose:** Ensure binary inclusion toggles yield `boolean`.
**Test data:**

```json
{ "raw_text": "[INCLUDE PROBATION CLAUSE]", "context": { "document_id": "1111…", "clause_path": "2.4" } }
```

**Mocking:** None.
**Assertions:**

* `answer_kind="boolean"`; no `options`.
  **AC-Ref:** 6.2.1.29
  **EARS-Refs:** U3, E1

---

**7.2.1.30**
**Title:** Suggest resolves enum (literal-only)
**Purpose:** Ensure literal OR list yields enum with canonical values and preserved labels.
**Test data:**

```json
{ "raw_text": "Intranet OR Handbook Portal", "context": { "document_id": "1111…", "clause_path": "2.5" } }
```

**Mocking:** None.
**Assertions:**

* `answer_kind="enum_single"`; `options[].value` = `INTRANET`, `HANDBOOK_PORTAL`; `label` = original literals.
  **AC-Ref:** 6.2.1.30
  **EARS-Refs:** U3, U10, E1

---

**7.2.1.31**
**Title:** Suggest resolves enum (literal + nested placeholder)
**Purpose:** Ensure mixed list returns literal options plus nested placeholder key option.
**Test data:**

```json
{ "raw_text": "The HR Manager OR [POSITION]", "context": { "document_id": "1111…", "clause_path": "2.6" } }
```

**Mocking:** None.
**Assertions:**

* Options include `HR_MANAGER` and an option with `value="POSITION"`, `placeholder_key="POSITION"`, `placeholder_id=null`.
  **AC-Ref:** 6.2.1.31
  **EARS-Refs:** O1, E1

---

**7.2.1.32**
**Title:** Suggest labels nested placeholder option with canonical token
**Purpose:** Ensure label for nested option uses canonical token when `placeholder_id=null`.
**Test data:** As 7.2.1.31.
**Mocking:** None.
**Assertions:**

* For the nested option, `label="POSITION"`, `placeholder_id=null`.
  **AC-Ref:** 6.2.1.32
  **EARS-Refs:** O1, E1

---

**7.2.1.33**
**Title:** Suggest determinism for kind and option order
**Purpose:** Same probe twice yields identical `answer_kind` and option ordering.
**Test data:** Repeat 7.2.1.30 request twice.
**Mocking:** None.
**Assertions:**

* `answer_kind` identical across calls.
* `options[]` arrays are byte-for-byte equal including order.
  **AC-Ref:** 6.2.1.33
  **EARS-Refs:** U3, E1

---

**7.2.1.34**
**Title:** Bind (first) with non-enum omits options
**Purpose:** Ensure non-enum first bind does not return options.
**Test data:** Suggest `short_string`, then bind.
**Mocking:** DB mock persists placeholder only.
**Assertions:**

* `bind_result.answer_kind="short_string"`; `bind_result.options` absent.
  **AC-Ref:** 6.2.1.34
  **EARS-Refs:** E3

---

**7.2.1.35**
**Title:** Bind (first) enum literal-only mirrors suggestion options
**Purpose:** Ensure bound options equal suggested options.
**Test data:** Use suggestion from 7.2.1.30; then bind.
**Mocking:** DB mock persists identical option set.
**Assertions:**

* `bind_result.options[]` equals suggestion options (values and labels).
  **AC-Ref:** 6.2.1.35
  **EARS-Refs:** E3, S1

---

**7.2.1.36**
**Title:** Bind (first) enum with nested child not yet bound
**Purpose:** Parent’s nested option carries key with null id.
**Test data:** Use suggestion from 7.2.1.31; then bind parent.
**Mocking:** DB mock stores option with `placeholder_key="POSITION"`, `placeholder_id=null`.
**Assertions:**

* `bind_result.options[]` contains that nested option with `placeholder_id=null`.
  **AC-Ref:** 6.2.1.36
  **EARS-Refs:** E3, E5, S3

---

**7.2.1.37**
**Title:** Bind child updates parent nested linkage
**Purpose:** After binding child, parent option’s `placeholder_id` is set.
**Test data:** After 7.2.1.36, bind child `[POSITION]`.
**Mocking:** DB mock updates parent option’s `placeholder_id="55555555-5555-5555-5555-555555555555"`.
**Assertions:**

* `bind_result.options[]` now shows `placeholder_id` populated for `POSITION`.
  **AC-Ref:** 6.2.1.37
  **EARS-Refs:** E5, S3

---

**7.2.1.38**
**Title:** Preview mirrors suggestion for kind and options
**Purpose:** Ensure preview returns same canonicalisation as suggest.
**Test data:** Use same `raw_text` as 7.2.1.30.
**Mocking:** None.
**Assertions:**

* `preview.answer_kind="enum_single"` and `preview.options[]` equals suggestion’s canonical list.
  **AC-Ref:** 6.2.1.38
  **EARS-Refs:** E11, U3

---

**7.2.1.39**
**Title:** List reflects latest nested linkage state
**Purpose:** Verify listing shows parent/child linkage after both binds.
**Test data:** After tests 7.2.1.36–37, list placeholders for the question.
**Mocking:** DB returns parent with nested option linked to child placeholder ID.
**Assertions:**

* Listing (or immediate `bind_result`) reflects `placeholder_id` populated for the nested option corresponding to the bound child.
  **AC-Ref:** 6.2.1.39
  **EARS-Refs:** E5, S3

**7.2.2.1**
**Title:** `/transforms/suggest` rejects missing `raw_text`
**Purpose:** Verify the API returns the defined precondition error when `raw_text` is absent.
**Test Data:**
Request JSON:

```json
{
  "raw_text": "",
  "context": { "document_id": "3f1c2f3a-54d0-447f-9a2c-6a9e0f7a2f11", "clause_path": "1.2.3" }
}
```

**Mocking:**

* Mock HTTP layer only (no internal logic). No downstream mocks required. Assert handler receives body with empty `raw_text`.
  **Assertions:**
* HTTP 400 with `error.code == "PRE_PLACEHOLDER_PROBE_RAW_TEXT_MISSING"`.
* Error message explicitly states “raw_text is required”.
  **AC-Ref:** 6.2.2.1
  **Error Mode:** PRE_PLACEHOLDER_PROBE_RAW_TEXT_MISSING

---

**7.2.2.2**
**Title:** `/transforms/suggest` rejects non-UUID `document_id`
**Purpose:** Ensure invalid UUID in context is handled by contract error.
**Test Data:**
Request JSON:

```json
{
  "raw_text": "[YES]",
  "context": { "document_id": "not-a-uuid", "clause_path": "1.2.3" }
}
```

**Mocking:**

* Mock HTTP layer only. No model invoked.
  **Assertions:**
* HTTP 400 with `error.code == "PRE_PLACEHOLDER_PROBE_CONTEXT_DOCUMENT_ID_INVALID"`.
* Error includes pointer to `context.document_id`.
  **AC-Ref:** 6.2.2.2
  **Error Mode:** PRE_PLACEHOLDER_PROBE_CONTEXT_DOCUMENT_ID_INVALID

---

**7.2.2.3**
**Title:** `/transforms/suggest` rejects empty `clause_path`
**Purpose:** Contract error when `clause_path` is empty.
**Test Data:**
Request JSON:

```json
{
  "raw_text": "[YES]",
  "context": { "document_id": "3f1c2f3a-54d0-447f-9a2c-6a9e0f7a2f11", "clause_path": "" }
}
```

**Mocking:** None beyond HTTP boundary.
**Assertions:**

* HTTP 400 with `error.code == "PRE_PLACEHOLDER_PROBE_CONTEXT_CLAUSE_PATH_EMPTY"`.
  **AC-Ref:** 6.2.2.3
  **Error Mode:** PRE_PLACEHOLDER_PROBE_CONTEXT_CLAUSE_PATH_EMPTY

---

**7.2.2.4**
**Title:** `/transforms/suggest` rejects negative span start
**Purpose:** Validate span semantics.
**Test Data:**
Request JSON:

```json
{
  "raw_text": "[YES]",
  "context": {
    "document_id": "3f1c2f3a-54d0-447f-9a2c-6a9e0f7a2f11",
    "clause_path": "1.2.3",
    "span": { "start": -1, "end": 10 }
  }
}
```

**Mocking:** None beyond HTTP boundary.
**Assertions:**

* HTTP 400 with `error.code == "PRE_PLACEHOLDER_PROBE_CONTEXT_SPAN_INVALID_RANGE"`.
  **AC-Ref:** 6.2.2.4
  **Error Mode:** PRE_PLACEHOLDER_PROBE_CONTEXT_SPAN_INVALID_RANGE

---

**7.2.2.5**
**Title:** `/transforms/suggest` rejects `span.end <= start`
**Purpose:** Catch zero/negative width spans.
**Test Data:**
`span: { "start": 12, "end": 12 }`
**Mocking:** None beyond HTTP boundary.
**Assertions:**

* HTTP 400 with `error.code == "PRE_PLACEHOLDER_PROBE_CONTEXT_SPAN_INVALID_RANGE"`.
  **AC-Ref:** 6.2.2.5
  **Error Mode:** PRE_PLACEHOLDER_PROBE_CONTEXT_SPAN_INVALID_RANGE

---

**7.2.2.6**
**Title:** `/transforms/suggest` rejects `doc_etag` with invalid format
**Purpose:** ETag format enforcement.
**Test Data:**
`doc_etag: "bad/etag"`
**Mocking:** None beyond HTTP boundary.
**Assertions:**

* HTTP 400 with `error.code == "PRE_PLACEHOLDER_PROBE_CONTEXT_DOC_ETAG_INVALID"`.
  **AC-Ref:** 6.2.2.6
  **Error Mode:** PRE_PLACEHOLDER_PROBE_CONTEXT_DOC_ETAG_INVALID

---

**7.2.2.7**
**Title:** Suggestion returns 422 for unrecognised placeholder pattern
**Purpose:** Contract for “no viable transform”.
**Test Data:**
`raw_text: "[This $%^&* is not a valid placeholder]"`
**Mocking:**

* Mock classifier to return “unrecognised” signal to surface contract error.
  **Assertions:**
* HTTP 422 with `error.code == "PRE_TRANSFORM_SUGGEST_UNRECOGNISED_PATTERN"`; message references `raw_text`.
  **AC-Ref:** 6.2.2.7
  **Error Mode:** PRE_TRANSFORM_SUGGEST_UNRECOGNISED_PATTERN

---

**7.2.2.8**
**Title:** Suggestion rejects long_text with line breaks when short_text required
**Purpose:** Enforce short text rule (no line breaks).
**Test Data:**
`raw_text` contains embedded `\n` within brackets, length 80 chars.
**Mocking:** Classifier returns violation.
**Assertions:**

* HTTP 422 with `error.code == "PRE_SHORT_STRING_LINE_BREAKS_NOT_ALLOWED"`.
  **AC-Ref:** 6.2.2.8
  **Error Mode:** PRE_SHORT_STRING_LINE_BREAKS_NOT_ALLOWED

---

**7.2.2.9**
**Title:** `/placeholders/bind` rejects missing `Idempotency-Key`
**Purpose:** Idempotency contract must be enforced.
**Test Data:**
POST body: valid; headers omit `Idempotency-Key`.
**Mocking:** None beyond HTTP boundary.
**Assertions:**

* HTTP 400 with `error.code == "PRE_BIND_IDEMPOTENCY_KEY_MISSING"`.
  **AC-Ref:** 6.2.2.9
  **Error Mode:** PRE_BIND_IDEMPOTENCY_KEY_MISSING

---

**7.2.2.10**
**Title:** `/placeholders/bind` rejects missing `If-Match` ETag
**Purpose:** Concurrency control precondition.
**Test Data:**
Omit `If-Match`.
**Mocking:** None beyond HTTP boundary.
**Assertions:**

* HTTP 400 with `error.code == "PRE_BIND_IF_MATCH_HEADER_MISSING"`.
  **AC-Ref:** 6.2.2.10
  **Error Mode:** PRE_BIND_IF_MATCH_HEADER_MISSING

---

**7.2.2.11**
**Title:** `/placeholders/bind` rejects invalid `question_id` format
**Purpose:** Validate UUID formatting.
**Test Data:**
`question_id: "123"`
**Mocking:** None beyond HTTP boundary.
**Assertions:**

* HTTP 400 with `error.code == "PRE_BIND_QUESTION_ID_INVALID"`.
  **AC-Ref:** 6.2.2.11
  **Error Mode:** PRE_BIND_QUESTION_ID_INVALID

---

**7.2.2.12**
**Title:** `/placeholders/bind` rejects unknown `transform_id`
**Purpose:** Only known transforms may be bound.
**Test Data:**
`transform_id: "does-not-exist"`
**Mocking:** Mock transform registry lookup to return not found.
**Assertions:**

* HTTP 422 with `error.code == "PRE_BIND_TRANSFORM_ID_UNKNOWN"`.
  **AC-Ref:** 6.2.2.12
  **Error Mode:** PRE_BIND_TRANSFORM_ID_UNKNOWN

---

**7.2.2.13**
**Title:** `/placeholders/bind` rejects missing `placeholder.raw_text`
**Purpose:** PlaceholderProbe completeness.
**Test Data:**
`placeholder: { raw_text: "" }`
**Mocking:** None beyond HTTP boundary.
**Assertions:**

* HTTP 400 with `error.code == "PRE_BIND_PLACEHOLDER_RAW_TEXT_MISSING"`.
  **AC-Ref:** 6.2.2.13
  **Error Mode:** PRE_BIND_PLACEHOLDER_RAW_TEXT_MISSING

---

**7.2.2.14**
**Title:** `/placeholders/bind` rejects missing `context.document_id`
**Purpose:** Context completeness.
**Test Data:**
`placeholder.context` lacks `document_id`.
**Mocking:** None beyond HTTP boundary.
**Assertions:**

* HTTP 400 with `error.code == "PRE_BIND_CONTEXT_DOCUMENT_ID_MISSING"`.
  **AC-Ref:** 6.2.2.14
  **Error Mode:** PRE_BIND_CONTEXT_DOCUMENT_ID_MISSING

---

**7.2.2.15**
**Title:** `/placeholders/bind` rejects missing `context.clause_path`
**Purpose:** Context completeness.
**Test Data:**
`clause_path` omitted.
**Mocking:** None.
**Assertions:**

* HTTP 400 with `error.code == "PRE_BIND_CONTEXT_CLAUSE_PATH_MISSING"`.
  **AC-Ref:** 6.2.2.15
  **Error Mode:** PRE_BIND_CONTEXT_CLAUSE_PATH_MISSING

---

**7.2.2.16**
**Title:** `/placeholders/bind` rejects `apply_mode` not in {verify, apply}
**Purpose:** Enforce enum.
**Test Data:**
`apply_mode: "commit"`
**Mocking:** None.
**Assertions:**

* HTTP 400 with `error.code == "PRE_BIND_APPLY_MODE_INVALID"`.
  **AC-Ref:** 6.2.2.16
  **Error Mode:** PRE_BIND_APPLY_MODE_INVALID

---

**7.2.2.17**
**Title:** `/placeholders/bind` rejects stale question ETag
**Purpose:** Concurrency conflict surfaced at contract.
**Test Data:**
Header `If-Match: "abc123"`; server current ETag differs.
**Mocking:** Mock question store to return current ETag “xyz999”.
**Assertions:**

* HTTP 412 with `error.code == "PRE_BIND_IF_MATCH_PRECONDITION_FAILED"`.
  **AC-Ref:** 6.2.2.17
  **Error Mode:** PRE_BIND_IF_MATCH_PRECONDITION_FAILED

---

**7.2.2.18**
**Title:** `/placeholders/bind` rejects transform that changes established `answer_kind`
**Purpose:** Model consistency contract.
**Test Data:**
Existing question has `answer_kind=enum_single`; request proposes `answer_kind=boolean`.
**Mocking:** Mock model comparer to detect mismatch.
**Assertions:**

* HTTP 409 with `error.code == "POST_BIND_MODEL_CONFLICT_ANSWER_KIND_CHANGED"`.
  **AC-Ref:** 6.2.2.18
  **Error Mode:** POST_BIND_MODEL_CONFLICT_ANSWER_KIND_CHANGED

---

**7.2.2.19**
**Title:** `/placeholders/bind` rejects transform that alters canonical option set
**Purpose:** Option set immutability.
**Test Data:**
Existing options: `["HR_MANAGER"]`; proposed options: `["INTRANET"]`.
**Mocking:** Mock comparison to yield difference.
**Assertions:**

* HTTP 409 with `error.code == "POST_BIND_MODEL_CONFLICT_OPTIONS_CHANGED"`.
  **AC-Ref:** 6.2.2.19
  **Error Mode:** POST_BIND_MODEL_CONFLICT_OPTIONS_CHANGED

---

**7.2.2.20**
**Title:** `/placeholders/bind` rejects suggestion with mismatched `probe_hash`
**Purpose:** Prevent binding with stale probe context.
**Test Data:**
`probe.probe_hash: "oldhash"`; server recompute yields “newhash”.
**Mocking:** Mock probe-hash service to return “newhash”.
**Assertions:**

* HTTP 409 with `error.code == "PRE_BIND_PROBE_HASH_MISMATCH"`.
  **AC-Ref:** 6.2.2.20
  **Error Mode:** PRE_BIND_PROBE_HASH_MISMATCH

---

**7.2.2.21**
**Title:** `/placeholders/bind` rejects span outside document clause bounds
**Purpose:** Span must be within clause text.
**Test Data:**
`span: { start: 100000, end: 100100 }` in a short clause.
**Mocking:** Mock document service to return clause length 300.
**Assertions:**

* HTTP 422 with `error.code == "PRE_BIND_SPAN_OUT_OF_CLAUSE_BOUNDS"`.
  **AC-Ref:** 6.2.2.21
  **Error Mode:** PRE_BIND_SPAN_OUT_OF_CLAUSE_BOUNDS

---

**7.2.2.22**
**Title:** `/placeholders/bind` rejects unknown `question_id`
**Purpose:** Target question must exist.
**Test Data:**
`question_id: "3f1c2f3a-54d0-447f-9a2c-6a9e0f7a2f99"` (nonexistent)
**Mocking:** Mock question repository `get` → None.
**Assertions:**

* HTTP 404 with `error.code == "PRE_BIND_QUESTION_NOT_FOUND"`.
  **AC-Ref:** 6.2.2.22
  **Error Mode:** PRE_BIND_QUESTION_NOT_FOUND

---

**7.2.2.23**
**Title:** `/placeholders/unbind` rejects missing `If-Match`
**Purpose:** Concurrency precondition on unbind.
**Test Data:**
Header omitted.
**Mocking:** None.
**Assertions:**

* HTTP 400 with `error.code == "PRE_UNBIND_IF_MATCH_HEADER_MISSING"`.
  **AC-Ref:** 6.2.2.23
  **Error Mode:** PRE_UNBIND_IF_MATCH_HEADER_MISSING

---

**7.2.2.24**
**Title:** `/placeholders/unbind` rejects invalid `placeholder_id` format
**Purpose:** Validate UUID.
**Test Data:**
`placeholder_id: "abc"`
**Mocking:** None.
**Assertions:**

* HTTP 400 with `error.code == "PRE_UNBIND_PLACEHOLDER_ID_INVALID"`.
  **AC-Ref:** 6.2.2.24
  **Error Mode:** PRE_UNBIND_PLACEHOLDER_ID_INVALID

---

**7.2.2.25**
**Title:** `/placeholders/unbind` rejects unknown `placeholder_id`
**Purpose:** Target must exist.
**Test Data:**
Valid UUID not in DB.
**Mocking:** Repo returns None.
**Assertions:**

* HTTP 404 with `error.code == "PRE_UNBIND_PLACEHOLDER_NOT_FOUND"`.
  **AC-Ref:** 6.2.2.25
  **Error Mode:** PRE_UNBIND_PLACEHOLDER_NOT_FOUND

---

**7.2.2.26**
**Title:** `/questions/{id}/placeholders` rejects unknown question
**Purpose:** Listing requires existing question.
**Test Data:**
`question_id` unknown.
**Mocking:** Repo returns None.
**Assertions:**

* HTTP 404 with `error.code == "PRE_LIST_QUESTION_NOT_FOUND"`.
  **AC-Ref:** 6.2.2.26
  **Error Mode:** PRE_LIST_QUESTION_NOT_FOUND

---

**7.2.2.27**
**Title:** `/questions/{id}/placeholders` rejects invalid `document_id` filter
**Purpose:** Filter must be UUID if present.
**Test Data:**
`document_id="?bad"`
**Mocking:** None beyond HTTP.
**Assertions:**

* HTTP 400 with `error.code == "PRE_LIST_DOCUMENT_ID_INVALID"`.
  **AC-Ref:** 6.2.2.27
  **Error Mode:** PRE_LIST_DOCUMENT_ID_INVALID

---

**7.2.2.28**
**Title:** `/documents/{id}/bindings:purge` rejects non-UUID document ID
**Purpose:** Enforce path param format.
**Test Data:**
`/documents/not-a-uuid/bindings:purge`
**Mocking:** None.
**Assertions:**

* HTTP 400 with `error.code == "PRE_PURGE_DOCUMENT_ID_INVALID"`.
  **AC-Ref:** 6.2.2.28
  **Error Mode:** PRE_PURGE_DOCUMENT_ID_INVALID

---

**7.2.2.29**
**Title:** `/documents/{id}/bindings:purge` rejects unknown document
**Purpose:** Document must exist (or defined as no-op only if spec demands; here we surface 404 per errors list).
**Test Data:**
Valid UUID not present.
**Mocking:** Document repo returns None.
**Assertions:**

* HTTP 404 with `error.code == "PRE_PURGE_DOCUMENT_NOT_FOUND"`.
  **AC-Ref:** 6.2.2.29
  **Error Mode:** PRE_PURGE_DOCUMENT_NOT_FOUND

---

**7.2.2.30**
**Title:** Suggestion runtime failure bubbles as contract error
**Purpose:** Surface classifier crash as runtime contract error.
**Test Data:**
Valid request; classifier raises exception.
**Mocking:** Mock transform classifier to throw `ValueError("tokenise failed")`.
**Assertions:**

* HTTP 500 with `error.code == "RUN_SUGGEST_DETOKENISE_FAILURE"`; `error.details.reason` contains “tokenise failed”.
  **AC-Ref:** 6.2.2.30
  **Error Mode:** RUN_SUGGEST_DETOKENISE_FAILURE

---

**7.2.2.31**
**Title:** Bind persistence failure surfaces runtime error
**Purpose:** Contract on DB write failure.
**Test Data:**
Valid bind apply; DB insert fails.
**Mocking:** Mock placeholder repo `.insert` → raises `DBWriteError("unique_violation")`.
**Assertions:**

* HTTP 500 with `error.code == "RUN_BIND_PERSIST_FAILURE"`; `error.details.cause == "unique_violation"`.
  **AC-Ref:** 6.2.2.31
  **Error Mode:** RUN_BIND_PERSIST_FAILURE

---

**7.2.2.32**
**Title:** Bind “verify” mode stops on comparator crash
**Purpose:** Surface runtime comparison error.
**Test Data:**
`apply_mode: "verify"`; comparator throws.
**Mocking:** Mock model comparator `.compare` → raises `TypeError`.
**Assertions:**

* HTTP 500 with `error.code == "RUN_BIND_MODEL_COMPARE_FAILURE"`.
  **AC-Ref:** 6.2.2.32
  **Error Mode:** RUN_BIND_MODEL_COMPARE_FAILURE

---

**7.2.2.33**
**Title:** Nested linkage update failure surfaces runtime error
**Purpose:** Parent option linkage update error must surface.
**Test Data:**
Child within parent; updating parent option fails.
**Mocking:** Mock options repo `.update` → raises `DBWriteError("fk_missing")`.
**Assertions:**

* HTTP 500 with `error.code == "RUN_BIND_NESTED_LINKAGE_UPDATE_FAILURE"`.
  **AC-Ref:** 6.2.2.33
  **Error Mode:** RUN_BIND_NESTED_LINKAGE_UPDATE_FAILURE

---

**7.2.2.34**
**Title:** Unbind fails on stale ETag
**Purpose:** Concurrency error surfaced.
**Test Data:**
Header `If-Match: "old"`; current differs.
**Mocking:** Mock question repo to return ETag “new”.
**Assertions:**

* HTTP 412 with `error.code == "PRE_UNBIND_IF_MATCH_PRECONDITION_FAILED"`.
  **AC-Ref:** 6.2.2.34
  **Error Mode:** PRE_UNBIND_IF_MATCH_PRECONDITION_FAILED

---

**7.2.2.35**
**Title:** Unbind runtime delete failure returns error
**Purpose:** DB failure on delete must surface.
**Test Data:**
Valid unbind.
**Mocking:** placeholder repo `.delete` → raises `DBWriteError("constraint_violation")`.
**Assertions:**

* HTTP 500 with `error.code == "RUN_UNBIND_DELETE_FAILURE"`.
  **AC-Ref:** 6.2.2.35
  **Error Mode:** RUN_UNBIND_DELETE_FAILURE

---

**7.2.2.36**
**Title:** List runtime query failure returns error
**Purpose:** Query error is surfaced.
**Test Data:**
`GET /questions/{id}/placeholders`
**Mocking:** repo `.listByQuestion` → raises `DBReadError("timeout")`.
**Assertions:**

* HTTP 500 with `error.code == "RUN_LIST_QUERY_FAILURE"`.
  **AC-Ref:** 6.2.2.36
  **Error Mode:** RUN_LIST_QUERY_FAILURE

---

**7.2.2.37**
**Title:** Purge transaction rollback returns error
**Purpose:** Transactional cleanup failure must surface.
**Test Data:**
`POST /documents/{id}/bindings:purge`
**Mocking:** transaction manager `.commit` → raises `TxRollback("deadlock")`.
**Assertions:**

* HTTP 500 with `error.code == "RUN_PURGE_TRANSACTION_ROLLBACK"`.
  **AC-Ref:** 6.2.2.37
  **Error Mode:** RUN_PURGE_TRANSACTION_ROLLBACK

---

**7.2.2.38**
**Title:** Transforms catalog runtime failure surfaces error
**Purpose:** Catalog read must surface errors.
**Test Data:**
`GET /transforms/catalog`
**Mocking:** registry `.list` → raises `IOError("registry missing")`.
**Assertions:**

* HTTP 500 with `error.code == "RUN_CATALOG_READ_FAILURE"`.
  **AC-Ref:** 6.2.2.38
  **Error Mode:** RUN_CATALOG_READ_FAILURE

---

**7.2.2.39**
**Title:** Transforms preview rejects invalid payload
**Purpose:** Payload validation contract for preview.
**Test Data:**
`{ "literals": "not-an-array" }`
**Mocking:** None beyond HTTP.
**Assertions:**

* HTTP 400 with `error.code == "PRE_PREVIEW_PAYLOAD_INVALID"`.
  **AC-Ref:** 6.2.2.39
  **Error Mode:** PRE_PREVIEW_PAYLOAD_INVALID

---

**7.2.2.40**
**Title:** Transforms preview runtime failure surfaces error
**Purpose:** Canonicalisation crash must surface.
**Test Data:**
`{ "literals": ["Manager", "Intranet"] }`
**Mocking:** canonicaliser throws `KeyError("value")`.
**Assertions:**

* HTTP 500 with `error.code == "RUN_PREVIEW_CANONICALISE_FAILURE"`.
  **AC-Ref:** 6.2.2.40
  **Error Mode:** RUN_PREVIEW_CANONICALISE_FAILURE

---

**7.2.2.41**
**Title:** Suggestion rejects boolean inclusion without bracketed body
**Purpose:** Enforce deterministic boolean inclusion pattern.
**Test Data:**
`raw_text: "YES"` (no brackets)
**Mocking:** None beyond HTTP.
**Assertions:**

* HTTP 422 with `error.code == "PRE_BOOLEAN_INCLUSION_PATTERN_INVALID"`.
  **AC-Ref:** 6.2.2.41
  **Error Mode:** PRE_BOOLEAN_INCLUSION_PATTERN_INVALID

---

**7.2.2.42**
**Title:** Suggestion rejects enum with empty literal list
**Purpose:** Enum must not be empty.
**Test Data:**
`raw_text: "[]”` or `"[ OR ]"`
**Mocking:** Parser returns empty options.
**Assertions:**

* HTTP 422 with `error.code == "PRE_ENUM_OPTIONS_EMPTY"`.
  **AC-Ref:** 6.2.2.42
  **Error Mode:** PRE_ENUM_OPTIONS_EMPTY

---

**7.2.2.43**
**Title:** Bind rejects duplicate enum option values at insert
**Purpose:** Prevent duplicate canonical values.
**Test Data:**
Existing option: `HR_MANAGER`; proposed also `HR_MANAGER`.
**Mocking:** Options repo `.insert` → raises unique violation.
**Assertions:**

* HTTP 409 with `error.code == "POST_BIND_OPTION_VALUE_COLLISION"`.
  **AC-Ref:** 6.2.2.43
  **Error Mode:** POST_BIND_OPTION_VALUE_COLLISION

---

**7.2.2.44**
**Title:** Bind rejects mixed enum with invalid placeholder key token
**Purpose:** Placeholder key must be canonical token.
**Test Data:**
Option value uses “Position (Mgr)” as placeholder key.
**Mocking:** Tokeniser flags invalid token.
**Assertions:**

* HTTP 422 with `error.code == "PRE_ENUM_PLACEHOLDER_KEY_INVALID"`.
  **AC-Ref:** 6.2.2.44
  **Error Mode:** PRE_ENUM_PLACEHOLDER_KEY_INVALID

---

**7.2.2.45**
**Title:** Suggestion rejects number with non-numeric token
**Purpose:** Numeric transform requires numeric token(s).
**Test Data:**
`raw_text: "[TWELVE]"`
**Mocking:** Number detector returns non-numeric.
**Assertions:**

* HTTP 422 with `error.code == "PRE_NUMBER_NOT_NUMERIC"`.
  **AC-Ref:** 6.2.2.45
  **Error Mode:** PRE_NUMBER_NOT_NUMERIC

---

**7.2.2.46**
**Title:** Bind rejects number outside inferred bounds
**Purpose:** Enforce inferred validation metadata.
**Test Data:**
Transform preview inferred min=1, max=10; binding value implies 11.
**Mocking:** Bounds validator raises.
**Assertions:**

* HTTP 422 with `error.code == "POST_NUMBER_OUT_OF_BOUNDS"`.
  **AC-Ref:** 6.2.2.46
  **Error Mode:** POST_NUMBER_OUT_OF_BOUNDS

---

**7.2.2.47**
**Title:** Suggestion rejects long_text shorter than minimum length
**Purpose:** Long text must exceed short_text threshold and may include line breaks.
**Test Data:**
`raw_text: "[Hi]"`
**Mocking:** Length heuristic reports < min.
**Assertions:**

* HTTP 422 with `error.code == "PRE_LONG_TEXT_TOO_SHORT"`.
  **AC-Ref:** 6.2.2.47
  **Error Mode:** PRE_LONG_TEXT_TOO_SHORT

---

**7.2.2.48**
**Title:** Suggestion rejects short_string longer than allowed
**Purpose:** Short text upper bound enforcement.
**Test Data:**
`raw_text` 350 characters, no line breaks.
**Mocking:** Heuristic flags length > limit.
**Assertions:**

* HTTP 422 with `error.code == "PRE_SHORT_STRING_TOO_LONG"`.
  **AC-Ref:** 6.2.2.48
  **Error Mode:** PRE_SHORT_STRING_TOO_LONG

---

**7.2.2.49**
**Title:** Bind rejects nested placeholder option pointing to different document
**Purpose:** Parent option’s `placeholder_id` must reference a child in same document.
**Test Data:**
Parent doc A; child placeholder_id belongs to doc B.
**Mocking:** Repo returns mismatched document IDs.
**Assertions:**

* HTTP 409 with `error.code == "POST_BIND_NESTED_PLACEHOLDER_DOCUMENT_MISMATCH"`.
  **AC-Ref:** 6.2.2.49
  **Error Mode:** POST_BIND_NESTED_PLACEHOLDER_DOCUMENT_MISMATCH

---

**7.2.2.50**
**Title:** Purge rejects body with invalid `reason` enum
**Purpose:** Validate optional body fields.
**Test Data:**
Body `{ "reason": "because" }`
**Mocking:** None beyond HTTP.
**Assertions:**

* HTTP 400 with `error.code == "PRE_PURGE_REASON_INVALID"`.
  **AC-Ref:** 6.2.2.50
  **Error Mode:** PRE_PURGE_REASON_INVALID

**7.2.2.51**
**Title:** Suggest rejects non-string `raw_text`
**Purpose:** Enforce `raw_text` type contract.
**Test Data:** `raw_text: 12345`, `context.document_id: "3f1c2f3a-54d0-447f-9a2c-6a9e0f7a2f11"`, `clause_path: "1.2.3"`.
**Mocking:** HTTP boundary only; validator invoked. Assert handler receives numeric `raw_text`.
**Assertions:** HTTP 400; `error.code == "PRE_PLACEHOLDER_PROBE_RAW_TEXT_TYPE_INVALID"`.
**AC-Ref:** 6.2.2.51
**Error Mode:** PRE_PLACEHOLDER_PROBE_RAW_TEXT_TYPE_INVALID

---

**7.2.2.52**
**Title:** Suggest rejects missing `context` object
**Purpose:** Require context container.
**Test Data:** `{ "raw_text": "[YES]" }` (no `context`).
**Mocking:** HTTP boundary; no classifier call.
**Assertions:** HTTP 400; `error.code == "PRE_PLACEHOLDER_PROBE_CONTEXT_MISSING"`.
**AC-Ref:** 6.2.2.52
**Error Mode:** PRE_PLACEHOLDER_PROBE_CONTEXT_MISSING

---

**7.2.2.53**
**Title:** Suggest rejects extra unknown top-level fields
**Purpose:** Strict schema without additionalProperties.
**Test Data:** `{ "raw_text":"[YES]","context":{...},"extra":"x" }`.
**Mocking:** HTTP boundary.
**Assertions:** HTTP 400; `error.code == "PRE_TRANSFORM_SUGGEST_PAYLOAD_SCHEMA_VIOLATION"`.
**AC-Ref:** 6.2.2.53
**Error Mode:** PRE_TRANSFORM_SUGGEST_PAYLOAD_SCHEMA_VIOLATION

---

**7.2.2.54**
**Title:** Suggest rejects `span` with non-integer indices
**Purpose:** Span numeric integrity.
**Test Data:** `span: { "start": "0", "end": "10" }`.
**Mocking:** HTTP boundary.
**Assertions:** HTTP 400; `error.code == "PRE_PLACEHOLDER_PROBE_CONTEXT_SPAN_TYPE_INVALID"`.
**AC-Ref:** 6.2.2.54
**Error Mode:** PRE_PLACEHOLDER_PROBE_CONTEXT_SPAN_TYPE_INVALID

---

**7.2.2.55**
**Title:** Suggest rejects `document_id` not matching probe receipt later
**Purpose:** Context consistency.
**Test Data:** Suggest with `document_id A`; later bind uses receipt for `document_id B`.
**Mocking:** Suggest returns probe for A; bind checks mismatch.
**Assertions:** Bind HTTP 409; `error.code == "PRE_BIND_DOCUMENT_CONTEXT_MISMATCH"`.
**AC-Ref:** 6.2.2.55
**Error Mode:** PRE_BIND_DOCUMENT_CONTEXT_MISMATCH

---

**7.2.2.56**
**Title:** Suggest rejects boolean inclusion with OR content
**Purpose:** Enforce “no ORs” in boolean-inclusion.
**Test Data:** `raw_text: "[INCLUDE PROBATION OR NOTICE]"`.
**Mocking:** Classifier flags invalid composition.
**Assertions:** HTTP 422; `error.code == "PRE_BOOLEAN_INCLUSION_CONTAINS_OR"`.
**AC-Ref:** 6.2.2.56
**Error Mode:** PRE_BOOLEAN_INCLUSION_CONTAINS_OR

---

**7.2.2.57**
**Title:** Suggest rejects enum with duplicated literal tokens
**Purpose:** No duplicates post-canonicalisation.
**Test Data:** `"Intranet OR intranet"`.
**Mocking:** Parser returns duplicate canonical `INTRANET`.
**Assertions:** HTTP 422; `error.code == "PRE_ENUM_DUPLICATE_LITERALS"`.
**AC-Ref:** 6.2.2.57
**Error Mode:** PRE_ENUM_DUPLICATE_LITERALS

---

**7.2.2.58**
**Title:** Suggest rejects mixed enum with empty nested token
**Purpose:** Placeholder key must not be empty.
**Test Data:** `"Manager OR []"`.
**Mocking:** Parser yields empty token.
**Assertions:** HTTP 422; `error.code == "PRE_ENUM_PLACEHOLDER_KEY_EMPTY"`.
**AC-Ref:** 6.2.2.58
**Error Mode:** PRE_ENUM_PLACEHOLDER_KEY_EMPTY

---

**7.2.2.59**
**Title:** Suggest rejects `short_string` with line breaks
**Purpose:** Short-string “no line breaks” rule.
**Test Data:** `"[LINE\nBREAK]"`.
**Mocking:** Classifier flags.
**Assertions:** HTTP 422; `error.code == "PRE_SHORT_STRING_LINE_BREAKS_NOT_ALLOWED"`.
**AC-Ref:** 6.2.2.59
**Error Mode:** PRE_SHORT_STRING_LINE_BREAKS_NOT_ALLOWED

---

**7.2.2.60**
**Title:** Suggest rejects `long_text` without brackets
**Purpose:** Placeholder syntax enforcement.
**Test Data:** `"GENERAL DETAILS ABOUT …"` (no brackets).
**Mocking:** Parser flags missing brackets.
**Assertions:** HTTP 422; `error.code == "PRE_PLACEHOLDER_SYNTAX_NOT_BRACKETED"`.
**AC-Ref:** 6.2.2.60
**Error Mode:** PRE_PLACEHOLDER_SYNTAX_NOT_BRACKETED

---

**7.2.2.61**
**Title:** Bind rejects `verify` with side effects attempted
**Purpose:** Verify mode must not write.
**Test Data:** `apply_mode: "verify"`.
**Mocking:** DB repo mock asserts no writes; inject handler code path that would attempt write → raise.
**Assertions:** HTTP 500; `error.code == "RUN_BIND_VERIFY_MODE_WITH_WRITE_ATTEMPT"`.
**AC-Ref:** 6.2.2.61
**Error Mode:** RUN_BIND_VERIFY_MODE_WITH_WRITE_ATTEMPT

---

**7.2.2.62**
**Title:** Bind rejects stale `probe.resolved_span` against updated clause
**Purpose:** Drift detection via `doc_etag`.
**Test Data:** Suggest returned `doc_etag: "v1"`; current is `"v2"`.
**Mocking:** Document service returns ETag `"v2"`.
**Assertions:** HTTP 409; `error.code == "PRE_BIND_DOCUMENT_ETAG_MISMATCH"`.
**AC-Ref:** 6.2.2.62
**Error Mode:** PRE_BIND_DOCUMENT_ETAG_MISMATCH

---

**7.2.2.63**
**Title:** Bind rejects invalid `option_labelling` value
**Purpose:** Enum of `value`|`value_label`.
**Test Data:** `"option_labelling":"labels_only"`.
**Mocking:** HTTP validation.
**Assertions:** HTTP 400; `error.code == "PRE_BIND_OPTION_LABELLING_INVALID"`.
**AC-Ref:** 6.2.2.63
**Error Mode:** PRE_BIND_OPTION_LABELLING_INVALID

---

**7.2.2.64**
**Title:** Bind rejects suggestion/transform mismatch for text
**Purpose:** Transform must be applicable to `raw_text`.
**Test Data:** Transform `"enum_single"` but `raw_text:"[YES]"`.
**Mocking:** Classifier returns `boolean`; applicability check fails.
**Assertions:** HTTP 422; `error.code == "PRE_BIND_TRANSFORM_NOT_APPLICABLE"`.
**AC-Ref:** 6.2.2.64
**Error Mode:** PRE_BIND_TRANSFORM_NOT_APPLICABLE

---

**7.2.2.65**
**Title:** Bind rejects conflicting nested option mapping by value token
**Purpose:** Parent option value must equal nested key token.
**Test Data:** Parent value `"POSITION"`, child key `"ROLE"`.
**Mocking:** Comparator detects mismatch.
**Assertions:** HTTP 409; `error.code == "POST_BIND_NESTED_OPTION_VALUE_MISMATCH"`.
**AC-Ref:** 6.2.2.65
**Error Mode:** POST_BIND_NESTED_OPTION_VALUE_MISMATCH

---

**7.2.2.66**
**Title:** Bind rejects duplicate binding of identical span to same question
**Purpose:** Idempotency without key should not duplicate.
**Test Data:** Same payload, different `Idempotency-Key`.
**Mocking:** Repo unique constraint on `(question_id, document_id, clause_path, span)`.
**Assertions:** HTTP 409; `error.code == "POST_BIND_DUPLICATE_PLACEHOLDER_SPAN"`.
**AC-Ref:** 6.2.2.66
**Error Mode:** POST_BIND_DUPLICATE_PLACEHOLDER_SPAN

---

**7.2.2.67**
**Title:** Bind rejects option label mutation on existing canonical set
**Purpose:** Labels immutable unless via dedicated path.
**Test Data:** Proposed label differs from stored for `HR_MANAGER`.
**Mocking:** Comparator flags forbidden label delta.
**Assertions:** HTTP 409; `error.code == "POST_BIND_LABEL_CHANGE_NOT_ALLOWED"`.
**AC-Ref:** 6.2.2.67
**Error Mode:** POST_BIND_LABEL_CHANGE_NOT_ALLOWED

---

**7.2.2.68**
**Title:** Bind rejects extra option introduced by second placeholder
**Purpose:** Option set fixed after first bind.
**Test Data:** Existing `["HR_MANAGER"]`; proposed adds `"THE_COO"`.
**Mocking:** Comparator flags added token.
**Assertions:** HTTP 409; `error.code == "POST_BIND_OPTIONS_ADDED_NOT_ALLOWED"`.
**AC-Ref:** 6.2.2.68
**Error Mode:** POST_BIND_OPTIONS_ADDED_NOT_ALLOWED

---

**7.2.2.69**
**Title:** Bind rejects removed option due to conflicting suggestion
**Purpose:** No removal of canonical options.
**Test Data:** Existing `["HR_MANAGER","THE_COO"]`; proposed just `["HR_MANAGER"]`.
**Mocking:** Comparator flags removed token.
**Assertions:** HTTP 409; `error.code == "POST_BIND_OPTIONS_REMOVED_NOT_ALLOWED"`.
**AC-Ref:** 6.2.2.69
**Error Mode:** POST_BIND_OPTIONS_REMOVED_NOT_ALLOWED

---

**7.2.2.70**
**Title:** Bind rejects enum option with non-canonical value format
**Purpose:** Enforce UPPER_SNAKE_CASE.
**Test Data:** Option `value:"HrManager"`.
**Mocking:** Validator rejects pattern.
**Assertions:** HTTP 422; `error.code == "PRE_OPTION_VALUE_NOT_CANONICAL"`.
**AC-Ref:** 6.2.2.70
**Error Mode:** PRE_OPTION_VALUE_NOT_CANONICAL

---

**7.2.2.71**
**Title:** Bind rejects enum option label missing when `option_labelling=value_label`
**Purpose:** Require labels in this mode.
**Test Data:** `option_labelling:"value_label"`; omit label.
**Mocking:** Validator.
**Assertions:** HTTP 400; `error.code == "PRE_OPTION_LABEL_REQUIRED"`.
**AC-Ref:** 6.2.2.71
**Error Mode:** PRE_OPTION_LABEL_REQUIRED

---

**7.2.2.72**
**Title:** Unbind rejects placeholder belonging to different question
**Purpose:** Integrity of question linkage.
**Test Data:** `placeholder_id` links to another `question_id`.
**Mocking:** Repo shows mismatch.
**Assertions:** HTTP 409; `error.code == "POST_UNBIND_QUESTION_MISMATCH"`.
**AC-Ref:** 6.2.2.72
**Error Mode:** POST_UNBIND_QUESTION_MISMATCH

---

**7.2.2.73**
**Title:** Unbind rejects when placeholder already deleted
**Purpose:** No-op must surface not found.
**Test Data:** Valid UUID not present.
**Mocking:** Repo delete returns 0 rows affected.
**Assertions:** HTTP 404; `error.code == "PRE_UNBIND_PLACEHOLDER_NOT_FOUND"`.
**AC-Ref:** 6.2.2.73
**Error Mode:** PRE_UNBIND_PLACEHOLDER_NOT_FOUND

---

**7.2.2.74**
**Title:** Unbind rejects invalid ETag weak/strong mix
**Purpose:** Require strong ETag format.
**Test Data:** `If-Match: W/"abc"`.
**Mocking:** Validator rejects weak ETag.
**Assertions:** HTTP 400; `error.code == "PRE_UNBIND_IF_MATCH_FORMAT_INVALID"`.
**AC-Ref:** 6.2.2.74
**Error Mode:** PRE_UNBIND_IF_MATCH_FORMAT_INVALID

---

**7.2.2.75**
**Title:** List rejects invalid `question_id` format
**Purpose:** Path param validation.
**Test Data:** `/questions/123/placeholders`.
**Mocking:** HTTP boundary.
**Assertions:** HTTP 400; `error.code == "PRE_LIST_QUESTION_ID_INVALID"`.
**AC-Ref:** 6.2.2.75
**Error Mode:** PRE_LIST_QUESTION_ID_INVALID

---

**7.2.2.76**
**Title:** List rejects conflicting filters
**Purpose:** Disallow mutually exclusive params (if specified in spec).
**Test Data:** `document_id` + `since_etag` together (assume exclusive).
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_LIST_FILTERS_CONFLICT"`.
**AC-Ref:** 6.2.2.76
**Error Mode:** PRE_LIST_FILTERS_CONFLICT

---

**7.2.2.77**
**Title:** Purge rejects missing Content-Type
**Purpose:** Contract requires `application/json`.
**Test Data:** POST with no `Content-Type`.
**Mocking:** HTTP boundary.
**Assertions:** HTTP 400; `error.code == "PRE_PURGE_CONTENT_TYPE_MISSING"`.
**AC-Ref:** 6.2.2.77
**Error Mode:** PRE_PURGE_CONTENT_TYPE_MISSING

---

**7.2.2.78**
**Title:** Purge rejects non-JSON body
**Purpose:** Body must parse as JSON.
**Test Data:** Raw text “not json”.
**Mocking:** JSON parser raises.
**Assertions:** HTTP 400; `error.code == "PRE_PURGE_BODY_NOT_JSON"`.
**AC-Ref:** 6.2.2.78
**Error Mode:** PRE_PURGE_BODY_NOT_JSON

---

**7.2.2.79**
**Title:** Suggest runtime timeout surfaces error
**Purpose:** Timeouts mapped to runtime error.
**Test Data:** Valid request.
**Mocking:** Classifier future times out.
**Assertions:** HTTP 500; `error.code == "RUN_SUGGEST_TIMEOUT"`.
**AC-Ref:** 6.2.2.79
**Error Mode:** RUN_SUGGEST_TIMEOUT

---

**7.2.2.80**
**Title:** Suggest runtime null dereference surfaces error
**Purpose:** Defensive runtime mapping.
**Test Data:** Valid request.
**Mocking:** Classifier raises `NullAccessError`.
**Assertions:** HTTP 500; `error.code == "RUN_SUGGEST_INTERNAL_EXCEPTION"`.
**AC-Ref:** 6.2.2.80
**Error Mode:** RUN_SUGGEST_INTERNAL_EXCEPTION

---

**7.2.2.81**
**Title:** Bind runtime transaction begin failure
**Purpose:** Surface begin error.
**Test Data:** Valid bind.
**Mocking:** Tx manager `.begin` raises.
**Assertions:** HTTP 500; `error.code == "RUN_BIND_TRANSACTION_BEGIN_FAILURE"`.
**AC-Ref:** 6.2.2.81
**Error Mode:** RUN_BIND_TRANSACTION_BEGIN_FAILURE

---

**7.2.2.82**
**Title:** Bind runtime transaction commit failure
**Purpose:** Surface commit error.
**Test Data:** Valid bind.
**Mocking:** Tx manager `.commit` raises.
**Assertions:** HTTP 500; `error.code == "RUN_BIND_TRANSACTION_COMMIT_FAILURE"`.
**AC-Ref:** 6.2.2.82
**Error Mode:** RUN_BIND_TRANSACTION_COMMIT_FAILURE

---

**7.2.2.83**
**Title:** Bind runtime ETag generation failure
**Purpose:** Map ETag utility failure.
**Test Data:** Valid bind.
**Mocking:** ETag utility throws.
**Assertions:** HTTP 500; `error.code == "RUN_BIND_ETAG_GENERATION_FAILURE"`.
**AC-Ref:** 6.2.2.83
**Error Mode:** RUN_BIND_ETAG_GENERATION_FAILURE

---

**7.2.2.84**
**Title:** Unbind runtime ETag generation failure
**Purpose:** Map ETag error on unbind.
**Test Data:** Valid unbind.
**Mocking:** ETag utility throws.
**Assertions:** HTTP 500; `error.code == "RUN_UNBIND_ETAG_GENERATION_FAILURE"`.
**AC-Ref:** 6.2.2.84
**Error Mode:** RUN_UNBIND_ETAG_GENERATION_FAILURE

---

**7.2.2.85**
**Title:** List runtime ETag retrieval failure
**Purpose:** Surface query for ETag failure.
**Test Data:** Valid list.
**Mocking:** Repo `getQuestionETag` throws.
**Assertions:** HTTP 500; `error.code == "RUN_LIST_ETAG_READ_FAILURE"`.
**AC-Ref:** 6.2.2.85
**Error Mode:** RUN_LIST_ETAG_READ_FAILURE

---

**7.2.2.86**
**Title:** Catalog runtime serialization failure
**Purpose:** Map to runtime error.
**Test Data:** Valid request.
**Mocking:** Serializer raises.
**Assertions:** HTTP 500; `error.code == "RUN_CATALOG_SERIALIZATION_FAILURE"`.
**AC-Ref:** 6.2.2.86
**Error Mode:** RUN_CATALOG_SERIALIZATION_FAILURE

---

**7.2.2.87**
**Title:** Preview runtime option canonicaliser failure
**Purpose:** Map canonicaliser crash.
**Test Data:** Valid payload.
**Mocking:** Canonicaliser throws `ValueError`.
**Assertions:** HTTP 500; `error.code == "RUN_PREVIEW_OPTION_CANON_FAILURE"`.
**AC-Ref:** 6.2.2.87
**Error Mode:** RUN_PREVIEW_OPTION_CANON_FAILURE

---

**7.2.2.88**
**Title:** Suggest rejects empty brackets `[]`
**Purpose:** Placeholder token cannot be empty.
**Test Data:** `raw_text:"[]"`.
**Mocking:** Parser flags.
**Assertions:** HTTP 422; `error.code == "PRE_PLACEHOLDER_EMPTY"`.
**AC-Ref:** 6.2.2.88
**Error Mode:** PRE_PLACEHOLDER_EMPTY

---

**7.2.2.89**
**Title:** Suggest rejects disallowed characters inside brackets
**Purpose:** Token character set enforcement.
**Test Data:** `"[POSI*TION]"`.
**Mocking:** Token validator flags.
**Assertions:** HTTP 422; `error.code == "PRE_PLACEHOLDER_TOKEN_INVALID_CHARS"`.
**AC-Ref:** 6.2.2.89
**Error Mode:** PRE_PLACEHOLDER_TOKEN_INVALID_CHARS

---

**7.2.2.90**
**Title:** Suggest rejects OR list with trailing OR
**Purpose:** Syntax integrity for enum lists.
**Test Data:** `"Manager OR "`.
**Mocking:** Parser yields unterminated.
**Assertions:** HTTP 422; `error.code == "PRE_ENUM_SYNTAX_TRAILING_OR"`.
**AC-Ref:** 6.2.2.90
**Error Mode:** PRE_ENUM_SYNTAX_TRAILING_OR

---

**7.2.2.91**
**Title:** Suggest rejects OR list with leading OR
**Purpose:** Syntax integrity.
**Test Data:** `"OR Manager"`.
**Mocking:** Parser flags.
**Assertions:** HTTP 422; `error.code == "PRE_ENUM_SYNTAX_LEADING_OR"`.
**AC-Ref:** 6.2.2.91
**Error Mode:** PRE_ENUM_SYNTAX_LEADING_OR

---

**7.2.2.92**
**Title:** Suggest rejects OR list with consecutive ORs
**Purpose:** Syntax integrity.
**Test Data:** `"Manager OR OR COO"`.
**Mocking:** Parser flags.
**Assertions:** HTTP 422; `error.code == "PRE_ENUM_SYNTAX_CONSECUTIVE_OR"`.
**AC-Ref:** 6.2.2.92
**Error Mode:** PRE_ENUM_SYNTAX_CONSECUTIVE_OR

---

**7.2.2.93**
**Title:** Suggest rejects mixed literal and non-bracketed variable
**Purpose:** Require brackets for variable.
**Test Data:** `"Manager OR POSITION"`.
**Mocking:** Parser flags.
**Assertions:** HTTP 422; `error.code == "PRE_ENUM_UNBRACKETED_PLACEHOLDER"`.
**AC-Ref:** 6.2.2.93
**Error Mode:** PRE_ENUM_UNBRACKETED_PLACEHOLDER

---

**7.2.2.94**
**Title:** Suggest rejects nested brackets
**Purpose:** No nesting at this level.
**Test Data:** `"[OUTER [INNER]]"`.
**Mocking:** Parser flags.
**Assertions:** HTTP 422; `error.code == "PRE_PLACEHOLDER_NESTING_NOT_SUPPORTED"`.
**AC-Ref:** 6.2.2.94
**Error Mode:** PRE_PLACEHOLDER_NESTING_NOT_SUPPORTED

---

**7.2.2.95**
**Title:** Bind rejects parent-child cycle detection
**Purpose:** Prevent cyclic linkage.
**Test Data:** Parent option targets child; child option targets parent.
**Mocking:** Graph checker detects cycle.
**Assertions:** HTTP 409; `error.code == "POST_BIND_NESTED_CYCLE_DETECTED"`.
**AC-Ref:** 6.2.2.95
**Error Mode:** POST_BIND_NESTED_CYCLE_DETECTED

---

**7.2.2.96**
**Title:** Bind rejects child placeholder outside parent span
**Purpose:** Spatial containment required.
**Test Data:** Child span does not sit within parent.
**Mocking:** Span comparator flags.
**Assertions:** HTTP 409; `error.code == "POST_BIND_CHILD_NOT_WITHIN_PARENT_SPAN"`.
**AC-Ref:** 6.2.2.96
**Error Mode:** POST_BIND_CHILD_NOT_WITHIN_PARENT_SPAN

---

**7.2.2.97**
**Title:** Bind rejects boolean transform on enum-established question
**Purpose:** Answer-kind immutability.
**Test Data:** Existing `enum_single`; new `boolean`.
**Mocking:** Comparator flags.
**Assertions:** HTTP 409; `error.code == "POST_BIND_MODEL_CONFLICT_ANSWER_KIND_CHANGED"`.
**AC-Ref:** 6.2.2.97
**Error Mode:** POST_BIND_MODEL_CONFLICT_ANSWER_KIND_CHANGED

---

**7.2.2.98**
**Title:** Bind rejects number transform on text-established question
**Purpose:** Answer-kind immutability.
**Test Data:** Existing `short_string`; new `number`.
**Mocking:** Comparator flags.
**Assertions:** HTTP 409; `error.code == "POST_BIND_MODEL_CONFLICT_ANSWER_KIND_CHANGED"`.
**AC-Ref:** 6.2.2.98
**Error Mode:** POST_BIND_MODEL_CONFLICT_ANSWER_KIND_CHANGED

---

**7.2.2.99**
**Title:** Bind rejects enum where canonical values differ only by case
**Purpose:** Case-insensitive canonical uniqueness.
**Test Data:** `HR_Manager` vs `HR_MANAGER`.
**Mocking:** Canonicaliser normalises; comparator flags collision.
**Assertions:** HTTP 409; `error.code == "POST_BIND_OPTION_VALUE_COLLISION"`.
**AC-Ref:** 6.2.2.99
**Error Mode:** POST_BIND_OPTION_VALUE_COLLISION

---

**7.2.2.100**
**Title:** Bind rejects enum where literal label disappears
**Purpose:** Labels must preserve original literal text (unless overridden via dedicated UI).
**Test Data:** Proposed label “HR” for literal “The HR Manager”.
**Mocking:** Label validator flags.
**Assertions:** HTTP 409; `error.code == "POST_BIND_LABEL_MISMATCH_WITH_LITERAL"`.
**AC-Ref:** 6.2.2.100
**Error Mode:** POST_BIND_LABEL_MISMATCH_WITH_LITERAL

---

**7.2.2.101**
**Title:** Preview rejects both `raw_text` and `literals` present
**Purpose:** Inputs are mutually exclusive.
**Test Data:** `{ "raw_text":"x", "literals":["y"] }`.
**Mocking:** Validator flags conflict.
**Assertions:** HTTP 400; `error.code == "PRE_PREVIEW_MUTUALLY_EXCLUSIVE_INPUTS"`.
**AC-Ref:** 6.2.2.101
**Error Mode:** PRE_PREVIEW_MUTUALLY_EXCLUSIVE_INPUTS

---

**7.2.2.102**
**Title:** Preview rejects empty `literals` array
**Purpose:** Non-empty list required.
**Test Data:** `{ "literals":[] }`.
**Mocking:** Validator flags.
**Assertions:** HTTP 422; `error.code == "PRE_PREVIEW_LITERALS_EMPTY"`.
**AC-Ref:** 6.2.2.102
**Error Mode:** PRE_PREVIEW_LITERALS_EMPTY

---

**7.2.2.103**
**Title:** Preview rejects non-string literal in array
**Purpose:** Type integrity.
**Test Data:** `{ "literals":["Manager",42] }`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_PREVIEW_LITERAL_TYPE_INVALID"`.
**AC-Ref:** 6.2.2.103
**Error Mode:** PRE_PREVIEW_LITERAL_TYPE_INVALID

---

**7.2.2.104**
**Title:** Catalog rejects unsupported Accept header
**Purpose:** Only `application/json` supported.
**Test Data:** `Accept: text/xml`.
**Mocking:** HTTP boundary.
**Assertions:** HTTP 406; `error.code == "PRE_CATALOG_NOT_ACCEPTABLE"`.
**AC-Ref:** 6.2.2.104
**Error Mode:** PRE_CATALOG_NOT_ACCEPTABLE

---

**7.2.2.105**
**Title:** Suggest rejects UTF-16 surrogate pairs in token
**Purpose:** Restrict token charset.
**Test Data:** `raw_text:"[\uD83D\uDE80]"` (rocket emoji).
**Mocking:** Validator flags.
**Assertions:** HTTP 422; `error.code == "PRE_PLACEHOLDER_TOKEN_INVALID_CHARS"`.
**AC-Ref:** 6.2.2.105
**Error Mode:** PRE_PLACEHOLDER_TOKEN_INVALID_CHARS

---

**7.2.2.106**
**Title:** Suggest rejects excessive token length
**Purpose:** Upper bound for token length.
**Test Data:** 300-char token inside brackets.
**Mocking:** Validator flags.
**Assertions:** HTTP 422; `error.code == "PRE_PLACEHOLDER_TOKEN_TOO_LONG"`.
**AC-Ref:** 6.2.2.106
**Error Mode:** PRE_PLACEHOLDER_TOKEN_TOO_LONG

---

**7.2.2.107**
**Title:** Bind rejects `probe.resolved_span` missing
**Purpose:** Receipt must contain span.
**Test Data:** `probe` missing `resolved_span`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_BIND_PROBE_SPAN_MISSING"`.
**AC-Ref:** 6.2.2.107
**Error Mode:** PRE_BIND_PROBE_SPAN_MISSING

---

**7.2.2.108**
**Title:** Bind rejects `probe_hash` missing
**Purpose:** Idempotence/continuity requirement.
**Test Data:** `probe` without `probe_hash`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_BIND_PROBE_HASH_MISSING"`.
**AC-Ref:** 6.2.2.108
**Error Mode:** PRE_BIND_PROBE_HASH_MISSING

---

**7.2.2.109**
**Title:** Bind rejects `placeholder_key` mismatch against suggestion
**Purpose:** Key must match suggestion receipt.
**Test Data:** Suggest key “POSITION”; bind shows “ROLE”.
**Mocking:** Comparator flags.
**Assertions:** HTTP 409; `error.code == "PRE_BIND_PLACEHOLDER_KEY_MISMATCH"`.
**AC-Ref:** 6.2.2.109
**Error Mode:** PRE_BIND_PLACEHOLDER_KEY_MISMATCH

---

**7.2.2.110**
**Title:** Bind rejects transform not found in catalog
**Purpose:** Must be in `/transforms/catalog`.
**Test Data:** `transform_id:"unknown"`
**Mocking:** Catalog lookup returns empty.
**Assertions:** HTTP 422; `error.code == "PRE_BIND_TRANSFORM_ID_UNKNOWN"`.
**AC-Ref:** 6.2.2.110
**Error Mode:** PRE_BIND_TRANSFORM_ID_UNKNOWN

---

**7.2.2.111**
**Title:** Bind rejects enum option with `placeholder_id` that does not exist
**Purpose:** FK integrity.
**Test Data:** Parent option proposes `placeholder_id` non-existent.
**Mocking:** Repo returns None for FK.
**Assertions:** HTTP 404; `error.code == "PRE_BIND_NESTED_PLACEHOLDER_NOT_FOUND"`.
**AC-Ref:** 6.2.2.111
**Error Mode:** PRE_BIND_NESTED_PLACEHOLDER_NOT_FOUND

---

**7.2.2.112**
**Title:** Bind rejects nested placeholder referencing different question
**Purpose:** FK integrity across question scope.
**Test Data:** Child belongs to other question.
**Mocking:** Repo shows mismatch.
**Assertions:** HTTP 409; `error.code == "POST_BIND_NESTED_QUESTION_MISMATCH"`.
**AC-Ref:** 6.2.2.112
**Error Mode:** POST_BIND_NESTED_QUESTION_MISMATCH

---

**7.2.2.113**
**Title:** Bind rejects nested placeholder key not present in parent options
**Purpose:** Parent must have corresponding option.
**Test Data:** Child key “ROLE”; parent options don’t contain “ROLE”.
**Mocking:** Comparator flags.
**Assertions:** HTTP 409; `error.code == "POST_BIND_NESTED_OPTION_MISSING_FOR_KEY"`.
**AC-Ref:** 6.2.2.113
**Error Mode:** POST_BIND_NESTED_OPTION_MISSING_FOR_KEY

---

**7.2.2.114**
**Title:** Bind rejects boolean when placeholder body is empty
**Purpose:** Inclusion requires a body.
**Test Data:** `"[]"`
**Mocking:** Classifier flags.
**Assertions:** HTTP 422; `error.code == "PRE_BOOLEAN_INCLUSION_BODY_EMPTY"`.
**AC-Ref:** 6.2.2.114
**Error Mode:** PRE_BOOLEAN_INCLUSION_BODY_EMPTY

---

**7.2.2.115**
**Title:** Bind rejects number with mixed digits and letters when numeric required
**Purpose:** Strict numeric.
**Test Data:** `"[12AB]"`.
**Mocking:** Number detector flags.
**Assertions:** HTTP 422; `error.code == "PRE_NUMBER_NOT_NUMERIC"`.
**AC-Ref:** 6.2.2.115
**Error Mode:** PRE_NUMBER_NOT_NUMERIC

---

**7.2.2.116**
**Title:** Suggest rejects number with multiple numeric tokens
**Purpose:** Single numeric token expected.
**Test Data:** `"[30 60]"`.
**Mocking:** Detector flags.
**Assertions:** HTTP 422; `error.code == "PRE_NUMBER_MULTIPLE_TOKENS"`.
**AC-Ref:** 6.2.2.116
**Error Mode:** PRE_NUMBER_MULTIPLE_TOKENS

---

**7.2.2.117**
**Title:** Suggest rejects number with negative sign if not allowed
**Purpose:** Non-negative constraint.
**Test Data:** `[-5]`.
**Mocking:** Detector flags.
**Assertions:** HTTP 422; `error.code == "PRE_NUMBER_NEGATIVE_NOT_ALLOWED"`.
**AC-Ref:** 6.2.2.117
**Error Mode:** PRE_NUMBER_NEGATIVE_NOT_ALLOWED

---

**7.2.2.118**
**Title:** Suggest rejects number with decimal if integers only
**Purpose:** Integer-only constraint.
**Test Data:** `[3.14]`.
**Mocking:** Detector flags.
**Assertions:** HTTP 422; `error.code == "PRE_NUMBER_DECIMAL_NOT_ALLOWED"`.
**AC-Ref:** 6.2.2.118
**Error Mode:** PRE_NUMBER_DECIMAL_NOT_ALLOWED

---

**7.2.2.119**
**Title:** Suggest rejects unit string without number
**Purpose:** Unit requires numeric.
**Test Data:** `"[DAYS]"`.
**Mocking:** Detector flags.
**Assertions:** HTTP 422; `error.code == "PRE_NUMBER_MISSING_NUMERIC_VALUE"`.
**AC-Ref:** 6.2.2.119
**Error Mode:** PRE_NUMBER_MISSING_NUMERIC_VALUE

---

**7.2.2.120**
**Title:** Preview rejects literals that canonicalise to empty tokens
**Purpose:** Token must remain non-empty after canonicalisation.
**Test Data:** `["   "]`.
**Mocking:** Canonicaliser trims to empty.
**Assertions:** HTTP 422; `error.code == "PRE_PREVIEW_LITERAL_CANON_EMPTY"`.
**AC-Ref:** 6.2.2.120
**Error Mode:** PRE_PREVIEW_LITERAL_CANON_EMPTY

---

**7.2.2.121**
**Title:** Suggest rejects raw_text exceeding max payload size
**Purpose:** Payload size limit.
**Test Data:** 200KB raw_text.
**Mocking:** HTTP layer enforces size.
**Assertions:** HTTP 413; `error.code == "PRE_TRANSFORM_SUGGEST_PAYLOAD_TOO_LARGE"`.
**AC-Ref:** 6.2.2.121
**Error Mode:** PRE_TRANSFORM_SUGGEST_PAYLOAD_TOO_LARGE

---

**7.2.2.122**
**Title:** Bind rejects payload exceeding max size
**Purpose:** Size limit.
**Test Data:** Large `placeholder.raw_text` 200KB.
**Mocking:** HTTP layer enforces.
**Assertions:** HTTP 413; `error.code == "PRE_BIND_PAYLOAD_TOO_LARGE"`.
**AC-Ref:** 6.2.2.122
**Error Mode:** PRE_BIND_PAYLOAD_TOO_LARGE

---

**7.2.2.123**
**Title:** Unbind rejects payload with extra properties
**Purpose:** Strict schema.
**Test Data:** `{ "placeholder_id":"…", "unexpected":1 }`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_UNBIND_PAYLOAD_SCHEMA_VIOLATION"`.
**AC-Ref:** 6.2.2.123
**Error Mode:** PRE_UNBIND_PAYLOAD_SCHEMA_VIOLATION

---

**7.2.2.124**
**Title:** List rejects unsupported query parameter
**Purpose:** Strict query schema.
**Test Data:** `?foo=bar`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_LIST_QUERY_PARAM_UNKNOWN"`.
**AC-Ref:** 6.2.2.124
**Error Mode:** PRE_LIST_QUERY_PARAM_UNKNOWN

---

**7.2.2.125**
**Title:** Purge rejects unsupported body field
**Purpose:** Strict schema.
**Test Data:** `{ "reason":"deleted", "extra": true }`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_PURGE_BODY_SCHEMA_VIOLATION"`.
**AC-Ref:** 6.2.2.125
**Error Mode:** PRE_PURGE_BODY_SCHEMA_VIOLATION

---

**7.2.2.126**
**Title:** Suggest rejects mismatched `span` vs `raw_text` substring
**Purpose:** Span must match content.
**Test Data:** `span` points to “ABC”; `raw_text` is “[XYZ]”.
**Mocking:** Clause content provider returns “ABC”.
**Assertions:** HTTP 409; `error.code == "PRE_SUGGEST_SPAN_TEXT_MISMATCH"`.
**AC-Ref:** 6.2.2.126
**Error Mode:** PRE_SUGGEST_SPAN_TEXT_MISMATCH

---

**7.2.2.127**
**Title:** Bind rejects mismatched `span` vs `raw_text` substring
**Purpose:** Bind-time verification.
**Test Data:** As above.
**Mocking:** Content provider.
**Assertions:** HTTP 409; `error.code == "PRE_BIND_SPAN_TEXT_MISMATCH"`.
**AC-Ref:** 6.2.2.127
**Error Mode:** PRE_BIND_SPAN_TEXT_MISMATCH

---

**7.2.2.128**
**Title:** Bind rejects `apply_mode` missing
**Purpose:** Required field.
**Test Data:** Omit `apply_mode`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_BIND_APPLY_MODE_MISSING"`.
**AC-Ref:** 6.2.2.128
**Error Mode:** PRE_BIND_APPLY_MODE_MISSING

---

**7.2.2.129**
**Title:** Bind rejects `question_id` missing
**Purpose:** Required field.
**Test Data:** Omit `question_id`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_BIND_QUESTION_ID_MISSING"`.
**AC-Ref:** 6.2.2.129
**Error Mode:** PRE_BIND_QUESTION_ID_MISSING

---

**7.2.2.130**
**Title:** Bind rejects `transform_id` missing
**Purpose:** Required field.
**Test Data:** Omit `transform_id`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_BIND_TRANSFORM_ID_MISSING"`.
**AC-Ref:** 6.2.2.130
**Error Mode:** PRE_BIND_TRANSFORM_ID_MISSING

---

**7.2.2.131**
**Title:** Bind rejects placeholder context `clause_path` malformed
**Purpose:** Clause path format.
**Test Data:** `"clause_path":".."`
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_BIND_CONTEXT_CLAUSE_PATH_INVALID"`.
**AC-Ref:** 6.2.2.131
**Error Mode:** PRE_BIND_CONTEXT_CLAUSE_PATH_INVALID

---

**7.2.2.132**
**Title:** Bind rejects placeholder `raw_text` not bracketed
**Purpose:** Syntax.
**Test Data:** `"raw_text":"YES"`
**Mocking:** Validator flags.
**Assertions:** HTTP 422; `error.code == "PRE_PLACEHOLDER_SYNTAX_NOT_BRACKETED"`.
**AC-Ref:** 6.2.2.132
**Error Mode:** PRE_PLACEHOLDER_SYNTAX_NOT_BRACKETED

---

**7.2.2.133**
**Title:** Unbind rejects body missing `placeholder_id`
**Purpose:** Required field.
**Test Data:** `{}`
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_UNBIND_PLACEHOLDER_ID_MISSING"`.
**AC-Ref:** 6.2.2.133
**Error Mode:** PRE_UNBIND_PLACEHOLDER_ID_MISSING

---

**7.2.2.134**
**Title:** List rejects non-UUID `document_id` filter
**Purpose:** Type/format.
**Test Data:** `?document_id=foo`
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_LIST_DOCUMENT_ID_INVALID"`.
**AC-Ref:** 6.2.2.134
**Error Mode:** PRE_LIST_DOCUMENT_ID_INVALID

---

**7.2.2.135**
**Title:** Purge rejects unknown `reason` casing
**Purpose:** Case-sensitive enum.
**Test Data:** `{ "reason":"Deleted" }`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_PURGE_REASON_INVALID"`.
**AC-Ref:** 6.2.2.135
**Error Mode:** PRE_PURGE_REASON_INVALID

---

**7.2.2.136**
**Title:** Suggest runtime classifier returns invalid kind
**Purpose:** Guard invalid enum value from engine.
**Test Data:** Valid request.
**Mocking:** Classifier returns `answer_kind:"multi_select"` (unsupported).
**Assertions:** HTTP 500; `error.code == "RUN_SUGGEST_ENGINE_INVALID_KIND"`.
**AC-Ref:** 6.2.2.136
**Error Mode:** RUN_SUGGEST_ENGINE_INVALID_KIND

---

**7.2.2.137**
**Title:** Suggest runtime returns enum without options
**Purpose:** Engine invariant violation.
**Test Data:** Valid request.
**Mocking:** Classifier returns `answer_kind:"enum_single", options: []`.
**Assertions:** HTTP 500; `error.code == "RUN_SUGGEST_ENGINE_OPTIONS_EMPTY"`.
**AC-Ref:** 6.2.2.137
**Error Mode:** RUN_SUGGEST_ENGINE_OPTIONS_EMPTY

---

**7.2.2.138**
**Title:** Bind runtime option upsert partial failure
**Purpose:** Partial success must be error.
**Test Data:** Valid enum bind.
**Mocking:** Options repo inserts one succeeds, second fails.
**Assertions:** HTTP 500; `error.code == "RUN_BIND_OPTIONS_UPSERT_FAILURE"`.
**AC-Ref:** 6.2.2.138
**Error Mode:** RUN_BIND_OPTIONS_UPSERT_FAILURE

---

**7.2.2.139**
**Title:** Bind runtime parent lookup failure for nested linkage
**Purpose:** Parent scan crash.
**Test Data:** Valid child bind.
**Mocking:** Parent scan throws.
**Assertions:** HTTP 500; `error.code == "RUN_BIND_PARENT_SCAN_FAILURE"`.
**AC-Ref:** 6.2.2.139
**Error Mode:** RUN_BIND_PARENT_SCAN_FAILURE

---

**7.2.2.140**
**Title:** Unbind runtime cascade cleanup failure
**Purpose:** Cleanup of dependent options fails.
**Test Data:** Valid unbind.
**Mocking:** Cleanup routine throws.
**Assertions:** HTTP 500; `error.code == "RUN_UNBIND_CLEANUP_FAILURE"`.
**AC-Ref:** 6.2.2.140
**Error Mode:** RUN_UNBIND_CLEANUP_FAILURE

---

**7.2.2.141**
**Title:** List runtime serialization failure
**Purpose:** Mapping placeholders to response crashes.
**Test Data:** Valid list.
**Mocking:** Serializer throws.
**Assertions:** HTTP 500; `error.code == "RUN_LIST_SERIALIZATION_FAILURE"`.
**AC-Ref:** 6.2.2.141
**Error Mode:** RUN_LIST_SERIALIZATION_FAILURE

---

**7.2.2.142**
**Title:** Purge runtime enumeration failure
**Purpose:** Scan for placeholders crashes.
**Test Data:** Valid purge.
**Mocking:** Repo `.listByDocument` throws.
**Assertions:** HTTP 500; `error.code == "RUN_PURGE_ENUMERATION_FAILURE"`.
**AC-Ref:** 6.2.2.142
**Error Mode:** RUN_PURGE_ENUMERATION_FAILURE

---

**7.2.2.143**
**Title:** Catalog rejects registry with duplicate IDs
**Purpose:** Registry integrity.
**Test Data:** Registry exposes duplicate transform_id.
**Mocking:** Registry mock returns dupes.
**Assertions:** HTTP 500; `error.code == "RUN_CATALOG_DUPLICATE_TRANSFORM_ID"`.
**AC-Ref:** 6.2.2.143
**Error Mode:** RUN_CATALOG_DUPLICATE_TRANSFORM_ID

---

**7.2.2.144**
**Title:** Preview rejects `literals` producing duplicates after canonicalisation
**Purpose:** Duplicate options forbidden.
**Test Data:** `["Manager","manager"]`.
**Mocking:** Canonicaliser yields same token.
**Assertions:** HTTP 422; `error.code == "PRE_PREVIEW_LITERALS_DUPLICATE_CANON"`.
**AC-Ref:** 6.2.2.144
**Error Mode:** PRE_PREVIEW_LITERALS_DUPLICATE_CANON

---

**7.2.2.145**
**Title:** Suggest rejects boolean inclusion with negation tokens
**Purpose:** No “NOT”/“EXCLUDE” patterns in inclusion.
**Test Data:** `"[NOT INCLUDE PROBATION]"`.
**Mocking:** Detector flags.
**Assertions:** HTTP 422; `error.code == "PRE_BOOLEAN_INCLUSION_NEGATION_NOT_ALLOWED"`.
**AC-Ref:** 6.2.2.145
**Error Mode:** PRE_BOOLEAN_INCLUSION_NEGATION_NOT_ALLOWED

---

**7.2.2.146**
**Title:** Suggest rejects short_string exceeding 200 chars
**Purpose:** Upper bound per spec.
**Test Data:** 250-char token no line breaks.
**Mocking:** Heuristic flags.
**Assertions:** HTTP 422; `error.code == "PRE_SHORT_STRING_TOO_LONG"`.
**AC-Ref:** 6.2.2.146
**Error Mode:** PRE_SHORT_STRING_TOO_LONG

---

**7.2.2.147**
**Title:** Suggest rejects `long_text` with zero line breaks and too short
**Purpose:** Must be multi-line or longer body.
**Test Data:** 40 chars single line.
**Mocking:** Heuristic flags.
**Assertions:** HTTP 422; `error.code == "PRE_LONG_TEXT_TOO_SHORT"`.
**AC-Ref:** 6.2.2.147
**Error Mode:** PRE_LONG_TEXT_TOO_SHORT

---

**7.2.2.148**
**Title:** Bind rejects enum suggestion where labels not original literals
**Purpose:** Preserve original literal text in labels.
**Test Data:** Suggest labels truncated.
**Mocking:** Comparator flags.
**Assertions:** HTTP 409; `error.code == "POST_BIND_LABEL_MISMATCH_WITH_LITERAL"`.
**AC-Ref:** 6.2.2.148
**Error Mode:** POST_BIND_LABEL_MISMATCH_WITH_LITERAL

---

**7.2.2.149**
**Title:** Bind rejects parent option pointing to multiple children
**Purpose:** One-to-one mapping.
**Test Data:** Parent option attempts two `placeholder_id`s.
**Mocking:** Validator flags.
**Assertions:** HTTP 422; `error.code == "PRE_BIND_NESTED_MULTIPLE_CHILDREN_NOT_ALLOWED"`.
**AC-Ref:** 6.2.2.149
**Error Mode:** PRE_BIND_NESTED_MULTIPLE_CHILDREN_NOT_ALLOWED

---

**7.2.2.150**
**Title:** Bind rejects child linked to multiple parent options
**Purpose:** Single parent per child in enum_single context.
**Test Data:** Two parents reference same child.
**Mocking:** Graph checker flags.
**Assertions:** HTTP 409; `error.code == "POST_BIND_CHILD_MULTIPLE_PARENTS_NOT_ALLOWED"`.
**AC-Ref:** 6.2.2.150
**Error Mode:** POST_BIND_CHILD_MULTIPLE_PARENTS_NOT_ALLOWED

---

**7.2.2.151**
**Title:** Bind rejects enum option with blank label when required
**Purpose:** Non-empty label in `value_label` mode.
**Test Data:** Label `""`.
**Mocking:** Validator.
**Assertions:** HTTP 400; `error.code == "PRE_OPTION_LABEL_REQUIRED"`.
**AC-Ref:** 6.2.2.151
**Error Mode:** PRE_OPTION_LABEL_REQUIRED

---

**7.2.2.152**
**Title:** Suggest rejects excessive number of OR literals
**Purpose:** Upper bound on list size.
**Test Data:** 200 literals.
**Mocking:** Parser counts > limit.
**Assertions:** HTTP 422; `error.code == "PRE_ENUM_TOO_MANY_OPTIONS"`.
**AC-Ref:** 6.2.2.152
**Error Mode:** PRE_ENUM_TOO_MANY_OPTIONS

---

**7.2.2.153**
**Title:** Preview rejects literals exceeding max length after canonicalisation
**Purpose:** Token length upper bound.
**Test Data:** One literal 300 chars.
**Mocking:** Canonicaliser produces long token.
**Assertions:** HTTP 422; `error.code == "PRE_PREVIEW_LITERAL_CANON_TOO_LONG"`.
**AC-Ref:** 6.2.2.153
**Error Mode:** PRE_PREVIEW_LITERAL_CANON_TOO_LONG

---

**7.2.2.154**
**Title:** Suggest rejects control characters in literal
**Purpose:** Disallow non-printable chars.
**Test Data:** `"Manager\u0007"` (BEL).
**Mocking:** Validator flags.
**Assertions:** HTTP 422; `error.code == "PRE_ENUM_LITERAL_INVALID_CHARS"`.
**AC-Ref:** 6.2.2.154
**Error Mode:** PRE_ENUM_LITERAL_INVALID_CHARS

---

**7.2.2.155**
**Title:** Bind rejects boolean transform where clause has OR content
**Purpose:** Boolean-inclusion must not encapsulate OR.
**Test Data:** `"[Include X OR Y]"`.
**Mocking:** Applicability check flags.
**Assertions:** HTTP 422; `error.code == "PRE_BOOLEAN_INCLUSION_CONTAINS_OR"`.
**AC-Ref:** 6.2.2.155
**Error Mode:** PRE_BOOLEAN_INCLUSION_CONTAINS_OR

---

**7.2.2.156**
**Title:** Bind rejects transform suggestion not matching engine re-evaluation
**Purpose:** Bind validates suggestion determinism.
**Test Data:** Suggest said enum; re-eval says number.
**Mocking:** Engine re-eval returns different kind.
**Assertions:** HTTP 409; `error.code == "PRE_BIND_SUGGESTION_ENGINE_MISMATCH"`.
**AC-Ref:** 6.2.2.156
**Error Mode:** PRE_BIND_SUGGESTION_ENGINE_MISMATCH

---

**7.2.2.157**
**Title:** Unbind rejects when unbinding would orphan required model state
**Purpose:** Clearing last placeholder must be explicit.
**Test Data:** Unbind with header missing explicit confirm flag (if spec requires).
**Mocking:** Validator flags.
**Assertions:** HTTP 409; `error.code == "POST_UNBIND_MODEL_CLEAR_CONFIRMATION_REQUIRED"`.
**AC-Ref:** 6.2.2.157
**Error Mode:** POST_UNBIND_MODEL_CLEAR_CONFIRMATION_REQUIRED

---

**7.2.2.158**
**Title:** List rejects pagination params out of range
**Purpose:** Enforce bounds.
**Test Data:** `?limit=0&offset=-1`.
**Mocking:** Validator flags.
**Assertions:** HTTP 400; `error.code == "PRE_LIST_PAGINATION_INVALID"`.
**AC-Ref:** 6.2.2.158
**Error Mode:** PRE_LIST_PAGINATION_INVALID

---

**7.2.2.159**
**Title:** Purge rejects idempotency replay with mismatched body
**Purpose:** Idempotency safety.
**Test Data:** Same `Idempotency-Key` with different `reason`.
**Mocking:** Idempotency store returns previous fingerprint.
**Assertions:** HTTP 409; `error.code == "PRE_PURGE_IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"`.
**AC-Ref:** 6.2.2.159
**Error Mode:** PRE_PURGE_IDEMPOTENCY_KEY_PAYLOAD_MISMATCH

---

**7.2.2.160**
**Title:** Suggest rejects conflicting `context.document_id` between URL and body (if URL-scoped)
**Purpose:** Path/body consistency.
**Test Data:** URL doc=A; body context doc=B.
**Mocking:** Router provides URL param; validator compares.
**Assertions:** HTTP 409; `error.code == "PRE_SUGGEST_DOCUMENT_CONTEXT_MISMATCH"`.
**AC-Ref:** 6.2.2.160
**Error Mode:** PRE_SUGGEST_DOCUMENT_CONTEXT_MISMATCH

---

**7.2.2.161**
**Title:** Bind rejects suggestion where enum option values collide with placeholder keys
**Purpose:** Disallow value/key namespace collisions.
**Test Data:** Literal canonicalises to `POSITION` and also nested key `POSITION`.
**Mocking:** Comparator flags collision.
**Assertions:** HTTP 409; `error.code == "POST_BIND_ENUM_VALUE_PLACEHOLDER_KEY_COLLISION"`.
**AC-Ref:** 6.2.2.161
**Error Mode:** POST_BIND_ENUM_VALUE_PLACEHOLDER_KEY_COLLISION

**7.3.1.1 — Suggest → Bind-init triggers**

**Title:** Transform suggestion completion triggers bind initiation
**Purpose:** Verify that, after a successful transform suggestion, the bind flow is initiated.
**Test Data:** `document_id="doc-001"`, `clause_path="1.2"`, `raw_text="[The HR Manager OR POSITION]"`, `span={start:120,end:149}`.
**Mocking:** Mock `POST /api/v1/transforms/suggest` to return a valid `TransformSuggestion` (answer_kind=`enum_single`, options present) and a `ProbeReceipt`. Returns immediately with a dummy success body.
**Assertions:** Assert bind initiation is invoked once immediately after suggestion completes, and not before.
**AC-Ref:** 6.3.1.1

---

**7.3.1.2 — First bind (no existing model) → Model set**

**Title:** First successful bind triggers model-setting step
**Purpose:** Verify that, after first bind, the question model-setting step is invoked.
**Test Data:** `question_id="q-001"`, `apply_mode="apply"`, suggestion from prior step (enum_single).
**Mocking:** Mock `POST /api/v1/placeholders/bind` to succeed and indicate “no existing model” case.
**Assertions:** Assert model-setting step is invoked once immediately after bind completes, and not before.
**AC-Ref:** 6.3.1.2

---

**7.3.1.3 — Model set → Option upsert**

**Title:** Model-setting completion triggers option upsert
**Purpose:** Verify option upsert is invoked after model is set.
**Test Data:** Model set to `enum_single`, canonical values `["HR_MANAGER","POSITION"]`.
**Mocking:** Mock the internal “option upsert” boundary (if separate) to return success.
**Assertions:** Assert option upsert is invoked once immediately after model-setting completes, and not before.
**AC-Ref:** 6.3.1.3

---

**7.3.1.4 — Subsequent bind (existing model) → Consistency check**

**Title:** Subsequent bind completion triggers consistency verification
**Purpose:** Verify that, after binding when a model already exists, the consistency check runs next.
**Test Data:** Existing model `enum_single` with values `["HR_MANAGER","POSITION"]`; new bind uses same set.
**Mocking:** Mock `POST /api/v1/placeholders/bind` to succeed (no change to model).
**Assertions:** Assert consistency verification is invoked once immediately after bind completes, and not before.
**AC-Ref:** 6.3.1.4

---

**7.3.1.5 — Consistency ok → No model mutation**

**Title:** Consistency success prevents model mutation flow and proceeds to normal completion
**Purpose:** Verify that no model-mutation step is triggered when consistency passes; control proceeds to normal completion.
**Test Data:** Same as prior; no diffs.
**Mocking:** No additional mocks beyond stub “success” for verification.
**Assertions:** Assert model-mutation step is not invoked; assert normal completion step is invoked once after consistency check.
**AC-Ref:** 6.3.1.5

---

**7.3.1.6 — Child bind → Parent-link update**

**Title:** Binding a nested placeholder triggers parent option linkage update
**Purpose:** Verify that, after child bind, the parent option linkage update is invoked.
**Test Data:** Parent enum options: `["INTRANET","DETAILS"]` with `DETAILS` carrying `placeholder_key="DETAILS"`; child bind supplies `placeholder_id="ph-child-01"`.
**Mocking:** Mock bind success returning `placeholder_id`.
**Assertions:** Assert parent-link update is invoked once immediately after child bind completes, and not before.
**AC-Ref:** 6.3.1.6

---

**7.3.1.7 — Unbind (not last) → Complete without model clear**

**Title:** Unbinding a non-final placeholder triggers normal completion without model clear
**Purpose:** Verify that, after unbind where other bindings remain, flow proceeds to completion without model-clear.
**Test Data:** `placeholder_id="ph-keep-01"` unbound; at least one other placeholder still bound.
**Mocking:** Mock `POST /api/v1/placeholders/unbind` to succeed.
**Assertions:** Assert model-clear step is not invoked; assert normal completion is invoked once after unbind.
**AC-Ref:** 6.3.1.7

---

**7.3.1.8 — Unbind (last) → Model clear**

**Title:** Unbinding the final placeholder triggers model clear
**Purpose:** Verify that, when last binding is removed, the model-clear step is invoked next.
**Test Data:** `placeholder_id="ph-last-01"`; no other bindings remain.
**Mocking:** Mock unbind success response indicating “zero placeholders remain”.
**Assertions:** Assert model-clear is invoked once immediately after unbind completes, and not before.
**AC-Ref:** 6.3.1.8

---

**7.3.1.9 — Document delete → Purge bindings**

**Title:** Document deletion triggers bindings purge
**Purpose:** Verify that, after document delete, bindings purge is invoked.
**Test Data:** `document_id="doc-001"`.
**Mocking:** Mock `POST /api/v1/documents/{id}/bindings:purge` to succeed.
**Assertions:** Assert purge is invoked once immediately after document deletion event is processed, and not before.
**AC-Ref:** 6.3.1.9

---

**7.3.1.10 — Purge complete → Question tidy**

**Title:** Purge completion triggers question tidy-ups
**Purpose:** Verify that, after purge completes, the question tidy routine executes.
**Test Data:** Purge reports affected questions `[q-001,q-002]`.
**Mocking:** Mock tidy operation success.
**Assertions:** Assert tidy is invoked once immediately after purge completes, and not before.
**AC-Ref:** 6.3.1.10

---

**7.3.1.11 — Read/list → UI handoff**

**Title:** Listing placeholders triggers UI handoff step
**Purpose:** Verify that, after a successful list call, the UI handoff sequencing step runs.
**Test Data:** `GET /api/v1/questions/q-001/placeholders?document_id=doc-001`.
**Mocking:** Mock list to return `[ph-1, ph-2]`.
**Assertions:** Assert UI handoff step is invoked once immediately after list completes, and not before.
**AC-Ref:** 6.3.1.11

---

**7.3.1.12 — Preview → Return-to-editor sequencing**

**Title:** Transform preview completion triggers return-to-editor flow
**Purpose:** Verify preview success leads to the “return-to-editor” sequencing step.
**Test Data:** `POST /api/v1/transforms/preview { literals:["Yes","No"] }`.
**Mocking:** Mock preview to return `{ answer_kind:"enum_single", options:[...] }`.
**Assertions:** Assert return-to-editor step is invoked once immediately after preview completes, and not before.
**AC-Ref:** 6.3.1.12

---

**7.3.1.13 — Catalog → Tooling refresh**

**Title:** Transforms catalog retrieval triggers tooling refresh step
**Purpose:** Verify successful catalog fetch starts downstream tooling refresh.
**Test Data:** `GET /api/v1/transforms/catalog`.
**Mocking:** Mock catalog to return `[ {transform_id:"enum_single", ...} ]`.
**Assertions:** Assert tooling refresh is invoked once immediately after catalog retrieval completes, and not before.
**AC-Ref:** 6.3.1.13

---

**7.3.1.14 — Verify mode → Apply mode allowed**

**Title:** Successful verify-mode bind permits transition to apply mode
**Purpose:** Verify that completion of `apply_mode="verify"` triggers the “allow apply” step.
**Test Data:** `apply_mode:"verify"` with no conflicts.
**Mocking:** Mock bind (verify) to return success with no writes.
**Assertions:** Assert “allow-apply” step is invoked once immediately after verify completes, and not before.
**AC-Ref:** 6.3.1.14

---

**7.3.1.15 — Boolean transform → Clause-visibility routing**

**Title:** Boolean inclusion transform triggers clause-visibility routing
**Purpose:** Verify that, after boolean suggestion/bind success, the clause-visibility routing step is invoked.
**Test Data:** Placeholder `[GENERAL DETAILS …]` recognised as `boolean` inclusion toggle per deterministic rules.
**Mocking:** Suggest → `boolean`; bind → success.
**Assertions:** Assert clause-visibility routing is invoked once immediately after boolean flow completes, and not before.
**AC-Ref:** 6.3.1.15

---

**7.3.1.16 — Number transform → Validation pass → Next step**

**Title:** Number transform with valid value triggers next sequencing step
**Purpose:** Verify success of numeric path triggers the downstream “ready” step.
**Test Data:** Placeholder `[30 DAYS]` recognised as `number`.
**Mocking:** Suggest/preview return `number`; bind verify succeeds.
**Assertions:** Assert downstream “ready” step is invoked once immediately after number-path completes, and not before.
**AC-Ref:** 6.3.1.16

---

**7.3.1.17 — Enum (literal + nested) → Companion short_string reveal step**

**Title:** Mixed enum suggestion triggers companion-field reveal sequencing
**Purpose:** Verify that, after enum with nested placeholder is confirmed, the UI-reveal sequencing is invoked.
**Test Data:** `"On the intranet OR [DETAILS]"` → enum options `["INTRANET","DETAILS"]`.
**Mocking:** Suggest returns enum; bind succeeds; no parent conflict.
**Assertions:** Assert companion-field reveal step is invoked once immediately after confirm/bind completes, and not before.
**AC-Ref:** 6.3.1.17

---

**7.3.1.18 — Long text recognition → Editor handoff**

**Title:** Long text transform completion triggers editor handoff
**Purpose:** Verify long-text path leads to the “editor handoff” sequencing step.
**Test Data:** Placeholder `[GENERAL DETAILS ABOUT THE EMPLOYER AND ITS BUSINESS.]`.
**Mocking:** Suggest returns `long_text`; bind verify succeeds.
**Assertions:** Assert editor handoff is invoked once immediately after long-text path completes, and not before.
**AC-Ref:** 6.3.1.18

---

**7.3.1.19 — Read-only inspection → No-op transition**

**Title:** Inspection step completion proceeds to no-op transition
**Purpose:** Verify read/list inspection completes and transitions to the defined no-op terminator step.
**Test Data:** Same as listing case; no mutations.
**Mocking:** List succeeds.
**Assertions:** Assert no-op transition is invoked once immediately after inspection completes, and not before.
**AC-Ref:** 6.3.1.19

---

**7.3.1.20 — Idempotent rebind → Single-completion transition**

**Title:** Idempotent repeat bind triggers single-completion transition without duplicates
**Purpose:** Verify that an idempotent rebind flows to a single completion transition.
**Test Data:** Same payload + same Idempotency-Key as a prior successful bind.
**Mocking:** Mock bind to return same success result as original.
**Assertions:** Assert single-completion transition is invoked exactly once after rebind completes, and not before.
**AC-Ref:** 6.3.1.20

---

**7.3.1.21 — Option upsert → Question ETag refresh**

**Title:** Completion of option upsert triggers question ETag refresh
**Purpose:** Verify that, after successful option upsert, the ETag refresh step runs.
**Test Data:** Question `q-001`, options `["INTRANET","DETAILS"]`.
**Mocking:** ETag service returns a dummy strong ETag.
**Assertions:** Assert ETag refresh is invoked once immediately after option upsert completes, and not before.
**AC-Ref:** 6.3.1.21

---

**7.3.1.22 — Question ETag refresh → Response dispatch**

**Title:** ETag refresh completion triggers response dispatch to client
**Purpose:** Verify that response dispatch runs right after ETag refresh.
**Test Data:** Updated ETag `WONTUSE/12345` (example strong tag).
**Mocking:** HTTP responder stub returns a dummy success envelope.
**Assertions:** Assert response dispatch is invoked once immediately after ETag refresh completes, and not before.
**AC-Ref:** 6.3.1.22

---

**7.3.1.23 — Parent-link update → Consistency verification**

**Title:** Parent option linkage update triggers a consistency verification pass
**Purpose:** Verify that, after updating parent linkage, a targeted consistency check runs next.
**Test Data:** Parent option `DETAILS` now points to `placeholder_id="ph-child-01"`.
**Mocking:** Consistency checker returns “consistent”.
**Assertions:** Assert consistency verification is invoked once immediately after parent-link update completes, and not before.
**AC-Ref:** 6.3.1.23

---

**7.3.1.24 — Model clear → Option set removal**

**Title:** Clearing question model triggers canonical option set removal
**Purpose:** Verify that, after model clear, the option-removal step is invoked.
**Test Data:** Question `q-002` has options; last placeholder just unbound.
**Mocking:** Option removal stub returns success.
**Assertions:** Assert option set removal is invoked once immediately after model clear completes, and not before.
**AC-Ref:** 6.3.1.24

---

**7.3.1.25 — Purge bindings → Affected questions sweep**

**Title:** Bindings purge completion triggers affected-questions sweep
**Purpose:** Verify that, after purge, the system sweeps impacted questions for tidy up.
**Test Data:** Purge result reports `deleted_placeholders=7`.
**Mocking:** Sweep job returns a list of question IDs processed.
**Assertions:** Assert affected-questions sweep is invoked once immediately after purge completes, and not before.
**AC-Ref:** 6.3.1.25

---

**7.3.1.26 — Verify apply_mode → UI affordance to proceed**

**Title:** Successful verify-only bind triggers UI affordance to proceed to apply
**Purpose:** Verify that, after verify success, the UI “Proceed to Apply” sequencing fires.
**Test Data:** Bind request with `apply_mode="verify"`.
**Mocking:** Verify path returns “no writes performed”.
**Assertions:** Assert UI affordance step is invoked once immediately after verify completes, and not before.
**AC-Ref:** 6.3.1.26

---

**7.3.1.27 — Boolean inclusion set → Visibility engine notification**

**Title:** Boolean clause decision triggers visibility engine notification
**Purpose:** Verify that, after boolean path success, visibility engine notify runs.
**Test Data:** Boolean toggled `true` for a clause block.
**Mocking:** Visibility notifier returns success.
**Assertions:** Assert visibility engine notification is invoked once immediately after boolean decision completes, and not before.
**AC-Ref:** 6.3.1.27

---

**7.3.1.28 — Number validation pass → Downstream rules evaluation**

**Title:** Number validation success triggers downstream rules evaluation step
**Purpose:** Verify that, after numeric validation, rules evaluation is invoked.
**Test Data:** `[30 DAYS]` recognised and validated.
**Mocking:** Rules evaluator returns “no changes required”.
**Assertions:** Assert rules evaluation is invoked once immediately after number validation completes, and not before.
**AC-Ref:** 6.3.1.28

---

**7.3.1.29 — Mixed enum confirmation → Companion-field reveal signal**

**Title:** Mixed enum confirmation triggers a companion-field reveal signal to UI
**Purpose:** Verify reveal signal fires right after confirmation.
**Test Data:** Options `INTRANET` and `DETAILS` (nested).
**Mocking:** UI bus mock acknowledges signal receipt.
**Assertions:** Assert companion-field reveal signal is invoked once immediately after confirmation completes, and not before.
**AC-Ref:** 6.3.1.29

---

**7.3.1.30 — Long-text confirmation → Editor focus step**

**Title:** Long-text confirmation triggers editor focus to the bound span
**Purpose:** Verify that the editor focus step is invoked post-confirmation.
**Test Data:** Long-text placeholder span `{start: 500, end: 760}`.
**Mocking:** Editor controller stub accepts a focus request.
**Assertions:** Assert editor focus is invoked once immediately after long-text confirmation completes, and not before.
**AC-Ref:** 6.3.1.30

---

**7.3.1.31 — Read/list success → ETag propagation to client**

**Title:** Successful listing triggers propagation of the question ETag
**Purpose:** Verify ETag propagation occurs immediately after list returns.
**Test Data:** List returns `items=[…]` and server-side ETag.
**Mocking:** Response builder returns `ETag: "abc123"` header.
**Assertions:** Assert ETag propagation is invoked once immediately after list completes, and not before.
**AC-Ref:** 6.3.1.31

---

**7.3.1.32 — Catalog load → Tooling cache refresh**

**Title:** Transform catalog retrieval triggers local tooling cache refresh
**Purpose:** Verify cache refresh runs after catalog load.
**Test Data:** Catalog includes `enum_single`, `short_string`, `boolean`, `number`, `long_text`.
**Mocking:** Cache layer mock records a refresh call.
**Assertions:** Assert cache refresh is invoked once immediately after catalog retrieval completes, and not before.
**AC-Ref:** 6.3.1.32

---

**7.3.1.33 — Preview success → Return to selection UI**

**Title:** Preview success triggers return to transform selection UI state
**Purpose:** Verify UI state transition occurs after preview.
**Test Data:** Preview returns `answer_kind="enum_single"` with two options.
**Mocking:** UI state machine accepts a `return_to_selection` event.
**Assertions:** Assert UI transition is invoked once immediately after preview completes, and not before.
**AC-Ref:** 6.3.1.33

---

**7.3.1.34 — Child linkage established → Parent summary refresh**

**Title:** Establishing child linkage triggers a parent placeholder summary refresh
**Purpose:** Verify the summary refresh invokes right after linkage.
**Test Data:** Parent shows `DETAILS → ph-child-01`.
**Mocking:** Summary refresher acknowledges refresh.
**Assertions:** Assert parent summary refresh is invoked once immediately after linkage completes, and not before.
**AC-Ref:** 6.3.1.34

---

**7.3.1.35 — Idempotent rebind (same key) → Single completion path**

**Title:** Rebinding with same Idempotency-Key triggers a single completion path
**Purpose:** Verify no duplicate flow is triggered on idempotent replay.
**Test Data:** Same bind payload and `Idempotency-Key: "key-123"`.
**Mocking:** Idempotency store returns prior completion token.
**Assertions:** Assert only one completion transition is invoked after the replay completes, and not before.
**AC-Ref:** 6.3.1.35

---

**7.3.1.36 — Document purge completion → UI doc list refresh**

**Title:** Completing purge triggers a UI document list refresh
**Purpose:** Verify UI refresh runs post-purge.
**Test Data:** Purge on `document_id="doc-001"` reports deletions.
**Mocking:** UI bus mock records a `refresh_documents` event.
**Assertions:** Assert UI document list refresh is invoked once immediately after purge completes, and not before.
**AC-Ref:** 6.3.1.36

---

**7.3.1.37 — Unbind last placeholder → Clear-answer-model broadcast**

**Title:** Clearing the last binding triggers an answer-model cleared broadcast
**Purpose:** Verify a broadcast step runs right after last unbind.
**Test Data:** Question `q-003` becomes unbound.
**Mocking:** Event bus mock records `answer_model_cleared` event.
**Assertions:** Assert broadcast is invoked once immediately after final unbind completes, and not before.
**AC-Ref:** 6.3.1.37

---

**7.3.1.38 — Successful bind apply → Read-after-write fetch**

**Title:** Successful apply-mode bind triggers a read-after-write fetch
**Purpose:** Verify the immediate R-A-W fetch occurs post-apply.
**Test Data:** Bind apply for `q-004` returns `placeholder_id="ph-999"`.
**Mocking:** Read endpoint mocked to return the newly bound placeholder list.
**Assertions:** Assert read-after-write fetch is invoked once immediately after bind apply completes, and not before.
**AC-Ref:** 6.3.1.38

---

**7.3.1.39 — Read-after-write fetch → UI reconciliation**

**Title:** Completion of read-after-write fetch triggers UI reconciliation
**Purpose:** Verify reconciliation runs after the R-A-W fetch.
**Test Data:** Returned list contains `ph-999` with correct linkage.
**Mocking:** UI reconciliation handler stub accepts the delta.
**Assertions:** Assert UI reconciliation is invoked once immediately after read-after-write fetch completes, and not before.
**AC-Ref:** 6.3.1.39

**7.3.2.1**

**Title:** Bind write failure halts STEP-2 and stops STEP-3
**Purpose:** Verify that a DB write failure during bind halts STEP-2 Bind and prevents STEP-3 Inspect.
**Test Data:** `POST /api/v1/placeholders/bind` with `question_id="q-001"`, valid `PlaceholderProbe`, `apply_mode="apply"`, `Idempotency-Key:"k-1"`.
**Mocking:** DB gateway mock for “create placeholder” raises write error once; idempotency store returns “not seen”. Assert DB mock called with `(document_id, question_id, clause_path, span)`.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** raises, and not before. Assert **STEP-3 Inspect** is not invoked following the failure. Assert that error mode **RUN_CREATE_ENTITY_DB_WRITE_FAILED** is observed.
**AC-Ref:** 6.3.2.1
**Error Mode:** RUN_CREATE_ENTITY_DB_WRITE_FAILED

---

**7.3.2.2**

**Title:** First-bind model update failure halts STEP-2 and stops STEP-3
**Purpose:** Verify that failing to update `answer_kind` and options on first bind halts STEP-2 and prevents STEP-3.
**Test Data:** Same bind as 7.3.2.1, but “first bind” path (no existing model).
**Mocking:** DB gateway mock for “update question model” raises write error once; placeholder create succeeds.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** raises, and not before. Assert **STEP-3 Inspect** is not invoked. Assert **RUN_UPDATE_ENTITY_DB_WRITE_FAILED** observed.
**AC-Ref:** 6.3.2.2
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED

---

**7.3.2.3**

**Title:** Unbind delete failure halts STEP-3 and stops STEP-4
**Purpose:** Verify that placeholder delete failure during unbind halts STEP-3 Inspect and prevents STEP-4 Cleanup.
**Test Data:** `POST /api/v1/placeholders/unbind` with `placeholder_id="ph-123"`, `If-Match:"etag-1"`.
**Mocking:** DB gateway mock for “delete placeholder” raises write error once.
**Assertions:** Assert error handler is invoked once immediately when **STEP-3 Inspect** raises, and not before. Assert **STEP-4 Cleanup on document deletion** is not invoked. Assert **RUN_DELETE_ENTITY_DB_WRITE_FAILED** observed.
**AC-Ref:** 6.3.2.3
**Error Mode:** RUN_DELETE_ENTITY_DB_WRITE_FAILED

---

**7.3.2.4**

**Title:** Listing read failure halts STEP-3 and stops STEP-4
**Purpose:** Verify that read failure when listing placeholders halts STEP-3 and prevents STEP-4.
**Test Data:** `GET /api/v1/questions/q-001/placeholders?document_id=doc-001`.
**Mocking:** DB gateway mock for “list placeholders by question/document” raises read error once.
**Assertions:** Assert error handler is invoked once immediately when **STEP-3 Inspect** raises, and not before. Assert **STEP-4 Cleanup on document deletion** is not invoked. Assert **RUN_RETRIEVE_ENTITY_DB_READ_FAILED** observed.
**AC-Ref:** 6.3.2.4
**Error Mode:** RUN_RETRIEVE_ENTITY_DB_READ_FAILED

---

**7.3.2.5**

**Title:** Idempotency backend unavailable halts STEP-2 and stops STEP-3
**Purpose:** Verify that idempotency-store outage halts bind and prevents inspect.
**Test Data:** Same bind as 7.3.2.1.
**Mocking:** Idempotency store mock raises “service unavailable” before write begins; DB gateway untouched. Assert idempotency checked with the request hash and key.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** raises, and not before. Assert **STEP-3 Inspect** is not invoked. Assert **RUN_IDEMPOTENCY_STORE_UNAVAILABLE** observed.
**AC-Ref:** 6.3.2.5
**Error Mode:** RUN_IDEMPOTENCY_STORE_UNAVAILABLE

---

**7.3.2.6**

**Title:** ETag computation failure blocks finalisation of STEP-2 and stops STEP-3
**Purpose:** Verify that ETag compute failure blocks finalisation of the current write step and prevents inspect.
**Test Data:** Bind succeeds up to just before response; ETag required.
**Mocking:** ETag calculator mock raises compute error once after successful DB changes.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** finalisation raises, and not before. Assert **STEP-3 Inspect** is not invoked. Assert **RUN_ETAG_COMPUTE_FAILED** observed.
**AC-Ref:** 6.3.2.6
**Error Mode:** RUN_ETAG_COMPUTE_FAILED

---

**7.3.2.7**

**Title:** Concurrency token generation failure blocks finalisation of STEP-2 and stops STEP-3
**Purpose:** Verify that generating a new concurrency token fails and blocks completion of the write step.
**Test Data:** Bind with `If-Match` workflow requiring a new token.
**Mocking:** Concurrency token service mock raises generation error once after DB write succeeds.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** finalisation raises, and not before. Assert **STEP-3 Inspect** is not invoked. Assert **RUN_CONCURRENCY_TOKEN_GENERATION_FAILED** observed.
**AC-Ref:** 6.3.2.7
**Error Mode:** RUN_CONCURRENCY_TOKEN_GENERATION_FAILED

---

**7.3.2.8**

**Title:** Problem+JSON encoding failure blocks response at STEP-1 and stops STEP-2
**Purpose:** Verify that failure to encode problem+json blocks finalisation of the current step and prevents the next.
**Test Data:** Error response path in `POST /api/v1/transforms/suggest`.
**Mocking:** Problem+JSON encoder mock raises serialisation error once; suggestion failure already present.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** finalisation raises, and not before. Assert **STEP-2 Bind** is not invoked. Assert **RUN_PROBLEM_JSON_ENCODING_FAILED** observed.
**AC-Ref:** 6.3.2.8
**Error Mode:** RUN_PROBLEM_JSON_ENCODING_FAILED

---

**7.3.2.9**

**Title:** Parent–child linkage enforcement failure halts STEP-2 and stops STEP-3
**Purpose:** Verify that enforcing parent option’s `placeholder_id` linkage failure halts bind and prevents inspect.
**Test Data:** Bind where child is nested within a parent option requiring linkage.
**Mocking:** Relation-enforcement gateway mock raises linkage error upon setting `placeholder_id`.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** raises, and not before. Assert **STEP-3 Inspect** is not invoked. Assert **RUN_LINKAGE_RELATION_ENFORCEMENT_FAILED** observed.
**AC-Ref:** 6.3.2.9
**Error Mode:** RUN_LINKAGE_RELATION_ENFORCEMENT_FAILED

---

**7.3.2.10**

**Title:** Purge delete failure halts STEP-4 and stops pipeline completion
**Purpose:** Verify that placeholder purge delete failure halts cleanup and prevents pipeline completion.
**Test Data:** `POST /api/v1/documents/doc-001/bindings:purge`.
**Mocking:** DB gateway mock for “batch delete by document” raises write error once.
**Assertions:** Assert error handler is invoked once immediately when **STEP-4 Cleanup on document deletion** raises, and not before. Assert pipeline completion is not invoked. Assert **RUN_DELETE_ENTITY_DB_WRITE_FAILED** observed.
**AC-Ref:** 6.3.2.10
**Error Mode:** RUN_DELETE_ENTITY_DB_WRITE_FAILED

---

**7.3.2.11**

**Title:** Unidentified runtime error halts current step and stops next step
**Purpose:** Verify that an unhandled runtime error halts the active step and prevents its downstream step.
**Test Data:** Trigger generic exception in the active controller (choose STEP-2 bind controller).
**Mocking:** Controller mock throws an unclassified exception once during main operation.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** raises, and not before. Assert **STEP-3 Inspect** is not invoked. Assert **RUN_UNIDENTIFIED_ERROR** observed.
**AC-Ref:** 6.3.2.11
**Error Mode:** RUN_UNIDENTIFIED_ERROR

---

**7.3.2.12**

**Title:** Suggestion problem+json encode failure blocks STEP-1 finalisation and stops STEP-2
**Purpose:** Verify that suggestion error response encoding failure blocks STEP-1 and prevents STEP-2.
**Test Data:** `POST /api/v1/transforms/suggest` error path.
**Mocking:** Problem+JSON encoder mock raises serialisation error once on the error response.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** finalisation raises, and not before. Assert **STEP-2 Bind** is not invoked. Assert **RUN_PROBLEM_JSON_ENCODING_FAILED** observed.
**AC-Ref:** 6.3.2.12
**Error Mode:** RUN_PROBLEM_JSON_ENCODING_FAILED

---

**7.3.2.13**

**Title:** Option linkage set-up failure halts transform-backed bind and stops STEP-3
**Purpose:** Verify that failure establishing option→child linkage halts bind and prevents inspect.
**Test Data:** Bind with enum option carrying `placeholder_key` that must be linked to new child `placeholder_id`.
**Mocking:** Relation-enforcement mock raises on setting `placeholder_id`.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** raises, and not before. Assert **STEP-3 Inspect** is not invoked. Assert **RUN_LINKAGE_RELATION_ENFORCEMENT_FAILED** observed.
**AC-Ref:** 6.3.2.13
**Error Mode:** RUN_LINKAGE_RELATION_ENFORCEMENT_FAILED

---

**7.3.2.14**

**Title:** Deterministic model update write failure halts STEP-2 and stops STEP-3
**Purpose:** Verify write failure during deterministic model set (first bind) halts bind and prevents inspect.
**Test Data:** First-bind with `answer_kind="enum_single"`, literals→canonical options.
**Mocking:** DB gateway “update question model” raises write error once; earlier operations succeed.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** raises, and not before. Assert **STEP-3 Inspect** is not invoked. Assert **RUN_UPDATE_ENTITY_DB_WRITE_FAILED** observed.
**AC-Ref:** 6.3.2.14
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED

---

**7.3.2.15**

**Title:** Idempotency verification unavailable halts STEP-2 and stops STEP-3
**Purpose:** Verify idempotency key verification outage halts bind and prevents inspect.
**Test Data:** Bind with `Idempotency-Key:"k-77"`.
**Mocking:** Idempotency store mock raises “unavailable” before any DB writes.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** raises, and not before. Assert **STEP-3 Inspect** is not invoked. Assert **RUN_IDEMPOTENCY_STORE_UNAVAILABLE** observed.
**AC-Ref:** 6.3.2.15
**Error Mode:** RUN_IDEMPOTENCY_STORE_UNAVAILABLE

---

**7.3.2.16**

**Title:** Suggestion engine runtime failure halts STEP-1 and stops STEP-2
**Purpose:** Verify that an internal suggestion engine exception halts STEP-1 and prevents STEP-2.
**Test Data:** `POST /api/v1/transforms/suggest` with valid probe.
**Mocking:** Suggestion engine mock throws a runtime exception before generating a response.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** raises, and not before. Assert **STEP-2 Bind** is not invoked. Assert **RUN_UNIDENTIFIED_ERROR** observed.
**AC-Ref:** 6.3.2.16
**Error Mode:** RUN_UNIDENTIFIED_ERROR

---

**7.3.2.17**

**Title:** Preview engine runtime failure halts STEP-1 and stops STEP-2
**Purpose:** Verify that a preview-path runtime failure halts suggestion/preview flow and prevents bind.
**Test Data:** `POST /api/v1/transforms/preview` with literals list.
**Mocking:** Preview engine mock throws a runtime exception before producing preview.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** raises, and not before. Assert **STEP-2 Bind** is not invoked. Assert **RUN_UNIDENTIFIED_ERROR** observed.
**AC-Ref:** 6.3.2.17
**Error Mode:** RUN_UNIDENTIFIED_ERROR

**7.3.2.22**
**Title:** Database unavailable halts binding and prevents inspection
**Purpose:** Verify that binding halts and inspection is not invoked when the database is unavailable.
**Test Data:** Minimal bind request `{ question_id:"7e1…", transform_id:"enum_single", probe:{document_id:"d1…", clause_path:"1.2", span:{start:10,end:22}} }`.
**Mocking:** DB client mock throws “connection refused” on first write; no other dependencies mocked. Assert DB client called once with `insertPlaceholder(...)`.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** raises due to database unavailability, and not before. Assert **STEP-3 Inspect** is not invoked. Assert error mode **ENV_DATABASE_UNAVAILABLE** is observed. Assert no retries and no partial state. Assert one error telemetry event is emitted.
**AC-Ref:** 6.3.2.18
**Error Mode:** ENV_DATABASE_UNAVAILABLE

---

**7.3.2.23**
**Title:** Database permission denied halts mutation and prevents inspection
**Purpose:** Verify that binding stops when DB denies write permissions.
**Test Data:** Same bind request as 7.3.2.22.
**Mocking:** DB client mock raises “permission denied” on write.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** raises due to permission denial. Assert **STEP-3 Inspect** is not invoked. Assert **ENV_DATABASE_PERMISSION_DENIED** is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.19
**Error Mode:** ENV_DATABASE_PERMISSION_DENIED

---

**7.3.2.24**
**Title:** Cache backend unavailable bypasses cache and continues to bind
**Purpose:** Verify degraded continuation when cache is unavailable during suggestion/listing.
**Test Data:** Suggest call with `PlaceholderProbe` and then bind.
**Mocking:** Cache client mock raises “service unavailable” for `get/set`; suggestion engine returns successfully without cache.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** cache access raises, and not before. Assert system **continues to STEP-2 Bind** (no cache attempts thereafter). Assert **ENV_CACHE_UNAVAILABLE** is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.20
**Error Mode:** ENV_CACHE_UNAVAILABLE

---

**7.3.2.25**
**Title:** Message broker unavailable halts cleanup eventing
**Purpose:** Verify cleanup halts when broker is unavailable.
**Test Data:** Purge call for `document_id:"d1…"`.
**Mocking:** Event bus publish mock throws “broker unavailable”; DB delete is not executed after the failure.
**Assertions:** Assert error handler is invoked once immediately when **STEP-4 Cleanup on document deletion** attempts publish and raises. Assert downstream pipeline completion is not reached. Assert **ENV_EVENT_BUS_UNAVAILABLE** is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.21
**Error Mode:** ENV_EVENT_BUS_UNAVAILABLE

---

**7.3.2.26**
**Title:** Object storage unavailable halts purge
**Purpose:** Verify purge stops when object storage cannot be reached.
**Test Data:** Purge call for `document_id:"d2…"`.
**Mocking:** Object storage client `deleteObjects` throws “endpoint unreachable”.
**Assertions:** Assert error handler is invoked once immediately when **STEP-4 Cleanup on document deletion** raises, and not before. Assert pipeline completion is not reached. Assert **ENV_OBJECT_STORAGE_UNAVAILABLE** is observed. Assert one telemetry event.
**AC-Ref:** 6.3.2.22
**Error Mode:** ENV_OBJECT_STORAGE_UNAVAILABLE

---

**7.3.2.27**
**Title:** Object storage permission denied prevents purge
**Purpose:** Verify purge halts when deletion is forbidden.
**Test Data:** Purge call for `document_id:"d3…"`.
**Mocking:** Object storage client throws “access denied” on delete.
**Assertions:** Assert error handler is invoked once immediately when **STEP-4 Cleanup on document deletion** raises. Assert pipeline completion not reached. Assert **ENV_OBJECT_STORAGE_PERMISSION_DENIED**. Assert one telemetry event.
**AC-Ref:** 6.3.2.23
**Error Mode:** ENV_OBJECT_STORAGE_PERMISSION_DENIED

---

**7.3.2.28**
**Title:** Network unreachable halts suggestion and prevents bind
**Purpose:** Verify that suggestion stops and bind is not invoked when network is down.
**Test Data:** Suggest call with valid `PlaceholderProbe`.
**Mocking:** HTTP client used by suggestion path throws “network unreachable”.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** raises; Assert **STEP-2 Bind** is not invoked. Assert **ENV_NETWORK_UNREACHABLE**. Assert one telemetry event.
**AC-Ref:** 6.3.2.24
**Error Mode:** ENV_NETWORK_UNREACHABLE

---

**7.3.2.29**
**Title:** DNS resolution failure halts suggestion and prevents bind
**Purpose:** Verify that suggestion stops when DNS fails.
**Test Data:** Suggest call with valid `PlaceholderProbe`.
**Mocking:** DNS resolution mock returns “NXDOMAIN” for endpoint host.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** raises; Assert **STEP-2 Bind** is not invoked. Assert **ENV_DNS_RESOLUTION_FAILED**. Assert one telemetry event.
**AC-Ref:** 6.3.2.25
**Error Mode:** ENV_DNS_RESOLUTION_FAILED

---

**7.3.2.30**
**Title:** TLS handshake failure halts API calls during suggestion
**Purpose:** Verify TLS failures halt suggestion.
**Test Data:** Suggest call with valid `PlaceholderProbe`.
**Mocking:** HTTP client TLS handshake mock raises “handshake failure”.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** raises; Assert **STEP-2 Bind** is not invoked. Assert **ENV_TLS_HANDSHAKE_FAILED**. Assert one telemetry event.
**AC-Ref:** 6.3.2.26
**Error Mode:** ENV_TLS_HANDSHAKE_FAILED

---

**7.3.2.31**
**Title:** Disk space exhausted blocks finalisation of bind/cleanup
**Purpose:** Verify bind/cleanup cannot finalise when disk is full.
**Test Data:** Bind call, and separately purge call.
**Mocking:** Filesystem write for temp/ETag snapshot throws “no space left on device”.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** or **STEP-4 Cleanup on document deletion** attempts final write; Assert downstream steps are **blocked**. Assert **ENV_DISK_SPACE_EXHAUSTED**. Assert one telemetry event.
**AC-Ref:** 6.3.2.27
**Error Mode:** ENV_DISK_SPACE_EXHAUSTED

---

**7.3.2.32**
**Title:** Temp directory unavailable halts suggestion preprocessing
**Purpose:** Verify suggestion halts when temp workspace is missing.
**Test Data:** Suggest call.
**Mocking:** `mkdtemp`/tmp allocator throws “ENOENT”.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** raises; Assert **STEP-2 Bind** is not invoked. Assert **ENV_TEMP_DIR_UNAVAILABLE**. Assert one telemetry event.
**AC-Ref:** 6.3.2.28
**Error Mode:** ENV_TEMP_DIR_UNAVAILABLE

---

**7.3.2.33**
**Title:** AI endpoint unavailable halts suggestion and prevents bind
**Purpose:** Verify AI dependency outage halts suggestion.
**Test Data:** Suggest call.
**Mocking:** AI client `suggestTransform` throws “service unavailable”.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** raises; Assert **STEP-2 Bind** is not invoked. Assert **ENV_AI_ENDPOINT_UNAVAILABLE**. Assert one telemetry event.
**AC-Ref:** 6.3.2.29
**Error Mode:** ENV_AI_ENDPOINT_UNAVAILABLE

---

**7.3.2.34**
**Title:** GPU resources unavailable halts suggestion compute
**Purpose:** Verify GPU shortage halts suggestion path.
**Test Data:** Suggest call that selects GPU path.
**Mocking:** GPU allocator mock returns “no GPU available”.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** raises; Assert **STEP-2 Bind** is not invoked. Assert **ENV_GPU_RESOURCES_UNAVAILABLE**. Assert one telemetry event.
**AC-Ref:** 6.3.2.30
**Error Mode:** ENV_GPU_RESOURCES_UNAVAILABLE

---

**7.3.2.35**
**Title:** API rate limit exceeded skips non-critical cache refresh and continues
**Purpose:** Verify degraded continuation when upstream rate limit blocks cache priming.
**Test Data:** Listing with optional cache-prime flag enabled.
**Mocking:** Upstream API mock returns HTTP 429 for cache priming call only; listing core path returns success.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** cache-prime raises; Assert system **continues to STEP-2 Bind**; Assert no additional cache calls are made. Assert **ENV_API_RATE_LIMIT_EXCEEDED**. Assert one telemetry event.
**AC-Ref:** 6.3.2.31
**Error Mode:** ENV_API_RATE_LIMIT_EXCEEDED

---

**7.3.2.36**
**Title:** API quota exceeded halts suggestion and prevents bind
**Purpose:** Verify quota exhaustion halts suggestion.
**Test Data:** Suggest call.
**Mocking:** Upstream API mock returns HTTP 403/“quota exceeded”.
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Explore and decide** raises; Assert **STEP-2 Bind** is not invoked. Assert **ENV_API_QUOTA_EXCEEDED**. Assert one telemetry event.
**AC-Ref:** 6.3.2.32
**Error Mode:** ENV_API_QUOTA_EXCEEDED

---

**7.3.2.37**
**Title:** Time synchronisation failure blocks idempotency finalisation
**Purpose:** Verify unsynchronised clock blocks bind finalisation when time-ordered tokens are required.
**Test Data:** Bind call with Idempotency-Key semantics enabled.
**Mocking:** Time source mock returns skewed time; token validator raises “clock out of sync”.
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Bind** finalisation checks time; Assert **STEP-3 Inspect** is not invoked. Assert **ENV_TIME_SYNCHRONISATION_FAILED**. Assert one telemetry event.
**AC-Ref:** 6.3.2.33
**Error Mode:** ENV_TIME_SYNCHRONISATION_FAILED