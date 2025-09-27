"""Architectural tests for EPIC I — Conditional Visibility (Section 7.1).

These tests are intentionally written first (TDD) and are expected to fail
until the corresponding application code and contracts are implemented.

Rules enforced by this module:
- One test instance per 7.1.x subsection, discovered dynamically from the spec
  document (docs/api/Epic I - Conditional Visibility.md).
- Within each test instance, all "assert:" statements listed under that
  subsection are surfaced and must be enforced against the codebase via
  structural checks (AST / filesystem). For now, they fail explicitly to
  signal missing implementation.

Runner stability:
- No application modules are imported; only filesystem and AST inspection is
  used. Any parsing errors surface as assertion failures rather than crashing
  the test run.
"""

from __future__ import annotations

import ast
import io
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "api" / "Epic I - Conditional Visibility.md"


def _read_text(path: Path) -> Tuple[str | None, str | None]:
    """Read file text; never raise at import/collection time.

    Returns (text, error_message). Exactly one of the tuple items is non-None.
    """
    try:
        return path.read_text(encoding="utf-8"), None
    except FileNotFoundError as e:
        return None, (
            f"Specification not found: {path}. This test suite requires the EPIC I spec "
            f"to exist with Section 7.1 defined. Error: {e}"
        )
    except OSError as e:
        return None, f"Failed to read specification at {path}: {e}"


SECTION_RE = re.compile(r"^\s*7\.1\.(\d+)\s*[\u2014\-\—\–]\s*(.+)$")
ASSERT_RE = re.compile(r"^\s*(?:[-*]\s*)?assert\s*:\s*(.+)$", re.IGNORECASE)


def _extract_7_1_sections(markdown: str) -> List[Dict[str, object]]:
    """Parse the EPIC I spec and return a list of subsections under 7.1.

    Each item has keys: id (e.g. "7.1.1"), title (str), asserts (List[str]).
    The parser is tolerant to list markers like '-' or '*', and various dash
    characters used as separators in headings.
    """
    lines = markdown.splitlines()
    sections: List[Dict[str, object]] = []
    current: Dict[str, object] | None = None

    # Track whether we are inside the broader 7.1 block (if explicitly titled)
    # but operate primarily by matching 7.1.x headings.
    for raw in lines:
        line = raw.rstrip()

        # Start of a 7.1.x subsection
        m = SECTION_RE.match(line)
        if m:
            # Close previous section bucket
            if current is not None:
                sections.append(current)

            index, title = m.group(1), m.group(2).strip()
            current = {
                "id": f"7.1.{index}",
                "title": title,
                "asserts": [],
            }
            continue

        # Collect "assert:" lines under the current subsection
        if current is not None:
            am = ASSERT_RE.match(line)
            if am:
                current["asserts"].append(am.group(1).strip())

    if current is not None:
        sections.append(current)

    return sections


def _repo_python_files() -> List[Path]:
    """Enumerate Python source files in the repository for AST analysis.

    This intentionally targets known project directories to avoid scanning
    virtualenvs or binary artefacts. Adjust the roots here if the project
    topology changes.
    """
    roots = [
        REPO_ROOT / "app",
        REPO_ROOT / "schemas",
        REPO_ROOT / "tests",
        REPO_ROOT / "migrations",
        REPO_ROOT / "policy",
    ]
    files: List[Path] = []
    for r in roots:
        if r.exists():
            for p in r.rglob("*.py"):
                # Skip this test file itself for most structural checks
                if p.resolve() == Path(__file__).resolve():
                    continue
                files.append(p)
    return files


