Feature: Epic D – Placeholders, Bindings and Transforms

Background:
Given the API base URL is "/api/v1"
And a document "doc-001" exists containing a clause at path "1.2"
And questions exist:
| question_id | text                                 |
| q-short     | What is the contact name?            |
| q-boolean   | Include whistleblowing clause?       |
| q-enum      | Where is the policy published?       |
| q-nested    | Who is responsible for this policy?  |
And the system has no existing placeholders for these questions
And the current question ETags are known:
| question_id | etag      |
| q-short     | etag-s-1  |
| q-boolean   | etag-b-1  |
| q-enum      | etag-e-1  |
| q-nested    | etag-n-1  |

@happy @suggest-short_string
Scenario: Suggest transform for a short text placeholder
When I POST "/api/v1/transforms/suggest" with JSON:
"""
{
"raw_text": "[CONTACT NAME]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 40, "end": 54 } }
}
"""
Then the response status should be 200
And the response JSON at "answer_kind" should be "short_string"
And the response JSON should have a "probe.probe_hash"
And the response JSON at "probe.document_id" should be "doc-001"
And the response JSON at "probe.clause_path" should be "1.2"
And the response JSON at "options" should be absent

@happy @bind-first-short_string
Scenario: Bind first short_string placeholder sets the question model
Given I have a valid TransformSuggestion for "[CONTACT NAME]" with answer_kind "short_string" and probe for doc-001/1.2
When I POST "/api/v1/placeholders/bind" with JSON:
"""
{
"question_id": "q-short",
"transform_id": "short_string_v1",
"placeholder": {
"raw_text": "[CONTACT NAME]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 40, "end": 54 } }
},
"apply_mode": "apply"
}
"""
And header "If-Match" is "etag-s-1"
And header "Idempotency-Key" is "key-001"
Then the response status should be 200
And the response JSON at "bound" should be true
And the response JSON at "question_id" should be "q-short"
And the response JSON at "answer_kind" should be "short_string"
And the response JSON should have "placeholder_id"
And the response JSON should not have "options"

@happy @idempotent-bind
Scenario: Idempotent bind replays safely with the same Idempotency-Key
When I repeat the previous POST with the exact same body and headers
Then the response status should be 200
And the response JSON at "placeholder_id" should equal the previously returned "placeholder_id"

@happy @suggest-boolean
Scenario: Suggest transform for boolean inclusion
When I POST "/api/v1/transforms/suggest" with JSON:
"""
{
"raw_text": "[INCLUDE THIS CLAUSE]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 60, "end": 81 } }
}
"""
Then the response status should be 200
And the response JSON at "answer_kind" should be "boolean"
And the response JSON should not have "options"

@happy @bind-boolean
Scenario: Bind boolean placeholder leaves no options and sets model
When I POST "/api/v1/placeholders/bind" with JSON:
"""
{
"question_id": "q-boolean",
"transform_id": "boolean_v1",
"placeholder": {
"raw_text": "[INCLUDE THIS CLAUSE]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 60, "end": 81 } }
},
"apply_mode": "apply"
}
"""
And header "If-Match" is "etag-b-1"
And header "Idempotency-Key" is "key-002"
Then the response status should be 200
And the response JSON at "answer_kind" should be "boolean"
And the response JSON should not have "options"

@happy @suggest-enum-literal-plus-placeholder
Scenario: Suggest transform for literal OR nested placeholder (enum_single)
When I POST "/api/v1/transforms/suggest" with JSON:
"""
{
"raw_text": "on the intranet OR [DETAILS]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 90, "end": 118 } }
}
"""
Then the response status should be 200
And the response JSON at "answer_kind" should be "enum_single"
And the response JSON at "options[0].value" should be "INTRANET"
And the response JSON at "options[0].label" should be "on the intranet"
And the response JSON at "options[1].value" should be "DETAILS"
And the response JSON at "options[1].placeholder_key" should be "DETAILS"
And the response JSON at "options[1].placeholder_id" should be absent

