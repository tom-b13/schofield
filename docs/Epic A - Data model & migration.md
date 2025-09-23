# Functional Outline

## 1) Objective

Establish a robust relational schema to store questionnaire definitions, answers, **mappings via `QuestionnaireQuestion.placeholder_code`**, and generated documents—while enforcing encryption in transit and supporting encryption at rest for sensitive data.

---

## 2) In-scope tables

**Company, QuestionnaireQuestion, AnswerOption, ResponseSet, Response, GeneratedDocument, FieldGroup, QuestionToFieldGroup, GroupValue.**  
*All field definitions, PK/FK, uniques, and indexes are described in `./docs/erd_spec.json`.*

Notes:

- `QuestionnaireQuestion` includes: `placeholder_code` (nullable), `mandatory` (bool, default `false`).  
- A **partial unique index** enforces that `placeholder_code` is unique when present.  
- `answer_kind` enum includes: `short_string`, `long_text`, `boolean`, `number`, **`enum_single`**.

---

## 3) Goals

- Migrations run from a clean state to produce all tables with PKs, FKs, uniques, and indexes as defined in the ERD spec.  
- Enumerations are present and correct, including **`enum_single`** for single-choice questions (backed by `AnswerOption`).  
- The application can insert and retrieve rows without schema errors.

**Constraints enforce integrity:**
- One response per question per submission: `UNIQUE(response_set_id, question_id)` on `Response`.  
- No duplicate placeholders: **partial unique** on `QuestionnaireQuestion(placeholder_code)` where not null.  
- Group invariants:  
  - `UNIQUE(response_set_id, field_group_id)` on `GroupValue`.  
  - `UNIQUE(question_id, field_group_id)` on `QuestionToFieldGroup`.  
- For `enum_single`:  
  - At least one `AnswerOption` exists for the question.  
  - `UNIQUE(question_id, value)` on `AnswerOption`.  
  - If a response uses `enum_single`, its `option_id` references an `AnswerOption` for the same question.

- ERD export (`./docs/erd_mermaid.md`, `./docs/erd_relationships.csv`) matches the schema.

---

## 4) Deliverables

- SQL migration files (types, tables, constraints, indexes), including base `001_init.sql`–`004_rollbacks.sql` and patch `005_add_enum_single.sql`.  
- Updated ERD spec JSON (`./docs/erd_spec.json`) as the normative definition.  
- Updated Mermaid ERD (`./docs/erd_mermaid.md`) and relationships CSV (`./docs/erd_relationships.csv`).  
- Migration rollback scripts.  
- Encryption documentation (TLS enforcement and at-rest guidance).

---

## 5) Non-functional requirements

- **Encryption at rest**: database files encrypted by default (managed DB recommended).  
- **Encryption in transit**: TLS enforced on all DB connections.  
- **Performance**: indexes chosen for primary read paths (question → response; `placeholder_code` lookups).  
- **Determinism & repeatability**: migrations are ordered and idempotent; rollbacks reverse cleanly.  
- **Traceability**: each placeholder code is uniquely attributable to a single source question.

# 1. Scope

## 1.1 Purpose  
Establish a secure and robust relational data model for storing questionnaire-related information, including answers and mappings to document placeholders, while ensuring sensitive data is protected.

## 1.2 Inclusions  
- Creation of relational tables for questionnaires, answers, response sets, generated documents, field groups, and group values.  
- Implementation of primary keys, foreign keys, **uniqueness (including a partial unique on `QuestionnaireQuestion.placeholder_code`)**, and indexes to enforce integrity and performance.  
- Encryption at rest and **TLS in transit**; support for column-level encryption flags for sensitive fields as specified in the ERD.  
- Provision of SQL migration files, rollback scripts, and updated ERD documentation (JSON, Mermaid, relationships CSV).  
- Ensuring application compatibility for data insertion and retrieval without schema errors.  
- **Direct placeholder resolution** via lookup of `placeholder_code` on questions (placeholders are parsed from the single handbook at merge time).

## 1.3 Exclusions  
- Changes to application logic unrelated to data handling.  
- Non-relational data storage solutions or structures.  
- Any development beyond the defined encryption standards and constraints.

## 1.4 Context  
This story establishes the database foundation for the questionnaire management system on PostgreSQL. Placeholders are **not** stored as separate template entities; instead, each question may carry a `placeholder_code` used to populate the handbook during merge. Where column-level encryption is enabled, keys may be managed by an external KMS; all database connections must use TLS.

## 2.2. EARS Functionality

### 2.2.1 Ubiquitous requirements

* **U1** The system will create a relational schema to persist questionnaire definitions.
* **U2** The system will create a relational schema to persist questionnaire answers.
* **U3** The system will create a relational schema to persist mappings by storing a `placeholder_code` on questions, with uniqueness enforced when present.
* **U4** The system will create a relational schema to persist response sets as submissions.
* **U5** The system will create a relational schema to persist generated documents.
* **U6** The system will create a relational schema to persist field groups that represent shared values across questions.
* **U7** The system will create a relational schema to persist group values per response set and link them to field groups and (optionally) source questions.
* **U8** The system will support column-level encryption flags for sensitive fields as specified in the ERD.

### 2.2.2 Event-driven requirements

* **E1** When migrations are executed, the system will create all required tables.
* **E2** When migrations are executed, the system will create all required constraints including primary keys, foreign keys, uniqueness, and indexes.
* **E3** When column-level encryption is enabled, the system will apply encryption to fields marked as sensitive during migration.
* **E4** When a database connection is initiated, the system will enforce TLS according to configuration.
* **E5** When a row is inserted, the system will validate the value type against the declared schema.
* **E6** When placeholder values are resolved, the system will perform a direct lookup by `placeholder_code` on questions (unique when present) to source the value.
* **E7** When placeholder values are resolved, the system will return the resolved values to the requesting component.
* **E8** When rollback migrations are executed, the system will drop objects created by the corresponding migration in reverse order.
* **E9** When migrations are executed, the system will create a unique constraint for `(response_set_id, field_group_id)` on `GroupValue` and for `(question_id, field_group_id)` on `QuestionToFieldGroup`.
* **E10** When migrations are executed, the system will create supporting indexes on foreign keys for `FieldGroup`, `QuestionToFieldGroup`, and `GroupValue`.

### 2.2.3 State-driven requirements

* **S1** While data is at rest, the system will ensure that database files are encrypted by default.
* **S2** While a TLS session is established, the system will encrypt data in transit for all database connections.
* **S3** While sensitive fields are accessed, the system will use keys managed by a KMS for decryption and access control (when enabled).
* **S4** While lookups are executed, the system will ensure deterministic results for repeated operations with the same inputs.

### 2.2.4 Optional-feature requirements

* **O1** Where new templates are introduced, the system will integrate them without requiring schema changes.
* **O2** Where new policies are introduced, the system will integrate them without requiring schema changes.

### 2.2.5 Unwanted-behaviour requirements

* **N1** If duplicate `placeholder_code` values are attempted (non-null), the system will prevent their persistence.
* **N2** If more than one response per question per submission is attempted, the system will reject the operation.
* **N3** If an unsupported data type is submitted, the system will reject the operation.
* **N4** If encryption keys are unavailable or invalid, the system will prevent access to encrypted data.
* **N5** If migrations are executed out of order, the system will abort with an explicit error.
* **N6** If a non-TLS connection is attempted when TLS is required, the system will reject the connection.

### 2.2.6 Step Index

* **STEP-1** Objective → U1, U2, U3, U4, U5, U6, U7, U8
* **STEP-2** In-scope tables → U1, U2, U3, U4, U5, U6, U7, U8
* **STEP-3** Goals → E1, E2, E3, E4, E5, E6, E7, E8, S1, S2, S3, S4
* **STEP-4** Deliverables → O1, O2
* **STEP-5** Non-functional requirements → N1, N2, N3, N4, N5, N6

| Field                                 | Description                                                                         | Type          | Schema / Reference                                   | Notes                                                                                                                              | Pre-Conditions                                                                                                                            | Origin   |
| ------------------------------------- | ----------------------------------------------------------------------------------- | ------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| docs/erd\_spec.json                   | Authoritative ERD spec (entities, fields, PK/FK, uniques, indexes, encrypted flags) | file json     | ./docs/erd\_spec.json                                | None                                                                                                                               | File exists and is readable; Content parses as valid JSON; Content conforms to the referenced schema                                      | acquired |
| docs/erd\_mermaid.md                  | Human-readable ERD diagram text used for parity checks                              | file markdown | ./docs/erd\_mermaid.md                               | None                                                                                                                               | File exists and is readable; Content is UTF-8 text; Diagram blocks are syntactically valid Mermaid                                        | acquired |
| docs/erd\_relationships.csv           | Machine-readable relationships list for cross-checks                                | file csv      | ./docs/erd\_relationships.csv                        | None                                                                                                                               | File exists and is readable; Content parses as CSV; Columns match expected headers                                                        | acquired |
| migrations/001\_init.sql              | Base migration that creates initial schema and enums                                | file sql      | #/components/schemas/MigrationFile                   | First migration in sequence                                                                                                        | File exists and is readable; File parses as valid SQL; Statements execute without error                                                   | acquired |
| migrations/002\_constraints.sql       | Migration that adds PK, FK, uniques, check constraints                              | file sql      | #/components/schemas/MigrationFile                   | Executed after init; **Includes partial unique on `QuestionnaireQuestion(placeholder_code)` WHERE `placeholder_code IS NOT NULL`** | File exists and is readable; File parses as valid SQL; Statements execute without error                                                   | acquired |
| migrations/003\_indexes.sql           | Migration that adds indexes for **lookups and performance**                         | file sql      | #/components/schemas/MigrationFile                   | Executed after constraints                                                                                                         | File exists and is readable; File parses as valid SQL; Statements execute without error                                                   | acquired |
| migrations/005\_add\_enum\_single.sql | Patch migration that adds `enum_single` to `answer_kind`                            | file sql      | #/components/schemas/MigrationFile                   | Executed after indexes                                                                                                             | File exists and is readable; File parses as valid SQL; Statements execute without error                                                   | acquired |
| migrations/004\_rollbacks.sql         | Rollback migration scripts for schema teardown                                      | file sql      | #/components/schemas/MigrationFile                   | Used for reversibility testing                                                                                                     | File exists and is readable; File parses as valid SQL; Statements execute without error                                                   | acquired |
| config/database.url                   | JDBC/DSN used by migration runner                                                   | string        | #/components/schemas/DatabaseUrl                     | Example: `postgresql://user@host:5432/db`                                                                                          | Field is required and must be provided; Value must be a valid DSN; Hostname must resolve                                                  | provided |
| config/database.ssl.required          | Toggle to enforce TLS for DB connections                                            | boolean       | #/components/schemas/Boolean                         | Default true                                                                                                                       | Field is required and must be provided; Value must be boolean; If true, TLS materials must be available                                   | provided |
| config/encryption.mode                | Encryption mode selection (e.g., tde, column)                                       | string        | #/components/schemas/EncryptionMode                  | Allowed: `tde`, `column`, `tde+column`                                                                                             | Field is required and must be provided; Value must be one of allowed set                                                                  | provided |
| config/kms.key\_alias                 | Logical KMS key identifier for column encryption                                    | string        | #/components/schemas/KmsKeyAlias                     | Example: `alias/contracts-app`                                                                                                     | Field is required when encryption.mode includes `column`; Alias must exist in KMS                                                         | provided |
| kms.get\_key(alias)                   | KMS returns handle/material for encryption                                          | object        | #/components/schemas/KmsKeyHandle                    | Provider: KMS service                                                                                                              | Call must complete without error; Return value must match the declared schema; Return value must be treated as immutable within this step | returned |
| secrets/db\_password                  | Secret Manager provides DB password                                                 | string        | #/components/schemas/SecretString                    | Provider: Secret Manager                                                                                                           | Call must complete without error; Return value must match the declared schema; Secret must not be logged                                  | returned |
| truststore/ca\_bundle.pem             | CA bundle for TLS verification                                                      | file pem      | #/components/schemas/CaBundle                        | May be OS bundle or project file                                                                                                   | File exists and is readable; Content parses as valid PEM; Certificate dates are within validity                                           | acquired |
| policy/encrypted\_fields              | List of columns marked “encrypted: true” in ERD                                     | list\[string] | ./docs/erd\_spec.json#/entities/*/fields/*/encrypted | Derived from ERD; used to assert column-level encryption                                                                           | File exists and is readable; JSON pointers resolve; Each field exists in the target entity                                                | acquired |
| config/migration.timeout\_seconds     | Execution timeout per migration                                                     | integer       | #/components/schemas/TimeoutSeconds                  | None                                                                                                                               | Field is required and must be provided; Value must be integer > 0                                                                         | provided |

| Field                                                      | Description                                            | Type            | Schema / Reference                                                                                                                   | Notes                                                  | Post-Conditions                                                                                                                                                                                                 |
| ---------------------------------------------------------- | ------------------------------------------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| outputs.entities\[]                                        | List of all entities (tables) present after migrations | array of object | #/components/schemas/Outputs/properties/entities/items                                                                               | Each item corresponds 1:1 to an ERD entity             | Array must include every entity defined in ERD; Order must be deterministic by entity name; Array must be immutable within this step                                                                            |
| outputs.entities\[].name                                   | Entity (table) name                                    | string          | #/components/schemas/Outputs/properties/entities/items/properties/name                                                               | Example: `Response`                                    | Value must be non-empty; Value must match ERD entity name exactly; Value is required                                                                                                                            |
| outputs.entities\[].fields\[]                              | Fields (columns) of the entity                         | array of object | #/components/schemas/Outputs/properties/entities/items/properties/fields/items                                                       | Each item represents one column                        | Array must include all and only fields defined in ERD for the entity; Order must be deterministic by field name; Array is required                                                                              |
| outputs.entities\[].fields\[].name                         | Field (column) name                                    | string          | #/components/schemas/Outputs/properties/entities/items/properties/fields/items/properties/name                                       | None                                                   | Value must match ERD field name exactly; Value must be unique within the entity; Value is required                                                                                                              |
| outputs.entities\[].fields\[].type                         | Field data type                                        | string          | #/components/schemas/Outputs/properties/entities/items/properties/fields/items/properties/type                                       | Examples: `uuid`, `text`, `jsonb`, enum names          | Value must match ERD type exactly; Value is required                                                                                                                                                            |
| outputs.entities\[].fields\[].encrypted                    | Column-level encryption flag                           | boolean         | #/components/schemas/Outputs/properties/entities/items/properties/fields/items/properties/encrypted                                  | Reflects `"encrypted": true` annotations in ERD        | Value must be `true` for every field marked encrypted in ERD; Value must be `false` otherwise; Value is required                                                                                                |
| outputs.entities\[].primary\_key.columns\[]                | Columns that form the primary key                      | list\[string]   | #/components/schemas/Outputs/properties/entities/items/properties/primary\_key/properties/columns/items                              | None                                                   | List must contain at least one column; Columns must exist in the entity; Order must be deterministic; Field is required if a PK is defined in ERD                                                               |
| outputs.entities\[].foreign\_keys\[]                       | Foreign key constraints for the entity                 | array of object | #/components/schemas/Outputs/properties/entities/items/properties/foreign\_keys/items                                                | Each item describes one FK                             | Array must contain exactly the FKs defined in ERD; Order must be deterministic by FK name; Array may be empty if no FKs                                                                                         |
| outputs.entities\[].foreign\_keys\[].name                  | Foreign key constraint name                            | string          | #/components/schemas/Outputs/properties/entities/items/properties/foreign\_keys/items/properties/name                                | DB-visible identifier                                  | Value must be non-empty; Value must be unique per entity; Value is required when FKs exist                                                                                                                      |
| outputs.entities\[].foreign\_keys\[].columns\[]            | Local columns participating in the FK                  | list\[string]   | #/components/schemas/Outputs/properties/entities/items/properties/foreign\_keys/items/properties/columns/items                       | None                                                   | All columns must exist in the entity; Order must be deterministic; Field is required when FKs exist                                                                                                             |
| outputs.entities\[].foreign\_keys\[].references.entity     | Referenced entity name                                 | string          | #/components/schemas/Outputs/properties/entities/items/properties/foreign\_keys/items/properties/references/properties/entity        | None                                                   | Value must match an ERD entity name; Value is required when FKs exist                                                                                                                                           |
| outputs.entities\[].foreign\_keys\[].references.columns\[] | Referenced columns                                     | list\[string]   | #/components/schemas/Outputs/properties/entities/items/properties/foreign\_keys/items/properties/references/properties/columns/items | None                                                   | All columns must exist in the referenced entity; Order must be deterministic; Field is required when FKs exist                                                                                                  |
| outputs.entities\[].unique\_constraints\[]                 | Unique constraints defined on the entity               | array of object | #/components/schemas/Outputs/properties/entities/items/properties/unique\_constraints/items                                          | Each item describes one unique constraint              | Array must contain exactly the unique constraints defined in ERD; Order must be deterministic by constraint name; Array may be empty                                                                            |
| outputs.entities\[].unique\_constraints\[].name            | Unique constraint name                                 | string          | #/components/schemas/Outputs/properties/entities/items/properties/unique\_constraints/items/properties/name                          | DB-visible identifier                                  | Value must be non-empty; Value must be unique per entity; Value is required when uniques exist                                                                                                                  |
| outputs.entities\[].unique\_constraints\[].columns\[]      | Columns participating in the unique constraint         | list\[string]   | #/components/schemas/Outputs/properties/entities/items/properties/unique\_constraints/items/properties/columns/items                 | None                                                   | All columns must exist in the entity; Order must be deterministic; Field is required when uniques exist                                                                                                         |
| outputs.entities\[].indexes\[]                             | Secondary indexes for the entity                       | array of object | #/components/schemas/Outputs/properties/entities/items/properties/indexes/items                                                      | Each item describes one index                          | Array must contain exactly the indexes defined in ERD; Order must be deterministic by index name; Array may be empty                                                                                            |
| outputs.entities\[].indexes\[].name                        | Index name                                             | string          | #/components/schemas/Outputs/properties/entities/items/properties/indexes/items/properties/name                                      | DB-visible identifier                                  | Value must be non-empty; Value must be unique per entity; Value is required when indexes exist                                                                                                                  |
| outputs.entities\[].indexes\[].columns\[]                  | Indexed columns                                        | list\[string]   | #/components/schemas/Outputs/properties/entities/items/properties/indexes/items/properties/columns/items                             | None                                                   | All columns must exist in the entity; Order must be deterministic; Field is required when indexes exist                                                                                                         |
| outputs.enums\[]                                           | Enumerated types created by migrations                 | array of object | #/components/schemas/Outputs/properties/enums/items                                                                                  | Examples: `doc_kind`, `answer_kind`                    | Array must contain all enums defined in ERD; Order must be deterministic by enum name; Array may be empty                                                                                                       |
| outputs.enums\[].name                                      | Enum name                                              | string          | #/components/schemas/Outputs/properties/enums/items/properties/name                                                                  | None                                                   | Value must be non-empty; Value must match ERD enum name; Value is required when enums exist                                                                                                                     |
| outputs.enums\[].values\[]                                 | Allowed values for the enum                            | list\[string]   | #/components/schemas/Outputs/properties/enums/items/properties/values/items                                                          | None                                                   | List must contain at least one value; Values must match ERD; Order must be deterministic; Field is required when enums exist                                                                                    |
| outputs.encrypted\_fields\[]                               | Fully-qualified names of encrypted fields              | list\[string]   | #/components/schemas/Outputs/properties/encrypted\_fields/items                                                                      | Format `Entity.field_name`                             | List must include every encrypted field from ERD; Values must be unique; List may be empty only if ERD marks none as encrypted                                                                                  |
| outputs.constraints\_applied\[]                            | Global list of constraints applied across entities     | list\[string]   | #/components/schemas/Outputs/properties/constraints\_applied/items                                                                   | May include PK/FK/UNIQUE/CHECK identifiers             | List must include all constraints defined in ERD; Values must be non-empty; Values must be unique; Order must be deterministic                                                                                  |
| outputs.migration\_journal\[]                              | Ordered records of executed migrations                 | array of object | #/components/schemas/Outputs/properties/migration\_journal/items                                                                     | Projection of the migration runner’s persisted journal | Array must contain at least one entry; Entries must be ordered deterministically by sequence; Each entry must include filename and applied\_at; Array is optional if a journal is not persisted in this feature |
| outputs.migration\_journal\[].filename                     | Executed migration filename                            | path            | #/components/schemas/Outputs/properties/migration\_journal/items/properties/filename                                                 | Project-relative under `./migrations`                  | Value must be a valid project-relative path; Value must be unique within the journal; Value is required when journal exists                                                                                     |
| outputs.migration\_journal\[].applied\_at                  | Timestamp when migration was applied                   | string          | #/components/schemas/Outputs/properties/migration\_journal/items/properties/applied\_at                                              | ISO 8601 UTC timestamp                                 | Value must be ISO 8601 UTC; Value must be non-decreasing across the journal; Value is required when journal exists                                                                                              |

| Error Code                                                        | Field Reference                   | Description                                                                                                  | Likely Cause                                                     | Flow Impact         | Behavioural AC Required |
| ----------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- | ------------------- | ----------------------- |
| PRE\_docs\_erd\_spec\_json\_MISSING\_OR\_UNREADABLE               | docs/erd\_spec.json               | Pre-condition failed: file does not exist or is not readable for docs/erd\_spec.json                         | Missing file; wrong path; insufficient permissions               | halt\_pipeline      | Yes                     |
| PRE\_docs\_erd\_spec\_json\_INVALID\_JSON                         | docs/erd\_spec.json               | Pre-condition failed: content does not parse as valid JSON for docs/erd\_spec.json                           | Malformed JSON                                                   | halt\_pipeline      | Yes                     |
| PRE\_docs\_erd\_spec\_json\_SCHEMA\_MISMATCH                      | docs/erd\_spec.json               | Pre-condition failed: content does not conform to the referenced schema for docs/erd\_spec.json              | Out-of-date spec; wrong shape; missing keys                      | halt\_pipeline      | Yes                     |
| PRE\_docs\_erd\_mermaid\_md\_MISSING\_OR\_UNREADABLE              | docs/erd\_mermaid.md              | Pre-condition failed: file does not exist or is not readable for docs/erd\_mermaid.md                        | Missing file; wrong path; insufficient permissions               | halt\_pipeline      | Yes                     |
| PRE\_docs\_erd\_mermaid\_md\_NOT\_UTF8\_TEXT                      | docs/erd\_mermaid.md              | Pre-condition failed: content is not UTF-8 text for docs/erd\_mermaid.md                                     | Wrong encoding; binary file                                      | halt\_pipeline      | Yes                     |
| PRE\_docs\_erd\_mermaid\_md\_INVALID\_MERMAID                     | docs/erd\_mermaid.md              | Pre-condition failed: diagram blocks are not syntactically valid Mermaid for docs/erd\_mermaid.md            | Syntax errors in diagram                                         | halt\_pipeline      | Yes                     |
| PRE\_docs\_erd\_relationships\_csv\_MISSING\_OR\_UNREADABLE       | docs/erd\_relationships.csv       | Pre-condition failed: file does not exist or is not readable for docs/erd\_relationships.csv                 | Missing file; wrong path; insufficient permissions               | halt\_pipeline      | Yes                     |
| PRE\_docs\_erd\_relationships\_csv\_INVALID\_CSV                  | docs/erd\_relationships.csv       | Pre-condition failed: content does not parse as CSV for docs/erd\_relationships.csv                          | Malformed CSV; delimiter/quote issues                            | halt\_pipeline      | Yes                     |
| PRE\_docs\_erd\_relationships\_csv\_HEADER\_MISMATCH              | docs/erd\_relationships.csv       | Pre-condition failed: columns do not match expected headers for docs/erd\_relationships.csv                  | Wrong header names/order                                         | halt\_pipeline      | Yes                     |
| PRE\_migrations\_001\_init\_sql\_MISSING\_OR\_UNREADABLE          | migrations/001\_init.sql          | Pre-condition failed: file does not exist or is not readable for migrations/001\_init.sql                    | Missing file; wrong path; insufficient permissions               | halt\_pipeline      | Yes                     |
| PRE\_migrations\_001\_init\_sql\_INVALID\_SQL                     | migrations/001\_init.sql          | Pre-condition failed: file does not parse as valid SQL for migrations/001\_init.sql                          | SQL syntax errors                                                | halt\_pipeline      | Yes                     |
| PRE\_migrations\_001\_init\_sql\_EXECUTION\_ERROR                 | migrations/001\_init.sql          | Pre-condition failed: statements do not execute without error for migrations/001\_init.sql                   | Incompatible DB version; missing privileges; conflicting objects | halt\_pipeline      | Yes                     |
| PRE\_migrations\_002\_constraints\_sql\_MISSING\_OR\_UNREADABLE   | migrations/002\_constraints.sql   | Pre-condition failed: file does not exist or is not readable for migrations/002\_constraints.sql             | Missing file; wrong path; insufficient permissions               | halt\_pipeline      | Yes                     |
| PRE\_migrations\_002\_constraints\_sql\_INVALID\_SQL              | migrations/002\_constraints.sql   | Pre-condition failed: file does not parse as valid SQL for migrations/002\_constraints.sql                   | SQL syntax errors                                                | halt\_pipeline      | Yes                     |
| PRE\_migrations\_002\_constraints\_sql\_EXECUTION\_ERROR          | migrations/002\_constraints.sql   | Pre-condition failed: statements do not execute without error for migrations/002\_constraints.sql            | FK/unique/index creation errors; missing tables                  | halt\_pipeline      | Yes                     |
| PRE\_migrations\_003\_indexes\_sql\_MISSING\_OR\_UNREADABLE       | migrations/003\_indexes.sql       | Pre-condition failed: file does not exist or is not readable for migrations/003\_indexes.sql                 | Missing file; wrong path; insufficient permissions               | halt\_pipeline      | Yes                     |
| PRE\_migrations\_003\_indexes\_sql\_INVALID\_SQL                  | migrations/003\_indexes.sql       | Pre-condition failed: file does not parse as valid SQL for migrations/003\_indexes.sql                       | SQL syntax errors                                                | halt\_pipeline      | Yes                     |
| PRE\_migrations\_003\_indexes\_sql\_EXECUTION\_ERROR              | migrations/003\_indexes.sql       | Pre-condition failed: statements do not execute without error for migrations/003\_indexes.sql                | Index creation errors; lock conflicts                            | halt\_pipeline      | Yes                     |
| PRE\_migrations\_004\_rollbacks\_sql\_MISSING\_OR\_UNREADABLE     | migrations/004\_rollbacks.sql     | Pre-condition failed: file does not exist or is not readable for migrations/004\_rollbacks.sql               | Missing file; wrong path; insufficient permissions               | halt\_pipeline      | Yes                     |
| PRE\_migrations\_004\_rollbacks\_sql\_INVALID\_SQL                | migrations/004\_rollbacks.sql     | Pre-condition failed: file does not parse as valid SQL for migrations/004\_rollbacks.sql                     | SQL syntax errors                                                | halt\_pipeline      | Yes                     |
| PRE\_migrations\_004\_rollbacks\_sql\_EXECUTION\_ERROR            | migrations/004\_rollbacks.sql     | Pre-condition failed: statements do not execute without error for migrations/004\_rollbacks.sql              | Drop order conflicts; dependency violations                      | halt\_pipeline      | Yes                     |
| PRE\_config\_database\_url\_MISSING                               | config/database.url               | Pre-condition failed: field is required and must be provided for config/database.url                         | Missing configuration                                            | halt\_pipeline      | Yes                     |
| PRE\_config\_database\_url\_INVALID\_DSN                          | config/database.url               | Pre-condition failed: value is not a valid DSN for config/database.url                                       | Malformed URL; wrong scheme                                      | halt\_pipeline      | Yes                     |
| PRE\_config\_database\_url\_HOST\_UNRESOLVED                      | config/database.url               | Pre-condition failed: hostname does not resolve for config/database.url                                      | DNS issue; typo in host                                          | halt\_pipeline      | Yes                     |
| PRE\_config\_database\_ssl\_required\_MISSING                     | config/database.ssl.required      | Pre-condition failed: field is required and must be provided for config/database.ssl.required                | Missing configuration                                            | halt\_pipeline      | Yes                     |
| PRE\_config\_database\_ssl\_required\_NOT\_BOOLEAN                | config/database.ssl.required      | Pre-condition failed: value is not boolean for config/database.ssl.required                                  | Wrong type                                                       | halt\_pipeline      | Yes                     |
| PRE\_config\_database\_ssl\_required\_TLS\_MATERIALS\_UNAVAILABLE | config/database.ssl.required      | Pre-condition failed: TLS materials are not available while SSL is required for config/database.ssl.required | Missing CA bundle/certs; misconfiguration                        | halt\_pipeline      | Yes                     |
| PRE\_config\_encryption\_mode\_MISSING                            | config/encryption.mode            | Pre-condition failed: field is required and must be provided for config/encryption.mode                      | Missing configuration                                            | halt\_pipeline      | Yes                     |
| PRE\_config\_encryption\_mode\_INVALID\_VALUE                     | config/encryption.mode            | Pre-condition failed: value is not one of the allowed set for config/encryption.mode                         | Unsupported mode; typo                                           | halt\_pipeline      | Yes                     |
| PRE\_config\_kms\_key\_alias\_REQUIRED\_FOR\_COLUMN\_MODE         | config/kms.key\_alias             | Pre-condition failed: field is required when encryption.mode includes column for config/kms.key\_alias       | Column encryption selected without key alias                     | halt\_pipeline      | Yes                     |
| PRE\_config\_kms\_key\_alias\_ALIAS\_NOT\_FOUND                   | config/kms.key\_alias             | Pre-condition failed: alias does not exist in KMS for config/kms.key\_alias                                  | Wrong alias; key deleted                                         | halt\_pipeline      | Yes                     |
| PRE\_kms\_get\_key\_alias\_CALL\_FAILED                           | kms.get\_key(alias)               | Pre-condition failed: call did not complete without error for kms.get\_key(alias)                            | Network/KMS outage; permissions                                  | halt\_pipeline      | Yes                     |
| PRE\_kms\_get\_key\_alias\_SCHEMA\_MISMATCH                       | kms.get\_key(alias)               | Pre-condition failed: return value does not match declared schema for kms.get\_key(alias)                    | Provider contract change; parsing error                          | halt\_pipeline      | Yes                     |
| PRE\_kms\_get\_key\_alias\_NOT\_IMMUTABLE                         | kms.get\_key(alias)               | Pre-condition failed: return value is not treated as immutable within this step for kms.get\_key(alias)      | Object mutated by caller; shared reference misuse                | halt\_pipeline      | Yes                     |
| PRE\_secrets\_db\_password\_CALL\_FAILED                          | secrets/db\_password              | Pre-condition failed: call did not complete without error for secrets/db\_password                           | Secret Manager outage; permissions                               | halt\_pipeline      | Yes                     |
| PRE\_secrets\_db\_password\_SCHEMA\_MISMATCH                      | secrets/db\_password              | Pre-condition failed: return value does not match declared schema for secrets/db\_password                   | Wrong secret type; missing value                                 | halt\_pipeline      | Yes                     |
| PRE\_secrets\_db\_password\_LOGGED                                | secrets/db\_password              | Pre-condition failed: secret was logged contrary to requirement for secrets/db\_password                     | Misconfigured logging; debug dumps                               | block\_finalization | Yes                     |
| PRE\_truststore\_ca\_bundle\_pem\_MISSING\_OR\_UNREADABLE         | truststore/ca\_bundle.pem         | Pre-condition failed: file does not exist or is not readable for truststore/ca\_bundle.pem                   | Missing file; wrong path; permissions                            | halt\_pipeline      | Yes                     |
| PRE\_truststore\_ca\_bundle\_pem\_INVALID\_PEM                    | truststore/ca\_bundle.pem         | Pre-condition failed: content does not parse as valid PEM for truststore/ca\_bundle.pem                      | Corrupt certificate; wrong format                                | halt\_pipeline      | Yes                     |
| PRE\_truststore\_ca\_bundle\_pem\_CERT\_NOT\_VALID                | truststore/ca\_bundle.pem         | Pre-condition failed: certificate dates are not within validity for truststore/ca\_bundle.pem                | Expired/not yet valid certs                                      | halt\_pipeline      | Yes                     |
| PRE\_policy\_encrypted\_fields\_MISSING\_OR\_UNREADABLE           | policy/encrypted\_fields          | Pre-condition failed: file does not exist or is not readable for policy/encrypted\_fields                    | Missing file; wrong path; permissions                            | halt\_pipeline      | Yes                     |
| PRE\_policy\_encrypted\_fields\_POINTERS\_UNRESOLVED              | policy/encrypted\_fields          | Pre-condition failed: JSON pointers do not resolve for policy/encrypted\_fields                              | Wrong pointers; mismatched ERD                                   | halt\_pipeline      | Yes                     |
| PRE\_policy\_encrypted\_fields\_FIELD\_NOT\_IN\_ENTITY            | policy/encrypted\_fields          | Pre-condition failed: referenced field does not exist in target entity for policy/encrypted\_fields          | ERD drift; typo in field name                                    | halt\_pipeline      | Yes                     |
| PRE\_config\_migration\_timeout\_seconds\_MISSING                 | config/migration.timeout\_seconds | Pre-condition failed: field is required and must be provided for config/migration.timeout\_seconds           | Missing configuration                                            | halt\_pipeline      | Yes                     |
| PRE\_config\_migration\_timeout\_seconds\_NOT\_POSITIVE\_INT      | config/migration.timeout\_seconds | Pre-condition failed: value is not an integer greater than zero for config/migration.timeout\_seconds        | Wrong type; zero/negative value                                  | halt\_pipeline      | Yes                     |

