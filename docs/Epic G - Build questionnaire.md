# epic g - build questionnaire

purpose
Enable fine-grained authoring of a questionnaire without relying on bulk CSV import. Authors can add screens, add questions to a screen, update question text, change order, set or clear a conditional parent, and move a question between screens. Changes are safe, versioned, and reflected deterministically when screens are read.

scope

* Create, rename and order screens within a questionnaire
* Create a question on a specific screen
* Update question text
* Reorder questions within a screen
* Reorder screens within a questionnaire
* Move a question from one screen to another
* Set or clear a conditional parent for a question (including condition rule)
* Concurrency guarded with ETags and idempotency on creates

out of scope

* End user response capture
* Visibility evaluation at runtime beyond updating the authoring model
* Bulk CSV import or export flows
* Rich question types beyond those already defined
* Any access or role management

resources and identifiers

* questionnaire_id: stable identifier for a questionnaire under authoring
* screen_id: stable identifier for a screen within a questionnaire
* question_id: stable identifier for a question
* screen_order: 1-based integer defining order of screens within a questionnaire
* question_order: 1-based integer defining order of questions within a screen
* conditional_parent: a reference to another question on any screen plus a rule describing when this question is visible

headers

* If-Match: required on PATCH to prevent lost updates
* Idempotency-Key: required on POST to safely retry create operations
* Question-ETag, Screen-ETag, Questionnaire-ETag: returned on write operations to support optimistic concurrency at multiple levels

high level rules

* Screen ordering is authoritative in the backend and stored as a unique, contiguous sequence of screen_order values starting at 1 with no gaps.
* Within a screen, questions are ordered by a unique, contiguous sequence of question_order values starting at 1 with no gaps.
* After any operation that might affect ordering (create, delete, move, reorder), the backend recalculates and persists contiguous sequences for the affected collection(s) and returns updated order values and ETags.
* Clients may propose a target position, but the backend is always authoritative for the final order.
* A question may have zero or one conditional parent; clearing the parent removes any associated rule.
* Moving a question between screens preserves its identity and audit trail. The backend assigns a new question_order in the target screen and reindexes the source screen to maintain contiguity.

## endpoint summary

* POST `/api/v1/authoring/questionnaires/{questionnaire_id}/screens`
  Create a screen with a title. Optionally propose a position; the backend assigns the final screen_order.

* PATCH `/api/v1/authoring/questionnaires/{questionnaire_id}/screens/{screen_id}`
  Rename a screen and optionally propose a new position. The backend recalculates a contiguous screen_order sequence.

* POST `/api/v1/authoring/questionnaires/{questionnaire_id}/questions`
  Create a question on a given screen with initial text and answer kind. Optionally propose question_order; the backend assigns the final value and reindexes as needed.

* PATCH `/api/v1/authoring/questions/{question_id}`
  Update question_text. Optional fields in the same call: mandatory flag and helper text.

* PATCH `/api/v1/authoring/questions/{question_id}/position`
  Reorder a question within its screen by proposing a new question_order, or move it to another screen by providing a target screen_id and an optional proposed question_order. The backend recalculates contiguous sequences for both the source and target screens.

* PATCH `/api/v1/authoring/questions/{question_id}/visibility`
  Set or clear the conditional parent. Supply parent_question_id and a simple rule. Clearing removes both.

## request and response outlines

create screen

* Request body: title, optional proposed_position
* Success: 201 with screen { screen_id, title, screen_order } and Screen-ETag, Questionnaire-ETag

update screen

* Request body: title? proposed_position?
* Success: 200 with updated screen { screen_id, title, screen_order } and Screen-ETag, Questionnaire-ETag
* Notes: changing position triggers backend reindex to a contiguous 1..N sequence across all screens

create question

* Request body: screen_id, question_text, answer_kind, optional proposed_question_order, optional mandatory, optional helper_text
* Success: 201 with question { question_id, screen_id, question_text, answer_kind, mandatory, helper_text, question_order } and Question-ETag, Screen-ETag, Questionnaire-ETag

update question text

* Request body: question_text, optional mandatory, optional helper_text
* Success: 200 with updated question and Question-ETag, Screen-ETag, Questionnaire-ETag

reorder or move question

* Request body: one of

  * { proposed_question_order } to reorder within the same screen
  * { screen_id, proposed_question_order? } to move to another screen
* Success: 200 with updated question and ETags. Backend assigns final contiguous orders, reindexing both source and target screens as needed.

set or clear conditional parent

* Request body to set: { parent_question_id, rule } where rule is compatible with the parent’s answer_kind
* Request body to clear: { parent_question_id: null, rule: null }
* Success: 200 with updated question visibility metadata and Question-ETag, Screen-ETag, Questionnaire-ETag

## validation rules

* title is required on create screen and must be unique within the questionnaire
* answer_kind must be one of: short_string, long_text, boolean, number, enum_single
* question_text must be non-empty
* screen_order and question_order are positive integers maintained by the backend as unique, contiguous sequences without gaps
* parent_question_id must reference an existing question and cannot be the same as question_id
* visibility rule must specify a value (or array of values) that equals the parent’s canonical value for its answer_kind; the backend performs equality-only checks (per Epic I) and rejects incompatible kinds; if the parent is unanswered the child is hidden
* moving a question between screens is rejected if the target screen_id does not belong to the same questionnaire

## concurrency and ordering behaviour

* All PATCH operations require If-Match of the current Question-ETag or Screen-ETag as appropriate.
* On create, reorder and move operations the backend is authoritative for order calculations and returns updated ETags and final contiguous order values.
* Reads of screens and questions return items already sorted by their respective order fields. Clients must not sort or compute order.

## acceptance criteria

* Authors can add a screen and see it appear in a position determined by the backend with contiguous screen_order.
* Authors can reorder screens by proposing a position; the backend recalculates and persists a contiguous sequence with no gaps.
* Authors can add a question to a screen with a valid answer kind and see it in the correct position assigned by the backend.
* Authors can update question text without disturbing order.
* Authors can change question order within a screen by proposing a position; the backend returns a contiguous sequence.
* Authors can move a question between screens; the backend reindexes both source and target screens to maintain contiguous sequences.
* Authors can set or clear a conditional parent with a valid rule, and the model reflects this on subsequent reads.
* All writes are protected by ETags and respond deterministically with updated ordering and ETags.

Scope

1.1 Purpose
Enable precise, safe authoring of questionnaires without bulk import. Authors can curate screens and questions, with ordering and simple visibility rules managed consistently by the system.

1.2 Inclusions

Create, rename and order screens within a questionnaire

Add questions to a chosen screen

Update question text and mandatory flag or helper text

Reorder questions within a screen

Move a question between screens

Set or clear a question’s conditional parent using equality-based visibility rules

System-maintained, gapless ordering for screens and questions

1.3 Exclusions

End user response capture

Runtime visibility evaluation beyond storing the authoring rule

Bulk CSV import or export flows

New or experimental answer kinds

Any access or role management

1.4 Context
This story sits in the authoring domain and complements existing read and runtime services. It persists questionnaire structure and simple visibility rules so downstream reads can present screens and questions in a deterministic order. It interacts only with internal questionnaire authoring APIs; the client proposes positions or changes, and the backend ensures contiguous ordering and consistency.

**2.2. EARS Functionality**

**2.2.1 Ubiquitous requirements**

* **U1** The system will maintain a contiguous 1-based screen_order for each questionnaire with no gaps.
* **U2** The system will maintain a contiguous 1-based question_order for each screen with no gaps.
* **U3** The system will act as the authoritative source of final order values irrespective of any client proposals.
* **U4** The system will provide deterministic read ordering for screens and questions given the same stored state.
* **U5** The system will return updated ETags for all affected entities after each successful write.
* **U6** The system will enforce equality-only visibility rules against the parent’s canonical value for its answer_kind.
* **U7** The system will allow a question to exist in an untyped state until the first placeholder is allocated.

**2.2.2 Event-driven requirements**

* **E1** When an author requests to create a screen with a title, the system will create the screen.
* **E2** When a screen is created, the system will assign a final screen_order position.
* **E3** When a screen is created, the system will persist the screen.
* **E4** When a screen is created, the system will return the created screen with screen_id, title, and screen_order.
* **E5** When a screen is created, the system will return Screen-ETag and Questionnaire-ETag.
* **E6** When an author requests to rename a screen, the system will update the screen title.
* **E7** When an author proposes a new screen position, the system will recalculate a contiguous screen_order for all screens.
* **E8** When a screen is renamed or repositioned, the system will persist the changes.
* **E9** When a screen is renamed or repositioned, the system will return updated ETags.
* **E10** When an author requests to create a question with text and target screen, the system will create a question scaffold without an answer kind and assign an initial question_order.
* **E11** When a question scaffold is created, the system will persist the question.
* **E12** When a question scaffold is created, the system will return the created question with answer_kind unset and question_order set.
* **E13** When a question scaffold is created, the system will return Question-ETag, Screen-ETag, and Questionnaire-ETag.
* **E14** When a question is created, the system will return Question-ETag, Screen-ETag, and Questionnaire-ETag.
* **E15** When an author requests to update question_text or metadata, the system will update the specified fields.
* **E16** When question fields are updated, the system will persist the changes.
* **E17** When question fields are updated, the system will return updated ETags.
* **E18** When an author proposes a new question_order for a question, the system will recalculate a contiguous sequence for that screen.
* **E19** When a question is repositioned, the system will persist the updated sequence.
* **E20** When a question is repositioned, the system will return updated ETags and the updated question_order.
* **E21** When an author requests to move a question to another screen, the system will assign a new question_order in the target screen.
* **E22** When a question is moved, the system will reindex the source screen to maintain a contiguous sequence.
* **E23** When a question is moved, the system will persist changes to both source and target screens.
* **E24** When a question is moved, the system will return updated ETags for all affected entities and the updated question_order in the target screen.
* **E25** When a conditional parent is cleared, the system will remove the parent reference and rule and return updated ETags.
* **E26** When the first placeholder is allocated to an untyped question, the system will determine the answer kind from the allocation context.
* **E27** When an answer kind is determined for a question, the system will persist the answer kind.
* **E28** When an answer kind is persisted for a question, the system will return the updated question with answer_kind set and updated ETags.

**2.2.3 State-driven requirements**

* **S1** While a questionnaire exists, the system will expose screens sorted by screen_order.
* **S2** While a screen exists, the system will expose questions sorted by question_order.
* **S3** While a question is untyped, the system will expose answer_kind as unset and suppress type-dependent authoring fields.

**2.2.4 Optional-feature requirements**

* **O1** Where a proposed position is provided on create or move, the system will treat it as a placement hint.
* **O2** Where an Idempotency-Key is provided on a create request, the system will de-duplicate retried requests and return the original result.
* **O3** Where If-Match is provided on a PATCH, the system will validate concurrency against the current entity ETag.

**2.2.5 Unwanted-behaviour requirements**

* **N1** If If-Match does not match the current ETag, the system will reject the request without persisting any changes.
* **N2** If a move targets a screen outside the questionnaire, the system will reject the request without persisting any changes.
* **N3** If answer_kind is invalid, the system will reject the request without persisting any changes.
* **N4** If a proposed position is non-positive or not an integer, the system will reject the request without persisting any changes.
* **N5** If a visibility rule is incompatible with the parent’s answer_kind, the system will reject the request without persisting any changes.
* **N6** If parent_question_id introduces a cycle, the system will reject the request without persisting any changes.
* **N7** If a duplicate screen title is supplied within a questionnaire, the system will reject the request without persisting any changes.
* **N8** If a request attempts to move a question across questionnaire boundaries, the system will reject the request without persisting any changes.
* **N9** If a client supplies an answer kind during question creation, the system will reject the request without persisting any changes.

**2.2.6 Step Index**

* **STEP-1** Create screen → U1, U3, U4, U5, E1, E2, E3, E4, E5, O2
* **STEP-2** Rename screen and set position → U1, U3, U4, U5, E6, E7, E8, E9, O3, N1, N7, N4
* **STEP-3** Create question → U2, U3, U4, U5, U7, E10, E11, E12, E13, E14, O2, N3, N9
* **STEP-3A** Allocate first placeholder → E29, E30, E31, S4, U6, N10, N11
* **STEP-4** Update question text → U5, E15, E16, E17, O3, N1
* **STEP-5** Reorder questions within a screen → U2, U3, U4, U5, E18, E19, E20, O1, O3, N1, N4
* **STEP-6** Reorder screens → U1, U3, U4, U5, E7, E8, E9, O1, O3, N1, N4
* **STEP-7** Move question between screens → U1, U2, U3, U4, U5, E21, E22, E23, E24, O1, O3, N1, N2, N8
* **STEP-8** Set conditional parent → U6, U5, E25, E26, E27, O3, N1, N5, N6
* **STEP-9** Clear conditional parent → U5, E28, O3, N1

# Input Fields

For each field required as an effective input to this feature, complete the table with the following columns:

Field – The exact name of the input. Use consistent naming with APIs, UI forms, or system references.

Include inputs from three origins:

* provided – supplied by the caller at the entrypoint
* acquired – fetched internally by this feature from outside its scope (for example file system, environment, network) and then consumed as input
* returned – data produced by a call to an external function or service that is outside this spec’s scope, which then becomes input to downstream steps

If (and only if) an input is a declared structured object with a known or proposed schema, list its relevant declared nested fields as separate rows using dot or bracket notation (for example parent.child, parent.items\[].subfield). This applies to structured inputs of any origin.

Do not infer or invent nested fields for inputs that are atomic (for example string, number, boolean, date, file) or for objects without a declared or proposed schema.

Description – A short, plain-language explanation of what the field represents. Avoid technical jargon.

Type – The data type (for example string, integer, boolean, date, array, object).

Schema / Reference – Always populate this.

