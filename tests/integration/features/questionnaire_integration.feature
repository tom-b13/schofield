Feature: Questionnaire Service end-to-end integration (API ⇄ DB ⇄ API)
End-to-end tests across HTTP API and the backing database with no mocks.
Covers happy paths for retrieval, autosave, gating, import/export; and key sad paths
(optimistic concurrency, validation, unknown identifiers, and import duplication).
Assumptions: a real database is available and migrated; HTTP server is running; CSV I/O is enabled.

Background:
Given a clean database
And the following questionnaire exists in the database:
\| questionnaire\_id                      | key         | title                 |
\| 11111111-1111-1111-1111-111111111111  | ONB-2025    | Onboarding 2025       |
And the following screens exist for questionnaire "11111111-1111-1111-1111-111111111111":
\| screen\_id                              | screen\_key   | title          | order |
\| 22222222-2222-2222-2222-222222222222   | company      | Company Info   | 1     |
And the following questions exist and are bound to screen "22222222-2222-2222-2222-222222222222":
\| question\_id                            | external\_qid | question\_text                | answer\_kind  | mandatory | question\_order |
\| 33333333-3333-3333-3333-333333333331   | Q\_CO\_NAME    | What is the company name?    | short\_string | true      | 1              |
\| 33333333-3333-3333-3333-333333333332   | Q\_CO\_SIZE    | How many employees?          | number       | true      | 2              |
\| 33333333-3333-3333-3333-333333333333   | Q\_NEWSLETTER | Subscribe to newsletter?     | boolean      | false     | 3              |
And an empty response set exists:
\| response\_set\_id                         | company\_id                         |
\| 44444444-4444-4444-4444-444444444444    | 55555555-5555-5555-5555-555555555555 |
And no answers exist yet for response set "44444444-4444-4444-4444-444444444444"

@integration @happy\_path
Scenario: Retrieve a screen with questions and current answers (none yet)
When I GET "/response-sets/44444444-4444-4444-4444-444444444444/screens/22222222-2222-2222-2222-222222222222"
Then the response code should be 200
And the response header "ETag" should be a non-empty string
And the response JSON at "\$.screen.screen\_id" equals "22222222-2222-2222-2222-222222222222"
And the response JSON at "\$.questions.length()" equals 3
And the response JSON at "\$.questions\[?(@.question\_id=='33333333-3333-3333-3333-333333333331')].answer\_kind" equals "short\_string"
And the database table "answer" should have 0 rows for response\_set\_id "44444444-4444-4444-4444-444444444444"

@integration @happy\_path
Scenario: Autosave a single answer with idempotency and ETag
Given I GET "/response-sets/44444444-4444-4444-4444-444444444444/screens/22222222-2222-2222-2222-222222222222" and capture header "ETag" as "etag\_v1"
When I PATCH "/response-sets/44444444-4444-4444-4444-444444444444/answers/33333333-3333-3333-3333-333333333331" with headers:
\| Idempotency-Key | idem-001 |
\| If-Match        | {etag\_v1} |
And body:
"""
{ "question\_id": "33333333-3333-3333-3333-333333333331", "value": "Acme Ltd" }
"""
Then the response code should be 200
And the response JSON at "\$.saved" equals true
And the response header "ETag" should be a non-empty string and capture as "etag\_v2"
And the database should contain exactly 1 row in "answer" for (response\_set\_id="44444444-4444-4444-4444-444444444444", question\_id="33333333-3333-3333-3333-333333333331") with value "Acme Ltd"
When I PATCH "/response-sets/44444444-4444-4444-4444-444444444444/answers/33333333-3333-3333-3333-333333333331" with headers:
\| Idempotency-Key | idem-001 |
\| If-Match        | {etag\_v2} |
And body:
"""
{ "question\_id": "33333333-3333-3333-3333-333333333331", "value": "Acme Ltd" }
"""
Then the response code should be 200
And the response JSON at "\$.saved" equals true
And the database should still contain exactly 1 row in "answer" for (response\_set\_id="44444444-4444-4444-4444-444444444444", question\_id="33333333-3333-3333-3333-333333333331")

@integration @happy\_path
Scenario: Complete mandatory answers and pass regenerate-check gating
Given I PATCH "/response-sets/44444444-4444-4444-4444-444444444444/answers/33333333-3333-3333-3333-333333333332" with headers:
\| Idempotency-Key | idem-002 |
\| If-Match        | "\*" |
And body:
"""
{ "question\_id": "33333333-3333-3333-3333-333333333332", "value": 42 }
"""
When I POST "/response-sets/44444444-4444-4444-4444-444444444444/regenerate-check"
Then the response code should be 200
And the response JSON at "\$.ok" equals true
And the response JSON at "\$.blocking\_items" equals \[]

@integration @happy\_path
Scenario: Import questionnaire updates from CSV (create + update, no errors)
When I POST "/questionnaires/import" with multipart file "questions.csv" containing:
"""
external\_qid,screen\_key,question\_order,question\_text,answer\_kind,mandatory,placeholder\_code,options
Q\_CO\_NAME,company,1,What is the company name?,short\_string,true,,
Q\_FAV\_FRUIT,company,4,Pick a fruit,enum\_single,false,,apple\:Apple|pear\:Pear
"""
Then the response code should be 200
And the response JSON at "\$.created" equals 1
And the response JSON at "\$.updated" equals 1
And the response JSON at "\$.errors.length()" equals 0
And the database table "question" should include a row where external\_qid="Q\_FAV\_FRUIT" and answer\_kind="enum\_single"
And the database table "answer\_option" should include 2 rows for the new question ordered by sort\_index