| Error Code                                                                             | Output Field Ref                                           | Description                                                            | Likely Cause                                    | Flow Impact         | Behavioural AC Required |
| -------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------- | ------------------- | ----------------------- |
| POST\_OUTPUTS\_ENTITIES\_INCOMPLETE                                                    | outputs.entities\[]                                        | Array does not include every entity defined in ERD                     | Missing entities; ERD/spec drift                | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_ORDER\_NOT\_DETERMINISTIC                                     | outputs.entities\[]                                        | Array order is not deterministic by entity name                        | Non-deterministic sorting; unstable enumeration | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_MUTABLE\_WITHIN\_STEP                                         | outputs.entities\[]                                        | Array is not immutable within this step                                | Data mutated post-creation; shared reference    | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_NAME\_EMPTY                                                   | outputs.entities\[].name                                   | Entity name value is empty                                             | Missing value                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_NAME\_MISMATCH\_WITH\_ERD                                     | outputs.entities\[].name                                   | Entity name does not match ERD exactly                                 | Renamed table; typo                             | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_NAME\_MISSING                                                 | outputs.entities\[].name                                   | Entity name value is missing                                           | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_SET\_INVALID                                          | outputs.entities\[].fields\[]                              | Fields array does not include all and only ERD-defined fields          | Missing or extra columns; spec drift            | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_ORDER\_NOT\_DETERMINISTIC                             | outputs.entities\[].fields\[]                              | Fields array order is not deterministic by field name                  | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_ARRAY\_MISSING                                        | outputs.entities\[].fields\[]                              | Fields array is missing for the entity                                 | Omitted structure                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_NAME\_MISMATCH\_WITH\_ERD                             | outputs.entities\[].fields\[].name                         | Field name does not match ERD exactly                                  | Renamed column; typo                            | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_NAME\_NOT\_UNIQUE                                     | outputs.entities\[].fields\[].name                         | Field name is not unique within the entity                             | Duplicate column entry                          | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_NAME\_MISSING                                         | outputs.entities\[].fields\[].name                         | Field name value is missing                                            | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_TYPE\_MISMATCH\_WITH\_ERD                             | outputs.entities\[].fields\[].type                         | Field type does not match ERD type exactly                             | Wrong SQL type; enum mismatch                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_TYPE\_MISSING                                         | outputs.entities\[].fields\[].type                         | Field type value is missing                                            | Omitted type                                    | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_ENCRYPTED\_FALSE\_WHEN\_REQUIRED                      | outputs.entities\[].fields\[].encrypted                    | Encrypted flag is false for a field marked encrypted in ERD            | Column not encrypted; missing annotation        | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_ENCRYPTED\_TRUE\_WHEN\_NOT\_REQUIRED                  | outputs.entities\[].fields\[].encrypted                    | Encrypted flag is true for a field not marked encrypted in ERD         | Over-encryption; wrong policy mapping           | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FIELDS\_ENCRYPTED\_MISSING                                    | outputs.entities\[].fields\[].encrypted                    | Encrypted flag value is missing                                        | Omitted flag                                    | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_PRIMARY\_KEY\_COLUMNS\_EMPTY                                  | outputs.entities\[].primary\_key.columns\[]                | Primary key columns list is empty                                      | PK not defined correctly                        | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_PRIMARY\_KEY\_COLUMNS\_UNKNOWN                                | outputs.entities\[].primary\_key.columns\[]                | Primary key list references columns not in the entity                  | Misspelled or missing columns                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_PRIMARY\_KEY\_COLUMNS\_ORDER\_NOT\_DETERMINISTIC              | outputs.entities\[].primary\_key.columns\[]                | Primary key column order is not deterministic                          | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_PRIMARY\_KEY\_COLUMNS\_MISSING\_WHEN\_PK\_DEFINED             | outputs.entities\[].primary\_key.columns\[]                | Primary key columns list is missing while PK is defined in ERD         | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_SET\_INVALID                                   | outputs.entities\[].foreign\_keys\[]                       | Foreign keys array does not match ERD exactly                          | Missing or extra FKs; spec drift                | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_ORDER\_NOT\_DETERMINISTIC                      | outputs.entities\[].foreign\_keys\[]                       | Foreign keys array order is not deterministic by FK name               | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_NAME\_EMPTY                                    | outputs.entities\[].foreign\_keys\[].name                  | Foreign key name value is empty                                        | Missing value                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_NAME\_NOT\_UNIQUE                              | outputs.entities\[].foreign\_keys\[].name                  | Foreign key name is not unique within the entity                       | Duplicate FK name                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_NAME\_MISSING\_WHEN\_FKS\_EXIST                | outputs.entities\[].foreign\_keys\[].name                  | Foreign key name is missing while FKs exist                            | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_COLUMNS\_UNKNOWN                               | outputs.entities\[].foreign\_keys\[].columns\[]            | Foreign key references columns not in the entity                       | Misspelled or missing columns                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_COLUMNS\_ORDER\_NOT\_DETERMINISTIC             | outputs.entities\[].foreign\_keys\[].columns\[]            | Foreign key columns order is not deterministic                         | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_COLUMNS\_MISSING\_WHEN\_FKS\_EXIST             | outputs.entities\[].foreign\_keys\[].columns\[]            | Foreign key columns list is missing while FKs exist                    | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_REFERENCES\_ENTITY\_MISMATCH\_WITH\_ERD        | outputs.entities\[].foreign\_keys\[].references.entity     | Referenced entity name does not match ERD                              | Wrong target table                              | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_REFERENCES\_ENTITY\_MISSING\_WHEN\_FKS\_EXIST  | outputs.entities\[].foreign\_keys\[].references.entity     | Referenced entity name is missing while FKs exist                      | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_REFERENCES\_COLUMNS\_UNKNOWN                   | outputs.entities\[].foreign\_keys\[].references.columns\[] | Referenced columns do not exist in the target entity                   | Misspelled or missing columns                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_REFERENCES\_COLUMNS\_ORDER\_NOT\_DETERMINISTIC | outputs.entities\[].foreign\_keys\[].references.columns\[] | Referenced columns order is not deterministic                          | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_REFERENCES\_COLUMNS\_MISSING\_WHEN\_FKS\_EXIST | outputs.entities\[].foreign\_keys\[].references.columns\[] | Referenced columns list is missing while FKs exist                     | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_SET\_INVALID                             | outputs.entities\[].unique\_constraints\[]                 | Unique constraints array does not match ERD exactly                    | Missing or extra uniques                        | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_ORDER\_NOT\_DETERMINISTIC                | outputs.entities\[].unique\_constraints\[]                 | Unique constraints array order is not deterministic by constraint name | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_NAME\_EMPTY                              | outputs.entities\[].unique\_constraints\[].name            | Unique constraint name value is empty                                  | Missing value                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_NAME\_NOT\_UNIQUE                        | outputs.entities\[].unique\_constraints\[].name            | Unique constraint name is not unique within the entity                 | Duplicate unique name                           | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_NAME\_MISSING\_WHEN\_UNIQUES\_EXIST      | outputs.entities\[].unique\_constraints\[].name            | Unique constraint name is missing while uniques exist                  | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_COLUMNS\_UNKNOWN                         | outputs.entities\[].unique\_constraints\[].columns\[]      | Unique constraint references columns not in the entity                 | Misspelled or missing columns                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_COLUMNS\_ORDER\_NOT\_DETERMINISTIC       | outputs.entities\[].unique\_constraints\[].columns\[]      | Unique constraint columns order is not deterministic                   | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_COLUMNS\_MISSING\_WHEN\_UNIQUES\_EXIST   | outputs.entities\[].unique\_constraints\[].columns\[]      | Unique constraint columns list is missing while uniques exist          | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_INDEXES\_SET\_INVALID                                         | outputs.entities\[].indexes\[]                             | Indexes array does not match ERD exactly                               | Missing or extra indexes                        | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_INDEXES\_ORDER\_NOT\_DETERMINISTIC                            | outputs.entities\[].indexes\[]                             | Indexes array order is not deterministic by index name                 | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_INDEXES\_NAME\_EMPTY                                          | outputs.entities\[].indexes\[].name                        | Index name value is empty                                              | Missing value                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_INDEXES\_NAME\_NOT\_UNIQUE                                    | outputs.entities\[].indexes\[].name                        | Index name is not unique within the entity                             | Duplicate index name                            | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_INDEXES\_NAME\_MISSING\_WHEN\_INDEXES\_EXIST                  | outputs.entities\[].indexes\[].name                        | Index name is missing while indexes exist                              | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_INDEXES\_COLUMNS\_UNKNOWN                                     | outputs.entities\[].indexes\[].columns\[]                  | Index references columns not in the entity                             | Misspelled or missing columns                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_INDEXES\_COLUMNS\_ORDER\_NOT\_DETERMINISTIC                   | outputs.entities\[].indexes\[].columns\[]                  | Index columns order is not deterministic                               | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENTITIES\_INDEXES\_COLUMNS\_MISSING\_WHEN\_INDEXES\_EXIST               | outputs.entities\[].indexes\[].columns\[]                  | Index columns list is missing while indexes exist                      | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENUMS\_INCOMPLETE                                                       | outputs.enums\[]                                           | Enums array does not contain all enums defined in ERD                  | Missing enum types                              | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENUMS\_ORDER\_NOT\_DETERMINISTIC                                        | outputs.enums\[]                                           | Enums array order is not deterministic by enum name                    | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENUMS\_NAME\_EMPTY                                                      | outputs.enums\[].name                                      | Enum name value is empty                                               | Missing value                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENUMS\_NAME\_MISMATCH\_WITH\_ERD                                        | outputs.enums\[].name                                      | Enum name does not match ERD exactly                                   | Renamed enum; typo                              | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENUMS\_NAME\_MISSING\_WHEN\_ENUMS\_EXIST                                | outputs.enums\[].name                                      | Enum name is missing while enums exist                                 | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENUMS\_VALUES\_EMPTY                                                    | outputs.enums\[].values\[]                                 | Enum values list is empty                                              | No values defined                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENUMS\_VALUES\_MISMATCH\_WITH\_ERD                                      | outputs.enums\[].values\[]                                 | Enum values do not match ERD exactly                                   | Added/removed values; wrong casing              | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENUMS\_VALUES\_ORDER\_NOT\_DETERMINISTIC                                | outputs.enums\[].values\[]                                 | Enum values order is not deterministic                                 | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENUMS\_VALUES\_MISSING\_WHEN\_ENUMS\_EXIST                              | outputs.enums\[].values\[]                                 | Enum values list is missing while enums exist                          | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENCRYPTED\_FIELDS\_INCOMPLETE                                           | outputs.encrypted\_fields\[]                               | Encrypted fields list does not include every encrypted field from ERD  | Missing entries; ERD drift                      | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENCRYPTED\_FIELDS\_VALUES\_NOT\_UNIQUE                                  | outputs.encrypted\_fields\[]                               | Encrypted fields list contains duplicate values                        | Duplicate entries                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_ENCRYPTED\_FIELDS\_PRESENT\_WHEN\_ERD\_NONE                             | outputs.encrypted\_fields\[]                               | Encrypted fields listed when ERD marks none as encrypted               | Over-declaration; policy mismatch               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_CONSTRAINTS\_APPLIED\_INCOMPLETE                                        | outputs.constraints\_applied\[]                            | Constraints list does not include all constraints defined in ERD       | Missing PK/FK/UNIQUE/CHECK                      | block\_finalization | Yes                     |
| POST\_OUTPUTS\_CONSTRAINTS\_APPLIED\_VALUE\_EMPTY                                      | outputs.constraints\_applied\[]                            | Constraints list contains an empty identifier                          | Missing name                                    | block\_finalization | Yes                     |
| POST\_OUTPUTS\_CONSTRAINTS\_APPLIED\_VALUES\_NOT\_UNIQUE                               | outputs.constraints\_applied\[]                            | Constraints list contains duplicate identifiers                        | Duplicate names                                 | block\_finalization | Yes                     |
| POST\_OUTPUTS\_CONSTRAINTS\_APPLIED\_ORDER\_NOT\_DETERMINISTIC                         | outputs.constraints\_applied\[]                            | Constraints list order is not deterministic                            | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_MIGRATION\_JOURNAL\_EMPTY                                               | outputs.migration\_journal\[]                              | Migration journal exists but contains no entries                       | Journal not recorded                            | block\_finalization | Yes                     |
| POST\_OUTPUTS\_MIGRATION\_JOURNAL\_ORDER\_NOT\_DETERMINISTIC                           | outputs.migration\_journal\[]                              | Migration journal order is not deterministic by sequence               | Unstable ordering                               | block\_finalization | Yes                     |
| POST\_OUTPUTS\_MIGRATION\_JOURNAL\_MISSING\_REQUIRED\_FIELDS                           | outputs.migration\_journal\[]                              | Migration journal entries do not include both filename and applied\_at | Partial entry metadata                          | block\_finalization | Yes                     |
| POST\_OUTPUTS\_MIGRATION\_JOURNAL\_FILENAME\_INVALID\_PATH                             | outputs.migration\_journal\[].filename                     | Migration journal filename is not a valid project-relative path        | Wrong format; absolute path; bad prefix         | block\_finalization | Yes                     |
| POST\_OUTPUTS\_MIGRATION\_JOURNAL\_FILENAME\_NOT\_UNIQUE                               | outputs.migration\_journal\[].filename                     | Migration journal filename is not unique within the journal            | Duplicate filenames                             | block\_finalization | Yes                     |
| POST\_OUTPUTS\_MIGRATION\_JOURNAL\_FILENAME\_MISSING\_WHEN\_JOURNAL\_EXISTS            | outputs.migration\_journal\[].filename                     | Migration journal filename is missing while journal exists             | Omitted field                                   | block\_finalization | Yes                     |
| POST\_OUTPUTS\_MIGRATION\_JOURNAL\_APPLIED\_AT\_INVALID\_FORMAT                        | outputs.migration\_journal\[].applied\_at                  | Migration journal timestamp is not ISO 8601 UTC                        | Wrong format; timezone not UTC                  | block\_finalization | Yes                     |
| POST\_OUTPUTS\_MIGRATION\_JOURNAL\_APPLIED\_AT\_NON\_MONOTONIC                         | outputs.migration\_journal\[].applied\_at                  | Migration journal timestamps are not non-decreasing                    | Clock skew; sorting bug                         | block\_finalization | Yes                     |
| POST\_OUTPUTS\_MIGRATION\_JOURNAL\_APPLIED\_AT\_MISSING\_WHEN\_JOURNAL\_EXISTS         | outputs.migration\_journal\[].applied\_at                  | Migration journal timestamp is missing while journal exists            | Omitted field                                   | block\_finalization | Yes                     |

| Error Code                       | Description                                                             | Likely Cause                                                                                                                                                                                                                     | Source (Step in Section 2.x)                                      | Step ID (from Section 2.2.6) | Reachability Rationale                                                                                                | Flow Impact    | Behavioural AC Required |
| -------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------- | -------------- | ----------------------- |
| RUN\_MIGRATION\_EXECUTION\_ERROR | Migration execution failed during initial schema creation               | SQL syntax errors; incompatible DB version; missing privileges                                                                                                                                                                   | 2.2.2 – E1: Create all required tables                            | STEP-3                       | E1 requires creating all tables including FieldGroup, QuestionToFieldGroup, GroupValue. A failure here is runtime     | halt\_pipeline | Yes                     |
| RUN\_CONSTRAINT\_CREATION\_ERROR | Creation of PK/FK/UNIQUE/INDEX constraints failed                       | Unique violation on GroupValue(response\_set\_id, field\_group\_id) or QuestionToFieldGroup(question\_id, field\_group\_id); missing referenced PK on FieldGroup or QuestionnaireQuestion or ResponseSet; index creation failure | 2.2.2 – E2: Create all required constraints                       | STEP-3                       | E2 mandates PK, FK, UNIQUE, INDEX creation including E9 and E10 for grouping constraints and indexes                  | halt\_pipeline | Yes                     |
| RUN\_ENCRYPTION\_APPLY\_ERROR    | Applying column-level encryption to sensitive fields failed             | KMS access issues; misconfigured encryption policy; encryption manifest missing GroupValue value fields                                                                                                                          | 2.2.2 – E3: Apply column-level encryption                         | STEP-3                       | E3 applies encryption to flagged columns; GroupValue.value\_\* fields are included per U10, U12                       | halt\_pipeline | Yes                     |
| RUN\_MIGRATION\_ROLLBACK\_ERROR  | Rollback failed to drop objects created by a migration                  | Dependency or lock conflicts; incorrect drop order involving new grouping FKs                                                                                                                                                    | 2.2.2 – E8: Execute rollback migrations                           | STEP-3                       | E8 defines rollback; dropping FieldGroup, QuestionToFieldGroup, GroupValue can fail due to dependency chains          | halt\_pipeline | Yes                     |
| RUN\_TLS\_CONNECTION\_ERROR      | Enforcing TLS on DB connection failed at initiation                     | Missing or invalid certificates; TLS config mismatch                                                                                                                                                                             | 2.2.2 – E4: Enforce TLS for DB connections                        | STEP-3                       | E4 requires TLS for DB sessions; connection establishment may fail at runtime                                         | halt\_pipeline | Yes                     |
| RUN\_ROW\_INSERTION\_ERROR       | Row insertion failed validation against declared schema                 | Null or invalid types; enum mismatch; length violations; invalid apply\_mode in QuestionToFieldGroup; invalid value\_json or option\_id in GroupValue                                                                            | 2.2.2 – E5: Validate row insert                                   | STEP-3                       | E5 requires schema validation on insert for all entities including new grouping tables                                | halt\_pipeline | Yes                     |
| RUN\_JOIN\_RESOLUTION\_ERROR     | Resolving placeholder values via joins failed                           | Missing FK links; unmapped placeholder; join cardinality mismatch                                                                                                                                                                | 2.2.2 – E6: Execute join to resolve placeholders                  | STEP-3                       | E6 requires Response → QuestionToPlaceholder → TemplatePlaceholder resolution. Grouping does not alter this join path | halt\_pipeline | Yes                     |
| RUN\_INVALID\_ENCRYPTION\_KEY    | Encryption or decryption key invalid or unavailable during field access | KMS key disabled or rotated; wrong alias; key policy blocks access to GroupValue encrypted fields                                                                                                                                | 2.2.3 – S3: Use KMS-managed keys while accessing sensitive fields | STEP-3                       | S3 governs access to encrypted fields including Response.\* and GroupValue.value\_\*                                  | halt\_pipeline | Yes                     |
| RUN\_TLS\_MATERIALS\_UNAVAILABLE | TLS materials required by policy were not available at connection time  | Missing CA bundle; unreadable cert files                                                                                                                                                                                         | 2.2.2 – E4: Enforce TLS for DB connections                        | STEP-3                       | E4 requires TLS enforcement; materials must be present at runtime                                                     | halt\_pipeline | Yes                     |
| RUN\_UNSUPPORTED\_DATA\_TYPE     | Runtime detected an unsupported data type during validation             | Unknown enum; unexpected JSON shape in Response.value\_json or GroupValue.value\_json                                                                                                                                            | 2.2.2 – E5: Validate row insert                                   | STEP-3                       | E5 covers runtime type validation on inserts for Response and GroupValue                                              | halt\_pipeline | Yes                     |
| RUN\_MIGRATION\_OUT\_OF\_ORDER   | A migration attempted to run out of the required sequence               | Incorrect runner order; missing prior migration                                                                                                                                                                                  | 2.2.2 – E1/E2/E8: Migration, constraint, rollback execution       | STEP-3                       | E1, E2, E8 imply ordered execution; out-of-order invocation is a runtime failure                                      | halt\_pipeline | Yes                     |
| RUN\_UNIDENTIFIED\_ERROR         | An otherwise unspecified runtime failure occurred during an E2.x step   | Unhandled exception; unexpected state                                                                                                                                                                                            | 2.2 – Any step (E1–E8, S1–S4)                                     | STEP-3                       | Section 2 defines multiple runtime operations; a catch-all may occur despite specific guards                          | halt\_pipeline | Yes                     |

| Error Code                            | Description                                                                                            | Likely Cause                                                  | Impacted Steps | EARS Refs              | Flow Impact    | Behavioural AC Required |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------- | -------------- | ---------------------- | -------------- | ----------------------- |
| ENV\_NETWORK\_UNREACHABLE\_DB         | Network unreachable while establishing database connectivity required for migrations and runtime joins | Network outage; firewall rules; VPC routing error             | STEP-3         | E1, E2, E4, E5, E6, E8 | halt\_pipeline | Yes                     |
| ENV\_DNS\_RESOLUTION\_FAILED\_DB      | DNS resolution failed for database host during connection setup                                        | Misconfigured DNS; missing DNS record; resolver outage        | STEP-3         | E1, E2, E4, E5, E6, E8 | halt\_pipeline | Yes                     |
| ENV\_TLS\_HANDSHAKE\_FAILED\_DB       | TLS handshake to the database endpoint failed                                                          | Invalid certificate; unsupported cipher; hostname mismatch    | STEP-3         | E4, S2                 | halt\_pipeline | Yes                     |
| ENV\_TLS\_MATERIALS\_MISSING          | TLS verification materials were unavailable for database connection                                    | Missing CA bundle; unreadable trust store; misconfigured path | STEP-3         | E4, S2                 | halt\_pipeline | Yes                     |
| ENV\_TIME\_SYNCHRONISATION\_FAILED    | System clock skew prevented certificate validation during TLS session establishment                    | Unsynchronised NTP; incorrect system time                     | STEP-3         | E4, S2                 | halt\_pipeline | Yes                     |
| ENV\_DB\_UNAVAILABLE                  | Database service was unavailable during migration or data operations                                   | Planned maintenance; instance crash; failover in progress     | STEP-3         | E1, E2, E4, E5, E6, E8 | halt\_pipeline | Yes                     |
| ENV\_DB\_PERMISSION\_DENIED           | Database permissions insufficient for required operations (create/alter/insert/rollback)               | Role lacks privileges; incorrect credentials; revoked grants  | STEP-3         | E1, E2, E5, E6, E8     | halt\_pipeline | Yes                     |
| ENV\_DB\_CONNECTIONS\_QUOTA\_EXCEEDED | Database connection quota or max\_connections limit exceeded at connection time                        | Too many concurrent clients; pool misconfiguration            | STEP-3         | E4, E1, E2, E5, E6, E8 | halt\_pipeline | Yes                     |
| ENV\_DATABASE\_STORAGE\_EXHAUSTED     | Database storage exhausted while creating objects or writing rows                                      | Disk full on DB node; tablespace quota exceeded               | STEP-3         | E1, E2, E5, E6, E8     | halt\_pipeline | Yes                     |
| ENV\_KMS\_UNAVAILABLE                 | KMS service unavailable when applying or accessing column encryption                                   | Regional outage; network path to KMS down                     | STEP-3         | E3, S3                 | halt\_pipeline | Yes                     |
| ENV\_KMS\_PERMISSION\_DENIED          | KMS denied access to required key operations for encryption/decryption                                 | IAM policy denies action; key disabled or revoked             | STEP-3         | E3, S3                 | halt\_pipeline | Yes                     |
| ENV\_KMS\_RATE\_LIMIT\_EXCEEDED       | KMS rate limit exceeded during encryption key operations                                               | Request burst exceeded KMS quota; throttling                  | STEP-3         | E3, S3                 | halt\_pipeline | Yes                     |

## 6.1 Architectural Acceptance Criteria

**6.1.1 Entities Declared and Named Canonically**
Each database entity must be declared with a unique canonical name that exactly matches `outputs.entities[].name`.

**6.1.2 Per-Entity Field List is Explicit**
Every entity must declare a `fields[]` collection, and each entry must expose `name` and `type`.

**6.1.3 No Duplicate Field Names Within an Entity**
Within each entity, field names must be unique.

**6.1.4 Field Types Align With ERD**
Every declared field type must match the ERD’s type declaration.

**6.1.5 Encryption Flag Present Where Required**
Fields marked sensitive in the ERD must include an `encrypted` boolean flag in the schema representation.

**6.1.6 Primary Key Columns Listed Structurally**
Entities that have a primary key must declare `primary_key.columns[]`.

**6.1.7 Foreign Keys Modelled With Names, Columns, and References**
Each foreign key must be an object including `name`, `columns[]`, and `references.entity` with `references.columns[]`.

**6.1.8 Unique Constraints Declared With Name and Columns**
Each unique constraint must expose `name` and `columns[]`.

**6.1.9 Secondary Indexes Declared With Name and Columns**
Each index must expose `name` and `columns[]`.

**6.1.10 Enumerations Declared Centrally**
All enumerations must be represented with `outputs.enums[].name` and `outputs.enums[].values[]`.

**6.1.11 Global Encrypted Field Manifest Exists**
There must be a global manifest of encrypted columns at `outputs.encrypted_fields[]` using `Entity.field` notation.

**6.1.12 Global Constraint Manifest Exists**
All applied constraints must be enumerated in `outputs.constraints_applied[]`.

**6.1.13 Migration Journal Structure is Stable**
If a journal is persisted, each entry must include `filename` (project-relative path) and `applied_at` (ISO-8601 UTC).

**6.1.14 Deterministic Ordering of Collections**
Collections representing entities, fields, constraints, indexes, enums, and journal entries must define a deterministic ordering key (name or sequence) and consistently apply it.

**6.1.15 Placeholder Lookup Artefacts Are Present**
The schema must include the artefacts necessary to support **direct placeholder resolution by lookup** on `QuestionnaireQuestion.placeholder_code` (e.g., presence of the field and uniqueness when present).

**6.1.16 Constraint Rules Enforced Structurally**
The model must declare structures that enable “one response per question per submission” and “**no duplicate placeholder codes**”.

**6.1.17 TLS Requirement Exposed as Configuration**
The architecture must surface a boolean configuration to enforce TLS for database connections.

**6.1.18 Column-Level Encryption is Configurable**
The architecture must surface an encryption mode and key alias configuration to drive column-level encryption at migration time.

**6.1.19 ERD Sources Versioned as Project Artefacts**
The ERD JSON spec and human-readable ERD documents must exist as committed project artefacts (normative JSON plus Mermaid/CSV parity docs).

**6.1.20 Rollback Scripts Present and Ordered**
Rollback migration scripts must be present and organised to reverse prior migrations in strict reverse order.

**6.1.21 Generated Document Storage is Modelled**
The schema must include a structure for generated documents with a stable identifier and output URI.

