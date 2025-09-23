%% EPIC-A ERD (sorted)
class AnswerOption
class Company
class FieldGroup
class GeneratedDocument
class GroupValue
class QuestionToFieldGroup
class QuestionnaireQuestion
class Response
class ResponseSet

% Edges (source→target), sorted pairs
AnswerOption --> QuestionnaireQuestion
GeneratedDocument --> ResponseSet
GroupValue --> AnswerOption
GroupValue --> FieldGroup
GroupValue --> QuestionnaireQuestion
GroupValue --> ResponseSet
QuestionToFieldGroup --> FieldGroup
QuestionToFieldGroup --> QuestionnaireQuestion
Response --> AnswerOption
Response --> QuestionnaireQuestion
Response --> ResponseSet
ResponseSet --> Company
