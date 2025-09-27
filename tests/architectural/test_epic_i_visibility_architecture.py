"""Architectural tests for EPIC-I — Conditional Visibility (Section 7.1).

These tests are authored first (TDD) to enforce the architectural
assertions defined in the spec at:
  docs/api/Epic I - Conditional Visibility.md

Rules:
- Exactly one test per 7.1.x section; do not combine or split.
- Tests must rely on static inspection only (no runtime side effects).
- On parsing errors, fail with a clear assertion instead of crashing.

Note: Tests are generated 1:1 with spec sections (7.1.x), and each is
intentionally failing until concrete static checks are implemented to
enforce every "assert:" line. This preserves strict TDD and avoids
side effects by relying only on file I/O and static analysis readiness.
"""

from __future__ import annotations

import os
import re
from typing import List, Tuple

import pytest


SPEC_PATH = os.path.join("docs", "api", "Epic I - Conditional Visibility.md")


def _read_text(path: str) -> str:
    """Read text file contents, failing clearly on error.

    Runner stability: do not raise arbitrary exceptions from import-time.
    """
    if not os.path.exists(path):
        # Do not call pytest.fail() during import-time; raise and
        # convert to an assertion within an actual test body.
        raise FileNotFoundError(
            f"Required spec not found: {path}. Add the EPIC-I spec before implementing architecture checks."
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        # Avoid failing at import-time; surface within tests.
        raise IOError(f"Failed to read spec at {path}: {exc}")


Section = Tuple[str, str, List[str]]  # (section_id, title, assert_lines)


def _parse_7_1_sections(md: str) -> List[Section]:
    """Extract 7.1.x sections and their 'assert:' lines from Markdown.

    - Matches headings like: `7.1.3 – Title` (accepts -, –, — dashes)
    - Collects consecutive lines until the next 7.1.* heading
    - Within each section, collects lines beginning with 'assert:' (case-insensitive)
    """
    # Normalize newlines
    lines = md.splitlines()

    # Regex that tolerates ASCII hyphen and a range of Unicode dashes
    dash = r"[-\u2012-\u2015]"  # includes en/em/minus variants
    heading_re = re.compile(rf"^(7\.1\.(\d+))\s*{dash}\s*(.+?)\s*$")

    # Accept bare `assert:` as well as bullet/numbered list forms like:
    # - assert: ...
    # * assert: ...
    # 1. assert: ...
    # 1) assert: ...
    assert_re = re.compile(r"^(?:[-*+]|\d+[\.)])?\s*assert\s*:\s*(.+)$", re.IGNORECASE)

    sections: List[Section] = []
    current: Tuple[str, str, List[str]] | None = None

    def flush_current():
        nonlocal current
        if current is not None:
            sections.append(current)
            current = None

    for line in lines:
        m = heading_re.match(line.strip())
        if m:
            # Start a new section
            flush_current()
            sec_id, _num, title = m.group(1), m.group(2), m.group(3).strip()
            current = (sec_id, title, [])
        else:
            if current is None:
                continue
            # Collect assert: lines (including common list/bullet prefixes)
            stripped = line.strip()
            m_assert = assert_re.match(stripped)
            if m_assert:
                payload = m_assert.group(1).strip()
                # Normalize spacing while preserving the original text for readability
                current[2].append("assert: " + payload)

    flush_current()
    # Ensure stable ordering by numeric sub-section index (7.1.N)
    try:
        sections.sort(key=lambda s: int(s[0].split(".")[-1]))
    except Exception:
        # If anything odd, keep discovered order to avoid raising during collection
        pass
    return sections


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _generate_test_for_section(sec: Section):
    sec_id, title, assert_lines = sec
    fn_name = f"test_epic_i_{sec_id.replace('.', '_')}_{_slugify(title)[:40]}"

    def _test():
        """EPIC-I {sec_id} — {title}

        Section {sec_id} (7.1.x) — one dedicated test.
        The section declares architectural assertions that MUST be
        validated via static inspection only (no runtime side effects).
        """

        # Section reference (explicit comment per instructions)
        # Verifies section {sec_id} — {title}

        # Asserts declared in spec (listed for reviewer clarity)
        for i, line in enumerate(assert_lines, start=1):
            # This loop exists to surface each assertion item in failure output
            # and to make the test intent explicit without executing app code.
            _ = (i, line)  # no-op; aids readability in tracebacks

        # Placeholder failure to uphold strict TDD. Replace this with
        # concrete static checks that enforce every 'assert:' statement
        # for this specific section.
        details = "\n - " + "\n - ".join(assert_lines) if assert_lines else "\n (No 'assert:' lines parsed — update spec.)"
        pytest.fail(
            f"Pending: implement static validations for EPIC-I {sec_id} — {title}.{details}"
        )

    _test.__name__ = fn_name
    _test.__doc__ = f"EPIC-I {sec_id} — {title} (one test per section)."
    globals()[fn_name] = _test


def _bootstrap_dynamic_tests():
    # Parse the spec and generate one failing test per 7.1.x section.
    md = _read_text(SPEC_PATH)
    sections = _parse_7_1_sections(md)
    if not sections:
        # Avoid pytest.fail during import-time
        raise ValueError(
            "No 7.1.x sections were discovered in the EPIC-I spec. Add 7.1.x headings with 'assert:' lines."
        )
    for sec in sections:
        _generate_test_for_section(sec)


def test_epic_i_spec_file_present_and_parsable():
    """Sanity: EPIC-I spec exists and exposes at least one 7.1.x section.

    This test ensures runner stability and provides an actionable
    failure if the spec is missing or malformed.
    """
    try:
        md = _read_text(SPEC_PATH)
        sections = _parse_7_1_sections(md)
    except (FileNotFoundError, IOError, ValueError) as exc:
        pytest.fail(str(exc))
    assert sections, "Expected to find at least one '7.1.x – <title>' section in EPIC-I spec."


# Generate section-specific tests at import-time (safe; failures are captured via pytest)
try:  # pragma: no cover - exercised by pytest collection
    _bootstrap_dynamic_tests()
except Exception as _exc:  # Safety net to avoid crashing test discovery
    # Convert unexpected bootstrap errors into a clear, single failure. Capture the
    # message as a default argument to avoid NameError due to exception scoping rules.
    _msg = f"Failed to generate EPIC-I 7.1.x tests from spec at {SPEC_PATH}: {_exc}"

    def test_epic_i_dynamic_generation_failed(msg: str = _msg):  # noqa: D401
        """Dynamic generation failed; see assertion for details."""

        pytest.fail(msg)