**6.1.22 Deterministic Lookup Contracts Are Encoded in Keys**
Keys and indexes necessary to guarantee **deterministic lookup** for repeated inputs must be explicitly defined on the participating tables (e.g., partial unique on `QuestionnaireQuestion.placeholder_code`, supporting indexes on `Response`).

**6.1.23 Encryption at Rest Policy is Traceable to Columns**
For every field marked encrypted in the model, there must be a corresponding entry in `outputs.encrypted_fields[]`.

**6.1.24 Constraint/Index Definitions Live With Schema, Not Code Paths**
All PK/FK/UNIQUE/CHECK constraints and indexes must be declared in schema/migration artefacts rather than embedded in application code.

**6.1.25 Placeholder Uniqueness Encoded as a Constraint**
**Placeholder code** uniqueness must be enforced via a declared **partial unique** constraint on `QuestionnaireQuestion.placeholder_code` (non-null values only), rather than runtime checks.

**6.1.26 One-Response-Per-Question-Per-Submission Encoded as a Constraint**
The “one response per question per submission” rule must be enforced by a composite unique constraint across the response table’s key fields.

**6.1.27 Deterministic Export Parity With ERD**
A generated ERD parity export must structurally correspond to the ERD spec (same entities and relationships represented), as static artefacts alongside the schema.

## 6.2 Happy Path Contractual Acceptance Criteria

**6.2.1.1 Entities Are Persisted With Canonical Names**
*Given* a schema is created from the ERD,
*When* entities are migrated successfully,
*Then* each entity must be persisted with the canonical name declared.
**Reference:** U1, E1; `outputs.entities[].name`

**6.2.1.2 Entity Fields Are Exposed With Declared Types**
*Given* a schema entity exists,
*When* its fields are created,
*Then* each field must be externally visible with its declared name and type.
**Reference:** U2, E1; `outputs.entities[].fields[].name`, `outputs.entities[].fields[].type`

**6.2.1.3 Primary Key Is Externally Declared**
*Given* an entity with a primary key,
*When* migrations are applied,
*Then* the entity must expose its `primary_key.columns[]`.
**Reference:** U1, E2; `outputs.entities[].primary_key.columns[]`

**6.2.1.4 Foreign Key Constraints Are Present**
*Given* related entities exist,
*When* migrations apply constraints,
*Then* each foreign key must be declared with name, columns, and referenced entity and columns.
**Reference:** U1, E2; `outputs.entities[].foreign_keys[]`

**6.2.1.5 Unique Constraints Are Present**
*Given* a schema requires uniqueness,
*When* migrations apply constraints,
*Then* unique constraints must be externally listed by name and columns.
**Reference:** U1, E2; `outputs.entities[].unique_constraints[]`

**6.2.1.6 Indexes Are Present**
*Given* entities are migrated,
*When* indexes are required,
*Then* each index must be externally observable with name and columns.
**Reference:** U1, E2; `outputs.entities[].indexes[]`

**6.2.1.7 Enums Are Externally Declared**
*Given* enums are defined in the schema,
*When* migrations apply,
*Then* enums must be visible with their declared name and values.
**Reference:** U1, E1; `outputs.enums[].name`, `outputs.enums[].values[]`

**6.2.1.8 Encrypted Fields Are Explicitly Flagged**
*Given* a field is sensitive,
*When* migrations apply encryption,
*Then* the field must expose an `encrypted` flag.
**Reference:** U8, E3, S3; `outputs.entities[].fields[].encrypted`

**6.2.1.9 Global Encrypted Fields Manifest Exists**
*Given* fields are encrypted,
*When* outputs are materialised,
*Then* a global manifest must list all encrypted fields.
**Reference:** U8, S1, S3; `outputs.encrypted_fields[]`

**6.2.1.10 Constraints Are Listed Globally**
*Given* constraints are applied,
*When* outputs are materialised,
*Then* a global list of constraints must exist.
**Reference:** U1, E2; `outputs.constraints_applied[]`

**6.2.1.11 Migration Journal Entries Include Filenames**
*Given* migrations are applied,
*When* a migration completes,
*Then* the journal must include a valid relative path in `filename`.
**Reference:** E1, E8; `outputs.migration_journal[].filename`

**6.2.1.12 Migration Journal Entries Include Timestamps**
*Given* migrations are applied,
*When* a migration completes,
*Then* the journal must include an `applied_at` ISO-8601 UTC timestamp.
**Reference:** E1, E8, S4; `outputs.migration_journal[].applied_at`

**6.2.1.13 One Response Per Question Per Submission**
*Given* responses are submitted,
*When* values are persisted,
*Then* no more than one response per question per submission must be observable.
**Reference:** N2; `outputs.entities[].unique_constraints[]`

**6.2.1.14 Duplicate Placeholders Are Rejected**
*Given* placeholder codes are defined on questions,
*When* outputs are materialised,
*Then* each non-null `placeholder_code` must be unique (partial unique index on `QuestionnaireQuestion.placeholder_code`).
**Reference:** U3, N1, E2; `outputs.entities[].unique_constraints[]`

**6.2.1.15 Direct Lookup Correctly Resolves Placeholders**
*Given* a `placeholder_code` exists on a question,
*When* placeholder values are resolved,
*Then* the system will source at most one question per code (DB-enforced uniqueness) and expose the direct-lookup model (no template join path).
**Reference:** E6; `outputs.entities[].name` (includes `QuestionnaireQuestion`), `outputs.entities[].unique_constraints[]`

**6.2.1.16 TLS Enforcement Is Externally Visible**
*Given* database connections are established,
*When* a TLS connection is required,
*Then* the configuration must declare enforcement (e.g., `config.database.ssl.required = true`) and connections must be attempted over TLS.
**Reference:** S2, E4; `config.database.ssl.required`

**6.2.1.17 Deterministic Ordering of Artefacts**
*Given* collections are produced,
*When* outputs are finalised,
*Then* ordering of entities, fields, constraints, and journal entries must be deterministic.
**Reference:** S4; `outputs.entities[]`, `outputs.entities[].fields[]`, `outputs.migration_journal[]`

# 6.2.2 Sad Path Contractual Acceptance Criteria

**6.2.2.1 ERD Spec File Missing or Unreadable**  
*Given* the system requires or produces `docs/erd_spec.json`,  
*When* the ERD spec file is missing or unreadable,  
*Then* the system must expose error `PRE_docs_erd_spec_json_MISSING_OR_UNREADABLE`.  
**Error Mode:** PRE_docs_erd_spec_json_MISSING_OR_UNREADABLE  
**Reference:** docs/erd_spec.json  

**6.2.2.2 ERD Spec Contains Invalid JSON**  
*Given* the system requires or produces `docs/erd_spec.json`,  
*When* the ERD spec content does not parse as valid JSON,  
*Then* the system must expose error `PRE_docs_erd_spec_json_INVALID_JSON`.  
**Error Mode:** PRE_docs_erd_spec_json_INVALID_JSON  
**Reference:** docs/erd_spec.json  

**6.2.2.3 ERD Spec Schema Mismatch**  
*Given* the system requires or produces `docs/erd_spec.json`,  
*When* the ERD spec content does not conform to the referenced schema,  
*Then* the system must expose error `PRE_docs_erd_spec_json_SCHEMA_MISMATCH`.  
**Error Mode:** PRE_docs_erd_spec_json_SCHEMA_MISMATCH  
**Reference:** docs/erd_spec.json  

**6.2.2.4 Mermaid ERD File Missing or Unreadable**  
*Given* the system requires or produces `docs/erd_mermaid.md`,  
*When* the Mermaid ERD file is missing or unreadable,  
*Then* the system must expose error `PRE_docs_erd_mermaid_md_MISSING_OR_UNREADABLE`.  
**Error Mode:** PRE_docs_erd_mermaid_md_MISSING_OR_UNREADABLE  
**Reference:** docs/erd_mermaid.md  

**6.2.2.5 Mermaid ERD Not UTF-8**  
*Given* the system requires or produces `docs/erd_mermaid.md`,  
*When* the Mermaid ERD content is not UTF-8 text,  
*Then* the system must expose error `PRE_docs_erd_mermaid_md_NOT_UTF8_TEXT`.  
**Error Mode:** PRE_docs_erd_mermaid_md_NOT_UTF8_TEXT  
**Reference:** docs/erd_mermaid.md  

**6.2.2.6 Mermaid ERD Invalid**  
*Given* the system requires or produces `docs/erd_mermaid.md`,  
*When* diagram blocks in the Mermaid ERD are not syntactically valid,  
*Then* the system must expose error `PRE_docs_erd_mermaid_md_INVALID_MERMAID`.  
**Error Mode:** PRE_docs_erd_mermaid_md_INVALID_MERMAID  
**Reference:** docs/erd_mermaid.md  

**6.2.2.7 Relationships CSV Missing or Unreadable**  
*Given* the system requires or produces `docs/erd_relationships.csv`,  
*When* the relationships CSV file is missing or unreadable,  
*Then* the system must expose error `PRE_docs_erd_relationships_csv_MISSING_OR_UNREADABLE`.  
**Error Mode:** PRE_docs_erd_relationships_csv_MISSING_OR_UNREADABLE  
**Reference:** docs/erd_relationships.csv  

**6.2.2.8 Relationships CSV Invalid**  
*Given* the system requires or produces `docs/erd_relationships.csv`,  
*When* the relationships CSV content does not parse as valid CSV,  
*Then* the system must expose error `PRE_docs_erd_relationships_csv_INVALID_CSV`.  
**Error Mode:** PRE_docs_erd_relationships_csv_INVALID_CSV  
**Reference:** docs/erd_relationships.csv  

**6.2.2.9 Relationships CSV Header Mismatch**  
*Given* the system requires or produces `docs/erd_relationships.csv`,  
*When* the relationships CSV columns do not match expected headers,  
*Then* the system must expose error `PRE_docs_erd_relationships_csv_HEADER_MISMATCH`.  
**Error Mode:** PRE_docs_erd_relationships_csv_HEADER_MISMATCH  
**Reference:** docs/erd_relationships.csv  

**6.2.2.10 Init Migration Missing or Unreadable**  
*Given* the system requires or produces `migrations/001_init.sql`,  
*When* the init migration file is missing or unreadable,  
*Then* the system must expose error `PRE_migrations_001_init_sql_MISSING_OR_UNREADABLE`.  
**Error Mode:** PRE_migrations_001_init_sql_MISSING_OR_UNREADABLE  
**Reference:** migrations/001_init.sql  

**6.2.2.11 Init Migration Invalid SQL**  
*Given* the system requires or produces `migrations/001_init.sql`,  
*When* the init migration file does not parse as valid SQL,  
*Then* the system must expose error `PRE_migrations_001_init_sql_INVALID_SQL`.  
**Error Mode:** PRE_migrations_001_init_sql_INVALID_SQL  
**Reference:** migrations/001_init.sql  

**6.2.2.12 Init Migration Execution Error**  
*Given* the system requires or produces `migrations/001_init.sql`,  
*When* statements in the init migration do not execute without error,  
*Then* the system must expose error `PRE_migrations_001_init_sql_EXECUTION_ERROR`.  
**Error Mode:** PRE_migrations_001_init_sql_EXECUTION_ERROR  
**Reference:** migrations/001_init.sql  

**6.2.2.13 Constraints Migration Missing or Unreadable**  
*Given* the system requires or produces `migrations/002_constraints.sql`,  
*When* the constraints migration file is missing or unreadable,  
*Then* the system must expose error `PRE_migrations_002_constraints_sql_MISSING_OR_UNREADABLE`.  
**Error Mode:** PRE_migrations_002_constraints_sql_MISSING_OR_UNREADABLE  
**Reference:** migrations/002_constraints.sql  

**6.2.2.14 Constraints Migration Invalid SQL**  
*Given* the system requires or produces `migrations/002_constraints.sql`,  
*When* the constraints migration file does not parse as valid SQL,  
*Then* the system must expose error `PRE_migrations_002_constraints_sql_INVALID_SQL`.  
**Error Mode:** PRE_migrations_002_constraints_sql_INVALID_SQL  
**Reference:** migrations/002_constraints.sql  

**6.2.2.15 Constraints Migration Execution Error**  
*Given* the system requires or produces `migrations/002_constraints.sql`,  
*When* statements in the constraints migration do not execute without error,  
*Then* the system must expose error `PRE_migrations_002_constraints_sql_EXECUTION_ERROR`.  
**Error Mode:** PRE_migrations_002_constraints_sql_EXECUTION_ERROR  
**Reference:** migrations/002_constraints.sql  

**6.2.2.16 Indexes Migration Missing or Unreadable**  
*Given* the system requires or produces `migrations/003_indexes.sql`,  
*When* the indexes migration file is missing or unreadable,  
*Then* the system must expose error `PRE_migrations_003_indexes_sql_MISSING_OR_UNREADABLE`.  
**Error Mode:** PRE_migrations_003_indexes_sql_MISSING_OR_UNREADABLE  
**Reference:** migrations/003_indexes.sql  

**6.2.2.17 Indexes Migration Invalid SQL**  
*Given* the system requires or produces `migrations/003_indexes.sql`,  
*When* the indexes migration file does not parse as valid SQL,  
*Then* the system must expose error `PRE_migrations_003_indexes_sql_INVALID_SQL`.  
**Error Mode:** PRE_migrations_003_indexes_sql_INVALID_SQL  
**Reference:** migrations/003_indexes.sql  

**6.2.2.18 Indexes Migration Execution Error**  
*Given* the system requires or produces `migrations/003_indexes.sql`,  
*When* statements in the indexes migration do not execute without error,  
*Then* the system must expose error `PRE_migrations_003_indexes_sql_EXECUTION_ERROR`.  
**Error Mode:** PRE_migrations_003_indexes_sql_EXECUTION_ERROR  
**Reference:** migrations/003_indexes.sql  

**6.2.2.19 Rollbacks Migration Missing or Unreadable**  
*Given* the system requires or produces `migrations/004_rollbacks.sql`,  
*When* the rollbacks migration file is missing or unreadable,  
*Then* the system must expose error `PRE_migrations_004_rollbacks_sql_MISSING_OR_UNREADABLE`.  
**Error Mode:** PRE_migrations_004_rollbacks_sql_MISSING_OR_UNREADABLE  
**Reference:** migrations/004_rollbacks.sql  

**6.2.2.20 Rollbacks Migration Invalid SQL**  
*Given* the system requires or produces `migrations/004_rollbacks.sql`,  
*When* the rollbacks migration file does not parse as valid SQL,  
*Then* the system must expose error `PRE_migrations_004_rollbacks_sql_INVALID_SQL`.  
**Error Mode:** PRE_migrations_004_rollbacks_sql_INVALID_SQL  
**Reference:** migrations/004_rollbacks.sql  

**6.2.2.21 Rollbacks Migration Execution Error**  
*Given* the system requires or produces `migrations/004_rollbacks.sql`,  
*When* statements in the rollbacks migration do not execute without error,  
*Then* the system must expose error `PRE_migrations_004_rollbacks_sql_EXECUTION_ERROR`.  
**Error Mode:** PRE_migrations_004_rollbacks_sql_EXECUTION_ERROR  
**Reference:** migrations/004_rollbacks.sql  

**6.2.2.22 Database URL Missing**  
*Given* the system requires or produces `config/database.url`,  
*When* the database URL field is not provided,  
*Then* the system must expose error `PRE_config_database_url_MISSING`.  
**Error Mode:** PRE_config_database_url_MISSING  
**Reference:** config/database.url  

**6.2.2.23 Database URL Invalid DSN**  
*Given* the system requires or produces `config/database.url`,  
*When* the database URL value is not a valid DSN,  
*Then* the system must expose error `PRE_config_database_url_INVALID_DSN`.  
**Error Mode:** PRE_config_database_url_INVALID_DSN  
**Reference:** config/database.url  

**6.2.2.24 Database Host Unresolved**  
*Given* the system requires or produces `config/database.url`,  
*When* the database hostname does not resolve,  
*Then* the system must expose error `PRE_config_database_url_HOST_UNRESOLVED`.  
**Error Mode:** PRE_config_database_url_HOST_UNRESOLVED  
**Reference:** config/database.url  

**6.2.2.25 Database SSL Required Missing**  
*Given* the system requires or produces `config/database.ssl.required`,  
*When* the SSL required flag is not provided,  
*Then* the system must expose error `PRE_config_database_ssl_required_MISSING`.  
**Error Mode:** PRE_config_database_ssl_required_MISSING  
**Reference:** config/database.ssl.required  

**6.2.2.26 Database SSL Required Not Boolean**  
*Given* the system requires or produces `config/database.ssl.required`,  
*When* the SSL required flag value is not boolean,  
*Then* the system must expose error `PRE_config_database_ssl_required_NOT_BOOLEAN`.  
**Error Mode:** PRE_config_database_ssl_required_NOT_BOOLEAN  
**Reference:** config/database.ssl.required  

**6.2.2.27 TLS Materials Unavailable While Required**  
*Given* the system requires or produces `config/database.ssl.required`,  
*When* TLS materials are not available while SSL is required,  
*Then* the system must expose error `PRE_config_database_ssl_required_TLS_MATERIALS_UNAVAILABLE`.  
**Error Mode:** PRE_config_database_ssl_required_TLS_MATERIALS_UNAVAILABLE  
**Reference:** config/database.ssl.required  

**6.2.2.28 Encryption Mode Missing**  
*Given* the system requires or produces `config/encryption.mode`,  
*When* the encryption mode field is not provided,  
*Then* the system must expose error `PRE_config_encryption_mode_MISSING`.  
**Error Mode:** PRE_config_encryption_mode_MISSING  
**Reference:** config/encryption.mode  

**6.2.2.29 Encryption Mode Invalid Value**  
*Given* the system requires or produces `config/encryption.mode`,  
*When* the encryption mode value is not one of the allowed set,  
*Then* the system must expose error `PRE_config_encryption_mode_INVALID_VALUE`.  
**Error Mode:** PRE_config_encryption_mode_INVALID_VALUE  
**Reference:** config/encryption.mode  

**6.2.2.30 KMS Key Alias Required For Column Mode**  
*Given* the system requires or produces `config/kms.key_alias`,  
*When* the key alias is not provided while column encryption is selected,  
*Then* the system must expose error `PRE_config_kms_key_alias_REQUIRED_FOR_COLUMN_MODE`.  
**Error Mode:** PRE_config_kms_key_alias_REQUIRED_FOR_COLUMN_MODE  
**Reference:** config/kms.key_alias  

**6.2.2.31 KMS Key Alias Not Found**  
*Given* the system requires or produces `config/kms.key_alias`,  
*When* the provided key alias does not exist in KMS,  
*Then* the system must expose error `PRE_config_kms_key_alias_ALIAS_NOT_FOUND`.  
**Error Mode:** PRE_config_kms_key_alias_ALIAS_NOT_FOUND  
**Reference:** config/kms.key_alias  

**6.2.2.32 KMS Get Key Call Failed**  
*Given* the system requires or produces `kms.get_key(alias)`,  
*When* the KMS call did not complete without error,  
*Then* the system must expose error `PRE_kms_get_key_alias_CALL_FAILED`.  
**Error Mode:** PRE_kms_get_key_alias_CALL_FAILED  
**Reference:** kms.get_key(alias)  

**6.2.2.33 KMS Get Key Schema Mismatch**  
*Given* the system requires or produces `kms.get_key(alias)`,  
*When* the KMS return value does not match the declared schema,  
*Then* the system must expose error `PRE_kms_get_key_alias_SCHEMA_MISMATCH`.  
**Error Mode:** PRE_kms_get_key_alias_SCHEMA_MISMATCH  
**Reference:** kms.get_key(alias)  

**6.2.2.34 KMS Get Key Not Immutable**  
*Given* the system requires or produces `kms.get_key(alias)`,  
*When* the KMS return value was not treated as immutable within the step,  
*Then* the system must expose error `PRE_kms_get_key_alias_NOT_IMMUTABLE`.  
**Error Mode:** PRE_kms_get_key_alias_NOT_IMMUTABLE  
**Reference:** kms.get_key(alias)  

**6.2.2.35 Secret Manager Call Failed**  
*Given* the system requires or produces `secrets/db_password`,  
*When* the Secret Manager call did not complete without error,  
*Then* the system must expose error `PRE_secrets_db_password_CALL_FAILED`.  
**Error Mode:** PRE_secrets_db_password_CALL_FAILED  
**Reference:** secrets/db_password  

**6.2.2.36 Secret Manager Schema Mismatch**  
*Given* the system requires or produces `secrets/db_password`,  
*When* the return value does not match the declared schema,  
*Then* the system must expose error `PRE_secrets_db_password_SCHEMA_MISMATCH`.  
**Error Mode:** PRE_secrets_db_password_SCHEMA_MISMATCH  
**Reference:** secrets/db_password  

**6.2.2.37 Secret Was Logged**  
*Given* the system requires or produces `secrets/db_password`,  
*When* the secret value was logged contrary to requirement,  
*Then* the system must expose error `PRE_secrets_db_password_LOGGED`.  
**Error Mode:** PRE_secrets_db_password_LOGGED  
**Reference:** secrets/db_password  

**6.2.2.38 CA Bundle Missing or Unreadable**  
*Given* the system requires or produces `truststore/ca_bundle.pem`,  
*When* the CA bundle file is missing or unreadable,  
*Then* the system must expose error `PRE_truststore_ca_bundle_pem_MISSING_OR_UNREADABLE`.  
**Error Mode:** PRE_truststore_ca_bundle_pem_MISSING_OR_UNREADABLE  
**Reference:** truststore/ca_bundle.pem  

**6.2.2.39 CA Bundle Invalid PEM**  
*Given* the system requires or produces `truststore/ca_bundle.pem`,  
*When* the CA bundle content does not parse as valid PEM,  
*Then* the system must expose error `PRE_truststore_ca_bundle_pem_INVALID_PEM`.  
**Error Mode:** PRE_truststore_ca_bundle_pem_INVALID_PEM  
**Reference:** truststore/ca_bundle.pem  

**6.2.2.40 CA Bundle Certificate Not Valid**  
*Given* the system requires or produces `truststore/ca_bundle.pem`,  
*When* certificate dates are not within validity,  
*Then* the system must expose error `PRE_truststore_ca_bundle_pem_CERT_NOT_VALID`.  
**Error Mode:** PRE_truststore_ca_bundle_pem_CERT_NOT_VALID  
**Reference:** truststore/ca_bundle.pem  

**6.2.2.41 Encrypted Fields Policy Missing or Unreadable**  
*Given* the system requires or produces `policy/encrypted_fields`,  
*When* the encrypted fields policy file is missing or unreadable,  
*Then* the system must expose error `PRE_policy_encrypted_fields_MISSING_OR_UNREADABLE`.  
**Error Mode:** PRE_policy_encrypted_fields_MISSING_OR_UNREADABLE  
**Reference:** policy/encrypted_fields  

**6.2.2.42 Encrypted Fields Pointers Unresolved**  
*Given* the system requires or produces `policy/encrypted_fields`,  
*When* the JSON pointers in the policy do not resolve,  
*Then* the system must expose error `PRE_policy_encrypted_fields_POINTERS_UNRESOLVED`.  
**Error Mode:** PRE_policy_encrypted_fields_POINTERS_UNRESOLVED  
**Reference:** policy/encrypted_fields  

**6.2.2.43 Encrypted Field Not In Entity**  
*Given* the system requires or produces `policy/encrypted_fields`,  
*When* a referenced field does not exist in the target entity,  
*Then* the system must expose error `PRE_policy_encrypted_fields_FIELD_NOT_IN_ENTITY`.  
**Error Mode:** PRE_policy_encrypted_fields_FIELD_NOT_IN_ENTITY  
**Reference:** policy/encrypted_fields  

**6.2.2.44 Migration Timeout Seconds Missing**  
*Given* the system requires or produces `config/migration.timeout_seconds`,  
*When* the timeout configuration is not provided,  
*Then* the system must expose error `PRE_config_migration_timeout_seconds_MISSING`.  
**Error Mode:** PRE_config_migration_timeout_seconds_MISSING  
**Reference:** config/migration.timeout_seconds  

**6.2.2.45 Migration Timeout Not Positive Integer**  
*Given* the system requires or produces `config/migration.timeout_seconds`,  
*When* the timeout value is not an integer greater than zero,  
*Then* the system must expose error `PRE_config_migration_timeout_seconds_NOT_POSITIVE_INT`.  
**Error Mode:** PRE_config_migration_timeout_seconds_NOT_POSITIVE_INT  
**Reference:** config/migration.timeout_seconds  

**6.2.2.46 Migration Execution Failure**  
*Given* the system requires or produces `migrations/001_init.sql, outputs.entities[]`,  
*When* a migration fails during initial schema creation,  
*Then* the system must expose error `RUN_MIGRATION_EXECUTION_ERROR`.  
**Error Mode:** RUN_MIGRATION_EXECUTION_ERROR  
**Reference:** migrations/001_init.sql, outputs.entities[]  

