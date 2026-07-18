"""elicit_client_spec — chat -> validated ClientSpec via a MOCK teacher."""

from __future__ import annotations

import json

import pytest

from open_agent_compiler.personalization import (
    ClientSpec,
    SpecElicitationError,
    elicit_client_spec,
    parse_client_spec,
)

from .conftest import FakeTeacher


def test_elicit_returns_validated_spec(valid_spec_payload: dict) -> None:
    teacher = FakeTeacher.returning_spec_json(valid_spec_payload)
    spec = elicit_client_spec("client: I want email triage...", teacher)
    assert isinstance(spec, ClientSpec)
    assert spec.goal.startswith("Triage")
    assert len(spec.example_tasks) == 2
    assert spec.example_tasks[1].expected_outcome == ""  # empty preserved
    assert "Never promise a refund" in spec.constraints
    assert len(spec.success_criteria) == 3


def test_elicit_passes_transcript_to_teacher(valid_spec_payload: dict) -> None:
    teacher = FakeTeacher.returning_spec_json(valid_spec_payload)
    elicit_client_spec("MAGIC_TRANSCRIPT_MARKER", teacher, model="glm-5.1")
    assert len(teacher.calls) == 1
    system, user, model = teacher.calls[0]
    assert "MAGIC_TRANSCRIPT_MARKER" in user
    assert "STRICT JSON" in system
    assert model == "glm-5.1"


def test_elicit_tolerates_json_fences(valid_spec_payload: dict) -> None:
    fenced = "```json\n" + json.dumps(valid_spec_payload) + "\n```"
    spec = elicit_client_spec("chat", FakeTeacher(fenced))
    assert spec.goal.startswith("Triage")


def test_elicit_extracts_object_with_preamble(valid_spec_payload: dict) -> None:
    noisy = "Sure! Here is the spec:\n" + json.dumps(valid_spec_payload) + "\nDone."
    spec = elicit_client_spec("chat", FakeTeacher(noisy))
    assert len(spec.example_tasks) == 2


def test_elicit_empty_transcript_raises() -> None:
    with pytest.raises(SpecElicitationError, match="empty"):
        elicit_client_spec("   ", FakeTeacher("{}"))


def test_elicit_empty_teacher_output_raises() -> None:
    with pytest.raises(SpecElicitationError, match="empty"):
        elicit_client_spec("chat", FakeTeacher(""))


def test_elicit_no_json_raises() -> None:
    with pytest.raises(SpecElicitationError, match="no JSON"):
        elicit_client_spec("chat", FakeTeacher("I cannot help with that."))


def test_elicit_malformed_json_raises() -> None:
    with pytest.raises(SpecElicitationError, match="not valid JSON"):
        elicit_client_spec("chat", FakeTeacher('{"goal": "x", oops}'))


def test_elicit_missing_goal_raises() -> None:
    with pytest.raises(SpecElicitationError, match="goal"):
        elicit_client_spec("chat", FakeTeacher('{"example_tasks": []}'))


def test_parse_coerces_bare_string_example_task() -> None:
    raw = json.dumps(
        {"goal": "g", "example_tasks": ["just a string task"], "success_criteria": ["ok"]}
    )
    spec = parse_client_spec(raw)
    assert spec.example_tasks[0].prompt == "just a string task"
    assert spec.example_tasks[0].expected_outcome == ""


def test_parse_skips_empty_example_tasks() -> None:
    raw = json.dumps(
        {
            "goal": "g",
            "example_tasks": [{"prompt": "   "}, {"prompt": "real"}],
            "success_criteria": ["ok"],
        }
    )
    spec = parse_client_spec(raw)
    assert [t.prompt for t in spec.example_tasks] == ["real"]


def test_parse_bare_string_preferences() -> None:
    raw = json.dumps({"goal": "g", "preferences": "be nice"})
    spec = parse_client_spec(raw)
    assert spec.preferences == ("be nice",)


def test_parse_rejects_non_string_list_entries() -> None:
    raw = json.dumps({"goal": "g", "constraints": [123]})
    with pytest.raises(SpecElicitationError, match="must be strings"):
        parse_client_spec(raw)


def test_elicit_require_usable_raises_on_partial_spec() -> None:
    raw = json.dumps({"goal": "g", "example_tasks": [], "success_criteria": []})
    # without require_usable, a partial-but-valid spec is returned fine
    spec = elicit_client_spec("chat", FakeTeacher(raw))
    assert spec.is_usable is False
    # with require_usable, the missing example_tasks trips the stronger contract
    with pytest.raises(ValueError, match="not usable"):
        elicit_client_spec("chat", FakeTeacher(raw), require_usable=True)
