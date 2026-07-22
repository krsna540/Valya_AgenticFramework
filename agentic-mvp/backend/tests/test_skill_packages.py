"""Tests for this app's canonical Skill folder format: SKILL.md frontmatter
parsing/validation, the optional skill.json triggers/hooks sidecar (both in
app/skills/package_spec.py), and zip extraction/round-trip
(app/skills/package_extract.py). No DB/HTTP — these are the modules with
real logic (parsing untrusted text, safely extracting an untrusted zip); the
route layer (app/api/routes/skills.py) is thin CRUD glue over them.
"""
import io
import tempfile
import zipfile
from pathlib import Path

import pytest

from app.skills.package_extract import SkillPackageExtractError, extract_skill_zip, zip_package
from app.skills.package_spec import (
    SkillPackageValidationError,
    parse_and_validate_skill_json,
    parse_and_validate_skill_md,
)

# --- package_spec.py: SKILL.md parsing ---------------------------------

MINIMAL = """---
name: skill-name
description: A description of what this skill does and when to use it.
---
"""

WITH_OPTIONALS = """---
name: pdf-processing
description: Extract PDF text, fill forms, merge files. Use when handling PDFs.
license: Apache-2.0
compatibility: Requires Python 3.14+ and uv
metadata:
  author: example-org
  version: "1.0"
allowed-tools: Bash(git:*) Read
---

# PDF Processing

Step 1. Do the thing.
"""


def test_parses_minimal_frontmatter():
    parsed = parse_and_validate_skill_md(MINIMAL, dir_name="skill-name")
    assert parsed.name == "skill-name"
    assert parsed.description.startswith("A description")
    assert parsed.license is None
    assert parsed.compatibility is None
    assert parsed.metadata == {}
    assert parsed.allowed_tools is None
    assert "SKILL.md body" in parsed.warnings[0]


def test_parses_all_optional_fields():
    parsed = parse_and_validate_skill_md(WITH_OPTIONALS, dir_name="pdf-processing")
    assert parsed.name == "pdf-processing"
    assert parsed.license == "Apache-2.0"
    assert parsed.compatibility == "Requires Python 3.14+ and uv"
    assert parsed.metadata == {"author": "example-org", "version": "1.0"}
    assert parsed.allowed_tools == "Bash(git:*) Read"
    assert "Step 1" in parsed.body_markdown
    assert parsed.warnings == []


@pytest.mark.parametrize(
    "name",
    ["PDF-Processing", "-pdf", "pdf-", "pdf--processing", "pdf_processing", "pdf processing", "a" * 65],
)
def test_rejects_invalid_names(name):
    raw = f"---\nname: {name}\ndescription: valid description\n---\n"
    with pytest.raises(SkillPackageValidationError):
        parse_and_validate_skill_md(raw, dir_name=name)


@pytest.mark.parametrize("name", ["pdf-processing", "a", "a1-b2-c3", "data-analysis"])
def test_accepts_valid_names(name):
    raw = f"---\nname: {name}\ndescription: valid description\n---\n"
    parsed = parse_and_validate_skill_md(raw, dir_name=name)
    assert parsed.name == name


def test_rejects_missing_name():
    raw = "---\ndescription: valid description\n---\n"
    with pytest.raises(SkillPackageValidationError) as exc:
        parse_and_validate_skill_md(raw)
    assert any("name" in e for e in exc.value.errors)


def test_rejects_missing_description():
    raw = "---\nname: my-skill\n---\n"
    with pytest.raises(SkillPackageValidationError) as exc:
        parse_and_validate_skill_md(raw)
    assert any("description" in e for e in exc.value.errors)


def test_rejects_description_too_long():
    raw = "---\nname: my-skill\ndescription: " + ("x" * 1025) + "\n---\n"
    with pytest.raises(SkillPackageValidationError) as exc:
        parse_and_validate_skill_md(raw)
    assert any("description" in e for e in exc.value.errors)


