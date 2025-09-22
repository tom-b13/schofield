## Project overview

This project implements a multi-agent AI orchestration system for automated, test-driven software development. It is built around three key roles:

- **Ada** – the developer agent that writes production-ready code
- **Clarke** – the reviewing agent that ensures correctness and quality
- **Hamilton** – the coach/orchestrator agent that summarises progress and coordinates iteration flow

The system operates through structured LangGraph workflows, using defined JSON schemas, helper functions, and a shared prompt cache to maintain consistency and control.

### Key goals

- Enable automated, test-driven development loops
- Maintain human-readable summaries and checkpoints
- Enforce architectural and quality standards via Clarke
- Enable humans to intercede at any time with full context
- Avoid overreach: each agent has clear, isolated responsibilities

### Key features

- **LangGraph-driven orchestration** for deterministic flow control
- **Centralised prompt management** using versioned, cached templates
- **Structured task handoff** via JSON schemas and context propagation
- **Error-tolerant execution** with guardrails and logging
- **Pluggable agent logic** enabling refinement, expansion, and overrides

This system forms the foundation for a reliable and extensible AI software engineer, with minimal human intervention required between iterations.

## Documentation and references
The ./docs/ directory contains reference material and specifications that support agent behaviour, orchestration logic, and implementation scope. These documents are not part of the LangGraph runtime but define the source-of-truth for correctness, validation, and code generation.

### Reference overview: APPENDICES.md
The ./docs/APPENDICES.md document defines all formal reference structures used across LangGraph. This includes schemas, table definitions, routing logic, and helper contracts. Each appendix is scoped to a different dimension of runtime behaviour:

#### Appendix A – JSON schemas
Defines all JSON schema files used for validation of data flowing through LangGraph nodes. Ensures structural consistency and typed correctness at each orchestration step.

#### Appendix B – SQLite table definitions
Outlines schema for persistent storage, including LangGraph state, iteration summaries, technical debt, and prompt templates.

#### Appendix C – Routing logic
Describes the YAML-based routing structure used to determine LangGraph transitions based on outputs.

#### Appendix D – LangGraph node definitions
Provides full specification of each node including:

- Function signature
- Expected inputs/outputs
- Responsible story
- Handled exceptions and edge cases
- Used as the primary reference when generating or validating stubs.

#### Appendix E – Helper function definitions
Documents all reusable support functions for logging, prompt rendering, schema validation, etc.

#### Appendix F – Environment variables
Lists runtime environment variables such as keys, toggles, file paths, and debug flags used by the application.

## Tech stack

This system is implemented using the following technologies:

- **Python 3.11+** – Primary language for orchestration and agent logic
- **LangGraph** – Framework for defining and executing deterministic multi-agent workflows
- **OpenAI / Humanloop** – LLM execution, prompt versioning, and experiment tracking
- **SQLite** – Lightweight, local storage for LangGraph state, test results, and iteration data
- **JSON Schema** – Structured input/output validation and contract enforcement
- **Jinja2** – Templating engine used to dynamically render prompts
- **Pytest** – Core test framework for unit, integration, and orchestration testing
- **pytest-mock** – Cleaner mocking syntax and fixtures for improved test readability
- **responses** – HTTP mocking for external API requests (e.g. OpenAI, Humanloop)
- **freezegun** – Freeze and control time during tests for deterministic behaviour
- **coverage.py** – Measures code coverage and supports TDD completeness
- **pytest-cov** – Integrates `coverage.py` with `pytest` for combined reporting
- **Pydantic** – Typed data models and validation, if used internally
- **Behave** – BDD framework used for integration tests
- **ast** – Runs the architectural tests

All orchestration logic, schemas, tests, and helper utilities live directly under the project root directory, following a structured layout for clarity, separation of concerns, and agent compatibility.

## Directory structure

The following structure ensures separation of concerns, testability, and clarity of responsibility across the LangGraph orchestration framework:

