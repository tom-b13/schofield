Feature: Epic C — Document ingestion and parsing
  Manages versioned DOCX template documents with strict ordering, synchronous validation on upload,
  list concurrency via ETag, and deterministic retrieval.

  Background:
    Given a clean database
    And the API base URL is "http://localhost:8080"
    And the DOCX MIME is "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

  # =========================
  # Happy path scenarios
  # =========================

  @happy @create
  Scenario: Create a document with initial metadata
    When I POST "/documents" with JSON:
      """
      { "title": "HR Policy – Leave", "order_number": 3 }
      """
    Then the response status should be 201
    And the response JSON at "document.document_id" should be a valid UUIDv4
    And the response JSON at "document.title" should equal "HR Policy – Leave"
    And the response JSON at "document.order_number" should equal 3
    And the response JSON at "document.version" should equal 1

  @happy @content-put
  Scenario: Upload DOCX content and increment version
    Given I have created a document "D" with title "HR Policy – Leave" and order_number 3 (version 1)
    And I GET "/documents/names" and capture "list_etag" as "LE1"
    And I GET metadata for document "D" and capture the document ETag as "W/\"doc-v1\""
    When I PUT "/documents/{D}/content" with headers:
      | Content-Type   | application/vnd.openxmlformats-officedocument.wordprocessingml.document |
      | Idempotency-Key| idem-001                                                                |
      | If-Match       | W/"doc-v1"                                                              |
      And body is a valid DOCX file of 12345 bytes named "policy-v2.docx"
    Then the response status should be 200
    And the response JSON at "content_result.document_id" should equal "{D}"
    And the response JSON at "content_result.version" should equal 2
    And when I GET metadata for document "D" the version should be 2
    And when I repeat the same PUT with identical Idempotency-Key the response version should equal 2

  @happy @patch
  Scenario: Update title without changing order or version
    Given a document "D" exists with title "Original Title", order_number 5, version 2
    When I PATCH "/documents/{D}" with JSON:
      """
      { "title": "Updated Title" }
      """
    Then the response status should be 200
    And the response JSON at "document.title" should equal "Updated Title"
    And the response JSON at "document.order_number" should equal 5
    And the response JSON at "document.version" should equal 2

  @happy @list
  Scenario: List document names in strict order with list ETag
    Given documents exist:
      | title              | order_number | version |
      | Alpha              | 1            | 1       |
      | Beta               | 2            | 1       |
      | Gamma              | 3            | 2       |
    When I GET "/documents/names"
    Then the response status should be 200
    And the response JSON at "list" should be an array of length 3
    And the response JSON at "list[0].title" should equal "Alpha"
    And the response JSON at "list[1].title" should equal "Beta"
    And the response JSON at "list[2].title" should equal "Gamma"
    And the response JSON at "list_etag" should be a non-empty string
    And the sequence of "order_number" across "list" should be contiguous from 1

  @happy @reorder
  Scenario: Reorder documents atomically using list ETag
    Given documents exist with IDs "E","F","G" and order 1,2,3 respectively
    And I GET "/documents/names" and capture "list_etag" as "LE1"
    When I PUT "/documents/order" with headers:
      | If-Match | LE1 |
      And JSON body:
      """
      {
        "items": [
          { "document_id": "G", "order_number": 1 },
          { "document_id": "E", "order_number": 2 },
          { "document_id": "F", "order_number": 3 }
        ]
      }
      """
    Then the response status should be 200
    And the response JSON at "list[0].document_id" should equal "G"
    And the response JSON at "list[1].document_id" should equal "E"
    And the response JSON at "list[2].document_id" should equal "F"
    And the sequence of "order_number" across "list" should be [1,2,3]

  @happy @delete
  Scenario: Delete a document and resequence remaining orders
    Given documents exist with orders: A→1, B→2, C→3, D→4
    When I DELETE "/documents/{B}"
    Then the response status should be 204
    And when I GET "/documents/names"
    Then the response JSON at "list" should contain three items
    And the sequence of "order_number" across "list" should be [1,2,3]
    And the relative order of remaining docs should be A before C before D

  @happy @download
  Scenario: Download current DOCX content
    Given document "J" has uploaded DOCX content with checksum "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    When I GET "/documents/{J}/content"
    Then the response status should be 200
    And the response header "Content-Type" should equal "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    And the response body length should be > 0
    And the response body SHA-256 should equal "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

  # =========================
  # Key sad path scenarios (subset)
  # =========================

  @sad @pre @create-duplicate-order
  Scenario: Reject duplicate order_number on create
    Given a document exists with order_number 2
    When I POST "/documents" with JSON:
      """
      { "title": "Benefits", "order_number": 2 }
      """
    Then the response status should be 409
    And the response JSON at "code" should equal "PRE_ORDER_NUMBER_DUPLICATE"

  @sad @pre @content-mime
  Scenario: Reject non-DOCX content type on upload
    Given a document "D" exists
    When I PUT "/documents/{D}/content" with headers:
      | Content-Type | text/plain |
      And body "hello world"
    Then the response status should be 415
    And the response JSON at "code" should equal "PRE_CONTENT_TYPE_MISMATCH"

  @sad @pre @if-match-missing
  Scenario: Reject content update without If-Match header
    Given a document "D" exists with version 2
    When I PUT "/documents/{D}/content" with headers:
      | Content-Type   | application/vnd.openxmlformats-officedocument.wordprocessingml.document |
      | Idempotency-Key| idem-002                                                                |
      And body is a valid DOCX file
    Then the response status should be 428
    And the response JSON at "code" should equal "PRE_IF_MATCH_MISSING_DOCUMENT"

  @sad @run @reorder-stale-etag
  Scenario: Reject reorder with stale list ETag
    Given documents exist with a current list ETag "W/\"list-v4\""
    When I PUT "/documents/order" with headers:
      | If-Match | W/"list-v3" |
      And JSON body:
      """
      {
        "items": [
          { "document_id": "X", "order_number": 1 }
        ]
      }
      """
    Then the response status should be 412
    And the response JSON at "code" should equal "RUN_LIST_ETAG_MISMATCH"

  @sad @run @invalid-docx
  Scenario: Reject structurally invalid DOCX on upload
    Given a document "D" exists with version 1 and ETag W/"doc-v1"
    When I PUT "/documents/{D}/content" with headers:
      | Content-Type   | application/vnd.openxmlformats-officedocument.wordprocessingml.document |
      | Idempotency-Key| idem-003                                                                |
      | If-Match       | W/"doc-v1"                                                              |
      And body is an invalid DOCX byte stream
    Then the response status should be 422
    And the response JSON at "code" should equal "RUN_UPLOAD_VALIDATION_FAILED"

  @sad @pre @doc-not-found
  Scenario: Reject content update for unknown document
    When I PUT "/documents/4f2a3b9d-9b2a-4d8b-932a-d1e9a1f1d001/content" with headers:
      | Content-Type   | application/vnd.openxmlformats-officedocument.wordprocessingml.document |
      | Idempotency-Key| idem-004                                                                |
      | If-Match       | W/"doc-v1"                                                              |
      And body is a valid DOCX file
    Then the response status should be 404
    And the response JSON at "code" should equal "PRE_DOCUMENT_NOT_FOUND"
