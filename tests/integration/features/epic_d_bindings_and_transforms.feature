Feature: Epic E – Response Ingestion API (house-style)
Exercise all happy paths and key sad paths for creating response sets, reading screens, saving/clearing answers, batching, and deleting sets.

Background:
Given a clean database
And the API base url is "/api/v1"
And a questionnaire exists with screen_key "profile" containing:
| question_id                            | kind         | label          | options                                                                                                  |
| 11111111-1111-1111-1111-111111111111   | number       | Age            |                                                                                                          |
| 22222222-2222-2222-2222-222222222222   | boolean      | Newsletter?    |                                                                                                          |
| 33333333-3333-3333-3333-333333333333   | enum_single  | Country        | [{"option_id":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","value":"GB","label":"United Kingdom"}]            |
| 44444444-4444-4444-4444-444444444444   | short_string | Alias          |                                                                                                          |
And an event sink is attached for "response.saved" and "response_set.deleted"

# -------------------------

# Happy paths

# -------------------------

@happy @post @response_set
Scenario: Create response set returns identifier, name, etag, created_at
When I POST "/response-sets" with body:
"""
{ "name": "Client Intake 2025-03" }
"""
And headers:
| Content-Type | application/json |
Then the response status should be 201
And the response JSON at "$.response_set_id" should be a valid UUID
And the response JSON at "$.name" should equal "Client Intake 2025-03"
And the response JSON at "$.etag" should be a non-empty string
And the response JSON at "$.created_at" should be an RFC3339 UTC timestamp

@happy @get @screen
Scenario: Read screen returns screen_view with Screen-ETag header
Given I create a response set named "Client Intake A" and capture "response_set_id"
When I GET "/response-sets/{response_set_id}/screens/profile"
Then the response status should be 200
And the response header "Screen-ETag" should equal the response JSON at "$.screen_view.etag"
And the response JSON at "$.screen_view.screen_key" should equal "profile"
And the response JSON at "$.screen_view.questions" should be an array

@happy @patch @number
Scenario: Save finite number to number-kind question
Given I have a current ETag for question "11111111-1111-1111-1111-111111111111" in response_set "{response_set_id}" as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/11111111-1111-1111-1111-111111111111" with body:
"""
{ "value": 42 }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response status should be 200
And the response JSON at "$.saved.question_id" should equal "11111111-1111-1111-1111-111111111111"
And the response JSON at "$.etag" should not equal "{etag}"
And the response JSON at "$.screen_view.questions[?(@.question_id=='11111111-1111-1111-1111-111111111111')].answer.number" should equal 42

@happy @patch @boolean
Scenario: Save boolean literal to boolean-kind question
Given I have a current ETag for question "22222222-2222-2222-2222-222222222222" in response_set "{response_set_id}" as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/22222222-2222-2222-2222-222222222222" with body:
"""
{ "value": true }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response status should be 200
And the response JSON at "$.saved.question_id" should equal "22222222-2222-2222-2222-222222222222"
And the response JSON at "$.etag" should not equal "{etag}"
And the response JSON at "$.screen_view.questions[?(@.question_id=='22222222-2222-2222-2222-222222222222')].answer.bool" should equal true

@happy @patch @enum
Scenario: Save enum_single by option_id is represented as option_id
Given I have a current ETag for question "33333333-3333-3333-3333-333333333333" in response_set "{response_set_id}" as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/33333333-3333-3333-3333-333333333333" with body:
"""
{ "option_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response status should be 200
And the response JSON at "$.screen_view.questions[?(@.question_id=='33333333-3333-3333-3333-333333333333')].answer.option_id" should equal "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

@happy @patch @enum
Scenario: Save enum_single by canonical value token resolves to option_id
Given I have a current ETag for question "33333333-3333-3333-3333-333333333333" in response_set "{response_set_id}" as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/33333333-3333-3333-3333-333333333333" with body:
"""
{ "value": "GB" }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response status should be 200
And the response JSON at "$.screen_view.questions[?(@.question_id=='33333333-3333-3333-3333-333333333333')].answer.option_id" should equal "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

@happy @patch @text
Scenario: Save short_string round-trips unchanged
Given I have a current ETag for question "44444444-4444-4444-4444-444444444444" in response_set "{response_set_id}" as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/44444444-4444-4444-4444-444444444444" with body:
"""
{ "value": "alpha-42" }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response status should be 200
And the response JSON at "$.screen_view.questions[?(@.question_id=='44444444-4444-4444-4444-444444444444')].answer.text" should equal "alpha-42"

@happy @patch @clear
Scenario: PATCH clear=true removes the answer and updates Screen-ETag
Given the question "22222222-2222-2222-2222-222222222222" has a stored answer in response_set "{response_set_id}"
And I have a current ETag for that question as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/22222222-2222-2222-2222-222222222222" with body:
"""
{ "clear": true }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response status should be 200
And the response JSON at "$.screen_view.questions[?(@.question_id=='22222222-2222-2222-2222-222222222222')].answer" should be absent
And the response header "Screen-ETag" should equal the response JSON at "$.screen_view.etag"

@happy @delete @answer
Scenario: DELETE answer returns 204 and updated ETag header
Given the question "11111111-1111-1111-1111-111111111111" has a stored answer in response_set "{response_set_id}"
And I have a current ETag for that question as "{etag}"
When I DELETE "/response-sets/{response_set_id}/answers/11111111-1111-1111-1111-111111111111"
And headers:
| If-Match | {etag} |
Then the response status should be 204
And the response header "ETag" should be a non-empty string different to "{etag}"

@happy @events
Scenario: Save emits response.saved event
Given I have a current ETag for question "44444444-4444-4444-4444-444444444444" in response_set "{response_set_id}" as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/44444444-4444-4444-4444-444444444444" with body:
"""
{ "value": "gamma" }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response status should be 200
And the event sink should contain exactly one "response.saved" event with:
| payload.response_set_id | {response_set_id}                      |
| payload.question_id     | 44444444-4444-4444-4444-444444444444   |
| payload.state_version   | integer >= 0                           |

@happy @batch
Scenario: Batch upsert with merge strategy succeeds and preserves item order
Given I capture current ETags for:
| question_id                            | etag_var   |
| 11111111-1111-1111-1111-111111111111   | {etag_q1}  |
| 22222222-2222-2222-2222-222222222222   | {etag_q2}  |
When I POST "/response-sets/{response_set_id}/answers:batch" with body:
"""
{
"update_strategy": "merge",
"items": [
{ "question_id": "11111111-1111-1111-1111-111111111111", "etag": "{etag_q1}", "body": { "value": 7 } },
{ "question_id": "22222222-2222-2222-2222-222222222222", "etag": "{etag_q2}", "body": { "value": false } }
]
}
"""
And headers:
| Content-Type | application/json |
Then the response status should be 200
And the response JSON at "$.batch_result.items[0].question_id" should equal "11111111-1111-1111-1111-111111111111"
And the response JSON at "$.batch_result.items[1].question_id" should equal "22222222-2222-2222-2222-222222222222"
And the response JSON at "$.batch_result.items[*].outcome" should all equal "success"

@happy @delete @response_set
Scenario: Delete response set cascades answers and emits event
Given I have a current ETag for response_set "{response_set_id}" as "{etag_set}"
When I DELETE "/response-sets/{response_set_id}"
And headers:
| If-Match | {etag_set} |
Then the response status should be 204
And the event sink should contain exactly one "response_set.deleted" event with:
| payload.response_set_id | {response_set_id} |

# -------------------------

# Key sad paths (contractual)

# -------------------------

@sad @patch @precondition
Scenario: PATCH without required If-Match header
Given I have a response set "{response_set_id}"
When I PATCH "/response-sets/{response_set_id}/answers/11111111-1111-1111-1111-111111111111" with body:
"""
{ "value": 9 }
"""
And headers:
| Content-Type | application/json |
Then the response content type should be "application/problem+json"
And the response JSON at "$.code" should equal "PRE_IF_MATCH_MISSING"

@sad @patch @precondition
Scenario: PATCH with stale ETag
Given I have a response set "{response_set_id}" and a stale ETag for "11111111-1111-1111-1111-111111111111" as "{stale_etag}"
When I PATCH "/response-sets/{response_set_id}/answers/11111111-1111-1111-1111-111111111111" with body:
"""
{ "value": 10 }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {stale_etag}     |
Then the response content type should be "application/problem+json"
And the response JSON at "$.code" should equal "PRE_IF_MATCH_ETAG_MISMATCH"

@sad @patch @validation
Scenario: Save number with non-finite value is rejected
Given I have a current ETag for question "11111111-1111-1111-1111-111111111111" in response_set "{response_set_id}" as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/11111111-1111-1111-1111-111111111111" with body:
"""
{ "value": "Infinity" }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response content type should be "application/problem+json"
And the response JSON at "$.code" should equal "PRE_ANSWER_PATCH_VALUE_NUMBER_NOT_FINITE"

@sad @patch @validation
Scenario: Save boolean with non-literal value is rejected
Given I have a current ETag for question "22222222-2222-2222-2222-222222222222" in response_set "{response_set_id}" as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/22222222-2222-2222-2222-222222222222" with body:
"""
{ "value": "yes" }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response content type should be "application/problem+json"
And the response JSON at "$.code" should equal "PRE_ANSWER_PATCH_VALUE_NOT_BOOLEAN_LITERAL"

@sad @patch @validation
Scenario: Save enum_single with unknown value token is rejected
Given I have a current ETag for question "33333333-3333-3333-3333-333333333333" in response_set "{response_set_id}" as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/33333333-3333-3333-3333-333333333333" with body:
"""
{ "value": "XX" }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response content type should be "application/problem+json"
And the response JSON at "$.code" should equal "PRE_ANSWER_PATCH_VALUE_TOKEN_UNKNOWN"

@sad @patch @validation
Scenario: Save enum_single with invalid option_id format is rejected
Given I have a current ETag for question "33333333-3333-3333-3333-333333333333" in response_set "{response_set_id}" as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/33333333-3333-3333-3333-333333333333" with body:
"""
{ "option_id": "not-a-uuid" }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response content type should be "application/problem+json"
And the response JSON at "$.code" should equal "PRE_ANSWER_PATCH_OPTION_ID_INVALID_UUID"

@sad @patch @notfound
Scenario: Unknown question_id returns not found contract error
Given I have a response set "{response_set_id}" and a random question_id "99999999-9999-9999-9999-999999999999"
And I have a current ETag for that random question_id as "{etag}"
When I PATCH "/response-sets/{response_set_id}/answers/99999999-9999-9999-9999-999999999999" with body:
"""
{ "value": 1 }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response content type should be "application/problem+json"
And the response JSON at "$.code" should equal "PRE_QUESTION_ID_UNKNOWN"

@sad @get @notfound
Scenario: Unknown response_set_id returns not found contract error
When I GET "/response-sets/88888888-8888-8888-8888-888888888888/screens/profile"
Then the response content type should be "application/problem+json"
And the response JSON at "$.code" should equal "PRE_RESPONSE_SET_ID_UNKNOWN"

@sad @batch @validation
Scenario: Batch item missing question_id yields per-item error outcome
Given I have a response set "{response_set_id}"
When I POST "/response-sets/{response_set_id}/answers:batch" with body:
"""
{
"update_strategy": "merge",
"items": [
{ "etag": "W/"ignored-etag"", "body": { "value": 1 } }
]
}
"""
And headers:
| Content-Type | application/json |
Then the response status should be 200
And the response JSON at "$.batch_result.items[0].outcome" should equal "error"
And the response JSON at "$.batch_result.items[0].error.code" should equal "PRE_BATCH_ITEM_QUESTION_ID_MISSING"

@sad @batch @concurrency
Scenario: Batch item with stale etag yields per-item error outcome
Given I have a response set "{response_set_id}"
When I POST "/response-sets/{response_set_id}/answers:batch" with body:
"""
{
"update_strategy": "merge",
"items": [
{ "question_id": "11111111-1111-1111-1111-111111111111", "etag": "W/"stale"", "body": { "value": 3 } }
]
}
"""
And headers:
| Content-Type | application/json |
Then the response status should be 200
And the response JSON at "$.batch_result.items[0].outcome" should equal "error"
And the response JSON at "$.batch_result.items[0].error.code" should equal "PRE_BATCH_ITEM_ETAG_MISMATCH"

@sad @runtime @patch
Scenario: Runtime failure during save upsert returns runtime contract error
Given I have a current ETag for question "44444444-4444-4444-4444-444444444444" in response_set "{response_set_id}" as "{etag}"
And the repository upsert will fail at runtime for this request
When I PATCH "/response-sets/{response_set_id}/answers/44444444-4444-4444-4444-444444444444" with body:
"""
{ "value": "delta" }
"""
And headers:
| Content-Type | application/json |
| If-Match     | {etag}           |
Then the response content type should be "application/problem+json"
And the response JSON at "$.code" should equal "RUN_SAVE_ANSWER_UPSERT_FAILED"

@sad @runtime @get
Scenario: Runtime failure during visibility computation on GET returns runtime contract error
Given a response set "{response_set_id}"
And the visibility helper "compute_visible_set" will fail at runtime for this request
When I GET "/response-sets/{response_set_id}/screens/profile"
Then the response content type should be "application/problem+json"
And the response JSON at "$.code" should equal "RUN_COMPUTE_VISIBLE_SET_FAILED"