```
.                          # Root of the project and the directory that Codex is running from.
│
├── /nodes/                # LangGraph node implementations
│   └── [node_name].py
│
├── /orchestrators/        # Orchestration helpers
│   └── [orchestrator_name].py
│
├── /helpers/              # Globally importable helper functions
│   └── [helper_name].py
│
├── /strategies/           # LLM invocation strategies
│   └── /llm_client/
│       └── [strategy_name].py
│
├── /schemas/              # JSON schema files for validation
│   └── [schema_name].json
│
├── /prompts/              # Jinja2 templates for prompt rendering
│   └── prompt_[agent]_[task_type]_[target_layer].j2
│
├── /logs/                 # Logs directory
│   └── [log_file].log
│
├── /routes/               # LangGraph routing YAML files
│   └── [routing_file].yaml
│
├── /sqlite_migrations/    # SQL table creation scripts
│   └── [table_name].sql
│
├── /tests/                # Test harnesses and test cases
│   ├── unit/
│   │   └── [unit_test_name].py
│   │
│   ├── integration/
│   │   ├── features/
│   │   │   ├── [feature_name].feature
│   │   │   └── steps/
│   │   │       └── [step_definition].py
│   │   ├── data/
│   │   │   └── [story_name]/
│   │   │       ├── txt_data.txt
│   │   │       ├── json_data.json
│   │   │       └── py_data.py
│   │
│   └── architecture/
│       └── [architecture_test_name].py
│
├── cadence_config.json    # Boot-time config file
├── .coveragerc
├── noxfile.py
└── requirements.txt
```

---

## Development Principles for Agent Output

All agent-generated code (especially from Ada) must follow the following development principles:

1. **Test-driven development (TDD)**

   * Write or revise tests first. Use tests to define desired behaviour before generating or updating implementation code.

2. **Minimal surface area**

   * Only write the code required to satisfy the current task or test. Avoid speculative features or premature abstraction.

3. **Fail fast, change fast**

   * Code should be easy to debug, update, and roll back. Prefer simplicity over cleverness.

4. **Single responsibility**

   * Each function, method, or class should do one thing well. Avoid mixing concerns.

5. **Explicit over implicit**

   * Be clear in naming, structure, and logic. Avoid magic variables or overly compressed expressions.

6. **Readable and maintainable**

   * Write code as if the next person reading it will not have access to this prompt. Clarity wins over brevity.

7. **Security and performance-aware**

   * Default to safe and efficient approaches, even if the task scope is narrow.

8. **Consistent style**

   * Adhere to the agreed style guide (e.g. PEP8 for Python). Consistency is more important than personal preference.

9. **Versionable**

   * Ensure changes are structured in commit-sized units. Don’t cross boundaries between features without separation.

10. **KISS (Keep It Simple, Stupid)**

    * Favour straightforward, intuitive implementations over clever hacks. If it’s hard to explain, it probably needs to be simpler.

11. **YAGNI (You Aren’t Gonna Need It)**

    * Don’t build functionality unless it’s explicitly required. Premature features introduce risk, complexity, and waste.

12. **Fail clearly, not silently**

    * Use meaningful error messages, validation checks, and guard clauses. Make it obvious when something goes wrong and why.

13. **Design for testability**

    * Write code that can be easily unit tested. Avoid side effects, tightly coupled logic, or hidden dependencies.

14. **Separate concerns**

    * Maintain clear boundaries between business logic, data access, presentation, and orchestration. This ensures agents don’t entangle responsibilities.

15. **Optimise for change**

    * Assume the code will evolve. Choose structures that are easy to extend or replace without rewriting everything.

