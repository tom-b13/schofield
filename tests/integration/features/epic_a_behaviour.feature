Feature: Epic A Behaviour

  Scenario: Migration Initiates Schema Creation
    Given the migration runner starts
    When migrations are executed
    Then the system must initiate table creation as the first step in schema setup.

  Scenario: Direct Lookup Follows Row Validation
    Given row insertion has passed schema validation
    When placeholder sourcing is required
    Then the system must perform a direct lookup by QuestionnaireQuestion.placeholder_code (unique when present).

