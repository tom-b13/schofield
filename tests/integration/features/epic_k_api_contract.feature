@epic_k_phase0
Feature: Epic K Phase-0 — ETag contract and parity without breaking existing behaviour
  As a client of the API
  I want domain ETag headers to be emitted consistently and preconditions enforced where already required
  So that the frontend can rely on a single predictable contract without changing token values or body shapes

  Background:
    Given API base URL is configured
    And an auth token is configured
    And a questionnaire id "QNR-001" exists
    And I create a response set for questionnaire "QNR-001" and store as "response_set_id"
    And a screen key "applicant_details" exists for questionnaire "QNR-001"
    And a question id "Q-ENUM-001" exists on screen "applicant_details"
    And a document id "DOC-001" exists

  @runtime @screens @headers
  Scenario: Screens GET emits Screen-ETag and ETag with legacy-parity and mirrors body screen_view.etag
    When I GET "/api/v1/response-sets/{response_set_id}/screens/{screen_key}" with path vars screen_key="applicant_details"
    Then the response status is 200
    And the response header "Screen-ETag" is present
    And the response header "ETag" is present
    And the response header "Screen-ETag" equals the response header "ETag"
    And the JSON pointer "/screen_view/etag" equals the response header "Screen-ETag"

  @runtime @answers @ifmatch @success
  Scenario: Answers PATCH with valid If-Match succeeds and rotates Screen-ETag (legacy value preserved)
    Given I GET "/api/v1/response-sets/{response_set_id}/screens/{screen_key}" with path vars screen_key="applicant_details"
    And I capture the response header "Screen-ETag" as "etag_before"
    When I PATCH "/api/v1/response-sets/{response_set_id}/answers/{question_id}" with headers If-Match="{etag_before}" and body:
      | value | "Yes" |
    Then the response status is one of:
      | 200 |
      | 204 |
    And the response header "Screen-ETag" is present
    And the response header "ETag" is present
    And the response header "Screen-ETag" equals the response header "ETag"
    And the response header "Screen-ETag" does not equal stored "etag_before"

  @runtime @answers @ifmatch @mismatch
  Scenario: Answers PATCH with mismatched If-Match returns 409 with unchanged problem shape
    When I PATCH "/api/v1/response-sets/{response_set_id}/answers/{question_id}" with headers If-Match="W/\"not-the-right-tag\"" and body:
      | value | "No" |
    Then the response status is 409
    And the problem JSON matches baseline fixture "tests/integration/data/epic_k/answers_mismatch.problem.json"

  @runtime @answers @ifmatch @missing
  Scenario: Answers PATCH missing If-Match returns 428 with unchanged problem shape
    When I PATCH "/api/v1/response-sets/{response_set_id}/answers/{question_id}" with no If-Match header and body:
      | value | "Maybe" |
    Then the response status is 428
    And the problem JSON matches baseline fixture "tests/integration/data/epic_k/answers_missing_if_match.problem.json"

  @documents @headers @diagnostics
  Scenario: Documents reorder emits Document-ETag and preserves diagnostics
    Given I GET "/api/v1/documents/{document_id}" and capture the response header "ETag" as "list_etag_before"
    When I PUT "/api/v1/documents/order" with headers If-Match="{list_etag_before}" and body from file "tests/integration/data/epic_k/doc_order_payload.json"
    Then the response status is 200
    And the response header "Document-ETag" is present
    And the response header "ETag" is present
    And the response header "Document-ETag" equals the response header "ETag"
    And the response header "X-List-ETag" is present
    And the response header "X-If-Match-Normalized" is present

  @documents @ifmatch @mismatch
  Scenario: Documents reorder with mismatched If-Match returns 412 with unchanged problem shape
    When I PUT "/api/v1/documents/order" with headers If-Match="W/\"not-the-right-list-tag\"" and body from file "tests/integration/data/epic_k/doc_order_payload.json"
    Then the response status is 412
    And the problem JSON matches baseline fixture "tests/integration/data/epic_k/documents_mismatch.problem.json"

  @questionnaires @csv @headers
  Scenario: Questionnaires CSV export emits Questionnaire-ETag and legacy ETag without altering bytes
    When I GET "/api/v1/questionnaires/{questionnaire_id}/export" with path vars questionnaire_id="QNR-001"
    Then the response status is 200
    And the response header "Questionnaire-ETag" is present
    And the response header "ETag" is present
    And the response header "Questionnaire-ETag" equals the response header "ETag"
    And the body bytes equal fixture "tests/integration/data/epic_k/csv_fixture.csv"

  @authoring @screens @no-enforcement
  Scenario: Authoring screen create succeeds without If-Match and does not add generic ETag
    When I POST "/api/v1/authoring/screens" with JSON body:
      | questionnaire_id | "QNR-001"           |
      | screen_key       | "new_section"       |
      | title            | "New section title" |
    Then the response status is one of:
      | 200 |
      | 201 |
    And the response header "Screen-ETag" is present
    And the response header "ETag" is absent

  @authoring @questions @no-enforcement
  Scenario: Authoring question update succeeds without If-Match and does not add generic ETag
    When I PATCH "/api/v1/authoring/questions/{question_id}" with body:
      | question_text | "Updated copy" |
    Then the response status is 200
    And the response header "Question-ETag" is present
    And the response header "ETag" is absent

  @placeholders @headers @parity
  Scenario: GET question placeholders sets ETag header equal to body etag
    When I GET "/api/v1/questions/{question_id}/placeholders"
    Then the response status is 200
    And the response header "ETag" is present
    And the JSON pointer "/etag" equals the response header "ETag"

  @placeholders @ifmatch @mismatch
  Scenario: Bind placeholder mismatch preserves 412 and includes ETag header only
    When I POST "/api/v1/placeholders/bind" with headers If-Match="W/\"wrong-placeholder-tag\"" and body from file "tests/integration/data/epic_k/bind_payload.json"
    Then the response status is 412
    And the response header "ETag" is present
    And the response header "Screen-ETag" is absent
    And the response header "Question-ETag" is absent
    And the response header "Document-ETag" is absent

  @cors @expose-headers
  Scenario: Access-Control-Expose-Headers exposes all domain headers for FE access
    When I GET "/api/v1/response-sets/{response_set_id}/screens/{screen_key}" with path vars screen_key="applicant_details"
    Then the response status is 200
    And the response header "Access-Control-Expose-Headers" contains tokens:
      | ETag               |
      | Screen-ETag        |
      | Question-ETag      |
      | Document-ETag      |
      | Questionnaire-ETag |
