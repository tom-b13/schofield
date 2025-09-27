Feature: Epic I — Conditional Visibility
  As a client using the Questionnaire service
  I want the backend to authoritatively evaluate conditional visibility
  So that screens show only visible questions and PATCH returns minimal deltas

  Background:
    Given a questionnaire screen "s-main" containing:
      | question_id         | answer_kind  | question_text        | parent_question_id | visible_if_value |
      | q_parent_bool       | boolean      | "Is there a director?" |                   |                  |
      | q_child_name        | short_string | "Director name"      | q_parent_bool      | ["true"]         |
      | q_always_visible    | short_string | "Company trading name" |                   |                  |
    And a response set "rs-001" exists
    And no answer is stored yet for "q_parent_bool" in response set "rs-001"
    And the server computes visibility using the canonical value of parents

  @happy @get
  Scenario: GET returns only base questions when parent is unanswered (child hidden by default)
    When I GET "/response-sets/rs-001/screens/s-main"
    Then the response status should be 200
    And the JSON "$.questions[*].question_id" should contain "q_parent_bool"
    And the JSON "$.questions[*].question_id" should contain "q_always_visible"
    And the JSON "$.questions[*].question_id" should not contain "q_child_name"
    And the response should include an "ETag" header

  @happy @get
  Scenario: GET returns child when parent’s canonical value matches visible_if_value
    Given the response set "rs-001" has answer for "q_parent_bool" = true
    When I GET "/response-sets/rs-001/screens/s-main"
    Then the response status should be 200
    And the JSON "$.questions[*].question_id" should contain "q_child_name"

  @happy @patch
  Scenario: PATCH reveals child when parent toggles to matching value (delta now_visible)
    Given the response set "rs-001" has answer for "q_parent_bool" = false
    And I GET "/response-sets/rs-001/screens/s-main" and store the "ETag" as "etag_v1"
    When I PATCH "/response-sets/rs-001/answers/q_parent_bool" with body:
      """
      { "value_bool": true }
      """
      And headers:
      | Idempotency-Key | key-001 |
      | If-Match        | etag_v1 |
    Then the response status should be 200
    And the JSON "$.saved" should equal true
    And the JSON "$.visibility_delta.now_visible" should contain "q_child_name"
    And the JSON "$.visibility_delta.now_hidden" should be an empty array
    And the JSON "$.suppressed_answers" should be an empty array
    And the JSON "$.etag" should not equal "etag_v1"

  @happy @patch
  Scenario: PATCH hides child when parent toggles to non-matching value (delta now_hidden, suppression listed)
    Given the response set "rs-001" has answer for "q_parent_bool" = true
    And the response set "rs-001" has answer for "q_child_name" = "Jane Doe"
    And I GET "/response-sets/rs-001/screens/s-main" and store the "ETag" as "etag_v2"
    When I PATCH "/response-sets/rs-001/answers/q_parent_bool" with body:
      """
      { "value_bool": false }
      """
      And headers:
      | Idempotency-Key | key-002 |
      | If-Match        | etag_v2 |
    Then the response status should be 200
    And the JSON "$.saved" should equal true
    And the JSON "$.visibility_delta.now_hidden" should contain "q_child_name"
    And the JSON "$.visibility_delta.now_visible" should be an empty array
    And the JSON "$.suppressed_answers" should contain "q_child_name"
    And the JSON "$.etag" should not equal "etag_v2"

  @happy @patch
  Scenario: PATCH to a leaf question with no descendants produces empty delta
    Given I GET "/response-sets/rs-001/screens/s-main" and store the "ETag" as "etag_v3"
    When I PATCH "/response-sets/rs-001/answers/q_always_visible" with body:
      """
      { "value_text": "ACME Trading" }
      """
      And headers:
      | Idempotency-Key | key-003 |
      | If-Match        | etag_v3 |
    Then the response status should be 200
    And the JSON "$.visibility_delta.now_visible" should be an empty array
    And the JSON "$.visibility_delta.now_hidden" should be an empty array
    And the JSON "$.suppressed_answers" should be an empty array

  @happy @get
  Scenario: GET reflects updated visibility immediately after PATCH
    Given the response set "rs-001" has answer for "q_parent_bool" = true
    When I GET "/response-sets/rs-001/screens/s-main"
    Then the response status should be 200
    And the JSON "$.questions[*].question_id" should contain "q_child_name"

  @sad @concurrency
  Scenario: PATCH with stale If-Match returns 409 and prevents subtree re-evaluation
    Given I GET "/response-sets/rs-001/screens/s-main" and store the "ETag" as "stale_etag"
    And another client updated the screen so the current ETag is different from "stale_etag"
    When I PATCH "/response-sets/rs-001/answers/q_parent_bool" with body:
      """
      { "value_bool": true }
      """
      And headers:
      | Idempotency-Key | key-004 |
      | If-Match        | stale_etag |
    Then the response status should be 409
    And the JSON "$.type" should equal "about:blank"
    And the JSON "$.title" should contain "Conflict"
    And the JSON "$.detail" should contain "If-Match"
    And no descendant re-evaluation occurs

  @sad @validation
  Scenario: PATCH with type mismatch returns 422 and no visibility delta
    Given I GET "/response-sets/rs-001/screens/s-main" and store the "ETag" as "etag_v4"
    When I PATCH "/response-sets/rs-001/answers/q_parent_bool" with body:
      """
      { "value_text": "not-a-boolean" }
      """
      And headers:
      | Idempotency-Key | key-005 |
      | If-Match        | etag_v4 |
    Then the response status should be 422
    And the JSON "$.title" should contain "Unprocessable Entity"
    And the JSON "$.errors[0].field" should equal "value_bool"
    And the JSON "$.errors[0].message" should contain "boolean"
    And the JSON should not have the path "$.visibility_delta"

  @sad @routing
  Scenario: GET with unknown screen_id returns 404
    When I GET "/response-sets/rs-001/screens/s-does-not-exist"
    Then the response status should be 404
    And the JSON "$.title" should contain "Not Found"
    And the JSON "$.detail" should contain "screen_id"

  @sad @routing
  Scenario: PATCH with unknown question_id returns 404
    Given I GET "/response-sets/rs-001/screens/s-main" and store the "ETag" as "etag_v5"
    When I PATCH "/response-sets/rs-001/answers/q-missing" with body:
      """
      { "value_text": "irrelevant" }
      """
      And headers:
      | Idempotency-Key | key-006 |
      | If-Match        | etag_v5 |
    Then the response status should be 404
    And the JSON "$.title" should contain "Not Found"
    And the JSON "$.detail" should contain "question_id"

  @happy @idempotency
  Scenario: PATCH is idempotent for same Idempotency-Key
    Given I GET "/response-sets/rs-001/screens/s-main" and store the "ETag" as "etag_v6"
    When I PATCH "/response-sets/rs-001/answers/q_always_visible" with body:
      """
      { "value_text": "ACME Trading" }
      """
      And headers:
      | Idempotency-Key | idem-007 |
      | If-Match        | etag_v6 |
    And I PATCH "/response-sets/rs-001/answers/q_always_visible" with the same body and headers:
      | Idempotency-Key | idem-007 |
      | If-Match        | etag_v6 |
    Then both responses should have status 200
    And both responses should have identical bodies
    And the server should persist only one change for Idempotency-Key "idem-007"
