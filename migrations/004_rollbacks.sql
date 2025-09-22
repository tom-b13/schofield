-- migrations/004_rollbacks.sql
-- Drop objects in reverse dependency order
DROP TABLE IF EXISTS GeneratedDocument;
DROP TABLE IF EXISTS ComputedPlaceholderValue;
DROP TABLE IF EXISTS Response;
DROP TABLE IF EXISTS ResponseSet;
DROP TABLE IF EXISTS GroupValue;
DROP TABLE IF EXISTS QuestionToFieldGroup;
DROP TABLE IF EXISTS FieldGroup;
DROP TABLE IF EXISTS QuestionToScreen;
DROP TABLE IF EXISTS QuestionnaireScreen;
DROP TABLE IF EXISTS QuestionToPlaceholder;
DROP TABLE IF EXISTS TransformationRule;
DROP TABLE IF EXISTS TemplatePlaceholder;
DROP TABLE IF EXISTS ContractTemplate;
DROP TABLE IF EXISTS AnswerOption;
DROP TABLE IF EXISTS QuestionnaireQuestion;
DROP TABLE IF EXISTS Company;
