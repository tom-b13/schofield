Feature: Epic G — Build questionnaire (authoring)
  As an author
  I want to create and organise screens and questions
  So that questionnaires can be assembled deterministically with safe ordering and visibility rules

  Background:
    Given a questionnaire "Q-100" exists
    And no screens exist for questionnaire "Q-100"
    And I use base path "/api/v1/authoring"
    And I clear captured ETags and idempotency keys

  @happy_path
  Scenario: Create screen without proposed position assigns order 1
    When I POST "/questionnaires/Q-100/screens" with body:
      | title | Getting started |
    And I set header "Idempotency-Key" to "idem-s-001"
    Then the response status should be 201
    And the response should include a "screen_id"
    And the response body "title" should equal "Getting started"
    And the response body "screen_order" should equal 1
    And the response should include headers "Screen-ETag" and "Questionnaire-ETag"

  @happy_path
  Scenario: Create second screen with proposed position reindexes contiguously
    Given screen "S-1" exists on questionnaire "Q-100" with title "Getting started" and order 1
    When I POST "/questionnaires/Q-100/screens" with body:
      | title             | Basics |
      | proposed_position | 1      |
    And I set header "Idempotency-Key" to "idem-s-002"
    Then the response status should be 201
    And the response body "title" should equal "Basics"
    And the response body "screen_order" should equal 1
    And screen "S-1" now has "screen_order" 2
    And the response should include headers "Screen-ETag" and "Questionnaire-ETag"

  @happy_path
  Scenario: Rename a screen and keep position (If-Match required)
    Given screen "S-2" exists on questionnaire "Q-100" with title "Basics" and order 1
    And I have the current "Screen-ETag" for "S-2"
    When I PATCH "/questionnaires/Q-100/screens/S-2" with body:
      | title | Introduction |
    And I set header "If-Match" to the current "Screen-ETag" for "S-2"
    Then the response status should be 200
    And the response body "screen_id" should equal "S-2"
    And the response body "title" should equal "Introduction"
    And the response should include headers "Screen-ETag" and "Questionnaire-ETag"

  @happy_path
  Scenario: Create question scaffold without answer_kind (unset) and assigned order
    Given screen "S-2" exists on questionnaire "Q-100" with title "Introduction" and order 1
    When I POST "/questionnaires/Q-100/questions" with body:
      | screen_id     | S-2              |
      | question_text | What is your HQ? |
    And I set header "Idempotency-Key" to "idem-q-001"
    Then the response status should be 201
    And the response should include a "question_id"
    And the response body "screen_id" should equal "S-2"
    And the response body "question_text" should equal "What is your HQ?"
    And the response body "answer_kind" should be absent or null
    And the response body "question_order" should equal 1
    And the response should include headers "Question-ETag", "Screen-ETag" and "Questionnaire-ETag"

  @happy_path
  Scenario: Update question text with If-Match
    Given question "Q-1" exists on screen "S-2" with text "What is your HQ?" and order 1
    And I have the current "Question-ETag" for "Q-1"
    When I PATCH "/questions/Q-1" with body:
      | question_text | Where is your HQ located? |
    And I set header "If-Match" to the current "Question-ETag" for "Q-1"
    Then the response status should be 200
    And the response body "question_id" should equal "Q-1"
    And the response body "question_text" should equal "Where is your HQ located?"
    And the response should include headers "Question-ETag", "Screen-ETag" and "Questionnaire-ETag"

  @happy_path
  Scenario: Reorder questions within a screen (backend authoritative contiguous sequence)
    Given screen "S-2" exists with questions:
      | question_id | question_text            | question_order |
      | Q-1         | Where is your HQ located?| 1              |
      | Q-2         | How many offices?        | 2              |
      | Q-3         | Do you have subsidiaries?| 3              |
    And I have the current "Question-ETag" for "Q-3"
    When I PATCH "/questions/Q-3/position" with body:
      | proposed_question_order | 1 |
    And I set header "If-Match" to the current "Question-ETag" for "Q-3"
    Then the response status should be 200
    And the response body "question_id" should equal "Q-3"
    And the response body "question_order" should equal 1
    And question "Q-1" now has "question_order" 2
    And question "Q-2" now has "question_order" 3
    And the response should include headers "Question-ETag", "Screen-ETag" and "Questionnaire-ETag"

  @happy_path
  Scenario: Reorder screens (backend authoritative contiguous sequence)
    Given questionnaire "Q-100" has screens:
      | screen_id | title           | screen_order |
      | S-2       | Introduction    | 1            |
      | S-1       | Getting started | 2            |
    And I have the current "Screen-ETag" for "S-1"
    When I PATCH "/questionnaires/Q-100/screens/S-1" with body:
      | proposed_position | 1 |
    And I set header "If-Match" to the current "Screen-ETag" for "S-1"
    Then the response status should be 200
    And screen "S-1" now has "screen_order" 1
    And screen "S-2" now has "screen_order" 2
    And the response should include headers "Screen-ETag" and "Questionnaire-ETag"

  @happy_path
  Scenario: Move question between screens (target gets new order; source reindexed)
    Given questionnaire "Q-100" has screens:
      | screen_id | title        | screen_order |
      | S-1       | Overview     | 1            |
      | S-2       | Introduction | 2            |
    And screen "S-1" has questions:
      | question_id | question_text | question_order |
      | Q-10        | A             | 1              |
      | Q-11        | B             | 2              |
    And I have the current "Question-ETag" for "Q-10"
    When I PATCH "/questions/Q-10/position" with body:
      | screen_id               | S-2 |
      | proposed_question_order | 1   |
    And I set header "If-Match" to the current "Question-ETag" for "Q-10"
    Then the response status should be 200
    And question "Q-10" now has "screen_id" S-2
    And question "Q-10" now has "question_order" 1
    And question "Q-11" now has "question_order" 1
    And the response should include headers "Question-ETag", "Screen-ETag" and "Questionnaire-ETag"

  @happy_path
  Scenario: Set conditional parent with compatible visible_if_value
    Given question "Q-20" exists on screen "S-2" with text "Do you operate internationally?" and order 1 and answer_kind "boolean"
    And question "Q-21" exists on screen "S-2" with text "List operating countries" and order 2 and answer_kind is unset
    And I have the current "Question-ETag" for "Q-21"
    When I PATCH "/questions/Q-21/visibility" with body:
      | parent_question_id | Q-20  |
      | visible_if_value   | true  |
    And I set header "If-Match" to the current "Question-ETag" for "Q-21"
    Then the response status should be 200
    And question "Q-21" now has "parent_question_id" Q-20
    And question "Q-21" now has "visible_if_value" ["true"]
    And the response should include headers "Question-ETag", "Screen-ETag" and "Questionnaire-ETag"

  @happy_path
  Scenario: Clear conditional parent
    Given question "Q-21" has "parent_question_id" Q-20 and "visible_if_value" ["true"]
    And I have the current "Question-ETag" for "Q-21"
    When I PATCH "/questions/Q-21/visibility" with body:
      | parent_question_id | null |
      | visible_if_value   | null |
    And I set header "If-Match" to the current "Question-ETag" for "Q-21"
    Then the response status should be 200
    And question "Q-21" now has "parent_question_id" null
    And question "Q-21" now has "visible_if_value" null
    And the response should include headers "Question-ETag", "Screen-ETag" and "Questionnaire-ETag"

  @happy_path
  Scenario: Idempotent create screen returns original resource on retry
    When I POST "/questionnaires/Q-100/screens" with body:
      | title | Compliance |
    And I set header "Idempotency-Key" to "idem-s-003"
    Then the response status should be 201
    And I capture "Screen-ETag" as "etag-compliance"
    When I POST "/questionnaires/Q-100/screens" with body:
      | title | Compliance |
    And I set header "Idempotency-Key" to "idem-s-003"
    Then the response status should be 201
    And the response "screen_id" should equal the original for Idempotency-Key "idem-s-003"
    And the response header "Screen-ETag" should equal "etag-compliance"

  @happy_path
  Scenario: Allocate first placeholder infers and persists answer_kind
    Given question "Q-30" exists on screen "S-2" with text "Pick one region" and order 1 and answer_kind is unset
    When an allocation event occurs for "Q-30" with placeholder "P-REG-1" that implies answer_kind "enum_single"
    Then question "Q-30" now has "answer_kind" "enum_single"
    And the response should include headers "Question-ETag", "Screen-ETag" and "Questionnaire-ETag"

  @sad_path
  Scenario: Concurrency failure when If-Match does not match
    Given screen "S-2" exists on questionnaire "Q-100" with title "Introduction" and order 1
    And I set header "If-Match" to "\"stale-etag\""
    When I PATCH "/questionnaires/Q-100/screens/S-2" with body:
      | title | Intro |
    Then the request is rejected due to ETag mismatch
    And no changes are persisted for screen "S-2"

  @sad_path
  Scenario: Non-positive proposed position is rejected on screen reorder
    Given I have the current "Screen-ETag" for "S-2"
    When I PATCH "/questionnaires/Q-100/screens/S-2" with body:
      | proposed_position | 0 |
    And I set header "If-Match" to the current "Screen-ETag" for "S-2"
    Then the request is rejected due to invalid proposed position
    And screen "S-2" retains its original order

  @sad_path
  Scenario: Visibility rule incompatible with parent answer_kind is rejected
    Given question "Q-40" exists with answer_kind "number"
    And question "Q-41" exists with answer_kind unset
    And I have the current "Question-ETag" for "Q-41"
    When I PATCH "/questions/Q-41/visibility" with body:
      | parent_question_id | Q-40  |
      | visible_if_value   | true  |
    And I set header "If-Match" to the current "Question-ETag" for "Q-41"
    Then the request is rejected due to incompatible visibility rule
    And no changes are persisted for question "Q-41"

  @sad_path
  Scenario: Parent cycle is rejected
    Given question "Q-50" has "parent_question_id" Q-51
    And I have the current "Question-ETag" for "Q-51"
    When I PATCH "/questions/Q-51/visibility" with body:
      | parent_question_id | Q-50 |
      | visible_if_value   | 1    |
    And I set header "If-Match" to the current "Question-ETag" for "Q-51"
    Then the request is rejected due to cyclic parent linkage
    And parent/visibility fields remain unchanged for "Q-51"

  @sad_path
  Scenario: Duplicate screen title within a questionnaire is rejected
    Given questionnaire "Q-100" has screens:
      | screen_id | title     | screen_order |
      | S-70      | Policies  | 1            |
    When I POST "/questionnaires/Q-100/screens" with body:
      | title | Policies |
    And I set header "Idempotency-Key" to "idem-s-004"
    Then the request is rejected due to duplicate screen title
    And no new screen is created

  @sad_path
  Scenario: Move question to a screen outside the questionnaire is rejected
    Given question "Q-11" exists on questionnaire "Q-100"
    And screen "S-EXT-1" exists on questionnaire "Q-200"
    And I have the current "Question-ETag" for "Q-11"
    When I PATCH "/questions/Q-11/position" with body:
      | screen_id | S-EXT-1 |
    And I set header "If-Match" to the current "Question-ETag" for "Q-11"
    Then the request is rejected because target screen is outside questionnaire
    And question "Q-11" remains on its original screen

  @sad_path
  Scenario: Move question across questionnaire boundaries is rejected
    Given question "Q-60" exists on questionnaire "Q-100"
    And I have the current "Question-ETag" for "Q-60"
    When I PATCH "/questions/Q-60/position" with body:
      | screen_id | S-EXTERNAL |
    And I set header "If-Match" to the current "Question-ETag" for "Q-60"
    Then the request is rejected due to cross-questionnaire move
    And no changes are persisted for question "Q-60"

  @sad_path
  Scenario: Supplying answer_kind during question creation is rejected
    Given screen "S-2" exists on questionnaire "Q-100"
    When I POST "/questionnaires/Q-100/questions" with body:
      | screen_id     | S-2                 |
      | question_text | Choose one country  |
      | answer_kind   | enum_single         |
    And I set header "Idempotency-Key" to "idem-q-err-01"
    Then the request is rejected because answer_kind cannot be supplied on create
    And no question is created

    @happy_path
    Scenario: Read questions for a screen returns ordered list with Screen-ETag
        Given screen "S-2" exists with questions:
          | question_id | question_text            | question_order |
          | Q-1         | Where is your HQ?        | 1              |
          | Q-2         | How many offices?        | 2              |
        When I GET "/screens/S-2/questions"
        Then the response status should be 200
        And the response should include headers "Screen-ETag"
        And the response body should include:
          | path                        | value                   |
          | questions[0].question_id    | Q-1                     |
          | questions[0].question_text  | Where is your HQ?       |
          | questions[0].question_order | 1                       |
          | questions[1].question_id    | Q-2                     |
          | questions[1].question_text  | How many offices?       |
          | questions[1].question_order | 2                       |
    
    @sad_path
    Scenario: Read questions for unknown screen returns 404
        When I GET "/screens/DOES-NOT-EXIST/questions"
        Then the response status should be 404