def _safe_parse_ast(path: Path) -> ast.AST | None:
    """Parse a Python file to AST, converting any exception into a test failure.

    Returns None if file cannot be parsed due to syntax error; the caller can
    decide how to treat such cases per assertion.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:  # pragma: no cover — failures asserted by caller
        pytest.fail(f"Failed to read {path}: {e}")
        return None

    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError:
        # Report syntax errors as assertion-friendly signals rather than hard crash
        return None


def _collect_project_asts() -> List[Tuple[Path, ast.AST | None]]:
    return [(p, _safe_parse_ast(p)) for p in _repo_python_files()]


def _load_spec_sections() -> Tuple[List[Dict[str, object]] | None, str | None]:
    text, err = _read_text(SPEC_PATH)
    if err is not None:
        return None, err
    sections = _extract_7_1_sections(text or "")
    if not sections:
        return None, (
            "EPIC I Section 7.1 subsections not found in spec. Ensure headings like "
            "'7.1.1 — <title>' exist and include assert: lines."
        )
    return sections, None


def _ids_for_param(section: Dict[str, object]) -> str:
    return f"{section.get('id', '7.1.?')} — {section.get('title', '').strip()}"


def pytest_generate_tests(metafunc):
    """Dynamically parameterize one test per 7.1.x section without crashing collection.

    If the spec is missing or malformed, generate a single failing case that
    reports the problem via the test body, preserving runner stability.
    """
    if "section" in metafunc.fixturenames:
        sections, err = _load_spec_sections()
        if err is not None:
            metafunc.parametrize(
                "section",
                [
                    {
                        "id": "7.1.error",
                        "title": "Spec missing or malformed",
                        "asserts": [],
                        "error": err,
                    }
                ],
                ids=["7.1.error"],
            )
        else:
            metafunc.parametrize(
                "section",
                sections or [],
                ids=_ids_for_param,
            )


@pytest.mark.parametrize("section", SECTIONS_7_1, ids=_ids_for_param)
def test_epic_i_conditional_visibility_section_contracts(section: Dict[str, object]):
    """Verifies EPIC I — Section 7.1.x contracts.

    This single parametrized test yields one test instance per 7.1.x section.
    For each section, it enumerates all "assert:" requirements defined in the
    spec and ensures there is an enforcement placeholder that fails until the
    real structural checks are implemented.

    Section validated: section["id"] (e.g., '7.1.1').
    """
    # Comment: Which 7.1.x section this test verifies
    section_id = section.get("id", "7.1.?")
    section_title = section.get("title", "").strip()
    asserts: List[str] = list(section.get("asserts", []))

    # If parameterization captured an upstream spec error, surface it cleanly here.
    if section.get("error"):
        pytest.fail(str(section["error"]))

    # Ensure each section actually specifies at least one assert: rule
    assert asserts, (
        f"Spec section {section_id} — '{section_title}' defines no 'assert:' lines. "
        f"Add explicit 'assert:' statements to the spec to drive enforcement."
    )

    # Prepare ASTs to support structural validations once implemented
    asts = _collect_project_asts()

    # For now, each assertion fails explicitly as these are TDD placeholders.
    # Replace each failure with a concrete structural check (AST/FS) that enforces
    # the assertion on the codebase once implementation work begins.
    failures: List[str] = []
    for idx, rule in enumerate(asserts, start=1):
        # Comment: What is being asserted from the spec
        # f"assert: {rule}"
        failures.append(
            f"[{section_id}] Missing enforcement for assertion #{idx}: {rule}"
        )

    if failures:
        pytest.fail(
            "\n".join(
                [
                    f"EPIC I — Conditional Visibility — Section {section_id}: {section_title}",
                    "Unimplemented architectural enforcement rules:",
                    *failures,
                ]
            )
        )


def test_epic_i_spec_file_exists_and_is_parseable():
    """Sanity check: the EPIC I spec file exists and contains Section 7.1.

    This guards against accidental deletion or misnaming of the authoritative
    spec document that drives these architectural tests.
    """
    assert SPEC_PATH.exists(), (
        f"Missing specification file: {SPEC_PATH}. Expected EPIC I spec to be present."
    )

    text, err = _read_text(SPEC_PATH)
    if err:
        pytest.fail(err)
    # Ensure at least one 7.1.x heading and one assert: line exist
    sections = _extract_7_1_sections(text or "")
    assert sections, "No 7.1.x subsections found in the spec — add 7.1.* headings."
    has_any_assert = any(s.get("asserts") for s in sections)
    assert has_any_assert, (
        "No 'assert:' lines were found under Section 7.1 — add explicit assertions "
        "for each 7.1.x subsection."
    )
