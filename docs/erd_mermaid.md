%% EPIC D — ERD (keep nodes/edges alphabetically sorted where feasible)

%% === Entity nodes ===
class AnswerOption
class Company
class Document
class DocumentBlob
class DocumentListState
class EnumOptionPlaceholderLink
class FieldGroup
class GeneratedDocument
class GroupValue
class IdempotencyKey
class Placeholder
class QuestionToFieldGroup
class QuestionnaireQuestion
class Response
class ResponseSet

%% === FK edges (one-to-many unless noted) ===
AnswerOption --> QuestionnaireQuestion
DocumentBlob --> Document
GeneratedDocument --> ResponseSet
GroupValue --> AnswerOption
GroupValue --> FieldGroup
GroupValue --> QuestionnaireQuestion
GroupValue --> ResponseSet
Placeholder --> Document
Placeholder --> QuestionnaireQuestion
EnumOptionPlaceholderLink --> AnswerOption
EnumOptionPlaceholderLink --> Placeholder
QuestionToFieldGroup --> FieldGroup
QuestionToFieldGroup --> QuestionnaireQuestion
QuestionnaireQuestion --> QuestionnaireQuestion
Response --> AnswerOption
Response --> QuestionnaireQuestion
Response --> ResponseSet
ResponseSet --> Company

%% Mermaid “erDiagram” overview for visual graph renderers
erDiagram
  Company ||--o{ ResponseSet : "has"
  ResponseSet ||--o{ Response : "includes"
  ResponseSet ||--o{ GeneratedDocument : "produces"

  Document ||--|| DocumentBlob : "current_blob"
  Document ||--o{ Placeholder : "contains_spans"

  QuestionnaireQuestion ||--o{ AnswerOption : "offers"
  QuestionnaireQuestion ||--o{ Response : "asks"
  QuestionnaireQuestion ||--o{ GroupValue : "sources"
  QuestionnaireQuestion ||--o{ Placeholder : "binds"
  QuestionnaireQuestion ||--o{ QuestionToFieldGroup : "maps"
  QuestionnaireQuestion ||--o{ QuestionnaireQuestion : "parents"  %% self parent

  AnswerOption ||--o{ Response : "chosen_by"
  AnswerOption ||--o{ GroupValue : "groups"
  AnswerOption ||--o{ EnumOptionPlaceholderLink : "links_to_child_placeholder"

  FieldGroup ||--o{ GroupValue : "has_values"
  QuestionToFieldGroup }o--|| FieldGroup : "targets_group"

  Placeholder ||--o{ EnumOptionPlaceholderLink : "child_of_option"