def test_rejects_compatibility_too_long():
    raw = "---\nname: my-skill\ndescription: ok\ncompatibility: " + ("x" * 501) + "\n---\n"
    with pytest.raises(SkillPackageValidationError) as exc:
        parse_and_validate_skill_md(raw)
    assert any("compatibility" in e for e in exc.value.errors)


def test_rejects_name_directory_mismatch():
    raw = "---\nname: foo\ndescription: ok\n---\n"
    with pytest.raises(SkillPackageValidationError) as exc:
        parse_and_validate_skill_md(raw, dir_name="bar")
    assert any("directory name" in e for e in exc.value.errors)


def test_collects_multiple_errors_at_once():
    raw = "---\nname: BAD_NAME\n---\n"  # missing description AND invalid name
    with pytest.raises(SkillPackageValidationError) as exc:
        parse_and_validate_skill_md(raw)
    assert len(exc.value.errors) == 2


def test_rejects_missing_frontmatter():
    with pytest.raises(SkillPackageValidationError):
        parse_and_validate_skill_md("# Just a markdown file, no frontmatter\n")


def test_rejects_unclosed_frontmatter():
    with pytest.raises(SkillPackageValidationError):
        parse_and_validate_skill_md("---\nname: x\ndescription: y\n")


def test_rejects_invalid_yaml():
    with pytest.raises(SkillPackageValidationError):
        parse_and_validate_skill_md("---\nname: [unterminated\n---\n")


def test_warns_on_unknown_frontmatter_fields():
    raw = "---\nname: my-skill\ndescription: ok\nfrobnicate: true\n---\nbody\n"
    parsed = parse_and_validate_skill_md(raw, dir_name="my-skill")
    assert any("frobnicate" in w for w in parsed.warnings)


def test_metadata_values_coerced_to_strings():
    raw = "---\nname: my-skill\ndescription: ok\nmetadata:\n  version: 1.0\n  count: 3\n---\n"
    parsed = parse_and_validate_skill_md(raw, dir_name="my-skill")
    assert parsed.metadata == {"version": "1.0", "count": "3"}


# --- package_extract.py: zip extraction ---------------------------------


def _make_zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_extracts_valid_skill_package():
    data = _make_zip(
        {
            "pdf-processing/SKILL.md": "---\nname: pdf-processing\ndescription: x\n---\nbody",
            "pdf-processing/scripts/extract.py": "print('hi')",
            "pdf-processing/references/REFERENCE.md": "# Ref",
        }
    )
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "pkg"
        result = extract_skill_zip(data, dest, max_extracted_bytes=10_000_000, max_files=500)
        assert result.root_dir_name == "pdf-processing"
        assert set(result.file_manifest) == {"SKILL.md", "scripts/extract.py", "references/REFERENCE.md"}
        assert (dest / "SKILL.md").exists()
        assert (dest / "scripts" / "extract.py").exists()


def test_round_trip_zip_matches_manifest():
    data = _make_zip({"my-skill/SKILL.md": "---\nname: my-skill\ndescription: x\n---\n"})
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "pkg"
        result = extract_skill_zip(data, dest, max_extracted_bytes=10_000_000, max_files=500)
        rezipped = zip_package(dest, "my-skill")
        names = zipfile.ZipFile(io.BytesIO(rezipped)).namelist()
        assert names == [f"my-skill/{p}" for p in result.file_manifest]


def test_rejects_zip_slip():
    data = _make_zip({"evil/SKILL.md": "x", "evil/../../../etc/passwd": "pwned"})
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(SkillPackageExtractError, match="Unsafe path"):
            extract_skill_zip(data, Path(td) / "pkg", max_extracted_bytes=10_000_000, max_files=500)


def test_rejects_missing_skill_md():
    data = _make_zip({"foo/readme.txt": "hi"})
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(SkillPackageExtractError, match="SKILL.md"):
            extract_skill_zip(data, Path(td) / "pkg", max_extracted_bytes=10_000_000, max_files=500)


