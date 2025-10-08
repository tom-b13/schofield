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
EnumOptionPlaceholderLink --> AnswerOption
EnumOptionPlaceholderLink --> Placeholder
GeneratedDocument --> ResponseSet
GroupValue --> AnswerOption
GroupValue --> FieldGroup
GroupValue --> QuestionnaireQuestion
GroupValue --> ResponseSet
Placeholder --> Document
Placeholder --> QuestionnaireQuestion
QuestionToFieldGroup --> FieldGroup
QuestionToFieldGroup --> QuestionnaireQuestion
QuestionnaireQuestion --> QuestionnaireQuestion
Response --> AnswerOption
Response --> QuestionnaireQuestion
Response --> ResponseSet
ResponseSet --> Company

%% Mermaid “erDiagram” overview for visual graph renderers
erDiagram
  AnswerOption ||--o{ EnumOptionPlaceholderLink : "links_to_child_placeholder"
  AnswerOption ||--o{ GroupValue : "groups"
  AnswerOption ||--o{ Response : "chosen_by"
  Company ||--o{ ResponseSet : "has"
  Document ||--|| DocumentBlob : "current_blob"
  Document ||--o{ Placeholder : "contains_spans"
  FieldGroup ||--o{ GroupValue : "has_values"
  Placeholder ||--o{ EnumOptionPlaceholderLink : "child_of_option"
  QuestionnaireQuestion ||--o{ AnswerOption : "offers"
  QuestionnaireQuestion ||--o{ GroupValue : "sources"
  QuestionnaireQuestion ||--o{ Placeholder : "binds"
  QuestionnaireQuestion ||--o{ QuestionToFieldGroup : "maps"
  QuestionnaireQuestion ||--o{ QuestionnaireQuestion : "parents"  %% self parent
  QuestionToFieldGroup }o--|| FieldGroup : "targets_group"
  ResponseSet ||--o{ GeneratedDocument : "produces"
  ResponseSet ||--o{ Response : "includes"
