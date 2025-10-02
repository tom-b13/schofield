# scope

purpose
Enable upload, versioning, and validation of DOCX source documents with deterministic rules. Keep the data model simple. Do not compute diffs between versions. Placeholders are not stored until they are allocated to a question.

inclusions

* Upload DOCX and maintain a version number on the document record.
* A required order_number defines document ordering for stitched downloads and admin views.
* Synchronous validation of DOCX structure on upload (e.g., confirm it is well formed); no normalisation or deeper parsing.
* Endpoints to support: GET /documents/names, POST /documents, PUT /documents/{document_id}/content, PATCH /documents/{document_id}, DELETE /documents/{document_id}, PUT /documents/order

exclusions

* Diffs across versions.
* Autosave. Saving happens only when a user clicks save.
* Storing placeholders at parse time. Placeholders are stored only when allocated to a question.
* Template rendering and merge.
* OCR or PDF parsing.

non functional

* Deterministic parsing for identical inputs.
* Idempotent uploads by content hash.
* Problem+json errors.
* No authentication required yet (will be handled in another epic).

# data model

Keep table names aligned to existing conventions.

* document
  id (uuid), title (text), uq_document_order_number (int unique not null), version (int not null default 1), created_at, updated_at

* document_blob
  id (uuid), document_id (fk), file_sha256 (char(64)), filename (text), mime (text), byte_size (int), storage_url (text), uploaded_at, uploaded_by
  unique(document_id)

  notes: holds the current binary for the document. when content is replaced via save, overwrite this row fields and increment document.version by 1 in the same transaction. prior binaries are not retained by this epic. if we later need history, we can reintroduce document_revision.

# behaviours

versioning

* Each explicit save that replaces DOCX content increments document.version by 1.
* No autosave. The UI must call the relevant endpoint only when the user clicks save.

ordering

* After a document is deleted, the system will resequence order_number for all remaining documents to be strict 1..N with no gaps, performed atomically in the same transaction.
* When the UI submits a reordered list via PUT /documents/order, the system will atomically update all order_number values to match the submitted order (strict 1..N) and return the new ordered list.

parsing determinism

* Same bytes always produce the same outcome under the current rules (no deeper parsing or normalisation).

# apis

conventions

* Continue to use Idempotency Key for uploads and Problem+json for errors.
* ETag applies to read endpoints where a stable snapshot is returned for a given document.version.

Upload and store DOCX with explicit save

* POST /documents — for creating a brand new document record with a title and order_number. Updating existing documents happens via PUT /documents/{document_id}/content or PATCH /documents/{document_id}
  body: { title,  order_number }
  returns: { document_id, title, order_number, version }

* PUT /documents/{document_id}/content\

    headers: Idempotency-Key, If-Match (required for concurrency control)\

    content-type: application/vnd.openxmlformats-officedocument.wordprocessingml.document\

    body: raw bytes\

    behaviour:

  * Validate content type.

  * Calculate file_sha256.

  * Compare If-Match ETag with current document ETag; on mismatch, return 409 with the current ETag in response headers.

  * Store or overwrite document_blob for the document.

  * Increment document.version by 1.

* PATCH /documents/{document_id}
  body: { title }
  rules: order_number cannot be changed here; use PUT /documents/order to resequence.
  returns: updated metadata

* GET /documents/names
  purpose: UI index needs a list of all documents.
  returns: [{ document_id, title, order_number, version }], sorted by order_number asc, then title asc.

* DELETE /documents/{document_id}
  behaviour: deletes the document and associated blob and jobs, then resequences order_number across remaining documents to 1..N with no gaps in the same transaction

* PUT /documents/order
  body: { items: [{ document_id, order_number }, ...] }
  rules:

  * The set of document_id values must cover all documents intended to be ordered; order_number must form a strict 1..N sequence with no duplicates or gaps.
  * Operation is atomic; on any validation error, no changes are committed.
  * Idempotent: submitting the same sequence produces no changes.
    returns: [{ document_id, title, order_number, version }]
    errors:
  * 400 if sequence invalid (duplicates, gaps, or non-existent IDs).
  * 409 if a concurrent change is detected. Client must send If-Match with the list ETag from GET /documents/names; the server compares it to the current list ETag and, on mismatch, returns 409 and includes the current ETag in the response headers.

# migration notes

* Add document table with unique index on order_number (e.g. uq_document_order_number).

  Add document_blob table with unique(document_id).

1. Scope
1.1 Purpose

Enable users to upload, save, and manage versioned DOCX template documents. The objective is to provide a simple mechanism to store documents, enforce a strict order for later stitched outputs, and validate files on upload.

1.2 Inclusions

Upload and save DOCX files with explicit version increments.

Maintain a unique sequential order number for each document.

Synchronous validation of DOCX structure during upload.

Endpoints to create, update, delete, list, and reorder documents.

Automatic resequencing of order numbers when documents are deleted or reordered.

1.3 Exclusions

Automatic or background parsing beyond structural validation.

Autosave functionality.

Placeholder storage during upload; placeholders are only saved when allocated to questions.

OCR, PDF, or non-DOCX file handling.

Authentication and authorisation (to be handled in a future epic).

1.4 Context

This story supports document management as part of a larger system that assembles multiple policy or template files into a stitched output. It provides the foundation for later placeholder allocation and questionnaire integration handled in other epics. The scope interacts only with internal document storage and exposes REST API endpoints for the UI to upload, reorder, and manage documents. No external services are required at this stage.

| Field                | Description                                              | Type             | Schema / Reference                                                                  | Notes                                                                                                | Pre-Conditions                                                                                                                                    | Origin   |
| -------------------- | -------------------------------------------------------- | ---------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| title                | Title for a new document or a metadata update via PATCH  | string           | schemas/Document.schema.json#/properties/title                                      | Used by POST /documents and PATCH /documents/{document_id}.                                          | Field is required and must be provided; Value must be a non-empty string; Value must be UTF-8 encodable                                           | provided |
| order_number         | Sequential ordering position for the document            | integer          | schemas/Document.schema.json#/properties/order_number                               | Unique and gap-free across all documents; resequenced by DELETE and PUT /documents/order only.       | Field is required and must be provided; Value must be a positive integer; Value must not duplicate any existing order_number                      | provided |
| document_id          | Identifier of the target document (path parameter)       | string (uuid)    | schemas/DocumentId.schema.json                                                      | Used by PUT /documents/{document_id}/content, PATCH, and DELETE.                                     | Field is required and must be provided; Value must be a valid UUID; Value must reference an existing document                                     | provided |
| raw_bytes            | Binary DOCX payload uploaded on create/update            | file (docx)      | schemas/DocumentBlob.schema.json#/properties/file_sha256 (checksum of this content) | Sent to PUT /documents/{document_id}/content; server derives checksum and metadata.                  | File exists and is readable; Content parses as valid DOCX; Content conforms to the referenced schema                                              | provided |
| Content-Type         | MIME type for the uploaded payload                       | string           | openapi.yaml#/components/parameters/ContentType (provisional)                       | Must be application/vnd.openxmlformats-officedocument.wordprocessingml.document.                     | Field is required and must be provided; Value must equal the DOCX MIME type; Value must be a non-empty string                                     | provided |
| Idempotency-Key      | Header to guarantee idempotent content uploads           | string           | openapi.yaml#/components/parameters/IdempotencyKey                                  | Required on PUT /documents/{document_id}/content.                                                    | Field is required and must be provided; Value must be a non-empty string; Value must be unique per logical upload attempt                         | provided |
| If-Match             | ETag header for optimistic concurrency control           | string           | openapi.yaml#/components/parameters/IfMatch                                         | Used on PUT /documents/{document_id}/content (document ETag) and PUT /documents/order (list ETag).   | Field is required and must be provided; Value must equal the current ETag for the addressed resource; Value must be a non-empty string            | provided |
| items[].document_id  | Document identifier in a reorder request item            | string (uuid)    | schemas/ReorderRequest.schema.json#/properties/items/items/properties/document_id   | Part of PUT /documents/order request body.                                                           | Field is required and must be provided; Value must be a valid UUID; Value must reference an existing document                                     | provided |
| items[].order_number | Target sequential order number in a reorder request item | integer          | schemas/ReorderRequest.schema.json#/properties/items/items/properties/order_number  | Values across items must form a strict 1..N sequence.                                                | Field is required and must be provided; Value must be a positive integer; Sequence across all items must be contiguous without duplicates or gaps | provided |
| filename             | Original filename of the uploaded DOCX                   | string           | schemas/DocumentBlob.schema.json#/properties/filename                               | Captured from upload for audit and storage metadata.                                                 | Field is required and must be provided; Value must be a non-empty string; Value must be UTF-8 encodable                                           | provided |
| file_sha256          | SHA-256 checksum computed from raw_bytes                 | string (hex[64]) | schemas/DocumentBlob.schema.json#/properties/file_sha256                            | Derived server-side and stored with the blob.                                                        | File must hash successfully; Hash length must be exactly 64 hex characters; Hash must match content on persistence                                | acquired |
| mime                 | Persisted MIME type of stored DOCX                       | string           | schemas/DocumentBlob.schema.json#/properties/mime                                   | Should be the standard DOCX MIME type.                                                               | Resource must exist and be readable by the process; Value must equal the DOCX MIME type                                                           | acquired |
| byte_size            | Persisted byte size of stored DOCX                       | integer          | schemas/DocumentBlob.schema.json#/properties/byte_size                              | Recorded for storage/accounting.                                                                     | Resource must exist and be readable by the process; Value must be an integer ≥ 1                                                                  | acquired |
| storage_url          | Internal storage locator for the blob                    | string           | schemas/DocumentBlob.schema.json#/properties/storage_url                            | Implementation-specific location (object storage, DB pointer).                                       | Resource must exist and be readable by the process; Reference must resolve to a retrievable object                                                | acquired |