**6.2.2.47 Constraint Creation Error**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[], outputs.entities[].unique_constraints[]`,  
*When* creation of PK/FK/UNIQUE/INDEX constraints fails,  
*Then* the system must expose error `RUN_CONSTRAINT_CREATION_ERROR`.  
**Error Mode:** RUN_CONSTRAINT_CREATION_ERROR  
**Reference:** outputs.entities[].foreign_keys[], outputs.entities[].unique_constraints[]  

**6.2.2.48 Encryption Apply Error**  
*Given* the system requires or produces `outputs.entities[].fields[].encrypted`,  
*When* applying column-level encryption to sensitive fields fails,  
*Then* the system must expose error `RUN_ENCRYPTION_APPLY_ERROR`.  
**Error Mode:** RUN_ENCRYPTION_APPLY_ERROR  
**Reference:** outputs.entities[].fields[].encrypted  

**6.2.2.49 Rollback Migration Error**  
*Given* the system requires or produces `migrations/004_rollbacks.sql`,  
*When* rollback fails to drop created objects,  
*Then* the system must expose error `RUN_MIGRATION_ROLLBACK_ERROR`.  
**Error Mode:** RUN_MIGRATION_ROLLBACK_ERROR  
**Reference:** migrations/004_rollbacks.sql  

**6.2.2.50 TLS Connection Error**  
*Given* the system requires or produces `config/database.ssl.required`,  
*When* enforcing TLS on database connection fails at initiation,  
*Then* the system must expose error `RUN_TLS_CONNECTION_ERROR`.  
**Error Mode:** RUN_TLS_CONNECTION_ERROR  
**Reference:** config/database.ssl.required  

**6.2.2.51 Row Insertion Error**  
*Given* the system requires or produces `outputs.entities[].fields[]`,  
*When* row insertion fails validation against declared schema,  
*Then* the system must expose error `RUN_ROW_INSERTION_ERROR`.  
**Error Mode:** RUN_ROW_INSERTION_ERROR  
**Reference:** outputs.entities[].fields[]  

**6.2.2.52 Join Resolution Error**  
*Given* the system requires or produces `outputs.entities[].name (Response, QuestionToPlaceholder, TemplatePlaceholder)`,  
*When* resolving placeholder values via joins fails,  
*Then* the system must expose error `RUN_JOIN_RESOLUTION_ERROR`.  
**Error Mode:** RUN_JOIN_RESOLUTION_ERROR  
**Reference:** outputs.entities[].name (Response, QuestionToPlaceholder, TemplatePlaceholder)  

**6.2.2.53 Invalid Encryption Key**  
*Given* the system requires or produces `outputs.entities[].fields[].encrypted`,  
*When* encryption/decryption key is invalid or unavailable during field access,  
*Then* the system must expose error `RUN_INVALID_ENCRYPTION_KEY`.  
**Error Mode:** RUN_INVALID_ENCRYPTION_KEY  
**Reference:** outputs.entities[].fields[].encrypted  

**6.2.2.54 TLS Materials Unavailable**  
*Given* the system requires or produces `config/database.ssl.required`,  
*When* required TLS materials are unavailable at connection time,  
*Then* the system must expose error `RUN_TLS_MATERIALS_UNAVAILABLE`.  
**Error Mode:** RUN_TLS_MATERIALS_UNAVAILABLE  
**Reference:** config/database.ssl.required  

**6.2.2.55 Unsupported Data Type**  
*Given* the system requires or produces `outputs.entities[].fields[]`,  
*When* runtime detects an unsupported data type during validation,  
*Then* the system must expose error `RUN_UNSUPPORTED_DATA_TYPE`.  
**Error Mode:** RUN_UNSUPPORTED_DATA_TYPE  
**Reference:** outputs.entities[].fields[]  

**6.2.2.56 Migration Out of Order**  
*Given* the system requires or produces `migrations/*`,  
*When* a migration attempts to run out of the required sequence,  
*Then* the system must expose error `RUN_MIGRATION_OUT_OF_ORDER`.  
**Error Mode:** RUN_MIGRATION_OUT_OF_ORDER  
**Reference:** migrations/*  

**6.2.2.57 Unidentified Runtime Error**  
*Given* the system requires or produces `system`,  
*When* an unspecified runtime failure occurs during a 2.2 step,  
*Then* the system must expose error `RUN_UNIDENTIFIED_ERROR`.  
**Error Mode:** RUN_UNIDENTIFIED_ERROR  
**Reference:** system  

**6.2.2.58 Entities Missing From Outputs**  
*Given* the system requires or produces `outputs.entities[]`,  
*When* the array does not include every entity defined in ERD,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_INCOMPLETE`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_INCOMPLETE  
**Reference:** outputs.entities[]  

**6.2.2.59 Entities Order Not Deterministic**  
*Given* the system requires or produces `outputs.entities[]`,  
*When* the array order is not deterministic by entity name,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.entities[]  

**6.2.2.60 Entities Mutable Within Step**  
*Given* the system requires or produces `outputs.entities[]`,  
*When* the array is not immutable within this step,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_MUTABLE_WITHIN_STEP`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_MUTABLE_WITHIN_STEP  
**Reference:** outputs.entities[]  

**6.2.2.61 Entity Name Empty**  
*Given* the system requires or produces `outputs.entities[].name`,  
*When* the entity name value is empty,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_NAME_EMPTY`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_NAME_EMPTY  
**Reference:** outputs.entities[].name  

**6.2.2.62 Entity Name Mismatch With ERD**  
*Given* the system requires or produces `outputs.entities[].name`,  
*When* the entity name does not match ERD exactly,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_NAME_MISMATCH_WITH_ERD`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_NAME_MISMATCH_WITH_ERD  
**Reference:** outputs.entities[].name  

**6.2.2.63 Entity Name Missing**  
*Given* the system requires or produces `outputs.entities[].name`,  
*When* the entity name value is missing,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_NAME_MISSING`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_NAME_MISSING  
**Reference:** outputs.entities[].name  

**6.2.2.64 Entity Fields Set Invalid**  
*Given* the system requires or produces `outputs.entities[].fields[]`,  
*When* the fields array does not include all and only ERD-defined fields,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_SET_INVALID`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_SET_INVALID  
**Reference:** outputs.entities[].fields[]  

**6.2.2.65 Entity Fields Order Not Deterministic**  
*Given* the system requires or produces `outputs.entities[].fields[]`,  
*When* the fields array order is not deterministic by field name,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.entities[].fields[]  

**6.2.2.66 Entity Fields Array Missing**  
*Given* the system requires or produces `outputs.entities[].fields[]`,  
*When* the fields array is missing for the entity,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_ARRAY_MISSING`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_ARRAY_MISSING  
**Reference:** outputs.entities[].fields[]  

**6.2.2.67 Field Name Mismatch With ERD**  
*Given* the system requires or produces `outputs.entities[].fields[].name`,  
*When* the field name does not match ERD exactly,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_NAME_MISMATCH_WITH_ERD`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_NAME_MISMATCH_WITH_ERD  
**Reference:** outputs.entities[].fields[].name  

**6.2.2.68 Field Name Not Unique**  
*Given* the system requires or produces `outputs.entities[].fields[].name`,  
*When* the field name is not unique within the entity,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_NAME_NOT_UNIQUE`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_NAME_NOT_UNIQUE  
**Reference:** outputs.entities[].fields[].name  

**6.2.2.69 Field Name Missing**  
*Given* the system requires or produces `outputs.entities[].fields[].name`,  
*When* the field name value is missing,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_NAME_MISSING`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_NAME_MISSING  
**Reference:** outputs.entities[].fields[].name  

**6.2.2.70 Field Type Mismatch With ERD**  
*Given* the system requires or produces `outputs.entities[].fields[].type`,  
*When* the field type does not match ERD type exactly,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_TYPE_MISMATCH_WITH_ERD`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_TYPE_MISMATCH_WITH_ERD  
**Reference:** outputs.entities[].fields[].type  

**6.2.2.71 Field Type Missing**  
*Given* the system requires or produces `outputs.entities[].fields[].type`,  
*When* the field type value is missing,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_TYPE_MISSING`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_TYPE_MISSING  
**Reference:** outputs.entities[].fields[].type  

**6.2.2.72 Encrypted Flag False When Required**  
*Given* the system requires or produces `outputs.entities[].fields[].encrypted`,  
*When* the encrypted flag is false for a field marked encrypted in ERD,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_ENCRYPTED_FALSE_WHEN_REQUIRED`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_ENCRYPTED_FALSE_WHEN_REQUIRED  
**Reference:** outputs.entities[].fields[].encrypted  

**6.2.2.73 Encrypted Flag True When Not Required**  
*Given* the system requires or produces `outputs.entities[].fields[].encrypted`,  
*When* the encrypted flag is true for a field not marked encrypted in ERD,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_ENCRYPTED_TRUE_WHEN_NOT_REQUIRED`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_ENCRYPTED_TRUE_WHEN_NOT_REQUIRED  
**Reference:** outputs.entities[].fields[].encrypted  

**6.2.2.74 Encrypted Flag Missing**  
*Given* the system requires or produces `outputs.entities[].fields[].encrypted`,  
*When* the encrypted flag value is missing,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FIELDS_ENCRYPTED_MISSING`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FIELDS_ENCRYPTED_MISSING  
**Reference:** outputs.entities[].fields[].encrypted  

**6.2.2.75 Primary Key Columns Empty**  
*Given* the system requires or produces `outputs.entities[].primary_key.columns[]`,  
*When* the primary key columns list is empty,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_EMPTY`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_EMPTY  
**Reference:** outputs.entities[].primary_key.columns[]  

**6.2.2.76 Primary Key Columns Unknown**  
*Given* the system requires or produces `outputs.entities[].primary_key.columns[]`,  
*When* the primary key list references columns not in the entity,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_UNKNOWN`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_UNKNOWN  
**Reference:** outputs.entities[].primary_key.columns[]  

**6.2.2.77 Primary Key Columns Order Not Deterministic**  
*Given* the system requires or produces `outputs.entities[].primary_key.columns[]`,  
*When* the primary key column order is not deterministic,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.entities[].primary_key.columns[]  

**6.2.2.78 Primary Key Columns Missing When PK Defined**  
*Given* the system requires or produces `outputs.entities[].primary_key.columns[]`,  
*When* the primary key columns list is missing while PK is defined in ERD,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_MISSING_WHEN_PK_DEFINED`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_MISSING_WHEN_PK_DEFINED  
**Reference:** outputs.entities[].primary_key.columns[]  

**6.2.2.79 Foreign Keys Set Invalid**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[]`,  
*When* the foreign keys array does not match ERD exactly,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_SET_INVALID`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_SET_INVALID  
**Reference:** outputs.entities[].foreign_keys[]  

**6.2.2.80 Foreign Keys Order Not Deterministic**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[]`,  
*When* the foreign keys array order is not deterministic by FK name,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.entities[].foreign_keys[]  

**6.2.2.81 Foreign Key Name Empty**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].name`,  
*When* the foreign key name value is empty,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_NAME_EMPTY`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_NAME_EMPTY  
**Reference:** outputs.entities[].foreign_keys[].name  

**6.2.2.82 Foreign Key Name Not Unique**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].name`,  
*When* the foreign key name is not unique within the entity,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_NAME_NOT_UNIQUE`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_NAME_NOT_UNIQUE  
**Reference:** outputs.entities[].foreign_keys[].name  

**6.2.2.83 Foreign Key Name Missing When FKs Exist**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].name`,  
*When* the foreign key name is missing while FKs exist,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_NAME_MISSING_WHEN_FKS_EXIST`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_NAME_MISSING_WHEN_FKS_EXIST  
**Reference:** outputs.entities[].foreign_keys[].name  

**6.2.2.84 Foreign Key Columns Unknown**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].columns[]`,  
*When* the foreign key references columns not in the entity,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_COLUMNS_UNKNOWN`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_COLUMNS_UNKNOWN  
**Reference:** outputs.entities[].foreign_keys[].columns[]  

**6.2.2.85 Foreign Key Columns Order Not Deterministic**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].columns[]`,  
*When* the foreign key columns order is not deterministic,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_COLUMNS_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_COLUMNS_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.entities[].foreign_keys[].columns[]  

**6.2.2.86 Foreign Key Columns Missing When FKs Exist**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].columns[]`,  
*When* the foreign key columns list is missing while FKs exist,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_COLUMNS_MISSING_WHEN_FKS_EXIST`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_COLUMNS_MISSING_WHEN_FKS_EXIST  
**Reference:** outputs.entities[].foreign_keys[].columns[]  

**6.2.2.87 References Entity Mismatch With ERD**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].references.entity`,  
*When* the referenced entity name does not match ERD,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_ENTITY_MISMATCH_WITH_ERD`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_ENTITY_MISMATCH_WITH_ERD  
**Reference:** outputs.entities[].foreign_keys[].references.entity  

**6.2.2.88 References Entity Missing When FKs Exist**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].references.entity`,  
*When* the referenced entity name is missing while FKs exist,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_ENTITY_MISSING_WHEN_FKS_EXIST`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_ENTITY_MISSING_WHEN_FKS_EXIST  
**Reference:** outputs.entities[].foreign_keys[].references.entity  

**6.2.2.89 References Columns Unknown**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].references.columns[]`,  
*When* the referenced columns do not exist in the target entity,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_COLUMNS_UNKNOWN`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_COLUMNS_UNKNOWN  
**Reference:** outputs.entities[].foreign_keys[].references.columns[]  

**6.2.2.90 References Columns Order Not Deterministic**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].references.columns[]`,  
*When* the referenced columns order is not deterministic,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_COLUMNS_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_COLUMNS_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.entities[].foreign_keys[].references.columns[]  

**6.2.2.91 References Columns Missing When FKs Exist**  
*Given* the system requires or produces `outputs.entities[].foreign_keys[].references.columns[]`,  
*When* the referenced columns list is missing while FKs exist,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_COLUMNS_MISSING_WHEN_FKS_EXIST`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_COLUMNS_MISSING_WHEN_FKS_EXIST  
**Reference:** outputs.entities[].foreign_keys[].references.columns[]  

**6.2.2.92 Unique Constraints Set Invalid**  
*Given* the system requires or produces `outputs.entities[].unique_constraints[]`,  
*When* the unique constraints array does not match ERD exactly,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_SET_INVALID`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_SET_INVALID  
**Reference:** outputs.entities[].unique_constraints[]  

**6.2.2.93 Unique Constraints Order Not Deterministic**  
*Given* the system requires or produces `outputs.entities[].unique_constraints[]`,  
*When* the unique constraints array order is not deterministic by constraint name,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.entities[].unique_constraints[]  

**6.2.2.94 Unique Constraint Name Empty**  
*Given* the system requires or produces `outputs.entities[].unique_constraints[].name`,  
*When* the unique constraint name value is empty,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_NAME_EMPTY`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_NAME_EMPTY  
**Reference:** outputs.entities[].unique_constraints[].name  

**6.2.2.95 Unique Constraint Name Not Unique**  
*Given* the system requires or produces `outputs.entities[].unique_constraints[].name`,  
*When* the unique constraint name is not unique within the entity,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_NAME_NOT_UNIQUE`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_NAME_NOT_UNIQUE  
**Reference:** outputs.entities[].unique_constraints[].name  

**6.2.2.96 Unique Constraint Name Missing When Uniques Exist**  
*Given* the system requires or produces `outputs.entities[].unique_constraints[].name`,  
*When* the unique constraint name is missing while uniques exist,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_NAME_MISSING_WHEN_UNIQUES_EXIST`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_NAME_MISSING_WHEN_UNIQUES_EXIST  
**Reference:** outputs.entities[].unique_constraints[].name  

**6.2.2.97 Unique Constraint Columns Unknown**  
*Given* the system requires or produces `outputs.entities[].unique_constraints[].columns[]`,  
*When* the unique constraint references columns not in the entity,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_COLUMNS_UNKNOWN`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_COLUMNS_UNKNOWN  
**Reference:** outputs.entities[].unique_constraints[].columns[]  

**6.2.2.98 Unique Constraint Columns Order Not Deterministic**  
*Given* the system requires or produces `outputs.entities[].unique_constraints[].columns[]`,  
*When* the unique constraint columns order is not deterministic,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_COLUMNS_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_COLUMNS_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.entities[].unique_constraints[].columns[]  

**6.2.2.99 Unique Constraint Columns Missing When Uniques Exist**  
*Given* the system requires or produces `outputs.entities[].unique_constraints[].columns[]`,  
*When* the unique constraint columns list is missing while uniques exist,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_COLUMNS_MISSING_WHEN_UNIQUES_EXIST`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_COLUMNS_MISSING_WHEN_UNIQUES_EXIST  
**Reference:** outputs.entities[].unique_constraints[].columns[]  

**6.2.2.100 Indexes Set Invalid**  
*Given* the system requires or produces `outputs.entities[].indexes[]`,  
*When* the indexes array does not match ERD exactly,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_INDEXES_SET_INVALID`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_INDEXES_SET_INVALID  
**Reference:** outputs.entities[].indexes[]  

**6.2.2.101 Indexes Order Not Deterministic**  
*Given* the system requires or produces `outputs.entities[].indexes[]`,  
*When* the indexes array order is not deterministic by index name,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_INDEXES_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_INDEXES_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.entities[].indexes[]  

**6.2.2.102 Index Name Empty**  
*Given* the system requires or produces `outputs.entities[].indexes[].name`,  
*When* the index name value is empty,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_INDEXES_NAME_EMPTY`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_INDEXES_NAME_EMPTY  
**Reference:** outputs.entities[].indexes[].name  

**6.2.2.103 Index Name Not Unique**  
*Given* the system requires or produces `outputs.entities[].indexes[].name`,  
*When* the index name is not unique within the entity,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_INDEXES_NAME_NOT_UNIQUE`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_INDEXES_NAME_NOT_UNIQUE  
**Reference:** outputs.entities[].indexes[].name  

**6.2.2.104 Index Name Missing When Indexes Exist**  
*Given* the system requires or produces `outputs.entities[].indexes[].name`,  
*When* the index name is missing while indexes exist,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_INDEXES_NAME_MISSING_WHEN_INDEXES_EXIST`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_INDEXES_NAME_MISSING_WHEN_INDEXES_EXIST  
**Reference:** outputs.entities[].indexes[].name  

**6.2.2.105 Index Columns Unknown**  
*Given* the system requires or produces `outputs.entities[].indexes[].columns[]`,  
*When* the index references columns not in the entity,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_INDEXES_COLUMNS_UNKNOWN`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_INDEXES_COLUMNS_UNKNOWN  
**Reference:** outputs.entities[].indexes[].columns[]  

**6.2.2.106 Index Columns Order Not Deterministic**  
*Given* the system requires or produces `outputs.entities[].indexes[].columns[]`,  
*When* the index columns order is not deterministic,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_INDEXES_COLUMNS_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_INDEXES_COLUMNS_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.entities[].indexes[].columns[]  

**6.2.2.107 Index Columns Missing When Indexes Exist**  
*Given* the system requires or produces `outputs.entities[].indexes[].columns[]`,  
*When* the index columns list is missing while indexes exist,  
*Then* the system must expose error `POST_OUTPUTS_ENTITIES_INDEXES_COLUMNS_MISSING_WHEN_INDEXES_EXIST`.  
**Error Mode:** POST_OUTPUTS_ENTITIES_INDEXES_COLUMNS_MISSING_WHEN_INDEXES_EXIST  
**Reference:** outputs.entities[].indexes[].columns[]  

**6.2.2.108 Enums Incomplete**  
*Given* the system requires or produces `outputs.enums[]`,  
*When* the enums array does not contain all enums defined in ERD,  
*Then* the system must expose error `POST_OUTPUTS_ENUMS_INCOMPLETE`.  
**Error Mode:** POST_OUTPUTS_ENUMS_INCOMPLETE  
**Reference:** outputs.enums[]  

**6.2.2.109 Enums Order Not Deterministic**  
*Given* the system requires or produces `outputs.enums[]`,  
*When* the enums array order is not deterministic by enum name,  
*Then* the system must expose error `POST_OUTPUTS_ENUMS_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENUMS_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.enums[]  

**6.2.2.110 Enum Name Empty**  
*Given* the system requires or produces `outputs.enums[].name`,  
*When* the enum name value is empty,  
*Then* the system must expose error `POST_OUTPUTS_ENUMS_NAME_EMPTY`.  
**Error Mode:** POST_OUTPUTS_ENUMS_NAME_EMPTY  
**Reference:** outputs.enums[].name  

**6.2.2.111 Enum Name Mismatch With ERD**  
*Given* the system requires or produces `outputs.enums[].name`,  
*When* the enum name does not match ERD exactly,  
*Then* the system must expose error `POST_OUTPUTS_ENUMS_NAME_MISMATCH_WITH_ERD`.  
**Error Mode:** POST_OUTPUTS_ENUMS_NAME_MISMATCH_WITH_ERD  
**Reference:** outputs.enums[].name  

**6.2.2.112 Enum Name Missing When Enums Exist**  
*Given* the system requires or produces `outputs.enums[].name`,  
*When* the enum name is missing while enums exist,  
*Then* the system must expose error `POST_OUTPUTS_ENUMS_NAME_MISSING_WHEN_ENUMS_EXIST`.  
**Error Mode:** POST_OUTPUTS_ENUMS_NAME_MISSING_WHEN_ENUMS_EXIST  
**Reference:** outputs.enums[].name  

**6.2.2.113 Enum Values Empty**  
*Given* the system requires or produces `outputs.enums[].values[]`,  
*When* the enum values list is empty,  
*Then* the system must expose error `POST_OUTPUTS_ENUMS_VALUES_EMPTY`.  
**Error Mode:** POST_OUTPUTS_ENUMS_VALUES_EMPTY  
**Reference:** outputs.enums[].values[]  

**6.2.2.114 Enum Values Mismatch With ERD**  
*Given* the system requires or produces `outputs.enums[].values[]`,  
*When* the enum values do not match ERD exactly,  
*Then* the system must expose error `POST_OUTPUTS_ENUMS_VALUES_MISMATCH_WITH_ERD`.  
**Error Mode:** POST_OUTPUTS_ENUMS_VALUES_MISMATCH_WITH_ERD  
**Reference:** outputs.enums[].values[]  

**6.2.2.115 Enum Values Order Not Deterministic**  
*Given* the system requires or produces `outputs.enums[].values[]`,  
*When* the enum values order is not deterministic,  
*Then* the system must expose error `POST_OUTPUTS_ENUMS_VALUES_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_ENUMS_VALUES_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.enums[].values[]  

**6.2.2.116 Enum Values Missing When Enums Exist**  
*Given* the system requires or produces `outputs.enums[].values[]`,  
*When* the enum values list is missing while enums exist,  
*Then* the system must expose error `POST_OUTPUTS_ENUMS_VALUES_MISSING_WHEN_ENUMS_EXIST`.  
**Error Mode:** POST_OUTPUTS_ENUMS_VALUES_MISSING_WHEN_ENUMS_EXIST  
**Reference:** outputs.enums[].values[]  

**6.2.2.117 Encrypted Fields Incomplete**  
*Given* the system requires or produces `outputs.encrypted_fields[]`,  
*When* the encrypted fields list does not include every encrypted field from ERD,  
*Then* the system must expose error `POST_OUTPUTS_ENCRYPTED_FIELDS_INCOMPLETE`.  
**Error Mode:** POST_OUTPUTS_ENCRYPTED_FIELDS_INCOMPLETE  
**Reference:** outputs.encrypted_fields[]  

**6.2.2.118 Encrypted Fields Values Not Unique**  
*Given* the system requires or produces `outputs.encrypted_fields[]`,  
*When* the encrypted fields list contains duplicate values,  
*Then* the system must expose error `POST_OUTPUTS_ENCRYPTED_FIELDS_VALUES_NOT_UNIQUE`.  
**Error Mode:** POST_OUTPUTS_ENCRYPTED_FIELDS_VALUES_NOT_UNIQUE  
**Reference:** outputs.encrypted_fields[]  

**6.2.2.119 Encrypted Fields Present When ERD None**  
*Given* the system requires or produces `outputs.encrypted_fields[]`,  
*When* encrypted fields are listed when ERD marks none as encrypted,  
*Then* the system must expose error `POST_OUTPUTS_ENCRYPTED_FIELDS_PRESENT_WHEN_ERD_NONE`.  
**Error Mode:** POST_OUTPUTS_ENCRYPTED_FIELDS_PRESENT_WHEN_ERD_NONE  
**Reference:** outputs.encrypted_fields[]  

**6.2.2.120 Constraints Applied Incomplete**  
*Given* the system requires or produces `outputs.constraints_applied[]`,  
*When* the constraints list does not include all constraints defined in ERD,  
*Then* the system must expose error `POST_OUTPUTS_CONSTRAINTS_APPLIED_INCOMPLETE`.  
**Error Mode:** POST_OUTPUTS_CONSTRAINTS_APPLIED_INCOMPLETE  
**Reference:** outputs.constraints_applied[]  

**6.2.2.121 Constraints Applied Value Empty**  
*Given* the system requires or produces `outputs.constraints_applied[]`,  
*When* the constraints list contains an empty identifier,  
*Then* the system must expose error `POST_OUTPUTS_CONSTRAINTS_APPLIED_VALUE_EMPTY`.  
**Error Mode:** POST_OUTPUTS_CONSTRAINTS_APPLIED_VALUE_EMPTY  
**Reference:** outputs.constraints_applied[]  

**6.2.2.122 Constraints Applied Values Not Unique**  
*Given* the system requires or produces `outputs.constraints_applied[]`,  
*When* the constraints list contains duplicate identifiers,  
*Then* the system must expose error `POST_OUTPUTS_CONSTRAINTS_APPLIED_VALUES_NOT_UNIQUE`.  
**Error Mode:** POST_OUTPUTS_CONSTRAINTS_APPLIED_VALUES_NOT_UNIQUE  
**Reference:** outputs.constraints_applied[]  

**6.2.2.123 Constraints Applied Order Not Deterministic**  
*Given* the system requires or produces `outputs.constraints_applied[]`,  
*When* the constraints list order is not deterministic,  
*Then* the system must expose error `POST_OUTPUTS_CONSTRAINTS_APPLIED_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_CONSTRAINTS_APPLIED_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.constraints_applied[]  

**6.2.2.124 Migration Journal Empty**  
*Given* the system requires or produces `outputs.migration_journal[]`,  
*When* the migration journal exists but contains no entries,  
*Then* the system must expose error `POST_OUTPUTS_MIGRATION_JOURNAL_EMPTY`.  
**Error Mode:** POST_OUTPUTS_MIGRATION_JOURNAL_EMPTY  
**Reference:** outputs.migration_journal[]  

**6.2.2.125 Migration Journal Order Not Deterministic**  
*Given* the system requires or produces `outputs.migration_journal[]`,  
*When* the migration journal order is not deterministic by sequence,  
*Then* the system must expose error `POST_OUTPUTS_MIGRATION_JOURNAL_ORDER_NOT_DETERMINISTIC`.  
**Error Mode:** POST_OUTPUTS_MIGRATION_JOURNAL_ORDER_NOT_DETERMINISTIC  
**Reference:** outputs.migration_journal[]  

**6.2.2.126 Migration Journal Missing Required Fields**  
*Given* the system requires or produces `outputs.migration_journal[]`,  
*When* journal entries do not include both filename and applied_at,  
*Then* the system must expose error `POST_OUTPUTS_MIGRATION_JOURNAL_MISSING_REQUIRED_FIELDS`.  
**Error Mode:** POST_OUTPUTS_MIGRATION_JOURNAL_MISSING_REQUIRED_FIELDS  
**Reference:** outputs.migration_journal[]  

**6.2.2.127 Migration Journal Filename Invalid Path**  
*Given* the system requires or produces `outputs.migration_journal[].filename`,  
*When* the migration journal filename is not a valid project-relative path,  
*Then* the system must expose error `POST_OUTPUTS_MIGRATION_JOURNAL_FILENAME_INVALID_PATH`.  
**Error Mode:** POST_OUTPUTS_MIGRATION_JOURNAL_FILENAME_INVALID_PATH  
**Reference:** outputs.migration_journal[].filename  

**6.2.2.128 Migration Journal Filename Not Unique**  
*Given* the system requires or produces `outputs.migration_journal[].filename`,  
*When* the migration journal filename is not unique within the journal,  
*Then* the system must expose error `POST_OUTPUTS_MIGRATION_JOURNAL_FILENAME_NOT_UNIQUE`.  
**Error Mode:** POST_OUTPUTS_MIGRATION_JOURNAL_FILENAME_NOT_UNIQUE  
**Reference:** outputs.migration_journal[].filename  

**6.2.2.129 Migration Journal Filename Missing When Journal Exists**  
*Given* the system requires or produces `outputs.migration_journal[].filename`,  
*When* the migration journal filename is missing while journal exists,  
*Then* the system must expose error `POST_OUTPUTS_MIGRATION_JOURNAL_FILENAME_MISSING_WHEN_JOURNAL_EXISTS`.  
**Error Mode:** POST_OUTPUTS_MIGRATION_JOURNAL_FILENAME_MISSING_WHEN_JOURNAL_EXISTS  
**Reference:** outputs.migration_journal[].filename  

**6.2.2.130 Migration Journal Applied At Invalid Format**  
*Given* the system requires or produces `outputs.migration_journal[].applied_at`,  
*When* the migration journal timestamp is not ISO 8601 UTC,  
*Then* the system must expose error `POST_OUTPUTS_MIGRATION_JOURNAL_APPLIED_AT_INVALID_FORMAT`.  
**Error Mode:** POST_OUTPUTS_MIGRATION_JOURNAL_APPLIED_AT_INVALID_FORMAT  
**Reference:** outputs.migration_journal[].applied_at  

**6.2.2.131 Migration Journal Applied At Non Monotonic**  
*Given* the system requires or produces `outputs.migration_journal[].applied_at`,  
*When* the migration journal timestamps are not non-decreasing,  
*Then* the system must expose error `POST_OUTPUTS_MIGRATION_JOURNAL_APPLIED_AT_NON_MONOTONIC`.  
**Error Mode:** POST_OUTPUTS_MIGRATION_JOURNAL_APPLIED_AT_NON_MONOTONIC  
**Reference:** outputs.migration_journal[].applied_at  

**6.2.2.132 Migration Journal Applied At Missing When Journal Exists**  
*Given* the system requires or produces `outputs.migration_journal[].applied_at`,  
*When* the migration journal timestamp is missing while journal exists,  
*Then* the system must expose error `POST_OUTPUTS_MIGRATION_JOURNAL_APPLIED_AT_MISSING_WHEN_JOURNAL_EXISTS`.  
**Error Mode:** POST_OUTPUTS_MIGRATION_JOURNAL_APPLIED_AT_MISSING_WHEN_JOURNAL_EXISTS  
**Reference:** outputs.migration_journal[].applied_at

## 6.3 Happy Path Behavioural Acceptance Criteria

6.3.1.1 Migration Initiates Schema Creation
Given the migration runner starts,
When migrations are executed,
Then the system must initiate table creation as the first step in schema setup.
Reference: E1; STEP-3

6.3.1.2 Constraint Creation Follows Table Creation
Given all tables are created,
When migration execution continues,
Then the system must initiate creation of primary keys, foreign keys, unique constraints, and indexes.
Reference: E2; STEP-3

6.3.1.3 Encryption Application Follows Constraint Creation
Given constraints are applied,
When sensitive fields are detected,
Then the system must initiate encryption on those fields during the same migration flow.
Reference: E3, S3; STEP-3

6.3.1.4 TLS Enforcement Follows Database Connection Request
Given a database connection is initiated,
When TLS enforcement is configured,
Then the system must establish a TLS session before any subsequent operations proceed.
Reference: E4, S2; STEP-3

6.3.1.5 Row Validation Follows Connection Establishment
Given a TLS-secured database session is established,
When a row insert is attempted,
Then the system must validate row values against the declared schema before insertion proceeds.
Reference: E5; STEP-3

**6.3.1.6 Direct Lookup Follows Row Validation**
Given row insertion has passed schema validation,
When placeholder sourcing is required,
Then the system must perform a **direct lookup** by `QuestionnaireQuestion.placeholder_code` (unique when present).
Reference: E6; STEP-3

**6.3.1.7 Placeholder Resolution Follows Direct Lookup**
Given direct lookup completes successfully,
When placeholder resolution is required,
Then the system must return the resolved values to the requesting component.
Reference: E7; STEP-3

6.3.1.8 Rollback Follows Migration Failure
Given a migration encounters an execution failure,
When rollback is invoked,
Then the system must initiate reverse execution of the corresponding rollback scripts.
Reference: E8; STEP-3

6.3.1.9 Deterministic State Ensured After Step Completion
Given any migration step completes,
When the same step is repeated with identical inputs,
Then the system must maintain deterministic results for that operation before proceeding to the next step.
Reference: S4; STEP-3

**6.3.1.10 *(Reserved)***
*(This numbering is reserved; no behavioural step is defined here in this epic.)*

6.3.1.11 New Template Introduction Triggers Schema Reuse
Given a new template is introduced,
When the template is registered,
Then the system must proceed without initiating schema changes, reusing the existing schema structure.
Reference: O1; STEP-4

6.3.1.12 New Policy Introduction Triggers Schema Reuse
Given a new policy is introduced,
When the policy is registered,
Then the system must proceed without initiating schema changes, reusing the existing schema structure.
Reference: O2; STEP-4

### 6.3.2 Sad Path Behavioural Acceptance Criteria

#### **6.3.2.1**

**Title:** Migration execution halts on error
**Criterion:**
*Given* a migration is being executed, *when* a migration execution error occurs, *then* halt the migration step and stop propagation to constraint creation.
**Error Mode:** RUN\_MIGRATION\_EXECUTION\_ERROR
**Reference:** step: migrations/001\_init.sql

---

#### **6.3.2.2**

**Title:** Constraint creation halts on error
**Criterion:**
*Given* constraints are being created, *when* a constraint creation error occurs, *then* halt constraint creation and stop propagation to index creation.
**Error Mode:** RUN\_CONSTRAINT\_CREATION\_ERROR
**Reference:** step: migrations/002\_constraints.sql

---

#### **6.3.2.3**

**Title:** Encryption application halts on error
**Criterion:**
*Given* sensitive fields are being encrypted, *when* an encryption application error occurs, *then* halt encryption application and stop propagation to subsequent migrations.
**Error Mode:** RUN\_ENCRYPTION\_APPLY\_ERROR
**Reference:** step: migrations applying encrypted fields

---

#### **6.3.2.4**

**Title:** Rollback halts on error
**Criterion:**
*Given* a rollback migration is in progress, *when* a rollback error occurs, *then* halt rollback and stop propagation to subsequent rollback steps.
**Error Mode:** RUN\_MIGRATION\_ROLLBACK\_ERROR
**Reference:** step: migrations/004\_rollbacks.sql

---

#### **6.3.2.5**

**Title:** TLS enforcement halts on connection error
**Criterion:**
*Given* a database connection is being established, *when* a TLS connection error occurs, *then* halt connection initiation and stop propagation to row insertion.
**Error Mode:** RUN\_TLS\_CONNECTION\_ERROR
**Reference:** step: config/database.ssl.required

---

#### **6.3.2.6**

**Title:** Row insertion halts on schema validation error
**Criterion:**
*Given* a row is being inserted, *when* a row insertion error occurs, *then* halt row insertion and stop propagation to join resolution.
**Error Mode:** RUN\_ROW\_INSERTION\_ERROR
**Reference:** step: Response table insertion

---

#### **6.3.2.7**

**Title:** Join resolution halts on error
**Criterion:**
*Given* placeholder resolution via join is being executed, *when* a join resolution error occurs, *then* halt join resolution and stop propagation to placeholder return.
**Error Mode:** RUN\_JOIN\_RESOLUTION\_ERROR
**Reference:** step: join Response → QuestionToPlaceholder → TemplatePlaceholder

---

#### **6.3.2.8**

**Title:** Field access halts on invalid encryption key
**Criterion:**
*Given* an encrypted field is being accessed, *when* an invalid encryption key error occurs, *then* halt field access and stop propagation to response retrieval.
**Error Mode:** RUN\_INVALID\_ENCRYPTION\_KEY
**Reference:** step: sensitive fields with encryption

---

#### **6.3.2.9**

**Title:** TLS enforcement halts when materials unavailable
**Criterion:**
*Given* a database connection is being established, *when* required TLS materials are unavailable, *then* halt TLS enforcement and stop propagation to query execution.
**Error Mode:** RUN\_TLS\_MATERIALS\_UNAVAILABLE
**Reference:** step: truststore/ca\_bundle.pem

---

#### **6.3.2.10**

**Title:** Row insertion halts on unsupported data type
**Criterion:**
*Given* a row is being validated, *when* an unsupported data type error occurs, *then* halt row insertion and stop propagation to subsequent processing.
**Error Mode:** RUN\_UNSUPPORTED\_DATA\_TYPE
**Reference:** step: Response.value\_json

---

#### **6.3.2.11**

**Title:** Migration halts on out-of-order execution
**Criterion:**
*Given* migrations are being executed, *when* an out-of-order migration error occurs, *then* halt migration execution and stop propagation to subsequent migrations.
**Error Mode:** RUN\_MIGRATION\_OUT\_OF\_ORDER
**Reference:** step: migrations (001\_init.sql, 002\_constraints.sql, 003\_indexes.sql, 004\_rollbacks.sql)

---

#### **6.3.2.12**

**Title:** Processing halts on unidentified runtime error
**Criterion:**
*Given* a runtime operation is in progress, *when* an unidentified runtime error occurs, *then* halt the current step and stop propagation to downstream steps.
**Error Mode:** RUN\_UNIDENTIFIED\_ERROR
**Reference:** step: any E1–E8, S1–S4

6.3.2.13

Title: Database halts on connectivity failure
Criterion: Given a migration is in progress, when a database connectivity error occurs, then halt database operations and stop propagation to row insertion.
Error Mode: ENV_DATABASE_UNAVAILABLE
Reference: dependency: database; Step: STEP-3

6.3.2.14

Title: Database halts on permission failure
Criterion: Given a database session is being established, when a database permission error occurs, then halt session creation and stop propagation to schema creation.
Error Mode: ENV_DATABASE_PERMISSION_DENIED
Reference: dependency: database; Step: STEP-3

6.3.2.15

Title: TLS connection halts on certificate failure
Criterion: Given a database TLS handshake is initiated, when certificate validation fails, then halt connection establishment and stop propagation to row insertion.
Error Mode: ENV_TLS_CERTIFICATE_INVALID
Reference: dependency: TLS materials; Step: STEP-3

6.3.2.16

Title: Disk operations halt on space exhaustion
Criterion: Given schema migration requires local writes, when disk space is exhausted, then halt local file writes and stop propagation to migration journal updates.
Error Mode: ENV_DISK_SPACE_EXHAUSTED
Reference: dependency: filesystem/disk; Step: STEP-3

6.3.2.17

Title: Temp directory halts on unavailability
Criterion: Given temporary storage is required for migration, when the temp directory is unavailable, then halt intermediate write operations and stop propagation to placeholder resolution.
Error Mode: ENV_TEMP_DIR_UNAVAILABLE
Reference: dependency: filesystem/temp; Step: STEP-3

6.3.2.18

Title: KMS halts on encryption key failure
Criterion: Given encrypted fields are being accessed, when KMS is unavailable or misconfigured, then halt encryption operations and stop propagation to response retrieval.
Error Mode: ENV_KMS_UNAVAILABLE
Reference: dependency: key management service; Step: STEP-3

6.3.2.19

Title: System halts on clock synchronisation failure
Criterion: Given timestamps are required for migration journal, when system clock synchronisation fails, then halt timestamp assignment and stop propagation to journal persistence.
Error Mode: ENV_CLOCK_UNSYNCHRONISED
Reference: dependency: system clock; Step: STEP-3

6.3.2.20

Title: Migration halts on config file unavailability
Criterion: Given configuration is required for migrations, when the database configuration file is unavailable, then halt migration execution and stop propagation to constraint creation.
Error Mode: ENV_CONFIG_FILE_UNAVAILABLE
Reference: dependency: runtime config; Step: STEP-3

7.1.1 — Entities Declared with Canonical Names
**Title:** ERD entities are declared and uniquely named
**Purpose:** Verify every database entity is declared with a unique canonical name that exactly matches the ERD.&#x20;
**Test Data:** `./docs/erd_spec.json`
**Mocking:** None — static inspection of committed artefact.
**Assertions:**

* File exists and parses as JSON.
* `entities[*].name` exists for all entities.
* All names are non-empty strings.
* All names are unique (no duplicates).
  **AC-Ref:** 6.1.1

7.1.2 — Per-Entity Field List Is Explicit
**Title:** Entities declare explicit field collections
**Purpose:** Verify each entity declares `fields[]` with `name` and `type`.
**Test Data:** `./docs/erd_spec.json`
**Mocking:** None.
**Assertions:**

* For every `entities[*]`, `fields` is an array.
* Each `fields[*]` has non-empty `name` and `type`.
  **AC-Ref:** 6.1.2

7.1.3 — No Duplicate Field Names Within an Entity
**Title:** Entity field names are unique per entity
**Purpose:** Ensure no entity contains duplicate field names.
**Test Data:** `./docs/erd_spec.json`
**Mocking:** None.
**Assertions:**

* For each entity, set of `fields[*].name` has no duplicates.
  **AC-Ref:** 6.1.3

7.1.4 — Field Types Align With ERD
**Title:** Migration column types match ERD types
**Purpose:** Validate migration DDL types correspond to ERD-declared types.
**Test Data:** `./docs/erd_spec.json`, `./migrations/001_init.sql`
**Mocking:** None.
**Assertions:**

* For each entity/field in ERD, corresponding `CREATE TABLE` column exists in `001_init.sql`.
* Column type token matches ERD `fields[*].type` (e.g., `uuid`, `text`, `jsonb`, enum name).
  **AC-Ref:** 6.1.4

7.1.5 — Encryption Flag Present Where Required
**Title:** Sensitive fields include `encrypted` boolean
**Purpose:** Confirm fields marked sensitive are flagged with `encrypted: true`.
**Test Data:** `./docs/erd_spec.json`
**Mocking:** None.
**Assertions:**

* For each sensitive field in ERD, `encrypted` key exists and is boolean.
* Sensitive fields have `encrypted: true`; non-sensitive fields either omit or set `false`.
  **AC-Ref:** 6.1.5

7.1.6 — Primary Key Columns Listed Structurally
**Title:** Entities declare `primary_key.columns[]`
**Purpose:** Ensure entities with PKs list their key columns structurally.
**Test Data:** `./docs/erd_spec.json`
**Mocking:** None.
**Assertions:**

* Where ERD defines a PK, `primary_key.columns` array exists and is non-empty.
* Each listed column exists in `fields[*].name`.
  **AC-Ref:** 6.1.6

7.1.7 — Foreign Keys Modelled With Names, Columns, and References
**Title:** FKs are fully modelled in ERD and DDL
**Purpose:** Verify FK objects have `name`, `columns[]`, `references.entity`, `references.columns[]`, and appear in DDL.
**Test Data:** `./docs/erd_spec.json`, `./migrations/002_constraints.sql`
**Mocking:** None.
**Assertions:**

* ERD FK objects include required properties.
* `002_constraints.sql` contains matching `FOREIGN KEY` definitions for each ERD FK.
  **AC-Ref:** 6.1.7

7.1.8 — Unique Constraints Declared With Name and Columns
**Title:** Unique constraints defined and complete
**Purpose:** Ensure uniques are declared with `name` and `columns[]`, and present in DDL.
**Test Data:** `./docs/erd_spec.json`, `./migrations/002_constraints.sql`
**Mocking:** None.
**Assertions:**

* ERD unique constraints include `name` and non-empty `columns[]`.
* Matching `UNIQUE` constraints exist in `002_constraints.sql`.
  **AC-Ref:** 6.1.8

7.1.9 — Secondary Indexes Declared With Name and Columns
**Title:** Indexes are declared and present
**Purpose:** Validate indexes have `name` and `columns[]` and are created by migrations.
**Test Data:** `./docs/erd_spec.json`, `./migrations/003_indexes.sql`
**Mocking:** None.
**Assertions:**

* ERD index entries include `name` and non-empty `columns[]`.
* Matching `CREATE INDEX` statements exist in `003_indexes.sql`.
  **AC-Ref:** 6.1.9

7.1.10 — Enumerations Declared Centrally
**Title:** Enums are centralised with names and values
**Purpose:** Confirm enums exist centrally with names and values.
**Test Data:** `./docs/erd_spec.json`, `./migrations/001_init.sql`
**Mocking:** None.
**Assertions:**

* ERD includes `enums[]` with `name` and `values[]`.
* `001_init.sql` defines corresponding enum types and values.
  **AC-Ref:** 6.1.10

7.1.11 — Global Encrypted Field Manifest Exists
**Title:** Encrypted fields manifest is present
**Purpose:** Verify a global list of encrypted fields using `Entity.field` notation exists.
**Test Data:** `./docs/erd_spec.json`
**Mocking:** None.
**Assertions:**

* ERD (or associated output schema section) contains `encrypted_fields[]` array of strings `Entity.field`.
* Every encrypted field in entities appears in this manifest exactly once.
  **AC-Ref:** 6.1.11

7.1.12 — Global Constraint Manifest Exists
**Title:** Global constraints manifest is present
**Purpose:** Ensure `constraints_applied[]` enumerates all applied PK/FK/UNIQUE/CHECK identifiers.
**Test Data:** `./docs/erd_spec.json`
**Mocking:** None.
**Assertions:**

* A `constraints_applied[]` array exists and lists all constraints named in ERD/migrations.
  **AC-Ref:** 6.1.12

7.1.13 — Migration Journal Structure is Stable
**Title:** Migration journal entries contain filename and timestamp
**Purpose:** Validate journal entry structure for stability.
**Test Data:** Project artefact storing the migration journal (e.g., `./migrations/_journal.json` or runner output persisted under project root)
**Mocking:** None — fail if journal artefact not present.
**Assertions:**

* Journal file exists and parses (JSON/CSV/YAML as implemented).
* Each entry includes `filename` (project-relative) and `applied_at` (ISO-8601 UTC).
  **AC-Ref:** 6.1.13

7.1.14 — Deterministic Ordering of Collections
**Title:** Collections define and apply a deterministic order
**Purpose:** Check ERD or schema generator declares deterministic keys for ordering (e.g., by name) and applies them in parity exports.
**Test Data:** `./docs/erd_spec.json`, `./docs/erd_relationships.csv`, `./docs/erd_mermaid.md`
**Mocking:** None.
**Assertions:**

* ERD/exports list entities/fields/constraints/indexes in deterministic sorted order by their canonical names.
  **AC-Ref:** 6.1.14

REPLACE 7.1.15 with this

7.1.15 — Placeholder Lookup Artefacts Are Present
Title: Direct lookup artefacts exist for placeholder resolution
Purpose: Ensure the schema supports placeholder resolution by direct lookup on questions (no template/mapping join path).
Test Data: ./docs/erd_spec.json, ./migrations/001_init.sql, ./migrations/002_constraints.sql
Mocking: None.
Assertions:

ERD includes QuestionnaireQuestion with optional placeholder_code in fields[*].name.

002_constraints.sql defines a partial unique on QuestionnaireQuestion(placeholder_code) where placeholder_code IS NOT NULL.

No entities named TemplatePlaceholder or QuestionToPlaceholder appear in ERD or migrations.
AC-Ref: 6.1.15

EDIT 7.1.16 (adjust the second rule only)

7.1.16 — Constraint Rules Enforced Structurally
Title: Structural constraints encode response and placeholder rules
Purpose: Verify structural uniqueness rules exist for “one response per question per submission” and “no duplicate placeholders”.
Test Data: ./docs/erd_spec.json, ./migrations/002_constraints.sql
Mocking: None.
Assertions:

ERD defines a composite unique on Response(response_set_id, question_id).

002_constraints.sql contains a matching UNIQUE definition (or equivalent) for one-response-per-question-per-submission.

ERD/migrations encode no duplicate placeholders via a partial unique on QuestionnaireQuestion(placeholder_code) where placeholder_code IS NOT NULL.
AC-Ref: 6.1.16

7.1.17 — TLS Requirement Exposed as Configuration
**Title:** TLS enforcement flag is available in configuration
**Purpose:** Ensure a boolean configuration exists to enforce TLS for DB connections.
**Test Data:** `./config/database.ssl.required` (or config file that declares this key)
**Mocking:** None — static config presence.
**Assertions:**

* Configuration file/key exists and is boolean.
  **AC-Ref:** 6.1.17

7.1.18 — Column-Level Encryption is Configurable
**Title:** Encryption mode and KMS alias are configurable
**Purpose:** Verify presence of `config/encryption.mode` and, when needed, `config/kms.key_alias`.
**Test Data:** `./config/encryption.mode`, `./config/kms.key_alias`
**Mocking:** None.
**Assertions:**

* Encryption mode key exists with allowed value (`tde`, `column`, `tde+column`).
* If mode includes `column`, key alias file/key exists and is non-empty.
  **AC-Ref:** 6.1.18

7.1.19 — ERD Sources Versioned as Project Artefacts
**Title:** ERD JSON and parity docs exist under `./docs`
**Purpose:** Ensure normative ERD JSON and human-readable parity docs are committed.
**Test Data:** `./docs/erd_spec.json`, `./docs/erd_mermaid.md`, `./docs/erd_relationships.csv`
**Mocking:** None.
**Assertions:**

* All three files exist and are readable.
  **AC-Ref:** 6.1.19

7.1.20 — Rollback Scripts Present and Ordered
**Title:** Rollback SQL present and reverses prior migrations
**Purpose:** Verify rollback scripts exist and reverse objects in strict reverse order.
**Test Data:** `./migrations/004_rollbacks.sql`, prior migration files under `./migrations`
**Mocking:** None.
**Assertions:**

* `004_rollbacks.sql` exists and contains `DROP …` for objects created in `001–003` in reverse sequence.
  **AC-Ref:** 6.1.20

7.1.21 — Generated Document Storage is Modelled
**Title:** Generated document structure with identifier and URI
**Purpose:** Ensure model contains entity/fields for generated documents (id + `output_uri`).
**Test Data:** `./docs/erd_spec.json`, `./migrations/001_init.sql`
**Mocking:** None.
**Assertions:**

* ERD includes generated document entity with stable id and `output_uri` field.
* `001_init.sql` creates corresponding table/columns.
  **AC-Ref:** 6.1.21


7.1.24 — Deterministic Lookup Contracts Are Encoded in Keys
Title: Keys/indexes guarantee deterministic placeholder lookup
Purpose: Ensure keys/indexes required for deterministic lookups are declared.
Test Data: ./docs/erd_spec.json, ./migrations/002_constraints.sql, ./migrations/003_indexes.sql
Mocking: None.
Assertions:

002_constraints.sql defines a partial unique index/constraint on QuestionnaireQuestion(placeholder_code) where not null (single source of truth per code).

003_indexes.sql includes supporting indexes for primary lookup paths (e.g., Response(response_set_id), Response(question_id)), ensuring stable, repeatable resolution.
AC-Ref: 6.1.24

7.1.25 — Encryption at Rest Policy is Traceable to Columns
**Title:** Encrypted fields trace to global manifest
**Purpose:** Check every field marked `encrypted: true` appears once in the global `encrypted_fields[]` list.
**Test Data:** `./docs/erd_spec.json`
**Mocking:** None.
**Assertions:**

* Build `Entity.field` set from entities with `encrypted: true`.
* Compare equality with `encrypted_fields[]`.
  **AC-Ref:** 6.1.25

7.1.26 — Constraint/Index Definitions Live With Schema, Not Code
**Title:** All PK/FK/UNIQUE/CHECK/INDEX definitions are in migrations
**Purpose:** Ensure constraints/indexes are declared in SQL migrations rather than application code directories.
**Test Data:** `./migrations/001_init.sql`, `./migrations/002_constraints.sql`, `./migrations/003_indexes.sql`, application source directories (as present)
**Mocking:** None.
**Assertions:**

* Constraints and indexes are present in SQL files.
* Grep application source for DDL tokens (`CREATE TABLE`, `ALTER TABLE`, `CREATE INDEX`, `CONSTRAINT`) — none should appear outside `./migrations`.
  **AC-Ref:** 6.1.26

7.1.27 — Placeholder Uniqueness Encoded as a Constraint
Title: Placeholder code uniqueness enforced via partial unique on questions
Purpose: Verify uniqueness of placeholder codes is enforced on questions (no template/version scope).
Test Data: ./docs/erd_spec.json, ./migrations/002_constraints.sql
Mocking: None.
Assertions:

ERD defines a partial unique on QuestionnaireQuestion(placeholder_code) (non-null values only).

002_constraints.sql contains the corresponding CREATE UNIQUE INDEX … WHERE placeholder_code IS NOT NULL (or equivalent constraint).
AC-Ref: 6.1.27

7.1.28 — One-Response-Per-Question-Per-Submission Encoded as a Constraint
**Title:** Response uniqueness enforced structurally
**Purpose:** Ensure composite unique constraint exists for (submission, question).
**Test Data:** `./docs/erd_spec.json`, `./migrations/002_constraints.sql`
**Mocking:** None.
**Assertions:**

* ERD defines composite unique on response table keys.
* `002_constraints.sql` contains matching `UNIQUE` statement.
  **AC-Ref:** 6.1.28

7.1.29 — Deterministic Export Parity With ERD
**Title:** ERD parity exports structurally correspond to ERD spec
**Purpose:** Validate Mermaid and relationships CSV mirror ERD entities and relationships.
**Test Data:** `./docs/erd_spec.json`, `./docs/erd_mermaid.md`, `./docs/erd_relationships.csv`
**Mocking:** None.
**Assertions:**

* Every ERD entity appears in Mermaid and CSV.
* Every ERD relationship (FK) appears in CSV rows and Mermaid edges.
* No extra entities/relationships appear in exports beyond ERD.
  **AC-Ref:** 6.1.29

## 7.2.1 Happy path contractual tests

**7.2.1.1 — Entities are persisted with canonical names**
Title: `outputs.entities[].name` reflects ERD entity canonical names
Purpose: Verify that migrated entities are emitted with canonical names exactly as defined.
Test Data:

* ERD entities (subset sufficient for test): `["Company","QuestionnaireQuestion","AnswerOption","ResponseSet","Response","GeneratedDocument","FieldGroup","QuestionToFieldGroup","GroupValue"]`
* Invocation: run migrations from a clean database, then request the Section 4 outputs snapshot.
  Mocking: None — the test validates real migration output and schema export; mocking would invalidate the structural guarantee.
  Assertions:
* `outputs.entities[].name` must contain **all** names above, exactly once each (set-equality).
* Order must be deterministically ascending by name.
* No extra names appear.
  AC-Ref: 6.2.1.1
  EARS-Refs: U1, U2, U8, E1

---

**7.2.1.2 — Entity fields are exposed with declared types**
Title: `outputs.entities[].fields[]` includes field `name` and `type` for each entity
Purpose: Verify that fields for a chosen entity are exposed with canonical names and SQL types.
Test Data:

* Choose entity: `Response`
* ERD expected fields/types (excerpt):

  * `response_id: uuid`, `response_set_id: uuid`, `question_id: uuid`, `value_json: jsonb`
    Mocking: None — structural.
    Assertions:
* In `outputs.entities[?name=="Response"].fields[]`, assert presence of the above names with exact `type` values shown.
* No extra fields beyond ERD for `Response`.
* Field list order is deterministic ascending by field name.
  AC-Ref: 6.2.1.2
  EARS-Refs: U2, E1

---

**7.2.1.3 — Primary key is externally declared**
Title: `outputs.entities[].primary_key.columns[]` lists the PK for entities that have one
Purpose: Verify presence and correctness of PK columns list.
Test Data:

* Entity: `Response`
* ERD PK: `["response_id"]`
  Mocking: None — structural.
  Assertions:
* `outputs.entities[?name=="Response"].primary_key.columns` equals exactly `["response_id"]`.
* List is non-empty and deterministic.
  AC-Ref: 6.2.1.3
  EARS-Refs: U3, E2

---

**7.2.1.4 — Foreign key constraints are present**
Title: `outputs.entities[].foreign_keys[]` lists FK name, columns, and referenced entity/columns
Purpose: Verify FK exposure for link from `Response` to `ResponseSet`.
Test Data:

* Expected FK on `Response`:

  * `name: "fk_response_set"`
  * `columns: ["response_set_id"]`
  * `references.entity: "ResponseSet"`
  * `references.columns: ["response_set_id"]`
    Mocking: None — structural.
    Assertions:
* An entry exactly matching the above exists under `Response.foreign_keys[]`.
* No duplicate FK names within `Response`.
  AC-Ref: 6.2.1.4
  EARS-Refs: U3, E2

---

**7.2.1.5 — Unique constraints are present**
Title: `outputs.entities[].unique_constraints[]` lists unique constraint name and columns
Purpose: Verify uniqueness rule for “one response per question per submission.”
Test Data:

* Entity: `Response`
* Expected UNIQUE: `name: "uq_response_set_question"`, `columns: ["response_set_id","question_id"]`
  Mocking: None — structural.
  Assertions:
* The unique constraint exists exactly with the given name and column set.
* No other uniques conflict with the rule.
  AC-Ref: 6.2.1.5
  EARS-Refs: N2, E2

---

**7.2.1.6 — Indexes are present**
Title: `outputs.entities[].indexes[]` exposes index name and columns
Purpose: Verify presence of a lookup index for placeholder resolution.
Test Data:

* Entity: `QuestionnaireQuestion`
* Expected index: `name: "uq_question_placeholder_code"`, `columns: ["placeholder_code"]`
  Mocking: None — structural.
  Assertions:
* Index exists with exact name and columns.
* No duplicate index names within the entity.
  AC-Ref: 6.2.1.6
  EARS-Refs: U3, E2, S4

---

**7.2.1.7 — Enums are externally declared**
Title: `outputs.enums[]` exposes enum names and values
Purpose: Verify presence and exact membership for an ERD-defined enum.
Test Data:

* Enum: `answer_kind`
* Expected values: `["boolean","enum_single","long_text","number","short_string"]`
  Mocking: None — structural.
  Assertions:
* `outputs.enums[?name=="answer_kind"].values` equals the array above, in deterministic ascending order.
  AC-Ref: 6.2.1.7
  EARS-Refs: U3, E1

---

**7.2.1.8 — Encrypted fields are explicitly flagged**
Title: Sensitive fields expose `encrypted: true` in field metadata
Purpose: Verify that ERD-marked sensitive fields carry the encryption flag.
Test Data:

* Entity/field samples: `Company.legal_name`, `Company.registered_office_address`, `Response.value_json`, `GeneratedDocument.output_uri`
  Mocking: None — structural.
  Assertions:
* For each listed field, `outputs.entities[?name==Entity].fields[?name==Field].encrypted` is `true`.
* For a non-sensitive field (e.g., `Response.response_id`), `encrypted` is `false` or omitted per schema rules.
  AC-Ref: 6.2.1.8
  EARS-Refs: U10, E3, S3

---

**7.2.1.9 — Global encrypted fields manifest exists**
Title: `outputs.encrypted_fields[]` lists fully-qualified encrypted columns
Purpose: Verify that all sensitive columns appear as `Entity.field`.
Test Data:

* Expect at least:

  * `Company.legal_name`
  * `Company.registered_office_address`
  * `Response.value_json`
  * `GeneratedDocument.output_uri`
    Mocking: None — structural.
    Assertions:
* `outputs.encrypted_fields[]` contains all above entries exactly, with no duplicates.
  AC-Ref: 6.2.1.9
  EARS-Refs: U10, S1, S3

---

**7.2.1.10 — Constraints are listed globally**
Title: `outputs.constraints_applied[]` includes all PK/FK/UNIQUE/CHECK identifiers
Purpose: Verify global constraint manifest is complete.
Test Data:

* Sample required identifiers include:

  * `pk_response`
  * `fk_response_set`
  * `uq_response_set_question`
    Mocking: None — structural.
    Assertions:
* The set includes the above identifiers; ordering is deterministic.
* No duplicate identifiers.
  AC-Ref: 6.2.1.10
  EARS-Refs: U3, E2

---

**7.2.1.11 — Migration journal entries include filenames**
Title: `outputs.migration_journal[].filename` is a valid project-relative path in `./migrations`
Purpose: Verify each applied migration is recorded with a relative path.
Test Data:

* Expected first entries: `migrations/001_init.sql`, `migrations/002_constraints.sql`
  Mocking: None — structural.
  Assertions:
* Journal includes the two filenames above exactly.
* Each `filename` starts with `migrations/` and contains no absolute components.
  AC-Ref: 6.2.1.11
  EARS-Refs: E1, E8

---

**7.2.1.12 — Migration journal entries include timestamps**
Title: `outputs.migration_journal[].applied_at` is ISO-8601 UTC and non-decreasing
Purpose: Verify timestamp presence and format for applied migrations.
Test Data:

* Two sequential journal entries corresponding to 001 and 002.
  Mocking: None — structural.
  Assertions:
* Both entries include `applied_at` in `YYYY-MM-DDThh:mm:ssZ` format.
* `applied_at[001] <= applied_at[002]`.
  AC-Ref: 6.2.1.12
  EARS-Refs: E1, E8, S4

---

**7.2.1.13 — One response per question per submission**
Title: Uniqueness rule is externally visible in outputs for `Response`
Purpose: Verify that the unique constraint projecting the rule is present.
Test Data:

* Expected unique: `uq_response_set_question` on `["response_set_id","question_id"]`.
  Mocking: None — structural.
  Assertions:
* The unique constraint appears exactly as described in `outputs.entities[?name=="Response"].unique_constraints[]`.
  AC-Ref: 6.2.1.13
  EARS-Refs: N2

---

**7.2.1.14 — Duplicate placeholders are rejected via uniqueness**
Title: Placeholder code uniqueness is externally visible
Purpose: Verify placeholder code uniqueness is encoded as a partial unique on questions.
Test Data:

* Entity: `QuestionnaireQuestion`
* Expected unique/index: `uq_question_placeholder_code` on `["placeholder_code"]` (partial: `WHERE placeholder_code IS NOT NULL`)
  Mocking: None — structural.
  Assertions:
* The unique/index exists with exact name and columns under the entity’s outputs.
  AC-Ref: 6.2.1.14
  EARS-Refs: N1

---

**7.2.1.15 — Direct lookup correctly resolves placeholders (structural visibility)**
Title: Direct lookup artefacts for placeholder resolution are present
Purpose: Verify the model exposes direct lookup via `QuestionnaireQuestion.placeholder_code` and does **not** rely on a template/mapping join.
Test Data:

* Entity: `QuestionnaireQuestion`
  Mocking: None — structural.
  Assertions:
* `QuestionnaireQuestion` exists with a `placeholder_code` field.
* Entities named `QuestionToPlaceholder` and `TemplatePlaceholder` do **not** appear in `outputs.entities[]`.
  AC-Ref: 6.2.1.15
  EARS-Refs: E6, S4

---

**7.2.1.16 — TLS enforcement is externally visible (configuration surfaced)**
Title: TLS requirement surfaced as configuration enforced for DB connections
Purpose: Verify presence of configuration enforcing TLS (externally observable through outputs/config projection if present).
Test Data:

* Configuration input: `config/database.ssl.required=true`
  Mocking: None — structural.
  Assertions:
* If the outputs schema includes TLS configuration projection, assert a boolean field reflecting `true`.
  AC-Ref: 6.2.1.16
  EARS-Refs: E4, S2

---

**7.2.1.17 — Deterministic ordering of artefacts**
Title: Deterministic ordering across entities, fields, and journal
Purpose: Verify ordering keys are consistently applied.
Test Data:

* `outputs.entities[].name` — expect ascending by name.
* `outputs.entities[?name=="Response"].fields[].name` — ascending by name.
* `outputs.migration_journal[]` — ascending by sequence / non-decreasing `applied_at`.
  Mocking: None — structural.
  Assertions:
* Entities are strictly ascending by `name`.
* Fields for `Response` strictly ascending by `name`.
* Journal entries strictly non-decreasing by `applied_at`.
  AC-Ref: 6.2.1.17
  EARS-Refs: S4

# 7.2.2 Sad Path Contractual Tests

## 7.2.2.1 — ERD spec file missing or unreadable

**Purpose:** Verify the system surfaces the precise precondition error when the ERD JSON spec cannot be read.

**Test Data:**
CLI: `migrate --erd ./docs/erd_spec.json`
Mocked FS: `./docs/erd_spec.json` → raises `FileNotFoundError("No such file")`

**Mocking:**
Mock `open("./docs/erd_spec.json", "rb")` to raise `FileNotFoundError`. Rationale: exercise the public entrypoint while isolating file I/O at the boundary. Assert `open` called exactly once with the given path and mode. No internal logic is mocked.

**Assertions:**

1. Exit code = 1.
2. JSON error envelope:

   * `status = "error"`
   * `error.code = "PRE_docs_erd_spec_json_MISSING_OR_UNREADABLE"`
   * `error.message` contains `"docs/erd_spec.json"` and `"unreadable"` or `"missing"`.
3. No `outputs` field is present.

**AC-Ref:** 6.2.2.1
**Error Mode:** PRE\_docs\_erd\_spec\_json\_MISSING\_OR\_UNREADABLE

---

## 7.2.2.2 — ERD spec contains invalid JSON

**Purpose:** Ensure invalid JSON is reported with the correct precondition code.

**Test Data:**
CLI: `migrate --erd ./docs/erd_spec.json`
Mocked FS: `./docs/erd_spec.json` → bytes: `b'{"entities": [ invalid, }'`

**Mocking:**
Mock `open(...).read()` to return the invalid payload. No internal parsing mocked.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_docs_erd_spec_json_INVALID_JSON"`
3. `error.message` includes `"JSON"` and a parser position (line/column).
4. No partial `outputs` key.

**AC-Ref:** 6.2.2.2
**Error Mode:** PRE\_docs\_erd\_spec\_json\_INVALID\_JSON

---

## 7.2.2.3 — ERD spec schema mismatch

**Purpose:** Report schema mismatch with the ERD spec contract.

**Test Data:**
CLI: `migrate --erd ./docs/erd_spec.json`
Mocked FS content (valid JSON, wrong shape):

```json
{"entities": [{"table_name":"Response"}]}
```

**Mocking:**
Mock file read to the JSON above. Mock schema validator at boundary to return
`ValidationError("missing properties: name, fields")`.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_docs_erd_spec_json_SCHEMA_MISMATCH"`
3. `error.message` lists missing properties (`name`, `fields`).
4. No `outputs`.

**AC-Ref:** 6.2.2.3
**Error Mode:** PRE\_docs\_erd\_spec\_json\_SCHEMA\_MISMATCH

---

## 7.2.2.4 — Mermaid ERD missing/unreadable

**Purpose:** Surface correct error when Mermaid ERD is missing.

**Test Data:**
CLI: `migrate --mermaid ./docs/erd_mermaid.md`
Mocked FS: `open("./docs/erd_mermaid.md")` → `FileNotFoundError`

**Mocking:**
Mock `open` to raise `FileNotFoundError`. Assert single call with the path.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_docs_erd_mermaid_md_MISSING_OR_UNREADABLE"`
3. Message mentions `docs/erd_mermaid.md`.

**AC-Ref:** 6.2.2.4
**Error Mode:** PRE\_docs\_erd\_mermaid\_md\_MISSING\_OR\_UNREADABLE

---

## 7.2.2.5 — Mermaid ERD not UTF-8

**Purpose:** Non-UTF-8 Mermaid file is rejected with the right code.

**Test Data:**
CLI: `migrate`
Mocked FS bytes: invalid UTF-8 sequence `b"\x80\x81\xfe\xff"`

**Mocking:**
Mock `open(..., "rb").read()` to return invalid bytes. The UTF-8 decoder sits at the boundary.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_docs_erd_mermaid_md_NOT_UTF8_TEXT"`
3. Message mentions `"UTF-8"`.

**AC-Ref:** 6.2.2.5
**Error Mode:** PRE\_docs\_erd\_mermaid\_md\_NOT\_UTF8\_TEXT

---

## 7.2.2.6 — Mermaid ERD invalid syntax

**Purpose:** Invalid Mermaid diagram yields specific error code.

**Test Data:**
Mocked file content:

```
erddia
  A--B
```

**Mocking:**
Mock Mermaid parser function at the boundary to raise `MermaidSyntaxError("Unknown directive erddia")`.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_docs_erd_mermaid_md_INVALID_MERMAID"`
3. Message includes `"Unknown directive"`.

**AC-Ref:** 6.2.2.6
**Error Mode:** PRE\_docs\_erd\_mermaid\_md\_INVALID\_MERMAID

---

## 7.2.2.7 — Relationships CSV missing/unreadable

**Purpose:** Missing relationships CSV reports correct code.

**Test Data:**
Path `./docs/erd_relationships.csv` → `FileNotFoundError`.

**Mocking:**
Mock `open` to raise `FileNotFoundError`.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_docs_erd_relationships_csv_MISSING_OR_UNREADABLE"`
3. Message includes filename.

**AC-Ref:** 6.2.2.7
**Error Mode:** PRE\_docs\_erd\_relationships\_csv\_MISSING\_OR\_UNREADABLE

---

## 7.2.2.8 — Relationships CSV invalid CSV

**Purpose:** Malformed CSV is detected and reported.

**Test Data:**
CSV bytes: `b"from,to,kind\nResponse,QuestionToPlaceholder\n"` (missing third column)

**Mocking:**
Mock CSV reader to raise `csv.Error("expected 3 fields, saw 2")`.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_docs_erd_relationships_csv_INVALID_CSV"`
3. Message shows parser complaint.

**AC-Ref:** 6.2.2.8
**Error Mode:** PRE\_docs\_erd\_relationships\_csv\_INVALID\_CSV

---

## 7.2.2.9 — Relationships CSV header mismatch

**Purpose:** Wrong header names are rejected with the correct code.

**Test Data:**
Header line: `a,b,c` (expected: `from,to,kind`)

**Mocking:**
Mock CSV iterator to yield first row `["a","b","c"]`.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_docs_erd_relationships_csv_HEADER_MISMATCH"`
3. Message includes expected vs actual headers.

**AC-Ref:** 6.2.2.9
**Error Mode:** PRE\_docs\_erd\_relationships\_csv\_HEADER\_MISMATCH

---

## 7.2.2.10 — Init migration missing/unreadable

**Purpose:** Missing 001 migration triggers precise precondition error.

**Test Data:**
Path `./migrations/001_init.sql` → `FileNotFoundError`.

**Mocking:**
Mock `open` to raise `FileNotFoundError`.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_migrations_001_init_sql_MISSING_OR_UNREADABLE"`.

**AC-Ref:** 6.2.2.10
**Error Mode:** PRE\_migrations\_001\_init\_sql\_MISSING\_OR\_UNREADABLE

---

## 7.2.2.11 — Init migration invalid SQL

**Purpose:** Surface invalid SQL syntax in 001 migration.

**Test Data:**
File content: `CREATE TABL Response (id uuid primary key);`

**Mocking:**
Mock SQL parser/runner boundary to raise `SqlSyntaxError("TABL")`.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_migrations_001_init_sql_INVALID_SQL"`
3. Message includes token `"TABL"`.

**AC-Ref:** 6.2.2.11
**Error Mode:** PRE\_migrations\_001\_init\_sql\_INVALID\_SQL

---

## 7.2.2.12 — Init migration execution error

**Purpose:** Execution-time DB error surfaces as precondition execution error for 001.

**Test Data:**
Valid SQL; DB raises `PermissionDenied("CREATE TABLE")`.

**Mocking:**
Mock DB driver `.execute()` to raise `PermissionDenied`.

**Assertions:**

1. Exit code = 1.
2. `error.code = "PRE_migrations_001_init_sql_EXECUTION_ERROR"`
3. Message mentions `CREATE TABLE` privilege.

**AC-Ref:** 6.2.2.12
**Error Mode:** PRE\_migrations\_001\_init\_sql\_EXECUTION\_ERROR

---

## 7.2.2.13 — Constraints migration missing/unreadable

**Purpose:** 002 file missing is handled.

**Test Data:** path: `./migrations/002_constraints.sql` → `FileNotFoundError`.

**Mocking:** `open` raises.

**Assertions:**
`error.code = "PRE_migrations_002_constraints_sql_MISSING_OR_UNREADABLE"`

**AC-Ref:** 6.2.2.13
**Error Mode:** PRE\_migrations\_002\_constraints\_sql\_MISSING\_OR\_UNREADABLE

---

## 7.2.2.14 — Constraints migration invalid SQL

**Purpose:** Detect invalid SQL in 002.

**Test Data:** `ALTER TABE Response ADD PRIMARY KEY (id);`

**Mocking:** SQL executor raises `SqlSyntaxError("TABE")`.

**Assertions:**
`error.code = "PRE_migrations_002_constraints_sql_INVALID_SQL"`

**AC-Ref:** 6.2.2.14
**Error Mode:** PRE\_migrations\_002\_constraints\_sql\_INVALID\_SQL

---

## 7.2.2.15 — Constraints migration execution error

**Purpose:** FK creation fails at runtime with proper code.

**Test Data:** SQL attempts FK to missing table.

**Mocking:** DB `.execute()` raises `ForeignKeyTargetMissing("QuestionToPlaceholder")`.

**Assertions:**
`error.code = "PRE_migrations_002_constraints_sql_EXECUTION_ERROR"`

**AC-Ref:** 6.2.2.15
**Error Mode:** PRE\_migrations\_002\_constraints\_sql\_EXECUTION\_ERROR

---

## 7.2.2.16 — Indexes migration missing/unreadable

**Purpose:** 003 file missing is handled.

**Test Data:** path: `./migrations/003_indexes.sql` → `FileNotFoundError`.

**Mocking:** `open` raises.

**Assertions:**
`error.code = "PRE_migrations_003_indexes_sql_MISSING_OR_UNREADABLE"`

**AC-Ref:** 6.2.2.16
**Error Mode:** PRE\_migrations\_003\_indexes\_sql\_MISSING\_OR\_UNREADABLE

---

## 7.2.2.17 — Indexes migration invalid SQL

**Purpose:** Syntax error in 003 is surfaced.

**Test Data:** `CREATE INDX idx_resp_id ON Response(id);`

**Mocking:** Executor raises `SqlSyntaxError("INDX")`.

**Assertions:**
`error.code = "PRE_migrations_003_indexes_sql_INVALID_SQL"`

**AC-Ref:** 6.2.2.17
**Error Mode:** PRE\_migrations\_003\_indexes\_sql\_INVALID\_SQL

---

## 7.2.2.18 — Indexes migration execution error

**Purpose:** Runtime index creation failure is reported.

**Test Data:** Create index on unknown column `respnse_id`.

**Mocking:** DB raises `UndefinedColumn("respnse_id")`.

**Assertions:**
`error.code = "PRE_migrations_003_indexes_sql_EXECUTION_ERROR"`

**AC-Ref:** 6.2.2.18
**Error Mode:** PRE\_migrations\_003\_indexes\_sql\_EXECUTION\_ERROR

---

## 7.2.2.19 — Rollbacks migration missing/unreadable

**Purpose:** 004 file missing is handled.

**Test Data:** path: `./migrations/004_rollbacks.sql` → `FileNotFoundError`.

**Mocking:** `open` raises.

**Assertions:**
`error.code = "PRE_migrations_004_rollbacks_sql_MISSING_OR_UNREADABLE"`

**AC-Ref:** 6.2.2.19
**Error Mode:** PRE\_migrations\_004\_rollbacks\_sql\_MISSING\_OR\_UNREADABLE

---

## 7.2.2.20 — Rollbacks migration invalid SQL

**Purpose:** Syntax error in 004 is surfaced.

**Test Data:** `DOP TABLE Response;`

**Mocking:** Executor raises `SqlSyntaxError("DOP")`.

**Assertions:**
`error.code = "PRE_migrations_004_rollbacks_sql_INVALID_SQL"`

**AC-Ref:** 6.2.2.20
**Error Mode:** PRE\_migrations\_004\_rollbacks\_sql\_INVALID\_SQL

---

## 7.2.2.21 — Rollbacks migration execution error

**Purpose:** Drop order conflict is signalled.

**Test Data:** Drop table with dependent FK.

**Mocking:** DB raises `DependentObjectsExist`.

**Assertions:**
`error.code = "PRE_migrations_004_rollbacks_sql_EXECUTION_ERROR"`

**AC-Ref:** 6.2.2.21
**Error Mode:** PRE\_migrations\_004\_rollbacks\_sql\_EXECUTION\_ERROR

---

## 7.2.2.22 — Database URL missing

**Purpose:** Missing DSN is a contract error.

**Test Data:** Config JSON omits `database.url`.

**Mocking:** Config loader returns dict without key.

**Assertions:**
`error.code = "PRE_config_database_url_MISSING"`

**AC-Ref:** 6.2.2.22
**Error Mode:** PRE\_config\_database\_url\_MISSING

---

## 7.2.2.23 — Database URL invalid DSN

**Purpose:** Malformed DSN is rejected.

**Test Data:** `config/database.url = "postgres:/bad"`.

**Mocking:** DSN parser raises `DsnError("invalid scheme")`.

**Assertions:**
`error.code = "PRE_config_database_url_INVALID_DSN"`

**AC-Ref:** 6.2.2.23
**Error Mode:** PRE\_config\_database\_url\_INVALID\_DSN

---

## 7.2.2.24 — Database host unresolved

**Purpose:** DNS failure yields the right code.

**Test Data:** `postgresql://u@no-such-host:5432/db`

**Mocking:** Resolver call raises `DnsResolutionError("no-such-host")`.

**Assertions:**
`error.code = "PRE_config_database_url_HOST_UNRESOLVED"`

**AC-Ref:** 6.2.2.24
**Error Mode:** PRE\_config\_database\_url\_HOST\_UNRESOLVED

---

## 7.2.2.25 — TLS required flag missing

**Purpose:** Missing boolean is flagged.

**Test Data:** Config lacks `database.ssl.required`.

**Mocking:** Config loader returns dict without key.

**Assertions:**
`error.code = "PRE_config_database_ssl_required_MISSING"`

**AC-Ref:** 6.2.2.25
**Error Mode:** PRE\_config\_database\_ssl\_required\_MISSING

---

## 7.2.2.26 — TLS required not boolean

**Purpose:** Type enforcement on TLS flag.

**Test Data:** `database.ssl.required = "yes"`

**Mocking:** None beyond config read.

**Assertions:**
`error.code = "PRE_config_database_ssl_required_NOT_BOOLEAN"`

**AC-Ref:** 6.2.2.26
**Error Mode:** PRE\_config\_database\_ssl\_required\_NOT\_BOOLEAN

---

## 7.2.2.27 — TLS materials unavailable while required

**Purpose:** Required CA bundle missing when TLS=true.

**Test Data:** `database.ssl.required = true`

**Mocking:** Access to trust store path raises `FileNotFoundError`.

**Assertions:**
`error.code = "PRE_config_database_ssl_required_TLS_MATERIALS_UNAVAILABLE"`

**AC-Ref:** 6.2.2.27
**Error Mode:** PRE\_config\_database\_ssl\_required\_TLS\_MATERIALS\_UNAVAILABLE

---

## 7.2.2.28 — Encryption mode missing

**Purpose:** Mode must be provided.

**Test Data:** Config missing `encryption.mode`.

**Mocking:** Config loader omits key.

**Assertions:**
`error.code = "PRE_config_encryption_mode_MISSING"`

**AC-Ref:** 6.2.2.28
**Error Mode:** PRE\_config\_encryption\_mode\_MISSING

---

## 7.2.2.29 — Encryption mode invalid value

**Purpose:** Validate allowed values.

**Test Data:** `encryption.mode = "hybrid"`

**Mocking:** None beyond config read.

**Assertions:**
`error.code = "PRE_config_encryption_mode_INVALID_VALUE"`

**AC-Ref:** 6.2.2.29
**Error Mode:** PRE\_config\_encryption\_mode\_INVALID\_VALUE

---

## 7.2.2.30 — KMS key alias required for column mode

**Purpose:** Column mode without alias is rejected.

**Test Data:** `encryption.mode = "column"`, no `kms.key_alias`.

**Mocking:** None beyond config read.

**Assertions:**
`error.code = "PRE_config_kms_key_alias_REQUIRED_FOR_COLUMN_MODE"`

**AC-Ref:** 6.2.2.30
**Error Mode:** PRE\_config\_kms\_key\_alias\_REQUIRED\_FOR\_COLUMN\_MODE

---

## 7.2.2.31 — KMS key alias not found

**Purpose:** Nonexistent alias triggers error.

**Test Data:** `kms.key_alias = "alias/missing"`

**Mocking:** KMS `DescribeKey` returns `NotFound`.

**Assertions:**
`error.code = "PRE_config_kms_key_alias_ALIAS_NOT_FOUND"`

**AC-Ref:** 6.2.2.31
**Error Mode:** PRE\_config\_kms\_key\_alias\_ALIAS\_NOT\_FOUND

---

## 7.2.2.32 — KMS get\_key call failed

**Purpose:** KMS outage is surfaced as precondition failure.

**Test Data:** `kms.key_alias = "alias/contracts-app"`

**Mocking:** `kms.get_key("alias/contracts-app")` raises `TimeoutError`.

**Assertions:**
`error.code = "PRE_kms_get_key_alias_CALL_FAILED"`

**AC-Ref:** 6.2.2.32
**Error Mode:** PRE\_kms\_get\_key\_alias\_CALL\_FAILED

---

## 7.2.2.33 — KMS get\_key schema mismatch

**Purpose:** Provider returns wrong shape.

**Test Data:** KMS returns `{"key":"abc"}` (missing `arn`, `material`).

**Mocking:** KMS client returns the object above.

**Assertions:**
`error.code = "PRE_kms_get_key_alias_SCHEMA_MISMATCH"`

**AC-Ref:** 6.2.2.33
**Error Mode:** PRE\_kms\_get\_key\_alias\_SCHEMA\_MISMATCH

---

## 7.2.2.34 — KMS get\_key not immutable

**Purpose:** Caller mutates key handle; must be caught.

**Test Data:** Returned handle object is mutated by orchestrator during step.

**Mocking:** Spy wrapper detects attribute mutation after receipt.

**Assertions:**
`error.code = "PRE_kms_get_key_alias_NOT_IMMUTABLE"`

**AC-Ref:** 6.2.2.34
**Error Mode:** PRE\_kms\_get\_key\_alias\_NOT\_IMMUTABLE

---

## 7.2.2.35 — Secret manager call failed

**Purpose:** Secrets retrieval outage indicated.

**Test Data:** Secret name: `db_password`.

**Mocking:** Secret client `get("db_password")` raises `ServiceUnavailable`.

**Assertions:**
`error.code = "PRE_secrets_db_password_CALL_FAILED"`

**AC-Ref:** 6.2.2.35
**Error Mode:** PRE\_secrets\_db\_password\_CALL\_FAILED

---

## 7.2.2.36 — Secret schema mismatch

**Purpose:** Secret returns wrong type/shape.

**Test Data:** Secret returns `{ "password": 123 }`.

**Mocking:** Secret client returns object above.

**Assertions:**
`error.code = "PRE_secrets_db_password_SCHEMA_MISMATCH"`

**AC-Ref:** 6.2.2.36
**Error Mode:** PRE\_secrets\_db\_password\_SCHEMA\_MISMATCH

---

## 7.2.2.37 — Secret was logged

**Purpose:** Ensure secrets never appear in logs.

**Test Data:** Inject fake secret `"sk-test123"`.

**Mocking:** Secret client returns `"sk-test123"`. Capture logs via handler. No internal logic mocked.

**Assertions:**

1. Logs contain `request_id` and `agent_type` (non-secret).
2. Logs do **not** contain substring `"sk-test123"`.
3. Error envelope: `error.code = "PRE_secrets_db_password_LOGGED"` when leakage is detected (simulate by deliberately logging in a controlled branch of the test harness).

**AC-Ref:** 6.2.2.37
**Error Mode:** PRE\_secrets\_db\_password\_LOGGED

---

## 7.2.2.38 — CA bundle missing/unreadable

**Purpose:** Trust store is required when TLS enforced.

**Test Data:** `database.ssl.required = true`; `truststore/ca_bundle.pem` missing.

**Mocking:** `open("truststore/ca_bundle.pem")` raises `FileNotFoundError`.

**Assertions:**
`error.code = "PRE_truststore_ca_bundle_pem_MISSING_OR_UNREADABLE"`

**AC-Ref:** 6.2.2.38
**Error Mode:** PRE\_truststore\_ca\_bundle\_pem\_MISSING\_OR\_UNREADABLE

---

## 7.2.2.39 — CA bundle invalid PEM

**Purpose:** Invalid PEM is rejected.

**Test Data:** `truststore/ca_bundle.pem` → content `"-----BEGIN CERT-----\n...truncated"`

**Mocking:** PEM loader raises `ValueError("invalid PEM")`.

**Assertions:**
`error.code = "PRE_truststore_ca_bundle_pem_INVALID_PEM"`

**AC-Ref:** 6.2.2.39
**Error Mode:** PRE\_truststore\_ca\_bundle\_pem\_INVALID\_PEM

---

## 7.2.2.40 — CA certificate not valid

**Purpose:** Expired/not-yet-valid cert triggers correct code.

**Test Data:** PEM with `NotBefore` in the future.

**Mocking:** Certificate verifier raises `CertificateNotValid`.

**Assertions:**
`error.code = "PRE_truststore_ca_bundle_pem_CERT_NOT_VALID"`

**AC-Ref:** 6.2.2.40
**Error Mode:** PRE\_truststore\_ca\_bundle\_pem\_CERT\_NOT\_VALID

---

## 7.2.2.41 — Encrypted fields policy missing/unreadable

**Purpose:** Policy file must exist.

**Test Data:** `policy/encrypted_fields` missing.

**Mocking:** `open` raises `FileNotFoundError`.

**Assertions:**
`error.code = "PRE_policy_encrypted_fields_MISSING_OR_UNREADABLE"`

**AC-Ref:** 6.2.2.41
**Error Mode:** PRE\_policy\_encrypted\_fields\_MISSING\_OR\_UNREADABLE

---

## 7.2.2.42 — Encrypted fields pointers unresolved

**Purpose:** JSON pointers must resolve.

**Test Data:** Policy lists `/entities/Nope/fields/value_json`.

**Mocking:** JSON pointer resolver raises `PointerResolutionError`.

**Assertions:**
`error.code = "PRE_policy_encrypted_fields_POINTERS_UNRESOLVED"`

**AC-Ref:** 6.2.2.42
**Error Mode:** PRE\_policy\_encrypted\_fields\_POINTERS\_UNRESOLVED

---

## 7.2.2.43 — Encrypted field not in entity

**Purpose:** Referenced field must exist.

**Test Data:** Policy refers to `Response.value_jsno`.

**Mocking:** ERD lookup returns no such field.

**Assertions:**
`error.code = "PRE_policy_encrypted_fields_FIELD_NOT_IN_ENTITY"`

**AC-Ref:** 6.2.2.43
**Error Mode:** PRE\_policy\_encrypted\_fields\_FIELD\_NOT\_IN\_ENTITY

---

## 7.2.2.44 — Migration timeout missing

**Purpose:** Timeout must be provided.

**Test Data:** Config lacks `migration.timeout_seconds`.

**Mocking:** Config loader omits key.

**Assertions:**
`error.code = "PRE_config_migration_timeout_seconds_MISSING"`

**AC-Ref:** 6.2.2.44
**Error Mode:** PRE\_config\_migration\_timeout\_seconds\_MISSING

---

## 7.2.2.45 — Migration timeout not positive integer

**Purpose:** Timeout must be > 0.

**Test Data:** `migration.timeout_seconds = 0` (or `"ten"`)

**Mocking:** None beyond config read.

**Assertions:**
`error.code = "PRE_config_migration_timeout_seconds_NOT_POSITIVE_INT"`

**AC-Ref:** 6.2.2.45
**Error Mode:** PRE\_config\_migration\_timeout\_seconds\_NOT\_POSITIVE\_INT

---

## 7.2.2.46 — Runtime: migration execution failure

**Purpose:** Failures during E1 table creation surface runtime code.

**Test Data:** Valid SQL; DB raises `FeatureNotSupported("generated columns")`.

**Mocking:** `.execute()` raises the exception above.

**Assertions:**
`error.code = "RUN_MIGRATION_EXECUTION_ERROR"`

**AC-Ref:** 6.2.2.46
**Error Mode:** RUN\_MIGRATION\_EXECUTION\_ERROR

---

## 7.2.2.47 — Runtime: constraint creation error

**Purpose:** E2 constraint apply failure.

**Test Data:** Unique constraint on non-existent column.

**Mocking:** DB raises `UndefinedColumn`.

**Assertions:**
`error.code = "RUN_CONSTRAINT_CREATION_ERROR"`

**AC-Ref:** 6.2.2.47
**Error Mode:** RUN\_CONSTRAINT\_CREATION\_ERROR

---

## 7.2.2.48 — Runtime: encryption apply error

**Purpose:** Column-level encryption failed to apply.

**Test Data:** Column flagged encrypted; KMS throws `AccessDenied`.

**Mocking:** KMS client raises `AccessDenied`.

**Assertions:**
`error.code = "RUN_ENCRYPTION_APPLY_ERROR"`

**AC-Ref:** 6.2.2.48
**Error Mode:** RUN\_ENCRYPTION\_APPLY\_ERROR

---

## 7.2.2.49 — Runtime: rollback error

**Purpose:** Rollback failed to drop objects.

**Test Data:** Drop table with dependent view.

**Mocking:** DB raises `DependentObjectsExist`.

**Assertions:**
`error.code = "RUN_MIGRATION_ROLLBACK_ERROR"`

**AC-Ref:** 6.2.2.49
**Error Mode:** RUN\_MIGRATION\_ROLLBACK\_ERROR

---

## 7.2.2.50 — Runtime: TLS connection error

**Purpose:** TLS handshake rejected at initiation.

**Test Data:** TLS required; server presents self-signed cert.

**Mocking:** Driver handshake raises `TlsHandshakeError("self-signed")`.

**Assertions:**
`error.code = "RUN_TLS_CONNECTION_ERROR"`

**AC-Ref:** 6.2.2.50
**Error Mode:** RUN\_TLS\_CONNECTION\_ERROR

---

## 7.2.2.51 — Runtime: row insertion error

**Purpose:** Insert violates declared schema.

**Test Data:** Insert `Response.value_json = "not-json"`.

**Mocking:** DB/validator raises `TypeError("jsonb expected")`.

**Assertions:**
`error.code = "RUN_ROW_INSERTION_ERROR"`

**AC-Ref:** 6.2.2.51
**Error Mode:** RUN\_ROW\_INSERTION\_ERROR

---

## 7.2.2.52 — Runtime: join resolution error

**Purpose:** Join chain fails to resolve placeholder.

**Test Data:** Response references unknown question\_id.

**Mocking:** Join execution returns empty / raises `JoinCardinalityError`.

**Assertions:**
`error.code = "RUN_JOIN_RESOLUTION_ERROR"`

**AC-Ref:** 6.2.2.52
**Error Mode:** RUN\_JOIN\_RESOLUTION\_ERROR

---

## 7.2.2.53 — Runtime: invalid encryption key

**Purpose:** Decrypt with wrong/disabled key.

**Test Data:** Field encrypted; KMS key disabled.

**Mocking:** KMS decrypt raises `KeyDisabled`.

**Assertions:**
`error.code = "RUN_INVALID_ENCRYPTION_KEY"`

**AC-Ref:** 6.2.2.53
**Error Mode:** RUN\_INVALID\_ENCRYPTION\_KEY

---

## 7.2.2.54 — Runtime: TLS materials unavailable

**Purpose:** TLS enforced but materials missing at runtime.

**Test Data:** `database.ssl.required = true`, truststore path wrong.

**Mocking:** Driver attempts to load CA → `FileNotFoundError`.

**Assertions:**
`error.code = "RUN_TLS_MATERIALS_UNAVAILABLE"`

**AC-Ref:** 6.2.2.54
**Error Mode:** RUN\_TLS\_MATERIALS\_UNAVAILABLE

---

## 7.2.2.55 — Runtime: unsupported data type

**Purpose:** Enum/JSON shape not supported.

**Test Data:** `AnswerOption.kind = "weird"`.

**Mocking:** Validator raises `UnsupportedType("weird")`.

**Assertions:**
`error.code = "RUN_UNSUPPORTED_DATA_TYPE"`

**AC-Ref:** 6.2.2.55
**Error Mode:** RUN\_UNSUPPORTED\_DATA\_TYPE

---

## 7.2.2.56 — Runtime: migration out of order

**Purpose:** Running 003 before 001 is rejected.

**Test Data:** Migration runner invoked with sequence `[003,001]`.

**Mocking:** Journal indicates 001 not applied; runner detects inversion.

**Assertions:**
`error.code = "RUN_MIGRATION_OUT_OF_ORDER"`

**AC-Ref:** 6.2.2.56
**Error Mode:** RUN\_MIGRATION\_OUT\_OF\_ORDER

---

## 7.2.2.57 — Runtime: unidentified error

**Purpose:** Unknown runtime failure is reported with catch-all code.

**Test Data:** Executor raises unexpected `ZeroDivisionError`.

**Mocking:** DB driver stub raises `ZeroDivisionError`.

**Assertions:**
`error.code = "RUN_UNIDENTIFIED_ERROR"`

**AC-Ref:** 6.2.2.57
**Error Mode:** RUN\_UNIDENTIFIED\_ERROR

---

## 7.2.2.58 — Outputs: entities incomplete

**Purpose:** Missing entity in outputs is a contract failure.

**Test Data:** Outputs omit `GeneratedDocument`.

**Mocking:** Compose outputs without that entity.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_INCOMPLETE"`

**AC-Ref:** 6.2.2.58
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_INCOMPLETE

---

## 7.2.2.59 — Outputs: entities order not deterministic

**Purpose:** Non-deterministic order rejected.

**Test Data:** Two runs emit different `outputs.entities[].name` order.

**Mocking:** Shuffle order on second run.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_ORDER_NOT_DETERMINISTIC"`

**AC-Ref:** 6.2.2.59
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.60 — Outputs: entities mutable within step

**Purpose:** Array must be immutable within step.

**Test Data:** After initial construction, test harness mutates list to simulate shared reference bug.

**Mocking:** Spy detects mutation after publication but within step scope.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_MUTABLE_WITHIN_STEP"`

**AC-Ref:** 6.2.2.60
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_MUTABLE\_WITHIN\_STEP

---

## 7.2.2.61 — Outputs: entity name empty

**Purpose:** Empty name forbidden.

**Test Data:** `outputs.entities[0].name = ""`

**Mocking:** Emit outputs with empty string.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_NAME_EMPTY"`

**AC-Ref:** 6.2.2.61
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_NAME\_EMPTY

---

## 7.2.2.62 — Outputs: entity name mismatch with ERD

**Purpose:** Name must exactly match ERD.

**Test Data:** `Response` → `Responses`.

**Mocking:** Emit plural.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_NAME_MISMATCH_WITH_ERD"`

**AC-Ref:** 6.2.2.62
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_NAME\_MISMATCH\_WITH\_ERD

---

## 7.2.2.63 — Outputs: entity name missing

**Purpose:** Missing field is an error.

**Test Data:** Omit `name` key.

**Mocking:** Emit object without key.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_NAME_MISSING"`

**AC-Ref:** 6.2.2.63
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_NAME\_MISSING

---

## 7.2.2.64 — Outputs: fields set invalid

**Purpose:** Extra/missing columns rejected.

**Test Data:** `Response` missing `value_json`.

**Mocking:** Emit fields array without that entry.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_SET_INVALID"`

**AC-Ref:** 6.2.2.64
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_SET\_INVALID

---

## 7.2.2.65 — Outputs: fields order not deterministic

**Purpose:** Field order must be stable.

**Test Data:** Run A orders `["id","value_json"]`; Run B `["value_json","id"]`.

**Mocking:** Shuffle.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_ORDER_NOT_DETERMINISTIC"`

**AC-Ref:** 6.2.2.65
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.66 — Outputs: fields array missing

**Purpose:** `fields[]` is required per entity.

**Test Data:** Omit `fields`.

**Mocking:** Emit entity object without `fields`.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_ARRAY_MISSING"`

**AC-Ref:** 6.2.2.66
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_ARRAY\_MISSING

---

## 7.2.2.67 — Outputs: field name mismatch with ERD

**Purpose:** Column name must match ERD.

**Test Data:** `value_json` misspelled `value_jsno`.

**Mocking:** Emit wrong name.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_NAME_MISMATCH_WITH_ERD"`

**AC-Ref:** 6.2.2.67
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_NAME\_MISMATCH\_WITH\_ERD

---

## 7.2.2.68 — Outputs: field name not unique

**Purpose:** Duplicate field names disallowed.

**Test Data:** Two entries both `"id"`.

**Mocking:** Emit duplicates.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_NAME_NOT_UNIQUE"`

**AC-Ref:** 6.2.2.68
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_NAME\_NOT\_UNIQUE

---

## 7.2.2.69 — Outputs: field name missing

**Purpose:** Field objects must have `name`.

**Test Data:** One field object lacks the `name` key.

**Mocking:** Emit missing key.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_NAME_MISSING"`

**AC-Ref:** 6.2.2.69
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_NAME\_MISSING

---

## 7.2.2.70 — Outputs: field type mismatch with ERD

**Purpose:** Type must match ERD.

**Test Data:** `value_json` type emitted as `"text"` (ERD says `jsonb`).

**Mocking:** Emit mismatch.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_TYPE_MISMATCH_WITH_ERD"`

**AC-Ref:** 6.2.2.70
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_TYPE\_MISMATCH\_WITH\_ERD

---

## 7.2.2.71 — Outputs: field type missing

**Purpose:** `type` required for every field.

**Test Data:** Omit `type`.

**Mocking:** Emit missing key.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_TYPE_MISSING"`

**AC-Ref:** 6.2.2.71
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_TYPE\_MISSING

---

## 7.2.2.72 — Outputs: encrypted flag false when required

**Purpose:** Required encryption must be flagged `true`.

**Test Data:** ERD marks `Response.value_json` encrypted; outputs have `"encrypted": false`.

**Mocking:** Emit false.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_ENCRYPTED_FALSE_WHEN_REQUIRED"`

**AC-Ref:** 6.2.2.72
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_ENCRYPTED\_FALSE\_WHEN\_REQUIRED

---

## 7.2.2.73 — Outputs: encrypted flag true when not required

**Purpose:** No over-declaration of encryption.

**Test Data:** `AnswerOption.label` shown as `"encrypted": true` though ERD not encrypted.

**Mocking:** Emit true.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_ENCRYPTED_TRUE_WHEN_NOT_REQUIRED"`

**AC-Ref:** 6.2.2.73
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_ENCRYPTED\_TRUE\_WHEN\_NOT\_REQUIRED

---

## 7.2.2.74 — Outputs: encrypted flag missing

**Purpose:** Flag must be present for fields (per outputs schema).

**Test Data:** Remove `encrypted` from one field object.

**Mocking:** Emit missing key.

**Assertions:**
`error.code = "POST_OUTPUTS_ENTITIES_FIELDS_ENCRYPTED_MISSING"`

**AC-Ref:** 6.2.2.74
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FIELDS\_ENCRYPTED\_MISSING


## 7.2.2.75 — Primary Key Columns Empty

**Title:** Reject empty primary key column list
**Purpose:** Verify the system surfaces the correct error when `outputs.entities[].primary_key.columns[]` is present but empty.

**Test Data:**

* Invocation: `generate_erd_outputs()`
* Simulated produced outputs (invalid):

```json
{
  "outputs": {
    "entities": [
      {
        "name": "Employee",
        "fields": [{"name":"id","type":"uuid"}],
        "primary_key": { "columns": [] }
      }
    ]
  }
}
```

**Mocking:**

* Mock boundary: persistence layer (no-op), ERD reference loader (returns ERD with `Employee.id` as PK).
* Behaviour: ERD loader returns `{ entity: Employee, pk: ["id"] }`.
* Why: Isolate contract validation; avoid real I/O.
* Usage assertions: ERD loader called once with `"Employee"`.

**Assertions:**

1. Response envelope has `status = "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_EMPTY"`.
3. Error path references `outputs.entities[0].primary_key.columns`.
4. No partial success artefacts are returned.

**AC-Ref:** 6.2.2.75
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_PRIMARY\_KEY\_COLUMNS\_EMPTY

---

## 7.2.2.76 — Primary Key Columns Unknown

**Title:** Reject PK columns not present in entity fields
**Purpose:** Ensure unknown PK column names trigger the correct error.

**Test Data:**

* Invocation: `generate_erd_outputs()`
* Invalid outputs:

```json
{
  "outputs": {
    "entities": [
      {
        "name": "Employee",
        "fields": [{"name":"id","type":"uuid"}],
        "primary_key": { "columns": ["employee_code"] }
      }
    ]
  }
}
```

**Mocking:**

* Mock ERD loader returns entity fields: `["id"]`.
* Why: Boundary only; avoid real ERD files.
* Usage assertion: Called once with `"Employee"`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_UNKNOWN"`.
3. Error message lists `"employee_code"` as unknown.
4. Error path points to `outputs.entities[0].primary_key.columns[0]`.

**AC-Ref:** 6.2.2.76
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_PRIMARY\_KEY\_COLUMNS\_UNKNOWN

---

## 7.2.2.77 — Primary Key Columns Order Not Deterministic

**Title:** Reject non-deterministic PK column ordering
**Purpose:** Confirm the system flags non-deterministic ordering across runs.

**Test Data:**

* Two sequential invocations: `generate_erd_outputs(seed=1)` then `generate_erd_outputs(seed=2)`
* Both runs produce PK columns as permutations: `["dept_id","id"]` vs `["id","dept_id"]`.

**Mocking:**

* Mock ERD loader returns composite PK order contract: lexicographic by column name.
* Why: Constrain deterministic order without real ERD files.
* Usage: Called twice; both with `"Employee"`.

**Assertions:**

1. Second run returns `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_ORDER_NOT_DETERMINISTIC"`.
3. Diagnostic captures differing orders between runs.
4. Error path references `outputs.entities[].primary_key.columns`.

**AC-Ref:** 6.2.2.77
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_PRIMARY\_KEY\_COLUMNS\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.78 — Primary Key Columns Missing When PK Defined

**Title:** Reject missing PK columns when PK exists in ERD
**Purpose:** Ensure omission of `primary_key.columns` fails when ERD defines a PK.

**Test Data:**

```json
{
  "outputs": {
    "entities": [
      { "name": "Employee", "fields": [{"name":"id","type":"uuid"}], "primary_key": {} }
    ]
  }
}
```

**Mocking:**

* ERD loader ⇒ `Employee` has PK `["id"]`.
* Why: Boundary mock only.
* Assertion: Called once with `"Employee"`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_PRIMARY_KEY_COLUMNS_MISSING_WHEN_PK_DEFINED"`.
3. Error path: `outputs.entities[0].primary_key.columns`.

**AC-Ref:** 6.2.2.78
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_PRIMARY\_KEY\_COLUMNS\_MISSING\_WHEN\_PK\_DEFINED

---

## 7.2.2.79 — Foreign Keys Set Invalid

**Title:** Reject FK set not exactly matching ERD
**Purpose:** Validate FK set equality to ERD definition.

**Test Data:**
Invalid outputs include one extra FK `fk_unknown`:

```json
{
  "outputs": {
    "entities": [
      {
        "name":"Employee",
        "foreign_keys":[{"name":"fk_dept","columns":["dept_id"],"references":{"entity":"Dept","columns":["id"]}},
                        {"name":"fk_unknown","columns":["x"],"references":{"entity":"Y","columns":["z"]}}]
      }
    ]
  }
}
```

**Mocking:**

* ERD loader ⇒ only `fk_dept` exists.
* Why: Isolate comparison logic.
* Usage: Called once.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_SET_INVALID"`.
3. Error details list unexpected `"fk_unknown"`.

**AC-Ref:** 6.2.2.79
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_SET\_INVALID

---

## 7.2.2.80 — Foreign Keys Order Not Deterministic

**Title:** Reject non-deterministic FK ordering
**Purpose:** Ensure FK array ordering is deterministic by FK name.

**Test Data:**

* Run A outputs `["fk_a","fk_b"]`, Run B outputs `["fk_b","fk_a"]`.

**Mocking:**

* ERD loader ⇒ two FKs: `fk_a`, `fk_b`.
* Why: Boundary only.
* Usage: Two calls; identical input.

**Assertions:**

1. Second run `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_ORDER_NOT_DETERMINISTIC"`.
3. Evidence shows order differs.

**AC-Ref:** 6.2.2.80
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.81 — Foreign Key Name Empty

**Title:** Reject empty FK name
**Purpose:** Ensure FK entries include a non-empty `name`.

**Test Data:**

```json
{
  "outputs": {
    "entities":[{"name":"Employee","foreign_keys":[{"name":"","columns":["dept_id"],"references":{"entity":"Dept","columns":["id"]}}]}]
  }
}
```

**Mocking:**

* None beyond boundary stubs (no I/O).
* Why: Pure contract check.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_NAME_EMPTY"`.
3. Error path: `outputs.entities[0].foreign_keys[0].name`.

**AC-Ref:** 6.2.2.81
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_NAME\_EMPTY

---

## 7.2.2.82 — Foreign Key Name Not Unique

**Title:** Reject duplicate FK names within entity
**Purpose:** Validate uniqueness of FK `name`.

**Test Data:**
Two FKs both named `fk_dept`:

```json
{
  "outputs": {
    "entities":[{"name":"Employee","foreign_keys":[
      {"name":"fk_dept","columns":["dept_id"],"references":{"entity":"Dept","columns":["id"]}},
      {"name":"fk_dept","columns":["manager_dept_id"],"references":{"entity":"Dept","columns":["id"]}}
    ]}]
  }
}
```

**Mocking:**

* None (contract-level).

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_NAME_NOT_UNIQUE"`.
3. Duplicates enumerated.

**AC-Ref:** 6.2.2.82
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_NAME\_NOT\_UNIQUE

---

## 7.2.2.83 — Foreign Key Name Missing When FKs Exist

**Title:** Reject missing FK `name` when `foreign_keys[]` exist
**Purpose:** Ensure required property presence.

**Test Data:**

```json
{
  "outputs": {
    "entities":[{"name":"Employee","foreign_keys":[
      {"columns":["dept_id"],"references":{"entity":"Dept","columns":["id"]}}
    ]}]
  }
}
```

**Mocking:**

* None.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_NAME_MISSING_WHEN_FKS_EXIST"`.

**AC-Ref:** 6.2.2.83
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_NAME\_MISSING\_WHEN\_FKS\_EXIST

---

## 7.2.2.84 — Foreign Key Columns Unknown

**Title:** Reject FK referencing unknown local columns
**Purpose:** Ensure each FK `columns[]` exist in entity.

**Test Data:**

```json
{
  "outputs": {
    "entities":[{"name":"Employee","fields":[{"name":"id"}],
      "foreign_keys":[{"name":"fk_dept","columns":["dept_id"],"references":{"entity":"Dept","columns":["id"]}}]}]
  }
}
```

**Mocking:**

* ERD loader ⇒ Employee fields: `["id"]`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_COLUMNS_UNKNOWN"`.
3. Error pinpoints `"dept_id"`.

**AC-Ref:** 6.2.2.84
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_COLUMNS\_UNKNOWN

---

## 7.2.2.85 — Foreign Key Columns Order Not Deterministic

**Title:** Reject non-deterministic FK column order
**Purpose:** Ensure `foreign_keys[].columns[]` order is stable.

**Test Data:**

* Two runs yield `["a","b"]` vs `["b","a"]`.

**Mocking:**

* ERD loader ⇒ expects lexicographic.

**Assertions:**

1. Second run `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_COLUMNS_ORDER_NOT_DETERMINISTIC"`.

**AC-Ref:** 6.2.2.85
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_COLUMNS\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.86 — Foreign Key Columns Missing When FKs Exist

**Title:** Reject missing `columns[]` when FKs exist
**Purpose:** Required array presence.

**Test Data:**

```json
{
  "outputs": {
    "entities":[{"name":"Employee","foreign_keys":[{"name":"fk_dept","references":{"entity":"Dept","columns":["id"]}}]}]
  }
}
```

**Mocking:**

* None.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_COLUMNS_MISSING_WHEN_FKS_EXIST"`.

**AC-Ref:** 6.2.2.86
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_COLUMNS\_MISSING\_WHEN\_FKS\_EXIST

---

## 7.2.2.87 — Foreign Key References Entity Missing

**Title:** Reject FK with missing referenced entity
**Purpose:** Ensure `references.entity` is present.

**Test Data:**

```json
{
  "outputs": {
    "entities":[{"name":"Employee","foreign_keys":[{"name":"fk_dept","columns":["dept_id"],"references":{"columns":["id"]}}]}]
  }
}
```

**Mocking:**

* None.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_ENTITY_MISSING"`.

**AC-Ref:** 6.2.2.87
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_REFERENCES\_ENTITY\_MISSING

---

## 7.2.2.88 — Foreign Key References Columns Missing

**Title:** Reject FK with missing referenced columns
**Purpose:** Ensure `references.columns[]` is present.

**Test Data:**

```json
{
  "outputs": {
    "entities":[{"name":"Employee","foreign_keys":[{"name":"fk_dept","columns":["dept_id"],"references":{"entity":"Dept"}}]}]
  }
}
```

**Mocking:**

* None.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_COLUMNS_MISSING"`.

**AC-Ref:** 6.2.2.88
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_REFERENCES\_COLUMNS\_MISSING

---

## 7.2.2.89 — Foreign Key References Entity Unknown

**Title:** Reject FK referencing unknown ERD entity
**Purpose:** Verify referenced entity exists in ERD.

**Test Data:**

```json
{
  "outputs": {
    "entities":[{"name":"Employee","foreign_keys":[{"name":"fk_x","columns":["dept_id"],"references":{"entity":"Unknown","columns":["id"]}}]}]
  }
}
```

**Mocking:**

* ERD loader ⇒ known entities: `["Dept","Employee"]`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_ENTITY_UNKNOWN"`.

**AC-Ref:** 6.2.2.89
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_REFERENCES\_ENTITY\_UNKNOWN

---

## 7.2.2.90 — Foreign Key References Columns Unknown

**Title:** Reject FK referencing unknown columns in target entity
**Purpose:** Ensure `references.columns[]` exist.

**Test Data:**

```json
{
  "outputs": {
    "entities":[{"name":"Employee","foreign_keys":[{"name":"fk_dept","columns":["dept_id"],"references":{"entity":"Dept","columns":["code"]}}]}]
  }
}
```

**Mocking:**

* ERD loader ⇒ Dept has columns: `["id","name"]`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_COLUMNS_UNKNOWN"`.

**AC-Ref:** 6.2.2.90
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_REFERENCES\_COLUMNS\_UNKNOWN

---

## 7.2.2.91 — Foreign Key References Columns Count Mismatch

**Title:** Reject FK with mismatched column counts
**Purpose:** Validate equal count for local and referenced columns.

**Test Data:**

```json
{
  "outputs": {
    "entities":[{"name":"Employee","foreign_keys":[{"name":"fk_dept","columns":["dept_id","dept_code"],"references":{"entity":"Dept","columns":["id"]}}]}]
  }
}
```

**Mocking:**

* None.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_FOREIGN_KEYS_REFERENCES_COLUMNS_COUNT_MISMATCH"`.

**AC-Ref:** 6.2.2.91
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_FOREIGN\_KEYS\_REFERENCES\_COLUMNS\_COUNT\_MISMATCH

---

## 7.2.2.92 — Unique Constraints Set Invalid

**Title:** Reject uniques not exactly matching ERD
**Purpose:** Validate unique constraints equality.

**Test Data:**

* Invalid outputs include extra unique `u_bad`.

**Mocking:**

* ERD loader ⇒ expected uniques: `["u_employee_code"]`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_SET_INVALID"`.

**AC-Ref:** 6.2.2.92
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_SET\_INVALID

---

## 7.2.2.93 — Unique Constraints Order Not Deterministic

**Title:** Reject non-deterministic unique constraints order
**Purpose:** Deterministic sort by unique name.

**Test Data:** Two runs swap order of `["u_a","u_b"]`.

**Mocking:**

* ERD loader ⇒ two uniques exist.

**Assertions:**

1. Second run `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_ORDER_NOT_DETERMINISTIC"`.

**AC-Ref:** 6.2.2.93
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.94 — Unique Constraint Name Empty

**Title:** Reject empty unique name
**Purpose:** Enforce non-empty `unique_constraints[].name`.

**Test Data:** unique with `name:""`.

**Mocking:**

* None.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_NAME_EMPTY"`.

**AC-Ref:** 6.2.2.94
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_NAME\_EMPTY

---

## 7.2.2.95 — Unique Constraint Name Not Unique

**Title:** Reject duplicate unique names
**Purpose:** Names must be unique per entity.

**Test Data:** two uniques named `u_employee_code`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_NAME_NOT_UNIQUE"`.

**AC-Ref:** 6.2.2.95
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_NAME\_NOT\_UNIQUE

---

## 7.2.2.96 — Unique Constraint Name Missing When Uniques Exist

**Title:** Reject missing unique `name` property
**Purpose:** Required property presence.

**Test Data:** unique entry without `name`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_NAME_MISSING_WHEN_UNIQUES_EXIST"`.

**AC-Ref:** 6.2.2.96
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_NAME\_MISSING\_WHEN\_UNIQUES\_EXIST

---

## 7.2.2.97 — Unique Constraint Columns Unknown

**Title:** Reject unique columns not in entity
**Purpose:** Validate each column exists.

**Test Data:** unique on `["employee_code","unknown_col"]`, fields only contain `employee_code`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_COLUMNS_UNKNOWN"`.

**AC-Ref:** 6.2.2.97
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_COLUMNS\_UNKNOWN

---

## 7.2.2.98 — Unique Constraint Columns Order Not Deterministic

**Title:** Reject non-deterministic unique columns order
**Purpose:** Stable order check.

**Test Data:** runs produce `["a","b"]` vs `["b","a"]`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_COLUMNS_ORDER_NOT_DETERMINISTIC"`.

**AC-Ref:** 6.2.2.98
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_COLUMNS\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.99 — Unique Constraint Columns Missing When Uniques Exist

**Title:** Reject missing `columns[]` under uniques
**Purpose:** Required presence.

**Test Data:** unique with `name` but no `columns`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_UNIQUE_CONSTRAINTS_COLUMNS_MISSING_WHEN_UNIQUES_EXIST"`.

**AC-Ref:** 6.2.2.99
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_UNIQUE\_CONSTRAINTS\_COLUMNS\_MISSING\_WHEN\_UNIQUES\_EXIST

---

## 7.2.2.100 — Indexes Set Invalid

**Title:** Reject indexes not exactly matching ERD
**Purpose:** Validate equality of indexes set.

**Test Data:** includes extra `idx_bad`.

**Mocking:** ERD loader ⇒ expected `["idx_employee_name"]`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_INDEXES_SET_INVALID"`.

**AC-Ref:** 6.2.2.100
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_INDEXES\_SET\_INVALID

---

## 7.2.2.101 — Indexes Order Not Deterministic

**Title:** Reject non-deterministic index order
**Purpose:** Enforce deterministic sort by index name.

**Test Data:** two runs swap order.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_INDEXES_ORDER_NOT_DETERMINISTIC"`.

**AC-Ref:** 6.2.2.101
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_INDEXES\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.102 — Index Name Empty

**Title:** Reject empty index name
**Purpose:** Require `indexes[].name`.

**Test Data:** `name:""`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_INDEXES_NAME_EMPTY"`.

**AC-Ref:** 6.2.2.102
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_INDEXES\_NAME\_EMPTY

---

## 7.2.2.103 — Index Name Not Unique

**Title:** Reject duplicate index names
**Purpose:** Names unique per entity.

**Test Data:** two `idx_employee_name`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_INDEXES_NAME_NOT_UNIQUE"`.

**AC-Ref:** 6.2.2.103
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_INDEXES\_NAME\_NOT\_UNIQUE

---

## 7.2.2.104 — Index Name Missing When Indexes Exist

**Title:** Reject missing `name` in indexes
**Purpose:** Required presence.

**Test Data:** index without `name`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_INDEXES_NAME_MISSING_WHEN_INDEXES_EXIST"`.

**AC-Ref:** 6.2.2.104
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_INDEXES\_NAME\_MISSING\_WHEN\_INDEXES\_EXIST

---

## 7.2.2.105 — Index Columns Unknown

**Title:** Reject index columns not in entity
**Purpose:** Validate column existence.

**Test Data:** index `columns:["unknown"]`, entity fields only `["name"]`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_INDEXES_COLUMNS_UNKNOWN"`.

**AC-Ref:** 6.2.2.105
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_INDEXES\_COLUMNS\_UNKNOWN

---

## 7.2.2.106 — Index Columns Order Not Deterministic

**Title:** Reject non-deterministic index column order
**Purpose:** Stable order within `columns[]`.

**Test Data:** two runs swap order.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_INDEXES_COLUMNS_ORDER_NOT_DETERMINISTIC"`.

**AC-Ref:** 6.2.2.106
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_INDEXES\_COLUMNS\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.107 — Index Columns Missing When Indexes Exist

**Title:** Reject missing `columns[]` with indexes present
**Purpose:** Required property presence.

**Test Data:** index has `name` but no `columns`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENTITIES_INDEXES_COLUMNS_MISSING_WHEN_INDEXES_EXIST"`.

**AC-Ref:** 6.2.2.107
**Error Mode:** POST\_OUTPUTS\_ENTITIES\_INDEXES\_COLUMNS\_MISSING\_WHEN\_INDEXES\_EXIST

---

## 7.2.2.108 — Enums Incomplete

**Title:** Reject enum list missing ERD enums
**Purpose:** Ensure `outputs.enums[]` covers all ERD enums.

**Test Data:** ERD has `EmploymentType` and `ContractType`; outputs only include `EmploymentType`.

**Mocking:**

* ERD loader returns two enum schemas.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENUMS_INCOMPLETE"`.

**AC-Ref:** 6.2.2.108
**Error Mode:** POST\_OUTPUTS\_ENUMS\_INCOMPLETE

---

## 7.2.2.109 — Enums Order Not Deterministic

**Title:** Reject non-deterministic enum ordering
**Purpose:** Stable sort by enum name.

**Test Data:** two runs produce reversed order.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENUMS_ORDER_NOT_DETERMINISTIC"`.

**AC-Ref:** 6.2.2.109
**Error Mode:** POST\_OUTPUTS\_ENUMS\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.110 — Enum Name Empty

**Title:** Reject empty enum name
**Purpose:** Require `enums[].name` to be non-empty.

**Test Data:** enum with `name:""`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENUMS_NAME_EMPTY"`.

**AC-Ref:** 6.2.2.110
**Error Mode:** POST\_OUTPUTS\_ENUMS\_NAME\_EMPTY

---

## 7.2.2.111 — Enum Name Mismatch With ERD

**Title:** Reject enum name not matching ERD
**Purpose:** Name must match exactly.

**Test Data:** outputs enum name `"Employment_Type"` while ERD `"EmploymentType"`.

**Mocking:** ERD loader returns `"EmploymentType"`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENUMS_NAME_MISMATCH_WITH_ERD"`.

**AC-Ref:** 6.2.2.111
**Error Mode:** POST\_OUTPUTS\_ENUMS\_NAME\_MISMATCH\_WITH\_ERD

---

## 7.2.2.112 — Enum Name Missing When Enums Exist

**Title:** Reject missing `name` for existing enums
**Purpose:** Required presence.

**Test Data:** enum item without `name`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENUMS_NAME_MISSING_WHEN_ENUMS_EXIST"`.

**AC-Ref:** 6.2.2.112
**Error Mode:** POST\_OUTPUTS\_ENUMS\_NAME\_MISSING\_WHEN\_ENUMS\_EXIST

---

## 7.2.2.113 — Enum Values Empty

**Title:** Reject empty enum values
**Purpose:** `values[]` must contain at least one value.

**Test Data:** `values: []`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENUMS_VALUES_EMPTY"`.

**AC-Ref:** 6.2.2.113
**Error Mode:** POST\_OUTPUTS\_ENUMS\_VALUES\_EMPTY

---

## 7.2.2.114 — Enum Values Mismatch With ERD

**Title:** Reject enum values not matching ERD
**Purpose:** Exact equality with ERD values.

**Test Data:** ERD values: `["FULL_TIME","PART_TIME"]`; outputs: `["FULL_TIME","FLEX"]`.

**Mocking:** ERD loader returns canonical values.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENUMS_VALUES_MISMATCH_WITH_ERD"`.

**AC-Ref:** 6.2.2.114
**Error Mode:** POST\_OUTPUTS\_ENUMS\_VALUES\_MISMATCH\_WITH\_ERD

---

## 7.2.2.115 — Enum Values Order Not Deterministic

**Title:** Reject non-deterministic enum values order
**Purpose:** Values must be deterministically ordered.

**Test Data:** Two runs reorder values.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENUMS_VALUES_ORDER_NOT_DETERMINISTIC"`.

**AC-Ref:** 6.2.2.115
**Error Mode:** POST\_OUTPUTS\_ENUMS\_VALUES\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.116 — Enum Values Missing When Enums Exist

**Title:** Reject missing `values[]` for present enum
**Purpose:** Required property presence.

**Test Data:** enum with `name` but no `values`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENUMS_VALUES_MISSING_WHEN_ENUMS_EXIST"`.

**AC-Ref:** 6.2.2.116
**Error Mode:** POST\_OUTPUTS\_ENUMS\_VALUES\_MISSING\_WHEN\_ENUMS\_EXIST

---

## 7.2.2.117 — Encrypted Fields Incomplete

**Title:** Reject missing encrypted field entries
**Purpose:** `outputs.encrypted_fields[]` must include all ERD-encrypted fields.

**Test Data:** ERD marks `["Employee.ni_number"]` encrypted; outputs omit it.

**Mocking:** ERD loader returns encrypted list.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENCRYPTED_FIELDS_INCOMPLETE"`.

**AC-Ref:** 6.2.2.117
**Error Mode:** POST\_OUTPUTS\_ENCRYPTED\_FIELDS\_INCOMPLETE

---

## 7.2.2.118 — Encrypted Fields Values Not Unique

**Title:** Reject duplicate encrypted field entries
**Purpose:** Uniqueness within list.

**Test Data:** `["Employee.ni_number","Employee.ni_number"]`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENCRYPTED_FIELDS_VALUES_NOT_UNIQUE"`.

**AC-Ref:** 6.2.2.118
**Error Mode:** POST\_OUTPUTS\_ENCRYPTED\_FIELDS\_VALUES\_NOT\_UNIQUE

---

## 7.2.2.119 — Encrypted Fields Present When ERD None

**Title:** Reject encrypted list when ERD has none
**Purpose:** No encrypted fields should be listed.

**Test Data:** outputs `encrypted_fields:["X"]`; ERD says none.

**Mocking:** ERD loader ⇒ empty encrypted set.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_ENCRYPTED_FIELDS_PRESENT_WHEN_ERD_NONE"`.

**AC-Ref:** 6.2.2.119
**Error Mode:** POST\_OUTPUTS\_ENCRYPTED\_FIELDS\_PRESENT\_WHEN\_ERD\_NONE

---

## 7.2.2.120 — Constraints Applied Incomplete

**Title:** Reject missing constraint identifiers
**Purpose:** Ensure all ERD constraints are listed.

**Test Data:** ERD constraints: `["chk_salary_positive"]`; outputs: `[]`.

**Mocking:** ERD loader returns list above.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_CONSTRAINTS_APPLIED_INCOMPLETE"`.

**AC-Ref:** 6.2.2.120
**Error Mode:** POST\_OUTPUTS\_CONSTRAINTS\_APPLIED\_INCOMPLETE

---

## 7.2.2.121 — Constraints Applied Value Empty

**Title:** Reject empty string constraint identifier
**Purpose:** Non-empty identifiers.

**Test Data:** `constraints_applied:[""]`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_CONSTRAINTS_APPLIED_VALUE_EMPTY"`.

**AC-Ref:** 6.2.2.121
**Error Mode:** POST\_OUTPUTS\_CONSTRAINTS\_APPLIED\_VALUE\_EMPTY

---

## 7.2.2.122 — Constraints Applied Values Not Unique

**Title:** Reject duplicate constraint identifiers
**Purpose:** Enforce uniqueness.

**Test Data:** `constraints_applied:["chk_salary_positive","chk_salary_positive"]`.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_CONSTRAINTS_APPLIED_VALUES_NOT_UNIQUE"`.

**AC-Ref:** 6.2.2.122
**Error Mode:** POST\_OUTPUTS\_CONSTRAINTS\_APPLIED\_VALUES\_NOT\_UNIQUE

---

## 7.2.2.123 — Constraints Applied Order Not Deterministic

**Title:** Reject non-deterministic constraint order
**Purpose:** Deterministic ordering.

**Test Data:** two runs swap order.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_CONSTRAINTS_APPLIED_ORDER_NOT_DETERMINISTIC"`.

**AC-Ref:** 6.2.2.123
**Error Mode:** POST\_OUTPUTS\_CONSTRAINTS\_APPLIED\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.124 — Migration Journal Empty

**Title:** Reject empty migration journal when present
**Purpose:** Journal must contain at least one entry.

**Test Data:** `migration_journal: []`.

**Mocking:**

* Filesystem writer mocked (no writes). Boundary only.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_MIGRATION_JOURNAL_EMPTY"`.

**AC-Ref:** 6.2.2.124
**Error Mode:** POST\_OUTPUTS\_MIGRATION\_JOURNAL\_EMPTY

---

## 7.2.2.125 — Migration Journal Order Not Deterministic

**Title:** Reject non-deterministic journal ordering
**Purpose:** Stable order by sequence/filename.

**Test Data:** two runs reverse journal entry order:

```json
{
  "outputs": {
    "migration_journal": [
      {"filename":"002.add-fk.sql","applied_at":"2025-01-02T10:00:00Z"},
      {"filename":"001.init.sql","applied_at":"2025-01-02T09:58:00Z"}
    ]
  }
}
```

(second run flips)

**Mocking:**

* Clock fixed; file I/O mocked.

**Assertions:**

1. Second run `status == "error"`.
2. `error.code == "POST_OUTPUTS_MIGRATION_JOURNAL_ORDER_NOT_DETERMINISTIC"`.

**AC-Ref:** 6.2.2.125
**Error Mode:** POST\_OUTPUTS\_MIGRATION\_JOURNAL\_ORDER\_NOT\_DETERMINISTIC

---

## 7.2.2.126 — Migration Journal Missing Required Fields

**Title:** Reject journal entries missing required fields
**Purpose:** Each entry must include `filename` and `applied_at`.

**Test Data:**

```json
{
  "outputs": {
    "migration_journal": [
      {"filename":"001.init.sql"},
      {"applied_at":"2025-01-02T09:58:00Z"}
    ]
  }
}
```

**Mocking:**

* None beyond boundary stubs.

**Assertions:**

1. `status == "error"`.
2. `error.code == "POST_OUTPUTS_MIGRATION_JOURNAL_MISSING_REQUIRED_FIELDS"`.
3. Error path indicates the exact offending entry indices (0,1).

**AC-Ref:** 6.2.2.126
**Error Mode:** POST\_OUTPUTS\_MIGRATION\_JOURNAL\_MISSING\_REQUIRED\_FIELDS

## 7.3 Happy Path Behavioural Tests

**7.3.1.1 — Table creation is initiated after migration runner starts**  
**Title:** Start → Create Tables sequencing  
**Purpose:** Verify that table creation is invoked immediately after the migration runner starts, and not before.  
**Test Data:** Minimal ERD with one entity `Company`; config `{ database.url: "postgresql://user@host:5432/db", database.ssl.required: true }`.  
**Mocking:**

* Mock `MigrationRunner.create_tables()` to return a dummy success token.
* Mock DB client connect to return a dummy TLS-secured session sufficient for sequencing.
* Rationale: external boundaries only; observe invocation order.  
  **Assertions:** Assert invoked once immediately after migration runner start completes, and not before.  
  **AC-Ref:** 6.3.1.1

---

**7.3.1.2 — Constraint creation follows table creation**  
**Title:** Create Tables → Create Constraints sequencing  
**Purpose:** Verify that constraint creation (PK/FK/UNIQUE/INDEX) starts only after table creation completes.  
**Test Data:** ERD with two entities and one FK; same DB config as 7.3.1.1.  
**Mocking:**

* Mock `MigrationRunner.create_constraints()` to return dummy success.
* Mock `MigrationRunner.create_tables()` to return success token.  
  **Assertions:** Assert invoked once immediately after table creation completes, and not before.  
  **AC-Ref:** 6.3.1.2

---

**7.3.1.3 — Encryption application follows constraint creation**  
**Title:** Create Constraints → Apply Encryption sequencing  
**Purpose:** Verify that column-level encryption setup is invoked only after constraints are created.  
**Test Data:** ERD marking `Company.legal_name` as encrypted; config `{ encryption.mode: "column", kms.key_alias: "alias/contracts-app" }`.  
**Mocking:**

* Mock `MigrationRunner.apply_column_encryption()` to return dummy success.
* Mock KMS client `get_key("alias/contracts-app")` to return a dummy handle.  
  **Assertions:** Assert invoked once immediately after constraint creation completes, and not before.  
  **AC-Ref:** 6.3.1.3

---

**7.3.1.4 — TLS session established before any DB operation**  
**Title:** Connection Request → Enforce TLS sequencing  
**Purpose:** Verify that TLS enforcement is performed before subsequent database operations begin.  
**Test Data:** Config `{ database.ssl.required: true }`.  
**Mocking:**

* Mock DB client `connect()` to require `sslmode=require` and return dummy success.
* Mock truststore load to return a dummy CA bundle object.  
  **Assertions:** Assert invoked once immediately after connection request and before any schema or data operation; not invoked after.  
  **AC-Ref:** 6.3.1.4

---

**7.3.1.5 — Row validation is performed after secure connection**  
**Title:** TLS Established → Validate Row sequencing  
**Purpose:** Verify that type validation is invoked only after a secure DB session is established.  
**Test Data:** Example insert `{ Response.id: "r-1", value_json: {"k":"v"} }`.  
**Mocking:**

* Mock `DBSession.validate_row()` to return dummy success.
* DB connect mocked as in 7.3.1.4.  
  **Assertions:** Assert invoked once immediately after TLS session establishment completes, and not before.  
  **AC-Ref:** 6.3.1.5

---

**7.3.1.6 — Direct lookup follows row validation**  
**Title:** Validate Row → Direct Lookup sequencing  
**Purpose:** Verify that **direct lookup by `QuestionnaireQuestion.placeholder_code`** is invoked only after row validation completes (no join path).  
**Test Data:** One `placeholder_code` (e.g., `"COMPANY_NAME"`) present on a `QuestionnaireQuestion`.  
**Mocking:**

* Mock `PlaceholderResolver.lookup_by_code("COMPANY_NAME")` (or `DBSession.select_one(...)`) to return a dummy question record.
* Mock `DBSession.validate_row()` to return success.  
  **Assertions:** Assert lookup is invoked once immediately after row validation completes, and not before.  
  **AC-Ref:** 6.3.1.6

---

**7.3.1.7 — Placeholder resolution follows direct lookup**  
**Title:** Direct Lookup → Resolve Placeholders sequencing  
**Purpose:** Verify that placeholder resolution is triggered only after the **direct lookup** finishes.  
**Test Data:** One placeholder `{{company_name}}` mapped via `placeholder_code`.  
**Mocking:**

* Mock `Resolver.resolve_placeholders(lookup_result)` to return a dummy success token.
* Mock `PlaceholderResolver.lookup_by_code(...)` to return a dummy record sufficient to proceed.  
  **Assertions:** Assert resolution is invoked once immediately after direct lookup completes, and not before.  
  **AC-Ref:** 6.3.1.7

---

**7.3.1.8 — Rollback is initiated immediately after a migration failure**  
**Title:** Migration Failure → Rollback sequencing  
**Purpose:** Verify that rollback is triggered as the immediate next step after a migration failure.  
**Test Data:** Same ERD as 7.3.1.1; simulate failure in table creation.  
**Mocking:**

* Mock `MigrationRunner.create_tables()` to raise a controlled failure signal.
* Mock `MigrationRunner.rollback()` to return dummy success.  
  **Assertions:** Assert invoked once immediately after migration failure is signalled, and not before.  
  **AC-Ref:** 6.3.1.8

---

**7.3.1.9 — Determinism check precedes transition to the next step**  
**Title:** Step Completion → Determinism Gate → Next Step sequencing  
**Purpose:** Verify that a determinism gate is evaluated before transitioning to the next step.  
**Test Data:** Repeatable input seed for a step (e.g., sorted entity list).  
**Mocking:**

* Mock `DeterminismChecker.verify(step_output, seed)` to return dummy success.
* Next-step initiation mocked to allow sequencing only after checker returns.  
  **Assertions:** Assert invoked once immediately after step completion and before the next step is initiated; not after.  
  **AC-Ref:** 6.3.1.9

---

**7.3.1.10 — _(Reserved)_**  
**Title:** _(Reserved)_  
**Purpose:** _(Reserved in this epic; no cache materialisation test)_  
**Test Data:** _(n/a)_  
**Mocking:** _(n/a)_  
  **Assertions:** _(n/a)_  
  **AC-Ref:** 6.3.1.10

---

**7.3.1.11 — New template registration proceeds without schema migrations**  
**Title:** Register Template → Reuse Schema sequencing  
**Purpose:** Verify that template registration continues the workflow without initiating schema migration steps.  
**Test Data:** Template id `tpl-1`, version `v1`.  
**Mocking:**

* Mock `TemplateRegistry.register()` to return dummy success.
* Spy on `MigrationRunner.start()` to ensure it is not invoked.  
  **Assertions:** Assert template registration invoked once immediately after template introduction; assert migration runner not invoked at any time during this flow.  
  **AC-Ref:** 6.3.1.11

---

**7.3.1.12 — New policy registration proceeds without schema migrations**  
**Title:** Register Policy → Reuse Schema sequencing  
**Purpose:** Verify that policy registration continues the workflow without initiating schema migration steps.  
**Test Data:** Policy id `pol-1`, rule `no_pii_export=true`.  
**Mocking:**

* Mock `PolicyRegistry.register()` to return dummy success.
* Spy on `MigrationRunner.start()` to ensure it is not invoked.  
  **Assertions:** Assert policy registration invoked once immediately after policy introduction; assert migration runner not invoked at any time during this flow.  
  **AC-Ref:** 6.3.1.12

## 7.3.2 Sad Path Behavioural Tests

(derived from 6.3.2 and Section 5 runtime errors)&#x20;

### 7.3.2.1 – Halt on migration execution error (E1 → E2)

**Purpose:** Verify that a migration execution failure halts STEP-3 (E1: create tables) and prevents propagation to constraint creation (E2).

**Test Data:**

* Invocation: `run_migrations(sequence=["migrations/001_init.sql", "migrations/002_constraints.sql"])`
* Context: clean database, valid config.

**Mocking:**

* Mock the database executor bound at the migration runner boundary to raise `DatabaseExecutionError("syntax error at or near 'CREATEE'")` on executing `migrations/001_init.sql`.
* Do not mock the migration runner’s control flow.
* Assert the executor was called once with the exact SQL from `001_init.sql`; assert it was **not** called with `002_constraints.sql`.

**Assertions:**

* Assert error handler is invoked once immediately when **STEP-3/E1 (table creation)** raises, and not before.
* Assert **STEP-3/E2 (constraint creation)** is not invoked following the failure.
* Assert that error mode `RUN_MIGRATION_EXECUTION_ERROR` is observed.

**AC-Ref:** 6.3.2.1
**Error Mode:** RUN\_MIGRATION\_EXECUTION\_ERROR

---

### 7.3.2.2 – Halt on constraint creation error (E2 → indexes)

**Purpose:** Verify that a constraint creation failure halts STEP-3 (E2) and prevents propagation to index creation.

**Test Data:**

* Invocation: `run_migrations(sequence=["migrations/001_init.sql","migrations/002_constraints.sql","migrations/003_indexes.sql"])`
* Preconditions: `001_init.sql` succeeds.

**Mocking:**

* Mock DB executor to succeed for `001_init.sql`.
* For `002_constraints.sql`, raise `ConstraintError("FK company_id references missing table")`.
* Assert no executor call is made for `003_indexes.sql`.

**Assertions:**

* Assert error handler is invoked once immediately when **STEP-3/E2 (constraint creation)** raises, and not before.
* Assert **index creation** is not invoked following the failure.
* Assert `RUN_CONSTRAINT_CREATION_ERROR` is observed.

**AC-Ref:** 6.3.2.2
**Error Mode:** RUN\_CONSTRAINT\_CREATION\_ERROR

---

### 7.3.2.3 – Halt on encryption application error (E3 → remainder)

**Purpose:** Verify that encryption application failure halts STEP-3 (E3) and prevents subsequent migration steps.

**Test Data:**

* Invocation: `run_migrations(sequence=["…/002_constraints.sql","…/003_indexes.sql"])` with encryption enabled.

**Mocking:**

* Mock KMS adapter at the boundary to raise `EncryptionApplyError("key not permitted for encrypt")` on first encrypted column operation.
* DB executor left real to reach the encryption call; only the KMS boundary is mocked.

**Assertions:**

* Assert error handler is invoked once immediately when **STEP-3/E3 (apply column encryption)** raises, and not before.
* Assert subsequent migration steps are not invoked.
* Assert `RUN_ENCRYPTION_APPLY_ERROR` is observed.

**AC-Ref:** 6.3.2.3
**Error Mode:** RUN\_ENCRYPTION\_APPLY\_ERROR

---

### 7.3.2.4 – Halt on rollback failure (E8)

**Purpose:** Verify that a rollback failure halts STEP-3 (E8) and prevents further rollback steps.

**Test Data:**

* Invocation: `run_rollback(sequence=["migrations/004_rollbacks.sql"])`.

**Mocking:**

* Mock DB executor to raise `RollbackError("dependent objects exist")` on a `DROP TABLE` statement.
* Assert only the first failing rollback statement executed once.

**Assertions:**

* Assert error handler is invoked once immediately when **STEP-3/E8 (rollback)** raises, and not before.
* Assert no subsequent rollback statements are invoked.
* Assert `RUN_MIGRATION_ROLLBACK_ERROR` is observed.

**AC-Ref:** 6.3.2.4
**Error Mode:** RUN\_MIGRATION\_ROLLBACK\_ERROR

---

### 7.3.2.5 – Halt on TLS connection error (E4 → E5)

**Purpose:** Verify that a TLS connection failure halts STEP-3 (E4) and prevents row insertion (E5).

**Test Data:**

* Invocation: `open_db_connection(tls_required=True)` then `insert_row(Response, …)`.

**Mocking:**

* Mock DB connection adapter to raise `TlsConnectionError("handshake alert: certificate required")` during `connect()`.
* Assert no calls made to `insert_row`.

**Assertions:**

* Assert error handler is invoked once immediately when **STEP-3/E4 (enforce TLS)** raises, and not before.
* Assert **STEP-3/E5 (row validation/insert)** is not invoked.
* Assert `RUN_TLS_CONNECTION_ERROR` is observed.

**AC-Ref:** 6.3.2.5
**Error Mode:** RUN\_TLS\_CONNECTION\_ERROR

---

### 7.3.2.6 – Halt on row insertion validation error (E5 → E6)

**Purpose:** Verify that a row validation failure halts STEP-3 (E5) and prevents join resolution (E6).

**Test Data:**

* Invocation: `insert_row(Response, value_json={"answer_kind":"bogus"})` after successful connection.

**Mocking:**

* Do not mock validation logic; mock only DB adapter to accept the call if validation passes (it won’t).
* Validation layer raises `RowValidationError("enum mismatch: answer_kind")`.

**Assertions:**

* Assert error handler is invoked once immediately when **STEP-3/E5 (validate insert)** raises, and not before.
* Assert **STEP-3/E6 (join resolution)** is not invoked.
* Assert `RUN_ROW_INSERTION_ERROR` is observed.

**AC-Ref:** 6.3.2.6
**Error Mode:** RUN\_ROW\_INSERTION\_ERROR

---

### 7.3.2.7 – Halt on join resolution error (E6 → E7)

**Purpose:** Verify that a join failure halts STEP-3 (E6) and prevents placeholder return (E7).

**Test Data:**

* Invocation: `resolve_placeholders(response_id="r-123")`.

**Mocking:**

* Mock DB to return rows that create a broken join (missing foreign key target), causing the join layer to raise `JoinResolutionError("template_placeholder not found")`.
* Assert no call to the component that returns placeholders to requestor.

**Assertions:**

* Assert error handler is invoked once immediately when **STEP-3/E6 (execute join)** raises, and not before.
* Assert **STEP-3/E7 (return resolved values)** is not invoked.
* Assert `RUN_JOIN_RESOLUTION_ERROR` is observed.

**AC-Ref:** 6.3.2.7
**Error Mode:** RUN\_JOIN\_RESOLUTION\_ERROR

---

### 7.3.2.8 – Halt on invalid encryption key during field access (S3)

**Purpose:** Verify that invalid key access halts STEP-3 (S3-bound access) and prevents response retrieval.

**Test Data:**

* Invocation: `read_encrypted_field(entity="Company", field="legal_name", id="c-001")`.

**Mocking:**

* Mock KMS adapter to raise `InvalidKeyError("key disabled")` on `decrypt()`.
* Assert no downstream repository method returns the value.

**Assertions:**

* Assert error handler is invoked once immediately when **STEP-3/S3 (use KMS-managed keys during access)** raises, and not before.
* Assert response retrieval does not proceed.
* Assert `RUN_INVALID_ENCRYPTION_KEY` is observed.

**AC-Ref:** 6.3.2.8
**Error Mode:** RUN\_INVALID\_ENCRYPTION\_KEY

---

### 7.3.2.9 – Halt when TLS materials unavailable (E4)

**Purpose:** Verify that unavailability of TLS materials halts STEP-3 (E4) and prevents any subsequent DB operations.

**Test Data:**

* Invocation: `open_db_connection(tls_required=True, ca_bundle_path="truststore/ca_bundle.pem")`.

**Mocking:**

* Mock filesystem accessor at the connection boundary to raise `TlsMaterialsUnavailable("CA bundle missing")` when loading the bundle (prior to socket connect).
* Assert no DB `connect()` call is attempted.

**Assertions:**

* Assert error handler is invoked once immediately when **STEP-3/E4 (TLS preflight)** raises, and not before.
* Assert no subsequent DB operations occur.
* Assert `RUN_TLS_MATERIALS_UNAVAILABLE` is observed.

**AC-Ref:** 6.3.2.9
**Error Mode:** RUN\_TLS\_MATERIALS\_UNAVAILABLE

---

### 7.3.2.10 – Halt on unsupported data type at validation (E5)

**Purpose:** Verify that encountering an unsupported type halts STEP-3 (E5) and prevents any downstream steps.

**Test Data:**

* Invocation: `insert_row(Response, value_json={"unsupported_field":{"nested":"object"}})` where schema expects a scalar/enum.

**Mocking:**

* No mocks on validator; mock DB executor to be reachable. Validator raises `UnsupportedTypeError("unsupported_field type object")`.

**Assertions:**

* Assert error handler is invoked once immediately when **STEP-3/E5 (validate insert)** raises, and not before.
* Assert no downstream steps (joins, returns) are invoked.
* Assert `RUN_UNSUPPORTED_DATA_TYPE` is observed.

**AC-Ref:** 6.3.2.10
**Error Mode:** RUN\_UNSUPPORTED\_DATA\_TYPE

---

### 7.3.2.11 – Halt on out-of-order migration execution (E1/E2/E8)

**Purpose:** Verify that an out-of-sequence migration attempt halts STEP-3 and prevents subsequent migrations.

**Test Data:**

* Invocation: `run_migrations(sequence=["migrations/003_indexes.sql","migrations/001_init.sql"])`.

**Mocking:**

* Mock journal/state provider to report that `001_init.sql` has not run; ordering guard raises `OutOfOrderMigration("003 before 001")`.
* Assert DB executor is **not** invoked for `003_indexes.sql`.

**Assertions:**

* Assert error handler is invoked once immediately when the **STEP-3 migration order check** raises, and not before.
* Assert no further migration files are executed.
* Assert `RUN_MIGRATION_OUT_OF_ORDER` is observed.

**AC-Ref:** 6.3.2.11
**Error Mode:** RUN\_MIGRATION\_OUT\_OF\_ORDER

---

### 7.3.2.12 – Halt on unidentified runtime error (catch-all)

**Purpose:** Verify that an unexpected runtime failure halts the current STEP-3 sub-step and prevents downstream propagation.

**Test Data:**

* Invocation: `run_migrations(sequence=["migrations/002_constraints.sql"])`.

**Mocking:**

* Mock DB executor to raise `RuntimeError("unexpected None dereference")` during execution, not matching any specific handled category.
* Ensure the generic handler path is exercised.

**Assertions:**

* Assert error handler is invoked once immediately when the **current STEP-3 sub-step** raises an unidentified error, and not before.
* Assert downstream steps are not invoked.
* Assert `RUN_UNIDENTIFIED_ERROR` is observed.

**AC-Ref:** 6.3.2.12
**Error Mode:** RUN\_UNIDENTIFIED\_ERROR

---

### Post-flight audit

* **acs\_found:** `["6.3.2.1","6.3.2.2","6.3.2.3","6.3.2.4","6.3.2.5","6.3.2.6","6.3.2.7","6.3.2.8","6.3.2.9","6.3.2.10","6.3.2.11","6.3.2.12"]`
* **run\_errors\_used:** `["RUN_MIGRATION_EXECUTION_ERROR","RUN_CONSTRAINT_CREATION_ERROR","RUN_ENCRYPTION_APPLY_ERROR","RUN_MIGRATION_ROLLBACK_ERROR","RUN_TLS_CONNECTION_ERROR","RUN_ROW_INSERTION_ERROR","RUN_JOIN_RESOLUTION_ERROR","RUN_INVALID_ENCRYPTION_KEY","RUN_TLS_MATERIALS_UNAVAILABLE","RUN_UNSUPPORTED_DATA_TYPE","RUN_MIGRATION_OUT_OF_ORDER","RUN_UNIDENTIFIED_ERROR"]`
* **non\_run\_codes\_detected:** `[]`
* **unmapped\_acs:** `["6.3.2.13","6.3.2.14","6.3.2.15","6.3.2.16","6.3.2.17","6.3.2.18","6.3.2.19","6.3.2.20"]` (environmental ACs map to `ENV_…` errors and are out of scope for this section)

7.3.2.13 — Database connectivity failure halts STEP-3 and prevents downstream operations

Title: STEP-3 halts when DB network is unreachable; no downstream steps invoked
Purpose: Verify that a database connectivity outage during STEP-3 immediately halts processing and prevents any subsequent STEP-3 sub-operations.
Test Data: database.url="postgresql://user@db.example.org:5432/appdb"; TLS required = true.
Mocking: Mock the DB client/driver connect call used by STEP-3 to raise a network unreachable error on first invocation (e.g., socket errno for network down). No other components mocked. Assert the connect function is called exactly once with the DSN above.
Assertions: Assert error handler is invoked once immediately when STEP-3 attempts DB connect and not before. Assert STEP-3 sub-operations (table creation, constraints, joins) are not invoked. Assert that error mode ENV_NETWORK_UNREACHABLE_DB is observed. Assert no retries without backoff and no partial schema actions occur. Assert one error telemetry event is emitted.
AC-Ref: 6.3.2.13
Error Mode: ENV_NETWORK_UNREACHABLE_DB 

7.3.2.14 — Database permission failure halts STEP-3 and prevents schema creation

Title: STEP-3 halts when DB permissions are insufficient; schema creation bypassed
Purpose: Verify that insufficient DB privileges during STEP-3 stop the process before any schema DDL is attempted.
Test Data: database.url="postgresql://leastpriv@db.example.org:5432/appdb"; user lacks CREATE/TABLE privileges.
Mocking: Mock the DB client to succeed on TCP/TLS connection but raise a permission error (e.g., SQLSTATE 42501) on the first DDL prepare/execute call within STEP-3. Assert connect called once; assert DDL execute called once and fails.
Assertions: Assert error handler is invoked immediately on first DDL attempt and not before. Assert subsequent STEP-3 sub-operations (FKs, indexes, joins) are not invoked. Assert ENV_DB_PERMISSION_DENIED observed. Assert no objects are created. Assert one telemetry error event.
AC-Ref: 6.3.2.14
Error Mode: ENV_DB_PERMISSION_DENIED 

7.3.2.15 — TLS certificate/handshake failure halts STEP-3 and prevents inserts

Title: STEP-3 halts when DB TLS handshake fails; inserts and joins are prevented
Purpose: Verify that a TLS handshake failure during DB connection blocks all subsequent STEP-3 actions.
Test Data: database.ssl.required=true; trust bundle path configured; server presents a certificate with hostname mismatch CN=db.bad.example.
Mocking: Mock the TLS layer in the DB driver so that handshake returns a certificate verification error before session establishment. Assert the connect is attempted once with TLS enabled.
Assertions: Assert error handler is invoked once immediately on handshake failure and not before. Assert STEP-3 row insertion and join execution are not invoked. Assert ENV_TLS_HANDSHAKE_FAILED_DB observed. Assert one telemetry error event.
AC-Ref: 6.3.2.15
Error Mode: ENV_TLS_HANDSHAKE_FAILED_DB 

7.3.2.16 — Database storage exhaustion halts STEP-3 and prevents journal updates

Title: STEP-3 halts when DB storage is exhausted; no journal/write follow-ups occur
Purpose: Verify that tablespace/storage exhaustion in the database halts STEP-3 and prevents subsequent persistence and journal updates.
Test Data: Normal DSN; simulate DB tablespace full on first CREATE TABLE execution.
Mocking: Mock the DB execute for the first CREATE TABLE to raise “disk full / tablespace out of space” error. Assert no subsequent DDL attempts occur.
Assertions: Assert error handler is invoked once immediately on the failing CREATE and not before. Assert remaining STEP-3 actions (constraints, indexes, journal writes) are not invoked. Assert ENV_DATABASE_STORAGE_EXHAUSTED observed. Assert one telemetry error event.
AC-Ref: 6.3.2.16
Error Mode: ENV_DATABASE_STORAGE_EXHAUSTED 

7.3.2.17 — Filesystem/temp unavailability prevents STEP-3 continuation (degraded stop)

Title: STEP-3 halts when temp filesystem required by migration is unavailable
Purpose: Verify that local temp resource unavailability used by STEP-3 halts processing and prevents downstream DB actions.
Test Data: Migration requires a temp write (e.g., staging file path /tmp/migrate-stage.sql).
Mocking: Mock filesystem I/O at the boundary used by STEP-3 to throw “No such file or directory” or “Read-only filesystem” on first temp file open. Assert open() called once with the expected path.
Assertions: Assert error handler is invoked once immediately on temp open failure and not before. Assert no DB DDL/DDL-follow-ups are invoked after the failure. Assert ENV_DATABASE_STORAGE_EXHAUSTED observed as the environmental storage exhaustion proxy used by the system. Assert one telemetry error event.
AC-Ref: 6.3.2.17
Error Mode: ENV_DATABASE_STORAGE_EXHAUSTED 

7.3.2.18 — KMS unavailability halts STEP-3 encryption operations and prevents access

Title: STEP-3 halts when KMS is unavailable; no encrypted-field access proceeds
Purpose: Verify that KMS unavailability during encryption apply/access in STEP-3 halts the flow and prevents any dependent operations.
Test Data: Encryption mode includes column encryption; kms.key_alias="alias/contracts-app".
Mocking: Mock the KMS client call invoked by STEP-3 to raise a service unavailable error (HTTP 503/throttling not used here). Assert the client is called once with the configured alias.
Assertions: Assert error handler is invoked once immediately on KMS call and not before. Assert no further STEP-3 encryption or row access attempts occur. Assert ENV_KMS_UNAVAILABLE observed. Assert one telemetry error event.
AC-Ref: 6.3.2.18
Error Mode: ENV_KMS_UNAVAILABLE 

7.3.2.19 — Time synchronisation failure halts STEP-3 where timestamps are required

Title: STEP-3 halts when system time is unsynchronised for timestamped operations
Purpose: Verify that clock skew preventing valid timestamping (e.g., for journal entries) halts STEP-3 and prevents continuation.
Test Data: Operation within STEP-3 requires generating an ISO-8601 UTC timestamp; system time skewed beyond validation tolerance.
Mocking: Mock the time source used by STEP-3 to return a non-UTC or invalid/monotonicity-violating time on first call.
Assertions: Assert error handler is invoked once immediately on time validation failure and not before. Assert downstream STEP-3 sub-operations are not invoked. Assert ENV_TIME_SYNCHRONISATION_FAILED observed. Assert one telemetry error event.
AC-Ref: 6.3.2.19
Error Mode: ENV_TIME_SYNCHRONISATION_FAILED 

7.3.2.20 — Configuration dependency unavailability prevents STEP-3 initiation

Title: STEP-3 halts when required configuration dependency is unavailable
Purpose: Verify that a missing/unavailable configuration dependency for STEP-3 prevents starting any STEP-3 sub-operations.
Test Data: Access to the configuration provider for DB/TLS settings returns dependency-unavailable.
Mocking: Mock the configuration loader used by STEP-3 to raise a dependency-unavailable error on first fetch of database.url or database.ssl.required. Assert fetch called once.
Assertions: Assert error handler is invoked once immediately on config fetch failure and not before. Assert ZERO DB connections or DDL invocations occur. Assert ENV_DB_UNAVAILABLE observed as the environment code used for unavailable DB prerequisites at connect time. Assert one telemetry error event.
AC-Ref: 6.3.2.20
Error Mode: ENV_DB_UNAVAILABLE

# Schemas

schemas/
  erd_and_runtime_inputs.schema.json
  migration_outputs.schema.json

Test File Tree

tests/
  conftest.py
  test_arch_epic_a.py          # architectural
  test_functional_epic_a.py    # contractual + behavioural via pytest
  fixtures/
    __init__.py
    tmp_workdir.py
    kms_stub.py
    tls_materials.py

# Application File Tree

app/
  __init__.py
  config.py
  db/
    __init__.py
    base.py
    migrations_runner.py
migrations/
  001_init.sql
  002_constraints.sql
  003_indexes.sql
  004_rollbacks.sql
