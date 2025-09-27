%% EPIC-A ERD (nodes for tests; keep sorted)
class AnswerOption
class Company
class FieldGroup
class GeneratedDocument
class GroupValue
class QuestionToFieldGroup
class QuestionnaireQuestion
class Response
class ResponseSet

%% FK edges for tests (sorted)
AnswerOption --> QuestionnaireQuestion
GeneratedDocument --> ResponseSet
GroupValue --> AnswerOption
GroupValue --> FieldGroup
GroupValue --> QuestionnaireQuestion
GroupValue --> ResponseSet
QuestionToFieldGroup --> FieldGroup
QuestionToFieldGroup --> QuestionnaireQuestion
QuestionnaireQuestion --> QuestionnaireQuestion
Response --> AnswerOption
Response --> QuestionnaireQuestion
Response --> ResponseSet
ResponseSet --> Company


erDiagram
  Company ||--o{ ResponseSet : "has"
  ResponseSet ||--o{ Response : "includes"
  ResponseSet ||--o{ GeneratedDocument : "produces"

  ContractTemplate ||--o{ TemplatePlaceholder : "contains"
  %% (PolicyTemplate optionally exists in extended models)

  QuestionnaireQuestion ||--o{ AnswerOption : "offers"
  QuestionnaireQuestion ||--o{ QuestionnaireQuestion : "parents"
  QuestionnaireQuestion }o--o{ TemplatePlaceholder : "maps_via_QuestionToPlaceholder"

  %% === NEW: Screen-driven UI model ===
  QuestionnaireScreen ||--o{ ScreenGroup : "has"
  QuestionnaireScreen }o--o{ QuestionnaireQuestion : "places_via_QuestionToScreen"
  ScreenGroup }o--o{ QuestionnaireQuestion : "groups_via_QuestionToScreen"

  %% Joins
  QuestionnaireQuestion ||--o{ QuestionToPlaceholder : "maps"
  TemplatePlaceholder ||--o{ QuestionToPlaceholder : "mapped_by"

  QuestionnaireQuestion ||--o{ QuestionToScreen : "placed_in"
  QuestionnaireScreen ||--o{ QuestionToScreen : "composes"
  ScreenGroup ||--o{ QuestionToScreen : "subgroups"
