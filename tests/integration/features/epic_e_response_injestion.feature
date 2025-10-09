Feature: Epic E – Response Ingestion API
Exercise all happy paths and key sad paths for creating response sets, reading screens, saving/clearing answers, batching, and deleting sets.

Background:
Given the API base path is "/api/v1"
And a questionnaire exists with screen_key "profile" containing:
| question_id                            | kind         | label          | options                                  |
| 11111111-1111-1111-1111-111111111111   | number       | "Age"          |                                          |
| 22222222-2222-2222-2222-222222222222   | boolean      | "Newsletter?"  |                                          |
| 33333333-3333-3333-3333-333333333333   | enum_single  | "Country"      | [{"option_id":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","value":"GB","label":"United Kingdom"}] |
| 44444444-4444-4444-4444-444444444444   | short_string | "Alias"        |                                          |
And a fresh event sink is attached to capture "response.saved" and "response_set.deleted" events

# -------------------------

# Happy paths

# -------------------------

Scenario: Create response set returns identifier, name, etag, created_at
When I POST "/response-sets" with JSON:
"""
{ "name": "Client Intake 2025-03" }
"""
Then the response status is 201
And the JSON at "response_set_id" is a valid UUID
And the JSON at "name" equals "Client Intake 2025-03"
And the JSON at "etag" is a non-empty opaque string
And the JSON at "created_at" is an RFC3339 UTC timestamp

Scenario: Read screen returns screen_view with Screen-ETag header
Given I have created a response set named "Client Intake A" and captured its "response_set_id"
When I GET "/response-sets/{response_set_id}/screens/profile"
Then the response status is 200
And the JSON at "screen_view.screen_key" equals "profile"
And the JSON at "screen_view.questions" is an array
And the HTTP header "Screen-ETag" equals JSON "screen_view.etag"

Scenario: Save finite number to number-kind question
Given I have a valid "If-Match" for question "11111111-1111-1111-1111-111111111111" in response_set "{response_set_id}"
When I PATCH "/response-sets/{response_set_id}/answers/11111111-1111-1111-1111-111111111111" with JSON:
"""
{ "value": 42 }
"""
And header "If-Match" set to "{etag}"
Then the response status is 200
And the JSON at "saved.question_id" equals "11111111-1111-1111-1111-111111111111"
And the JSON at "etag" changes from previous
And the JSON at "screen_view.questions[?(@.question_id=='11111111-1111-1111-1111-111111111111')].answer.number" equals 42

Scenario: Save boolean literal to boolean-kind question
Given I have a valid "If-Match" for question "22222222-2222-2222-2222-222222222222" in response_set "{response_set_id}"
When I PATCH "/response-sets/{response_set_id}/answers/22222222-2222-2222-2222-222222222222" with JSON:
"""
{ "value": true }
"""
And header "If-Match" set to "{etag}"
Then the response status is 200
And the JSON at "saved.question_id" equals "22222222-2222-2222-2222-222222222222"
And the JSON at "etag" changes from previous
And the JSON at "screen_view.questions[?(@.question_id=='22222222-2222-2222-2222-222222222222')].answer.bool" equals true

Scenario: Save enum_single by option_id is represented as option_id
Given I have a valid "If-Match" for question "33333333-3333-3333-3333-333333333333" in response_set "{response_set_id}"
When I PATCH "/response-sets/{response_set_id}/answers/33333333-3333-3333-3333-333333333333" with JSON:
"""
{ "option_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" }
"""
And header "If-Match" set to "{etag}"
Then the response status is 200
And the JSON at "screen_view.questions[?(@.question_id=='33333333-3333-3333-3333-333333333333')].answer.option_id" equals "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

Scenario: Save enum_single by canonical value token resolves to option_id
Given I have a valid "If-Match" for question "33333333-3333-3333-3333-333333333333" in response_set "{response_set_id}"
When I PATCH "/response-sets/{response_set_id}/answers/33333333-3333-3333-3333-333333333333" with JSON:
"""
{ "value": "GB" }
"""
And header "If-Match" set to "{etag}"
Then the response status is 200
And the JSON at "screen_view.questions[?(@.question_id=='33333333-3333-3333-3333-333333333333')].answer.option_id" equals "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

Scenario: Save short_string round-trips unchanged
Given I have a valid "If-Match" for question "44444444-4444-4444-4444-444444444444" in response_set "{response_set_id}"
When I PATCH "/response-sets/{response_set_id}/answers/44444444-4444-4444-4444-444444444444" with JSON:
"""
{ "value": "alpha-42" }
"""
And header "If-Match" set to "{etag}"
Then the response status is 200
And the JSON at "screen_view.questions[?(@.question_id=='44444444-4444-4444-4444-444444444444')].answer.text" equals "alpha-42"

Scenario: PATCH clear=true removes the answer and updates Screen-ETag
Given the question "22222222-2222-2222-2222-222222222222" currently has a stored answer in response_set "{response_set_id}"
And I have a valid "If-Match" for that question
When I PATCH "/response-sets/{response_set_id}/answers/22222222-2222-2222-2222-222222222222" with JSON:
"""
{ "clear": true }
"""
And header "If-Match" set to "{etag}"
Then the response status is 200
And the JSON at "screen_view.questions[?(@.question_id=='22222222-2222-2222-2222-222222222222')].answer" is absent
And the HTTP header "Screen-ETag" equals JSON "screen_view.etag"

Scenario: DELETE answer returns 204 and updated ETag header
Given the question "11111111-1111-1111-1111-111111111111" currently has a stored answer in response_set "{response_set_id}"
And I have a valid "If-Match" for that question
When I DELETE "/response-sets/{response_set_id}/answers/11111111-1111-1111-1111-111111111111" with header "If-Match: {etag}"
Then the response status is 204
And the HTTP header "ETag" is a non-empty opaque string different from previous

Scenario: Save emits response.saved event
Given I have a valid "If-Match" for question "44444444-4444-4444-4444-444444444444" in response_set "{response_set_id}"
When I PATCH "/response-sets/{response_set_id}/answers/44444444-4444-4444-4444-444444444444" with JSON:
"""
{ "value": "gamma" }
"""
And header "If-Match" set to "{etag}"
Then the response status is 200
And the JSON at "events[?(@.type=='response.saved')].payload.response_set_id" equals "{response_set_id}"
And the JSON at "events[?(@.type=='response.saved')].payload.question_id" equals "44444444-4444-4444-4444-444444444444"
And the JSON at "events[?(@.type=='response.saved')].payload.state_version" is a non-negative integer

Scenario: Batch upsert with merge strategy succeeds and preserves item order
Given I have current ETags for questions "11111111-1111-1111-1111-111111111111" and "22222222-2222-2222-2222-222222222222"
When I POST "/response-sets/{response_set_id}/answers:batch" with JSON:
"""
{
"update_strategy": "merge",
"items": [
{ "question_id": "11111111-1111-1111-1111-111111111111", "etag": "{etag_q1}", "body": { "value": 7 } },
{ "question_id": "22222222-2222-2222-2222-222222222222", "etag": "{etag_q2}", "body": { "value": false } }
]
}
"""
Then the response status is 200
And the JSON at "batch_result.items[0].question_id" equals "11111111-1111-1111-1111-111111111111"
And the JSON at "batch_result.items[1].question_id" equals "22222222-2222-2222-2222-222222222222"
And the JSON at "batch_result.items[*].outcome" are all "success"

Scenario: Delete response set cascades answers and emits event
Given I have a valid "If-Match" for response_set "{response_set_id}"
When I DELETE "/response-sets/{response_set_id}" with header "If-Match: {etag_set}"
Then the response status is 204
And an event "response_set.deleted" is observed in the event sink with "payload.response_set_id" = "{response_set_id}"

# -------------------------

# Key sad paths (contractual)

# -------------------------

Scenario: PATCH without required If-Match header
Given I have a response set "{response_set_id}"
When I PATCH "/response-sets/{response_set_id}/answers/11111111-1111-1111-1111-111111111111" with JSON:
"""
{ "value": 9 }
"""
And no "If-Match" header
Then the response content type is "application/problem+json"
And the problem "code" equals "PRE_IF_MATCH_MISSING"

Scenario: PATCH with stale ETag
Given I have a response set "{response_set_id}" and a stale ETag for "11111111-1111-1111-1111-111111111111"
When I PATCH "/response-sets/{response_set_id}/answers/11111111-1111-1111-1111-111111111111" with JSON:
"""
{ "value": 10 }
"""
And header "If-Match" set to "{stale_etag}"
Then the response content type is "application/problem+json"
And the problem "code" equals "PRE_IF_MATCH_ETAG_MISMATCH"

Scenario: Save number with non-finite value is rejected
Given I have a valid "If-Match" for question "11111111-1111-1111-1111-111111111111"
When I PATCH "/response-sets/{response_set_id}/answers/11111111-1111-1111-1111-111111111111" with JSON:
"""
{ "value": "Infinity" }
"""
And header "If-Match" set to "{etag}"
Then the response content type is "application/problem+json"
And the problem "code" equals "PRE_ANSWER_PATCH_VALUE_NUMBER_NOT_FINITE"

Scenario: Save boolean with non-literal value is rejected
Given I have a valid "If-Match" for question "22222222-2222-2222-2222-222222222222"
When I PATCH "/response-sets/{response_set_id}/answers/22222222-2222-2222-2222-222222222222" with JSON:
"""
{ "value": "yes" }
"""
And header "If-Match" set to "{etag}"
Then the response content type is "application/problem+json"
And the problem "code" equals "PRE_ANSWER_PATCH_VALUE_NOT_BOOLEAN_LITERAL"

Scenario: Save enum_single with unknown value token is rejected
Given I have a valid "If-Match" for question "33333333-3333-3333-3333-333333333333"
When I PATCH "/response-sets/{response_set_id}/answers/33333333-3333-3333-3333-333333333333" with JSON:
"""
{ "value": "XX" }
"""
And header "If-Match" set to "{etag}"
Then the response content type is "application/problem+json"
And the problem "code" equals "PRE_ANSWER_PATCH_VALUE_TOKEN_UNKNOWN"

Scenario: Save enum_single with invalid option_id format is rejected
Given I have a valid "If-Match" for question "33333333-3333-3333-3333-333333333333"
When I PATCH "/response-sets/{response_set_id}/answers/33333333-3333-3333-3333-333333333333" with JSON:
"""
{ "option_id": "not-a-uuid" }
"""
And header "If-Match" set to "{etag}"
Then the response content type is "application/problem+json"
And the problem "code" equals "PRE_ANSWER_PATCH_OPTION_ID_INVALID_UUID"

Scenario: Unknown question_id returns not found contract error
Given I have a response set "{response_set_id}" and a random question_id "99999999-9999-9999-9999-999999999999"
And I have a valid "If-Match" for that random question_id
When I PATCH "/response-sets/{response_set_id}/answers/99999999-9999-9999-9999-999999999999" with JSON:
"""
{ "value": 1 }
"""
And header "If-Match" set to "{etag}"
Then the response content type is "application/problem+json"
And the problem "code" equals "PRE_QUESTION_ID_UNKNOWN"

Scenario: Unknown response_set_id returns not found contract error
When I GET "/response-sets/88888888-8888-8888-8888-888888888888/screens/profile"
Then the response content type is "application/problem+json"
And the problem "code" equals "PRE_RESPONSE_SET_ID_UNKNOWN"

Scenario: Batch item missing question_id yields per-item error outcome
Given I have a response set "{response_set_id}"
When I POST "/response-sets/{response_set_id}/answers:batch" with JSON:
"""
{
"update_strategy": "merge",
"items": [
{ "etag": "W/"ignored-etag"", "body": { "value": 1 } }
]
}
"""
Then the response status is 200
And the JSON at "batch_result.items[0].outcome" equals "error"
And the JSON at "batch_result.items[0].error.code" equals "PRE_BATCH_ITEM_QUESTION_ID_MISSING"

Scenario: Batch item with stale etag yields per-item error outcome
Given I have a response set "{response_set_id}"
When I POST "/response-sets/{response_set_id}/answers:batch" with JSON:
"""
{
"update_strategy": "merge",
"items": [
{ "question_id": "11111111-1111-1111-1111-111111111111", "etag": "W/"stale"", "body": { "value": 3 } }
]
}
"""
Then the response status is 200
And the JSON at "batch_result.items[0].outcome" equals "error"
And the JSON at "batch_result.items[0].error.code" equals "PRE_BATCH_ITEM_ETAG_MISMATCH"

Scenario: Runtime failure during save upsert returns runtime contract error
Given I have a valid "If-Match" for question "44444444-4444-4444-4444-444444444444"
And the repository upsert will fail at runtime for this request
When I PATCH "/response-sets/{response_set_id}/answers/44444444-4444-4444-4444-444444444444" with JSON:
"""
{ "value": "delta" }
"""
And header "If-Match" set to "{etag}"
Then the response content type is "application/problem+json"
And the problem "code" equals "RUN_SAVE_ANSWER_UPSERT_FAILED"

Scenario: Runtime failure during visibility computation on GET returns runtime contract error
Given a response set "{response_set_id}"
And the visibility helper "compute_visible_set" will fail at runtime for this request
When I GET "/response-sets/{response_set_id}/screens/profile"
Then the response content type is "application/problem+json"
And the problem "code" equals "RUN_COMPUTE_VISIBLE_SET_FAILED"