| Field                              | Description                                                          | Type          | Schema / Reference                                                                                                                                                                                                                                                 | Notes                                                                                                              | Post-Conditions                                                                                                                                                                                                                                                  | Origin    |
| ---------------------------------- | -------------------------------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| outputs                            | Canonical response and persistence container for this feature        | object        | schemas/DocumentResponse.schema.json (for document responses); schemas/DocumentListResponse.schema.json (for list responses); schemas/ContentUpdateResult.schema.json (for content updates); schemas/BlobMetadataProjection.schema.json (for blob metadata projection) | Envelope varies by endpoint; each schema is endpoint-specific and reuses existing component schemas where possible | Object validates against the referenced endpoint schema; Key set is deterministic for the addressed endpoint; Field is required for all responses that return a body                                                                                             | returned  |
| outputs.document                   | The current document resource returned by create or metadata update  | object        | schemas/DocumentResponse.schema.json#/properties/document                                                                                                                                                                                                           | Used by POST /documents and PATCH /documents/{document_id}                                                         | Object validates against schema; Field is required when a single document is returned; Object contains keys document_id, title, order_number, version                                                                                                            | returned  |
| outputs.document.document_id       | Identifier of the document                                           | string        | schemas/DocumentResponse.schema.json#/properties/document/properties/document_id                                                                                                                                                                                    | UUID string                                                                                                        | Value validates as UUID; Value corresponds to a persisted document row; Field is required when outputs.document is present                                                                                                                                       | returned  |
| outputs.document.title             | Title of the document                                                | string        | schemas/DocumentResponse.schema.json#/properties/document/properties/title                                                                                                                                                                                          | Reuses existing Document.title definition                                                                          | Value is a non-empty string; Value equals the persisted title for the document; Field is required when outputs.document is present                                                                                                                               | returned  |
| outputs.document.order_number      | Sequential order number of the document                              | integer       | schemas/DocumentResponse.schema.json#/properties/document/properties/order_number                                                                                                                                                                                   | Reuses existing Document.order_number definition                                                                   | Value is a positive integer; Value is unique among all documents; Value reflects current persisted ordering; Field is required when outputs.document is present                                                                                                  | returned  |
| outputs.document.version           | Version number of the document                                       | integer       | schemas/DocumentResponse.schema.json#/properties/document/properties/version                                                                                                                                                                                        | Increments only when content is updated via PUT /documents/{document_id}/content                                   | Value is a positive integer; Value equals the persisted version; Value increases only on content updates; Field is required when outputs.document is present                                                                                                     | returned  |
| outputs.content_result             | Summary object for a successful content update                       | object        | schemas/ContentUpdateResult.schema.json#/properties/content_result                                                                                                                                                                                                  | Used by PUT /documents/{document_id}/content                                                                       | Object validates against schema; Field is required on successful content update; Object contains keys document_id, version                                                                                                                                       | returned  |
| outputs.content_result.document_id | Identifier of the updated document                                   | string        | schemas/ContentUpdateResult.schema.json#/properties/content_result/properties/document_id                                                                                                                                                                           | UUID string                                                                                                        | Value validates as UUID; Value matches the addressed path parameter; Field is required when outputs.content_result is present                                                                                                                                    | returned  |
| outputs.content_result.version     | New version after content update                                     | integer       | schemas/ContentUpdateResult.schema.json#/properties/content_result/properties/version                                                                                                                                                                               | Reflects increment caused by content change                                                                        | Value is a positive integer; Value equals previous version plus one; Field is required when outputs.content_result is present                                                                                                                                    | returned  |
| outputs.list                       | Ordered list of document summaries for the UI index or after reorder | list[object]  | schemas/DocumentListResponse.schema.json#/properties/list                                                                                                                                                                                                           | Used by GET /documents/names and PUT /documents/order                                                              | Array validates against schema; Items are instances of the declared item schema; Items are sorted by order_number ascending; Array may be empty                                                                                                                  | returned  |
| outputs.list[].document_id         | Identifier for a list item                                           | string        | schemas/DocumentListResponse.schema.json#/properties/list/items/properties/document_id                                                                                                                                                                              | UUID string                                                                                                        | Value validates as UUID; Value corresponds to a persisted document row; Field is required for every item in outputs.list                                                                                                                                         | returned  |
| outputs.list[].title               | Title for a list item                                                | string        | schemas/DocumentListResponse.schema.json#/properties/list/items/properties/title                                                                                                                                                                                    | Reuses existing Document.title definition                                                                          | Value is a non-empty string; Field is required for every item in outputs.list                                                                                                                                                                                    | returned  |
| outputs.list[].order_number        | Sequential order for a list item                                     | integer       | schemas/DocumentListResponse.schema.json#/properties/list/items/properties/order_number                                                                                                                                                                             | Reuses existing Document.order_number definition                                                                   | Values across items form a strict 1..N sequence without gaps; Field is required for every item in outputs.list                                                                                                                                                   | returned  |
| outputs.list[].version             | Version for a list item                                              | integer       | schemas/DocumentListResponse.schema.json#/properties/list/items/properties/version                                                                                                                                                                                  | Reuses existing Document.version definition                                                                        | Value is a positive integer; Field is required for every item in outputs.list                                                                                                                                                                                    | returned  |
| outputs.list_etag                  | ETag representing the current list ordering state                    | string        | schemas/DocumentListResponse.schema.json#/properties/list_etag                                                                                                                                                                                                      | Provided in responses that expose the ordered list                                                                 | Value is a non-empty string; Value changes when ordering or membership changes; Field is required on GET /documents/names responses; Field is optional on PUT /documents/order responses                                                                         | returned  |
| outputs.content_file               | The current DOCX file content for download                           | file (binary) | schemas/DocumentContentResponse.schema.json                                                                                                                                                                                                                         | Binary response body, not JSON; endpoint streams file content                                                      | File bytes validate as a well-formed DOCX; MIME type equals application/vnd.openxmlformats-officedocument.wordprocessingml.document; File content corresponds to the persisted blob for the addressed document; Field is required on successful content download | returned  |
| outputs.blob_metadata              | Persisted metadata for the stored DOCX blob                          | object        | schemas/BlobMetadataProjection.schema.json#/properties/blob_metadata                                                                                                                                                                                                | Projection of persisted state following content upload                                                             | Object validates against schema; Object contains keys file_sha256, filename, mime, byte_size, storage_url; Field is required to be persisted after successful content upload; Field is optional to include in responses                                          | persisted |
| outputs.blob_metadata.file_sha256  | SHA-256 checksum of the blob                                         | string        | schemas/DocumentBlob.schema.json#/properties/file_sha256                                                                                                                                                                                                            | Hex-encoded 64-character checksum                                                                                  | Value length is 64 hexadecimal characters; Value matches the checksum of outputs.content_file when present; Field is required to be persisted after successful content upload                                                                                    | persisted |
| outputs.blob_metadata.filename     | Original filename of the uploaded DOCX                               | string        | schemas/DocumentBlob.schema.json#/properties/filename                                                                                                                                                                                                               | Reuses existing DocumentBlob.filename definition                                                                   | Value is a non-empty string; Value is UTF-8 encodable; Field is required to be persisted after successful content upload                                                                                                                                         | persisted |
| outputs.blob_metadata.mime         | Persisted MIME type                                                  | string        | schemas/DocumentBlob.schema.json#/properties/mime                                                                                                                                                                                                                   | Standard DOCX MIME type                                                                                            | Value equals application/vnd.openxmlformats-officedocument.wordprocessingml.document; Field is required to be persisted after successful content upload                                                                                                          | persisted |
| outputs.blob_metadata.byte_size    | Persisted byte size                                                  | integer       | schemas/DocumentBlob.schema.json#/properties/byte_size                                                                                                                                                                                                              | Reuses existing DocumentBlob.byte_size definition                                                                  | Value is an integer greater than or equal to 1; Field is required to be persisted after successful content upload                                                                                                                                                | persisted |
| outputs.blob_metadata.storage_url  | Internal storage locator                                             | path          | schemas/DocumentBlob.schema.json#/properties/storage_url                                                                                                                                                                                                            | Logical locator or URL depending on storage implementation                                                         | Value resolves to a retrievable object in storage; Value is a non-empty string; Field is required to be persisted after successful content upload                                                                                                                | persisted |

| Error Code                         | Description                                                | Likely Cause                                                           | Source (Step in Section 2.x)                                                                                           | Step ID (from Section 2.2.6) | Reachability Rationale                                                                  | Flow Impact        | Behavioural AC Required |
| ---------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ---------------------------- | --------------------------------------------------------------------------------------- | ------------------ | ----------------------- |
| RUN_UPLOAD_VALIDATION_FAILED       | Upload of a DOCX file failed during synchronous validation | Malformed DOCX structure or unsupported encoding                       | 2.2.2 Event-driven – “When a user uploads a DOCX file, the system will synchronously validate its structure.”          | STEP-2 Inclusions            | Validation is explicitly required on upload; invalid DOCX produces runtime failure      | halt_pipeline      | Yes                     |
| RUN_DELETE_RESEQUENCE_FAILED       | Automatic resequencing after document deletion failed      | Database constraint error or sequencing logic failure                  | 2.2.2 Event-driven – “When a user deletes a document, the system will resequence the order numbers…”                   | STEP-2 Inclusions            | Deletion triggers mandatory resequencing; resequencing logic can fail at runtime        | halt_pipeline      | Yes                     |
| RUN_REORDER_SEQUENCE_INVALID       | Submitted reorder sequence could not be applied            | Inconsistent order numbers (e.g. duplicates, gaps) detected at runtime | 2.2.2 Event-driven – “When a user reorders documents via the UI…”                                                      | STEP-2 Inclusions            | Reorder must form a strict 1..N sequence; if not, runtime resequencing fails            | halt_pipeline      | Yes                     |
| RUN_METADATA_PERSISTENCE_FAILED    | Persisting document metadata failed                        | Database write failure when saving title/order/version                 | 2.2.1 Ubiquitous – “The system will save uploaded DOCX documents as immutable records.”                                | STEP-1 Purpose               | Any persistence step can fail at runtime even if pre-conditions passed                  | halt_pipeline      | Yes                     |
| RUN_BLOB_STORAGE_FAILURE           | Writing or reading the DOCX blob failed                    | Storage backend unavailable or write error                             | 2.2.1 Ubiquitous – “The system will allow users to upload DOCX template documents.”                                    | STEP-1 Purpose               | Blob persistence is part of storing the document; failure is a runtime error            | halt_pipeline      | Yes                     |
| RUN_LIST_ETAG_MISMATCH             | Concurrency check on list_etag failed                      | If-Match header does not match current list state                      | 2.2.1 Ubiquitous – “The system will expose endpoints… reorder documents.” (with concurrency)                           | STEP-2 Inclusions            | PUT /documents/order requires concurrency control; mismatch yields runtime error        | block_finalization | Yes                     |
| RUN_DOCUMENT_ETAG_MISMATCH         | Concurrency check on document ETag failed                  | If-Match header does not match current document state                  | 2.2.1 Ubiquitous – “The system will increment version only when content updates” (with optimistic concurrency)         | STEP-2 Inclusions            | PUT /documents/{id}/content requires concurrency check; mismatch yields runtime error   | block_finalization | Yes                     |
| RUN_STATE_RETENTION_FAILURE        | Retention of document metadata state failed                | Corruption or inconsistency detected in stored metadata                | 2.2.3 State-driven – “While a document is stored, the system will retain its title, version number, and order number…” | STEP-4 Context               | State persistence is mandatory; corruption or read failure is a runtime error           | halt_pipeline      | Yes                     |
| RUN_OPTIONAL_STITCH_ACCESS_FAILURE | Accessing documents for stitched outputs failed            | Downstream epic requests stitched output but access fails              | 2.2.4 Optional-feature – “Where stitched outputs are requested…”                                                       | STEP-4 Context               | Although optional, if invoked the system must provide docs in order; failure is runtime | halt_pipeline      | Yes                     |

| Error Code                             | Description                                                                              | Likely Cause                                             | Impacted Steps | EARS Refs                  | Flow Impact        | Behavioural AC Required |
| -------------------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------- | -------------- | -------------------------- | ------------------ | ----------------------- |
| ENV_DB_UNAVAILABLE                     | Database service is unavailable during document create, update, delete, list, or reorder | Database host down or connection refused                 | STEP-1, STEP-2 | U2, U4, U5, U6, S1, E2, E3 | halt_pipeline      | Yes                     |
| ENV_DB_PERMISSION_DENIED               | Database rejects credentials required for persistence or resequencing                    | Invalid username/password or revoked role                | STEP-1, STEP-2 | U2, U4, U5, U6, S1, E2, E3 | halt_pipeline      | Yes                     |
| ENV_OBJECT_STORAGE_UNAVAILABLE         | Object storage is unreachable when writing or reading DOCX blobs                         | Storage endpoint offline or network partition            | STEP-1, STEP-2 | U1, U2, U6, E1             | halt_pipeline      | Yes                     |
| ENV_OBJECT_STORAGE_PERMISSION_DENIED   | Object storage denies access to the target container or key                              | Missing/expired access key or insufficient bucket policy | STEP-1, STEP-2 | U1, U2, U6, E1             | halt_pipeline      | Yes                     |
| ENV_NETWORK_UNREACHABLE_STORAGE        | Network connectivity to object storage fails during content upload or download           | Network unreachable, routing failure, or firewall block  | STEP-1, STEP-2 | U1, U2, U6, E1             | halt_pipeline      | Yes                     |
| ENV_DNS_RESOLUTION_FAILED_STORAGE      | DNS name for object storage cannot be resolved                                           | Misconfigured DNS or upstream DNS outage                 | STEP-1, STEP-2 | U1, U2, U6, E1             | halt_pipeline      | Yes                     |
| ENV_TLS_HANDSHAKE_FAILED_STORAGE       | TLS handshake with object storage fails                                                  | Invalid certificate, unsupported cipher, or clock skew   | STEP-1, STEP-2 | U1, U2, U6, E1             | halt_pipeline      | Yes                     |
| ENV_CONFIG_MISSING_DB_CREDENTIALS      | Runtime configuration for database credentials is missing                                | Absent environment variables or secrets not mounted      | STEP-1, STEP-2 | U2, U4, U5, U6, S1, E2, E3 | halt_pipeline      | Yes                     |
| ENV_CONFIG_MISSING_STORAGE_CREDENTIALS | Runtime configuration for object storage credentials is missing                          | Absent environment variables or secrets not mounted      | STEP-1, STEP-2 | U1, U2, U6, E1             | halt_pipeline      | Yes                     |
| ENV_FILESYSTEM_TEMP_UNAVAILABLE        | Temporary directory required for handling upload streams is unavailable                  | Temp path missing or not mounted                         | STEP-1, STEP-2 | U1, U2, U6, E1             | halt_pipeline      | Yes                     |
| ENV_DISK_SPACE_EXHAUSTED               | Local disk space insufficient for buffering uploads or assembling responses              | Disk quota exceeded or full partition                    | STEP-1, STEP-2 | U1, U2, U6, E1             | halt_pipeline      | Yes                     |
| ENV_RATE_LIMIT_EXCEEDED_STORAGE        | Object storage rate limit exceeded during burst uploads or downloads                     | Per-account or per-bucket API throttling                 | STEP-1, STEP-2 | U1, U2, U6, E1             | block_finalization | Yes                     |
| ENV_QUOTA_EXCEEDED_STORAGE             | Object storage quota exceeded for the account or bucket                                  | Capacity limit reached for bucket or account             | STEP-1, STEP-2 | U1, U2, U6, E1             | halt_pipeline      | Yes                     |