@happy @bind-enum-parent
Scenario: Bind enum_single parent with nested placeholder option defers linkage
When I POST "/api/v1/placeholders/bind" with JSON:
"""
{
"question_id": "q-enum",
"transform_id": "enum_single_v1",
"placeholder": {
"raw_text": "on the intranet OR [DETAILS]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 90, "end": 118 } }
},
"apply_mode": "apply"
}
"""
And header "If-Match" is "etag-e-1"
And header "Idempotency-Key" is "key-003"
Then the response status should be 200
And the response JSON at "answer_kind" should be "enum_single"
And the response JSON at "options[0].value" should be "INTRANET"
And the response JSON at "options[1].value" should be "DETAILS"
And the response JSON at "options[1].placeholder_key" should be "DETAILS"
And the response JSON at "options[1].placeholder_id" should be null

@happy @bind-nested-child
Scenario: Bind the child short_string placeholder and auto-link the parent option
Given I have a TransformSuggestion for child placeholder "[DETAILS]" with answer_kind "short_string"
When I POST "/api/v1/placeholders/bind" with JSON:
"""
{
"question_id": "q-nested",
"transform_id": "short_string_v1",
"placeholder": {
"raw_text": "[DETAILS]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 106, "end": 114 } }
},
"apply_mode": "apply"
}
"""
And header "If-Match" is "etag-n-1"
And header "Idempotency-Key" is "key-004"
Then the response status should be 200
And the response JSON should have "placeholder_id"
And I GET "/api/v1/questions/q-enum/placeholders?document_id=doc-001"
Then the response status should be 200
And the response JSON at "items[0].transform_id" should be "enum_single_v1"
And the response JSON at "items[0].payload_json.options[1].placeholder_id" should equal the newly bound child "placeholder_id"

@happy @list-placeholders
Scenario: List placeholders for a question filtered by document
When I GET "/api/v1/questions/q-enum/placeholders?document_id=doc-001"
Then the response status should be 200
And the response JSON at "items" should contain at least 1 element

@happy @unbind-child
Scenario: Unbind a child placeholder does not alter parent model
Given I have the child "placeholder_id" from the bind-nested-child scenario
When I POST "/api/v1/placeholders/unbind" with JSON:
"""
{ "placeholder_id": "<child-placeholder-id>" }
"""
And header "If-Match" is "<latest-etag-for-q-nested>"
Then the response status should be 200
And I GET "/api/v1/questions/q-enum/placeholders?document_id=doc-001"
Then the response JSON at "items[0].payload_json.options[1].placeholder_id" should be null
And the response JSON at "items[0].payload_json.options[0].value" should be "INTRANET"

@happy @unbind-last-clears-model
Scenario: Unbind the last placeholder clears the question’s model
Given "q-short" currently has exactly one bound placeholder
When I POST "/api/v1/placeholders/unbind" with JSON:
"""
{ "placeholder_id": "<only-placeholder-of-q-short>" }
"""
And header "If-Match" is "<latest-etag-for-q-short>"
Then the response status should be 200
And I GET "/api/v1/questions/q-short/placeholders?document_id=doc-001"
Then the response JSON at "items" should be an empty array
And the question "q-short" has no "answer_kind" and no "AnswerOption" rows

@happy @purge-on-document-delete
Scenario: Cleanup bindings when a document is deleted (purge)
When I POST "/api/v1/documents/doc-001/bindings:purge" with JSON:
"""
{ "reason": "deleted" }
"""
Then the response status should be 200
And the response JSON at "deleted_placeholders" should be greater than 0
And the response JSON at "updated_questions" should be greater than or equal to 0
And subsequent GET "/api/v1/questions/q-enum/placeholders?document_id=doc-001" returns 200 with "items" empty

@happy @catalog
Scenario: Read the transforms catalog
When I GET "/api/v1/transforms/catalog"
Then the response status should be 200
And the response JSON at "items[?(@.transform_id=='enum_single_v1')].answer_kind" should contain "enum_single"