@integration @happy\_path
Scenario: Export questionnaire snapshot to CSV with deterministic ordering
When I GET "/questionnaires/11111111-1111-1111-1111-111111111111/export"
Then the response code should be 200
And the response header "Content-Type" equals "text/csv; charset=utf-8"
And the first line of the CSV equals "external\_qid,screen\_key,question\_order,question\_text,answer\_kind,mandatory,placeholder\_code,options"
And subsequent rows are ordered by screen\_key asc, question\_order asc, then question\_id asc
And the response header "ETag" should be a non-empty string

@integration @sad\_path
Scenario: Autosave fails with 409 Conflict on stale ETag
Given I GET "/response-sets/44444444-4444-4444-4444-444444444444/screens/22222222-2222-2222-2222-222222222222" and capture header "ETag" as "old\_etag"
And I PATCH "/response-sets/44444444-4444-4444-4444-444444444444/answers/33333333-3333-3333-3333-333333333331" with headers:
\| Idempotency-Key | idem-003 |
\| If-Match        | {old\_etag} |
And body:
"""
{ "question\_id": "33333333-3333-3333-3333-333333333331", "value": "TempCo" }
"""
And I GET "/response-sets/44444444-4444-4444-4444-444444444444/screens/22222222-2222-2222-2222-222222222222" and capture header "ETag" as "fresh\_etag"
When I PATCH "/response-sets/44444444-4444-4444-4444-444444444444/answers/33333333-3333-3333-3333-333333333331" with headers:
\| Idempotency-Key | idem-004 |
\| If-Match        | {old\_etag} |
And body:
"""
{ "question\_id": "33333333-3333-3333-3333-333333333331", "value": "NewerCo" }
"""
Then the response code should be 409
And the response JSON at "\$.status" equals 409
And the database value in "answer" for (response\_set\_id="44444444-4444-4444-4444-444444444444", question\_id="33333333-3333-3333-3333-333333333331") should still equal "TempCo"

@integration @sad\_path
Scenario: Autosave fails with 422 Unprocessable Entity for type mismatch
When I PATCH "/response-sets/44444444-4444-4444-4444-444444444444/answers/33333333-3333-3333-3333-333333333332" with headers:
\| Idempotency-Key | idem-005 |
\| If-Match        | "\*" |
And body:
"""
{ "question\_id": "33333333-3333-3333-3333-333333333332", "value": "forty-two" }
"""
Then the response code should be 422
And the response JSON at "\$.errors\[0].path" equals "\$.value"
And the response JSON at "\$.errors\[0].code" equals "type\_mismatch"
And the database should not create or update any row in "answer" for (response\_set\_id="44444444-4444-4444-4444-444444444444", question\_id="33333333-3333-3333-3333-333333333332")

@integration @sad\_path
Scenario: GET questionnaire by unknown id returns 404
When I GET "/questionnaires/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
Then the response code should be 404
And the response JSON at "\$.status" equals 404

@integration @sad\_path
Scenario: Import CSV rejects duplicate external\_qid rows within the same file
When I POST "/questionnaires/import" with multipart file "dup.csv" containing:
"""
external\_qid,screen\_key,question\_order,question\_text,answer\_kind,mandatory,placeholder\_code,options
Q\_DUP,company,1,Question A,short\_string,true,,
Q\_DUP,company,2,Question B,short\_string,true,,
"""
Then the response code should be 200
And the response JSON at "\$.errors.length()" is greater than 0
And the response JSON at "\$.created" equals 0
And the response JSON at "\$.updated" equals 0
And the database table "question" should not contain any row where external\_qid="Q\_DUP"

@integration @sad\_path
Scenario: Export unknown questionnaire returns 404
When I GET "/questionnaires/bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/export"
Then the response code should be 404
And the response JSON at "\$.status" equals 404

@integration @happy\_path
Scenario: Gating blocks when a mandatory answer is missing and unblocks after completion
Given I DELETE any answer in table "answer" for (response\_set\_id="44444444-4444-4444-4444-444444444444", question\_id="33333333-3333-3333-3333-333333333332")
When I POST "/response-sets/44444444-4444-4444-4444-444444444444/regenerate-check"
Then the response code should be 200
And the response JSON at "\$.ok" equals false
And the response JSON at "\$.blocking\_items.length()" is greater than 0
When I PATCH "/response-sets/44444444-4444-4444-4444-444444444444/answers/33333333-3333-3333-3333-333333333332" with headers:
\| Idempotency-Key | idem-006 |
\| If-Match        | "\*" |
And body:
"""
{ "question\_id": "33333333-3333-3333-3333-333333333332", "value": 7 }
"""
And I POST "/response-sets/44444444-4444-4444-4444-444444444444/regenerate-check"
Then the response code should be 200
And the response JSON at "\$.ok" equals true
And the response JSON at "\$.blocking\_items" equals \[]