### 6.1 Architectural Acceptance Criteria

#### 6.1.1 Document table schema

The `document` table must include the fields `id`, `title`, `order_number` (unique, not null), `version` (default 1), `created_at`, and `updated_at`, as specified.
*Reference: Scope §data model; U4, U5; outputs.document.order_number, outputs.document.version*

#### 6.1.2 Unique sequential ordering constraint

The `document` table must enforce a unique sequential `order_number` via a database constraint or index.
*Reference: Behaviours – ordering; STEP-2 Inclusions; U4, U5; outputs.list[].order_number*

#### 6.1.3 Document blob schema

The `document_blob` table must include `id`, `document_id` (foreign key), `file_sha256`, `filename`, `mime`, `byte_size`, `storage_url`, `uploaded_at`, `uploaded_by`, with a unique constraint on `document_id`.
*Reference: Scope §data model; U2, U7; outputs.blob_metadata.*

#### 6.1.4 Atomic version increments

The architecture must increment `document.version` atomically in the same transaction when `document_blob` content is replaced.
*Reference: Behaviours – versioning; E1; outputs.content_result.version*

#### 6.1.5 No diffs retained

The architecture must not create or persist diffs or revision history between document versions.
*Reference: Scope §exclusions; U3*

#### 6.1.6 Synchronous validation enforcement

The upload pipeline must include a deterministic, synchronous validation step that accepts only valid DOCX files.
*Reference: Inclusions; E1; RUN_UPLOAD_VALIDATION_FAILED*

#### 6.1.7 Idempotency key support

The API layer must require and persist an `Idempotency-Key` header for PUT /documents/{document_id}/content requests.
*Reference: APIs – conventions; STEP-2 Inclusions; inputs.Idempotency-Key*

#### 6.1.8 Concurrency control via ETag

The architecture must compare an `If-Match` header value against the current document or list ETag to enforce optimistic concurrency.
*Reference: APIs – PUT /documents/{id}/content and PUT /documents/order; STEP-2 Inclusions; outputs.list_etag, outputs.document.version*

#### 6.1.9 Deterministic parsing property

The DOCX ingestion path must produce identical persisted artefacts and metadata for identical byte streams.
*Reference: Behaviours – parsing determinism; U7*

#### 6.1.10 Atomic resequencing on delete

When a document is deleted, resequencing of all remaining `order_number` values must occur atomically within the same transaction.
*Reference: Behaviours – ordering; E2; outputs.list[].order_number*

#### 6.1.11 Atomic resequencing on reorder

PUT /documents/order must atomically update all `order_number` values in a single transaction.
*Reference: Behaviours – ordering; E3; outputs.list[].order_number*

#### 6.1.12 Output schema separation

The architecture must provide distinct response schema definitions for document metadata (`DocumentResponse`), document lists (`DocumentListResponse`), content updates (`ContentUpdateResult`), and blob metadata (`BlobMetadataProjection`).
*Reference: Outputs table – outputs.*, outputs.list, outputs.blob_metadata*

#### 6.1.13 Strict title persistence

The `document.title` field must be stored as a non-empty UTF-8 string and updated only via PATCH /documents/{id}.
*Reference: Inputs.title; outputs.document.title; S1*

#### 6.1.14 No order updates via PATCH

PATCH /documents/{id} must not include or alter `order_number`; reordering is confined to PUT /documents/order.
*Reference: APIs – PATCH rules; STEP-2 Inclusions*

#### 6.1.15 Problem+json format

All errors surfaced by this epic must conform to Problem+json format, ensuring a consistent error contract.
*Reference: Non functional – Problem+json errors; STEP-2 Inclusions*

### 6.2 Happy Path Contractual Acceptance Criteria

#### 6.2.1.1 Create document with metadata

*Given* a user submits a valid POST /documents request with `title` and `order_number`
*When* the request is processed successfully
*Then* the response must include `outputs.document` with fields `document_id`, `title`, `order_number`, and `version` (initialised to 1).
**Reference:** U2, U4; outputs.document.*

#### 6.2.1.2 Increment version on content update

*Given* a user submits a valid PUT /documents/{document_id}/content request with a DOCX payload and matching `If-Match` header
*When* the request succeeds
*Then* the response must include `outputs.content_result.version` equal to the previous version plus one.
**Reference:** E1; outputs.content_result.version.*

#### 6.2.1.3 Persist blob metadata on content update

*Given* a user updates a document with PUT /documents/{document_id}/content
*When* the content is valid and accepted
*Then* the persisted state must include `outputs.blob_metadata.file_sha256`, `filename`, `mime`, `byte_size`, and `storage_url`.
**Reference:** U6, E1; outputs.blob_metadata.*

#### 6.2.1.4 Patch updates title only

*Given* a user submits a valid PATCH /documents/{document_id} request with a `title` value
*When* the request succeeds
*Then* the response must include `outputs.document.title` equal to the updated title, and `order_number` must remain unchanged.
**Reference:** S1; outputs.document.title.*

#### 6.2.1.5 Delete resequences order

*Given* a user deletes a document with DELETE /documents/{document_id}
*When* the request succeeds
*Then* the system must resequence all remaining documents’ `outputs.list[].order_number` to form a contiguous 1..N sequence.
**Reference:** E2; outputs.list[].order_number.*

#### 6.2.1.6 Reorder resequences order

*Given* a user submits PUT /documents/order with a valid contiguous sequence of document IDs and order numbers
*When* the request succeeds
*Then* the response must include `outputs.list` sorted by the new `order_number` values, with no duplicates or gaps.
**Reference:** E3; outputs.list[].order_number.*

#### 6.2.1.7 Return list with ETag

*Given* a user calls GET /documents/names
*When* the request succeeds
*Then* the response must include `outputs.list` and `outputs.list_etag` representing the current ordering state.
**Reference:** U5; outputs.list, outputs.list_etag.*

#### 6.2.1.8 Deterministic parsing outcome

*Given* two uploads with identical DOCX byte streams and metadata
*When* both are processed
*Then* the persisted `outputs.blob_metadata.file_sha256` and derived metadata must be identical.
**Reference:** U7; outputs.blob_metadata.file_sha256.*

#### 6.2.1.9 Download DOCX content

*Given* a user calls GET /documents/{document_id}/content with a valid ID
*When* the document exists
*Then* the response must stream `outputs.content_file` as a binary DOCX with the correct MIME type.
**Reference:** U1; outputs.content_file.*

### 6.2.2 Sad Path Contractual Acceptance Criteria

#### 6.2.2.1 Title missing on create

*Given* a POST /documents request without `title`
*When* the request is validated
*Then* the system must return an error with code PRE_TITLE_MISSING.
**Error Mode:** PRE_TITLE_MISSING
**Reference:** inputs.title

#### 6.2.2.2 order_number missing on create

*Given* a POST /documents request without `order_number`
*When* the request is validated
*Then* the system must return an error with code PRE_ORDER_NUMBER_MISSING.
**Error Mode:** PRE_ORDER_NUMBER_MISSING
**Reference:** inputs.order_number

#### 6.2.2.3 order_number not positive

*Given* a POST /documents request with `order_number` ≤ 0
*When* the request is validated
*Then* the system must return an error with code PRE_ORDER_NUMBER_NOT_POSITIVE.
**Error Mode:** PRE_ORDER_NUMBER_NOT_POSITIVE
**Reference:** inputs.order_number

#### 6.2.2.4 order_number duplicate on create

*Given* a POST /documents request whose `order_number` duplicates an existing document
*When* the request is validated
*Then* the system must return an error with code PRE_ORDER_NUMBER_DUPLICATE.
**Error Mode:** PRE_ORDER_NUMBER_DUPLICATE
**Reference:** inputs.order_number

#### 6.2.2.5 document_id invalid format

*Given* a request addressing `{document_id}` that is not a valid UUID
*When* the path parameter is validated
*Then* the system must return an error with code PRE_DOCUMENT_ID_INVALID.
**Error Mode:** PRE_DOCUMENT_ID_INVALID
**Reference:** inputs.document_id

#### 6.2.2.6 document not found

*Given* a request addressing `{document_id}` that does not exist
*When* the identifier is resolved
*Then* the system must return an error with code PRE_DOCUMENT_NOT_FOUND.
**Error Mode:** PRE_DOCUMENT_NOT_FOUND
**Reference:** inputs.document_id

#### 6.2.2.7 Content-Type unsupported

*Given* a PUT /documents/{document_id}/content request with a non-DOCX `Content-Type`
*When* headers are validated
*Then* the system must return an error with code PRE_CONTENT_TYPE_MISMATCH.
**Error Mode:** PRE_CONTENT_TYPE_MISMATCH
**Reference:** inputs.Content-Type

#### 6.2.2.8 Raw bytes missing on content upload

*Given* a PUT /documents/{document_id}/content request without a binary body
*When* the body is validated
*Then* the system must return an error with code PRE_RAW_BYTES_MISSING.
**Error Mode:** PRE_RAW_BYTES_MISSING
**Reference:** inputs.raw_bytes

#### 6.2.2.9 Idempotency-Key missing

*Given* a PUT /documents/{document_id}/content request without `Idempotency-Key`
*When* headers are validated
*Then* the system must return an error with code PRE_IDEMPOTENCY_KEY_MISSING.
**Error Mode:** PRE_IDEMPOTENCY_KEY_MISSING
**Reference:** inputs.Idempotency-Key

#### 6.2.2.10 If-Match missing for content update

*Given* a PUT /documents/{document_id}/content request without `If-Match`
*When* headers are validated
*Then* the system must return an error with code PRE_IF_MATCH_MISSING_DOCUMENT.
**Error Mode:** PRE_IF_MATCH_MISSING_DOCUMENT
**Reference:** inputs.If-Match

#### 6.2.2.11 If-Match missing for reorder

*Given* a PUT /documents/order request without `If-Match`
*When* headers are validated
*Then* the system must return an error with code PRE_IF_MATCH_MISSING_LIST.
**Error Mode:** PRE_IF_MATCH_MISSING_LIST
**Reference:** inputs.If-Match

#### 6.2.2.12 Reorder items empty

*Given* a PUT /documents/order request with an empty `items` array
*When* the body is validated
*Then* the system must return an error with code PRE_REORDER_ITEMS_EMPTY.
**Error Mode:** PRE_REORDER_ITEMS_EMPTY
**Reference:** inputs.items[].document_id, inputs.items[].order_number

#### 6.2.2.13 Reorder sequence invalid (gaps/duplicates)

*Given* a PUT /documents/order request whose `order_number` values contain gaps or duplicates
*When* the sequence is validated
*Then* the system must return an error with code PRE_REORDER_SEQUENCE_INVALID.
**Error Mode:** PRE_REORDER_SEQUENCE_INVALID
**Reference:** inputs.items[].order_number, outputs.list[].order_number

#### 6.2.2.14 Reorder contains unknown document_id

*Given* a PUT /documents/order request containing an item with an unknown `document_id`
*When* identifiers are resolved
*Then* the system must return an error with code PRE_REORDER_UNKNOWN_DOCUMENT_ID.
**Error Mode:** PRE_REORDER_UNKNOWN_DOCUMENT_ID
**Reference:** inputs.items[].document_id

#### 6.2.2.15 Invalid DOCX upload rejected

*Given* a user uploads a file that is not a valid DOCX structure
*When* synchronous validation is performed
*Then* the system must return an error with code RUN_UPLOAD_VALIDATION_FAILED.
**Error Mode:** RUN_UPLOAD_VALIDATION_FAILED
**Reference:** inputs.raw_bytes, inputs.Content-Type

#### 6.2.2.16 Delete resequencing fails at runtime

*Given* a DELETE /documents/{document_id} request for an existing document
*When* automatic resequencing of remaining documents fails during execution
*Then* the system must return an error with code RUN_DELETE_RESEQUENCE_FAILED.
**Error Mode:** RUN_DELETE_RESEQUENCE_FAILED
**Reference:** inputs.document_id, outputs.list[].order_number

#### 6.2.2.17 Metadata persistence failure at runtime

*Given* a POST /documents or PATCH /documents/{document_id} request with valid inputs
*When* persistence of the metadata record fails during execution
*Then* the system must return an error with code RUN_METADATA_PERSISTENCE_FAILED.
**Error Mode:** RUN_METADATA_PERSISTENCE_FAILED
**Reference:** inputs.title, inputs.order_number, outputs.document.*

#### 6.2.2.18 Blob storage failure at runtime