@happy @preview
Scenario: Preview canonicalisation for a literal list (no persistence)
When I POST "/api/v1/transforms/preview" with JSON:
"""
{ "literals": ["The HR Manager", "The Finance Director"] }
"""
Then the response status should be 200
And the response JSON at "answer_kind" should be "enum_single"
And the response JSON at "options[0].value" should be "HR_MANAGER"
And the response JSON at "options[1].value" should be "FINANCE_DIRECTOR"

# --- Key sad path scenarios (integration level, externally observable) ---

@sad @suggest-422
Scenario: Suggest returns 422 for unrecognised pattern
When I POST "/api/v1/transforms/suggest" with JSON:
"""
{
"raw_text": "[[MALFORMED",
"context": { "document_id": "doc-001", "clause_path": "1.2" }
}
"""
Then the response status should be 422
And the response body is problem+json with "title" containing "unrecognised pattern"

@sad @bind-409-model-conflict
Scenario: Bind rejected with 409 when model would change
Given question "q-enum" already has answer_kind "enum_single" with options ["INTRANET","DETAILS"]
When I POST "/api/v1/placeholders/bind" with JSON:
"""
{
"question_id": "q-enum",
"transform_id": "number_v1",
"placeholder": {
"raw_text": "[HEADCOUNT]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 130, "end": 140 } }
},
"apply_mode": "apply"
}
"""
And header "If-Match" is "<latest-etag-for-q-enum>"
And header "Idempotency-Key" is "key-009"
Then the response status should be 409
And the response body is problem+json with "title" containing "model conflict"

@sad @bind-412-precondition
Scenario: Bind rejected with 412 when If-Match precondition fails
When I POST "/api/v1/placeholders/bind" with JSON:
"""
{
"question_id": "q-short",
"transform_id": "short_string_v1",
"placeholder": {
"raw_text": "[CONTACT NAME]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 40, "end": 54 } }
},
"apply_mode": "apply"
}
"""
And header "If-Match" is "stale-etag"
And header "Idempotency-Key" is "key-010"
Then the response status should be 412
And the response body is problem+json with "title" containing "precondition failed"

@sad @bind-404-question
Scenario: Bind rejected with 404 when question does not exist
When I POST "/api/v1/placeholders/bind" with JSON:
"""
{
"question_id": "q-missing",
"transform_id": "short_string_v1",
"placeholder": {
"raw_text": "[CONTACT NAME]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 40, "end": 54 } }
},
"apply_mode": "apply"
}
"""
And header "If-Match" is "etag-x"
And header "Idempotency-Key" is "key-011"
Then the response status should be 404
And the response body is problem+json with "title" containing "question not found"

@sad @unbind-404-placeholder
Scenario: Unbind rejected with 404 when placeholder does not exist
When I POST "/api/v1/placeholders/unbind" with JSON:
"""
{ "placeholder_id": "ph-unknown" }
"""
And header "If-Match" is "etag-any"
Then the response status should be 404
And the response body is problem+json with "title" containing "not found"

@sad @bind-422-bad-transform
Scenario: Bind rejected with 422 when transform not applicable to text
When I POST "/api/v1/placeholders/bind" with JSON:
"""
{
"question_id": "q-short",
"transform_id": "number_v1",
"placeholder": {
"raw_text": "[CONTACT NAME]",
"context": { "document_id": "doc-001", "clause_path": "1.2", "span": { "start": 40, "end": 54 } }
},
"apply_mode": "apply"
}
"""
And header "If-Match" is "<latest-etag-for-q-short>"
And header "Idempotency-Key" is "key-012"
Then the response status should be 422
And the response body is problem+json with "title" containing "transform not applicable"

@sad @purge-404-or-noop
Scenario Outline: Purge handles unknown document per contract
When I POST "/api/v1/documents/<doc_id>/bindings:purge" with JSON:
"""
{ "reason": "deleted" }
"""
Then the response status should be <status>
And the response body should <body_check>

Examples:
  | doc_id   | status | body_check                                        |
  | doc-zzz  | 404    | be problem+json with "title" containing "not found" |
  | doc-noop | 200    | contain "deleted_placeholders" equal to 0         |