Prefer an authoritative reference: OpenAPI \$ref (for example #/components/schemas/UserId) or a JSON Schema URI or fragment.

If no schema exists, propose a provisional schema name and path that can later be formalised (for example #/components/schemas/InputObject, #/components/schemas/RequestContext).

For structured inputs (known or proposed) list nested rows and reflect their actual or proposed nested path here as well (for example #/components/schemas/RequestContext/properties/request\_id).

For atomic inputs, provide a single schema reference (actual or provisional) and do not invent nested property paths.

Notes – Capture explanatory details, business context, or guidance that is helpful but not enforceable as a requirement. Examples include optional defaults, usage examples, or domain clarifications. If there is no additional context, write “None.” Do not place constraints or validity rules here; all requirements must go in Pre-Conditions.

Pre-Conditions – List every condition that must hold true before this input can be processed. Write each condition as a clear clause using a verb and object, and separate clauses with semicolons ;.
Examples:

* provided: “Field is required and must be provided”; “Value must conform to ISO 8601 date format”
* acquired: “Resource must exist and be readable by the process”; “Document must parse as valid JSON”; “Reference must resolve to a known identifier”
* returned: “Call must complete without error”; “Return value must match the declared schema”; “Return value must be treated as immutable within this step”
  These conditions will drive the Pre-Condition Error Modes.

Origin – Use exactly one of: provided, acquired, returned.

* provided: data supplied by the caller at the entrypoint
* acquired: data fetched internally from outside this spec’s scope and then used as input
* returned: data produced by an out-of-scope call that is subsequently consumed as input

Guidelines

Scope: Include all effective inputs consumed by this feature, whether provided, acquired, or returned. Do not include system-generated identifiers, derived values created inside this feature, intermediate artefacts not consumed as inputs, or outputs.

Granularity: Expand nested rows only for inputs that are declared or proposed structured objects. Do not expand atomic types or any input lacking a declared or proposed schema for subfields.

Cover every input necessary for the feature to operate.

Be precise and unambiguous. One row per field.

Use semicolons ; to separate pre-conditions (one clause per condition).

Each clause must be at least four words and include the subject and the required state or action.

Do not duplicate conditions between Notes and Pre-Conditions. All enforceable requirements belong in Pre-Conditions. Notes are strictly for contextual or descriptive information.

If no input is required, write “None.”

Additional constraints for consistency and testability:

* Type vocabulary for resources: for filesystem and code resources, choose Type from this set only: path, file (yaml|json|python), directory, directory of files (json|python), module, dict, list\[type]. Do not use generic types like string or array for these resources.
* Origin gating: use returned only when the value is produced by a named external call outside this spec. When Origin is returned, include “Provider: <function or service name>” in Notes and reference the provider’s declared return contract in Schema / Reference. Otherwise classify as acquired.
* Concrete locator requirement: for acquired resources, the Field value must be a project-relative path or a glob pattern based on a configured base path (for example routes/langgraph\_routing.yaml, schemas/\*\*/\*.json). Do not use absolute OS paths or generic labels.
* Pre-Condition scope: Pre-Conditions must state verifiable properties of the input itself. Do not include system behaviours, process steps, or goals.
* Resource-specific Pre-Condition templates:

  * file: “File exists and is readable; Content parses as valid \<yaml|json>; Content conforms to the referenced schema”
  * directory of files (json): “Directory exists and is readable; Each file parses as valid JSON; Each schema includes a unique \$id; Each \$ref resolves to an existing definition”
  * directory of files (python): “Directory exists and is readable; Each file is importable as a module; Relative imports are not present; Each module exposes required symbols”
  * module: “Module is importable; Relative imports are not present; Module exposes callable <name>(state: dict) -> dict”
* Precision requirement: avoid vague phrases such as “defined correctly” or “adheres to conventions”. Write specific, testable conditions.
* Inclusion rule for derived artefacts: include a derived artefact as an input only if it crosses a boundary and is consumed as an input by a later step within this spec. Do not include logs, error objects, metrics, or internal caches unless they are provided by the caller or explicitly returned by a named external provider.
* Override pairing: when an acquired resource can be overridden by configuration (for example an environment variable or function argument), also include a corresponding provided input row for that override.
* Schema reference rule: always prefer an authoritative schema URI. If none exists, use a provisional name. For structured objects, include sub-rows for declared fields with dot or bracket paths.

Output format: Produce a plain Markdown table only, with columns exactly: Field, Description, Type, Schema / Reference, Notes, Pre-Conditions, Origin. Do not include code fences, language tags, or section headings around the table.

Reuse existing schemas and follow the same schema structure from the schemas folder in the attached codebase

| Field                               | Description                                                                                                     | Type                   | Schema / Reference                                                             | Notes                                                                                             | Post-Conditions                                                                                                                                                                                                                        |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| outputs.screen                      | Screen object returned when a screen is created or updated.                                                     | object                 | #/components/schemas/Outputs/properties/screen                                 | Projection of the affected screen only (not a list).                                              | Field is optional and present only for screen operations; Object contains keys screen_id, title, screen_order; Object validates against the referenced schema; Key set is deterministic for identical inputs.                          |
| outputs.screen.screen_id            | Identifier of the affected screen.                                                                              | string                 | #/components/schemas/Outputs/properties/screen/properties/screen_id            | None.                                                                                             | Field is required when outputs.screen is present; Value validates against the referenced schema; Value is non-empty and immutable for the lifetime of the screen.                                                                      |
| outputs.screen.title                | Current title of the screen.                                                                                    | string                 | #/components/schemas/Outputs/properties/screen/properties/title                | None.                                                                                             | Field is required when outputs.screen is present; Value validates against the referenced schema; Value reflects the latest persisted title.                                                                                            |
| outputs.screen.screen_order         | Screen’s position within the questionnaire.                                                                     | integer                | #/components/schemas/Outputs/properties/screen/properties/screen_order         | None.                                                                                             | Field is required when outputs.screen is present; Value validates against the referenced schema; Value is a positive integer; Value reflects a contiguous 1-based sequence with no gaps.                                               |
| outputs.question                    | Question object returned when a question is created, updated, reordered, moved, or its visibility rule changes. | object                 | #/components/schemas/Outputs/properties/question                               | Projection of the affected question only (not a list).                                            | Field is optional and present only for question operations; Object contains keys question_id, screen_id, question_text, question_order; Object validates against the referenced schema; Key set is deterministic for identical inputs. |
| outputs.question.question_id        | Identifier of the affected question.                                                                            | string                 | #/components/schemas/Outputs/properties/question/properties/question_id        | None.                                                                                             | Field is required when outputs.question is present; Value validates against the referenced schema; Value is non-empty and immutable for the lifetime of the question.                                                                  |
| outputs.question.screen_id          | Identifier of the screen the question currently belongs to.                                                     | string                 | #/components/schemas/Outputs/properties/question/properties/screen_id          | Changes when the question is moved.                                                               | Field is required when outputs.question is present; Value validates against the referenced schema; Value reflects the latest persisted screen assignment.                                                                              |
| outputs.question.question_text      | Current text of the question.                                                                                   | string                 | #/components/schemas/Outputs/properties/question/properties/question_text      | None.                                                                                             | Field is required when outputs.question is present; Value validates against the referenced schema; Value reflects the latest persisted text.                                                                                           |
| outputs.question.answer_kind        | Answer kind for the question.                                                                                   | string                 | #/components/schemas/Outputs/properties/question/properties/answer_kind        | May be unset (null) for newly created scaffolds until first placeholder is allocated.             | Field is optional; When present, value validates against the referenced schema; When absent or null, the question is considered untyped during this step.                                                                              |
| outputs.question.question_order     | Question’s position within its screen.                                                                          | integer                | #/components/schemas/Outputs/properties/question/properties/question_order     | Returned on create, reorder, and move.                                                            | Field is required when outputs.question is present; Value validates against the referenced schema; Value is a positive integer; Value reflects a contiguous 1-based sequence with no gaps.                                             |
| outputs.question.parent_question_id | Identifier of the parent question for visibility (nullable).                                                    | string                 | #/components/schemas/Outputs/properties/question/properties/parent_question_id | Null indicates no visibility rule is active.                                                      | Field is optional; When present, value validates against the referenced schema; When cleared, value is null and not an empty string.                                                                                                   |
| outputs.question.visible_if_value   | Canonical value(s) required for visibility (nullable).                                                          | string or list[string] | #/components/schemas/Outputs/properties/question/properties/visible_if_value   | Equality-only per Epic I; May be a single canonical value or a list (any-of).                     | Field is optional; When present, value validates against the referenced schema; When cleared, value is null; When present, values are instances of the parent’s canonical domain.                                                      |
| outputs.etags                       | ETag container for optimistic concurrency.                                                                      | object                 | #/components/schemas/Outputs/properties/etags                                  | May be delivered as HTTP headers in transport; represented here as a projection for completeness. | Field is required for successful writes; Object contains keys question, screen, questionnaire as applicable; Object validates against the referenced schema; Key set includes only entities affected by the operation.                 |
| outputs.etags.question              | Entity tag for the affected question.                                                                           | string                 | #/components/schemas/Outputs/properties/etags/properties/question              | Projection of the Question-ETag header.                                                           | Field is optional; When present, value validates against the referenced schema; Value is a non-empty opaque string; Value changes when the question’s persisted state changes.                                                         |
| outputs.etags.screen                | Entity tag for the affected screen.                                                                             | string                 | #/components/schemas/Outputs/properties/etags/properties/screen                | Projection of the Screen-ETag header.                                                             | Field is optional; When present, value validates against the referenced schema; Value is a non-empty opaque string; Value changes when the screen’s persisted state changes.                                                           |
| outputs.etags.questionnaire         | Entity tag for the questionnaire container.                                                                     | string                 | #/components/schemas/Outputs/properties/etags/properties/questionnaire         | Projection of the Questionnaire-ETag header.                                                      | Field is optional; When present, value validates against the referenced schema; Value is a non-empty opaque string; Value changes when the questionnaire’s persisted state changes.                                                    |

| Error Code                                                             | Field Reference                                    | Description                                                                                | Likely Cause                           | Flow Impact                                | Behavioural AC Required |
| ---------------------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------ | -------------------------------------- | ------------------------------------------ | ----------------------- |
| PRE_QUESTIONNAIRE_ID_MISSING                                           | questionnaire_id                                   | questionnaire_id is required but was not provided.                                         | Missing value at entrypoint.           | halt_pipeline                              | Yes                     |
| PRE_QUESTIONNAIRE_ID_SCHEMA_MISMATCH                                   | questionnaire_id                                   | questionnaire_id does not match the declared schema.                                       | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_QUESTIONNAIRE_ID_NOT_FOUND                                         | questionnaire_id                                   | questionnaire_id does not resolve to an existing questionnaire.                            | Unknown or deleted identifier.         | halt_pipeline                              | Yes                     |
| PRE_SCREEN_ID_REQUIRED_WHEN_TARGETED                                   | screen_id                                          | screen_id is required when targeting a specific screen but is missing.                     | Conditional required field omitted.    | halt_pipeline                              | Yes                     |
| PRE_SCREEN_ID_SCHEMA_MISMATCH                                          | screen_id                                          | screen_id does not match the declared schema.                                              | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_SCREEN_ID_NOT_IN_QUESTIONNAIRE                                     | screen_id                                          | screen_id does not resolve to a screen in the questionnaire.                               | Wrong questionnaire or unknown screen. | halt_pipeline                              | Yes                     |
| PRE_TARGET_SCREEN_ID_REQUIRED_FOR_MOVE                                 | target_screen_id                                   | target_screen_id is required when moving a question but is missing.                        | Conditional required field omitted.    | halt_pipeline                              | Yes                     |
| PRE_TARGET_SCREEN_ID_SCHEMA_MISMATCH                                   | target_screen_id                                   | target_screen_id does not match the declared schema.                                       | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_TARGET_SCREEN_ID_NOT_IN_QUESTIONNAIRE                              | target_screen_id                                   | target_screen_id does not resolve to a screen in the same questionnaire.                   | Cross-questionnaire or unknown screen. | halt_pipeline                              | Yes                     |
| PRE_QUESTION_ID_REQUIRED_FOR_OPERATION                                 | question_id                                        | question_id is required when operating on a question but is missing.                       | Conditional required field omitted.    | halt_pipeline                              | Yes                     |
| PRE_QUESTION_ID_SCHEMA_MISMATCH                                        | question_id                                        | question_id does not match the declared schema.                                            | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_QUESTION_ID_NOT_IN_QUESTIONNAIRE                                   | question_id                                        | question_id does not resolve to a question in the questionnaire.                           | Unknown or out-of-scope identifier.    | halt_pipeline                              | Yes                     |
| PRE_TITLE_REQUIRED_FOR_CREATE_RENAME                                   | title                                              | title is required for create or rename operations but is missing.                          | Required field omitted.                | halt_pipeline                              | Yes                     |
| PRE_TITLE_NON_EMPTY_STRING                                             | title                                              | title is not a non-empty string.                                                           | Empty or whitespace-only value.        | halt_pipeline                              | Yes                     |
| PRE_TITLE_NOT_UNIQUE                                                   | title                                              | title is not unique within the questionnaire.                                              | Duplicate screen title.                | halt_pipeline                              | Yes                     |
| PRE_QUESTION_TEXT_REQUIRED_FOR_CREATE_UPDATE                           | question_text                                      | question_text is required for creation or update but is missing.                           | Required field omitted.                | halt_pipeline                              | Yes                     |
| PRE_QUESTION_TEXT_NON_EMPTY_STRING                                     | question_text                                      | question_text is not a non-empty string.                                                   | Empty or whitespace-only value.        | halt_pipeline                              | Yes                     |
| PRE_QUESTION_TEXT_SCHEMA_MISMATCH                                      | question_text                                      | question_text does not match the declared schema.                                          | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_HINT_NOT_STRING_WHEN_PROVIDED                                      | hint                                               | hint was provided but is not a string.                                                     | Incorrect type supplied.               | halt_pipeline                              | Yes                     |
| PRE_HINT_SCHEMA_MISMATCH_WHEN_PROVIDED                                 | hint                                               | hint was provided but does not match the declared schema.                                  | Invalid format or constraints.         | halt_pipeline                              | Yes                     |
| PRE_TOOLTIP_NOT_STRING_WHEN_PROVIDED                                   | tooltip                                            | tooltip was provided but is not a string.                                                  | Incorrect type supplied.               | halt_pipeline                              | Yes                     |
| PRE_TOOLTIP_SCHEMA_MISMATCH_WHEN_PROVIDED                              | tooltip                                            | tooltip was provided but does not match the declared schema.                               | Invalid format or constraints.         | halt_pipeline                              | Yes                     |
| PRE_PROPOSED_POSITION_NOT_INTEGER_GE_1                                 | proposed_position                                  | proposed_position is not an integer ≥ 1.                                                   | Type or range violation.               | halt_pipeline                              | Yes                     |
| PRE_PROPOSED_POSITION_EXCEEDS_MAX                                      | proposed_position                                  | proposed_position exceeds current screen count plus one.                                   | Out-of-range placement.                | halt_pipeline                              | Yes                     |
| PRE_PROPOSED_QUESTION_ORDER_NOT_INT_GE_1                               | proposed_question_order                            | proposed_question_order is not an integer ≥ 1.                                             | Type or range violation.               | halt_pipeline                              | Yes                     |
| PRE_PROPOSED_QUESTION_ORDER_EXCEEDS_MAX                                | proposed_question_order                            | proposed_question_order exceeds current question count plus one.                           | Out-of-range placement.                | halt_pipeline                              | Yes                     |
| PRE_PARENT_QUESTION_ID_REQUIRED_FOR_RULE                               | parent_question_id                                 | parent_question_id is required when setting a visibility rule but is missing.              | Conditional required field omitted.    | halt_pipeline                              | Yes                     |
| PRE_PARENT_QUESTION_ID_SCHEMA_MISMATCH                                 | parent_question_id                                 | parent_question_id does not match the declared schema.                                     | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_PARENT_QUESTION_ID_NOT_FOUND_OR_SELF                               | parent_question_id                                 | parent_question_id does not resolve or references the child itself.                        | Unknown parent or self-reference.      | halt_pipeline                              | Yes                     |
| PRE_VISIBLE_IF_VALUE_REQUIRED_FOR_RULE                                 | visible_if_value                                   | visible_if_value is required when setting a visibility rule but is missing.                | Conditional required field omitted.    | halt_pipeline                              | Yes                     |
| PRE_VISIBLE_IF_VALUE_INVALID_TYPE                                      | visible_if_value                                   | visible_if_value is not a string or list of strings.                                       | Incorrect type supplied.               | halt_pipeline                              | Yes                     |
| PRE_VISIBLE_IF_VALUE_OUT_OF_DOMAIN                                     | visible_if_value                                   | visible_if_value contains values outside the parent’s canonical domain.                    | Unsupported canonical values.          | halt_pipeline                              | Yes                     |
| PRE_REQUEST_HEADERS_IDEMPOTENCY_KEY_NOT_OPAQUE                         | request_headers.idempotency_key                    | idempotency_key was provided but is not an opaque string.                                  | Predictable or structured value used.  | halt_pipeline                              | Yes                     |
| PRE_REQUEST_HEADERS_IDEMPOTENCY_KEY_SCHEMA_MISMATCH                    | request_headers.idempotency_key                    | idempotency_key was provided but does not match the declared schema.                       | Invalid format or constraints.         | halt_pipeline                              | Yes                     |
| PRE_REQUEST_HEADERS_IF_MATCH_REQUIRED_ON_PATCH                         | request_headers.if_match                           | if_match header is required on PATCH but is missing.                                       | Required header omitted.               | halt_pipeline                              | Yes                     |
| PRE_REQUEST_HEADERS_IF_MATCH_NOT_LATEST_ETAG                           | request_headers.if_match                           | if_match value does not equal the latest entity ETag known to the caller.                  | Stale or incorrect ETag.               | halt_pipeline                              | Yes                     |
| PRE_REQUEST_HEADERS_IF_MATCH_SCHEMA_MISMATCH                           | request_headers.if_match                           | if_match does not match the declared schema.                                               | Invalid format or constraints.         | halt_pipeline                              | Yes                     |
| PRE_SCREENS_SCREEN_ID_RESOURCE_UNREADABLE                              | screens[].screen_id                                | screens[].screen_id resource does not exist or is not readable.                            | Missing or inaccessible resource.      | halt_pipeline                              | Yes                     |
| PRE_SCREENS_SCREEN_ID_NOT_FOUND                                        | screens[].screen_id                                | screens[].screen_id does not resolve to an existing screen.                                | Unknown screen identifier.             | halt_pipeline                              | Yes                     |
| PRE_SCREENS_SCREEN_ID_SCHEMA_MISMATCH                                  | screens[].screen_id                                | screens[].screen_id does not match the declared schema.                                    | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_SCREENS_SCREEN_ORDER_RESOURCE_UNREADABLE                           | screens[].screen_order                             | screens[].screen_order resource does not exist or is not readable.                         | Missing or inaccessible resource.      | halt_pipeline                              | Yes                     |
| PRE_SCREENS_SCREEN_ORDER_NOT_INTEGER_GE_1                              | screens[].screen_order                             | screens[].screen_order is not an integer ≥ 1.                                              | Type or range violation.               | halt_pipeline                              | Yes                     |
| PRE_SCREENS_SCREEN_ORDER_SCHEMA_MISMATCH                               | screens[].screen_order                             | screens[].screen_order does not match the declared schema.                                 | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_QUESTIONS_QUESTION_ID_RESOURCE_UNREADABLE                          | questions[].question_id                            | questions[].question_id resource does not exist or is not readable.                        | Missing or inaccessible resource.      | halt_pipeline                              | Yes                     |
| PRE_QUESTIONS_QUESTION_ID_NOT_FOUND                                    | questions[].question_id                            | questions[].question_id does not resolve to an existing question.                          | Unknown question identifier.           | halt_pipeline                              | Yes                     |
| PRE_QUESTIONS_QUESTION_ID_SCHEMA_MISMATCH                              | questions[].question_id                            | questions[].question_id does not match the declared schema.                                | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_QUESTIONS_QUESTION_ORDER_RESOURCE_UNREADABLE                       | questions[].question_order                         | questions[].question_order resource does not exist or is not readable.                     | Missing or inaccessible resource.      | halt_pipeline                              | Yes                     |
| PRE_QUESTIONS_QUESTION_ORDER_NOT_INTEGER_GE_1                          | questions[].question_order                         | questions[].question_order is not an integer ≥ 1.                                          | Type or range violation.               | halt_pipeline                              | Yes                     |
| PRE_QUESTIONS_QUESTION_ORDER_SCHEMA_MISMATCH                           | questions[].question_order                         | questions[].question_order does not match the declared schema.                             | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_PARENT_QUESTION_QUESTION_ID_RESOURCE_UNREADABLE                    | parent_question.question_id                        | parent_question.question_id resource does not exist or is not readable.                    | Missing or inaccessible resource.      | halt_pipeline                              | Yes                     |
| PRE_PARENT_QUESTION_QUESTION_ID_MISMATCH                               | parent_question.question_id                        | parent_question.question_id does not match the provided parent_question_id.                | Cross-reference mismatch.              | halt_pipeline                              | Yes                     |
| PRE_PARENT_QUESTION_QUESTION_ID_SCHEMA_MISMATCH                        | parent_question.question_id                        | parent_question.question_id does not match the declared schema.                            | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_PARENT_QUESTION_ANSWER_KIND_RESOURCE_UNREADABLE                    | parent_question.answer_kind                        | parent_question.answer_kind resource does not exist or is not readable.                    | Missing or inaccessible resource.      | halt_pipeline                              | Yes                     |
| PRE_PARENT_QUESTION_ANSWER_KIND_UNSUPPORTED                            | parent_question.answer_kind                        | parent_question.answer_kind is not one of the supported answer kinds.                      | Unsupported or unknown type.           | halt_pipeline                              | Yes                     |
| PRE_PARENT_QUESTION_ANSWER_KIND_SCHEMA_MISMATCH                        | parent_question.answer_kind                        | parent_question.answer_kind does not match the declared schema.                            | Invalid format or type.                | halt_pipeline                              | Yes                     |
| PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_CALL_FAILED           | placeholder_allocation_result.placeholder_id       | placeholder_allocation_result.placeholder_id provider call did not complete without error. | Upstream Transform Service error.      | skip_downstream_step:determine_answer_kind | Yes                     |
| PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_SCHEMA_MISMATCH       | placeholder_allocation_result.placeholder_id       | placeholder_allocation_result.placeholder_id does not match the provider’s return schema.  | Contract drift or malformed response.  | skip_downstream_step:determine_answer_kind | Yes                     |
| PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_MUTATED               | placeholder_allocation_result.placeholder_id       | placeholder_allocation_result.placeholder_id value was mutated within this step.           | In-step mutation of returned value.    | halt_pipeline                              | Yes                     |
| PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_CALL_FAILED     | placeholder_allocation_result.inferred_answer_kind | inferred_answer_kind provider call did not complete without error.                         | Upstream Transform Service error.      | skip_downstream_step:determine_answer_kind | Yes                     |
| PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_SCHEMA_MISMATCH | placeholder_allocation_result.inferred_answer_kind | inferred_answer_kind does not match the provider’s return schema.                          | Contract drift or malformed response.  | skip_downstream_step:determine_answer_kind | Yes                     |
| PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_MUTATED         | placeholder_allocation_result.inferred_answer_kind | inferred_answer_kind value was mutated within this step.                                   | In-step mutation of returned value.    | halt_pipeline                              | Yes                     |

| Error Code                                             | Output Field Ref                    | Description                                                                                            | Likely Cause                                 | Flow Impact        | Behavioural AC Required |
| ------------------------------------------------------ | ----------------------------------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------- | ------------------ | ----------------------- |
| POST_OUTPUTS_SCREEN_CONTEXT_MISMATCH                   | outputs.screen                      | outputs.screen is missing for a screen operation or present for a non-screen operation.                | Conditional presence rule violated.          | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_KEYS_INCOMPLETE                    | outputs.screen                      | outputs.screen does not contain required keys screen_id, title, screen_order.                          | Partial object construction.                 | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_SCHEMA_INVALID                     | outputs.screen                      | outputs.screen does not validate against the referenced schema.                                        | Schema mismatch or wrong types.              | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_KEYS_NON_DETERMINISTIC             | outputs.screen                      | outputs.screen key set is not deterministic for identical inputs.                                      | Non-deterministic serialization or ordering. | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_SCREEN_ID_MISSING                  | outputs.screen.screen_id            | outputs.screen.screen_id is missing when outputs.screen is present.                                    | Omitted identifier.                          | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_SCREEN_ID_SCHEMA_INVALID           | outputs.screen.screen_id            | outputs.screen.screen_id does not validate against the referenced schema.                              | Invalid format or type.                      | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_SCREEN_ID_MUTATED                  | outputs.screen.screen_id            | outputs.screen.screen_id is not immutable across the screen’s lifetime.                                | Identifier reassigned or regenerated.        | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_TITLE_MISSING                      | outputs.screen.title                | outputs.screen.title is missing when outputs.screen is present.                                        | Omitted title.                               | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_TITLE_SCHEMA_INVALID               | outputs.screen.title                | outputs.screen.title does not validate against the referenced schema.                                  | Invalid format or type.                      | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_TITLE_NOT_LATEST                   | outputs.screen.title                | outputs.screen.title does not reflect the latest persisted title.                                      | Stale projection or failed update.           | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_SCREEN_ORDER_MISSING               | outputs.screen.screen_order         | outputs.screen.screen_order is missing when outputs.screen is present.                                 | Omitted order value.                         | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_SCREEN_ORDER_SCHEMA_INVALID        | outputs.screen.screen_order         | outputs.screen.screen_order does not validate against the referenced schema.                           | Invalid format or type.                      | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_SCREEN_ORDER_NOT_POSITIVE          | outputs.screen.screen_order         | outputs.screen.screen_order is not a positive integer.                                                 | Range violation.                             | block_finalization | Yes                     |
| POST_OUTPUTS_SCREEN_SCREEN_ORDER_SEQUENCE_BROKEN       | outputs.screen.screen_order         | outputs.screen.screen_order does not reflect a contiguous 1-based sequence with no gaps.               | Reindex failure or inconsistent ordering.    | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_CONTEXT_MISMATCH                 | outputs.question                    | outputs.question is missing for a question operation or present for a non-question operation.          | Conditional presence rule violated.          | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_KEYS_INCOMPLETE                  | outputs.question                    | outputs.question does not contain required keys question_id, screen_id, question_text, question_order. | Partial object construction.                 | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_SCHEMA_INVALID                   | outputs.question                    | outputs.question does not validate against the referenced schema.                                      | Schema mismatch or wrong types.              | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_KEYS_NON_DETERMINISTIC           | outputs.question                    | outputs.question key set is not deterministic for identical inputs.                                    | Non-deterministic serialization or ordering. | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_QUESTION_ID_MISSING              | outputs.question.question_id        | outputs.question.question_id is missing when outputs.question is present.                              | Omitted identifier.                          | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_QUESTION_ID_SCHEMA_INVALID       | outputs.question.question_id        | outputs.question.question_id does not validate against the referenced schema.                          | Invalid format or type.                      | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_QUESTION_ID_MUTATED              | outputs.question.question_id        | outputs.question.question_id is not immutable across the question’s lifetime.                          | Identifier reassigned or regenerated.        | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_SCREEN_ID_MISSING                | outputs.question.screen_id          | outputs.question.screen_id is missing when outputs.question is present.                                | Omitted screen assignment.                   | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_SCREEN_ID_SCHEMA_INVALID         | outputs.question.screen_id          | outputs.question.screen_id does not validate against the referenced schema.                            | Invalid format or type.                      | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_SCREEN_ID_NOT_LATEST             | outputs.question.screen_id          | outputs.question.screen_id does not reflect the latest persisted screen assignment.                    | Stale projection or failed move.             | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_TEXT_MISSING                     | outputs.question.question_text      | outputs.question.question_text is missing when outputs.question is present.                            | Omitted text.                                | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_TEXT_SCHEMA_INVALID              | outputs.question.question_text      | outputs.question.question_text does not validate against the referenced schema.                        | Invalid format or type.                      | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_TEXT_NOT_LATEST                  | outputs.question.question_text      | outputs.question.question_text does not reflect the latest persisted text.                             | Stale projection or failed update.           | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_ANSWER_KIND_SCHEMA_INVALID       | outputs.question.answer_kind        | outputs.question.answer_kind is present but does not validate against the referenced schema.           | Invalid value or type.                       | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_ORDER_MISSING                    | outputs.question.question_order     | outputs.question.question_order is missing when outputs.question is present.                           | Omitted order value.                         | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_ORDER_SCHEMA_INVALID             | outputs.question.question_order     | outputs.question.question_order does not validate against the referenced schema.                       | Invalid format or type.                      | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_ORDER_NOT_POSITIVE               | outputs.question.question_order     | outputs.question.question_order is not a positive integer.                                             | Range violation.                             | block_finalization | Yes                     |
| POST_OUTPUTS_QUESTION_ORDER_SEQUENCE_BROKEN            | outputs.question.question_order     | outputs.question.question_order does not reflect a contiguous 1-based sequence with no gaps.           | Reindex failure or inconsistent ordering.    | block_finalization | Yes                     |
| POST_OUTPUTS_PARENT_QUESTION_ID_SCHEMA_INVALID         | outputs.question.parent_question_id | outputs.question.parent_question_id is present but does not validate against the referenced schema.    | Invalid value or type.                       | block_finalization | Yes                     |
| POST_OUTPUTS_PARENT_QUESTION_ID_NOT_NULL_WHEN_CLEARED  | outputs.question.parent_question_id | outputs.question.parent_question_id is not null when the visibility rule has been cleared.             | Cleardown incorrectly represented.           | block_finalization | Yes                     |
| POST_OUTPUTS_VISIBLE_IF_VALUE_SCHEMA_INVALID           | outputs.question.visible_if_value   | outputs.question.visible_if_value is present but does not validate against the referenced schema.      | Invalid value or type.                       | block_finalization | Yes                     |
| POST_OUTPUTS_VISIBLE_IF_VALUE_NOT_NULL_WHEN_CLEARED    | outputs.question.visible_if_value   | outputs.question.visible_if_value is not null when the visibility rule has been cleared.               | Cleardown incorrectly represented.           | block_finalization | Yes                     |
| POST_OUTPUTS_VISIBLE_IF_VALUE_DOMAIN_MISMATCH          | outputs.question.visible_if_value   | outputs.question.visible_if_value values are not instances of the parent’s canonical domain.           | Domain mapping or normalization error.       | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_MISSING_FOR_WRITE                   | outputs.etags                       | outputs.etags is missing for a successful write.                                                       | Headers not captured or projection omitted.  | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_KEYS_INCOMPLETE                     | outputs.etags                       | outputs.etags does not contain only applicable keys question, screen, questionnaire.                   | Incorrect key population.                    | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_SCHEMA_INVALID                      | outputs.etags                       | outputs.etags does not validate against the referenced schema.                                         | Schema mismatch or wrong types.              | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_KEYS_INCLUDE_UNAFFECTED             | outputs.etags                       | outputs.etags includes entities not affected by the operation.                                         | Over-broad ETag reporting.                   | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_QUESTION_SCHEMA_INVALID             | outputs.etags.question              | outputs.etags.question is present but does not validate against the referenced schema.                 | Invalid value or type.                       | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_QUESTION_EMPTY                      | outputs.etags.question              | outputs.etags.question is empty and not an opaque string.                                              | Empty or placeholder value.                  | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_QUESTION_NOT_CHANGED_ON_UPDATE      | outputs.etags.question              | outputs.etags.question did not change after the question’s persisted state changed.                    | ETag not regenerated.                        | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_SCREEN_SCHEMA_INVALID               | outputs.etags.screen                | outputs.etags.screen is present but does not validate against the referenced schema.                   | Invalid value or type.                       | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_SCREEN_EMPTY                        | outputs.etags.screen                | outputs.etags.screen is empty and not an opaque string.                                                | Empty or placeholder value.                  | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_SCREEN_NOT_CHANGED_ON_UPDATE        | outputs.etags.screen                | outputs.etags.screen did not change after the screen’s persisted state changed.                        | ETag not regenerated.                        | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_QUESTIONNAIRE_SCHEMA_INVALID        | outputs.etags.questionnaire         | outputs.etags.questionnaire is present but does not validate against the referenced schema.            | Invalid value or type.                       | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_QUESTIONNAIRE_EMPTY                 | outputs.etags.questionnaire         | outputs.etags.questionnaire is empty and not an opaque string.                                         | Empty or placeholder value.                  | block_finalization | Yes                     |
| POST_OUTPUTS_ETAGS_QUESTIONNAIRE_NOT_CHANGED_ON_UPDATE | outputs.etags.questionnaire         | outputs.etags.questionnaire did not change after the questionnaire’s persisted state changed.          | ETag not regenerated.                        | block_finalization | Yes                     |

| Error Code                             | Description                                                             | Likely Cause                                      | Source (Step in Section 2.x)            | Step ID (from Section 2.2.6)             | Reachability Rationale                                                                   | Flow Impact        | Behavioural AC Required |
| -------------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------- | --------------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------ | ----------------------- |
| RUN_SCREEN_CREATE_PERSIST_FAILED       | Persisting the new screen failed during creation.                       | Storage write error or transaction conflict.      | 2.2 – Create screen                     | STEP-1 Create screen                     | E3 requires the system to persist the screen; that write can fail at runtime.            | halt_pipeline      | Yes                     |
| RUN_SCREEN_ORDER_ASSIGN_FAILED         | Assigning final screen_order failed.                                    | Ordering engine error or constraint violation.    | 2.2 – Create screen                     | STEP-1 Create screen                     | E2 mandates assigning a final position; calculating/assigning order can fail.            | halt_pipeline      | Yes                     |
| RUN_SCREEN_SERIALIZATION_FAILED        | Returning the created screen failed.                                    | Serialization/marshalling error.                  | 2.2 – Create screen                     | STEP-1 Create screen                     | E4 requires returning the created screen object; response construction can fail.         | block_finalization | Yes                     |
| RUN_SCREEN_ETAG_GEN_FAILED             | Generating or returning screen/questionnaire ETags failed.              | ETag generation or header projection error.       | 2.2 – Create screen                     | STEP-1 Create screen                     | E5 requires returning Screen-ETag and Questionnaire-ETag; generation/return can fail.    | block_finalization | Yes                     |
| RUN_SCREEN_UPDATE_PERSIST_FAILED       | Persisting a renamed or repositioned screen failed.                     | Storage write error or transaction conflict.      | 2.2 – Rename screen and set position    | STEP-2 Rename screen and set position    | E8 requires persisting changes after rename/reposition.                                  | halt_pipeline      | Yes                     |
| RUN_SCREEN_REINDEX_FAILED              | Recalculating a contiguous screen order failed.                         | Ordering engine error or constraint violation.    | 2.2 – Rename screen and set position    | STEP-2 Rename screen and set position    | E7 mandates recalculating contiguous order; reindex can fail.                            | halt_pipeline      | Yes                     |
| RUN_SCREEN_ETAG_UPDATE_FAILED          | Returning updated ETags after screen change failed.                     | ETag regeneration or projection error.            | 2.2 – Rename screen and set position    | STEP-2 Rename screen and set position    | E9 requires returning updated ETags; this can fail.                                      | block_finalization | Yes                     |
| RUN_QUESTION_SCAFFOLD_CREATE_FAILED    | Creating a question scaffold failed.                                    | In-memory allocation/initialization error.        | 2.2 – Create question                   | STEP-3 Create question                   | E10 requires creating a scaffold; initialization can fail.                               | halt_pipeline      | Yes                     |
| RUN_QUESTION_ORDER_ASSIGN_FAILED       | Assigning initial question_order failed.                                | Ordering engine error or constraint violation.    | 2.2 – Create question                   | STEP-3 Create question                   | E10 mandates assigning an initial question_order; this can fail.                         | halt_pipeline      | Yes                     |
| RUN_QUESTION_PERSIST_FAILED            | Persisting the question scaffold failed.                                | Storage write error or transaction conflict.      | 2.2 – Create question                   | STEP-3 Create question                   | E11 requires persisting the question; write can fail.                                    | halt_pipeline      | Yes                     |
| RUN_QUESTION_SERIALIZATION_FAILED      | Returning the created question failed.                                  | Serialization/marshalling error.                  | 2.2 – Create question                   | STEP-3 Create question                   | E12 requires returning the created question; serialization can fail.                     | block_finalization | Yes                     |
| RUN_QUESTION_ETAG_GEN_FAILED           | Generating or returning ETags for question/screen/questionnaire failed. | ETag generation or header projection error.       | 2.2 – Create question                   | STEP-3 Create question                   | E13 and E14 require returning ETags; generation/return can fail.                         | block_finalization | Yes                     |
| RUN_DETERMINE_ANSWER_KIND_FAILED       | Determining answer_kind from allocation context failed.                 | Inference logic error or null allocation context. | 2.2 – Allocate first placeholder        | STEP-3A Allocate first placeholder       | E26 requires determining answer kind; inference can fail at runtime.                     | halt_pipeline      | Yes                     |
| RUN_PERSIST_ANSWER_KIND_FAILED         | Persisting the determined answer_kind failed.                           | Storage write error or transaction conflict.      | 2.2 – Allocate first placeholder        | STEP-3A Allocate first placeholder       | E27 requires persisting answer kind; write can fail.                                     | halt_pipeline      | Yes                     |
| RUN_TYPED_QUESTION_RETURN_FAILED       | Returning the updated typed question failed.                            | Serialization/marshalling error.                  | 2.2 – Allocate first placeholder        | STEP-3A Allocate first placeholder       | E28 requires returning the updated question; response construction can fail.             | block_finalization | Yes                     |
| RUN_UPDATE_FIELDS_APPLY_FAILED         | Applying requested field updates failed.                                | In-memory model update error.                     | 2.2 – Update question text              | STEP-4 Update question text              | E15 requires updating fields; application to the entity can fail.                        | halt_pipeline      | Yes                     |
| RUN_QUESTION_UPDATE_PERSIST_FAILED     | Persisting updated question fields failed.                              | Storage write error or transaction conflict.      | 2.2 – Update question text              | STEP-4 Update question text              | E16 requires persisting updates; write can fail.                                         | halt_pipeline      | Yes                     |
| RUN_QUESTION_ETAG_UPDATE_FAILED        | Returning updated ETags after question update failed.                   | ETag regeneration or projection error.            | 2.2 – Update question text              | STEP-4 Update question text              | E17 requires returning updated ETags; this can fail.                                     | block_finalization | Yes                     |
| RUN_QUESTION_REINDEX_FAILED            | Recalculating a contiguous question order failed.                       | Ordering engine error or constraint violation.    | 2.2 – Reorder questions within a screen | STEP-5 Reorder questions within a screen | E18 mandates reindex within the screen; can fail.                                        | halt_pipeline      | Yes                     |
| RUN_REORDER_PERSIST_FAILED             | Persisting the reordered question sequence failed.                      | Storage write error or transaction conflict.      | 2.2 – Reorder questions within a screen | STEP-5 Reorder questions within a screen | E19 requires persisting the updated sequence; write can fail.                            | halt_pipeline      | Yes                     |
| RUN_REORDER_RESULT_RETURN_FAILED       | Returning updated ETags and question_order failed.                      | Serialization or response projection error.       | 2.2 – Reorder questions within a screen | STEP-5 Reorder questions within a screen | E20 requires returning updated ETags and order; return can fail.                         | block_finalization | Yes                     |
| RUN_SCREEN_REORDER_PERSIST_FAILED      | Persisting the reordered screen sequence failed.                        | Storage write error or transaction conflict.      | 2.2 – Reorder screens                   | STEP-6 Reorder screens                   | E8 requires persisting changes after reindex; write can fail.                            | halt_pipeline      | Yes                     |
| RUN_MOVE_ASSIGN_TARGET_ORDER_FAILED    | Assigning new question_order in the target screen failed.               | Ordering engine error or constraint violation.    | 2.2 – Move question between screens     | STEP-7 Move question between screens     | E21 requires assigning a new order in target; this can fail.                             | halt_pipeline      | Yes                     |
| RUN_MOVE_REINDEX_SOURCE_FAILED         | Reindexing the source screen after move failed.                         | Ordering engine error or constraint violation.    | 2.2 – Move question between screens     | STEP-7 Move question between screens     | E22 requires reindexing the source; can fail.                                            | halt_pipeline      | Yes                     |
| RUN_MOVE_PERSIST_FAILED                | Persisting changes to source and target screens failed.                 | Storage write error or transaction conflict.      | 2.2 – Move question between screens     | STEP-7 Move question between screens     | E23 requires persisting changes to both screens; write can fail.                         | halt_pipeline      | Yes                     |
| RUN_MOVE_RESULT_RETURN_FAILED          | Returning updated ETags and target question_order failed.               | Serialization or response projection error.       | 2.2 – Move question between screens     | STEP-7 Move question between screens     | E24 requires returning updated ETags and order; return can fail.                         | block_finalization | Yes                     |
| RUN_SET_VISIBILITY_LINK_PERSIST_FAILED | Persisting the link to the conditional parent failed.                   | Storage write error or transaction conflict.      | 2.2 – Set conditional parent            | STEP-8 Set conditional parent            | Step-8 describes setting a conditional parent; persisting that link can fail at runtime. | halt_pipeline      | Yes                     |
| RUN_CLEAR_VISIBILITY_PERSIST_FAILED    | Clearing parent reference and rule failed.                              | Storage write error or transaction conflict.      | 2.2 – Clear conditional parent          | STEP-9 Clear conditional parent          | E25 requires removing the reference and rule; persistence can fail.                      | halt_pipeline      | Yes                     |
| RUN_CLEAR_RULE_RETURN_FAILED           | Returning updated ETags after clearing rule failed.                     | ETag regeneration or response projection error.   | 2.2 – Clear conditional parent          | STEP-9 Clear conditional parent          | E25 requires returning updated ETags; return can fail.                                   | block_finalization | Yes                     |

| Error Code                       | Description                                                                    | Likely Cause                                                               | Impacted Steps                                         | EARS Refs                           | Flow Impact   | Behavioural AC Required |
| -------------------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------- | ------------------------------------------------------ | ----------------------------------- | ------------- | ----------------------- |
| ENV_DB_NETWORK_UNREACHABLE       | Database cannot be reached over the network required for persists and updates. | Network unreachable or routing failure to DB endpoint.                     | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | E3, E8, E11, E16, E19, E23, E27, U5 | halt_pipeline | Yes                     |
| ENV_DB_DNS_RESOLUTION_FAILED     | Database hostname cannot be resolved for persistence operations.               | DNS misconfiguration or resolver outage.                                   | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | E3, E8, E11, E16, E19, E23, E27, U5 | halt_pipeline | Yes                     |
| ENV_DB_TLS_HANDSHAKE_FAILED      | Secure connection to the database cannot be established.                       | Invalid certificate, unsupported cipher, or clock skew impacting TLS.      | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | E3, E8, E11, E16, E19, E23, E27, U5 | halt_pipeline | Yes                     |
| ENV_DB_CONFIG_MISSING            | Database connection configuration is unavailable at runtime.                   | Missing DSN/URI, missing environment variables, or misconfigured settings. | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | E3, E8, E11, E16, E19, E23, E27, U5 | halt_pipeline | Yes                     |
| ENV_DB_CREDENTIALS_INVALID       | Authentication to the database fails for write operations.                     | Invalid username/password, expired token, or revoked credentials.          | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | E3, E8, E11, E16, E19, E23, E27, U5 | halt_pipeline | Yes                     |
| ENV_DB_AUTHZ_DENIED              | Database denies authorisation for required write operations.                   | Insufficient privileges on tables or schemas.                              | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | E3, E8, E11, E16, E19, E23, E27, U5 | halt_pipeline | Yes                     |
| ENV_DB_CONNECTION_LIMIT_EXCEEDED | New database connections are rejected due to pool or server limits.            | Exhausted connection pool or server max connections reached.               | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | E3, E8, E11, E16, E19, E23, E27, U5 | halt_pipeline | Yes                     |
| ENV_DB_TRANSACTION_DEADLOCK      | Database transaction cannot complete due to deadlock.                          | Concurrent updates causing cyclic locks.                                   | STEP-2, STEP-4, STEP-5, STEP-6, STEP-7                 | E8, E16, E19, E8, E23, U5           | halt_pipeline | Yes                     |
| ENV_DB_STORAGE_QUOTA_EXCEEDED    | Database refuses writes due to storage quota or disk exhaustion.               | Tablespace full or quota exceeded on managed DB.                           | STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7 | E3, E8, E11, E16, E19, E23, U5      | halt_pipeline | Yes                     |

### 6.1 Architectural Acceptance Criteria

**6.1.1 Screen entity schema fields**
The codebase defines a Screen entity with fields `screen_id`, `title`, and `screen_order`.
Refs: E4; outputs.screen.*, outputs.screen.screen_id, outputs.screen.title, outputs.screen.screen_order; STEP-1.

**6.1.2 Screen order uniqueness constraint**
The persistence layer declares a uniqueness constraint scoped to a questionnaire for `screen_order` (one position per screen per questionnaire).
Refs: U1, E2, E7; STEP-1, STEP-2.

**6.1.3 Question entity schema fields**
The codebase defines a Question entity with fields `question_id`, `screen_id`, `question_text`, `answer_kind` (nullable), `question_order`, `parent_question_id` (nullable), and `visible_if_value` (nullable string or list[string]).
Refs: U7, E12, E28; outputs.question.*, outputs.question.answer_kind, outputs.question.parent_question_id, outputs.question.visible_if_value; STEP-3, STEP-8, STEP-9.

**6.1.4 `answer_kind` is nullable at rest**
The Question schema allows `answer_kind` to be null to support untyped scaffolds prior to placeholder allocation.
Refs: U7, E10, E12; STEP-3.

**6.1.5 Create-question request excludes `answer_kind`**
The create-question entrypoint does not accept `answer_kind` in its request contract.
Refs: E10, N9; STEP-3.

**6.1.6 Question responses include `question_order`**
Responses for question create, reorder, and move include `question_order`.
Refs: E12, E20, E24; outputs.question.question_order; STEP-3, STEP-5, STEP-7.

**6.1.7 Write responses include ETags**
All successful write responses include applicable `Question-ETag`, `Screen-ETag`, and/or `Questionnaire-ETag` as per the operation.
Refs: U5, E5, E9, E13, E14, E17, E20, E24, E28; outputs.etags.*; STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-7, STEP-9.

**6.1.8 PATCH endpoints enforce If-Match**
All PATCH handlers require and validate the `If-Match` header before applying changes.
Refs: O3, N1; STEP-2, STEP-4, STEP-5, STEP-6, STEP-7, STEP-9.

**6.1.9 POST endpoints integrate idempotency**
Create handlers accept an `Idempotency-Key` and route through a shared idempotency component.
Refs: O2; STEP-1, STEP-3.

**6.1.10 Shared ordering component**
Handlers that change ordering (create, reorder, move, rename with position) call a shared ordering component rather than computing order inline.
Refs: U3, E2, E7, E18, E21, E22; STEP-1, STEP-2, STEP-5, STEP-6, STEP-7.

**6.1.11 Read repositories apply canonical ORDER BY**
Read-side repositories explicitly order screens by `screen_order` and questions by `question_order`.
Refs: U4, S1, S2; STEP-1, STEP-2, STEP-5, STEP-6 (downstream reads).

**6.1.12 Visibility authoring stored-only**
The authoring module persists `parent_question_id` and `visible_if_value` but does not implement runtime visibility evaluation logic.
Refs: U6, E25; outputs.question.parent_question_id, outputs.question.visible_if_value; STEP-8, STEP-9.

**6.1.13 Equality-only rule validation**
The visibility-rule validator restricts comparisons to equality against the parent’s canonical value (no ranges, regex, or multi-field logic).
Refs: U6, N5; STEP-8.

**6.1.14 Move handler updates two collections**
The move-question handler submits reindex operations for both the source and target screens.
Refs: E21, E22, E23; STEP-7.

**6.1.15 Response projection is single-entity**
Write responses project only the affected entity object (`outputs.screen` or `outputs.question`) rather than returning full collections.
Refs: outputs.screen, outputs.question; E4, E12, E20, E24; STEP-1, STEP-3, STEP-5, STEP-7.

**6.1.16 ETags container keys limited to affected entities**
When present, `outputs.etags` contains keys only for entities changed by the operation (question, screen, questionnaire).
Refs: outputs.etags.*; U5, E5, E9, E13, E14, E17, E20, E24, E28; STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-7, STEP-9.

**6.1.17 Visibility fields are nullable on clear**
Clearing a visibility rule sets `parent_question_id` and `visible_if_value` to null in storage and response.
Refs: E25; outputs.question.parent_question_id, outputs.question.visible_if_value; STEP-9.

**6.1.18 Screen reorder uses backend-authoritative sequence**
Rename/reposition logic does not persist client-proposed positions directly; it defers to the shared ordering component for final positions.
Refs: U3, E7, E8; STEP-2.

**6.1.19 Question reorder uses backend-authoritative sequence**
Reorder logic does not persist client-proposed `question_order` directly; it defers to the shared ordering component for final positions.
Refs: U3, E18, E19; STEP-5.

**6.1.20 Move result includes new `screen_id` and `question_order`**
Move responses include the updated `screen_id` and the new `question_order` for the moved question.
Refs: E24; outputs.question.screen_id, outputs.question.question_order; STEP-7.

### 6.2 Happy Path Contractual Acceptance Criteria

**6.2.1.1 Create screen returns screen payload**
Given an author submits a valid create-screen request, When the system creates the screen, Then the response includes outputs.screen with screen_id, title, and screen_order.
Reference: E1, E4; outputs.screen, outputs.screen.screen_id, outputs.screen.title, outputs.screen.screen_order.

**6.2.1.2 Create screen assigns backend order**
Given a create-screen request without a final position guarantee, When the system assigns order, Then outputs.screen.screen_order is the backend-assigned positive integer.
Reference: U1, U3, E2; outputs.screen.screen_order.

**6.2.1.3 Create screen returns ETags**
Given a successful create-screen operation, When the response is produced, Then outputs.etags.screen and outputs.etags.questionnaire are present.
Reference: U5, E5; outputs.etags.screen, outputs.etags.questionnaire.

**6.2.1.4 Rename screen returns updated title**
Given a valid rename-screen request, When the system updates the title, Then outputs.screen.title equals the new persisted title.
Reference: E6, E8; outputs.screen.title.

**6.2.1.5 Reposition screen returns final order**
Given a valid reposition-screen request with a proposed position, When the system recalculates ordering, Then outputs.screen.screen_order equals the final backend-assigned position.
Reference: U1, U3, E7, E8; outputs.screen.screen_order.

**6.2.1.6 Screen update returns ETags**
Given a successful rename or reposition, When the response is produced, Then outputs.etags.screen and outputs.etags.questionnaire are present.
Reference: U5, E9; outputs.etags.screen, outputs.etags.questionnaire.

**6.2.1.7 Create question returns question payload**
Given a valid create-question request, When the system creates the question scaffold, Then the response includes outputs.question with question_id, screen_id, question_text, and question_order.
Reference: E10, E12; outputs.question, outputs.question.question_id, outputs.question.screen_id, outputs.question.question_text, outputs.question.question_order.

**6.2.1.8 Create question leaves answer_kind unset**
Given a newly created question scaffold, When the response is produced, Then outputs.question.answer_kind is unset (null).
Reference: U7, E12; outputs.question.answer_kind.

**6.2.1.9 Create question returns ETags**
Given a successful create-question operation, When the response is produced, Then outputs.etags.question, outputs.etags.screen, and outputs.etags.questionnaire are present.
Reference: U5, E13, E14; outputs.etags.question, outputs.etags.screen, outputs.etags.questionnaire.

**6.2.1.10 First placeholder sets answer_kind**
Given an untyped question with its first placeholder allocated, When the system determines and persists the type, Then outputs.question.answer_kind contains the determined answer kind.
Reference: E26, E27, E28, S3; outputs.question.answer_kind.

**6.2.1.11 First placeholder update returns ETags**
Given a successful type assignment from placeholder allocation, When the response is produced, Then outputs.etags.question is present.
Reference: U5, E28; outputs.etags.question.

**6.2.1.12 Update question returns updated text**
Given a valid update-question-text request, When the system applies and persists the change, Then outputs.question.question_text equals the new persisted value.
Reference: E15, E16; outputs.question.question_text.

**6.2.1.13 Update question returns ETags**
Given a successful question-text update, When the response is produced, Then outputs.etags.question is present.
Reference: U5, E17; outputs.etags.question.

**6.2.1.14 Reorder question returns final order**
Given a valid reorder-question request with a proposed_question_order, When the system recalculates ordering, Then outputs.question.question_order equals the final backend-assigned position.
Reference: U2, U3, E18, E19; outputs.question.question_order.

**6.2.1.15 Reorder question returns ETags**
Given a successful reorder within a screen, When the response is produced, Then outputs.etags.question is present.
Reference: U5, E20; outputs.etags.question.

**6.2.1.16 Reorder screens returns final order**
Given a valid reorder-screens request with proposed positions, When the system recalculates ordering, Then outputs.screen.screen_order equals the final backend-assigned position.
Reference: U1, U3, E7, E8; outputs.screen.screen_order.

**6.2.1.17 Reorder screens returns ETags**
Given a successful screen reorder, When the response is produced, Then outputs.etags.screen is present.
Reference: U5, E9; outputs.etags.screen.

**6.2.1.18 Move question returns new screen_id**
Given a valid move-question request with a target screen, When the system moves the question, Then outputs.question.screen_id equals the target screen_id.
Reference: E21, E23; outputs.question.screen_id.

**6.2.1.19 Move question returns new order**
Given a valid move-question request, When the system assigns order in the target screen, Then outputs.question.question_order equals the new backend-assigned position.
Reference: U2, U3, E21, E23; outputs.question.question_order.

**6.2.1.20 Move question returns ETags (question)**
Given a successful move between screens, When the response is produced, Then outputs.etags.question is present.
Reference: U5, E24; outputs.etags.question.

**6.2.1.21 Move question returns ETags (screen)**
Given a successful move between screens, When the response is produced, Then outputs.etags.screen is present.
Reference: U5, E24; outputs.etags.screen.

**6.2.1.22 Set conditional parent returns parent id**
Given a compatible conditional parent is set for a question, When the system persists the link, Then outputs.question.parent_question_id equals the specified parent id.
Reference: U6; outputs.question.parent_question_id.

**6.2.1.23 Set conditional rule returns canonical value(s)**
Given a compatible visibility rule value or values is provided, When the system persists the rule, Then outputs.question.visible_if_value equals the canonical value(s).
Reference: U6; outputs.question.visible_if_value.

**6.2.1.24 Set conditional parent returns ETags**
Given a successful visibility-link set, When the response is produced, Then outputs.etags.question is present.
Reference: U5; outputs.etags.question.

**6.2.1.25 Clear conditional parent nulls parent id**
Given a valid clear-visibility request, When the system clears the link, Then outputs.question.parent_question_id is null.
Reference: E25; outputs.question.parent_question_id.

**6.2.1.26 Clear conditional parent nulls rule values**
Given a valid clear-visibility request, When the system clears the rule, Then outputs.question.visible_if_value is null.
Reference: E25; outputs.question.visible_if_value.

**6.2.1.27 Clear conditional parent returns ETags**
Given a successful clear-visibility operation, When the response is produced, Then outputs.etags.question is present.
Reference: U5, E25; outputs.etags.question.

**6.2.1.28 Deterministic read: screens order stable**
Given the stored state is unchanged across two consecutive reads, When screens are retrieved, Then their order as indicated by screen_order is identical across reads.
Reference: U4, S1; outputs.screen.screen_order.

**6.2.1.29 Deterministic read: questions order stable**
Given the stored state is unchanged across two consecutive reads, When questions are retrieved for a screen, Then their order as indicated by question_order is identical across reads.
Reference: U4, S2; outputs.question.question_order.

**6.2.1.30 Read screens sorted by screen_order**
Given a questionnaire with one or more screens, When screens are retrieved, Then the list is sorted by ascending screen_order.
Reference: S1; outputs.screen.screen_order.

**6.2.1.31 Read questions sorted by question_order**
Given a screen with one or more questions, When questions are retrieved, Then the list is sorted by ascending question_order.
Reference: S2; outputs.question.question_order.

**6.2.2.1 questionnaire_id missing**
Criterion: Given a request without questionnaire_id, When inputs are validated, Then the system returns PRE_QUESTIONNAIRE_ID_MISSING.
Error Mode: PRE_QUESTIONNAIRE_ID_MISSING
Reference: questionnaire_id

**6.2.2.2 questionnaire_id schema mismatch**
Criterion: Given a request where questionnaire_id does not match the declared schema, When inputs are validated, Then the system returns PRE_QUESTIONNAIRE_ID_SCHEMA_MISMATCH.
Error Mode: PRE_QUESTIONNAIRE_ID_SCHEMA_MISMATCH
Reference: questionnaire_id

**6.2.2.3 questionnaire_id not found**
Criterion: Given a request referencing a non-existent questionnaire_id, When inputs are validated, Then the system returns PRE_QUESTIONNAIRE_ID_NOT_FOUND.
Error Mode: PRE_QUESTIONNAIRE_ID_NOT_FOUND
Reference: questionnaire_id

**6.2.2.4 screen_id required when targeted**
Criterion: Given an operation that targets a specific screen without screen_id, When inputs are validated, Then the system returns PRE_SCREEN_ID_REQUIRED_WHEN_TARGETED.
Error Mode: PRE_SCREEN_ID_REQUIRED_WHEN_TARGETED
Reference: screen_id

**6.2.2.5 screen_id schema mismatch**
Criterion: Given screen_id does not match the declared schema, When inputs are validated, Then the system returns PRE_SCREEN_ID_SCHEMA_MISMATCH.
Error Mode: PRE_SCREEN_ID_SCHEMA_MISMATCH
Reference: screen_id

**6.2.2.6 screen_id not in questionnaire**
Criterion: Given screen_id does not belong to the referenced questionnaire, When inputs are validated, Then the system returns PRE_SCREEN_ID_NOT_IN_QUESTIONNAIRE.
Error Mode: PRE_SCREEN_ID_NOT_IN_QUESTIONNAIRE
Reference: screen_id

**6.2.2.7 target_screen_id required for move**
Criterion: Given a move request without target_screen_id, When inputs are validated, Then the system returns PRE_TARGET_SCREEN_ID_REQUIRED_FOR_MOVE.
Error Mode: PRE_TARGET_SCREEN_ID_REQUIRED_FOR_MOVE
Reference: target_screen_id

**6.2.2.8 target_screen_id schema mismatch**
Criterion: Given target_screen_id does not match the declared schema, When inputs are validated, Then the system returns PRE_TARGET_SCREEN_ID_SCHEMA_MISMATCH.
Error Mode: PRE_TARGET_SCREEN_ID_SCHEMA_MISMATCH
Reference: target_screen_id

**6.2.2.9 target_screen_id not in questionnaire**
Criterion: Given target_screen_id is not part of the same questionnaire, When inputs are validated, Then the system returns PRE_TARGET_SCREEN_ID_NOT_IN_QUESTIONNAIRE.
Error Mode: PRE_TARGET_SCREEN_ID_NOT_IN_QUESTIONNAIRE
Reference: target_screen_id

**6.2.2.10 question_id required for operation**
Criterion: Given a question operation without question_id, When inputs are validated, Then the system returns PRE_QUESTION_ID_REQUIRED_FOR_OPERATION.
Error Mode: PRE_QUESTION_ID_REQUIRED_FOR_OPERATION
Reference: question_id

**6.2.2.11 question_id schema mismatch**
Criterion: Given question_id does not match the declared schema, When inputs are validated, Then the system returns PRE_QUESTION_ID_SCHEMA_MISMATCH.
Error Mode: PRE_QUESTION_ID_SCHEMA_MISMATCH
Reference: question_id

**6.2.2.12 question_id not in questionnaire**
Criterion: Given question_id does not belong to the questionnaire, When inputs are validated, Then the system returns PRE_QUESTION_ID_NOT_IN_QUESTIONNAIRE.
Error Mode: PRE_QUESTION_ID_NOT_IN_QUESTIONNAIRE
Reference: question_id

**6.2.2.13 title required for create/rename**
Criterion: Given a create or rename screen request without title, When inputs are validated, Then the system returns PRE_TITLE_REQUIRED_FOR_CREATE_RENAME.
Error Mode: PRE_TITLE_REQUIRED_FOR_CREATE_RENAME
Reference: title

**6.2.2.14 title must be non-empty string**
Criterion: Given title is empty or whitespace, When inputs are validated, Then the system returns PRE_TITLE_NON_EMPTY_STRING.
Error Mode: PRE_TITLE_NON_EMPTY_STRING
Reference: title

**6.2.2.15 title not unique**
Criterion: Given title duplicates another screen’s title within the questionnaire, When inputs are validated, Then the system returns PRE_TITLE_NOT_UNIQUE.
Error Mode: PRE_TITLE_NOT_UNIQUE
Reference: title

**6.2.2.16 question_text required**
Criterion: Given a create or update question request without question_text, When inputs are validated, Then the system returns PRE_QUESTION_TEXT_REQUIRED_FOR_CREATE_UPDATE.
Error Mode: PRE_QUESTION_TEXT_REQUIRED_FOR_CREATE_UPDATE
Reference: question_text

**6.2.2.17 question_text must be non-empty**
Criterion: Given question_text is empty or whitespace, When inputs are validated, Then the system returns PRE_QUESTION_TEXT_NON_EMPTY_STRING.
Error Mode: PRE_QUESTION_TEXT_NON_EMPTY_STRING
Reference: question_text

**6.2.2.18 question_text schema mismatch**
Criterion: Given question_text does not match the declared schema, When inputs are validated, Then the system returns PRE_QUESTION_TEXT_SCHEMA_MISMATCH.
Error Mode: PRE_QUESTION_TEXT_SCHEMA_MISMATCH
Reference: question_text

**6.2.2.19 hint wrong type**
Criterion: Given hint is provided and not a string, When inputs are validated, Then the system returns PRE_HINT_NOT_STRING_WHEN_PROVIDED.
Error Mode: PRE_HINT_NOT_STRING_WHEN_PROVIDED
Reference: hint

**6.2.2.20 hint schema mismatch**
Criterion: Given hint is provided and violates the declared schema, When inputs are validated, Then the system returns PRE_HINT_SCHEMA_MISMATCH_WHEN_PROVIDED.
Error Mode: PRE_HINT_SCHEMA_MISMATCH_WHEN_PROVIDED
Reference: hint

**6.2.2.21 tooltip wrong type**
Criterion: Given tooltip is provided and not a string, When inputs are validated, Then the system returns PRE_TOOLTIP_NOT_STRING_WHEN_PROVIDED.
Error Mode: PRE_TOOLTIP_NOT_STRING_WHEN_PROVIDED
Reference: tooltip

**6.2.2.22 tooltip schema mismatch**
Criterion: Given tooltip is provided and violates the declared schema, When inputs are validated, Then the system returns PRE_TOOLTIP_SCHEMA_MISMATCH_WHEN_PROVIDED.
Error Mode: PRE_TOOLTIP_SCHEMA_MISMATCH_WHEN_PROVIDED
Reference: tooltip

**6.2.2.23 proposed_position not integer ≥1**
Criterion: Given proposed_position is not an integer ≥ 1, When inputs are validated, Then the system returns PRE_PROPOSED_POSITION_NOT_INTEGER_GE_1.
Error Mode: PRE_PROPOSED_POSITION_NOT_INTEGER_GE_1
Reference: proposed_position

**6.2.2.24 proposed_position exceeds max**
Criterion: Given proposed_position exceeds current screen count + 1, When inputs are validated, Then the system returns PRE_PROPOSED_POSITION_EXCEEDS_MAX.
Error Mode: PRE_PROPOSED_POSITION_EXCEEDS_MAX
Reference: proposed_position

**6.2.2.25 proposed_question_order not integer ≥1**
Criterion: Given proposed_question_order is not an integer ≥ 1, When inputs are validated, Then the system returns PRE_PROPOSED_QUESTION_ORDER_NOT_INT_GE_1.
Error Mode: PRE_PROPOSED_QUESTION_ORDER_NOT_INT_GE_1
Reference: proposed_question_order

**6.2.2.26 proposed_question_order exceeds max**
Criterion: Given proposed_question_order exceeds current question count + 1, When inputs are validated, Then the system returns PRE_PROPOSED_QUESTION_ORDER_EXCEEDS_MAX.
Error Mode: PRE_PROPOSED_QUESTION_ORDER_EXCEEDS_MAX
Reference: proposed_question_order

**6.2.2.27 parent_question_id required for rule**
Criterion: Given a visibility rule set request without parent_question_id, When inputs are validated, Then the system returns PRE_PARENT_QUESTION_ID_REQUIRED_FOR_RULE.
Error Mode: PRE_PARENT_QUESTION_ID_REQUIRED_FOR_RULE
Reference: parent_question_id

**6.2.2.28 parent_question_id schema mismatch**
Criterion: Given parent_question_id does not match the declared schema, When inputs are validated, Then the system returns PRE_PARENT_QUESTION_ID_SCHEMA_MISMATCH.
Error Mode: PRE_PARENT_QUESTION_ID_SCHEMA_MISMATCH
Reference: parent_question_id

**6.2.2.29 parent_question_id not found or self**
Criterion: Given parent_question_id does not resolve or equals question_id, When inputs are validated, Then the system returns PRE_PARENT_QUESTION_ID_NOT_FOUND_OR_SELF.
Error Mode: PRE_PARENT_QUESTION_ID_NOT_FOUND_OR_SELF
Reference: parent_question_id

**6.2.2.30 visible_if_value required for rule**
Criterion: Given a visibility rule set request without visible_if_value, When inputs are validated, Then the system returns PRE_VISIBLE_IF_VALUE_REQUIRED_FOR_RULE.
Error Mode: PRE_VISIBLE_IF_VALUE_REQUIRED_FOR_RULE
Reference: visible_if_value

**6.2.2.31 visible_if_value invalid type**
Criterion: Given visible_if_value is neither a string nor list of strings, When inputs are validated, Then the system returns PRE_VISIBLE_IF_VALUE_INVALID_TYPE.
Error Mode: PRE_VISIBLE_IF_VALUE_INVALID_TYPE
Reference: visible_if_value

**6.2.2.32 visible_if_value out of domain**
Criterion: Given visible_if_value contains values outside the parent’s canonical domain, When inputs are validated, Then the system returns PRE_VISIBLE_IF_VALUE_OUT_OF_DOMAIN.
Error Mode: PRE_VISIBLE_IF_VALUE_OUT_OF_DOMAIN
Reference: visible_if_value

**6.2.2.33 idempotency_key not opaque**
Criterion: Given request_headers.idempotency_key is provided and not opaque, When inputs are validated, Then the system returns PRE_REQUEST_HEADERS_IDEMPOTENCY_KEY_NOT_OPAQUE.
Error Mode: PRE_REQUEST_HEADERS_IDEMPOTENCY_KEY_NOT_OPAQUE
Reference: request_headers.idempotency_key

**6.2.2.34 idempotency_key schema mismatch**
Criterion: Given request_headers.idempotency_key violates the declared schema, When inputs are validated, Then the system returns PRE_REQUEST_HEADERS_IDEMPOTENCY_KEY_SCHEMA_MISMATCH.
Error Mode: PRE_REQUEST_HEADERS_IDEMPOTENCY_KEY_SCHEMA_MISMATCH
Reference: request_headers.idempotency_key

**6.2.2.35 If-Match required on PATCH**
Criterion: Given a PATCH request without request_headers.if_match, When inputs are validated, Then the system returns PRE_REQUEST_HEADERS_IF_MATCH_REQUIRED_ON_PATCH.
Error Mode: PRE_REQUEST_HEADERS_IF_MATCH_REQUIRED_ON_PATCH
Reference: request_headers.if_match

**6.2.2.36 If-Match not latest ETag**
Criterion: Given request_headers.if_match does not equal the latest entity ETag, When inputs are validated, Then the system returns PRE_REQUEST_HEADERS_IF_MATCH_NOT_LATEST_ETAG.
Error Mode: PRE_REQUEST_HEADERS_IF_MATCH_NOT_LATEST_ETAG
Reference: request_headers.if_match

**6.2.2.37 If-Match schema mismatch**
Criterion: Given request_headers.if_match violates the declared schema, When inputs are validated, Then the system returns PRE_REQUEST_HEADERS_IF_MATCH_SCHEMA_MISMATCH.
Error Mode: PRE_REQUEST_HEADERS_IF_MATCH_SCHEMA_MISMATCH
Reference: request_headers.if_match

**6.2.2.38 screens[].screen_id unreadable**
Criterion: Given an acquired screens[].screen_id resource is missing or unreadable, When inputs are prepared, Then the system returns PRE_SCREENS_SCREEN_ID_RESOURCE_UNREADABLE.
Error Mode: PRE_SCREENS_SCREEN_ID_RESOURCE_UNREADABLE
Reference: screens[].screen_id

**6.2.2.39 screens[].screen_id not found**
Criterion: Given screens[].screen_id cannot be resolved to an existing screen, When inputs are prepared, Then the system returns PRE_SCREENS_SCREEN_ID_NOT_FOUND.
Error Mode: PRE_SCREENS_SCREEN_ID_NOT_FOUND
Reference: screens[].screen_id

**6.2.2.40 screens[].screen_id schema mismatch**
Criterion: Given screens[].screen_id violates the declared schema, When inputs are prepared, Then the system returns PRE_SCREENS_SCREEN_ID_SCHEMA_MISMATCH.
Error Mode: PRE_SCREENS_SCREEN_ID_SCHEMA_MISMATCH
Reference: screens[].screen_id

**6.2.2.41 screens[].screen_order unreadable**
Criterion: Given screens[].screen_order resource is missing or unreadable, When inputs are prepared, Then the system returns PRE_SCREENS_SCREEN_ORDER_RESOURCE_UNREADABLE.
Error Mode: PRE_SCREENS_SCREEN_ORDER_RESOURCE_UNREADABLE
Reference: screens[].screen_order

**6.2.2.42 screens[].screen_order not integer ≥1**
Criterion: Given screens[].screen_order is not an integer ≥ 1, When inputs are prepared, Then the system returns PRE_SCREENS_SCREEN_ORDER_NOT_INTEGER_GE_1.
Error Mode: PRE_SCREENS_SCREEN_ORDER_NOT_INTEGER_GE_1
Reference: screens[].screen_order

**6.2.2.43 screens[].screen_order schema mismatch**
Criterion: Given screens[].screen_order violates the declared schema, When inputs are prepared, Then the system returns PRE_SCREENS_SCREEN_ORDER_SCHEMA_MISMATCH.
Error Mode: PRE_SCREENS_SCREEN_ORDER_SCHEMA_MISMATCH
Reference: screens[].screen_order

**6.2.2.44 questions[].question_id unreadable**
Criterion: Given questions[].question_id resource is missing or unreadable, When inputs are prepared, Then the system returns PRE_QUESTIONS_QUESTION_ID_RESOURCE_UNREADABLE.
Error Mode: PRE_QUESTIONS_QUESTION_ID_RESOURCE_UNREADABLE
Reference: questions[].question_id

**6.2.2.45 questions[].question_id not found**
Criterion: Given questions[].question_id does not resolve to an existing question, When inputs are prepared, Then the system returns PRE_QUESTIONS_QUESTION_ID_NOT_FOUND.
Error Mode: PRE_QUESTIONS_QUESTION_ID_NOT_FOUND
Reference: questions[].question_id

**6.2.2.46 questions[].question_id schema mismatch**
Criterion: Given questions[].question_id violates the declared schema, When inputs are prepared, Then the system returns PRE_QUESTIONS_QUESTION_ID_SCHEMA_MISMATCH.
Error Mode: PRE_QUESTIONS_QUESTION_ID_SCHEMA_MISMATCH
Reference: questions[].question_id

**6.2.2.47 questions[].question_order unreadable**
Criterion: Given questions[].question_order resource is missing or unreadable, When inputs are prepared, Then the system returns PRE_QUESTIONS_QUESTION_ORDER_RESOURCE_UNREADABLE.
Error Mode: PRE_QUESTIONS_QUESTION_ORDER_RESOURCE_UNREADABLE
Reference: questions[].question_order

**6.2.2.48 questions[].question_order not integer ≥1**
Criterion: Given questions[].question_order is not an integer ≥ 1, When inputs are prepared, Then the system returns PRE_QUESTIONS_QUESTION_ORDER_NOT_INTEGER_GE_1.
Error Mode: PRE_QUESTIONS_QUESTION_ORDER_NOT_INTEGER_GE_1
Reference: questions[].question_order

**6.2.2.49 questions[].question_order schema mismatch**
Criterion: Given questions[].question_order violates the declared schema, When inputs are prepared, Then the system returns PRE_QUESTIONS_QUESTION_ORDER_SCHEMA_MISMATCH.
Error Mode: PRE_QUESTIONS_QUESTION_ORDER_SCHEMA_MISMATCH
Reference: questions[].question_order

**6.2.2.50 parent_question.question_id unreadable**
Criterion: Given parent_question.question_id resource is missing or unreadable, When inputs are prepared, Then the system returns PRE_PARENT_QUESTION_QUESTION_ID_RESOURCE_UNREADABLE.
Error Mode: PRE_PARENT_QUESTION_QUESTION_ID_RESOURCE_UNREADABLE
Reference: parent_question.question_id

**6.2.2.51 parent_question.question_id mismatch**
Criterion: Given parent_question.question_id does not match the provided parent_question_id, When inputs are prepared, Then the system returns PRE_PARENT_QUESTION_QUESTION_ID_MISMATCH.
Error Mode: PRE_PARENT_QUESTION_QUESTION_ID_MISMATCH
Reference: parent_question.question_id

**6.2.2.52 parent_question.question_id schema mismatch**
Criterion: Given parent_question.question_id violates the declared schema, When inputs are prepared, Then the system returns PRE_PARENT_QUESTION_QUESTION_ID_SCHEMA_MISMATCH.
Error Mode: PRE_PARENT_QUESTION_QUESTION_ID_SCHEMA_MISMATCH
Reference: parent_question.question_id

**6.2.2.53 parent_question.answer_kind unreadable**
Criterion: Given parent_question.answer_kind resource is missing or unreadable, When inputs are prepared, Then the system returns PRE_PARENT_QUESTION_ANSWER_KIND_RESOURCE_UNREADABLE.
Error Mode: PRE_PARENT_QUESTION_ANSWER_KIND_RESOURCE_UNREADABLE
Reference: parent_question.answer_kind

**6.2.2.54 parent_question.answer_kind unsupported**
Criterion: Given parent_question.answer_kind is not a supported answer kind, When inputs are prepared, Then the system returns PRE_PARENT_QUESTION_ANSWER_KIND_UNSUPPORTED.
Error Mode: PRE_PARENT_QUESTION_ANSWER_KIND_UNSUPPORTED
Reference: parent_question.answer_kind

**6.2.2.55 parent_question.answer_kind schema mismatch**
Criterion: Given parent_question.answer_kind violates the declared schema, When inputs are prepared, Then the system returns PRE_PARENT_QUESTION_ANSWER_KIND_SCHEMA_MISMATCH.
Error Mode: PRE_PARENT_QUESTION_ANSWER_KIND_SCHEMA_MISMATCH
Reference: parent_question.answer_kind

**6.2.2.56 placeholder_id provider call failed**
Criterion: Given the placeholder allocation call errors, When its result is consumed, Then the system returns PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_CALL_FAILED.
Error Mode: PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_CALL_FAILED
Reference: placeholder_allocation_result.placeholder_id

**6.2.2.57 placeholder_id schema mismatch**
Criterion: Given placeholder_allocation_result.placeholder_id violates the provider’s schema, When its result is consumed, Then the system returns PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_SCHEMA_MISMATCH.
Error Mode: PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_SCHEMA_MISMATCH
Reference: placeholder_allocation_result.placeholder_id

**6.2.2.58 inferred_answer_kind provider call failed**
Criterion: Given the provider call for inferred_answer_kind errors, When its result is consumed, Then the system returns PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_CALL_FAILED.
Error Mode: PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_CALL_FAILED
Reference: placeholder_allocation_result.inferred_answer_kind

**6.2.2.59 inferred_answer_kind schema mismatch**
Criterion: Given inferred_answer_kind violates the provider’s return schema, When its result is consumed, Then the system returns PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_SCHEMA_MISMATCH.
Error Mode: PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_SCHEMA_MISMATCH
Reference: placeholder_allocation_result.inferred_answer_kind

**6.2.2.60 Screen create persist failed**
Criterion: Given a valid create-screen request, When persisting the screen fails, Then the system returns RUN_SCREEN_CREATE_PERSIST_FAILED.
Error Mode: RUN_SCREEN_CREATE_PERSIST_FAILED
Reference: outputs.screen

**6.2.2.61 Screen order assignment failed**
Criterion: Given a screen has been created, When assigning final screen_order fails, Then the system returns RUN_SCREEN_ORDER_ASSIGN_FAILED.
Error Mode: RUN_SCREEN_ORDER_ASSIGN_FAILED
Reference: outputs.screen.screen_order

**6.2.2.62 Screen serialization failed**
Criterion: Given a screen is created, When constructing the response payload fails, Then the system returns RUN_SCREEN_SERIALIZATION_FAILED.
Error Mode: RUN_SCREEN_SERIALIZATION_FAILED
Reference: outputs.screen

**6.2.2.63 Screen ETag generation failed**
Criterion: Given a screen is created, When generating or returning ETags fails, Then the system returns RUN_SCREEN_ETAG_GEN_FAILED.
Error Mode: RUN_SCREEN_ETAG_GEN_FAILED
Reference: outputs.etags.screen, outputs.etags.questionnaire

**6.2.2.64 Screen update persist failed**
Criterion: Given a rename or reposition request, When persisting changes fails, Then the system returns RUN_SCREEN_UPDATE_PERSIST_FAILED.
Error Mode: RUN_SCREEN_UPDATE_PERSIST_FAILED
Reference: outputs.screen

**6.2.2.65 Screen reindex failed**
Criterion: Given a screen is being repositioned, When recalculating contiguous order fails, Then the system returns RUN_SCREEN_REINDEX_FAILED.
Error Mode: RUN_SCREEN_REINDEX_FAILED
Reference: outputs.screen.screen_order

**6.2.2.66 Screen ETag update failed**
Criterion: Given a screen is updated, When returning updated ETags fails, Then the system returns RUN_SCREEN_ETAG_UPDATE_FAILED.
Error Mode: RUN_SCREEN_ETAG_UPDATE_FAILED
Reference: outputs.etags.screen

**6.2.2.67 Question scaffold create failed**
Criterion: Given a create-question request, When creating the scaffold fails, Then the system returns RUN_QUESTION_SCAFFOLD_CREATE_FAILED.
Error Mode: RUN_QUESTION_SCAFFOLD_CREATE_FAILED
Reference: outputs.question

**6.2.2.68 Initial question_order assignment failed**
Criterion: Given a question scaffold is created, When assigning initial question_order fails, Then the system returns RUN_QUESTION_ORDER_ASSIGN_FAILED.
Error Mode: RUN_QUESTION_ORDER_ASSIGN_FAILED
Reference: outputs.question.question_order

**6.2.2.69 Question persist failed**
Criterion: Given a question scaffold exists, When persisting the question fails, Then the system returns RUN_QUESTION_PERSIST_FAILED.
Error Mode: RUN_QUESTION_PERSIST_FAILED
Reference: outputs.question

**6.2.2.70 Question serialization failed**
Criterion: Given a question is created, When constructing the response fails, Then the system returns RUN_QUESTION_SERIALIZATION_FAILED.
Error Mode: RUN_QUESTION_SERIALIZATION_FAILED
Reference: outputs.question

**6.2.2.71 Question ETag generation failed**
Criterion: Given a question is created, When generating or returning ETags fails, Then the system returns RUN_QUESTION_ETAG_GEN_FAILED.
Error Mode: RUN_QUESTION_ETAG_GEN_FAILED
Reference: outputs.etags.question, outputs.etags.screen, outputs.etags.questionnaire

**6.2.2.72 Determine answer_kind failed**
Criterion: Given the first placeholder is allocated, When determining answer_kind fails, Then the system returns RUN_DETERMINE_ANSWER_KIND_FAILED.
Error Mode: RUN_DETERMINE_ANSWER_KIND_FAILED
Reference: outputs.question.answer_kind

**6.2.2.73 Persist answer_kind failed**
Criterion: Given an answer_kind has been determined, When persisting it fails, Then the system returns RUN_PERSIST_ANSWER_KIND_FAILED.
Error Mode: RUN_PERSIST_ANSWER_KIND_FAILED
Reference: outputs.question.answer_kind

**6.2.2.74 Typed question return failed**
Criterion: Given answer_kind has been persisted, When returning the updated question fails, Then the system returns RUN_TYPED_QUESTION_RETURN_FAILED.
Error Mode: RUN_TYPED_QUESTION_RETURN_FAILED
Reference: outputs.question

**6.2.2.75 Apply field updates failed**
Criterion: Given a question update request, When applying field changes fails, Then the system returns RUN_UPDATE_FIELDS_APPLY_FAILED.
Error Mode: RUN_UPDATE_FIELDS_APPLY_FAILED
Reference: outputs.question

**6.2.2.76 Question update persist failed**
Criterion: Given fields are updated, When persisting the question fails, Then the system returns RUN_QUESTION_UPDATE_PERSIST_FAILED.
Error Mode: RUN_QUESTION_UPDATE_PERSIST_FAILED
Reference: outputs.question

**6.2.2.77 Question ETag update failed**
Criterion: Given a question is updated, When returning updated ETags fails, Then the system returns RUN_QUESTION_ETAG_UPDATE_FAILED.
Error Mode: RUN_QUESTION_ETAG_UPDATE_FAILED
Reference: outputs.etags.question

**6.2.2.78 Question reindex failed**
Criterion: Given a reorder within a screen, When recalculating contiguous order fails, Then the system returns RUN_QUESTION_REINDEX_FAILED.
Error Mode: RUN_QUESTION_REINDEX_FAILED
Reference: outputs.question.question_order

**6.2.2.79 Reorder persist failed**
Criterion: Given a reorder within a screen, When persisting the updated sequence fails, Then the system returns RUN_REORDER_PERSIST_FAILED.
Error Mode: RUN_REORDER_PERSIST_FAILED
Reference: outputs.question

**6.2.2.80 Reorder result return failed**
Criterion: Given a reorder is completed, When returning updated ETags and question_order fails, Then the system returns RUN_REORDER_RESULT_RETURN_FAILED.
Error Mode: RUN_REORDER_RESULT_RETURN_FAILED
Reference: outputs.etags.question, outputs.question.question_order

**6.2.2.81 Screen reorder persist failed**
Criterion: Given a screen reorder, When persisting the new sequence fails, Then the system returns RUN_SCREEN_REORDER_PERSIST_FAILED.
Error Mode: RUN_SCREEN_REORDER_PERSIST_FAILED
Reference: outputs.screen

**6.2.2.82 Move assign target order failed**
Criterion: Given a move to another screen, When assigning the new question_order in target fails, Then the system returns RUN_MOVE_ASSIGN_TARGET_ORDER_FAILED.
Error Mode: RUN_MOVE_ASSIGN_TARGET_ORDER_FAILED
Reference: outputs.question.question_order

**6.2.2.83 Move reindex source failed**
Criterion: Given a question is moved, When reindexing the source screen fails, Then the system returns RUN_MOVE_REINDEX_SOURCE_FAILED.
Error Mode: RUN_MOVE_REINDEX_SOURCE_FAILED
Reference: outputs.question.question_order

**6.2.2.84 Move persist failed**
Criterion: Given a question is moved, When persisting changes to both screens fails, Then the system returns RUN_MOVE_PERSIST_FAILED.
Error Mode: RUN_MOVE_PERSIST_FAILED
Reference: outputs.question

**6.2.2.85 Move result return failed**
Criterion: Given a question is moved, When returning updated ETags and target question_order fails, Then the system returns RUN_MOVE_RESULT_RETURN_FAILED.
Error Mode: RUN_MOVE_RESULT_RETURN_FAILED
Reference: outputs.etags.question, outputs.question.question_order

**6.2.2.86 Set visibility link persist failed**
Criterion: Given a set-visibility request, When persisting parent link fails, Then the system returns RUN_SET_VISIBILITY_LINK_PERSIST_FAILED.
Error Mode: RUN_SET_VISIBILITY_LINK_PERSIST_FAILED
Reference: outputs.question.parent_question_id, outputs.question.visible_if_value

**6.2.2.87 Clear visibility persist failed**
Criterion: Given a clear-visibility request, When clearing parent and rule fails, Then the system returns RUN_CLEAR_VISIBILITY_PERSIST_FAILED.
Error Mode: RUN_CLEAR_VISIBILITY_PERSIST_FAILED
Reference: outputs.question.parent_question_id, outputs.question.visible_if_value

**6.2.2.88 Clear rule return failed**
Criterion: Given visibility is cleared, When returning updated ETags fails, Then the system returns RUN_CLEAR_RULE_RETURN_FAILED.
Error Mode: RUN_CLEAR_RULE_RETURN_FAILED
Reference: outputs.etags.question

**6.2.2.89 outputs.screen context mismatch**
Criterion: Given a screen operation or non-screen operation response, When the outputs.screen presence does not match context, Then the system returns POST_OUTPUTS_SCREEN_CONTEXT_MISMATCH.
Error Mode: POST_OUTPUTS_SCREEN_CONTEXT_MISMATCH
Reference: outputs.screen

**6.2.2.90 outputs.screen keys incomplete**
Criterion: Given a screen response, When required keys are missing, Then the system returns POST_OUTPUTS_SCREEN_KEYS_INCOMPLETE.
Error Mode: POST_OUTPUTS_SCREEN_KEYS_INCOMPLETE
Reference: outputs.screen

**6.2.2.91 outputs.screen schema invalid**
Criterion: Given a screen response, When the object violates its schema, Then the system returns POST_OUTPUTS_SCREEN_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_SCREEN_SCHEMA_INVALID
Reference: outputs.screen

**6.2.2.92 screen_id missing**
Criterion: Given outputs.screen is present, When screen_id is absent, Then the system returns POST_OUTPUTS_SCREEN_SCREEN_ID_MISSING.
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ID_MISSING
Reference: outputs.screen.screen_id

**6.2.2.93 screen_id schema invalid**
Criterion: Given outputs.screen.screen_id exists, When it violates schema, Then the system returns POST_OUTPUTS_SCREEN_SCREEN_ID_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ID_SCHEMA_INVALID
Reference: outputs.screen.screen_id

**6.2.2.94 screen_id mutated**
Criterion: Given a screen’s lifetime, When outputs.screen.screen_id is not immutable, Then the system returns POST_OUTPUTS_SCREEN_SCREEN_ID_MUTATED.
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ID_MUTATED
Reference: outputs.screen.screen_id

**6.2.2.95 screen title missing**
Criterion: Given outputs.screen is present, When title is absent, Then the system returns POST_OUTPUTS_SCREEN_TITLE_MISSING.
Error Mode: POST_OUTPUTS_SCREEN_TITLE_MISSING
Reference: outputs.screen.title

**6.2.2.96 screen title schema invalid**
Criterion: Given outputs.screen.title exists, When it violates schema, Then the system returns POST_OUTPUTS_SCREEN_TITLE_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_SCREEN_TITLE_SCHEMA_INVALID
Reference: outputs.screen.title

**6.2.2.97 screen title not latest**
Criterion: Given a screen update occurred, When outputs.screen.title is not the latest persisted value, Then the system returns POST_OUTPUTS_SCREEN_TITLE_NOT_LATEST.
Error Mode: POST_OUTPUTS_SCREEN_TITLE_NOT_LATEST
Reference: outputs.screen.title

**6.2.2.98 screen_order missing**
Criterion: Given outputs.screen is present, When screen_order is absent, Then the system returns POST_OUTPUTS_SCREEN_SCREEN_ORDER_MISSING.
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ORDER_MISSING
Reference: outputs.screen.screen_order

**6.2.2.99 screen_order schema invalid**
Criterion: Given outputs.screen.screen_order exists, When it violates schema, Then the system returns POST_OUTPUTS_SCREEN_SCREEN_ORDER_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ORDER_SCHEMA_INVALID
Reference: outputs.screen.screen_order

**6.2.2.100 screen_order not positive**
Criterion: Given outputs.screen.screen_order exists, When it is not a positive integer, Then the system returns POST_OUTPUTS_SCREEN_SCREEN_ORDER_NOT_POSITIVE.
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ORDER_NOT_POSITIVE
Reference: outputs.screen.screen_order

**6.2.2.101 screen_order sequence broken**
Criterion: Given screens are ordered, When the sequence is not contiguous 1-based, Then the system returns POST_OUTPUTS_SCREEN_SCREEN_ORDER_SEQUENCE_BROKEN.
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ORDER_SEQUENCE_BROKEN
Reference: outputs.screen.screen_order

**6.2.2.102 outputs.question context mismatch**
Criterion: Given a question operation or non-question operation response, When outputs.question presence does not match context, Then the system returns POST_OUTPUTS_QUESTION_CONTEXT_MISMATCH.
Error Mode: POST_OUTPUTS_QUESTION_CONTEXT_MISMATCH
Reference: outputs.question

**6.2.2.103 outputs.question keys incomplete**
Criterion: Given a question response, When required keys are missing, Then the system returns POST_OUTPUTS_QUESTION_KEYS_INCOMPLETE.
Error Mode: POST_OUTPUTS_QUESTION_KEYS_INCOMPLETE
Reference: outputs.question

**6.2.2.104 outputs.question schema invalid**
Criterion: Given a question response, When the object violates its schema, Then the system returns POST_OUTPUTS_QUESTION_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_QUESTION_SCHEMA_INVALID
Reference: outputs.question

**6.2.2.105 question_id missing**
Criterion: Given outputs.question is present, When question_id is absent, Then the system returns POST_OUTPUTS_QUESTION_QUESTION_ID_MISSING.
Error Mode: POST_OUTPUTS_QUESTION_QUESTION_ID_MISSING
Reference: outputs.question.question_id

**6.2.2.106 question_id schema invalid**
Criterion: Given outputs.question.question_id exists, When it violates schema, Then the system returns POST_OUTPUTS_QUESTION_QUESTION_ID_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_QUESTION_QUESTION_ID_SCHEMA_INVALID
Reference: outputs.question.question_id

**6.2.2.107 question_id mutated**
Criterion: Given a question’s lifetime, When outputs.question.question_id is not immutable, Then the system returns POST_OUTPUTS_QUESTION_QUESTION_ID_MUTATED.
Error Mode: POST_OUTPUTS_QUESTION_QUESTION_ID_MUTATED
Reference: outputs.question.question_id

**6.2.2.108 screen_id missing in question**
Criterion: Given outputs.question is present, When screen_id is absent, Then the system returns POST_OUTPUTS_QUESTION_SCREEN_ID_MISSING.
Error Mode: POST_OUTPUTS_QUESTION_SCREEN_ID_MISSING
Reference: outputs.question.screen_id

**6.2.2.109 screen_id schema invalid in question**
Criterion: Given outputs.question.screen_id exists, When it violates schema, Then the system returns POST_OUTPUTS_QUESTION_SCREEN_ID_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_QUESTION_SCREEN_ID_SCHEMA_INVALID
Reference: outputs.question.screen_id

**6.2.2.110 screen_id not latest**
Criterion: Given a question move occurred, When outputs.question.screen_id does not reflect the latest persisted screen assignment, Then the system returns POST_OUTPUTS_QUESTION_SCREEN_ID_NOT_LATEST.
Error Mode: POST_OUTPUTS_QUESTION_SCREEN_ID_NOT_LATEST
Reference: outputs.question.screen_id

**6.2.2.111 question_text missing**
Criterion: Given outputs.question is present, When question_text is absent, Then the system returns POST_OUTPUTS_QUESTION_TEXT_MISSING.
Error Mode: POST_OUTPUTS_QUESTION_TEXT_MISSING
Reference: outputs.question.question_text

**6.2.2.112 question_text schema invalid**
Criterion: Given outputs.question.question_text exists, When it violates schema, Then the system returns POST_OUTPUTS_QUESTION_TEXT_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_QUESTION_TEXT_SCHEMA_INVALID
Reference: outputs.question.question_text

**6.2.2.113 question_text not latest**
Criterion: Given a question text update occurred, When outputs.question.question_text is not the latest value, Then the system returns POST_OUTPUTS_QUESTION_TEXT_NOT_LATEST.
Error Mode: POST_OUTPUTS_QUESTION_TEXT_NOT_LATEST
Reference: outputs.question.question_text

**6.2.2.114 answer_kind schema invalid**
Criterion: Given outputs.question.answer_kind is present, When it violates schema, Then the system returns POST_OUTPUTS_QUESTION_ANSWER_KIND_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_QUESTION_ANSWER_KIND_SCHEMA_INVALID
Reference: outputs.question.answer_kind

**6.2.2.115 question_order missing**
Criterion: Given outputs.question is present, When question_order is absent, Then the system returns POST_OUTPUTS_QUESTION_ORDER_MISSING.
Error Mode: POST_OUTPUTS_QUESTION_ORDER_MISSING
Reference: outputs.question.question_order

**6.2.2.116 question_order schema invalid**
Criterion: Given outputs.question.question_order exists, When it violates schema, Then the system returns POST_OUTPUTS_QUESTION_ORDER_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_QUESTION_ORDER_SCHEMA_INVALID
Reference: outputs.question.question_order

**6.2.2.117 question_order not positive**
Criterion: Given outputs.question.question_order exists, When it is not a positive integer, Then the system returns POST_OUTPUTS_QUESTION_ORDER_NOT_POSITIVE.
Error Mode: POST_OUTPUTS_QUESTION_ORDER_NOT_POSITIVE
Reference: outputs.question.question_order

**6.2.2.118 question_order sequence broken**
Criterion: Given questions are ordered within a screen, When the sequence is not contiguous 1-based, Then the system returns POST_OUTPUTS_QUESTION_ORDER_SEQUENCE_BROKEN.
Error Mode: POST_OUTPUTS_QUESTION_ORDER_SEQUENCE_BROKEN
Reference: outputs.question.question_order

**6.2.2.119 parent_question_id schema invalid**
Criterion: Given outputs.question.parent_question_id is present, When it violates schema, Then the system returns POST_OUTPUTS_PARENT_QUESTION_ID_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_PARENT_QUESTION_ID_SCHEMA_INVALID
Reference: outputs.question.parent_question_id

**6.2.2.120 parent_question_id not null when cleared**
Criterion: Given a visibility rule was cleared, When outputs.question.parent_question_id is not null, Then the system returns POST_OUTPUTS_PARENT_QUESTION_ID_NOT_NULL_WHEN_CLEARED.
Error Mode: POST_OUTPUTS_PARENT_QUESTION_ID_NOT_NULL_WHEN_CLEARED
Reference: outputs.question.parent_question_id

**6.2.2.121 visible_if_value schema invalid**
Criterion: Given outputs.question.visible_if_value is present, When it violates schema, Then the system returns POST_OUTPUTS_VISIBLE_IF_VALUE_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_VISIBLE_IF_VALUE_SCHEMA_INVALID
Reference: outputs.question.visible_if_value

**6.2.2.122 visible_if_value not null when cleared**
Criterion: Given a visibility rule was cleared, When outputs.question.visible_if_value is not null, Then the system returns POST_OUTPUTS_VISIBLE_IF_VALUE_NOT_NULL_WHEN_CLEARED.
Error Mode: POST_OUTPUTS_VISIBLE_IF_VALUE_NOT_NULL_WHEN_CLEARED
Reference: outputs.question.visible_if_value

**6.2.2.123 visible_if_value domain mismatch**
Criterion: Given outputs.question.visible_if_value is present, When values are not instances of the parent’s canonical domain, Then the system returns POST_OUTPUTS_VISIBLE_IF_VALUE_DOMAIN_MISMATCH.
Error Mode: POST_OUTPUTS_VISIBLE_IF_VALUE_DOMAIN_MISMATCH
Reference: outputs.question.visible_if_value

**6.2.2.124 etags missing for write**
Criterion: Given a successful write, When outputs.etags is absent, Then the system returns POST_OUTPUTS_ETAGS_MISSING_FOR_WRITE.
Error Mode: POST_OUTPUTS_ETAGS_MISSING_FOR_WRITE
Reference: outputs.etags

**6.2.2.125 etags keys incomplete**
Criterion: Given outputs.etags is present, When it does not contain only applicable keys, Then the system returns POST_OUTPUTS_ETAGS_KEYS_INCOMPLETE.
Error Mode: POST_OUTPUTS_ETAGS_KEYS_INCOMPLETE
Reference: outputs.etags

**6.2.2.126 etags schema invalid**
Criterion: Given outputs.etags is present, When it violates schema, Then the system returns POST_OUTPUTS_ETAGS_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_ETAGS_SCHEMA_INVALID
Reference: outputs.etags

**6.2.2.127 etags include unaffected entities**
Criterion: Given outputs.etags is present, When it includes entities not affected by the operation, Then the system returns POST_OUTPUTS_ETAGS_KEYS_INCLUDE_UNAFFECTED.
Error Mode: POST_OUTPUTS_ETAGS_KEYS_INCLUDE_UNAFFECTED
Reference: outputs.etags

**6.2.2.128 question etag schema invalid**
Criterion: Given outputs.etags.question is present, When it violates schema, Then the system returns POST_OUTPUTS_ETAGS_QUESTION_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_ETAGS_QUESTION_SCHEMA_INVALID
Reference: outputs.etags.question

**6.2.2.129 question etag empty**
Criterion: Given outputs.etags.question is present, When it is empty or not opaque, Then the system returns POST_OUTPUTS_ETAGS_QUESTION_EMPTY.
Error Mode: POST_OUTPUTS_ETAGS_QUESTION_EMPTY
Reference: outputs.etags.question

**6.2.2.130 question etag not changed on update**
Criterion: Given a question’s persisted state changed, When outputs.etags.question did not change, Then the system returns POST_OUTPUTS_ETAGS_QUESTION_NOT_CHANGED_ON_UPDATE.
Error Mode: POST_OUTPUTS_ETAGS_QUESTION_NOT_CHANGED_ON_UPDATE
Reference: outputs.etags.question

**6.2.2.131 screen etag schema invalid**
Criterion: Given outputs.etags.screen is present, When it violates schema, Then the system returns POST_OUTPUTS_ETAGS_SCREEN_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_ETAGS_SCREEN_SCHEMA_INVALID
Reference: outputs.etags.screen

**6.2.2.132 screen etag empty**
Criterion: Given outputs.etags.screen is present, When it is empty or not opaque, Then the system returns POST_OUTPUTS_ETAGS_SCREEN_EMPTY.
Error Mode: POST_OUTPUTS_ETAGS_SCREEN_EMPTY
Reference: outputs.etags.screen

**6.2.2.133 screen etag not changed on update**
Criterion: Given a screen’s persisted state changed, When outputs.etags.screen did not change, Then the system returns POST_OUTPUTS_ETAGS_SCREEN_NOT_CHANGED_ON_UPDATE.
Error Mode: POST_OUTPUTS_ETAGS_SCREEN_NOT_CHANGED_ON_UPDATE
Reference: outputs.etags.screen

**6.2.2.134 questionnaire etag schema invalid**
Criterion: Given outputs.etags.questionnaire is present, When it violates schema, Then the system returns POST_OUTPUTS_ETAGS_QUESTIONNAIRE_SCHEMA_INVALID.
Error Mode: POST_OUTPUTS_ETAGS_QUESTIONNAIRE_SCHEMA_INVALID
Reference: outputs.etags.questionnaire

**6.2.2.135 questionnaire etag empty**
Criterion: Given outputs.etags.questionnaire is present, When it is empty or not opaque, Then the system returns POST_OUTPUTS_ETAGS_QUESTIONNAIRE_EMPTY.
Error Mode: POST_OUTPUTS_ETAGS_QUESTIONNAIRE_EMPTY
Reference: outputs.etags.questionnaire

**6.2.2.136 questionnaire etag not changed on update**
Criterion: Given the questionnaire’s persisted state changed, When outputs.etags.questionnaire did not change, Then the system returns POST_OUTPUTS_ETAGS_QUESTIONNAIRE_NOT_CHANGED_ON_UPDATE.
Error Mode: POST_OUTPUTS_ETAGS_QUESTIONNAIRE_NOT_CHANGED_ON_UPDATE
Reference: outputs.etags.questionnaire

### 6.3 Happy Path Behavioural Acceptance Criteria

**6.3.1.1 Create screen → Rename/Reposition**
Given STEP-1 Create screen has completed successfully, When the author initiates a rename or proposes a new position, Then the system must initiate STEP-2 Rename screen and set position.
Reference: E6, E7.

**6.3.1.2 Create screen → Create question**
Given STEP-1 Create screen has completed successfully, When the author requests to create a question on that screen, Then the system must initiate STEP-3 Create question.
Reference: E10.

**6.3.1.3 Create screen → Reorder screens**
Given STEP-1 Create screen has completed successfully, When the author proposes a new screen position, Then the system must initiate STEP-6 Reorder screens.
Reference: E7.

**6.3.1.4 Rename/Reposition → Reorder screens**
Given STEP-2 Rename screen and set position has completed successfully, When the author proposes additional screen position changes, Then the system must initiate STEP-6 Reorder screens.
Reference: E7.

**6.3.1.5 Rename/Reposition → Create question**
Given STEP-2 Rename screen and set position has completed successfully, When the author requests to create a question on a screen, Then the system must initiate STEP-3 Create question.
Reference: E10.

**6.3.1.6 Create question → Allocate first placeholder**
Given STEP-3 Create question has completed successfully, When the first placeholder is allocated to the untyped question, Then the system must initiate STEP-3A Allocate first placeholder.
Reference: E26, S3.

**6.3.1.7 Create question → Update question**
Given STEP-3 Create question has completed successfully, When the author requests to update the question’s text or metadata, Then the system must initiate STEP-4 Update question text.
Reference: E15.

**6.3.1.8 Create question → Reorder within screen**
Given STEP-3 Create question has completed successfully, When the author proposes a new question order for that screen, Then the system must initiate STEP-5 Reorder questions within a screen.
Reference: E18.

**6.3.1.9 Create question → Move between screens**
Given STEP-3 Create question has completed successfully, When the author requests to move the question to another screen, Then the system must initiate STEP-7 Move question between screens.
Reference: E21.

**6.3.1.10 Allocate first placeholder → Update question**
Given STEP-3A Allocate first placeholder has completed successfully, When the author requests to modify question text or metadata, Then the system must initiate STEP-4 Update question text.
Reference: E15, E27, E28.

**6.3.1.11 Allocate first placeholder → Reorder within screen**
Given STEP-3A Allocate first placeholder has completed successfully, When the author proposes a new question order, Then the system must initiate STEP-5 Reorder questions within a screen.
Reference: E18, E27, E28.

**6.3.1.12 Update question → Reorder within screen**
Given STEP-4 Update question text has completed successfully, When the author proposes a new question order, Then the system must initiate STEP-5 Reorder questions within a screen.
Reference: E18.

**6.3.1.13 Update question → Move between screens**
Given STEP-4 Update question text has completed successfully, When the author requests to move the question to another screen, Then the system must initiate STEP-7 Move question between screens.
Reference: E21.

**6.3.1.14 Reorder within screen → Move between screens**
Given STEP-5 Reorder questions within a screen has completed successfully, When the author requests to move the question to another screen, Then the system must initiate STEP-7 Move question between screens.
Reference: E21.

**6.3.1.15 Reorder within screen → Set conditional parent**
Given STEP-5 Reorder questions within a screen has completed successfully, When the author requests to update visibility metadata for the question, Then the system must initiate STEP-8 Set conditional parent.
Reference: E15.

**6.3.1.16 Reorder screens → Move between screens**
Given STEP-6 Reorder screens has completed successfully, When the author requests to move a question to a different screen, Then the system must initiate STEP-7 Move question between screens.
Reference: E21.

**6.3.1.17 Move between screens → Reorder within target screen**
Given STEP-7 Move question between screens has completed successfully, When the author proposes a new order on the target screen, Then the system must initiate STEP-5 Reorder questions within a screen.
Reference: E18, E22.

**6.3.1.18 Move between screens → Set conditional parent**
Given STEP-7 Move question between screens has completed successfully, When the author requests to update the question’s visibility metadata, Then the system must initiate STEP-8 Set conditional parent.
Reference: E15.

**6.3.1.19 Set conditional parent → Clear conditional parent**
Given STEP-8 Set conditional parent has completed successfully, When the author requests to clear the visibility rule, Then the system must initiate STEP-9 Clear conditional parent.
Reference: E25.

**6.3.1.20 Clear conditional parent → Set conditional parent**
Given STEP-9 Clear conditional parent has completed successfully, When the author requests to define a new visibility rule, Then the system must initiate STEP-8 Set conditional parent.
Reference: E15.

#### 6.3.2.1

**Title:** Screen create persist failure halts create flow
**Criterion:** Given STEP-1 Create screen is applying the create request, when persisting the new screen fails, then halt STEP-1 Create screen and stop propagation to returning the created screen (E4).
**Error Mode:** RUN_SCREEN_CREATE_PERSIST_FAILED
**Reference:** outputs.screen (step: STEP-1 Create screen)

#### 6.3.2.2

**Title:** Screen order assignment failure halts create flow
**Criterion:** Given STEP-1 Create screen is assigning a final position, when order assignment fails, then halt STEP-1 Create screen and stop propagation to persistence (E3).
**Error Mode:** RUN_SCREEN_ORDER_ASSIGN_FAILED
**Reference:** outputs.screen.screen_order (step: STEP-1 Create screen)

#### 6.3.2.3

**Title:** Screen serialization failure blocks finalisation
**Criterion:** Given STEP-1 Create screen has a persisted entity, when response serialization fails, then prevent finalisation of STEP-1 Create screen and stop propagation to returning ETags (E5).
**Error Mode:** RUN_SCREEN_SERIALIZATION_FAILED
**Reference:** outputs.screen, outputs.etags (step: STEP-1 Create screen)

#### 6.3.2.4

**Title:** Screen ETag generation failure blocks finalisation
**Criterion:** Given STEP-1 Create screen has a persisted entity, when ETag generation or projection fails, then prevent finalisation of STEP-1 Create screen and stop propagation to client response completion.
**Error Mode:** RUN_SCREEN_ETAG_GEN_FAILED
**Reference:** outputs.etags.screen, outputs.etags.questionnaire (step: STEP-1 Create screen)

#### 6.3.2.5

**Title:** Screen update persist failure halts rename/reposition
**Criterion:** Given STEP-2 Rename screen and set position is applying changes, when persisting the update fails, then halt STEP-2 Rename screen and set position and stop propagation to returning updated ETags (E9).
**Error Mode:** RUN_SCREEN_UPDATE_PERSIST_FAILED
**Reference:** outputs.screen, outputs.etags.screen (step: STEP-2 Rename screen and set position)

#### 6.3.2.6

**Title:** Screen reindex failure halts rename/reposition
**Criterion:** Given STEP-2 Rename screen and set position is recalculating contiguous order, when reindexing fails, then halt STEP-2 Rename screen and set position and stop propagation to persistence (E8).
**Error Mode:** RUN_SCREEN_REINDEX_FAILED
**Reference:** outputs.screen.screen_order (step: STEP-2 Rename screen and set position)

#### 6.3.2.7

**Title:** Screen ETag update failure blocks finalisation
**Criterion:** Given STEP-2 Rename screen and set position has persisted changes, when ETag update or projection fails, then prevent finalisation of STEP-2 Rename screen and set position and stop propagation to client response completion.
**Error Mode:** RUN_SCREEN_ETAG_UPDATE_FAILED
**Reference:** outputs.etags.screen, outputs.etags.questionnaire (step: STEP-2 Rename screen and set position)

#### 6.3.2.8

**Title:** Question scaffold creation failure halts create
**Criterion:** Given STEP-3 Create question is initializing a scaffold, when scaffold creation fails, then halt STEP-3 Create question and stop propagation to persistence (E11).
**Error Mode:** RUN_QUESTION_SCAFFOLD_CREATE_FAILED
**Reference:** outputs.question (step: STEP-3 Create question)

#### 6.3.2.9

**Title:** Initial question order assignment failure halts create
**Criterion:** Given STEP-3 Create question is assigning initial question_order, when assignment fails, then halt STEP-3 Create question and stop propagation to persistence (E11).
**Error Mode:** RUN_QUESTION_ORDER_ASSIGN_FAILED
**Reference:** outputs.question.question_order (step: STEP-3 Create question)

#### 6.3.2.10

**Title:** Question persist failure halts create
**Criterion:** Given STEP-3 Create question has a scaffold, when persisting the question fails, then halt STEP-3 Create question and stop propagation to returning the created question (E12).
**Error Mode:** RUN_QUESTION_PERSIST_FAILED
**Reference:** outputs.question (step: STEP-3 Create question)

#### 6.3.2.11

**Title:** Question serialization failure blocks finalisation
**Criterion:** Given STEP-3 Create question has a persisted question, when response serialization fails, then prevent finalisation of STEP-3 Create question and stop propagation to returning ETags (E13/E14).
**Error Mode:** RUN_QUESTION_SERIALIZATION_FAILED
**Reference:** outputs.question, outputs.etags (step: STEP-3 Create question)

#### 6.3.2.12

**Title:** Question ETag generation failure blocks finalisation
**Criterion:** Given STEP-3 Create question has a persisted question, when ETag generation or projection fails, then prevent finalisation of STEP-3 Create question and stop propagation to client response completion.
**Error Mode:** RUN_QUESTION_ETAG_GEN_FAILED
**Reference:** outputs.etags.question, outputs.etags.screen, outputs.etags.questionnaire (step: STEP-3 Create question)

#### 6.3.2.13

**Title:** Determine answer_kind failure halts allocation
**Criterion:** Given STEP-3A Allocate first placeholder is inferring the type, when determining answer_kind fails, then halt STEP-3A Allocate first placeholder and stop propagation to persisting the type (E27).
**Error Mode:** RUN_DETERMINE_ANSWER_KIND_FAILED
**Reference:** outputs.question.answer_kind (step: STEP-3A Allocate first placeholder)

#### 6.3.2.14

**Title:** Persist answer_kind failure halts allocation
**Criterion:** Given STEP-3A Allocate first placeholder has determined the type, when persisting answer_kind fails, then halt STEP-3A Allocate first placeholder and stop propagation to returning the updated question (E28).
**Error Mode:** RUN_PERSIST_ANSWER_KIND_FAILED
**Reference:** outputs.question.answer_kind (step: STEP-3A Allocate first placeholder)

#### 6.3.2.15

**Title:** Typed question return failure blocks finalisation
**Criterion:** Given STEP-3A Allocate first placeholder has persisted the type, when returning the updated question fails, then prevent finalisation of STEP-3A Allocate first placeholder and stop propagation to client response completion.
**Error Mode:** RUN_TYPED_QUESTION_RETURN_FAILED
**Reference:** outputs.question (step: STEP-3A Allocate first placeholder)

#### 6.3.2.16

**Title:** Apply field updates failure halts update
**Criterion:** Given STEP-4 Update question text is applying requested changes, when applying field updates fails, then halt STEP-4 Update question text and stop propagation to persistence (E16).
**Error Mode:** RUN_UPDATE_FIELDS_APPLY_FAILED
**Reference:** outputs.question (step: STEP-4 Update question text)

#### 6.3.2.17

**Title:** Question update persist failure halts update
**Criterion:** Given STEP-4 Update question text has applied changes, when persisting the updates fails, then halt STEP-4 Update question text and stop propagation to returning updated ETags (E17).
**Error Mode:** RUN_QUESTION_UPDATE_PERSIST_FAILED
**Reference:** outputs.question, outputs.etags.question (step: STEP-4 Update question text)

#### 6.3.2.18

**Title:** Question ETag update failure blocks finalisation
**Criterion:** Given STEP-4 Update question text has persisted changes, when ETag update or projection fails, then prevent finalisation of STEP-4 Update question text and stop propagation to client response completion.
**Error Mode:** RUN_QUESTION_ETAG_UPDATE_FAILED
**Reference:** outputs.etags.question (step: STEP-4 Update question text)

#### 6.3.2.19

**Title:** Question reindex failure halts reorder
**Criterion:** Given STEP-5 Reorder questions within a screen is recalculating order, when reindexing fails, then halt STEP-5 Reorder questions within a screen and stop propagation to persistence (E19).
**Error Mode:** RUN_QUESTION_REINDEX_FAILED
**Reference:** outputs.question.question_order (step: STEP-5 Reorder questions within a screen)

#### 6.3.2.20

**Title:** Reorder persist failure halts reorder
**Criterion:** Given STEP-5 Reorder questions within a screen has a new sequence, when persisting the sequence fails, then halt STEP-5 Reorder questions within a screen and stop propagation to returning updated order and ETags (E20).
**Error Mode:** RUN_REORDER_PERSIST_FAILED
**Reference:** outputs.question, outputs.etags.question (step: STEP-5 Reorder questions within a screen)

#### 6.3.2.21

**Title:** Reorder result return failure blocks finalisation
**Criterion:** Given STEP-5 Reorder questions within a screen has persisted changes, when returning updated ETags and order fails, then prevent finalisation of STEP-5 Reorder questions within a screen and stop propagation to client response completion.
**Error Mode:** RUN_REORDER_RESULT_RETURN_FAILED
**Reference:** outputs.question.question_order, outputs.etags.question (step: STEP-5 Reorder questions within a screen)

#### 6.3.2.22

**Title:** Screen reorder persist failure halts reorder
**Criterion:** Given STEP-6 Reorder screens has a new sequence, when persisting the sequence fails, then halt STEP-6 Reorder screens and stop propagation to returning updated ETags (E9).
**Error Mode:** RUN_SCREEN_REORDER_PERSIST_FAILED
**Reference:** outputs.screen, outputs.etags.screen (step: STEP-6 Reorder screens)

#### 6.3.2.23

**Title:** Move assign target order failure halts move
**Criterion:** Given STEP-7 Move question between screens is assigning a target position, when assigning the new question_order fails, then halt STEP-7 Move question between screens and stop propagation to reindexing the source screen (E22).
**Error Mode:** RUN_MOVE_ASSIGN_TARGET_ORDER_FAILED
**Reference:** outputs.question.question_order (step: STEP-7 Move question between screens)

#### 6.3.2.24

**Title:** Move reindex source failure halts move
**Criterion:** Given STEP-7 Move question between screens is reindexing the source screen, when reindexing fails, then halt STEP-7 Move question between screens and stop propagation to persisting changes to both screens (E23).
**Error Mode:** RUN_MOVE_REINDEX_SOURCE_FAILED
**Reference:** outputs.question.question_order (step: STEP-7 Move question between screens)

#### 6.3.2.25

**Title:** Move persist failure halts move
**Criterion:** Given STEP-7 Move question between screens is persisting changes, when persistence fails, then halt STEP-7 Move question between screens and stop propagation to returning updated ETags and target order (E24).
**Error Mode:** RUN_MOVE_PERSIST_FAILED
**Reference:** outputs.question, outputs.etags (step: STEP-7 Move question between screens)

#### 6.3.2.26

**Title:** Move result return failure blocks finalisation
**Criterion:** Given STEP-7 Move question between screens has persisted changes, when returning updated ETags and target order fails, then prevent finalisation of STEP-7 Move question between screens and stop propagation to client response completion.
**Error Mode:** RUN_MOVE_RESULT_RETURN_FAILED
**Reference:** outputs.question.question_order, outputs.etags (step: STEP-7 Move question between screens)

#### 6.3.2.27

**Title:** Set visibility link persist failure halts visibility update
**Criterion:** Given STEP-8 Set conditional parent is persisting the parent link and rule, when persistence fails, then halt STEP-8 Set conditional parent and stop propagation to response finalisation for visibility changes.
**Error Mode:** RUN_SET_VISIBILITY_LINK_PERSIST_FAILED
**Reference:** outputs.question.parent_question_id, outputs.question.visible_if_value (step: STEP-8 Set conditional parent)

#### 6.3.2.28

**Title:** Clear visibility persist failure halts clear operation
**Criterion:** Given STEP-9 Clear conditional parent is removing the link and rule, when persistence fails, then halt STEP-9 Clear conditional parent and stop propagation to response finalisation for visibility changes.
**Error Mode:** RUN_CLEAR_VISIBILITY_PERSIST_FAILED
**Reference:** outputs.question.parent_question_id, outputs.question.visible_if_value (step: STEP-9 Clear conditional parent)

#### 6.3.2.29

**Title:** Clear rule return failure blocks finalisation
**Criterion:** Given STEP-9 Clear conditional parent has persisted the clear operation, when returning updated ETags fails, then prevent finalisation of STEP-9 Clear conditional parent and stop propagation to client response completion.
**Error Mode:** RUN_CLEAR_RULE_RETURN_FAILED
**Reference:** outputs.etags.question (step: STEP-9 Clear conditional parent)

#### 6.3.2.30

**Title:** Database network unreachable halts write steps and prevents downstream operations
**Criterion:** Given authoring write steps are in progress, when the database network becomes unreachable, then halt STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, and STEP-7 and stop propagation to their downstream operations including STEP-2, STEP-4, STEP-5, STEP-6, and STEP-7, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DB_NETWORK_UNREACHABLE
**Reference:** database network connectivity; Steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7

#### 6.3.2.31

**Title:** Database DNS resolution failure halts write steps and prevents downstream operations
**Criterion:** Given authoring write steps are in progress, when DNS resolution for the database endpoint fails, then halt STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, and STEP-7 and stop propagation to their downstream operations including STEP-2, STEP-4, STEP-5, STEP-6, and STEP-7, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DB_DNS_RESOLUTION_FAILED
**Reference:** database DNS resolution; Steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7

#### 6.3.2.32

**Title:** Database TLS handshake failure halts write steps and prevents downstream operations
**Criterion:** Given authoring write steps are in progress, when the TLS handshake with the database fails, then halt STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, and STEP-7 and stop propagation to their downstream operations including STEP-2, STEP-4, STEP-5, STEP-6, and STEP-7, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DB_TLS_HANDSHAKE_FAILED
**Reference:** database TLS/SSL handshakes; Steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7

#### 6.3.2.33

**Title:** Database configuration missing halts write steps and prevents downstream operations
**Criterion:** Given authoring write steps are in progress, when required database configuration is missing, then halt STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, and STEP-7 and stop propagation to their downstream operations including STEP-2, STEP-4, STEP-5, STEP-6, and STEP-7, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DB_CONFIG_MISSING
**Reference:** runtime database configuration; Steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7

#### 6.3.2.34

**Title:** Database credentials invalid halts write steps and prevents downstream operations
**Criterion:** Given authoring write steps are in progress, when database authentication fails due to invalid credentials, then halt STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, and STEP-7 and stop propagation to their downstream operations including STEP-2, STEP-4, STEP-5, STEP-6, and STEP-7, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DB_CREDENTIALS_INVALID
**Reference:** database authentication (credentials); Steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7

#### 6.3.2.35

**Title:** Database authorisation denied halts write steps and prevents downstream operations
**Criterion:** Given authoring write steps are in progress, when the database denies authorisation for required operations, then halt STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, and STEP-7 and stop propagation to their downstream operations including STEP-2, STEP-4, STEP-5, STEP-6, and STEP-7, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DB_AUTHZ_DENIED
**Reference:** database authorisation/permissions; Steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7

#### 6.3.2.36

**Title:** Database connection limit exceeded halts write steps and prevents downstream operations
**Criterion:** Given authoring write steps are in progress, when the database rejects new connections due to limits, then halt STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, and STEP-7 and stop propagation to their downstream operations including STEP-2, STEP-4, STEP-5, STEP-6, and STEP-7, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DB_CONNECTION_LIMIT_EXCEEDED
**Reference:** database connection pool/server limits; Steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7

#### 6.3.2.37

**Title:** Database transaction deadlock halts update/reindex steps and prevents subsequent operations
**Criterion:** Given an authoring update or reindex step is in progress, when a database transaction deadlock occurs, then halt STEP-2, STEP-4, STEP-5, STEP-6, and STEP-7 and stop propagation to their subsequent operations, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DB_TRANSACTION_DEADLOCK
**Reference:** database transaction processing; Steps: STEP-2, STEP-4, STEP-5, STEP-6, STEP-7

#### 6.3.2.38

**Title:** Database storage quota exceeded halts write steps and prevents downstream operations
**Criterion:** Given authoring write steps are in progress, when the database rejects writes due to storage quota or disk exhaustion, then halt STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, and STEP-7 and stop propagation to their downstream operations including STEP-2, STEP-4, STEP-5, STEP-6, and STEP-7, as required by the error mode’s Flow Impact.
**Error Mode:** ENV_DB_STORAGE_QUOTA_EXCEEDED
**Reference:** database storage/quota; Steps: STEP-1, STEP-2, STEP-3, STEP-4, STEP-5, STEP-6, STEP-7

7.1.1 – Centralised AnswerKind enumeration
Purpose: Verify that allowed answer kinds are centrally defined in code and mirrored in schema.
Test Data: schofield-main/app/models/question_kind.py; schofield-main/schemas/AnswerKind.json
Mocking: No mocking; this check inspects real files for constants and schema enum values.
Assertions:

* File schofield-main/app/models/question_kind.py exists.
* Class QuestionKind defines attributes SHORT_STRING, LONG_TEXT, NUMBER, BOOLEAN, ENUM_SINGLE with values "short_string", "long_text", "number", "boolean", "enum_single".
* File schofield-main/schemas/AnswerKind.json exists.
* JSON enum array equals the five values above (order-insensitive).
  AC-Ref: 6.1.1

7.1.2 – Identifier schemas exist for entities
Purpose: Ensure canonical identifier schemas are present for questionnaire, screen, and question IDs.
Test Data: schofield-main/schemas/QuestionnaireId.schema.json; schofield-main/schemas/ScreenId.schema.json; schofield-main/schemas/question_id.schema.json
Mocking: No mocking; structural presence and schema titles are inspected directly.
Assertions:

* Each schema file exists.
* Each schema declares "$schema" and "$id" keys.
* Titles include “QuestionnaireId”, “ScreenId”, and “question_id” (case-insensitive match permitted for file naming vs title).
  AC-Ref: 6.1.2

7.1.3 – Persistence columns for question ordering and visibility
Purpose: Verify persistence model includes question_order, parent_question_id, and visible_if_value for authoring features.
Test Data: schofield-main/migrations/001_init.sql; schofield-main/migrations/008_add_question_order.sql
Mocking: No mocking; SQL migration files are read to assert DDL presence.
Assertions:

* 001_init.sql contains table questionnaire_question with columns question_order, parent_question_id, visible_if_value.
* 001_init.sql defines question_order as INT (or integer) and NOT NULL.
* 008_add_question_order.sql exists and includes ALTER TABLE questionnaire_question ADD COLUMN IF NOT EXISTS question_order.
  AC-Ref: 6.1.3

7.1.4 – Screen ordering modeled in persistence
Purpose: Ensure a structural location exists for screen ordering (screen_order) in persistence layer.
Test Data: schofield-main/migrations/001_init.sql (and all *.sql under schofield-main/migrations/)
Mocking: No mocking; validates presence of DDL for screen_order.
Assertions:

* At least one migration declares a column named screen_order for screens/similar screen table (case-insensitive search for “screen_order”).
* Fails if no migration contains screen_order definition (expected until implemented).
  AC-Ref: 6.1.4

7.1.5 – Centralised ETag helper module
Purpose: Confirm ETag computation is centralised per architectural convention.
Test Data: schofield-main/app/logic/etag.py
Mocking: No mocking; static check for module and function signatures.
Assertions:

* File exists.
* Module defines function compute_screen_etag(response_set_id: str, screen_key: str) (name and arity check).
  AC-Ref: 6.1.5

7.1.6 – Repository layer present for screens and questionnaires
Purpose: Ensure data-access responsibilities are separated into repository modules.
Test Data: schofield-main/app/logic/repository_screens.py; schofield-main/app/logic/repository_questionnaires.py
Mocking: No mocking; checks for module existence and exported callables.
Assertions:

* Both repository modules exist.
* Each module exposes at least one callable (e.g., list_*, get_*, count_*), verified by simple regex on def lines.
  AC-Ref: 6.1.6

7.1.7 – Route modules present for questionnaire/screen HTTP surfaces
Purpose: Verify presence of route modules to host endpoints described in Section 2.
Test Data: schofield-main/app/routes/questionnaires.py; schofield-main/app/routes/screens.py
Mocking: No mocking; static inspection of defined routes.
Assertions:

* Both files exist.
* Each file defines a FastAPI APIRouter instance.
* At least one route path in either file begins with "/api/" (regex match).
  AC-Ref: 6.1.7

7.1.8 – Screen view schema exposes questions collection
Purpose: Ensure screen-level schema defines a questions array for downstream rendering.
Test Data: schofield-main/docs/schemas/ScreenView.schema.json
Mocking: No mocking; validates schema structure.
Assertions:

* File exists.
* Schema has properties.questions of type "array".
  AC-Ref: 6.1.8

7.1.9 – OptionSpec schema present to support enum_single options
Purpose: Ensure an option specification schema exists to model enumerated choices.
Test Data: schofield-main/schemas/OptionSpec.json
Mocking: No mocking; static file presence and minimal structure.
Assertions:

* File exists.
* Schema declares "$schema" and a "title" containing "OptionSpec".
  AC-Ref: 6.1.9

7.1.10 – Migrations runner present for deterministic evolution
Purpose: Verify the project includes a migrations runner aligned with schema evolution.
Test Data: schofield-main/app/db/migrations_runner.py
Mocking: No mocking; file presence only.
Assertions:

* File exists.
* File imports a database engine or connection utility from app.db.* (regex for "from app.db" or "import app.db").
  AC-Ref: 6.1.10

7.1.11 – AGENTS.md present at repository root
Purpose: Confirm architectural conventions document exists at the project root.
Test Data: schofield-main/AGENTS.md
Mocking: No mocking; file presence only.
Assertions:

* File exists at the exact path.
* File includes the string “Project overview” and at least one agent name (“Ada” or “Clarke” or “Hamilton”).
  AC-Ref: 6.1.11

7.1.12 – Question identifier schema referenced consistently
Purpose: Ensure question identifier schema is the canonical reference across docs and runtime schemas.
Test Data: schofield-main/schemas/question_id.schema.json; any JSON under schofield-main/schemas/** referencing question IDs
Mocking: No mocking; static scan for “$ref” usage.
Assertions:

* question_id.schema.json exists.
* At least one other schema references it via "$ref" containing "question_id.schema.json".
  AC-Ref: 6.1.12

7.1.13 – AnswerKind values consistent between code and schema
Purpose: Enforce consistency between Python constants and JSON Schema enum for AnswerKind.
Test Data: schofield-main/app/models/question_kind.py; schofield-main/schemas/AnswerKind.json
Mocking: No mocking; direct file read and comparison of sets.
Assertions:

* The set of string values defined in QuestionKind equals the enum array in AnswerKind.json (order-insensitive).
  AC-Ref: 6.1.13

7.1.14 – Visibility-related persistence fields present
Purpose: Ensure visibility rule storage aligns with Section 2 (visible_if_value and parent reference).
Test Data: schofield-main/migrations/001_init.sql
Mocking: No mocking; static DDL inspection.
Assertions:

* Table questionnaire_question has columns parent_question_id and visible_if_value.
* visible_if_value column type is JSON/JSONB (regex match for json/jsonb).
  AC-Ref: 6.1.14

7.1.15 – Ordering artefacts isolated from UI route modules
Purpose: Ensure low-level ordering logic is not implemented inside route files, preserving separation of concerns.
Test Data: schofield-main/app/routes/questionnaires.py; schofield-main/app/routes/screens.py
Mocking: No mocking; static check for absence of sorting algorithms.
Assertions:

* Route files do not define functions whose names contain “reindex”, “reorder”, or “contiguous” (regex negative check).
* Route files do not contain raw SQL touching question_order or screen_order (regex negative check for those identifiers).
  AC-Ref: 6.1.15

7.1.16 – Migrations journal tracked
Purpose: Ensure migrations state is tracked to support deterministic application order.
Test Data: schofield-main/migrations/_journal.json
Mocking: No mocking; file presence and minimal JSON validity.
Assertions:

* _journal.json exists.
* File parses as valid JSON and contains an array or object with at least one entry.
  AC-Ref: 6.1.16

**7.2.1.1**
**Title:** Create screen returns screen payload
**Purpose:** Verify that creating a screen returns the expected screen object with ID, title, and order.
**Test data:**

* Request: `POST /api/v1/authoring/questionnaires/q-001/screens` with body `{ "title": "Eligibility" }` and header `Idempotency-Key: idemp-001`.
  **Mocking:** None. Exercise the API against a test instance with a clean questionnaire `q-001`.
  **Assertions:**
* Assert HTTP 201.
* Assert response JSON has `outputs.screen` object.
* Assert `outputs.screen.screen_id` is a non-empty string.
* Assert `outputs.screen.title == "Eligibility"`.
* Assert `outputs.screen.screen_order == 1`.
  **AC-Ref:** 6.2.1.1
  **EARS-Refs:** E1, E4

---

**7.2.1.2**
**Title:** Create screen assigns backend order
**Purpose:** Verify backend assigns the authoritative screen order.
**Test data:**

* Pre-state: One existing screen on `q-001` with `screen_order = 1`.
* Request: `POST /api/v1/authoring/questionnaires/q-001/screens` body `{ "title": "Background" }` header `Idempotency-Key: idemp-002`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 201.
* Assert `outputs.screen.title == "Background"`.
* Assert `outputs.screen.screen_order == 2` (backend-assigned).
  **AC-Ref:** 6.2.1.2
  **EARS-Refs:** U1, U3, E2

---

**7.2.1.3**
**Title:** Create screen returns ETags
**Purpose:** Verify screen and questionnaire ETags are returned after create.
**Test data:**

* Request: `POST /api/v1/authoring/questionnaires/q-001/screens` body `{ "title": "Consent" }` header `Idempotency-Key: idemp-003`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 201.
* Assert `outputs.etags.screen` is a non-empty string.
* Assert `outputs.etags.questionnaire` is a non-empty string.
  **AC-Ref:** 6.2.1.3
  **EARS-Refs:** U5, E5

---

**7.2.1.4**
**Title:** Rename screen returns updated title
**Purpose:** Verify renaming a screen returns the new persisted title.
**Test data:**

* Existing: `screen_id = scr-001`, title `"Eligibility"`.
* Request: `PATCH /api/v1/authoring/questionnaires/q-001/screens/scr-001` body `{ "title": "Applicant Eligibility" }` header `If-Match: <Screen-ETag>`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.screen.screen_id == "scr-001"`.
* Assert `outputs.screen.title == "Applicant Eligibility"`.
  **AC-Ref:** 6.2.1.4
  **EARS-Refs:** E6, E8

---

**7.2.1.5**
**Title:** Reposition screen returns final order
**Purpose:** Verify proposing a new screen position returns the final backend order.
**Test data:**

* Existing screens: `scr-001(order 1)`, `scr-002(order 2)`, `scr-003(order 3)`.
* Request: `PATCH /api/v1/authoring/questionnaires/q-001/screens/scr-003` body `{ "proposed_position": 1 }` header `If-Match: <Screen-ETag>`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.screen.screen_id == "scr-003"`.
* Assert `outputs.screen.screen_order == 1`.
  **AC-Ref:** 6.2.1.5
  **EARS-Refs:** U1, U3, E7, E8

---

**7.2.1.6**
**Title:** Screen update returns ETags
**Purpose:** Verify screen and questionnaire ETags are returned on update.
**Test data:**

* Request: `PATCH /api/v1/authoring/questionnaires/q-001/screens/scr-001` body `{ "title": "Eligibility (v2)" }` header `If-Match: <Screen-ETag>`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.etags.screen` non-empty string.
* Assert `outputs.etags.questionnaire` non-empty string.
  **AC-Ref:** 6.2.1.6
  **EARS-Refs:** U5, E9

---

**7.2.1.7**
**Title:** Create question returns question payload
**Purpose:** Verify creating a question returns question object with identifiers and order.
**Test data:**

* Request: `POST /api/v1/authoring/questionnaires/q-001/questions` body `{ "screen_id": "scr-001", "question_text": "What is your age?" }` header `Idempotency-Key: idemp-101`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 201.
* Assert `outputs.question.question_id` non-empty string.
* Assert `outputs.question.screen_id == "scr-001"`.
* Assert `outputs.question.question_text == "What is your age?"`.
* Assert `outputs.question.question_order == 1` (if first on screen).
  **AC-Ref:** 6.2.1.7
  **EARS-Refs:** E10, E12

---

**7.2.1.8**
**Title:** Create question leaves answer_kind unset
**Purpose:** Verify newly created question scaffold has no answer_kind set.
**Test data:**

* Request: (as 7.2.1.7).
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 201.
* Assert `outputs.question.answer_kind is null`.
  **AC-Ref:** 6.2.1.8
  **EARS-Refs:** U7, E12

---

**7.2.1.9**
**Title:** Create question returns ETags
**Purpose:** Verify question, screen, and questionnaire ETags are returned on question create.
**Test data:**

* Request: (as 7.2.1.7) with unique `Idempotency-Key: idemp-102`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 201.
* Assert `outputs.etags.question` non-empty string.
* Assert `outputs.etags.screen` non-empty string.
* Assert `outputs.etags.questionnaire` non-empty string.
  **AC-Ref:** 6.2.1.9
  **EARS-Refs:** U5, E13, E14

---

**7.2.1.10**
**Title:** First placeholder sets answer_kind
**Purpose:** Verify allocating the first placeholder determines and sets the question’s answer_kind.
**Test data:**

* Pre-state: `question_id = qst-001` currently has `answer_kind = null`.
* Request: Allocate first placeholder (per authoring UI flow) that determines `answer_kind = "enum_single"`.
  **Mocking:** None (use real allocation flow).
  **Assertions:**
* Assert success status (200/201 per API).
* Assert `outputs.question.question_id == "qst-001"`.
* Assert `outputs.question.answer_kind == "enum_single"`.
  **AC-Ref:** 6.2.1.10
  **EARS-Refs:** E26, E27, E28, S3

---

**7.2.1.11**
**Title:** First placeholder update returns ETags
**Purpose:** Verify ETags are returned when answer_kind is persisted.
**Test data:**

* Request: (as 7.2.1.10).
  **Mocking:** None.
  **Assertions:**
* Assert success status.
* Assert `outputs.etags.question` non-empty string.
  **AC-Ref:** 6.2.1.11
  **EARS-Refs:** U5, E28

---

**7.2.1.12**
**Title:** Update question returns updated text
**Purpose:** Verify updating question text returns the new text.
**Test data:**

* Request: `PATCH /api/v1/authoring/questions/qst-001` body `{ "question_text": "What is your full name?" }` header `If-Match: <Question-ETag>`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.question.question_id == "qst-001"`.
* Assert `outputs.question.question_text == "What is your full name?"`.
  **AC-Ref:** 6.2.1.12
  **EARS-Refs:** E15, E16

---

**7.2.1.13**
**Title:** Update question returns ETags
**Purpose:** Verify ETags are returned on question update.
**Test data:**

* Request: (as 7.2.1.12).
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.etags.question` non-empty string.
  **AC-Ref:** 6.2.1.13
  **EARS-Refs:** U5, E17

---

**7.2.1.14**
**Title:** Reorder question returns final order
**Purpose:** Verify proposing a new question position returns final backend order.
**Test data:**

* Existing on `scr-001`: `qst-A(order 1)`, `qst-B(order 2)`.
* Request: `PATCH /api/v1/authoring/questions/qst-B/position` body `{ "proposed_question_order": 1 }` header `If-Match: <Question-ETag>`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert response `outputs.question.question_id == "qst-B"`.
* Assert `outputs.question.question_order == 1`.
  **AC-Ref:** 6.2.1.14
  **EARS-Refs:** U2, U3, E18, E19

---

**7.2.1.15**
**Title:** Reorder question returns ETags
**Purpose:** Verify question ETag is returned after reorder.
**Test data:**

* Request: (as 7.2.1.14).
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.etags.question` non-empty string.
  **AC-Ref:** 6.2.1.15
  **EARS-Refs:** U5, E20

---

**7.2.1.16**
**Title:** Reorder screens returns final order
**Purpose:** Verify final backend order returned after screen reorder.
**Test data:**

* Existing: `scr-001(1)`, `scr-002(2)`, `scr-003(3)`.
* Request: `PATCH /api/v1/authoring/questionnaires/q-001/screens/scr-001` body `{ "proposed_position": 3 }` header `If-Match: <Screen-ETag>`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.screen.screen_id == "scr-001"`.
* Assert `outputs.screen.screen_order == 3`.
  **AC-Ref:** 6.2.1.16
  **EARS-Refs:** U1, U3, E7, E8

---

**7.2.1.17**
**Title:** Reorder screens returns ETags
**Purpose:** Verify returning screen ETag on reorder.
**Test data:**

* Request: (as 7.2.1.16).
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.etags.screen` non-empty string.
  **AC-Ref:** 6.2.1.17
  **EARS-Refs:** U5, E9

---

**7.2.1.18**
**Title:** Move question returns new screen_id
**Purpose:** Verify moving a question to another screen returns the target screen_id.
**Test data:**

* Existing: `qst-010` on `scr-001`. Target screen `scr-003`.
* Request: `PATCH /api/v1/authoring/questions/qst-010/position` body `{ "screen_id": "scr-003" }` header `If-Match: <Question-ETag>`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.question.question_id == "qst-010"`.
* Assert `outputs.question.screen_id == "scr-003"`.
  **AC-Ref:** 6.2.1.18
  **EARS-Refs:** E21, E23

---

**7.2.1.19**
**Title:** Move question returns new order
**Purpose:** Verify backend assigns new order on target screen.
**Test data:**

* Pre-state: `scr-003` has 2 questions.
* Request: (as 7.2.1.18).
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.question.question_order == 3` (appended to target).
  **AC-Ref:** 6.2.1.19
  **EARS-Refs:** U2, U3, E21, E23

---

**7.2.1.20**
**Title:** Move question returns ETags (question)
**Purpose:** Verify question ETag is returned on move.
**Test data:**

* Request: (as 7.2.1.18).
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.etags.question` non-empty string.
  **AC-Ref:** 6.2.1.20
  **EARS-Refs:** U5, E24

---

**7.2.1.21**
**Title:** Move question returns ETags (screen)
**Purpose:** Verify affected screen ETag is returned on move.
**Test data:**

* Request: (as 7.2.1.18).
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.etags.screen` non-empty string.
  **AC-Ref:** 6.2.1.21
  **EARS-Refs:** U5, E24

---

**7.2.1.22**
**Title:** Set conditional parent returns parent id
**Purpose:** Verify setting a conditional parent returns the parent_question_id.
**Test data:**

* Request: `PATCH /api/v1/authoring/questions/qst-020/visibility` body `{ "parent_question_id": "qst-010", "rule": { "visible_if_value": ["Yes"] } }` header `If-Match: <Question-ETag>`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.question.parent_question_id == "qst-010"`.
  **AC-Ref:** 6.2.1.22
  **EARS-Refs:** U6

---

**7.2.1.23**
**Title:** Set conditional rule returns canonical value(s)
**Purpose:** Verify visible_if_value is persisted in canonical form.
**Test data:**

* Request: (as 7.2.1.22) with `rule.visible_if_value = ["Yes"]`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.question.visible_if_value == ["Yes"]`.
  **AC-Ref:** 6.2.1.23
  **EARS-Refs:** U6

---

**7.2.1.24**
**Title:** Set conditional parent returns ETags
**Purpose:** Verify ETags are returned after setting visibility.
**Test data:**

* Request: (as 7.2.1.22).
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.etags.question` non-empty string.
  **AC-Ref:** 6.2.1.24
  **EARS-Refs:** U5

---

**7.2.1.25**
**Title:** Clear conditional parent nulls parent id
**Purpose:** Verify clearing visibility nulls the parent reference.
**Test data:**

* Request: `PATCH /api/v1/authoring/questions/qst-020/visibility` body `{ "parent_question_id": null, "rule": null }` header `If-Match: <Question-ETag>`.
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.question.parent_question_id is null`.
  **AC-Ref:** 6.2.1.25
  **EARS-Refs:** E25

---

**7.2.1.26**
**Title:** Clear conditional parent nulls rule values
**Purpose:** Verify clearing visibility nulls visible_if_value.
**Test data:**

* Request: (as 7.2.1.25).
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.question.visible_if_value is null`.
  **AC-Ref:** 6.2.1.26
  **EARS-Refs:** E25

---

**7.2.1.27**
**Title:** Clear conditional parent returns ETags
**Purpose:** Verify ETags are returned after clearing visibility.
**Test data:**

* Request: (as 7.2.1.25).
  **Mocking:** None.
  **Assertions:**
* Assert HTTP 200.
* Assert `outputs.etags.question` non-empty string.
  **AC-Ref:** 6.2.1.27
  **EARS-Refs:** U5, E25

---

**7.2.1.28**
**Title:** Deterministic read: screens order stable
**Purpose:** Verify screen order is stable across reads when state is unchanged.
**Test data:**

* Pre-state: Questionnaire `q-001` with 3 screens, no writes between reads.
  **Mocking:** None.
  **Assertions:**
* Perform two consecutive reads of screens list.
* Assert both payloads’ `outputs.screen[].screen_order` sequences are identical (e.g., `[1,2,3]`).
  **AC-Ref:** 6.2.1.28
  **EARS-Refs:** U4, S1

---

**7.2.1.29**
**Title:** Deterministic read: questions order stable
**Purpose:** Verify question order is stable across reads when state is unchanged.
**Test data:**

* Pre-state: Screen `scr-001` with 3 questions, no writes between reads.
  **Mocking:** None.
  **Assertions:**
* Perform two consecutive reads of questions list.
* Assert both payloads’ `outputs.question[].question_order` sequences are identical (e.g., `[1,2,3]`).
  **AC-Ref:** 6.2.1.29
  **EARS-Refs:** U4, S2

---

**7.2.1.30**
**Title:** Read screens sorted by screen_order
**Purpose:** Verify screens are returned sorted ascending by screen_order.
**Test data:**

* Pre-state: Three screens with orders 2, 1, 3 persisted.
  **Mocking:** None.
  **Assertions:**
* Read screens list.
* Assert received list order by `outputs.screen[].screen_order` is `[1,2,3]`.
  **AC-Ref:** 6.2.1.30
  **EARS-Refs:** S1

---

**7.2.1.31**
**Title:** Read questions sorted by question_order
**Purpose:** Verify questions are returned sorted ascending by question_order.
**Test data:**

* Pre-state: Screen `scr-002` has questions with orders 3, 1, 2 persisted.
  **Mocking:** None.
  **Assertions:**
* Read questions list for `scr-002`.
* Assert received list order by `outputs.question[].question_order` is `[1,2,3]`.
  **AC-Ref:** 6.2.1.31
  **EARS-Refs:** S2

ID: 7.2.2.1
Title: questionnaire_id missing
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires//screens
Headers: {}
Body: {'title': 'Screen A'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTIONNAIRE_ID_MISSING'; response.error.message contains 'questionnaire_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.1
Error Mode: PRE_QUESTIONNAIRE_ID_MISSING

ID: 7.2.2.2
Title: questionnaire_id schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/not-a-uuid/screens
Headers: {}
Body: {'title': 'Screen A'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTIONNAIRE_ID_SCHEMA_MISMATCH'; response.error.message contains 'questionnaire_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.2
Error Mode: PRE_QUESTIONNAIRE_ID_SCHEMA_MISMATCH

ID: 7.2.2.3
Title: questionnaire_id not found
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-missing-000/screens
Headers: {}
Body: {'title': 'Screen A'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTIONNAIRE_ID_NOT_FOUND'; response.error.message contains 'questionnaire_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.3
Error Mode: PRE_QUESTIONNAIRE_ID_NOT_FOUND

ID: 7.2.2.4
Title: screen_id required when targeted
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/s-111
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_SCREEN_ID_REQUIRED_WHEN_TARGETED'; response.error.message contains 'screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.4
Error Mode: PRE_SCREEN_ID_REQUIRED_WHEN_TARGETED

ID: 7.2.2.5
Title: screen_id schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/###
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_SCREEN_ID_SCHEMA_MISMATCH'; response.error.message contains 'screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.5
Error Mode: PRE_SCREEN_ID_SCHEMA_MISMATCH

ID: 7.2.2.6
Title: screen_id not in questionnaire
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/s-111
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_SCREEN_ID_NOT_IN_QUESTIONNAIRE'; response.error.message contains 'screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.6
Error Mode: PRE_SCREEN_ID_NOT_IN_QUESTIONNAIRE

ID: 7.2.2.7
Title: target_screen_id required for move
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_TARGET_SCREEN_ID_REQUIRED_FOR_MOVE'; response.error.message contains 'target_screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.7
Error Mode: PRE_TARGET_SCREEN_ID_REQUIRED_FOR_MOVE

ID: 7.2.2.8
Title: target_screen_id schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/###
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_TARGET_SCREEN_ID_SCHEMA_MISMATCH'; response.error.message contains 'target_screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.8
Error Mode: PRE_TARGET_SCREEN_ID_SCHEMA_MISMATCH

ID: 7.2.2.9
Title: target_screen_id not in questionnaire
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/s-111
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_TARGET_SCREEN_ID_NOT_IN_QUESTIONNAIRE'; response.error.message contains 'target_screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.9
Error Mode: PRE_TARGET_SCREEN_ID_NOT_IN_QUESTIONNAIRE

ID: 7.2.2.10
Title: question_id required for operation
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTION_ID_REQUIRED_FOR_OPERATION'; response.error.message contains 'question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.10
Error Mode: PRE_QUESTION_ID_REQUIRED_FOR_OPERATION

ID: 7.2.2.11
Title: question_id schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/???
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTION_ID_SCHEMA_MISMATCH'; response.error.message contains 'question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.11
Error Mode: PRE_QUESTION_ID_SCHEMA_MISMATCH

ID: 7.2.2.12
Title: question_id not in questionnaire
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTION_ID_NOT_IN_QUESTIONNAIRE'; response.error.message contains 'question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.12
Error Mode: PRE_QUESTION_ID_NOT_IN_QUESTIONNAIRE

ID: 7.2.2.13
Title: title required for create/rename
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/screens
Headers: {}
Body: {}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_TITLE_REQUIRED_FOR_CREATE_RENAME'; response.error.message contains 'title' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.13
Error Mode: PRE_TITLE_REQUIRED_FOR_CREATE_RENAME

ID: 7.2.2.14
Title: title must be non-empty string
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/screens
Headers: {}
Body: {'title': 'New Screen'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_TITLE_NON_EMPTY_STRING'; response.error.message contains 'title' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.14
Error Mode: PRE_TITLE_NON_EMPTY_STRING

ID: 7.2.2.15
Title: title not unique
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/screens
Headers: {}
Body: {'title': 'New Screen'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_TITLE_NOT_UNIQUE'; response.error.message contains 'title' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.15
Error Mode: PRE_TITLE_NOT_UNIQUE

ID: 7.2.2.16
Title: question_text required
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTION_TEXT_REQUIRED_FOR_CREATE_UPDATE'; response.error.message contains 'question_text' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.16
Error Mode: PRE_QUESTION_TEXT_REQUIRED_FOR_CREATE_UPDATE

ID: 7.2.2.17
Title: question_text must be non-empty
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTION_TEXT_NON_EMPTY_STRING'; response.error.message contains 'question_text' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.17
Error Mode: PRE_QUESTION_TEXT_NON_EMPTY_STRING

ID: 7.2.2.18
Title: question_text schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTION_TEXT_SCHEMA_MISMATCH'; response.error.message contains 'question_text' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.18
Error Mode: PRE_QUESTION_TEXT_SCHEMA_MISMATCH

ID: 7.2.2.19
Title: hint wrong type
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_HINT_NOT_STRING_WHEN_PROVIDED'; response.error.message contains 'hint' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.19
Error Mode: PRE_HINT_NOT_STRING_WHEN_PROVIDED

ID: 7.2.2.20
Title: hint schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_HINT_SCHEMA_MISMATCH_WHEN_PROVIDED'; response.error.message contains 'hint' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.20
Error Mode: PRE_HINT_SCHEMA_MISMATCH_WHEN_PROVIDED

ID: 7.2.2.21
Title: tooltip wrong type
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_TOOLTIP_NOT_STRING_WHEN_PROVIDED'; response.error.message contains 'tooltip' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.21
Error Mode: PRE_TOOLTIP_NOT_STRING_WHEN_PROVIDED

ID: 7.2.2.22
Title: tooltip schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_TOOLTIP_SCHEMA_MISMATCH_WHEN_PROVIDED'; response.error.message contains 'tooltip' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.22
Error Mode: PRE_TOOLTIP_SCHEMA_MISMATCH_WHEN_PROVIDED

ID: 7.2.2.23
Title: proposed_position not integer ≥1
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/s-111
Headers: {}
Body: {'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PROPOSED_POSITION_NOT_INTEGER_GE_1'; response.error.message contains 'proposed_position' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.23
Error Mode: PRE_PROPOSED_POSITION_NOT_INTEGER_GE_1

ID: 7.2.2.24
Title: proposed_position exceeds max
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/s-111
Headers: {}
Body: {'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PROPOSED_POSITION_EXCEEDS_MAX'; response.error.message contains 'proposed_position' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.24
Error Mode: PRE_PROPOSED_POSITION_EXCEEDS_MAX

ID: 7.2.2.25
Title: proposed_question_order not integer ≥1
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999/position
Headers: {}
Body: {'proposed_question_order': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PROPOSED_QUESTION_ORDER_NOT_INT_GE_1'; response.error.message contains 'proposed_question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.25
Error Mode: PRE_PROPOSED_QUESTION_ORDER_NOT_INT_GE_1

ID: 7.2.2.26
Title: proposed_question_order exceeds max
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999/position
Headers: {}
Body: {'proposed_question_order': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PROPOSED_QUESTION_ORDER_EXCEEDS_MAX'; response.error.message contains 'proposed_question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.26
Error Mode: PRE_PROPOSED_QUESTION_ORDER_EXCEEDS_MAX

ID: 7.2.2.27
Title: parent_question_id required for rule
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions//visibility
Headers: {}
Body: {'parent_question_id': 'q-200', 'rule': {'visible_if_value': 'yes'}}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PARENT_QUESTION_ID_REQUIRED_FOR_RULE'; response.error.message contains 'parent_question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.27
Error Mode: PRE_PARENT_QUESTION_ID_REQUIRED_FOR_RULE

ID: 7.2.2.28
Title: parent_question_id schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/???/visibility
Headers: {}
Body: {'parent_question_id': 'q-200', 'rule': {'visible_if_value': 'yes'}}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PARENT_QUESTION_ID_SCHEMA_MISMATCH'; response.error.message contains 'parent_question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.28
Error Mode: PRE_PARENT_QUESTION_ID_SCHEMA_MISMATCH

ID: 7.2.2.29
Title: parent_question_id not found or self
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-missing-000/visibility
Headers: {}
Body: {'parent_question_id': 'q-200', 'rule': {'visible_if_value': 'yes'}}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PARENT_QUESTION_ID_NOT_FOUND_OR_SELF'; response.error.message contains 'parent_question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.29
Error Mode: PRE_PARENT_QUESTION_ID_NOT_FOUND_OR_SELF

ID: 7.2.2.30
Title: visible_if_value required for rule
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999/visibility
Headers: {}
Body: {'parent_question_id': 'q-200', 'rule': {'visible_if_value': 'yes'}}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_VISIBLE_IF_VALUE_REQUIRED_FOR_RULE'; response.error.message contains 'visible_if_value' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.30
Error Mode: PRE_VISIBLE_IF_VALUE_REQUIRED_FOR_RULE

ID: 7.2.2.31
Title: visible_if_value invalid type
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_VISIBLE_IF_VALUE_INVALID_TYPE'; response.error.message contains 'visible_if_value' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.31
Error Mode: PRE_VISIBLE_IF_VALUE_INVALID_TYPE

ID: 7.2.2.32
Title: visible_if_value out of domain
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_VISIBLE_IF_VALUE_OUT_OF_DOMAIN'; response.error.message contains 'visible_if_value' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.32
Error Mode: PRE_VISIBLE_IF_VALUE_OUT_OF_DOMAIN

ID: 7.2.2.33
Title: idempotency_key not opaque
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {'Idempotency-Key': 'idem-abc-123'}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_REQUEST_HEADERS_IDEMPOTENCY_KEY_NOT_OPAQUE'; response.error.message contains 'request_headers.idempotency_key' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.33
Error Mode: PRE_REQUEST_HEADERS_IDEMPOTENCY_KEY_NOT_OPAQUE

ID: 7.2.2.34
Title: idempotency_key schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {'Idempotency-Key': 'idem-abc-123'}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_REQUEST_HEADERS_IDEMPOTENCY_KEY_SCHEMA_MISMATCH'; response.error.message contains 'request_headers.idempotency_key' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.34
Error Mode: PRE_REQUEST_HEADERS_IDEMPOTENCY_KEY_SCHEMA_MISMATCH

ID: 7.2.2.35
Title: If-Match required on PATCH
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_REQUEST_HEADERS_IF_MATCH_REQUIRED_ON_PATCH'; response.error.message contains 'request_headers.if_match' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.35
Error Mode: PRE_REQUEST_HEADERS_IF_MATCH_REQUIRED_ON_PATCH

ID: 7.2.2.36
Title: If-Match not latest ETag
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {'If-Match': 'W/"etag-old"'}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_REQUEST_HEADERS_IF_MATCH_NOT_LATEST_ETAG'; response.error.message contains 'request_headers.if_match' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.36
Error Mode: PRE_REQUEST_HEADERS_IF_MATCH_NOT_LATEST_ETAG

ID: 7.2.2.37
Title: If-Match schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {'If-Match': 'W/"etag-old"'}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_REQUEST_HEADERS_IF_MATCH_SCHEMA_MISMATCH'; response.error.message contains 'request_headers.if_match' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.37
Error Mode: PRE_REQUEST_HEADERS_IF_MATCH_SCHEMA_MISMATCH

ID: 7.2.2.38
Title: screens[].screen_id unreadable
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/s-111
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_SCREENS_SCREEN_ID_RESOURCE_UNREADABLE'; response.error.message contains 'screens[].screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.38
Error Mode: PRE_SCREENS_SCREEN_ID_RESOURCE_UNREADABLE

ID: 7.2.2.39
Title: screens[].screen_id not found
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-missing-000/screens/s-missing-000
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_SCREENS_SCREEN_ID_NOT_FOUND'; response.error.message contains 'screens[].screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.39
Error Mode: PRE_SCREENS_SCREEN_ID_NOT_FOUND

ID: 7.2.2.40
Title: screens[].screen_id schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/###
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_SCREENS_SCREEN_ID_SCHEMA_MISMATCH'; response.error.message contains 'screens[].screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.40
Error Mode: PRE_SCREENS_SCREEN_ID_SCHEMA_MISMATCH

ID: 7.2.2.41
Title: screens[].screen_order unreadable
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_SCREENS_SCREEN_ORDER_RESOURCE_UNREADABLE'; response.error.message contains 'screens[].screen_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.41
Error Mode: PRE_SCREENS_SCREEN_ORDER_RESOURCE_UNREADABLE

ID: 7.2.2.42
Title: screens[].screen_order not integer ≥1
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_SCREENS_SCREEN_ORDER_NOT_INTEGER_GE_1'; response.error.message contains 'screens[].screen_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.42
Error Mode: PRE_SCREENS_SCREEN_ORDER_NOT_INTEGER_GE_1

ID: 7.2.2.43
Title: screens[].screen_order schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_SCREENS_SCREEN_ORDER_SCHEMA_MISMATCH'; response.error.message contains 'screens[].screen_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.43
Error Mode: PRE_SCREENS_SCREEN_ORDER_SCHEMA_MISMATCH

ID: 7.2.2.44
Title: questions[].question_id unreadable
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTIONS_QUESTION_ID_RESOURCE_UNREADABLE'; response.error.message contains 'questions[].question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.44
Error Mode: PRE_QUESTIONS_QUESTION_ID_RESOURCE_UNREADABLE

ID: 7.2.2.45
Title: questions[].question_id not found
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-missing-000
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTIONS_QUESTION_ID_NOT_FOUND'; response.error.message contains 'questions[].question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.45
Error Mode: PRE_QUESTIONS_QUESTION_ID_NOT_FOUND

ID: 7.2.2.46
Title: questions[].question_id schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/???
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTIONS_QUESTION_ID_SCHEMA_MISMATCH'; response.error.message contains 'questions[].question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.46
Error Mode: PRE_QUESTIONS_QUESTION_ID_SCHEMA_MISMATCH

ID: 7.2.2.47
Title: questions[].question_order unreadable
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTIONS_QUESTION_ORDER_RESOURCE_UNREADABLE'; response.error.message contains 'questions[].question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.47
Error Mode: PRE_QUESTIONS_QUESTION_ORDER_RESOURCE_UNREADABLE

ID: 7.2.2.48
Title: questions[].question_order not integer ≥1
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTIONS_QUESTION_ORDER_NOT_INTEGER_GE_1'; response.error.message contains 'questions[].question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.48
Error Mode: PRE_QUESTIONS_QUESTION_ORDER_NOT_INTEGER_GE_1

ID: 7.2.2.49
Title: questions[].question_order schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_QUESTIONS_QUESTION_ORDER_SCHEMA_MISMATCH'; response.error.message contains 'questions[].question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.49
Error Mode: PRE_QUESTIONS_QUESTION_ORDER_SCHEMA_MISMATCH

ID: 7.2.2.50
Title: parent_question.question_id unreadable
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PARENT_QUESTION_QUESTION_ID_RESOURCE_UNREADABLE'; response.error.message contains 'parent_question.question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.50
Error Mode: PRE_PARENT_QUESTION_QUESTION_ID_RESOURCE_UNREADABLE

ID: 7.2.2.51
Title: parent_question.question_id mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PARENT_QUESTION_QUESTION_ID_MISMATCH'; response.error.message contains 'parent_question.question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.51
Error Mode: PRE_PARENT_QUESTION_QUESTION_ID_MISMATCH

ID: 7.2.2.52
Title: parent_question.question_id schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/???
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PARENT_QUESTION_QUESTION_ID_SCHEMA_MISMATCH'; response.error.message contains 'parent_question.question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.52
Error Mode: PRE_PARENT_QUESTION_QUESTION_ID_SCHEMA_MISMATCH

ID: 7.2.2.53
Title: parent_question.answer_kind unreadable
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PARENT_QUESTION_ANSWER_KIND_RESOURCE_UNREADABLE'; response.error.message contains 'parent_question.answer_kind' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.53
Error Mode: PRE_PARENT_QUESTION_ANSWER_KIND_RESOURCE_UNREADABLE

ID: 7.2.2.54
Title: parent_question.answer_kind unsupported
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PARENT_QUESTION_ANSWER_KIND_UNSUPPORTED'; response.error.message contains 'parent_question.answer_kind' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.54
Error Mode: PRE_PARENT_QUESTION_ANSWER_KIND_UNSUPPORTED

ID: 7.2.2.55
Title: parent_question.answer_kind schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PARENT_QUESTION_ANSWER_KIND_SCHEMA_MISMATCH'; response.error.message contains 'parent_question.answer_kind' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.55
Error Mode: PRE_PARENT_QUESTION_ANSWER_KIND_SCHEMA_MISMATCH

ID: 7.2.2.56
Title: placeholder_id provider call failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_CALL_FAILED'; response.error.message contains 'placeholder_allocation_result.placeholder_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.56
Error Mode: PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_CALL_FAILED

ID: 7.2.2.57
Title: placeholder_id schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_SCHEMA_MISMATCH'; response.error.message contains 'placeholder_allocation_result.placeholder_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.57
Error Mode: PRE_PLACEHOLDER_ALLOCATION_RESULT_PLACEHOLDER_ID_SCHEMA_MISMATCH

ID: 7.2.2.58
Title: inferred_answer_kind provider call failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_CALL_FAILED'; response.error.message contains 'placeholder_allocation_result.inferred_answer_kind' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.58
Error Mode: PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_CALL_FAILED

ID: 7.2.2.59
Title: inferred_answer_kind schema mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_SCHEMA_MISMATCH'; response.error.message contains 'placeholder_allocation_result.inferred_answer_kind' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.59
Error Mode: PRE_PLACEHOLDER_ALLOCATION_RESULT_INFERRED_ANSWER_KIND_SCHEMA_MISMATCH

ID: 7.2.2.60
Title: Screen create persist failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/screens
Headers: {}
Body: {'title': 'Screen A'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_SCREEN_CREATE_PERSIST_FAILED'; response.error.message contains 'outputs.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.60
Error Mode: RUN_SCREEN_CREATE_PERSIST_FAILED

ID: 7.2.2.61
Title: Screen order assignment failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_SCREEN_ORDER_ASSIGN_FAILED'; response.error.message contains 'outputs.screen.screen_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.61
Error Mode: RUN_SCREEN_ORDER_ASSIGN_FAILED

ID: 7.2.2.62
Title: Screen serialization failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_SCREEN_SERIALIZATION_FAILED'; response.error.message contains 'outputs.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.62
Error Mode: RUN_SCREEN_SERIALIZATION_FAILED

ID: 7.2.2.63
Title: Screen ETag generation failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_SCREEN_ETAG_GEN_FAILED'; response.error.message contains 'outputs.etags.screen, outputs.etags.questionnaire' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.63
Error Mode: RUN_SCREEN_ETAG_GEN_FAILED

ID: 7.2.2.64
Title: Screen update persist failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_SCREEN_UPDATE_PERSIST_FAILED'; response.error.message contains 'outputs.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.64
Error Mode: RUN_SCREEN_UPDATE_PERSIST_FAILED

ID: 7.2.2.65
Title: Screen reindex failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_SCREEN_REINDEX_FAILED'; response.error.message contains 'outputs.screen.screen_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.65
Error Mode: RUN_SCREEN_REINDEX_FAILED

ID: 7.2.2.66
Title: Screen ETag update failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_SCREEN_ETAG_UPDATE_FAILED'; response.error.message contains 'outputs.etags.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.66
Error Mode: RUN_SCREEN_ETAG_UPDATE_FAILED

ID: 7.2.2.67
Title: Question scaffold create failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_QUESTION_SCAFFOLD_CREATE_FAILED'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.67
Error Mode: RUN_QUESTION_SCAFFOLD_CREATE_FAILED

ID: 7.2.2.68
Title: Initial question_order assignment failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_QUESTION_ORDER_ASSIGN_FAILED'; response.error.message contains 'outputs.question.question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.68
Error Mode: RUN_QUESTION_ORDER_ASSIGN_FAILED

ID: 7.2.2.69
Title: Question persist failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_QUESTION_PERSIST_FAILED'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.69
Error Mode: RUN_QUESTION_PERSIST_FAILED

ID: 7.2.2.70
Title: Question serialization failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_QUESTION_SERIALIZATION_FAILED'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.70
Error Mode: RUN_QUESTION_SERIALIZATION_FAILED

ID: 7.2.2.71
Title: Question ETag generation failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_QUESTION_ETAG_GEN_FAILED'; response.error.message contains 'outputs.etags.question, outputs.etags.screen, outputs.etags.questionnaire' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.71
Error Mode: RUN_QUESTION_ETAG_GEN_FAILED

ID: 7.2.2.72
Title: Determine answer_kind failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_DETERMINE_ANSWER_KIND_FAILED'; response.error.message contains 'outputs.question.answer_kind' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.72
Error Mode: RUN_DETERMINE_ANSWER_KIND_FAILED

ID: 7.2.2.73
Title: Persist answer_kind failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_PERSIST_ANSWER_KIND_FAILED'; response.error.message contains 'outputs.question.answer_kind' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.73
Error Mode: RUN_PERSIST_ANSWER_KIND_FAILED

ID: 7.2.2.74
Title: Typed question return failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_TYPED_QUESTION_RETURN_FAILED'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.74
Error Mode: RUN_TYPED_QUESTION_RETURN_FAILED

ID: 7.2.2.75
Title: Apply field updates failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_UPDATE_FIELDS_APPLY_FAILED'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.75
Error Mode: RUN_UPDATE_FIELDS_APPLY_FAILED

ID: 7.2.2.76
Title: Question update persist failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_QUESTION_UPDATE_PERSIST_FAILED'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.76
Error Mode: RUN_QUESTION_UPDATE_PERSIST_FAILED

ID: 7.2.2.77
Title: Question ETag update failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_QUESTION_ETAG_UPDATE_FAILED'; response.error.message contains 'outputs.etags.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.77
Error Mode: RUN_QUESTION_ETAG_UPDATE_FAILED

ID: 7.2.2.78
Title: Question reindex failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_QUESTION_REINDEX_FAILED'; response.error.message contains 'outputs.question.question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.78
Error Mode: RUN_QUESTION_REINDEX_FAILED

ID: 7.2.2.79
Title: Reorder persist failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_REORDER_PERSIST_FAILED'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.79
Error Mode: RUN_REORDER_PERSIST_FAILED

ID: 7.2.2.80
Title: Reorder result return failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_REORDER_RESULT_RETURN_FAILED'; response.error.message contains 'outputs.etags.question, outputs.question.question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.80
Error Mode: RUN_REORDER_RESULT_RETURN_FAILED

ID: 7.2.2.81
Title: Screen reorder persist failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_SCREEN_REORDER_PERSIST_FAILED'; response.error.message contains 'outputs.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.81
Error Mode: RUN_SCREEN_REORDER_PERSIST_FAILED

ID: 7.2.2.82
Title: Move assign target order failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_MOVE_ASSIGN_TARGET_ORDER_FAILED'; response.error.message contains 'outputs.question.question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.82
Error Mode: RUN_MOVE_ASSIGN_TARGET_ORDER_FAILED

ID: 7.2.2.83
Title: Move reindex source failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_MOVE_REINDEX_SOURCE_FAILED'; response.error.message contains 'outputs.question.question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.83
Error Mode: RUN_MOVE_REINDEX_SOURCE_FAILED

ID: 7.2.2.84
Title: Move persist failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_MOVE_PERSIST_FAILED'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.84
Error Mode: RUN_MOVE_PERSIST_FAILED

ID: 7.2.2.85
Title: Move result return failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_MOVE_RESULT_RETURN_FAILED'; response.error.message contains 'outputs.etags.question, outputs.question.question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.85
Error Mode: RUN_MOVE_RESULT_RETURN_FAILED

ID: 7.2.2.86
Title: Set visibility link persist failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999/visibility
Headers: {}
Body: {'parent_question_id': 'q-200', 'rule': {'visible_if_value': 'yes'}}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_SET_VISIBILITY_LINK_PERSIST_FAILED'; response.error.message contains 'outputs.question.parent_question_id, outputs.question.visible_if_value' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.86
Error Mode: RUN_SET_VISIBILITY_LINK_PERSIST_FAILED

ID: 7.2.2.87
Title: Clear visibility persist failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999/visibility
Headers: {}
Body: {'parent_question_id': 'q-200', 'rule': {'visible_if_value': 'yes'}}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_CLEAR_VISIBILITY_PERSIST_FAILED'; response.error.message contains 'outputs.question.parent_question_id, outputs.question.visible_if_value' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.87
Error Mode: RUN_CLEAR_VISIBILITY_PERSIST_FAILED

ID: 7.2.2.88
Title: Clear rule return failed
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999/visibility
Headers: {}
Body: {'parent_question_id': 'q-200', 'rule': {'visible_if_value': 'yes'}}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'RUN_CLEAR_RULE_RETURN_FAILED'; response.error.message contains 'outputs.etags.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.88
Error Mode: RUN_CLEAR_RULE_RETURN_FAILED

ID: 7.2.2.89
Title: outputs.screen context mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_CONTEXT_MISMATCH'; response.error.message contains 'outputs.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.89
Error Mode: POST_OUTPUTS_SCREEN_CONTEXT_MISMATCH

ID: 7.2.2.90
Title: outputs.screen keys incomplete
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_KEYS_INCOMPLETE'; response.error.message contains 'outputs.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.90
Error Mode: POST_OUTPUTS_SCREEN_KEYS_INCOMPLETE

ID: 7.2.2.91
Title: outputs.screen schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_SCHEMA_INVALID'; response.error.message contains 'outputs.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.91
Error Mode: POST_OUTPUTS_SCREEN_SCHEMA_INVALID

ID: 7.2.2.92
Title: screen_id missing
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_SCREEN_ID_MISSING'; response.error.message contains 'outputs.screen.screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.92
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ID_MISSING

ID: 7.2.2.93
Title: screen_id schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/###
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_SCREEN_ID_SCHEMA_INVALID'; response.error.message contains 'outputs.screen.screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.93
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ID_SCHEMA_INVALID

ID: 7.2.2.94
Title: screen_id mutated
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/s-111
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_SCREEN_ID_MUTATED'; response.error.message contains 'outputs.screen.screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.94
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ID_MUTATED

ID: 7.2.2.95
Title: screen title missing
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/screens
Headers: {}
Body: {}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_TITLE_MISSING'; response.error.message contains 'outputs.screen.title' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.95
Error Mode: POST_OUTPUTS_SCREEN_TITLE_MISSING

ID: 7.2.2.96
Title: screen title schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/screens
Headers: {}
Body: {'title': 123}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_TITLE_SCHEMA_INVALID'; response.error.message contains 'outputs.screen.title' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.96
Error Mode: POST_OUTPUTS_SCREEN_TITLE_SCHEMA_INVALID

ID: 7.2.2.97
Title: screen title not latest
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/screens
Headers: {}
Body: {'title': 'New Screen'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_TITLE_NOT_LATEST'; response.error.message contains 'outputs.screen.title' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.97
Error Mode: POST_OUTPUTS_SCREEN_TITLE_NOT_LATEST

ID: 7.2.2.98
Title: screen_order missing
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_SCREEN_ORDER_MISSING'; response.error.message contains 'outputs.screen.screen_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.98
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ORDER_MISSING

ID: 7.2.2.99
Title: screen_order schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_SCREEN_ORDER_SCHEMA_INVALID'; response.error.message contains 'outputs.screen.screen_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.99
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ORDER_SCHEMA_INVALID

ID: 7.2.2.100
Title: screen_order not positive
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_SCREEN_ORDER_NOT_POSITIVE'; response.error.message contains 'outputs.screen.screen_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.100
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ORDER_NOT_POSITIVE

ID: 7.2.2.101
Title: screen_order sequence broken
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_SCREEN_SCREEN_ORDER_SEQUENCE_BROKEN'; response.error.message contains 'outputs.screen.screen_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.101
Error Mode: POST_OUTPUTS_SCREEN_SCREEN_ORDER_SEQUENCE_BROKEN

ID: 7.2.2.102
Title: outputs.question context mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_CONTEXT_MISMATCH'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.102
Error Mode: POST_OUTPUTS_QUESTION_CONTEXT_MISMATCH

ID: 7.2.2.103
Title: outputs.question keys incomplete
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_KEYS_INCOMPLETE'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.103
Error Mode: POST_OUTPUTS_QUESTION_KEYS_INCOMPLETE

ID: 7.2.2.104
Title: outputs.question schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_SCHEMA_INVALID'; response.error.message contains 'outputs.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.104
Error Mode: POST_OUTPUTS_QUESTION_SCHEMA_INVALID

ID: 7.2.2.105
Title: question_id missing
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_QUESTION_ID_MISSING'; response.error.message contains 'outputs.question.question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.105
Error Mode: POST_OUTPUTS_QUESTION_QUESTION_ID_MISSING

ID: 7.2.2.106
Title: question_id schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/???
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_QUESTION_ID_SCHEMA_INVALID'; response.error.message contains 'outputs.question.question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.106
Error Mode: POST_OUTPUTS_QUESTION_QUESTION_ID_SCHEMA_INVALID

ID: 7.2.2.107
Title: question_id mutated
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999
Headers: {}
Body: {'question_text': 'Updated text'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_QUESTION_ID_MUTATED'; response.error.message contains 'outputs.question.question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.107
Error Mode: POST_OUTPUTS_QUESTION_QUESTION_ID_MUTATED

ID: 7.2.2.108
Title: screen_id missing in question
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_SCREEN_ID_MISSING'; response.error.message contains 'outputs.question.screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.108
Error Mode: POST_OUTPUTS_QUESTION_SCREEN_ID_MISSING

ID: 7.2.2.109
Title: screen_id schema invalid in question
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/###
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_SCREEN_ID_SCHEMA_INVALID'; response.error.message contains 'outputs.question.screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.109
Error Mode: POST_OUTPUTS_QUESTION_SCREEN_ID_SCHEMA_INVALID

ID: 7.2.2.110
Title: screen_id not latest
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questionnaires/q-12345/screens/s-111
Headers: {}
Body: {'title': 'Renamed Screen', 'proposed_position': 2}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_SCREEN_ID_NOT_LATEST'; response.error.message contains 'outputs.question.screen_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.110
Error Mode: POST_OUTPUTS_QUESTION_SCREEN_ID_NOT_LATEST

ID: 7.2.2.111
Title: question_text missing
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_TEXT_MISSING'; response.error.message contains 'outputs.question.question_text' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.111
Error Mode: POST_OUTPUTS_QUESTION_TEXT_MISSING

ID: 7.2.2.112
Title: question_text schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_TEXT_SCHEMA_INVALID'; response.error.message contains 'outputs.question.question_text' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.112
Error Mode: POST_OUTPUTS_QUESTION_TEXT_SCHEMA_INVALID

ID: 7.2.2.113
Title: question_text not latest
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_TEXT_NOT_LATEST'; response.error.message contains 'outputs.question.question_text' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.113
Error Mode: POST_OUTPUTS_QUESTION_TEXT_NOT_LATEST

ID: 7.2.2.114
Title: answer_kind schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_ANSWER_KIND_SCHEMA_INVALID'; response.error.message contains 'outputs.question.answer_kind' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.114
Error Mode: POST_OUTPUTS_QUESTION_ANSWER_KIND_SCHEMA_INVALID

ID: 7.2.2.115
Title: question_order missing
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_ORDER_MISSING'; response.error.message contains 'outputs.question.question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.115
Error Mode: POST_OUTPUTS_QUESTION_ORDER_MISSING

ID: 7.2.2.116
Title: question_order schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_ORDER_SCHEMA_INVALID'; response.error.message contains 'outputs.question.question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.116
Error Mode: POST_OUTPUTS_QUESTION_ORDER_SCHEMA_INVALID

ID: 7.2.2.117
Title: question_order not positive
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_ORDER_NOT_POSITIVE'; response.error.message contains 'outputs.question.question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.117
Error Mode: POST_OUTPUTS_QUESTION_ORDER_NOT_POSITIVE

ID: 7.2.2.118
Title: question_order sequence broken
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_QUESTION_ORDER_SEQUENCE_BROKEN'; response.error.message contains 'outputs.question.question_order' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.118
Error Mode: POST_OUTPUTS_QUESTION_ORDER_SEQUENCE_BROKEN

ID: 7.2.2.119
Title: parent_question_id schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/???/visibility
Headers: {}
Body: {'parent_question_id': 'q-200', 'rule': {'visible_if_value': 'yes'}}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_PARENT_QUESTION_ID_SCHEMA_INVALID'; response.error.message contains 'outputs.question.parent_question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.119
Error Mode: POST_OUTPUTS_PARENT_QUESTION_ID_SCHEMA_INVALID

ID: 7.2.2.120
Title: parent_question_id not null when cleared
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP PATCH /api/v1/authoring/questions/qn-999/visibility
Headers: {}
Body: {'parent_question_id': 'q-200', 'rule': {'visible_if_value': 'yes'}}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_PARENT_QUESTION_ID_NOT_NULL_WHEN_CLEARED'; response.error.message contains 'outputs.question.parent_question_id' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.120
Error Mode: POST_OUTPUTS_PARENT_QUESTION_ID_NOT_NULL_WHEN_CLEARED

ID: 7.2.2.121
Title: visible_if_value schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_VISIBLE_IF_VALUE_SCHEMA_INVALID'; response.error.message contains 'outputs.question.visible_if_value' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.121
Error Mode: POST_OUTPUTS_VISIBLE_IF_VALUE_SCHEMA_INVALID

ID: 7.2.2.122
Title: visible_if_value not null when cleared
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_VISIBLE_IF_VALUE_NOT_NULL_WHEN_CLEARED'; response.error.message contains 'outputs.question.visible_if_value' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.122
Error Mode: POST_OUTPUTS_VISIBLE_IF_VALUE_NOT_NULL_WHEN_CLEARED

ID: 7.2.2.123
Title: visible_if_value domain mismatch
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_VISIBLE_IF_VALUE_DOMAIN_MISMATCH'; response.error.message contains 'outputs.question.visible_if_value' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.123
Error Mode: POST_OUTPUTS_VISIBLE_IF_VALUE_DOMAIN_MISMATCH

ID: 7.2.2.124
Title: etags missing for write
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_MISSING_FOR_WRITE'; response.error.message contains 'outputs.etags' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.124
Error Mode: POST_OUTPUTS_ETAGS_MISSING_FOR_WRITE

ID: 7.2.2.125
Title: etags keys incomplete
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_KEYS_INCOMPLETE'; response.error.message contains 'outputs.etags' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.125
Error Mode: POST_OUTPUTS_ETAGS_KEYS_INCOMPLETE

ID: 7.2.2.126
Title: etags schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_SCHEMA_INVALID'; response.error.message contains 'outputs.etags' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.126
Error Mode: POST_OUTPUTS_ETAGS_SCHEMA_INVALID

ID: 7.2.2.127
Title: etags include unaffected entities
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_KEYS_INCLUDE_UNAFFECTED'; response.error.message contains 'outputs.etags' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.127
Error Mode: POST_OUTPUTS_ETAGS_KEYS_INCLUDE_UNAFFECTED

ID: 7.2.2.128
Title: question etag schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_QUESTION_SCHEMA_INVALID'; response.error.message contains 'outputs.etags.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.128
Error Mode: POST_OUTPUTS_ETAGS_QUESTION_SCHEMA_INVALID

ID: 7.2.2.129
Title: question etag empty
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_QUESTION_EMPTY'; response.error.message contains 'outputs.etags.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.129
Error Mode: POST_OUTPUTS_ETAGS_QUESTION_EMPTY

ID: 7.2.2.130
Title: question etag not changed on update
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_QUESTION_NOT_CHANGED_ON_UPDATE'; response.error.message contains 'outputs.etags.question' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.130
Error Mode: POST_OUTPUTS_ETAGS_QUESTION_NOT_CHANGED_ON_UPDATE

ID: 7.2.2.131
Title: screen etag schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_SCREEN_SCHEMA_INVALID'; response.error.message contains 'outputs.etags.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.131
Error Mode: POST_OUTPUTS_ETAGS_SCREEN_SCHEMA_INVALID

ID: 7.2.2.132
Title: screen etag empty
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_SCREEN_EMPTY'; response.error.message contains 'outputs.etags.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.132
Error Mode: POST_OUTPUTS_ETAGS_SCREEN_EMPTY

ID: 7.2.2.133
Title: screen etag not changed on update
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_SCREEN_NOT_CHANGED_ON_UPDATE'; response.error.message contains 'outputs.etags.screen' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.133
Error Mode: POST_OUTPUTS_ETAGS_SCREEN_NOT_CHANGED_ON_UPDATE

ID: 7.2.2.134
Title: questionnaire etag schema invalid
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_QUESTIONNAIRE_SCHEMA_INVALID'; response.error.message contains 'outputs.etags.questionnaire' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.134
Error Mode: POST_OUTPUTS_ETAGS_QUESTIONNAIRE_SCHEMA_INVALID

ID: 7.2.2.135
Title: questionnaire etag empty
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_QUESTIONNAIRE_EMPTY'; response.error.message contains 'outputs.etags.questionnaire' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.135
Error Mode: POST_OUTPUTS_ETAGS_QUESTIONNAIRE_EMPTY

ID: 7.2.2.136
Title: questionnaire etag not changed on update
Purpose: Verify that the specified invalid condition triggers the documented error mode and prevents downstream processing.
Test Data: HTTP POST /api/v1/authoring/questionnaires/q-12345/questions
Headers: {}
Body: {'screen_id': 's-111', 'question_text': 'Q1'}
Mocking: Mock external boundaries only — persistence gateways (ScreenRepo, QuestionRepo) and event publisher are stubbed and asserted not-called; no internal logic is mocked; mocks record invocation counts and arguments for verification.
Assertions: HTTP status == 400; response.status == 'error'; response.error.code == 'POST_OUTPUTS_ETAGS_QUESTIONNAIRE_NOT_CHANGED_ON_UPDATE'; response.error.message contains 'outputs.etags.questionnaire' if applicable; persistence gateways recorded 0 invocations; no side effects observed.
AC-Ref: 6.2.2.136
Error Mode: POST_OUTPUTS_ETAGS_QUESTIONNAIRE_NOT_CHANGED_ON_UPDATE

7.3.1.1 — Create screen → Rename/Reposition
Purpose: Verify that after a successful screen create, initiating a rename or re-position triggers the rename/position step.
Test Data: questionnaire_id="11111111-1111-1111-1111-111111111111", create-screen request {title:"Intro"}; subsequent rename/position request {title:"Introduction", proposed_position:1}.
Mocking: No external dependencies mocked. Attach a spy to the public entrypoint for STEP-2 Rename screen and set position to observe invocation (observation only; does not alter behaviour).
Assertions: Assert invoked once immediately after STEP-1 Create screen completes, and not before.
AC-Ref: 6.3.1.1.

7.3.1.2 — Create screen → Create question
Purpose: Verify that after a successful screen create, a create-question request triggers the question creation step.
Test Data: questionnaire_id="11111111-1111-1111-1111-111111111111", screen_id="S-001", create-question request {screen_id:"S-001", question_text:"Your name?"}.
Mocking: No external dependencies mocked. Attach a spy to the public entrypoint for STEP-3 Create question.
Assertions: Assert invoked once immediately after STEP-1 Create screen completes, and not before.
AC-Ref: 6.3.1.2.

7.3.1.3 — Create screen → Reorder screens
Purpose: Verify that after a successful screen create, proposing a new position triggers screen reordering.
Test Data: questionnaire_id="11111111-1111-1111-1111-111111111111", propose {proposed_position:2} for newly created screen S-002.
Mocking: No external dependencies mocked. Attach a spy to the public entrypoint for STEP-6 Reorder screens.
Assertions: Assert invoked once immediately after STEP-1 Create screen completes, and not before.
AC-Ref: 6.3.1.3.

7.3.1.4 — Rename/Reposition → Reorder screens
Purpose: Verify that after a successful rename/reposition, proposing an additional position change triggers screen reordering.
Test Data: questionnaire_id="11111111-1111-1111-1111-111111111111", rename/position applied to S-001; follow-up {proposed_position:3}.
Mocking: No external dependencies mocked. Attach a spy to STEP-6 Reorder screens.
Assertions: Assert invoked once immediately after STEP-2 Rename screen and set position completes, and not before.
AC-Ref: 6.3.1.4.

7.3.1.5 — Rename/Reposition → Create question
Purpose: Verify that after a successful rename/reposition, a create-question request triggers question creation.
Test Data: questionnaire_id="1111…1111", screen_id="S-001", create-question {screen_id:"S-001", question_text:"Date of birth?"}.
Mocking: No external dependencies mocked. Attach a spy to STEP-3 Create question.
Assertions: Assert invoked once immediately after STEP-2 Rename screen and set position completes, and not before.
AC-Ref: 6.3.1.5.

7.3.1.6 — Create question → Allocate first placeholder
Purpose: Verify that after a successful question scaffold create, allocating the first placeholder triggers the placeholder allocation step.
Test Data: question_id="Q-001", allocate-placeholder request {placeholder_id:"PH-001", context:"bind enum options"}.
Mocking: No external dependencies mocked. Attach a spy to STEP-3A Allocate first placeholder.
Assertions: Assert invoked once immediately after STEP-3 Create question completes, and not before.
AC-Ref: 6.3.1.6.

7.3.1.7 — Create question → Update question
Purpose: Verify that after a successful question create, an update request triggers the question-update step.
Test Data: question_id="Q-001", update {question_text:"What is your full name?"}.
Mocking: No external dependencies mocked. Attach a spy to STEP-4 Update question text.
Assertions: Assert invoked once immediately after STEP-3 Create question completes, and not before.
AC-Ref: 6.3.1.7.

7.3.1.8 — Create question → Reorder within screen
Purpose: Verify that after a successful question create, proposing a new question position triggers in-screen reordering.
Test Data: question_id="Q-002", reorder {proposed_question_order:1} within screen_id="S-001".
Mocking: No external dependencies mocked. Attach a spy to STEP-5 Reorder questions within a screen.
Assertions: Assert invoked once immediately after STEP-3 Create question completes, and not before.
AC-Ref: 6.3.1.8.

**7.3.1.9 — Create question → Move between screens**
**Purpose:** Verify that after a successful question create, a move request triggers the cross-screen move step.
**Test Data:** `question_id="Q-003"`, created on `screen_id="S-001"`; move request `{screen_id:"S-002"}`.
**Mocking:** No external dependencies mocked. Attach a spy to the public entrypoint for **STEP-7 Move question between screens** to observe invocation (observation only).
**Assertions:** *Assert invoked once immediately after STEP-3 Create question completes, and not before.*
**AC-Ref:** 6.3.1.9

---

**7.3.1.10 — Allocate first placeholder → Update question**
**Purpose:** Verify that after allocating the first placeholder, a question update request triggers the update step.
**Test Data:** `question_id="Q-004"`; placeholder allocation `{placeholder_id:"PH-101"}` then update `{question_text:"Revised wording"}`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-4 Update question text**.
**Assertions:** *Assert invoked once immediately after STEP-3A Allocate first placeholder completes, and not before.*
**AC-Ref:** 6.3.1.10

---

**7.3.1.11 — Allocate first placeholder → Reorder within screen**
**Purpose:** Verify that after allocating the first placeholder, proposing a new position triggers in-screen reorder.
**Test Data:** `question_id="Q-005"`, current `screen_id="S-001"`; reorder request `{proposed_question_order:1}`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-5 Reorder questions within a screen**.
**Assertions:** *Assert invoked once immediately after STEP-3A Allocate first placeholder completes, and not before.*
**AC-Ref:** 6.3.1.11

---

**7.3.1.12 — Update question → Reorder within screen**
**Purpose:** Verify that after a successful question update, proposing a new position triggers in-screen reorder.
**Test Data:** `question_id="Q-006"`; update `{question_text:"Clarified text"}` then reorder `{proposed_question_order:2}`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-5 Reorder questions within a screen**.
**Assertions:** *Assert invoked once immediately after STEP-4 Update question text completes, and not before.*
**AC-Ref:** 6.3.1.12

---

**7.3.1.13 — Update question → Move between screens**
**Purpose:** Verify that after a successful question update, a move request triggers cross-screen move.
**Test Data:** `question_id="Q-007"`; update `{question_text:"Updated"}` then move `{screen_id:"S-003"}`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-7 Move question between screens**.
**Assertions:** *Assert invoked once immediately after STEP-4 Update question text completes, and not before.*
**AC-Ref:** 6.3.1.13

---

**7.3.1.14 — Reorder within screen → Move between screens**
**Purpose:** Verify that after an in-screen reorder, a move request triggers cross-screen move.
**Test Data:** `question_id="Q-008"`; reorder `{proposed_question_order:3}` then move `{screen_id:"S-004"}`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-7 Move question between screens**.
**Assertions:** *Assert invoked once immediately after STEP-5 Reorder questions within a screen completes, and not before.*
**AC-Ref:** 6.3.1.14

---

**7.3.1.15 — Reorder within screen → Set conditional parent**
**Purpose:** Verify that after an in-screen reorder, a visibility-parent update triggers the set-parent step.
**Test Data:** `question_id="Q-009"`, set visibility `{parent_question_id:"Q-001", rule:{visible_if_value:["Yes"]}}`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-8 Set conditional parent**.
**Assertions:** *Assert invoked once immediately after STEP-5 Reorder questions within a screen completes, and not before.*
**AC-Ref:** 6.3.1.15

---

**7.3.1.16 — Reorder screens → Move between screens**
**Purpose:** Verify that after a screen reorder, a question move request triggers cross-screen move.
**Test Data:** Reorder screen `S-002` to position `1`, then move `question_id="Q-010"` to `screen_id:"S-002"`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-7 Move question between screens**.
**Assertions:** *Assert invoked once immediately after STEP-6 Reorder screens completes, and not before.*
**AC-Ref:** 6.3.1.16

---

**7.3.1.17 — Move between screens → Reorder within target screen**
**Purpose:** Verify that after a cross-screen move, proposing an order on the target screen triggers in-screen reorder.
**Test Data:** Move `question_id="Q-011"` to `screen_id:"S-005"`, then reorder `{proposed_question_order:2}` on `S-005`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-5 Reorder questions within a screen**.
**Assertions:** *Assert invoked once immediately after STEP-7 Move question between screens completes, and not before.*
**AC-Ref:** 6.3.1.17

---

**7.3.1.18 — Move between screens → Set conditional parent**
**Purpose:** Verify that after a cross-screen move, a visibility-parent update triggers the set-parent step.
**Test Data:** Move `question_id="Q-012"` to `screen_id:"S-006"`, then set visibility `{parent_question_id:"Q-003", rule:{visible_if_value:["No"]}}`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-8 Set conditional parent**.
**Assertions:** *Assert invoked once immediately after STEP-7 Move question between screens completes, and not before.*
**AC-Ref:** 6.3.1.18

---

**7.3.1.19 — Set conditional parent → Clear conditional parent**
**Purpose:** Verify that after setting a conditional parent, a clear request triggers the clear-parent step.
**Test Data:** For `question_id="Q-013"`, set parent `{parent_question_id:"Q-004", rule:{visible_if_value:["Yes"]}}`, then clear `{parent_question_id:null, rule:null}`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-9 Clear conditional parent**.
**Assertions:** *Assert invoked once immediately after STEP-8 Set conditional parent completes, and not before.*
**AC-Ref:** 6.3.1.19

---

**7.3.1.20 — Clear conditional parent → Set conditional parent**
**Purpose:** Verify that after clearing a conditional parent, a subsequent set request triggers the set-parent step.
**Test Data:** For `question_id="Q-014"`, clear `{parent_question_id:null, rule:null}`, then set `{parent_question_id:"Q-005", rule:{visible_if_value:["Yes"]}}`.
**Mocking:** No external dependencies mocked. Attach a spy to **STEP-8 Set conditional parent**.
**Assertions:** *Assert invoked once immediately after STEP-9 Clear conditional parent completes, and not before.*
**AC-Ref:** 6.3.1.20

# 7.3.2 Sad Path Behavioural Tests — Runtime Execution (RUN_*)

## 7.3.2.1
**Title:** Create screen write failure halts STEP-1 and prevents STEP-2  
**Purpose:** Verify that a DB write failure during screen creation halts the operation and prevents renaming/repositioning flow.  
**Test Data:** `POST /api/v1/authoring/questionnaires/Q-001/screens` with JSON body `{ "title": "Eligibility" }`, header `Idempotency-Key: ik-001`.  
**Mocking:** Mock `ScreensRepository.create(title, questionnaire_id)` to raise `WriteError("insert failed")` once. Boundary: database write. Assert mock called once with `(title="Eligibility", questionnaire_id="Q-001")`.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Create screen** raises, and not before. Assert **STEP-2 Rename screen and set position** is not invoked following the failure. Assert that error mode **RUN_CREATE_ENTITY_DB_WRITE_FAILED** is observed.  
**AC-Ref:** 6.3.2.1  
**Error Mode:** RUN_CREATE_ENTITY_DB_WRITE_FAILED

---

## 7.3.2.2
**Title:** Create screen problem+json encoding failure blocks finalisation and prevents STEP-2  
**Purpose:** Verify that problem+json serialisation failure blocks finalisation of create and prevents the next step.  
**Test Data:** Same as 7.3.2.1 with an earlier handled error path producing an error envelope.  
**Mocking:** Mock `ProblemJson.encode(error)` to raise `EncodingError("problem+json")` once after the handler prepares an error object. Boundary: error rendering. Assert encoder called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-1 Create screen** finalisation raises, and not before. Assert **STEP-2 Rename screen and set position** is not invoked following the failure. Assert that error mode **RUN_PROBLEM_JSON_ENCODING_FAILED** is observed.  
**AC-Ref:** 6.3.2.2  
**Error Mode:** RUN_PROBLEM_JSON_ENCODING_FAILED

---

## 7.3.2.3
**Title:** Rename screen update failure halts STEP-2 and prevents STEP-3  
**Purpose:** Verify that a DB update failure during rename/reposition halts the operation and prevents question creation.  
**Test Data:** `PATCH /api/v1/authoring/questionnaires/Q-001/screens/S-001` with body `{ "title": "Overview" }`, header `If-Match: W/"etag-s-001"`.  
**Mocking:** Mock `ScreensRepository.update(screen_id, title, position)` to raise `WriteError("update failed")`. Boundary: database write. Assert called once with `("S-001","Overview",None)`.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Rename screen and set position** raises, and not before. Assert **STEP-3 Create question** is not invoked following the failure. Assert that error mode **RUN_UPDATE_ENTITY_DB_WRITE_FAILED** is observed.  
**AC-Ref:** 6.3.2.3  
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED

---

## 7.3.2.4
**Title:** Reorder screens resequence computation failure halts STEP-2 and prevents STEP-3  
**Purpose:** Verify that runtime resequencing computation failure halts rename/position and prevents question creation.  
**Test Data:** `PATCH /api/v1/authoring/questionnaires/Q-001/screens/S-002` with body `{ "proposed_position": 1 }`, header `If-Match: W/"etag-s-002"`.  
**Mocking:** Mock `OrderingService.resequenceScreens(questionnaire_id)` to raise `ComputationError("non-contiguous")`. Boundary: sequencing algorithm. Assert called once with `("Q-001")`.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Rename screen and set position** finalisation raises, and not before. Assert **STEP-3 Create question** is not invoked following the failure. Assert that error mode **RUN_RESEQUENCE_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.4  
**Error Mode:** RUN_RESEQUENCE_COMPUTE_FAILED

---

## 7.3.2.5
**Title:** Rename screen ETag computation failure blocks finalisation and prevents STEP-3  
**Purpose:** Verify that ETag compute failure blocks completion of STEP-2 and prevents question creation.  
**Test Data:** Same request as 7.3.2.3.  
**Mocking:** Mock `ETag.compute(entity)` to raise `ComputeError("etag")` once after DB change succeeds. Boundary: version hashing. Assert called once with the updated screen entity.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Rename screen and set position** finalisation raises, and not before. Assert **STEP-3 Create question** is not invoked following the failure. Assert that error mode **RUN_ETAG_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.5  
**Error Mode:** RUN_ETAG_COMPUTE_FAILED

---

## 7.3.2.6
**Title:** Concurrency token generation failure blocks finalisation of STEP-2 and prevents STEP-3  
**Purpose:** Verify that generating a concurrency token during STEP-2 fails and blocks the next step.  
**Test Data:** Same request as 7.3.2.3 with `If-Match` present.  
**Mocking:** Mock `ConcurrencyTokens.issue()` to raise `TokenError("issue failed")` after successful update. Boundary: token generator. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-2 Rename screen and set position** finalisation raises, and not before. Assert **STEP-3 Create question** is not invoked following the failure. Assert that error mode **RUN_CONCURRENCY_TOKEN_GENERATION_FAILED** is observed.  
**AC-Ref:** 6.3.2.6  
**Error Mode:** RUN_CONCURRENCY_TOKEN_GENERATION_FAILED

---

## 7.3.2.7
**Title:** Create question write failure halts STEP-3 and prevents STEP-4  
**Purpose:** Verify DB write failure during question creation halts and prevents text update step.  
**Test Data:** `POST /api/v1/authoring/questionnaires/Q-001/questions` with body `{ "screen_id": "S-001", "question_text": "What is your name?" }`, header `Idempotency-Key: ik-002`.  
**Mocking:** Mock `QuestionsRepository.create(screen_id, text)` to raise `WriteError("insert failed")` once. Boundary: database write. Assert called once with `("S-001","What is your name?")`.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-3 Create question** raises, and not before. Assert **STEP-4 Update question text** is not invoked following the failure. Assert that error mode **RUN_CREATE_ENTITY_DB_WRITE_FAILED** is observed.  
**AC-Ref:** 6.3.2.7  
**Error Mode:** RUN_CREATE_ENTITY_DB_WRITE_FAILED

---

## 7.3.2.8
**Title:** Create question ETag computation failure blocks finalisation and prevents STEP-4  
**Purpose:** Verify ETag compute failure blocks completion of question creation and prevents text update flow.  
**Test Data:** Same request as 7.3.2.7.  
**Mocking:** Mock `ETag.compute(entity)` to raise `ComputeError("etag")` once after DB insert succeeds. Boundary: version hashing. Assert called once with created question entity.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-3 Create question** finalisation raises, and not before. Assert **STEP-4 Update question text** is not invoked following the failure. Assert that error mode **RUN_ETAG_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.8  
**Error Mode:** RUN_ETAG_COMPUTE_FAILED

---

## 7.3.2.9
**Title:** Idempotency backend unavailable halts STEP-3 and prevents STEP-4  
**Purpose:** Verify idempotency-store outage halts create question and prevents text update flow.  
**Test Data:** Same request as 7.3.2.7.  
**Mocking:** Mock `IdempotencyStore.checkAndPut(key)` to raise `ConnectionError("unavailable")` before write. Boundary: idempotency store. Assert called once with `("ik-002")`.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-3 Create question** raises, and not before. Assert **STEP-4 Update question text** is not invoked following the failure. Assert that error mode **RUN_IDEMPOTENCY_STORE_UNAVAILABLE** is observed.  
**AC-Ref:** 6.3.2.9  
**Error Mode:** RUN_IDEMPOTENCY_STORE_UNAVAILABLE

---

## 7.3.2.10
**Title:** Update question write failure halts STEP-4 and prevents STEP-5  
**Purpose:** Verify DB update failure during question text update halts and prevents reorder.  
**Test Data:** `PATCH /api/v1/authoring/questions/QST-101` with body `{ "question_text": "Preferred name?" }`, header `If-Match: W/"etag-q-101"`.  
**Mocking:** Mock `QuestionsRepository.updateText(question_id, text)` to raise `WriteError("update failed")`. Boundary: database write. Assert called once with `("QST-101","Preferred name?")`.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-4 Update question text** raises, and not before. Assert **STEP-5 Reorder questions within a screen** is not invoked following the failure. Assert that error mode **RUN_UPDATE_ENTITY_DB_WRITE_FAILED** is observed.  
**AC-Ref:** 6.3.2.10  
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED

---

## 7.3.2.11
**Title:** Update question ETag computation failure blocks finalisation and prevents STEP-5  
**Purpose:** Verify ETag compute failure blocks completion of text update and prevents reorder.  
**Test Data:** Same as 7.3.2.10.  
**Mocking:** Mock `ETag.compute(entity)` to raise `ComputeError("etag")` after update succeeds. Boundary: version hashing. Assert called once with updated question entity.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-4 Update question text** finalisation raises, and not before. Assert **STEP-5 Reorder questions within a screen** is not invoked following the failure. Assert that error mode **RUN_ETAG_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.11  
**Error Mode:** RUN_ETAG_COMPUTE_FAILED

---

## 7.3.2.12
**Title:** Concurrency token generation failure blocks finalisation of STEP-4 and prevents STEP-5  
**Purpose:** Verify generating a new concurrency token fails and blocks reorder step.  
**Test Data:** Same as 7.3.2.10 with `If-Match` present.  
**Mocking:** Mock `ConcurrencyTokens.issue()` to raise `TokenError("issue failed")` after DB update. Boundary: token generator. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-4 Update question text** finalisation raises, and not before. Assert **STEP-5 Reorder questions within a screen** is not invoked following the failure. Assert that error mode **RUN_CONCURRENCY_TOKEN_GENERATION_FAILED** is observed.  
**AC-Ref:** 6.3.2.12  
**Error Mode:** RUN_CONCURRENCY_TOKEN_GENERATION_FAILED

---

## 7.3.2.13
**Title:** Reorder questions resequence computation failure halts STEP-5 and prevents STEP-6  
**Purpose:** Verify that resequencing computation failure for questions halts reorder and prevents screen reordering.  
**Test Data:** `PATCH /api/v1/authoring/questions/QST-201/position` with body `{ "proposed_question_order": 1 }`, header `If-Match: W/"etag-q-201"`.  
**Mocking:** Mock `OrderingService.resequenceQuestions(screen_id)` to raise `ComputationError("duplicate index")`. Boundary: sequencing algorithm. Assert called once with the question’s `screen_id`.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-5 Reorder questions within a screen** raises, and not before. Assert **STEP-6 Reorder screens** is not invoked following the failure. Assert that error mode **RUN_RESEQUENCE_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.13  
**Error Mode:** RUN_RESEQUENCE_COMPUTE_FAILED

---

## 7.3.2.14
**Title:** Reorder questions sequence persist failure halts STEP-5 and prevents STEP-6  
**Purpose:** Verify DB write failure persisting new question order halts reorder and prevents screen reordering.  
**Test Data:** Same as 7.3.2.13.  
**Mocking:** Mock `QuestionsRepository.persistOrder(screen_id, sequence)` to raise `WriteError("bulk update failed")`. Boundary: database write. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-5 Reorder questions within a screen** raises, and not before. Assert **STEP-6 Reorder screens** is not invoked following the failure. Assert that error mode **RUN_UPDATE_ENTITY_DB_WRITE_FAILED** is observed.  
**AC-Ref:** 6.3.2.14  
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED

---

## 7.3.2.15
**Title:** Reorder questions ETag computation failure blocks finalisation and prevents STEP-6  
**Purpose:** Verify ETag compute failure after reorder blocks completion and prevents screen reordering.  
**Test Data:** Same as 7.3.2.13.  
**Mocking:** Mock `ETag.compute(screen)` to raise `ComputeError("etag")` once after resequence persisted. Boundary: version hashing. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-5 Reorder questions within a screen** finalisation raises, and not before. Assert **STEP-6 Reorder screens** is not invoked following the failure. Assert that error mode **RUN_ETAG_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.15  
**Error Mode:** RUN_ETAG_COMPUTE_FAILED

---

## 7.3.2.16
**Title:** Reorder screens persist failure halts STEP-6 and prevents STEP-7  
**Purpose:** Verify DB write failure persisting screen order halts and prevents move.  
**Test Data:** `PATCH /api/v1/authoring/questionnaires/Q-001/screens/S-003` with body `{ "proposed_position": 2 }`, header `If-Match: W/"etag-s-003"`.  
**Mocking:** Mock `ScreensRepository.persistOrder(questionnaire_id, sequence)` to raise `WriteError("bulk update failed")`. Boundary: database write. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-6 Reorder screens** raises, and not before. Assert **STEP-7 Move question between screens** is not invoked following the failure. Assert that error mode **RUN_UPDATE_ENTITY_DB_WRITE_FAILED** is observed.  
**AC-Ref:** 6.3.2.16  
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED

---

## 7.3.2.17
**Title:** Reorder screens read failure halts STEP-6 and prevents STEP-7  
**Purpose:** Verify read failure retrieving current screens halts reorder and prevents move.  
**Test Data:** Same as 7.3.2.16.  
**Mocking:** Mock `ScreensRepository.list(questionnaire_id)` to raise `ReadError("timeout")`. Boundary: database read. Assert called once with `("Q-001")`.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-6 Reorder screens** raises, and not before. Assert **STEP-7 Move question between screens** is not invoked following the failure. Assert that error mode **RUN_RETRIEVE_ENTITY_DB_READ_FAILED** is observed.  
**AC-Ref:** 6.3.2.17  
**Error Mode:** RUN_RETRIEVE_ENTITY_DB_READ_FAILED

---

## 7.3.2.18
**Title:** Move question read failure halts STEP-7 and prevents STEP-8  
**Purpose:** Verify read failure on source/target screens halts move and prevents setting parent.  
**Test Data:** `PATCH /api/v1/authoring/questions/QST-301/position` with body `{ "screen_id": "S-010", "proposed_question_order": 1 }`, header `If-Match: W/"etag-q-301"`.  
**Mocking:** Mock `ScreensRepository.get("S-010")` to raise `ReadError("not found")`. Boundary: database read. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-7 Move question between screens** raises, and not before. Assert **STEP-8 Set conditional parent** is not invoked following the failure. Assert that error mode **RUN_RETRIEVE_ENTITY_DB_READ_FAILED** is observed.  
**AC-Ref:** 6.3.2.18  
**Error Mode:** RUN_RETRIEVE_ENTITY_DB_READ_FAILED

---

## 7.3.2.19
**Title:** Move question persist failure halts STEP-7 and prevents STEP-8  
**Purpose:** Verify DB write failure when moving halts and prevents setting parent.  
**Test Data:** Same as 7.3.2.18.  
**Mocking:** Mock `QuestionsRepository.move(question_id, from_screen_id, to_screen_id, order)` to raise `WriteError("move failed")`. Boundary: database write. Assert called once with expected parameters.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-7 Move question between screens** raises, and not before. Assert **STEP-8 Set conditional parent** is not invoked following the failure. Assert that error mode **RUN_UPDATE_ENTITY_DB_WRITE_FAILED** is observed.  
**AC-Ref:** 6.3.2.19  
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED

---

## 7.3.2.20
**Title:** Move question resequence computation failure halts STEP-7 and prevents STEP-8  
**Purpose:** Verify resequencing failure on source or target screen halts move and prevents setting parent.  
**Test Data:** Same as 7.3.2.18.  
**Mocking:** Mock `OrderingService.resequenceQuestions(source_screen_id)` to raise `ComputationError("source gap")`. Boundary: sequencing algorithm. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-7 Move question between screens** raises, and not before. Assert **STEP-8 Set conditional parent** is not invoked following the failure. Assert that error mode **RUN_RESEQUENCE_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.20  
**Error Mode:** RUN_RESEQUENCE_COMPUTE_FAILED

---

## 7.3.2.21
**Title:** Move question ETag computation failure blocks finalisation and prevents STEP-8  
**Purpose:** Verify ETag compute failure after move blocks completion and prevents setting parent.  
**Test Data:** Same as 7.3.2.18.  
**Mocking:** Mock `ETag.compute(question)` to raise `ComputeError("etag")` after move persists. Boundary: version hashing. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-7 Move question between screens** finalisation raises, and not before. Assert **STEP-8 Set conditional parent** is not invoked following the failure. Assert that error mode **RUN_ETAG_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.21  
**Error Mode:** RUN_ETAG_COMPUTE_FAILED

---

## 7.3.2.22
**Title:** Set conditional parent read failure halts STEP-8 and prevents STEP-9  
**Purpose:** Verify read failure when fetching parent question halts and prevents clearing parent.  
**Test Data:** `PATCH /api/v1/authoring/questions/QST-401/visibility` with body `{ "parent_question_id": "QST-100", "visible_if_value": true }`, header `If-Match: W/"etag-q-401"`.  
**Mocking:** Mock `QuestionsRepository.get("QST-100")` to raise `ReadError("timeout")`. Boundary: database read. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-8 Set conditional parent** raises, and not before. Assert **STEP-9 Clear conditional parent** is not invoked following the failure. Assert that error mode **RUN_RETRIEVE_ENTITY_DB_READ_FAILED** is observed.  
**AC-Ref:** 6.3.2.22  
**Error Mode:** RUN_RETRIEVE_ENTITY_DB_READ_FAILED

---

## 7.3.2.23
**Title:** Set conditional parent persist failure halts STEP-8 and prevents STEP-9  
**Purpose:** Verify DB write failure setting visibility metadata halts and prevents clearing flow.  
**Test Data:** Same as 7.3.2.22.  
**Mocking:** Mock `QuestionsRepository.setVisibility(question_id, parent_id, visible_if_value)` to raise `WriteError("update failed")`. Boundary: database write. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-8 Set conditional parent** raises, and not before. Assert **STEP-9 Clear conditional parent** is not invoked following the failure. Assert that error mode **RUN_UPDATE_ENTITY_DB_WRITE_FAILED** is observed.  
**AC-Ref:** 6.3.2.23  
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED

---

## 7.3.2.24
**Title:** Set conditional parent ETag computation failure blocks finalisation and prevents STEP-9  
**Purpose:** Verify ETag compute failure after setting parent blocks completion and prevents clearing flow.  
**Test Data:** Same as 7.3.2.22.  
**Mocking:** Mock `ETag.compute(question)` to raise `ComputeError("etag")` after update. Boundary: version hashing. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-8 Set conditional parent** finalisation raises, and not before. Assert **STEP-9 Clear conditional parent** is not invoked following the failure. Assert that error mode **RUN_ETAG_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.24  
**Error Mode:** RUN_ETAG_COMPUTE_FAILED

---

## 7.3.2.25
**Title:** Clear conditional parent persist failure halts STEP-9  
**Purpose:** Verify DB write failure clearing parent halts the operation.  
**Test Data:** `PATCH /api/v1/authoring/questions/QST-401/visibility` with body `{ "parent_question_id": null, "visible_if_value": null }`, header `If-Match: W/"etag-q-401"`.  
**Mocking:** Mock `QuestionsRepository.clearVisibility(question_id)` to raise `WriteError("update failed")`. Boundary: database write. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-9 Clear conditional parent** raises, and not before. Assert **STEP-1 Create screen** is not invoked within the same transaction context. Assert that error mode **RUN_UPDATE_ENTITY_DB_WRITE_FAILED** is observed.  
**AC-Ref:** 6.3.2.25  
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED

---

## 7.3.2.26
**Title:** Clear conditional parent ETag computation failure blocks finalisation  
**Purpose:** Verify ETag compute failure after clearing parent blocks completion.  
**Test Data:** Same as 7.3.2.25.  
**Mocking:** Mock `ETag.compute(question)` to raise `ComputeError("etag")` after update. Boundary: version hashing. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-9 Clear conditional parent** finalisation raises, and not before. Assert **STEP-1 Create screen** is not invoked within the same transaction context. Assert that error mode **RUN_ETAG_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.26  
**Error Mode:** RUN_ETAG_COMPUTE_FAILED

---

## 7.3.2.27
**Title:** Allocate first placeholder persist failure halts STEP-3A and prevents STEP-4  
**Purpose:** Verify DB write failure during initial placeholder allocation halts and prevents text update flow.  
**Test Data:** Internal trigger upon first placeholder allocation for `QST-501`.  
**Mocking:** Mock `PlaceholdersRepository.create(question_id, ...)` to raise `WriteError("insert failed")`. Boundary: database write. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-3A Allocate first placeholder** raises, and not before. Assert **STEP-4 Update question text** is not invoked following the failure. Assert that error mode **RUN_UPDATE_ENTITY_DB_WRITE_FAILED** is observed.  
**AC-Ref:** 6.3.2.27  
**Error Mode:** RUN_UPDATE_ENTITY_DB_WRITE_FAILED

---

## 7.3.2.28
**Title:** Allocate first placeholder ETag computation failure blocks finalisation and prevents STEP-4  
**Purpose:** Verify ETag compute failure after first placeholder allocation blocks completion and prevents text update flow.  
**Test Data:** Same context as 7.3.2.27.  
**Mocking:** Mock `ETag.compute(question)` to raise `ComputeError("etag")` after allocation succeeds. Boundary: version hashing. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-3A Allocate first placeholder** finalisation raises, and not before. Assert **STEP-4 Update question text** is not invoked following the failure. Assert that error mode **RUN_ETAG_COMPUTE_FAILED** is observed.  
**AC-Ref:** 6.3.2.28  
**Error Mode:** RUN_ETAG_COMPUTE_FAILED

---

## 7.3.2.29
**Title:** Unidentified runtime error halts STEP-7 and prevents STEP-8  
**Purpose:** Verify catch-all runtime failure stops move and prevents setting parent.  
**Test Data:** Same as 7.3.2.18 but inject unexpected failure.  
**Mocking:** Mock `QuestionsRepository.move(...)` to raise `RuntimeError("unexpected")`. Boundary: catch-all runtime. Assert called once.  
**Assertions:** Assert error handler is invoked once immediately when **STEP-7 Move question between screens** raises, and not before. Assert **STEP-8 Set conditional parent** is not invoked following the failure. Assert that error mode **RUN_UNIDENTIFIED_ERROR** is observed.  
**AC-Ref:** 6.3.2.29  
**Error Mode:** RUN_UNIDENTIFIED_ERROR