*Given* a PUT /documents/{document_id}/content request with valid inputs
*When* blob storage cannot write or read the file during execution
*Then* the system must return an error with code RUN_BLOB_STORAGE_FAILURE.
**Error Mode:** RUN_BLOB_STORAGE_FAILURE
**Reference:** inputs.raw_bytes, outputs.blob_metadata, outputs.content_file

#### 6.2.2.19 Document ETag mismatch

*Given* a PUT /documents/{document_id}/content request with `If-Match` present
*When* the supplied `If-Match` does not equal the current document ETag
*Then* the system must return an error with code RUN_DOCUMENT_ETAG_MISMATCH.
**Error Mode:** RUN_DOCUMENT_ETAG_MISMATCH
**Reference:** inputs.If-Match, outputs.document.version

#### 6.2.2.20 List ETag mismatch

*Given* a PUT /documents/order request with `If-Match` present
*When* the supplied `If-Match` does not equal the current list ETag
*Then* the system must return an error with code RUN_LIST_ETAG_MISMATCH.
**Error Mode:** RUN_LIST_ETAG_MISMATCH
**Reference:** inputs.If-Match, outputs.list_etag

#### 6.2.2.21 State retention failure

*Given* a request that reads stored document metadata
*When* the system cannot read consistent metadata state
*Then* the system must return an error with code RUN_STATE_RETENTION_FAILURE.
**Error Mode:** RUN_STATE_RETENTION_FAILURE
**Reference:** outputs.document.title, outputs.document.order_number, outputs.document.version

#### 6.2.2.22 Optional stitched access failure

*Given* another epic requests documents for stitched output in strict order
*When* this epic cannot supply documents in order
*Then* the system must return an error with code RUN_OPTIONAL_STITCH_ACCESS_FAILURE.
**Error Mode:** RUN_OPTIONAL_STITCH_ACCESS_FAILURE
**Reference:** outputs.list, outputs.content_file

#### 6.2.2.23 Version not incremented after content update

*Given* a successful PUT /documents/{document_id}/content request
*When* the response is produced
*Then* the system must return an error with code POST_VERSION_NOT_INCREMENTED if `outputs.content_result.version` is not exactly previous version plus one.
**Error Mode:** POST_VERSION_NOT_INCREMENTED
**Reference:** outputs.content_result.version

#### 6.2.2.24 Blob metadata incomplete after content update

*Given* a successful PUT /documents/{document_id}/content request
*When* the persisted projection is examined
*Then* the system must return an error with code POST_BLOB_METADATA_INCOMPLETE if any of `outputs.blob_metadata.file_sha256`, `filename`, `mime`, `byte_size`, or `storage_url` is missing.
**Error Mode:** POST_BLOB_METADATA_INCOMPLETE
**Reference:** outputs.blob_metadata.*

#### 6.2.2.25 List not sorted by order_number

*Given* a successful GET /documents/names or PUT /documents/order
*When* the response body is examined
*Then* the system must return an error with code POST_LIST_NOT_SORTED if `outputs.list` is not sorted by `order_number` ascending.
**Error Mode:** POST_LIST_NOT_SORTED
**Reference:** outputs.list, outputs.list[].order_number

#### 6.2.2.26 Order sequence not contiguous

*Given* a successful DELETE /documents/{document_id} or PUT /documents/order
*When* the resulting ordering is examined
*Then* the system must return an error with code POST_ORDER_NOT_CONTIGUOUS if remaining `outputs.list[].order_number` values are not a strict 1..N sequence without gaps.
**Error Mode:** POST_ORDER_NOT_CONTIGUOUS
**Reference:** outputs.list[].order_number

#### 6.2.2.27 List ETag absent on names listing

*Given* a successful GET /documents/names
*When* the response headers/body are examined
*Then* the system must return an error with code POST_LIST_ETAG_ABSENT if `outputs.list_etag` is not present.
**Error Mode:** POST_LIST_ETAG_ABSENT
**Reference:** outputs.list_etag

#### 6.2.2.28 Downloaded content MIME incorrect

*Given* a successful GET /documents/{document_id}/content
*When* the response is streamed
*Then* the system must return an error with code POST_CONTENT_MIME_INCORRECT if the content is not a DOCX with the correct MIME type.
**Error Mode:** POST_CONTENT_MIME_INCORRECT
**Reference:** outputs.content_file

#### 6.2.2.29 Persisted checksum mismatch

*Given* a successful PUT /documents/{document_id}/content
*When* the persisted checksum projection is examined
*Then* the system must return an error with code POST_CONTENT_CHECKSUM_MISMATCH if `outputs.blob_metadata.file_sha256` does not match the content’s checksum.
**Error Mode:** POST_CONTENT_CHECKSUM_MISMATCH
**Reference:** outputs.blob_metadata.file_sha256, outputs.content_file

### 6.3 Happy Path Behavioural Acceptance Criteria

#### 6.3.1.1 Validation triggers content persistence

*Given* a user uploads a DOCX file
*When* synchronous validation completes successfully
*Then* the system must initiate the persistence of the document metadata and content.
**Reference:** E1

#### 6.3.1.2 Delete triggers resequencing

*Given* a user deletes a document
*When* the delete operation completes successfully
*Then* the system must trigger resequencing of all remaining documents.
**Reference:** E2

#### 6.3.1.3 Reorder triggers resequencing

*Given* a user submits a valid reorder request with PUT /documents/order
*When* the request is validated
*Then* the system must initiate resequencing of the documents according to the submitted order.
**Reference:** E3

#### 6.3.1.4 Metadata update maintains state

*Given* a document metadata update is accepted
*When* the update succeeds
*Then* the system must transition to a state where the new metadata is retained and becomes the current state.
**Reference:** S1

#### 6.3.1.5 Resequencing triggers list ETag update

*Given* resequencing of documents completes successfully
*When* the new order has been applied
*Then* the system must trigger an update of the list’s concurrency tag (ETag).
**Reference:** E2, E3

### 6.3.2 Sad Path Behavioural Acceptance Criteria

#### 6.3.2.1

**Title:** Upload validation failure halts persistence
**Criterion:** Given a document upload begins validation, when the DOCX structure is invalid and triggers validation failure, then halt the upload validation step and stop propagation to document persistence.
**Error Mode:** RUN_UPLOAD_VALIDATION_FAILED
**Reference:** inputs.raw_bytes (step: upload validation)

#### 6.3.2.2

**Title:** Delete resequencing failure halts order update
**Criterion:** Given a document delete request is in progress, when resequencing fails at runtime, then halt the resequencing step and stop propagation to list state update.
**Error Mode:** RUN_DELETE_RESEQUENCE_FAILED
**Reference:** inputs.document_id (step: delete resequencing)

#### 6.3.2.3

**Title:** Invalid reorder sequence halts resequencing
**Criterion:** Given a reorder request is being processed, when the sequence is invalid at runtime, then halt the reorder validation step and stop propagation to resequencing of documents.
**Error Mode:** RUN_REORDER_SEQUENCE_INVALID
**Reference:** inputs.items[].order_number (step: reorder validation)

#### 6.3.2.4

**Title:** Metadata persistence failure halts update flow
**Criterion:** Given a document create or metadata update request, when metadata persistence fails at runtime, then halt the metadata persistence step and stop propagation to downstream confirmation.
**Error Mode:** RUN_METADATA_PERSISTENCE_FAILED
**Reference:** outputs.document (step: metadata persistence)

#### 6.3.2.5

**Title:** Blob storage failure halts content update
**Criterion:** Given a document content update request, when blob storage fails at runtime, then halt the blob persistence step and stop propagation to version increment.
**Error Mode:** RUN_BLOB_STORAGE_FAILURE
**Reference:** outputs.blob_metadata (step: blob persistence)

#### 6.3.2.6

**Title:** List ETag mismatch prevents resequencing
**Criterion:** Given a reorder request with `If-Match`, when the list ETag mismatches at runtime, then halt the ETag validation step and stop propagation to resequencing.
**Error Mode:** RUN_LIST_ETAG_MISMATCH
**Reference:** inputs.If-Match, outputs.list_etag (step: reorder concurrency check)

#### 6.3.2.7

**Title:** Document ETag mismatch prevents content update
**Criterion:** Given a content update request with `If-Match`, when the document ETag mismatches at runtime, then halt the ETag validation step and stop propagation to content persistence.
**Error Mode:** RUN_DOCUMENT_ETAG_MISMATCH
**Reference:** inputs.If-Match, outputs.document.version (step: content concurrency check)

#### 6.3.2.8

**Title:** State retention failure halts metadata access
**Criterion:** Given a request to read document metadata, when state retention fails at runtime, then halt the metadata read step and stop propagation to downstream retrieval.
**Error Mode:** RUN_STATE_RETENTION_FAILURE
**Reference:** outputs.document (step: state retrieval)

#### 6.3.2.9

**Title:** Stitched access failure halts external supply
**Criterion:** Given an external stitched output request, when document access fails at runtime, then halt the stitched access step and stop propagation to downstream stitched response.
**Error Mode:** RUN_OPTIONAL_STITCH_ACCESS_FAILURE
**Reference:** outputs.list, outputs.content_file (step: stitched access)

### 6.3.2 Sad Path Behavioural Acceptance Criteria – Environmental Errors

#### 6.3.2.10

**Title:** Database unavailable halts persistence flow
**Criterion:** Given a document create or update request, when the database service is unavailable, then halt document persistence and stop propagation to resequencing and list update.
**Error Mode:** ENV_DB_UNAVAILABLE
**Reference:** dependency: database, Steps: STEP-1, STEP-2

#### 6.3.2.11

**Title:** Database permission denied halts persistence flow
**Criterion:** Given a document create or update request, when the database rejects credentials, then halt document persistence and stop propagation to resequencing and list update.
**Error Mode:** ENV_DB_PERMISSION_DENIED
**Reference:** dependency: database, Steps: STEP-1, STEP-2

#### 6.3.2.12

**Title:** Object storage unavailable halts content update
**Criterion:** Given a document content upload, when object storage is unreachable, then halt blob persistence and stop propagation to version increment.
**Error Mode:** ENV_OBJECT_STORAGE_UNAVAILABLE
**Reference:** dependency: object storage, Steps: STEP-1, STEP-2

#### 6.3.2.13

**Title:** Object storage permission denied halts content update
**Criterion:** Given a document content upload, when object storage denies access, then halt blob persistence and stop propagation to version increment.
**Error Mode:** ENV_OBJECT_STORAGE_PERMISSION_DENIED
**Reference:** dependency: object storage, Steps: STEP-1, STEP-2

#### 6.3.2.14

**Title:** Network unreachable prevents storage access
**Criterion:** Given a document content upload, when network connectivity to object storage is unreachable, then halt blob persistence and stop propagation to version increment.
**Error Mode:** ENV_NETWORK_UNREACHABLE_STORAGE
**Reference:** dependency: network→object storage, Steps: STEP-1, STEP-2

#### 6.3.2.15

**Title:** DNS resolution failure prevents storage access
**Criterion:** Given a document content upload, when object storage DNS resolution fails, then halt blob persistence and stop propagation to version increment.
**Error Mode:** ENV_DNS_RESOLUTION_FAILED_STORAGE
**Reference:** dependency: DNS→object storage, Steps: STEP-1, STEP-2

#### 6.3.2.16

**Title:** TLS handshake failure prevents storage access
**Criterion:** Given a document content upload, when TLS handshake with object storage fails, then halt blob persistence and stop propagation to version increment.
**Error Mode:** ENV_TLS_HANDSHAKE_FAILED_STORAGE
**Reference:** dependency: TLS→object storage, Steps: STEP-1, STEP-2

#### 6.3.2.17

**Title:** Missing database credentials halt persistence flow
**Criterion:** Given a document create or update request, when database credentials are missing from configuration, then halt document persistence and stop propagation to resequencing and list update.
**Error Mode:** ENV_CONFIG_MISSING_DB_CREDENTIALS
**Reference:** dependency: configuration→database, Steps: STEP-1, STEP-2

#### 6.3.2.18

**Title:** Missing storage credentials halt content update
**Criterion:** Given a document content upload, when object storage credentials are missing from configuration, then halt blob persistence and stop propagation to version increment.
**Error Mode:** ENV_CONFIG_MISSING_STORAGE_CREDENTIALS
**Reference:** dependency: configuration→object storage, Steps: STEP-1, STEP-2

#### 6.3.2.19

**Title:** Temporary filesystem unavailable halts upload flow
**Criterion:** Given a document content upload, when the temporary directory is unavailable, then halt upload streaming and stop propagation to blob persistence.
**Error Mode:** ENV_FILESYSTEM_TEMP_UNAVAILABLE
**Reference:** dependency: filesystem temp, Steps: STEP-1, STEP-2