16. **DRY (Don't Repeat Yourself)**

   * Avoid duplicated logic, data structures, or control flows. Extract reusable components and make intent clear through abstraction.

---

## Agents

All agent responses must strictly follow the output schema defined in the prompt. Return only the JSON content—no prose, no explanation.

### Clarke (Tech Lead / Solution Architect)

- **Purpose**: Clarke reviews Ada’s output for quality, correctness, and alignment with best practices. Clarke provides structured feedback to guide Ada’s next steps.

- **Prompt name format**: `clarke_<task_type>_<target_layer>`

- **Expected Input Schema**: `agent_task.schema.json`

- **Expected Output Schema**: `clarke_output.schema.json`

- **Responsibilities**:
  - Review functional or code-level output produced by Ada
  - Identify risks, violations of architectural principles, and unclear logic
  - Recommend changes using clear, structured instructions

- **Notes**:

  * Clarke should not assume control flow or orchestration context. Clarke’s role is purely reactive to the task provided.

#### Execution behaviour

Clarke operates in **review-only mode**. She does not generate or edit code directly.

For every submission received from Ada:
- Read the code and check for correctness, completeness, and alignment with the current task.
- Identify any bugs, design concerns, or violations of development principles.
- Recommend precise changes or improvements using clear, structured instructions.
- Flag non-blocking issues as technical debt.

Clarke has read-only access to the codebase and acts as the final check before tasks are marked complete.

#### Output

Clarke returns:
- A list of comments or suggestions in structured form.
- A pass/fail signal indicating whether Ada should rework the code or continue.

---

### Ada (Developer / Coder)

* **Purpose**: Ada receives structured tasks and generates clean, secure, production-quality code to meet the defined objectives.

* **Prompt name format**: `ada_<task_type>_<target_layer>`

* **Expected Input Schema**: `agent_task.schema.json`

* **Expected Output Schema**: `ada_output.schema.json`

* **Responsibilities**:

  * Interpret instructions from Clarke or from test failure context
  * Write or modify code to meet specified acceptance criteria
  * Return only the code, plus any relevant notes in the structured format

* **Notes**:

  * Ada does not test code, review other agents' work, or make architecture decisions.
  * Ada's focus is implementation based on tightly scoped tasks.

#### Execution behaviour

Ada always runs in **full-auto mode**. She never asks questions, never requests clarification, and never outputs explanations or guidance.

All tasks must be executed immediately and without commentary.

When writing tests:
- Always assume the implementation will follow.
- Use the project’s existing structure and dependencies.
- Mock all external services and modules.
- Follow predefined schemas, naming conventions, and file locations.

When writing implementation code:
- Focus only on the requirements defined in the current task or test.
- Do not introduce speculative features or abstractions.
- Maintain clarity, consistency, and alignment with the project's style and architectural principles.

Ada has write access to the codebase and is responsible for generating production-ready code and tests. Her output should be self-contained, logically correct, and strictly scoped to the current task.

---

### Hamilton (Coach / Orchestrator)

* **Purpose**: Hamilton coordinates the agent interaction process. She evaluates test results, determines the next steps, and provides a structured summary of progress for human review.

* **Prompt name format**: `hamilton_iteration_summary`

* **Expected Input Schema**: `iteration_summarisation_input.schema.json`

* **Expected Output Schema**: `iteration_summary.schema.json`

* **Responsibilities**:

  * Summarise Ada and Clarke’s activity across one iteration
  * Generate a coherent and human-readable summary of what happened
  * Record technical debt and raise confidence levels appropriately

* **Notes**:

  * Hamilton does not generate or review code.
  * Hamilton operates as a neutral summariser to aid human approval.

#### Execution behaviour

Hamilton does not write or review code. Her purpose is to:
- Track the current iteration state.
- Detect when tasks are complete and ready to move forward.
- Summarise progress, outcomes, and confidence levels.
- Raise blockers, highlight technical debt, and guide iteration flow.

Hamilton uses data generated by Ada and Clarke to create a human-readable snapshot of activity.

#### Output

Hamilton produces:
- An iteration summary formatted for human approval.
- A structured breakdown of completed, failed, or pending tasks.
- A record of open technical debt items, confidence levels, and rationale for decision-making.

## Architectural & Coding Conventions

This style guide is mandatory for all agents (Ada, Clarke, Hamilton) and
human contributors. It defines the architectural conventions, coding standards,
test layout, and workflow practices used throughout the codebase.
Adherence is required for all source, tests, and agent-generated output.

---

### 1. Module Structure

- **Project Root**: All code lives under the project root directory or its subfolders. Top-level project files are reserved for orchestration and configuration.
- **Subdirectories**:
  - `nodes/`: Each LangGraph node has its own module. One node per `.py` file.
  - `helpers/`: Reusable, stateless utilities. Each helper gets a dedicated file; group related small functions, but avoid monolithic helpers.
  - `schemas/`: All JSON schema files, named with a `.schema.json` suffix.
  - `tests/`: Mirror the structure of `nodes/` and `helpers/`. Each module or major behavior has its own dedicated test file.
  - **No Circular Imports**: All modules must be independently importable.
- **Explicit Imports Only**: No wildcard imports. Always use explicit, absolute imports within the project root.

---

### 2. Configuration and Error Handling

- **Configuration**:
  - Central config in `cadence_config.json`, loaded by the bootstrap or via a designated config loader node/helper.
  - Never hardcode environment or secret values in code. Reference config or environment variables at runtime only.
  - Always validate config on load; enforce required fields and types using schemas or Pydantic if used.

- **Error Handling**:
  - Use narrow `try/except` blocks only where failure is expected or must be handled.
  - All exceptions must either be:
    - Raised with a clear, actionable message
    - Logged as errors before being re-raised or propagated
  - Never catch-and-drop exceptions silently.
  - Custom exceptions should inherit from base Python exceptions and be named with a `Hamilton`-prefix (e.g., `HamiltonSchemaError`).

---

### 3. Logging Principles

- **Structured Logging**:
  - Use Python's built-in `logging` module.
  - Log structure: Always include timestamp, log level, module, and human-readable message.
- **Log Levels**:
  - Use `INFO` for major workflow milestones.
  - Use `WARNING` only for recoverable, noticed issues (e.g., deprecated config in use).
  - Use `ERROR` for all faults, exceptions, and contract violations.
  - Never use `DEBUG` in production path.
- **Do Not Print**:
  - Never use `print()` for production logs or debugging. Redirect all output to the logger.

---

4. Test writing and folder structure
All tests are located under /tests/, organised by type: contractual, behavioural, integration, and architectural. Each type has a distinct purpose, location, and testing framework.

This separation ensures clarity of responsibility, consistency, and adherence to the project’s development principles.
The three supported testing frameworks are:

pytest — used for contractual and behavioural unit tests.

Behave — used for integration tests with .feature files and step definitions.

AST-based assertions — used for architectural tests, inspecting static code structure.

```
/tests/
├── unit/                  # Contractual and behavioural tests
│   └── [unit_test_name].py
│
├── integration/           # Workflow tests executed end-to-end using Behave
│   ├── features/
│   │   ├── [feature_name].feature
│   │   └── steps/
│   │       └── [step_definition].py
│   ├── data/
│   │   └── [story_name]/
│   │       ├── txt_data.txt
│   │       ├── json_data.json
│   │       └── py_data.py
│
└── architecture/          # Static assertions for design and file structure
    └── [architecture_test_name].py
```

4.1 Contractual tests
Contractual tests validate that all inputs, outputs, state changes, and error conditions conform to the defined contracts and schemas. These are written in Python using pytest and live in /tests/unit/. They include checks for correct schema validation, counts matching, and proper error handling.

Framework: pytest

4.2 Behavioural tests
Behavioural tests validate the observed behaviour of a module: ensuring the correct actions, side-effects, and logs occur as expected. These tests also use pytest, and are colocated with contractual tests in /tests/unit/.

Framework: pytest

4.3 Integration tests
Integration tests simulate real end-to-end workflows, verifying the system’s behaviour in full execution paths with minimal mocking. These are written using Behave, with .feature files (Gherkin syntax) and Python step definitions in /tests/integration/features/. Supporting test data lives under /tests/integration/data/.

Framework: Behave

4.4 Architectural tests
Architectural tests ensure that the codebase adheres to agreed structural patterns, naming conventions, and separation of concerns. These are written as AST-based static assertions in Python, located in /tests/architecture/. They inspect the code structure without executing it, to enforce design integrity.

Framework: Python AST-based static assertions

---

### 5. Mocking Standards

- **Use pytest-mock**: Use the `mocker` fixture, not `unittest.mock.patch` directly.
- **Scope**:
  - Mock only third-party services, external dependencies, I/O, or clock/time.
  - Never mock code under direct unit test—test the real logic.
- **Assertions**:
  - Always assert the correct usage of mocks (called/not called, arguments).
- **HTTP/External APIs**: Use `responses` for requests, never real HTTP calls in tests.

---

### 6. Naming Conventions and Layout

- **Modules & Files**: Lowercase, separate words with underscore, no capitals.
- **Classes**: CamelCase, begin with uppercase (e.g., `HamiltonCoach`).
- **Functions & Methods**: Lowercase with underscores.
- **Variables**: Lowercase with underscores, descriptive and specific.
- **Constants**: All UPPERCASE with underscores.
- **Schema Files**: Use `snake_case.schema.json`.
- **Test Functions**: Begin with `test_`, then describe behavior.
- **No Abbreviation or Opaque Names**: Always prefer full, explicit names over brevity.

---

### 7. Code Coverage Strategy

- **Goal**: 100% statement and branch coverage for all core LangGraph nodes, helpers, and persistent logic.
- **Enforcement**:
  - Use `pytest-cov` in CI.
  - All new code must be covered by at least one test, or explicitly justified.
- **Test Quality**:
  - Prefer fewer, focused tests over broad, catch-all tests.
  - Cover both expected and edge (invalid input, error path) cases.

---

### 8. Test Title and Docstring Formatting

- **Test Titles**:
  - Use descriptive, behavior-driven names: `test_node_saves_valid_state_to_db`
- **Docstrings**:
  - Every test function must contain a single-line docstring explaining **intent** (not implementation):
        `"""Fails if the state lacks required keys."""`
- **Class & Module Docstrings**:
  - Required for all node, helper, and test modules.
  - State purpose, contract, and expected orchestration behavior.

---

All contributors and AGENTS must follow this guide. Code, tests, and generated output that fail to adhere will be rejected by review or
orchestration. No exceptions.
