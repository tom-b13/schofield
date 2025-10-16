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
class Questionnaire
class QuestionnaireQuestion
class Response
class ResponseSet
class Screen

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
QuestionnaireQuestion --> Screen
Response --> AnswerOption
Response --> QuestionnaireQuestion
Response --> ResponseSet
ResponseSet --> Company
Screen --> Questionnaire

%% Mermaid overview block removed to avoid edges not present in ERD direction set