#### 6.3.2.20

**Title:** Disk space exhaustion halts upload flow
**Criterion:** Given a document content upload, when local disk space is exhausted, then halt upload streaming and stop propagation to blob persistence.
**Error Mode:** ENV_DISK_SPACE_EXHAUSTED
**Reference:** dependency: filesystem disk, Steps: STEP-1, STEP-2

#### 6.3.2.21

**Title:** Storage rate limit exceeded blocks finalisation
**Criterion:** Given a document content upload, when object storage rate limits are exceeded, then halt blob persistence and block finalisation of the update.
**Error Mode:** ENV_RATE_LIMIT_EXCEEDED_STORAGE
**Reference:** dependency: object storage, Steps: STEP-1, STEP-2

#### 6.3.2.22

**Title:** Storage quota exceeded halts persistence flow
**Criterion:** Given a document content upload, when object storage quota is exceeded, then halt blob persistence and stop propagation to version increment.
**Error Mode:** ENV_QUOTA_EXCEEDED_STORAGE
**Reference:** dependency: object storage, Steps: STEP-1, STEP-2

7.1.1 Document schema declares required fields
Purpose: Verify the document schema defines the structural fields mandated by the architectural AC.
Test Data: project root; file path: schemas/Document.schema.json
Mocking: No mocking or stubbing. This is a static schema presence/shape check against the real file; mocking would invalidate the inspection.
Assertions:

* File schemas/Document.schema.json exists.
* JSON Schema contains properties: id, title, order_number, version, created_at, updated_at.
* Property types are declared for title (string), order_number (integer), version (integer).
  AC-Ref: 6.1.1

7.1.2 DocumentBlob schema declares required fields
Purpose: Verify the blob schema defines the structural fields mandated by the architectural AC.
Test Data: project root; file path: schemas/DocumentBlob.schema.json
Mocking: No mocking or stubbing. This is a static schema presence/shape check against the real file; mocking would invalidate the inspection.
Assertions:

* File schemas/DocumentBlob.schema.json exists.
* JSON Schema contains properties: file_sha256, filename, mime, byte_size, storage_url.
* Property types are declared for file_sha256 (string), filename (string), mime (string), byte_size (integer), storage_url (string).
  AC-Ref: 6.1.3

7.1.3 No diffs/revision schema present
Purpose: Ensure the codebase does not introduce a revision/diff schema contrary to exclusions.
Test Data: project root; directory: schemas/
Mocking: No mocking or stubbing. This is a real filesystem scan; mocking would undermine the guarantee.
Assertions:

* No file named schemas/DocumentRevision.schema.json exists.
* No file name in schemas/ matches the regex ^Document(Diff|Delta|Change|Revision).schema.json$.
  AC-Ref: 6.1.5

7.1.4 Output schema separation – document response schema present
Purpose: Ensure a dedicated response schema exists for single-document responses.
Test Data: project root; file path: schemas/DocumentResponse.schema.json
Mocking: No mocking or stubbing. Static presence/shape inspection.
Assertions:

* File schemas/DocumentResponse.schema.json exists.
* JSON Schema defines a top-level property document.
* The document object declares properties: document_id, title, order_number, version.
  AC-Ref: 6.1.12

7.1.5 Output schema separation – list response schema present
Purpose: Ensure a dedicated response schema exists for list responses and list ETag.
Test Data: project root; file path: schemas/DocumentListResponse.schema.json
Mocking: No mocking or stubbing. Static presence/shape inspection.
Assertions:

* File schemas/DocumentListResponse.schema.json exists.
* JSON Schema defines top-level properties list and list_etag.
* list is an array whose items declare properties: document_id, title, order_number, version.
  AC-Ref: 6.1.12

7.1.6 Output schema separation – content update result schema present
Purpose: Ensure a dedicated response schema exists for content update results.
Test Data: project root; file path: schemas/ContentUpdateResult.schema.json
Mocking: No mocking or stubbing. Static presence/shape inspection.
Assertions:

* File schemas/ContentUpdateResult.schema.json exists.
* JSON Schema defines a top-level property content_result with properties document_id and version.
  AC-Ref: 6.1.12

7.1.7 Output schema separation – blob metadata projection schema present
Purpose: Ensure a dedicated projection schema exists for persisted blob metadata.
Test Data: project root; file path: schemas/BlobMetadataProjection.schema.json
Mocking: No mocking or stubbing. Static presence/shape inspection.
Assertions:

* File schemas/BlobMetadataProjection.schema.json exists.
* JSON Schema defines a top-level property blob_metadata with properties file_sha256, filename, mime, byte_size, storage_url.
  AC-Ref: 6.1.12

7.1.8 ETag support fields available in list response schema
Purpose: Ensure the architectural requirement for list ETag concurrency is reflected in the schema.
Test Data: project root; file path: schemas/DocumentListResponse.schema.json
Mocking: No mocking or stubbing. Static presence/shape inspection.
Assertions:

* JSON Schema includes a property list_etag of type string at the top level.
  AC-Ref: 6.1.8

7.1.9 Title field constraints are declared
Purpose: Ensure the architectural requirement that title is a non-empty UTF-8 string is reflected in the schema.
Test Data: project root; file path: schemas/Document.schema.json
Mocking: No mocking or stubbing. Static presence/shape inspection.
Assertions:

* Property title exists and is type string.
* Schema declares a non-empty constraint for title (e.g., minLength ≥ 1).
  AC-Ref: 6.1.13

7.1.10 Unique sequential ordering is represented at the contract layer
Purpose: Ensure the ordering contract is represented by type and presence in both single and list schemas (structural reflection of the architectural constraint).
Test Data: project root; file paths: schemas/Document.schema.json, schemas/DocumentListResponse.schema.json, schemas/DocumentResponse.schema.json
Mocking: No mocking or stubbing. Static presence/shape inspection.
Assertions:

* order_number exists and is type integer in schemas/Document.schema.json.
* order_number exists and is type integer in list items of schemas/DocumentListResponse.schema.json.
* order_number exists and is type integer in the document object of schemas/DocumentResponse.schema.json.
  AC-Ref: 6.1.2

7.1.11 Version field present in schemas that expose document state
Purpose: Ensure the architectural guarantee of versioned documents is surfaced in the response schemas.
Test Data: project root; file paths: schemas/Document.schema.json, schemas/DocumentResponse.schema.json, schemas/DocumentListResponse.schema.json, schemas/ContentUpdateResult.schema.json
Mocking: No mocking or stubbing. Static presence/shape inspection.
Assertions:

* version exists and is type integer in schemas/Document.schema.json.
* version exists and is type integer in the document object of schemas/DocumentResponse.schema.json.
* version exists and is type integer in list items of schemas/DocumentListResponse.schema.json.
* version exists and is type integer in content_result of schemas/ContentUpdateResult.schema.json.
  AC-Ref: 6.1.1, 6.1.12

7.1.12 Absence of PATCH order_number in response schemas
Purpose: Ensure order_number cannot be updated via the metadata update pathway by verifying schemas do not expose an order_number field for PATCH response-only modifications (structural signal aligning with the AC).
Test Data: project root; file path: schemas/DocumentResponse.schema.json
Mocking: No mocking or stubbing. Static presence/shape inspection.
Assertions:

* DocumentResponse.schema.json exposes order_number only as a read property; no PATCH-specific schema includes order_number as a writable property (if a PATCH request schema exists, it must not include order_number).
  AC-Ref: 6.1.14

7.1.13 Problem+json error media type is declared at contract level
Purpose: Ensure a central contract declaration exists for Problem+json error responses (architectural convention).
Test Data: project root; file path: schemas (or OpenAPI) where error response components are declared (e.g., problem+json component).
Mocking: No mocking or stubbing. Static presence/shape inspection.
Assertions:

* A reusable Problem+json component/schema exists and is referenced by API error responses for this epic’s endpoints (e.g., POST /documents, PUT /documents/{document_id}/content, PATCH /documents/{document_id}, DELETE /documents/{document_id}, GET /documents/names, PUT /documents/order).
  AC-Ref: 6.1.15

7.2.1.1 Create document with metadata
Title: POST /documents creates a document with initial version and ordering
Purpose: Verify a valid create request returns a single document payload with required fields and initial version = 1.
Test data:

* HTTP method/path: POST /documents
* Request body (JSON): {"title":"HR Policy – Leave","order_number":3}
* Expected response HTTP status: 201
* Expected response schema: schemas/DocumentResponse.schema.json
  Mocking: No external dependencies are mocked. The persistence layer is exercised against the real test database (or migration-backed ephemeral DB). Mocking would invalidate the structural contract being verified.
  Assertions:
* Response JSON validates against schemas/DocumentResponse.schema.json.
* Response body.document.document_id is a valid UUID v4 (e.g., matches regex ^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$).
* Response body.document.title == "HR Policy – Leave".
* Response body.document.order_number == 3.
* Response body.document.version == 1.
* Database row for returned document_id exists with title "HR Policy – Leave", order_number 3, version 1.
* State non-mutation: take snapshot of the full documents list before the POST, assert that only one new row is added and no existing row’s title/order_number/version changed (deep equality on all pre-existing rows).
* Schema positive control: the same response re-validates after a fresh parse from bytes.
* Schema negative control (local validator only, not API): mutate version to "1" (string) and assert schema validator rejects it.
  AC-Ref: 6.2.1.1
  EARS-Refs: U2, U4

7.2.1.2 Increment version on content update
Title: PUT /documents/{id}/content increments version exactly by one
Purpose: Verify content update increments version by exactly 1 and returns the new version.
Test data:

* Precondition: Create a document D with version 1. Record ETag "W/"doc-v1"" from GET metadata.
* HTTP method/path: PUT /documents/{D}/content
* Headers: Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document; Idempotency-Key: "idem-001"; If-Match: "W/"doc-v1""
* Body: Binary DOCX payload (sample.docx) of 12,345 bytes.
* Expected response HTTP status: 200
* Expected response schema: schemas/ContentUpdateResult.schema.json
  Mocking: Mock object storage at the boundary to accept a single write and return success; assert exactly one putObject call with byte_size 12345 and deterministic key derived from D. Internal versioning logic is not mocked.
  Assertions:
* Response JSON validates against schemas/ContentUpdateResult.schema.json.
* Response content_result.document_id == D.
* Response content_result.version == 2.
* Subsequent GET metadata shows version == 2.
* Idempotency check: repeat the same PUT with identical Idempotency-Key and body; response version remains 2 and storage mock records no additional writes.
* Schema positive control: response re-validates from raw JSON.
* Schema negative control (local validator): set version to 1 in a copied response and assert schema validator rejects it if constrained; otherwise assert explicit equality to 2 in contract checks.
  AC-Ref: 6.2.1.2
  EARS-Refs: E1

7.2.1.3 Persist blob metadata on content update
Title: Content update persists blob metadata projection fields
Purpose: Verify blob metadata fields are persisted and retrievable after a successful content upload.
Test data:

* Document D exists; If-Match ETag matches current version.
* PUT /documents/{D}/content with a DOCX body whose SHA-256 (precomputed) is "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08".
* Filename: "policy-v2.docx". MIME: application/vnd.openxmlformats-officedocument.wordprocessingml.document. Size: 18,001 bytes.
* Expected response HTTP status: 200
  Mocking: Object storage mocked at boundary to accept upload and return a concrete storage URL "s3://bucket/docs/D/latest". No internal logic mocked.
  Assertions:
* Persisted projection (via a GET projection endpoint or direct repository read) includes:

  * blob_metadata.file_sha256 == "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
  * blob_metadata.filename == "policy-v2.docx"
  * blob_metadata.mime == DOCX MIME
  * blob_metadata.byte_size == 18001
  * blob_metadata.storage_url == "s3://bucket/docs/D/latest"
* State non-mutation: aside from document.version increment (verified in 7.2.1.2), assert no other document metadata fields changed.
* Schema positive control: projection validates against schemas/BlobMetadataProjection.schema.json.
  AC-Ref: 6.2.1.3
  EARS-Refs: U6, E1

7.2.1.4 Patch updates title only
Title: PATCH /documents/{id} updates title and does not change order_number
Purpose: Verify title is updated and ordering remains unchanged on metadata patch.
Test data:

* Pre-state: Document D has title "HR Policy – Leave", order_number 3, version 2.
* HTTP method/path: PATCH /documents/{D}
* Body: {"title":"HR Policy – Annual Leave"}
* Expected response HTTP status: 200
* Expected response schema: schemas/DocumentResponse.schema.json
  Mocking: No external mocks. Real persistence used to ensure field-level update semantics.
  Assertions:
* Response validates against schemas/DocumentResponse.schema.json.
* Response document.title == "HR Policy – Annual Leave".
* Response document.order_number == 3 (unchanged).
* Response document.version == 2 (unchanged by PATCH).
* State non-mutation: snapshot document row before PATCH; after PATCH, deep-compare all fields except title to confirm unchanged.
  AC-Ref: 6.2.1.4
  EARS-Refs: S1

7.2.1.5 Delete resequences order
Title: DELETE /documents/{id} resequences remaining documents 1..N without gaps
Purpose: Verify deletion triggers atomic resequencing and the returned list reflects contiguous order.
Test data:

* Pre-state: Documents with (A: order 1), (B: order 2), (C: order 3), (D: order 4). Delete B.
* HTTP method/path: DELETE /documents/{B}
* Expected response HTTP status: 204
* Follow-up: GET /documents/names
  Mocking: No mocks; persistence and resequencing exercised against real DB.
  Assertions:
* GET list returns three items sorted by order_number asc: A→1, C→2, D→3.
* There is no gap or duplicate in order_number.
* State snapshot: capture full list before delete; after resequencing, assert the relative order of unaffected documents is preserved (A before C before D) and only order_number values changed to fill gaps.
* Schema positive control: list validates against schemas/DocumentListResponse.schema.json.
  AC-Ref: 6.2.1.5
  EARS-Refs: E2

7.2.1.6 Reorder resequences order
Title: PUT /documents/order applies new strict 1..N ordering and returns ordered list
Purpose: Verify server applies the submitted order atomically and returns the new ordered list.
Test data:

* Pre-state: Documents E(1), F(2), G(3).
* Submit: PUT /documents/order with body {"items":[{"document_id":G,"order_number":1},{"document_id":E,"order_number":2},{"document_id":F,"order_number":3}]} and header If-Match: "W/"list-v3"" (matching current list ETag).
* Expected response HTTP status: 200
* Expected response schema: schemas/DocumentListResponse.schema.json
  Mocking: No mocks for DB; this verifies atomic multi-row update.
  Assertions:
* Response list length == 3.
* Response list items are ordered: G→1, E→2, F→3.
* No duplicate order_number values.
* Confirm subsequent GET /documents/names returns identical ordering (deterministic and persisted).
* Schema positive control: response validates against schemas/DocumentListResponse.schema.json.
  AC-Ref: 6.2.1.6
  EARS-Refs: E3

7.2.1.7 Return list with ETag
Title: GET /documents/names returns ordered list and list ETag
Purpose: Verify names listing returns the ordered list and a concurrency ETag representing the list state.
Test data:

* HTTP method/path: GET /documents/names
* Expect sorting by order_number asc, title asc (as specified).
* Expected response HTTP status: 200
* Expected response schema: schemas/DocumentListResponse.schema.json
  Mocking: No mocks; response generated from real data.
  Assertions:
* Response validates against schemas/DocumentListResponse.schema.json.
* Response has non-empty string list_etag; capture it as E1.
* Verify list is sorted by order_number asc; tie-break by title asc for any equal order_number (should not occur, but sorting is deterministic).
* Determinism check: immediate repeat GET returns identical list and same list_etag E1 when no changes occur.
  AC-Ref: 6.2.1.7
  EARS-Refs: U5

7.2.1.8 Deterministic parsing outcome
Title: Identical DOCX bytes produce identical persisted metadata
Purpose: Verify deterministic outcome for identical inputs (same checksum and metadata).
Test data:

* Create document H (version 1). Put content V1: bytes of "docx-A" with SHA-256 "aaaaaaaa…(64 hex)". If-Match ETag for version 1.
* Create document I (version 1). Put content V1’: same exact bytes as "docx-A" (identical SHA-256).
* Expected response HTTP status: 200 for both PUTs.
  Mocking: Object storage mocked at boundary to accept both uploads; store by checksum key. Internal logic not mocked.
  Assertions:
* For H and I, persisted blob_metadata.file_sha256 equals the identical checksum "aaaaaaaa…".
* MIME for both equals DOCX MIME; byte_size equal across H and I.
* Storage mock shows both point to the same logical checksum key (if dedupe is enabled) or two keys with identical content (implementation-dependent); determinism assertion is on metadata equality, not storage implementation.
* No other metadata divergence for blob-level fields.
  AC-Ref: 6.2.1.8
  EARS-Refs: U7

7.2.1.9 Download DOCX content
Title: GET /documents/{id}/content streams the current DOCX with correct MIME
Purpose: Verify content download returns binary DOCX with correct MIME and bytes match the stored blob.
Test data:

* Pre-state: Document J has uploaded content with SHA-256 "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb".
* HTTP method/path: GET /documents/{J}/content
* Expected response HTTP status: 200
* Expected content type: application/vnd.openxmlformats-officedocument.wordprocessingml.document
  Mocking: No mocks. Download reads actual persisted bytes from storage used in tests (local or mocked by storage adapter used in 7.2.1.3).
  Assertions:
* Response header Content-Type equals DOCX MIME.
* Compute SHA-256 of response body; equals "bbbb…(64 hex)".
* Content is non-empty (> 0 bytes).
* If conditional GET is supported, sending If-None-Match with current ETag yields 304 (optional; only assert if documented for this endpoint).
  AC-Ref: 6.2.1.9
  EARS-Refs: U1

7.2.2.1 Title missing on create
Title: POST /documents without title returns PRE_TITLE_MISSING
Purpose: Verify create rejects missing title with the correct precondition error.
Test Data: HTTP POST /documents with JSON body: {"order_number": 3}.
Mocking: Mock the persistence repository so that no DB calls occur when validation fails (assert repository.create not called). No object storage mock needed. Mocking is at the API boundary to isolate input validation; internal validation logic is real.
Assertions:

* HTTP status = 400.
* Response body.type = "about:blank"; body.code = "PRE_TITLE_MISSING"; body.title = "Invalid request"; body.detail contains "title".
* Repository.create not called.
  AC-Ref: 6.2.2.1
  Error Mode: PRE_TITLE_MISSING

7.2.2.2 order_number missing on create
Title: POST /documents without order_number returns PRE_ORDER_NUMBER_MISSING
Purpose: Verify create rejects missing order_number.
Test Data: POST /documents with {"title": "HR Policy – Leave"}.
Mocking: Mock repository.create to ensure it is not invoked on validation failure; assert no calls.
Assertions:

* 400 with code "PRE_ORDER_NUMBER_MISSING".
* detail mentions "order_number".
* Repository.create not called.
  AC-Ref: 6.2.2.2
  Error Mode: PRE_ORDER_NUMBER_MISSING

7.2.2.3 order_number not positive
Title: POST /documents with order_number = 0 returns PRE_ORDER_NUMBER_NOT_POSITIVE
Purpose: Enforce positive ordering.
Test Data: POST /documents with {"title":"HR Policy – Leave","order_number":0}.
Mocking: Repository.create mocked; assert not called.
Assertions:

* 400, code "PRE_ORDER_NUMBER_NOT_POSITIVE".
* detail mentions "positive".
  AC-Ref: 6.2.2.3
  Error Mode: PRE_ORDER_NUMBER_NOT_POSITIVE

7.2.2.4 order_number duplicate on create
Title: POST /documents with duplicate order_number returns PRE_ORDER_NUMBER_DUPLICATE
Purpose: Reject duplicate order position.
Test Data: POST /documents with {"title":"Benefits","order_number":2}.
Mocking: Mock repository.exists_order_number(2) → True; mock repository.create not called.
Assertions:

* 409, code "PRE_ORDER_NUMBER_DUPLICATE".
* exists_order_number called with 2; create not called.
  AC-Ref: 6.2.2.4
  Error Mode: PRE_ORDER_NUMBER_DUPLICATE

7.2.2.5 document_id invalid format
Title: PUT /documents/abc/content with non-UUID id returns PRE_DOCUMENT_ID_INVALID
Purpose: Path param must be UUID.
Test Data: PUT /documents/abc/content with valid headers, small payload.
Mocking: Assert router validator runs; repository.get not called.
Assertions:

* 400, code "PRE_DOCUMENT_ID_INVALID".
* repository.get not called.
  AC-Ref: 6.2.2.5
  Error Mode: PRE_DOCUMENT_ID_INVALID

7.2.2.6 document not found
Title: PUT /documents/{id}/content with unknown id returns PRE_DOCUMENT_NOT_FOUND
Purpose: Unknown document rejected.
Test Data: PUT /documents/4f2a3b9d-9b2a-4d8b-932a-d1e9a1f1d001/content …
Mocking: repository.get(id) → None; object storage not touched.
Assertions:

* 404, code "PRE_DOCUMENT_NOT_FOUND".
* repository.get called once with id; storage client not called.
  AC-Ref: 6.2.2.6
  Error Mode: PRE_DOCUMENT_NOT_FOUND

7.2.2.7 Content-Type unsupported
Title: PUT /documents/{id}/content with text/plain returns PRE_CONTENT_TYPE_MISMATCH
Purpose: Enforce DOCX MIME.
Test Data: Headers Content-Type: text/plain; body "hello".
Mocking: Storage client mock asserts never called.
Assertions:

* 415, code "PRE_CONTENT_TYPE_MISMATCH".
* storage.put not called.
  AC-Ref: 6.2.2.7
  Error Mode: PRE_CONTENT_TYPE_MISMATCH

7.2.2.8 Raw bytes missing on content upload
Title: PUT /documents/{id}/content with empty body returns PRE_RAW_BYTES_MISSING
Purpose: Require binary body.
Test Data: Empty body (0 bytes); correct DOCX Content-Type.
Mocking: Storage client mock asserts not called.
Assertions:

* 400, code "PRE_RAW_BYTES_MISSING".
* storage.put not called.
  AC-Ref: 6.2.2.8
  Error Mode: PRE_RAW_BYTES_MISSING

7.2.2.9 Idempotency-Key missing
Title: PUT /documents/{id}/content without Idempotency-Key returns PRE_IDEMPOTENCY_KEY_MISSING
Purpose: Header required.
Test Data: Missing Idempotency-Key; otherwise valid request.
Mocking: Storage client mocked; assert not called.
Assertions:

* 400, code "PRE_IDEMPOTENCY_KEY_MISSING".
* storage.put not called.
  AC-Ref: 6.2.2.9
  Error Mode: PRE_IDEMPOTENCY_KEY_MISSING

7.2.2.10 If-Match missing for content update
Title: PUT /documents/{id}/content without If-Match returns PRE_IF_MATCH_MISSING_DOCUMENT
Purpose: Require ETag for doc updates.
Test Data: Headers lack If-Match; otherwise valid.
Mocking: Storage client mocked; not called.
Assertions:

* 428, code "PRE_IF_MATCH_MISSING_DOCUMENT".
* storage.put not called.
  AC-Ref: 6.2.2.10
  Error Mode: PRE_IF_MATCH_MISSING_DOCUMENT

7.2.2.11 If-Match missing for reorder
Title: PUT /documents/order without If-Match returns PRE_IF_MATCH_MISSING_LIST
Purpose: Require list ETag for reorder.
Test Data: PUT /documents/order with valid items, missing If-Match.
Mocking: Repository.bulk_resequence mocked; assert not called.
Assertions:

* 428, code "PRE_IF_MATCH_MISSING_LIST".
* bulk_resequence not called.
  AC-Ref: 6.2.2.11
  Error Mode: PRE_IF_MATCH_MISSING_LIST

7.2.2.12 Reorder items empty
Title: PUT /documents/order with items=[] returns PRE_REORDER_ITEMS_EMPTY
Purpose: Require at least one item.
Test Data: Body {"items": []}.
Mocking: bulk_resequence mocked; assert not called.
Assertions:

* 400, code "PRE_REORDER_ITEMS_EMPTY".
* bulk_resequence not called.
  AC-Ref: 6.2.2.12
  Error Mode: PRE_REORDER_ITEMS_EMPTY

7.2.2.13 Reorder sequence invalid (gaps/duplicates)
Title: PUT /documents/order gaps/dupes returns PRE_REORDER_SEQUENCE_INVALID
Purpose: Enforce strict 1..N sequence.
Test Data: {"items":[{"document_id":"A","order_number":1},{"document_id":"B","order_number":1}]}.
Mocking: bulk_resequence mocked; not called.
Assertions:

* 400, code "PRE_REORDER_SEQUENCE_INVALID".
* bulk_resequence not called.
  AC-Ref: 6.2.2.13
  Error Mode: PRE_REORDER_SEQUENCE_INVALID