def test_rejects_multiple_top_level_dirs():
    data = _make_zip({"a/SKILL.md": "x", "b/file.txt": "y"})
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(SkillPackageExtractError, match="exactly one top-level"):
            extract_skill_zip(data, Path(td) / "pkg", max_extracted_bytes=10_000_000, max_files=500)


def test_rejects_empty_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(SkillPackageExtractError, match="no files"):
            extract_skill_zip(buf.getvalue(), Path(td) / "pkg", max_extracted_bytes=10_000_000, max_files=500)


def test_rejects_zip_bomb_by_declared_size():
    data = _make_zip({"my-skill/SKILL.md": "x" * 1000})
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(SkillPackageExtractError, match="byte limit"):
            extract_skill_zip(data, Path(td) / "pkg", max_extracted_bytes=100, max_files=500)


def test_rejects_too_many_files():
    entries = {"my-skill/SKILL.md": "x"}
    for i in range(10):
        entries[f"my-skill/scripts/f{i}.txt"] = "x"
    data = _make_zip(entries)
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(SkillPackageExtractError, match="exceeding the 5 limit"):
            extract_skill_zip(data, Path(td) / "pkg", max_extracted_bytes=10_000_000, max_files=5)


def test_rejects_invalid_zip_bytes():
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(SkillPackageExtractError, match="Not a valid zip"):
            extract_skill_zip(b"not a zip file", Path(td) / "pkg", max_extracted_bytes=10_000_000, max_files=500)


# --- package_spec.py: skill.json (triggers & hooks manifest) ----------------


def test_skill_json_empty_is_valid():
    parsed = parse_and_validate_skill_json("")
    assert parsed.name is None
    assert parsed.trigger_keywords == []
    assert parsed.hooks == []


def test_skill_json_parses_full_manifest():
    from app.services.hooks import BUILTIN_HOOKS

    known_hook = next(iter(BUILTIN_HOOKS))
    raw = f"""{{
        "name": "run-validator",
        "version": "1.0.0",
        "triggers": {{
            "keywords": ["validate", "lint"],
            "intents": ["code_review"],
            "lifecycle_events": ["UserPromptSubmit"]
        }},
        "hooks": ["{known_hook}"]
    }}"""
    parsed = parse_and_validate_skill_json(raw, skill_md_name="run-validator")
    assert parsed.name == "run-validator"
    assert parsed.version == "1.0.0"
    assert parsed.trigger_keywords == ["validate", "lint"]
    assert parsed.trigger_intents == ["code_review"]
    assert parsed.trigger_lifecycle_events == ["UserPromptSubmit"]
    assert parsed.hooks == [known_hook]


def test_skill_json_rejects_name_mismatch_with_skill_md():
    raw = '{"name": "other-name"}'
    with pytest.raises(SkillPackageValidationError, match="must match SKILL.md"):
        parse_and_validate_skill_json(raw, skill_md_name="run-validator")


def test_skill_json_rejects_unknown_lifecycle_event():
    raw = '{"triggers": {"lifecycle_events": ["NotARealStage"]}}'
    with pytest.raises(SkillPackageValidationError, match="unknown stage"):
        parse_and_validate_skill_json(raw)


def test_skill_json_rejects_unknown_hook():
    raw = '{"hooks": ["not_a_real_hook"]}'
    with pytest.raises(SkillPackageValidationError, match="unknown handler_key"):
        parse_and_validate_skill_json(raw)


def test_skill_json_rejects_invalid_json():
    with pytest.raises(SkillPackageValidationError, match="not valid JSON"):
        parse_and_validate_skill_json("{not valid json")


def test_skill_json_rejects_non_object():
    with pytest.raises(SkillPackageValidationError, match="must be a JSON object"):
        parse_and_validate_skill_json("[1, 2, 3]")


def test_skill_json_warns_on_unknown_top_level_field():
    parsed = parse_and_validate_skill_json('{"unexpected_field": true}')
    assert any("unexpected_field" in w for w in parsed.warnings)