7.2.2.14 Reorder contains unknown document_id
Title: PUT /documents/order with unknown id returns PRE_REORDER_UNKNOWN_DOCUMENT_ID
Purpose: Validate each item document_id.
Test Data: items include {"document_id":"00000000-0000-0000-0000-000000000000","order_number":2}.
Mocking: repository.exists_document(id) → False; bulk_resequence not called.
Assertions:

* 404, code "PRE_REORDER_UNKNOWN_DOCUMENT_ID".
* exists_document called; bulk_resequence not called.
  AC-Ref: 6.2.2.14
  Error Mode: PRE_REORDER_UNKNOWN_DOCUMENT_ID

7.2.2.15 Invalid DOCX upload rejected
Title: PUT /documents/{id}/content invalid DOCX returns RUN_UPLOAD_VALIDATION_FAILED
Purpose: Reject structurally invalid DOCX.
Test Data: Content-Type DOCX; body: bytes that fail DOCX open.
Mocking: Mock DOCX parser at boundary to raise InvalidDocxError; storage put not called.
Assertions:

* 422, code "RUN_UPLOAD_VALIDATION_FAILED".
* Parser called once; storage.put not called.
  AC-Ref: 6.2.2.15
  Error Mode: RUN_UPLOAD_VALIDATION_FAILED

7.2.2.16 Delete resequencing fails at runtime
Title: DELETE resequencing failure returns RUN_DELETE_RESEQUENCE_FAILED
Purpose: Propagate resequencing runtime failure.
Test Data: DELETE /documents/{B}.
Mocking: repository.delete(B) → OK; repository.resequence() raises SequencingError("conflict").
Assertions:

* 500, code "RUN_DELETE_RESEQUENCE_FAILED".
* delete called before resequence; resequence called once.
  AC-Ref: 6.2.2.16
  Error Mode: RUN_DELETE_RESEQUENCE_FAILED

7.2.2.17 Metadata persistence failure at runtime
Title: POST /documents persistence error returns RUN_METADATA_PERSISTENCE_FAILED
Purpose: Propagate DB write failure.
Test Data: POST /documents {"title":"X","order_number":5}.
Mocking: repository.create raises DBWriteError("timeout").
Assertions:

* 503, code "RUN_METADATA_PERSISTENCE_FAILED".
* repository.create called once with title "X", order_number 5.
  AC-Ref: 6.2.2.17
  Error Mode: RUN_METADATA_PERSISTENCE_FAILED

7.2.2.18 Blob storage failure at runtime
Title: PUT content storage error returns RUN_BLOB_STORAGE_FAILURE
Purpose: Surface storage failures.
Test Data: Valid PUT request.
Mocking: storage.put raises StorageError("write failed").
Assertions:

* 503, code "RUN_BLOB_STORAGE_FAILURE".
* storage.put called once with byte_size matching request.
  AC-Ref: 6.2.2.18
  Error Mode: RUN_BLOB_STORAGE_FAILURE

7.2.2.19 Document ETag mismatch
Title: PUT content with stale ETag returns RUN_DOCUMENT_ETAG_MISMATCH
Purpose: Enforce optimistic concurrency.
Test Data: If-Match: W/"doc-v1" while current is W/"doc-v2".
Mocking: repository.get_etag(id) → W/"doc-v2"; storage not called.
Assertions:

* 412, code "RUN_DOCUMENT_ETAG_MISMATCH".
* storage.put not called.
  AC-Ref: 6.2.2.19
  Error Mode: RUN_DOCUMENT_ETAG_MISMATCH

7.2.2.20 List ETag mismatch
Title: PUT order with stale list etag returns RUN_LIST_ETAG_MISMATCH
Purpose: Enforce list concurrency.
Test Data: If-Match: W/"list-v3" while current is W/"list-v4".
Mocking: repository.get_list_etag() → W/"list-v4"; bulk_resequence not called.
Assertions:

* 412, code "RUN_LIST_ETAG_MISMATCH".
* bulk_resequence not called.
  AC-Ref: 6.2.2.20
  Error Mode: RUN_LIST_ETAG_MISMATCH

7.2.2.21 State retention failure
Title: GET document metadata fails with RUN_STATE_RETENTION_FAILURE
Purpose: Surface state read errors.
Test Data: GET /documents/{id}.
Mocking: repository.read(id) raises StateCorruptionError("checksum mismatch").
Assertions:

* 500, code "RUN_STATE_RETENTION_FAILURE".
* repository.read called once.
  AC-Ref: 6.2.2.21
  Error Mode: RUN_STATE_RETENTION_FAILURE

7.2.2.22 Optional stitched access failure
Title: Stitched access failure returns RUN_OPTIONAL_STITCH_ACCESS_FAILURE
Purpose: If another epic requests ordered docs and access fails, propagate failure.
Test Data: External call to export/compose endpoint that asks this epic for ordered docs.
Mocking: gateway.get_documents_ordered raises AccessError("denied").
Assertions:

* 502, code "RUN_OPTIONAL_STITCH_ACCESS_FAILURE".
* gateway.get_documents_ordered called with expected parameters.
  AC-Ref: 6.2.2.22
  Error Mode: RUN_OPTIONAL_STITCH_ACCESS_FAILURE

7.2.2.23 Version not incremented after content update
Title: PUT content completes but version not incremented returns POST_VERSION_NOT_INCREMENTED
Purpose: Enforce version bump invariant.
Test Data: Start version 2; PUT content with matching If-Match W/"doc-v2".
Mocking: repository.commit returns success but repository.read_version returns 2 (unchanged) due to bug injected in mock.
Assertions:

* 500, code "POST_VERSION_NOT_INCREMENTED".
* read_version called after commit and equals previous.
  AC-Ref: 6.2.2.23
  Error Mode: POST_VERSION_NOT_INCREMENTED

7.2.2.24 Blob metadata incomplete after content update
Title: PUT content completes but metadata incomplete returns POST_BLOB_METADATA_INCOMPLETE
Purpose: Enforce metadata completeness.
Test Data: PUT content valid.
Mocking: repository.save_blob_metadata omits filename (returns object missing key).
Assertions:

* 500, code "POST_BLOB_METADATA_INCOMPLETE".
* save_blob_metadata called; response validator detects missing key.
  AC-Ref: 6.2.2.24
  Error Mode: POST_BLOB_METADATA_INCOMPLETE

7.2.2.25 List not sorted by order_number
Title: GET /documents/names returns unsorted list triggers POST_LIST_NOT_SORTED
Purpose: Enforce sorted output.
Test Data: GET /documents/names.
Mocking: repository.list_documents returns items in [order_number: 2,1]; do not mutate data to sorted in the mock to simulate bug.
Assertions:

* 500, code "POST_LIST_NOT_SORTED".
* Assert returned list order is 2 then 1 (unsorted) to prove detection.
  AC-Ref: 6.2.2.25
  Error Mode: POST_LIST_NOT_SORTED

7.2.2.26 Order sequence not contiguous
Title: DELETE resequencing leaves gap triggers POST_ORDER_NOT_CONTIGUOUS
Purpose: Enforce 1..N invariant after delete/reorder.
Test Data: After deleting B in set {A1,B2,C3}, backend returns {A1,C3}.
Mocking: repository.resequence returns {A1,C3} instead of {A1,C2}.
Assertions:

* 500, code "POST_ORDER_NOT_CONTIGUOUS".
* Verify gap present (no 2).
  AC-Ref: 6.2.2.26
  Error Mode: POST_ORDER_NOT_CONTIGUOUS

7.2.2.27 List ETag absent on names listing
Title: GET /documents/names missing list_etag triggers POST_LIST_ETAG_ABSENT
Purpose: Require concurrency token.
Test Data: GET /documents/names.
Mocking: controller or serializer mock omits list_etag field from response envelope.
Assertions:

* 500, code "POST_LIST_ETAG_ABSENT".
* Response JSON has no list_etag property.
  AC-Ref: 6.2.2.27
  Error Mode: POST_LIST_ETAG_ABSENT

7.2.2.28 Downloaded content MIME incorrect
Title: GET /documents/{id}/content returns wrong MIME triggers POST_CONTENT_MIME_INCORRECT
Purpose: Enforce DOCX MIME on download.
Test Data: GET /documents/{id}/content.
Mocking: storage.get returns bytes but controller sets Content-Type: application/octet-stream (forced via header mock).
Assertions:

* 500, code "POST_CONTENT_MIME_INCORRECT".
* Response header Content-Type == application/octet-stream.
  AC-Ref: 6.2.2.28
  Error Mode: POST_CONTENT_MIME_INCORRECT

7.2.2.29 Persisted checksum mismatch
Title: PUT content where stored checksum differs triggers POST_CONTENT_CHECKSUM_MISMATCH
Purpose: Enforce checksum integrity invariant.
Test Data: PUT content whose SHA-256 is "cccc…".
Mocking: storage.put returns success; repository.save_blob_metadata stores file_sha256 "dddd…".
Assertions:

* 500, code "POST_CONTENT_CHECKSUM_MISMATCH".
* Computed checksum "cccc…" ≠ persisted "dddd…".
  AC-Ref: 6.2.2.29
  Error Mode: POST_CONTENT_CHECKSUM_MISMATCH

7.3.1.1 Validation success triggers content persistence
Title: Upload validation completion invokes content persistence
Purpose: Verify that, after synchronous DOCX validation succeeds, the system invokes the content persistence step.
Test Data: PUT /documents/{D}/content with Content-Type=DOCX, Idempotency-Key=idem-001, If-Match=W/"doc-v1", body=valid DOCX bytes.
Mocking: Mock the external storage adapter to return a dummy success sufficient for sequencing (e.g., putObject → OK); mock returns do not include any artefact checks. No internal validation logic is mocked.
Assertions: Assert invoked once immediately after validation completes, and not before.
AC-Ref: 6.3.1.1

7.3.1.2 Delete completion triggers resequencing
Title: Successful delete invokes resequencing of remaining documents
Purpose: Verify that, after a document delete completes, the resequencing step is invoked.
Test Data: DELETE /documents/{B} for an existing document.
Mocking: Mock the repository.delete to return a dummy success; mock the resequencer to be callable and return a dummy success to allow flow.
Assertions: Assert invoked once immediately after delete completes, and not before.
AC-Ref: 6.3.1.2

7.3.1.3 Reorder validation triggers resequencing
Title: Valid reorder request invokes resequencing
Purpose: Verify that, after a valid PUT /documents/order request is validated, the resequencing step is invoked.
Test Data: PUT /documents/order with If-Match=W/"list-v3", body items=[(G,1),(E,2),(F,3)] valid and contiguous.
Mocking: Mock the list-order validator to return a dummy success; mock the resequencer to be callable and return a dummy success to allow flow.
Assertions: Assert invoked once immediately after reorder validation completes, and not before.
AC-Ref: 6.3.1.3

7.3.1.4 Metadata update acceptance triggers state retention transition
Title: Accepted PATCH metadata update transitions to retained state
Purpose: Verify that, after a metadata update succeeds, the system transitions to the state where updated metadata is retained as current.
Test Data: PATCH /documents/{D} with body {"title":"HR Policy – Annual Leave"} valid.
Mocking: Mock the persistence commit boundary to return a dummy success; expose a state-retention notifier/committer that returns a dummy success to allow flow observation.
Assertions: Assert invoked once immediately after metadata update completes, and not before.
AC-Ref: 6.3.1.4

7.3.1.5 Resequencing completion triggers list ETag update
Title: Successful resequencing invokes list ETag updater
Purpose: Verify that, after resequencing completes, the list ETag update step is invoked.
Test Data: Any operation that completes resequencing (e.g., DELETE /documents/{B} or PUT /documents/order with a valid sequence).
Mocking: Mock the resequencer to return a dummy success; mock the ETag updater to be callable and return a dummy success to allow flow.
Assertions: Assert invoked once immediately after resequencing completes, and not before.
AC-Ref: 6.3.1.5

7.3.2.1 Upload validation failure halts persistence
Title: Validation error stops content persistence
Purpose: Verify that a validation failure prevents the content persistence step from being invoked.
Test Data: PUT /documents/{D}/content with Content-Type=application/vnd.openxmlformats-officedocument.wordprocessingml.document and a byte stream that is structurally invalid as a DOCX.
Mocking: Mock the DOCX validator/parser (upload validation boundary) to raise a validation exception immediately; leave internal orchestration real; mock the content persistence gateway to be observable (spyable) but not pre-programmed.
Assertions: Assert error handler is invoked once immediately when STEP-2 Inclusions (upload validation) raises, and not before. Assert content persistence is not invoked following the failure. Assert that error mode RUN_UPLOAD_VALIDATION_FAILED is observed.
AC-Ref: 6.3.2.1
Error Mode: RUN_UPLOAD_VALIDATION_FAILED

7.3.2.2 Delete resequencing failure halts order update
Title: Resequencing error after delete stops list state update
Purpose: Verify that a resequencing failure after delete prevents downstream list-state/ETag update.
Test Data: DELETE /documents/{B} where {B} exists.
Mocking: Mock repository.delete({B}) to succeed; mock resequencer to raise a runtime sequencing exception; mock list ETag updater as a spy-only dependency.
Assertions: Assert error handler is invoked once immediately when STEP-2 Inclusions (delete-triggered resequencing) raises, and not before. Assert list ETag update is not invoked following the failure. Assert that error mode RUN_DELETE_RESEQUENCE_FAILED is observed.
AC-Ref: 6.3.2.2
Error Mode: RUN_DELETE_RESEQUENCE_FAILED

7.3.2.3 Invalid reorder sequence halts resequencing
Title: Reorder validation error prevents resequencing
Purpose: Verify that an invalid reorder sequence prevents resequencing from starting.
Test Data: PUT /documents/order with items containing duplicate order_number values (e.g., two items set to 1) and a valid If-Match.
Mocking: Mock reorder validator to detect duplicates and raise; mock resequencer as a spy-only dependency.
Assertions: Assert error handler is invoked once immediately when STEP-2 Inclusions (reorder validation) raises, and not before. Assert resequencing is not invoked following the failure. Assert that error mode RUN_REORDER_SEQUENCE_INVALID is observed.
AC-Ref: 6.3.2.3
Error Mode: RUN_REORDER_SEQUENCE_INVALID

7.3.2.4 Metadata persistence failure halts update flow
Title: Metadata write error stops downstream confirmation
Purpose: Verify that a metadata persistence failure halts the flow and prevents any downstream confirmation/commit steps.
Test Data: POST /documents with valid {"title":"X","order_number":5} or PATCH /documents/{D} with valid {"title":"Y"}.
Mocking: Mock metadata repository.save to raise a write error; expose response/confirmation step as a spy-only dependency.
Assertions: Assert error handler is invoked once immediately when STEP-1 Purpose (metadata persistence) raises, and not before. Assert downstream confirmation step is not invoked following the failure. Assert that error mode RUN_METADATA_PERSISTENCE_FAILED is observed.
AC-Ref: 6.3.2.4
Error Mode: RUN_METADATA_PERSISTENCE_FAILED

7.3.2.5 Blob storage failure halts content update
Title: Blob write error prevents version increment path
Purpose: Verify that a blob storage failure prevents the version-increment path from being invoked.
Test Data: PUT /documents/{D}/content with valid headers/body.
Mocking: Mock blob storage adapter.put to raise a storage runtime error; version increment step instrumented as a spy-only dependency.
Assertions: Assert error handler is invoked once immediately when STEP-1 Purpose (blob persistence) raises, and not before. Assert version increment step is not invoked following the failure. Assert that error mode RUN_BLOB_STORAGE_FAILURE is observed.
AC-Ref: 6.3.2.5
Error Mode: RUN_BLOB_STORAGE_FAILURE

7.3.2.6 List ETag mismatch prevents resequencing
Title: Stale list ETag stops resequencing during reorder
Purpose: Verify that a list ETag mismatch prevents resequencing from starting.
Test Data: PUT /documents/order with valid items but stale If-Match list ETag.
Mocking: Mock list ETag checker to return mismatch; resequencer exposed as spy-only dependency.
Assertions: Assert error handler is invoked once immediately when STEP-2 Inclusions (reorder concurrency check) raises, and not before. Assert resequencing is not invoked following the failure. Assert that error mode RUN_LIST_ETAG_MISMATCH is observed.
AC-Ref: 6.3.2.6
Error Mode: RUN_LIST_ETAG_MISMATCH

7.3.2.7 Document ETag mismatch prevents content update
Title: Stale document ETag stops content persistence
Purpose: Verify that a document ETag mismatch prevents the content persistence path from being invoked.
Test Data: PUT /documents/{D}/content with stale If-Match document ETag.
Mocking: Mock document ETag checker to return mismatch; content persistence step exposed as spy-only dependency.
Assertions: Assert error handler is invoked once immediately when STEP-2 Inclusions (content concurrency check) raises, and not before. Assert content persistence is not invoked following the failure. Assert that error mode RUN_DOCUMENT_ETAG_MISMATCH is observed.
AC-Ref: 6.3.2.7
Error Mode: RUN_DOCUMENT_ETAG_MISMATCH

7.3.2.8 State retention failure halts metadata access
Title: Metadata state read error stops downstream retrieval
Purpose: Verify that a state retention failure during read prevents downstream retrieval/serialization.
Test Data: GET /documents/{D} (or any metadata read path) for an existing ID.
Mocking: Mock repository.read({D}) to raise a state corruption/read error; serializer/response builder exposed as a spy-only dependency.
Assertions: Assert error handler is invoked once immediately when STEP-4 Context (metadata read) raises, and not before. Assert downstream retrieval/serialization is not invoked following the failure. Assert that error mode RUN_STATE_RETENTION_FAILURE is observed.
AC-Ref: 6.3.2.8
Error Mode: RUN_STATE_RETENTION_FAILURE

7.3.2.9 Stitched access failure halts external supply
Title: Ordered document supply failure stops stitched response path
Purpose: Verify that a failure to access ordered documents for stitching prevents the stitched-response path from continuing.
Test Data: External orchestrator call that requests ordered documents for stitching.
Mocking: Mock the “supply ordered docs” gateway to raise an access failure; stitched response builder exposed as spy-only dependency.
Assertions: Assert error handler is invoked once immediately when STEP-4 Context (stitched access) raises, and not before. Assert stitched response builder is not invoked following the failure. Assert that error mode RUN_OPTIONAL_STITCH_ACCESS_FAILURE is observed.
AC-Ref: 6.3.2.9
Error Mode: RUN_OPTIONAL_STITCH_ACCESS_FAILURE

7.3.2.10
Title: Database unavailable halts persistence flow
Purpose: Verify that database unavailability halts STEP-1 and prevents STEP-2 actions.
Test Data: Trigger a document create (POST /documents) with valid body {"title":"A","order_number":1}.
Mocking: Mock the database connection at the repository boundary to raise a connection error on first use (e.g., connect() → raises “connection refused”). No other dependencies mocked. Assert repository methods are called/not called as per flow.
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to database unavailability, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_DB_UNAVAILABLE is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.10
Error Mode: ENV_DB_UNAVAILABLE

7.3.2.11
Title: Database permission denied halts persistence flow
Purpose: Verify that database permission issues halt STEP-1 and prevent STEP-2.
Test Data: Trigger a metadata update (PATCH /documents/{id}) with a valid title.
Mocking: Mock the database auth at the repository boundary so the first write attempt raises “permission denied.”
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to permission denial, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_DB_PERMISSION_DENIED is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.11
Error Mode: ENV_DB_PERMISSION_DENIED

7.3.2.12
Title: Object storage unavailable halts content update
Purpose: Verify that storage unavailability halts STEP-1 content persistence and prevents STEP-2 version flow.
Test Data: PUT /documents/{id}/content with valid headers and DOCX bytes.
Mocking: Mock the object storage adapter so putObject() raises “endpoint offline.”
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to storage unavailability, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_OBJECT_STORAGE_UNAVAILABLE is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.12
Error Mode: ENV_OBJECT_STORAGE_UNAVAILABLE

7.3.2.13
Title: Object storage permission denied halts content update
Purpose: Verify that storage permission errors halt STEP-1 and prevent STEP-2.
Test Data: PUT /documents/{id}/content with valid headers and DOCX bytes.
Mocking: Mock object storage adapter so putObject() raises “access denied.”
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to storage permission denial, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_OBJECT_STORAGE_PERMISSION_DENIED is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.13
Error Mode: ENV_OBJECT_STORAGE_PERMISSION_DENIED

7.3.2.14
Title: Network unreachable prevents storage access
Purpose: Verify that network failure to storage halts STEP-1 and prevents STEP-2.
Test Data: PUT /documents/{id}/content with valid headers and DOCX bytes.
Mocking: Mock network layer used by storage client to raise “network unreachable” on first call.
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to network unreachability, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_NETWORK_UNREACHABLE_STORAGE is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.14
Error Mode: ENV_NETWORK_UNREACHABLE_STORAGE

7.3.2.15
Title: DNS failure prevents storage access
Purpose: Verify that DNS resolution failure halts STEP-1 and prevents STEP-2.
Test Data: PUT /documents/{id}/content with valid headers and DOCX bytes.
Mocking: Mock DNS resolver used by storage client so hostname resolution raises “NXDOMAIN.”
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to DNS failure, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_DNS_RESOLUTION_FAILED_STORAGE is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.15
Error Mode: ENV_DNS_RESOLUTION_FAILED_STORAGE

7.3.2.16
Title: TLS handshake failure prevents storage access
Purpose: Verify that TLS handshake failure halts STEP-1 and prevents STEP-2.
Test Data: PUT /documents/{id}/content with valid headers and DOCX bytes.
Mocking: Mock TLS/session of storage client to raise “handshake failure / bad certificate.”
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to TLS handshake failure, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_TLS_HANDSHAKE_FAILED_STORAGE is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.16
Error Mode: ENV_TLS_HANDSHAKE_FAILED_STORAGE

7.3.2.17
Title: Missing DB credentials halt persistence flow
Purpose: Verify that absent DB credentials halt STEP-1 and prevent STEP-2.
Test Data: POST /documents with valid body; environment lacks required DB secret keys.
Mocking: Mock configuration loader to return None/empty for DB credentials; repository initialisation fails on first use.
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to missing DB credentials, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_CONFIG_MISSING_DB_CREDENTIALS is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.17
Error Mode: ENV_CONFIG_MISSING_DB_CREDENTIALS

7.3.2.18
Title: Missing storage credentials halt content update
Purpose: Verify that absent storage credentials halt STEP-1 and prevent STEP-2.
Test Data: PUT /documents/{id}/content with valid headers and DOCX bytes; environment lacks storage keys.
Mocking: Mock configuration loader to return None/empty for storage credentials; storage client raises on first call.
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to missing storage credentials, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_CONFIG_MISSING_STORAGE_CREDENTIALS is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.18
Error Mode: ENV_CONFIG_MISSING_STORAGE_CREDENTIALS

7.3.2.19
Title: Temporary filesystem unavailable halts upload flow
Purpose: Verify that missing temp directory halts STEP-1 streaming and prevents STEP-2.
Test Data: PUT /documents/{id}/content with valid headers and DOCX bytes.
Mocking: Mock temp-file creation to raise “no such file or directory” for the configured temp path.
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to temp filesystem unavailability, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_FILESYSTEM_TEMP_UNAVAILABLE is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.19
Error Mode: ENV_FILESYSTEM_TEMP_UNAVAILABLE

7.3.2.20
Title: Disk space exhaustion halts upload flow
Purpose: Verify that no free space halts STEP-1 streaming and prevents STEP-2.
Test Data: PUT /documents/{id}/content with valid headers and DOCX bytes.
Mocking: Mock filesystem write to raise “no space left on device” on first buffer write.
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to disk exhaustion, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_DISK_SPACE_EXHAUSTED is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.20
Error Mode: ENV_DISK_SPACE_EXHAUSTED

7.3.2.21
Title: Storage rate limit exceeded blocks finalisation
Purpose: Verify that storage throttling blocks STEP-2 finalisation after STEP-1 attempts upload.
Test Data: PUT /documents/{id}/content with valid headers and DOCX bytes, simulate burst conditions.
Mocking: Mock storage client to raise “rate limit exceeded / 429” on write attempt.
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to storage rate limiting, and not before. Assert STEP-2 finalisation is blocked and not invoked. Assert that error mode ENV_RATE_LIMIT_EXCEEDED_STORAGE is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.21
Error Mode: ENV_RATE_LIMIT_EXCEEDED_STORAGE

7.3.2.22
Title: Storage quota exceeded halts persistence flow
Purpose: Verify that storage quota exhaustion halts STEP-1 persistence and prevents STEP-2.
Test Data: PUT /documents/{id}/content with valid headers and DOCX bytes.
Mocking: Mock storage client to raise “quota exceeded” on write attempt.
Assertions: Assert error handler is invoked once immediately when STEP-1 raises due to storage quota exhaustion, and not before. Assert STEP-2 is not invoked following the failure. Assert that error mode ENV_QUOTA_EXCEEDED_STORAGE is observed. Assert no unintended side-effects. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.22
Error Mode: ENV_QUOTA_EXCEEDED_STORAGE
