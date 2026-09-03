"""Phase-4 contracts: literal facts, one judge, trusted checks, and precedence."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import sys
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from skillroll import checks as checks_module
from skillroll.artifacts import store as store_module
from skillroll.artifacts.records import (
    checks_bytes,
    execution_bytes,
    experiment_report_bytes,
    final_report_bytes,
    judge_bytes,
    verdict_bytes,
)
from skillroll.artifacts.store import ArtifactError, ArtifactStore
from skillroll.assertions import evaluate_assertions
from skillroll.checks import (
    CheckRequest,
    CheckResult,
    HostCheckRunner,
    check_environment,
    redact_check_result,
    skipped_check,
)
from skillroll.commands import evaluate
from skillroll.commands import validate as validate_command
from skillroll.diagnostics import CommandResult, SourceLocation
from skillroll.evals import _assertion_data, _parse_assertions, parse_eval_case
from skillroll.inference.profile import (
    InferenceFailure,
    InferenceFailureKind,
    ResolvedInference,
    SecretRedactor,
    SecretValue,
)
from skillroll.inference.transport import (
    ChatRequest,
    ChatResponse,
    ModelUsage,
    ToolCall,
    TransportFailure,
)
from skillroll.judge import (
    MAX_JUDGE_BYTES,
    JudgeResult,
    _parse,
    criteria_items,
    estimate_judge_output_tokens,
    judge,
    judge_request,
)
from skillroll.models import (
    Assertion,
    CaseLimits,
    DeclaredCheck,
    EvalCase,
    GuardSettings,
    InferenceLimits,
    InferenceSettings,
    ModelPricing,
    ModelProfile,
    Skill,
    SkillRollConfig,
    ValidationReport,
)
from skillroll.outcomes import Outcome
from skillroll.runtime.attempt import PreliminaryAttempt
from skillroll.runtime.execution import (
    ExecutionResult,
    omitted_skill_instructions,
    wrapped_instructions,
)
from skillroll.verdicts import CaseResult, aggregate, case_outcome
from skillroll.world.bundle import SKILL_WARNING_BYTES, BundleWarning
from skillroll.world.session import WorldEvent


def _python_shell_command(source: str) -> str:
    arguments = [sys.executable, "-c", source]
    return (
        subprocess.list2cmdline(arguments) if os.name == "nt" else shlex.join(arguments)
    )


class Transport:
    def __init__(self, value: ChatResponse) -> None:
        self.value = value
        self.requests: list[ChatRequest] = []
        self.closed = False

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return self.value

    async def close(self) -> None:
        self.closed = True


class RaisingTransport(Transport):
    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        assert isinstance(self.value, Exception)
        raise self.value


class RuntimeErrorTransport(Transport):
    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        raise RuntimeError("secret failed")


class ScriptedTransport(Transport):
    def __init__(self, values: list[ChatResponse]) -> None:
        super().__init__(values[0])
        self.values = values

    async def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return self.values.pop(0)


class Executor:
    async def execute(self, request: object, world_action: object) -> object:
        assert callable(world_action)
        await world_action("Write", {"path": "overview.md"})
        from skillroll.runtime.execution import ExecutionAttempt

        return ExecutionAttempt(ExecutionResult("overview written", 1, (), ()), None)


class PassingRunner:
    async def run(self, request: CheckRequest, environment: object) -> CheckResult:
        del environment
        return CheckResult(request.check, "PASS", 0, "", "", 0.01)


def profile() -> ResolvedInference:
    return ResolvedInference(
        "https://example.test/v1", "tiny", SecretValue("secret"), InferenceLimits()
    )


def test_default_evaluator_factories_create_local_adapters() -> None:
    transport = evaluate._transport(profile())
    try:
        assert transport is not None
        assert evaluate._executor(profile()) is not None
    finally:
        asyncio.run(transport.close())
    assert evaluate._usage(None) is None


def test_cost_estimate_requires_explicit_complete_usage() -> None:
    usage = {
        "status": "observed",
        "calls": [
            {
                "input_tokens": 100,
                "output_tokens": 50,
            }
        ],
    }
    estimate = evaluate._estimate_cost((usage,), ModelPricing(0.4, 1.6), "USD")
    assert estimate == {
        "status": "estimated",
        "currency": "USD",
        "amount": 0.00012,
        "input_per_million": 0.4,
        "output_per_million": 1.6,
    }
    missing = evaluate._estimate_cost(
        ({"status": "unavailable", "calls": [{"input_tokens": None}]},),
        ModelPricing(0.4, 1.6),
    )
    assert missing["status"] == "unavailable"
    assert "zero" not in str(missing).lower()
    assert evaluate._estimate_cost((usage,), None)["status"] == "unavailable"


def test_usage_world_and_status_helpers_keep_states_separate() -> None:
    usage = ModelUsage(10, 4, 14)
    assert evaluate._usage((usage,)) == [
        {
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "cache_read_tokens": None,
        }
    ]
    assert evaluate._usage(usage) == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
        "cache_read_tokens": None,
    }
    event = WorldEvent(
        0,
        "Write",
        {},
        "ok",
        "world_model",
        model="served/model",
        usage=usage,
    )
    assert evaluate._world_usage((event,), "requested/model")["status"] == "observed"

    check = DeclaredCheck("check", "unused", (), SourceLocation())
    for outcome, expected in (
        ("ERROR", "failed"),
        ("FAIL", "failed"),
        ("SKIPPED", "not_run"),
    ):
        value = CheckResult(check, outcome, None, "", "", None)
        assert evaluate._trusted_status((value,)) == expected

    pricing = ModelPricing(1.0, 1.0)
    assert evaluate._estimate_cost(({"calls": "invalid"},), pricing)["status"] == (
        "unavailable"
    )
    assert evaluate._estimate_cost(({"calls": []},), pricing)["reason"] == (
        "no provider usage recorded"
    )
    cached = evaluate._estimate_cost(
        (
            {
                "calls": [
                    {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_read_tokens": 40,
                    }
                ]
            },
        ),
        ModelPricing(1.0, 2.0, 0.5),
    )
    assert cached["amount"] == 0.00018
    assert cached["cache_read_per_million"] == 0.5
    assert (
        evaluate._estimate_cost(
            (
                {
                    "calls": [
                        {
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "cache_read_tokens": 40,
                        }
                    ]
                },
            ),
            ModelPricing(1.0, 2.0),
        )["status"]
        == "unavailable"
    )
    assert (
        evaluate._estimate_cost(
            (
                {
                    "calls": [
                        {
                            "input_tokens": 10,
                            "output_tokens": 1,
                            "cache_read_tokens": 11,
                        }
                    ]
                },
            ),
            ModelPricing(1.0, 2.0, 0.5),
        )["status"]
        == "unavailable"
    )


def test_overall_explanations_name_the_independent_failure_source() -> None:
    passing = JudgeResult("PASS", "It met the criteria.", (), None, None)
    failing = JudgeResult("FAIL", "It missed a criterion.", ("criterion",), None, None)
    failed_fact = evaluate_assertions(
        (Assertion("final_output_contains", expected_text="required"),), "other"
    )
    check = DeclaredCheck("check", "unused", (), SourceLocation())
    skipped = CheckResult(check, "SKIPPED", None, "", "", None)
    failed_check = CheckResult(check, "FAIL", 1, "", "", 0.1)

    assert "could not check" in evaluate._overall_text("FAIL", None, (), (), None)[0]
    assert "did not meet" in evaluate._overall_text("FAIL", failing, (), (), None)[0]
    assert (
        "exact output check"
        in evaluate._overall_text("FAIL", passing, failed_fact, (), None)[0]
    )
    assert (
        "not run"
        in evaluate._overall_text("INCOMPLETE", passing, (), (skipped,), None)[0]
    )
    assert (
        "repository check"
        in evaluate._overall_text("FAIL", passing, (), (failed_check,), None)[0]
    )


def test_failure_stage_defaults_are_stable() -> None:
    assert (
        evaluate._failure_stage(
            InferenceFailure(
                InferenceFailureKind.EXECUTION_ERROR, "broken", stage="world"
            )
        )
        == "world"
    )
    assert (
        evaluate._failure_stage(
            InferenceFailure(InferenceFailureKind.JUDGE_INTEGRITY, "broken")
        )
        == "semantic_judgment"
    )


def test_result_separates_completed_execution_from_judge_failure(
    tmp_path: Path,
) -> None:
    case = case_at(tmp_path)
    summary = evaluate._result_summary(
        case,
        "ERROR",
        ExecutionResult("done", 2, (), ()),
        (),
        InferenceLimits(),
        None,
        (),
        (),
        InferenceFailure(
            InferenceFailureKind.JUDGE_INTEGRITY,
            "The judge response was contradictory.",
            stage="semantic_judgment",
        ),
        "provider/model",
        failure_stage="semantic_judgment",
    )
    execution = summary["execution"]
    technical = summary["technical_status"]
    assert isinstance(execution, dict)
    assert isinstance(technical, dict)
    assert execution["status"] == "completed"
    assert execution["final_response_produced"] is True
    assert technical["stage"] == "semantic_judgment"


def preflight_responses() -> list[ChatResponse]:
    return [
        ChatResponse(
            None,
            (ToolCall("id", "skillroll_preflight", {"value": "ready"}),),
            "tiny",
            None,
        ),
        ChatResponse('{"status":"ready"}', (), "tiny", None),
        ChatResponse("simulated write", (), "tiny", None),
        ChatResponse(
            '{"verdict":"PASS","rationale":"The output and action satisfy '
            'the criteria.","criteria":[{"criterion":"success",'
            '"status":"met","evidence":"The final response and transcript '
            'support the criterion."}],"unmet_criteria":[]}',
            (),
            "tiny",
            ModelUsage(12, 4, 16),
        ),
    ]


def case_at(tmp_path: Path, check: DeclaredCheck | None = None) -> EvalCase:
    root = tmp_path / "skills" / "review"
    root.mkdir(parents=True)
    skill_file = root / "SKILL.md"
    skill_file.write_text("Write an overview.", encoding="utf-8")
    eval_file = root / "evals" / "basic.eval.md"
    eval_file.parent.mkdir()
    eval_file.write_text("case", encoding="utf-8")
    skill = Skill(
        "review", PurePosixPath("skills/review"), root, skill_file, eval_file.parent
    )
    return EvalCase(
        eval_file,
        PurePosixPath("skills/review/evals/basic.eval.md"),
        skill,
        None,
        "input",
        "world",
        "success",
        () if check is None else (check,),
    )


def test_literal_assertions_are_independent_and_exact() -> None:
    values = (
        Assertion("final_output_contains", expected_text="done"),
        Assertion("final_output_not_contains", expected_text="secret"),
        Assertion("final_output_equals", expected_text="done"),
    )
    results = evaluate_assertions(values, "done")
    assert [item.passed for item in results] == [True, True, True]
    assert results[-1].ordinal == 3

    leaked = evaluate_assertions(
        (Assertion("final_output_not_contains", expected_text="secret"),),
        "leaked secret",
    )
    assert leaked[0].passed is False
    assert leaked[0].observed == "final output contained the forbidden literal"


def test_assertion_evaluator_rejects_an_unparsed_predicate() -> None:
    with pytest.raises(AssertionError, match="Unsupported assertion kind"):
        evaluate_assertions((Assertion("unsupported", expected_text="x"),), "x")


@pytest.mark.parametrize(
    "metadata",
    [
        "assertions: nope",
        "assertions: []",
        "assertions: [{unknown: x}]",
        "assertions: [{final_output_contains: ''}]",
        "assertions: [{final_output_not_contains: ''}]",
        "assertions: [{final_output_equals: 7}]",
        "assertions: [{action_count_at_most: true}]",
        "assertions: [{action_count_at_least: 33}]",
        "assertions: [{action_occurred: {}}]",
        "assertions: [{action_occurred: {tool_name: X, arguments: []}}]",
        "assertions: [{action_occurred: {tool_name: X, source: wrong}}]",
    ],
)
def test_parser_rejects_every_assertion_shape(tmp_path: Path, metadata: str) -> None:
    case = case_at(tmp_path)
    case.path.write_text(
        "# Case\n\n```skillroll\nschema_version: 1\n"
        + metadata
        + "\n```\n\n## Input\na\n\n## World\nb\n\n## Success criteria\nc\n",
        encoding="utf-8",
    )
    assert parse_eval_case(case.path, case.skill).value is None


def test_removed_action_assertion_explains_the_semantic_alternative(
    tmp_path: Path,
) -> None:
    case = case_at(tmp_path)
    case.path.write_text(
        "# Case\n\n```skillroll\nschema_version: 1\n"
        "assertions: [{action_occurred: {tool_name: Write}}]\n"
        "```\n\n## Input\na\n\n## World\nb\n\n## Success criteria\nc\n",
        encoding="utf-8",
    )
    parsed = parse_eval_case(case.path, case.skill)
    assert parsed.value is None
    assert "Action assertions are not supported" in parsed.diagnostics[0].summary
    assert "Success criteria" in parsed.diagnostics[0].summary


def test_parser_accepts_and_rejects_duplicate_assertion(tmp_path: Path) -> None:
    case = case_at(tmp_path)
    base = """# Case

```skillroll
schema_version: 1
assertions:
  - final_output_contains: done
```

## Input
a

## World
b

## Success criteria
c
"""
    case.path.write_text(base, encoding="utf-8")
    parsed = parse_eval_case(case.path, case.skill)
    assert parsed.value is not None
    assert parsed.value.assertions[0].expected_text == "done"
    case.path.write_text(
        base.replace(
            "```\n\n## Input",
            "  - final_output_contains: done\n```\n\n## Input",
        ),
        encoding="utf-8",
    )
    assert parse_eval_case(case.path, case.skill).value is None


def test_assertion_parser_covers_all_valid_forms_and_invalid_nested_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "case.eval.md"
    parsed, errors = _parse_assertions(
        [
            {"final_output_contains": "text"},
            {"final_output_not_contains": "secret"},
            {"final_output_equals": ""},
            7,
        ],
        path,
        1,
    )
    assert len(parsed) == 3 and len(errors) == 1
    oversized = {"x": "y" * (17 * 1024)}
    _, errors = _parse_assertions(
        [{"action_occurred": {"tool_name": "Write", "arguments": oversized}}],
        path,
        1,
    )
    assert errors
    assert _assertion_data(Assertion("final_output_equals", expected_text="")) == {
        "final_output_equals": ""
    }


def test_judge_renders_only_observed_evidence_and_calls_once(tmp_path: Path) -> None:
    case = case_at(tmp_path)
    execution = ExecutionResult("final", 1, (), ())
    request, failure = judge_request(
        profile(),
        case,
        execution,
        (WorldEvent(0, "Write", {}, "no", "rule", "denied"),),
    )
    assert failure is None and request is not None
    user = request.messages[1].content or ""
    assert "SKILL.md:" not in user
    assert "World:" not in user
    assert "Write an overview." not in user
    assert "Success criteria:" in user and "denied" in user
    assert user.index("Complete ordered actions:") < user.index("Final output:")
    assert request.tools == () and "secret" not in user
    assert request.temperature == 0.0
    assert request.response_format is not None
    assert request.response_format["type"] == "json_schema"
    json_schema = request.response_format["json_schema"]
    assert isinstance(json_schema, dict) and json_schema["strict"] is True
    schema = json_schema["schema"]
    assert isinstance(schema, dict)
    criteria_schema = schema["properties"]["criteria"]
    assert criteria_schema["minItems"] == criteria_schema["maxItems"] == 1
    assert set(criteria_schema["items"]["properties"]) == {"status", "evidence"}
    system = request.messages[0].content or ""
    assert "different tool spelling" in system
    assert "error or failure" in system
    assert "later Final output" in system
    assert "intermediate action result" in system
    assert "Do not soften or replace an explicit verdict label" in system
    transport = Transport(
        ChatResponse(
            '{"verdict":"PASS","rationale":"Observed evidence is '
            'enough.","criteria":[{'
            '"status":"met","evidence":"The final response supports '
            'the criterion."}],"unmet_criteria":[]}',
            (),
            "tiny",
            ModelUsage(1, 2, 3),
        )
    )
    result, failure = asyncio.run(judge(profile(), transport, case, execution, ()))
    assert (
        failure is None
        and result is not None
        and result.verdict == "PASS"
        and result.rationale == "Observed evidence is enough."
        and result.unmet_criteria == ()
    )
    assert len(transport.requests) == 1


def test_judge_parses_criterion_level_evidence_and_control_uses_same_judge_evidence(
    tmp_path: Path,
) -> None:
    case = case_at(tmp_path)
    parsed, failure = _parse(
        '{"verdict":"PASS","rationale":"supported",'
        '"criteria":[{"criterion":"first","status":"met",'
        '"evidence":"The response states the result."}],'
        '"unmet_criteria":[]}',
        False,
        ("first",),
    )
    assert failure is None and parsed is not None
    assert parsed.criteria[0].criterion == "first"
    assert parsed.criteria[0].status == "met"
    request, failure = judge_request(
        profile(),
        case,
        ExecutionResult("final", 1, (), ()),
        (),
        skill_available=False,
    )
    assert failure is None and request is not None
    user = request.messages[1].content or ""
    assert "SKILL.md:" not in user
    assert "World:" not in user
    assert "Write an overview." not in user
    assert "Criteria to assess:" in user
    assert "SKILL.md" not in omitted_skill_instructions()


def test_judge_accepts_legacy_empty_echoed_criterion_but_does_not_require_it() -> None:
    for assessment in (
        '{"status":"met","evidence":"The response states the result."}',
        '{"criterion":"","status":"met","evidence":"The response states the result."}',
    ):
        parsed, failure = _parse(
            '{"verdict":"PASS","rationale":"supported","criteria":['
            + assessment
            + '],"unmet_criteria":[]}',
            False,
            ("authored criterion",),
        )
        assert failure is None and parsed is not None
        assert parsed.criteria[0].criterion == "authored criterion"


def test_execution_instructions_preserve_action_terminology() -> None:
    instructions = wrapped_instructions("Use the child action described here.")
    assert "preserve the skill's intended action terminology" in instructions
    assert 'always use tool_name "Skill"' not in instructions
    assert "never put the step name in tool_name" not in instructions


def test_judge_rejects_ambiguous_or_tool_response(tmp_path: Path) -> None:
    case = case_at(tmp_path)
    result, failure = asyncio.run(
        judge(
            profile(),
            Transport(ChatResponse("maybe", (), None, None)),
            case,
            ExecutionResult("x", 1, (), ()),
            (),
        )
    )
    assert result is None and failure is not None


@pytest.mark.parametrize(
    ("assessment", "expected"),
    [
        (
            '{"criterion":"one","status":"no","evidence":"missing"}',
            "status must be exactly met, not_met, or unclear",
        ),
        (
            '{"criterion":"one","status":"not_met","evidence":""}',
            "evidence must be a non-empty string",
        ),
    ],
)
def test_judge_identifies_the_invalid_criterion_field(
    assessment: str, expected: str
) -> None:
    parsed, failure = _parse(
        '{"verdict":"FAIL","rationale":"incomplete","criteria":['
        + assessment
        + '],"unmet_criteria":["one"]}',
        False,
        ("one",),
    )
    assert parsed is None and failure is not None
    assert expected in failure.summary


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (ChatResponse("", (), None, None), InferenceFailureKind.MALFORMED_RESPONSE),
        (
            ChatResponse("PASS", (ToolCall("x", "x", {}),), None, None),
            InferenceFailureKind.MALFORMED_RESPONSE,
        ),
        (
            ChatResponse("FAIL\n" + "x" * 5000, (), None, None),
            InferenceFailureKind.MALFORMED_RESPONSE,
        ),
    ],
)
def test_judge_response_errors(
    tmp_path: Path, response: ChatResponse, kind: InferenceFailureKind
) -> None:
    result, failure = asyncio.run(
        judge(
            profile(),
            Transport(response),
            case_at(tmp_path),
            ExecutionResult("x", 1, (), ()),
            (),
        )
    )
    assert result is None and failure is not None and failure.kind is kind


def test_judge_reports_length_finish_reason_before_parsing(tmp_path: Path) -> None:
    result, failure = asyncio.run(
        judge(
            profile(),
            Transport(
                ChatResponse('{"verdict":"FAIL"', (), None, None, None, "length")
            ),
            case_at(tmp_path),
            ExecutionResult("x", 1, (), ()),
            (),
        )
    )
    assert result is None and failure is not None
    assert failure.kind is InferenceFailureKind.MALFORMED_RESPONSE
    assert "judge exhausted" in failure.summary
    assert "ERROR, not a skill FAIL" in failure.summary
    assert "max_output_tokens=8192" in failure.summary
    assert failure.details[0] == "provider finish_reason: length"
    assert any("1 criterion" in detail for detail in failure.details)
    assert "suggested diagnostic max_output_tokens: 16384" in failure.details
    assert any("skill and Dungeon Master" in detail for detail in failure.details)


def test_judge_output_estimate_scales_with_case_complexity() -> None:
    assert criteria_items("- first\n* second") == ("first", "second")
    assert estimate_judge_output_tokens(3, 16 * 1024) == 4096
    assert estimate_judge_output_tokens(4, 16 * 1024) == 8192
    assert estimate_judge_output_tokens(3, 64 * 1024 + 1) == 16384
    assert estimate_judge_output_tokens(7, 16 * 1024) == 16384


def test_judge_length_at_maximum_recommends_narrowing_evidence(
    tmp_path: Path,
) -> None:
    maximum = ResolvedInference(
        "https://example.test/v1",
        "tiny",
        SecretValue("secret"),
        InferenceLimits(max_output_tokens=16384),
    )

    result, failure = asyncio.run(
        judge(
            maximum,
            Transport(ChatResponse("{", (), None, None, None, "length")),
            case_at(tmp_path),
            ExecutionResult("x", 1, (), ()),
            (),
        )
    )

    assert result is None and failure is not None
    assert any("already 16384" in detail for detail in failure.details)
    assert not any("suggested diagnostic" in detail for detail in failure.details)


@pytest.mark.parametrize(
    "content",
    [
        '{"verdict":"MAYBE","rationale":"x","unmet_criteria":[]}',
        '{"verdict":"PASS","rationale":"","unmet_criteria":[]}',
        '{"verdict":"PASS","rationale":"x","unmet_criteria":"none"}',
        '{"verdict":"PASS","rationale":"' + "x" * 4097 + '","unmet_criteria":[]}',
    ],
)
def test_judge_parser_reports_each_json_contract_failure(content: str) -> None:
    result, failure = _parse(content, False)
    assert result is None
    assert failure is not None


@pytest.mark.parametrize(
    "content",
    [
        '{"verdict":"PASS","rationale":"Not enough evidence.",'
        '"unmet_criteria":["The response is incomplete."]}',
        '{"verdict":"FAIL","rationale":"It was incomplete.","unmet_criteria":[]}',
        '{"verdict":"PASS","rationale":"It passed.",'
        '"unmet_criteria":[],"extra":"nope"}',
    ],
)
def test_judge_rejects_internally_inconsistent_json(
    tmp_path: Path, content: str
) -> None:
    result, failure = asyncio.run(
        judge(
            profile(),
            Transport(ChatResponse(content, (), "tiny", None)),
            case_at(tmp_path),
            ExecutionResult("x", 1, (), ()),
            (),
        )
    )
    assert result is None
    assert failure is not None and failure.kind is InferenceFailureKind.JUDGE_INTEGRITY


def test_judge_handles_transport_failure_and_evidence_limit(tmp_path: Path) -> None:
    expected = InferenceFailure(InferenceFailureKind.TIMEOUT, "timed out")
    result, received = asyncio.run(
        judge(
            profile(),
            RaisingTransport(TransportFailure(expected)),
            case_at(tmp_path),
            ExecutionResult("x", 1, (), ()),
            (),
        )
    )
    assert result is None and received == expected
    case = case_at(tmp_path / "large")
    request, received = judge_request(
        profile(), case, ExecutionResult("x" * (MAX_JUDGE_BYTES + 1), 1, (), ()), ()
    )
    assert request is None and received is not None and "above" in received.summary
    result, received = asyncio.run(
        judge(
            profile(),
            Transport(ChatResponse("unused", (), None, None)),
            case,
            ExecutionResult("x" * (MAX_JUDGE_BYTES + 1), 1, (), ()),
            (),
        )
    )
    assert result is None and received is not None and "above" in received.summary


@pytest.mark.parametrize(
    "content",
    [
        '{"verdict":"FAIL","rationale":"x","criteria":{},"unmet_criteria":["one"]}',
        '{"verdict":"FAIL","rationale":"x","criteria":[{"extra":1}],'
        '"unmet_criteria":["one"]}',
        '{"verdict":"FAIL","rationale":"x","criteria":['
        '{"status":"not_met","evidence":"' + "x" * 4097 + '"}],'
        '"unmet_criteria":["one"]}',
        '{"verdict":"PASS","rationale":"x","criteria":['
        '{"status":"not_met","evidence":"x"}],"unmet_criteria":[]}',
        '{"verdict":"FAIL","rationale":"x","criteria":['
        '{"status":"met","evidence":"x"}],"unmet_criteria":["one"]}',
        '{"verdict":"PASS","rationale":"x","criteria":['
        '{"status":"met","evidence":"x"}],"unmet_criteria":["one"]}',
    ],
)
def test_judge_rejects_each_structured_criterion_integrity_failure(
    content: str,
) -> None:
    parsed, failure = _parse(content, False, ("one",))
    assert parsed is None and failure is not None


def test_judge_handles_missing_skill_and_unexpected_transport_error(
    tmp_path: Path,
) -> None:
    case = case_at(tmp_path)
    case.skill.skill_file.unlink()
    request, failure = judge_request(
        profile(), case, ExecutionResult("x", 1, (), ()), ()
    )
    assert request is not None and failure is None
    case = case_at(tmp_path / "error")
    result, failure = asyncio.run(
        judge(
            profile(),
            RuntimeErrorTransport(ChatResponse("unused", (), None, None)),
            case,
            ExecutionResult("x", 1, (), ()),
            (),
        )
    )
    assert result is None and failure is not None and "secret" not in failure.details[0]


def test_judge_handles_request_failure_and_cancellation(tmp_path: Path) -> None:
    case = case_at(tmp_path)
    case.skill.skill_file.unlink()
    result, failure = asyncio.run(
        judge(
            profile(),
            Transport(
                ChatResponse(
                    '{"verdict":"PASS","rationale":"Observed output is enough.",'
                    '"criteria":[{"criterion":"success","status":"met",'
                    '"evidence":"The final output says x."}],'
                    '"unmet_criteria":[]}',
                    (),
                    None,
                    None,
                )
            ),
            case,
            ExecutionResult("x", 1, (), ()),
            (),
        )
    )
    assert result is not None and failure is None

    class Cancelled(Transport):
        async def complete(self, request: ChatRequest) -> ChatResponse:
            del request
            raise asyncio.CancelledError

    result, failure = asyncio.run(
        judge(
            profile(),
            Cancelled(ChatResponse("unused", (), None, None)),
            case_at(tmp_path / "cancelled"),
            ExecutionResult("x", 1, (), ()),
            (),
        )
    )
    assert (
        result is None
        and failure is not None
        and failure.kind is InferenceFailureKind.CANCELLED
    )


def test_skipped_check_explains_trust_and_exact_remediation(tmp_path: Path) -> None:
    check = DeclaredCheck(
        "overview test",
        "python scripts/test.py",
        (PurePosixPath("scripts/test.py"),),
        SourceLocation("basic.eval.md", 1, 1),
    )
    request = CheckRequest(
        case_at(tmp_path, check),
        check,
        "eval",
        tmp_path,
        tmp_path / ".skillroll" / "runs" / "run-1",
    )
    skipped = skipped_check(request)
    assert skipped.outcome == "SKIPPED"
    assert "repository commands can" in (skipped.detail or "")
    assert "--run-commands" in (skipped.detail or "") and "model key is removed" in (
        skipped.detail or ""
    )


def test_check_environment_removes_only_configured_key_and_real_runner(
    tmp_path: Path,
) -> None:
    check = DeclaredCheck(
        "works",
        _python_shell_command("import sys; sys.stdout.write('ok')"),
        (PurePosixPath("scripts/test.py"),),
        SourceLocation(),
    )
    case = case_at(tmp_path, check)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    request = CheckRequest(case, check, "validate", tmp_path, None)
    environment = check_environment(config, request, {"KEY": "no", "OTHER": "yes"})
    assert (
        "KEY" not in environment
        and environment["OTHER"] == "yes"
        and environment["SKILLROLL_MODE"] == "validate"
    )
    result = asyncio.run(HostCheckRunner().run(request, environment))
    assert result.outcome == "PASS" and result.stdout == "ok"


def test_runner_captures_failure_and_timeout(tmp_path: Path) -> None:
    failed_check = DeclaredCheck(
        "fails",
        _python_shell_command(
            "import sys; sys.stderr.write('nope'); raise SystemExit(4)"
        ),
        (),
        SourceLocation(),
    )
    failed_request = CheckRequest(
        case_at(tmp_path, failed_check), failed_check, "validate", tmp_path, None
    )
    failed = asyncio.run(HostCheckRunner().run(failed_request, {}))
    assert (
        failed.outcome == "FAIL" and failed.exit_code == 4 and failed.stderr == "nope"
    )
    slow_check = DeclaredCheck(
        "slow",
        _python_shell_command("import time; time.sleep(1)"),
        (),
        SourceLocation(),
    )
    root = tmp_path / "slow"
    timed = asyncio.run(
        HostCheckRunner(timeout_seconds=0).run(
            CheckRequest(case_at(root, slow_check), slow_check, "validate", root, None),
            {},
        )
    )
    assert timed.outcome == "ERROR" and "did not finish" in (timed.detail or "")


def test_bounded_stream_handles_none_and_truncation() -> None:
    from skillroll.checks import _bounded_stream

    assert asyncio.run(_bounded_stream(None)) == ""

    async def oversized() -> str:
        reader = asyncio.StreamReader()
        reader.feed_data(b"x" * (64 * 1024 + 1))
        reader.feed_eof()
        return await _bounded_stream(reader)

    assert "truncated" in asyncio.run(oversized())


def test_runner_reports_spawn_and_stream_collection_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = DeclaredCheck("check", "unused", (), SourceLocation())
    request = CheckRequest(case_at(tmp_path, check), check, "validate", tmp_path, None)

    async def cannot_start(*_: object, **__: object) -> object:
        raise OSError("no shell")

    monkeypatch.setattr(checks_module.asyncio, "create_subprocess_shell", cannot_start)
    started = asyncio.run(HostCheckRunner().run(request, {}))
    assert started.outcome == "ERROR" and "could not start" in (started.detail or "")

    class Process:
        returncode = 0
        stdout = None
        stderr = None

        async def wait(self) -> int:
            return 0

    async def process(*_: object, **__: object) -> Process:
        return Process()

    async def broken_stream(_: object) -> str:
        raise RuntimeError("stream broke")

    monkeypatch.setattr(checks_module.asyncio, "create_subprocess_shell", process)
    monkeypatch.setattr(checks_module, "_bounded_stream", broken_stream)
    collected = asyncio.run(HostCheckRunner().run(request, {}))
    assert collected.outcome == "ERROR" and collected.started


def test_runner_propagates_cancellation_before_and_after_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = DeclaredCheck("check", "unused", (), SourceLocation())
    request = CheckRequest(case_at(tmp_path, check), check, "validate", tmp_path, None)

    async def cancelled_before_start(*_args: object, **_kwargs: object) -> object:
        raise asyncio.CancelledError

    monkeypatch.setattr(
        checks_module.asyncio, "create_subprocess_shell", cancelled_before_start
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(HostCheckRunner().run(request, {}))

    class Process:
        returncode = 0

        def __init__(self) -> None:
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.stopped = False

        async def wait(self) -> int:
            if self.stopped:
                return 0
            await asyncio.Event().wait()
            return 0

        def terminate(self) -> None:
            self.stopped = True

    async def started_process(*_args: object, **_kwargs: object) -> Process:
        return Process()

    monkeypatch.setattr(
        checks_module.asyncio, "create_subprocess_shell", started_process
    )

    async def cancel_after_start() -> None:
        task = asyncio.create_task(HostCheckRunner().run(request, {}))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_after_start())


def test_stop_cleanup_handles_lookup_kill_timeout_and_stream_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del tmp_path

    class Process:
        async def wait(self) -> int:
            return 0

        def terminate(self) -> None:
            raise ProcessLookupError

        def kill(self) -> None:
            raise ProcessLookupError

    async def value(text: str) -> str:
        return text

    async def run_normal() -> tuple[str, str, str | None]:
        return await HostCheckRunner()._collect_after_stop(
            Process(),
            asyncio.create_task(value("out")),
            asyncio.create_task(value("err")),
        )

    assert asyncio.run(run_normal()) == ("out", "err", None)

    class CannotTerminate(Process):
        def terminate(self) -> None:
            raise OSError("no permission")

    async def run_error() -> tuple[str, str, str | None]:
        return await HostCheckRunner()._collect_after_stop(
            CannotTerminate(),
            asyncio.create_task(value("out")),
            asyncio.create_task(value("err")),
        )

    assert "could not stop" in (asyncio.run(run_error())[2] or "")

    calls = 0

    async def always_timeout(awaitable: object, timeout: object) -> object:
        nonlocal calls
        calls += 1
        if hasattr(awaitable, "close"):
            awaitable.close()  # type: ignore[union-attr]
        raise TimeoutError

    monkeypatch.setattr(checks_module.asyncio, "wait_for", always_timeout)

    async def run_timeout() -> tuple[str, str, str | None]:
        return await HostCheckRunner()._collect_after_stop(
            Process(),
            asyncio.create_task(value("out")),
            asyncio.create_task(value("err")),
        )

    assert "within 5 seconds" in (asyncio.run(run_timeout())[2] or "")
    assert calls == 2


def test_stop_cleanup_reports_kill_and_stream_collection_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        async def wait(self) -> int:
            return 0

        def terminate(self) -> None:
            return None

        def kill(self) -> None:
            raise OSError("cannot kill")

    async def value(text: str) -> str:
        return text

    async def timeout(awaitable: object, timeout: object) -> object:
        if hasattr(awaitable, "close"):
            awaitable.close()  # type: ignore[union-attr]
        raise TimeoutError

    monkeypatch.setattr(checks_module.asyncio, "wait_for", timeout)

    async def run_kill_error() -> tuple[str, str, str | None]:
        return await HostCheckRunner()._collect_after_stop(
            Process(),
            asyncio.create_task(value("out")),
            asyncio.create_task(value("err")),
        )

    assert "could not stop" in (asyncio.run(run_kill_error())[2] or "")

    class CompleteProcess:
        async def wait(self) -> int:
            return 0

        def terminate(self) -> None:
            return None

    async def broken() -> str:
        raise RuntimeError("stream")

    async def run_stream_error() -> tuple[str, str, str | None]:
        return await HostCheckRunner()._collect_after_stop(
            CompleteProcess(),
            asyncio.create_task(broken()),
            asyncio.create_task(value("err")),
        )

    monkeypatch.undo()
    assert "could not collect" in (asyncio.run(run_stream_error())[2] or "")


def test_artifact_final_renderers_and_append_are_redacted(tmp_path: Path) -> None:
    store = ArtifactStore(
        tmp_path, SecretRedactor(SecretValue("secret")), id_factory=lambda: "id"
    )
    _, directory, _ = store.create()
    store.append(
        directory,
        (
            ("execution.json", execution_bytes("secret", 1, [])),
            ("judge.json", judge_bytes({"verdict": "PASS"}, [])),
            ("verdict.json", verdict_bytes("PASS", None)),
            ("checks.json", checks_bytes([])),
        ),
    )
    assert "[redacted]" in (directory / "execution.json").read_text(encoding="utf-8")
    assert (directory / "verdict.json").exists()
    with pytest.raises(ArtifactError):
        store.append(directory, (("../unsafe", b"x"),))


def test_final_report_and_check_logs_are_friendly_and_redacted(tmp_path: Path) -> None:
    store = ArtifactStore(
        tmp_path, SecretRedactor(SecretValue("secret")), id_factory=lambda: "logs"
    )
    _, directory, _ = store.create()
    result = redact_check_result(
        CheckResult(
            DeclaredCheck("check", "echo secret", (), SourceLocation("case.md")),
            "ERROR",
            None,
            "secret output",
            "secret error",
            0.1,
            "secret detail",
            True,
        ),
        SecretRedactor(SecretValue("secret")),
    )
    assert "secret" not in result.stdout + result.stderr + (result.detail or "")
    report = final_report_bytes(
        "review",
        "skills/review/evals/case.eval.md",
        "ERROR",
        {
            "verdict": "PASS",
            "rationale": "Observed success.",
            "unmet_criteria": [],
        },
        ({"ordinal": 1, "kind": "final_output_contains", "passed": True},),
        ({"name": "check", "outcome": "ERROR", "detail": result.detail},),
        "could not save final evidence",
    )
    assert b"preliminary" not in report and b"Observed success." in report
    store.append(
        directory,
        (
            ("report.md", report),
            ("checks/1-stdout.log", result.stdout.encode()),
            ("checks/1-stderr.log", result.stderr.encode()),
        ),
    )
    assert (directory / "checks" / "1-stdout.log").read_text() == "[redacted] output"
    assert "[redacted]" in (directory / "report.md").read_text()


def test_final_report_handles_missing_judge_assertions_checks_and_failure() -> None:
    report = final_report_bytes(
        "skill",
        "case",
        "ERROR",
        None,
        (),
        (),
        "broken",
        ("network timeout [redacted]",),
    )
    text = report.decode("utf-8")
    assert "What prevented completion" in text and "No exact fact" in text
    assert "No repository checks" in text and "broken" in text
    assert "Technical details" in text and "network timeout [redacted]" in text
    assert b'"failure":"broken"' in verdict_bytes(
        "ERROR", "broken", ("network timeout [redacted]",)
    )
    assert b'"failure_details":["network timeout [redacted]"]' in verdict_bytes(
        "ERROR", "broken", ("network timeout [redacted]",)
    )
    no_rationale = final_report_bytes(
        "skill",
        "case",
        "FAIL",
        {"verdict": "FAIL", "rationale": "", "unmet_criteria": ["criterion"]},
        (),
        (),
        None,
        model="provider/model",
        model_profile="baseline",
    ).decode()
    assert "Unmet criteria:" in no_rationale and "criterion" in no_rationale
    empty_explanation = final_report_bytes(
        "skill",
        "case",
        "PASS",
        {"verdict": "PASS", "rationale": "Observed success.", "unmet_criteria": []},
        (),
        (),
        None,
    )
    assert b"Result: **PASS**" in empty_explanation
    detailed = final_report_bytes(
        "skill",
        "case",
        "PASS",
        {
            "verdict": "PASS",
            "rationale": "The result meets the criteria.",
            "unmet_criteria": [],
            "criteria": (
                "ignore malformed assessment",
                {"criterion": "one", "status": "met", "evidence": ""},
                {"criterion": "two", "status": "met", "evidence": "observed"},
            ),
        },
        (
            {
                "ordinal": 1,
                "kind": "final_output_contains",
                "passed": True,
                "observed": "literal was present",
            },
        ),
        (),
        None,
        finished=True,
        events=(
            WorldEvent(
                0,
                "Read",
                {"path": "context.md"},
                "facts",
                "rule",
                omitted_history=1,
            ),
        ),
        execution_turns=2,
        model="provider/model",
        model_profile="baseline",
        model_profile_purpose="Low-cost release signal.",
    ).decode()
    assert all(
        heading in detailed
        for heading in (
            "Skill finished: yes",
            "Actions",
            "Success criteria",
            "Exact checks",
            "Repository checks",
        )
    )
    assert "`Read`" in detailed and "literal was present" in detailed
    assert "Profile purpose: Low-cost release signal." in detailed
    assert "omitted 1 earlier actions" in detailed


def test_experiment_report_handles_malformed_and_complete_optional_sections() -> None:
    minimal = experiment_report_bytes(
        {
            "interpretation": "invalid",
            "paired_comparisons": "invalid",
            "skill_runs": "invalid",
            "skill_control_runs": {"PASS": 0},
        }
    ).decode()
    assert "No interpretation was recorded" in minimal
    assert "skill_control_runs: PASS=0" in minimal

    detailed = experiment_report_bytes(
        {
            "interpretation": {"status": "mixed", "explanation": "review"},
            "paired_comparisons": [
                "invalid",
                {
                    "sample": 1,
                    "skill_run": {"outcome": "PASS", "artifact_directory": "a"},
                    "skill_control_run": "invalid",
                    "control_interpretation": "useful",
                },
            ],
            "skill_runs": {"PASS": 1},
        }
    ).decode()
    assert "| 1 | PASS | not run | useful | `a` |" in detailed


def test_fallback_append_writes_check_logs_and_rejects_unsafe_log_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "_descriptor_safety_available", lambda: False)
    store = ArtifactStore(
        tmp_path, SecretRedactor(SecretValue("")), id_factory=lambda: "fallback"
    )
    _, directory, _ = store.create()
    store.append(directory, (("checks/2-stderr.log", b"ok"),))
    assert (directory / "checks" / "2-stderr.log").read_bytes() == b"ok"
    (directory / "checks").unlink() if (directory / "checks").is_symlink() else None
    assert store._check_log_name("checks/not-a-log.txt") is None
    assert store._check_log_name("checks/hello-stdout.log") is None


def test_check_log_storage_errors_are_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(tmp_path, SecretRedactor(SecretValue("")))

    def no_mkdir(*_args: object, **_kwargs: object) -> None:
        raise OSError("no mkdir")

    def no_open(*_args: object, **_kwargs: object) -> int:
        raise OSError("no open")

    with monkeypatch.context() as scoped:
        scoped.setattr(store_module.os, "mkdir", no_mkdir)
        with pytest.raises(ArtifactError, match="create the repository-check"):
            store._open_check_logs(1)
    with monkeypatch.context() as scoped:
        scoped.setattr(store_module.os, "mkdir", lambda *_args, **_kwargs: None)
        scoped.setattr(store_module.os, "open", no_open)
        with pytest.raises(ArtifactError, match="open the repository-check"):
            store._open_check_logs(1)
    _, directory, _ = store.create()
    (directory / "checks").write_text("not a directory", encoding="utf-8")
    with pytest.raises(ArtifactError, match="safely create"):
        store._fallback_check_logs(directory)
    (directory / "checks").unlink()
    (directory / "checks").symlink_to(tmp_path)
    with pytest.raises(ArtifactError, match="ordinary folder"):
        store._fallback_check_logs(directory)


def test_evaluate_repository_runs_one_preflight_execution_judge_and_check(
    tmp_path: Path,
) -> None:
    check = DeclaredCheck("test", "unused", (), SourceLocation())
    case = case_at(tmp_path, check)
    case = EvalCase(
        case.path,
        case.identity,
        case.skill,
        case.title,
        case.input_markdown,
        case.world_markdown,
        case.success_criteria_markdown,
        case.checks,
        limits=CaseLimits(max_output_tokens=64),
        assertions=(Assertion("final_output_contains", expected_text="overview"),),
    )
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings(
            "https://example.test/v1", "tiny", "KEY", InferenceLimits(2, 10, 256)
        ),
        tmp_path / "skillroll.toml",
    )
    config.config_path.write_text("schema_version = 1", encoding="utf-8")
    transport = ScriptedTransport(preflight_responses())
    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=True,
            transport_factory=lambda _: transport,
            executor_factory=lambda _: Executor(),
            check_runner=PassingRunner(),
        )
    )
    assert not isinstance(result, InferenceFailure)
    assert result[0].outcome == "PASS", result[0].failure
    assert len(transport.requests) == 4
    assert transport.requests[-1].max_output_tokens == 64
    directory = tmp_path / result[0].artifact_directory
    assert (directory / "execution.json").exists()
    assert (directory / "judge.json").exists()
    judge_text = (directory / "judge.json").read_text(encoding="utf-8")
    assert '"semantic_judgment"' in judge_text
    assert '"total_tokens":16' in judge_text
    assert (directory / "verdict.json").exists()
    result_text = (directory / "result.json").read_text(encoding="utf-8")
    assert '"format_version":2' in result_text
    assert '"semantic_judgment"' in result_text
    assert "preliminary" not in (directory / "report.md").read_text(encoding="utf-8")
    assert transport.closed


def test_large_skill_warning_is_recorded_without_changing_verdict(
    tmp_path: Path,
) -> None:
    case = case_at(tmp_path)
    case.skill.skill_file.write_bytes(b"x" * SKILL_WARNING_BYTES)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    config.config_path.write_text("schema_version = 1", encoding="utf-8")
    transport = ScriptedTransport(preflight_responses())
    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            transport_factory=lambda _: transport,
            executor_factory=lambda _: Executor(),
        )
    )
    assert not isinstance(result, InferenceFailure)
    assert result[0].outcome == "PASS"
    assert len(result[0].warnings) == 1
    directory = tmp_path / result[0].artifact_directory
    run_record = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    assert run_record["warnings"][0]["bytes"] == SKILL_WARNING_BYTES
    assert "Evaluation continues" in run_record["warnings"][0]["summary"]
    assert "## Warnings" in (directory / "report.md").read_text(encoding="utf-8")


def test_aggregate_warnings_deduplicate_repeated_samples_and_cases(
    tmp_path: Path,
) -> None:
    first = case_at(tmp_path)
    second_path = first.skill.evals_directory / "second.eval.md"
    second_path.write_text("case", encoding="utf-8")
    second = replace(
        first,
        path=second_path,
        identity=PurePosixPath("skills/review/evals/second.eval.md"),
    )
    warning = BundleWarning(PurePosixPath("SKILL.md"), SKILL_WARNING_BYTES)
    results = tuple(
        CaseResult(case, "PASS", None, None, (), (), None, None, (), True, (warning,))
        for case in (first, second, first)
    )

    records = evaluate._case_warning_data(results)

    assert len(records) == 1
    assert records[0]["skill"] == "skills/review"
    assert records[0]["case"] == "skills/review/evals/basic.eval.md"


def test_experiment_report_keeps_context_for_warnings_from_multiple_skills() -> None:
    report = experiment_report_bytes(
        {
            "warnings": [
                "ignore malformed warning",
                {
                    "skill": "skills/no-case",
                    "summary": "no case context",
                },
                {
                    "skill": "skills/review",
                    "case": "skills/review/evals/basic.eval.md",
                    "summary": "review is large",
                },
                {
                    "skill": "skills/other",
                    "case": "skills/other/evals/basic.eval.md",
                    "summary": "other is large",
                },
            ]
        }
    ).decode()

    assert "Skill `skills/review`" in report
    assert "Skill `skills/other`" in report
    assert "Skill `skills/no-case`: no case context" in report
    assert "ignore malformed warning" not in report
    assert "review is large" in report and "other is large" in report


def test_authoring_experiment_pairs_skill_and_omission_runs(tmp_path: Path) -> None:
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings(
            "https://example.test/v1", "tiny", "KEY", InferenceLimits(2, 10, 256)
        ),
        tmp_path / "skillroll.toml",
    )
    config.config_path.write_text("schema_version = 1", encoding="utf-8")
    passing = (
        '{"verdict":"PASS","rationale":"supported",'
        '"criteria":[{"criterion":"success","status":"met",'
        '"evidence":"The response supports the criterion."}],'
        '"unmet_criteria":[]}'
    )
    failing = (
        '{"verdict":"FAIL","rationale":"unsupported",'
        '"criteria":[{"criterion":"success","status":"not_met",'
        '"evidence":"The response does not support the criterion."}],'
        '"unmet_criteria":["success"]}'
    )
    transport = ScriptedTransport(
        preflight_responses()[:2]
        + [
            ChatResponse("world", (), "tiny", None),
            ChatResponse(passing, (), "tiny", None),
            ChatResponse("world", (), "tiny", None),
            ChatResponse(failing, (), "tiny", None),
        ]
    )
    result = asyncio.run(
        evaluate.evaluate_experiment(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            samples=1,
            with_skill_control=True,
            transport_factory=lambda _: transport,
            executor_factory=lambda _: Executor(),
        )
    )
    assert isinstance(result, evaluate.ExperimentResult)
    assert result.summary["interpretation"]["status"] == "consistent_discrimination"
    pair = result.pairs[0]
    assert pair.skill.outcome == "PASS"
    assert pair.control is not None and pair.control.outcome == "FAIL"
    assert transport.closed
    experiment_dir = tmp_path / result.artifact_directory
    assert (experiment_dir / "result.json").exists()
    assert (experiment_dir / "report.md").exists()
    assert pair.control.artifact_directory is not None
    control_dir = tmp_path / pair.control.artifact_directory
    control_run = json.loads((control_dir / "run.json").read_text())
    assert control_run["skill_instructions_available"] is False
    assert "skills/review/SKILL.md" not in (control_dir / "inputs.json").read_text()


def test_experiment_interpretations_cover_every_authoring_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def result(name: str, outcome: str) -> CaseResult:
        return CaseResult(
            case_at(tmp_path / name),
            outcome,  # type: ignore[arg-type]
            None,
            None,
            (),
            (),
            None,
            PurePosixPath(f".skillroll/runs/{name}"),
        )

    passed = result("passed", "PASS")
    failed = result("failed", "FAIL")
    errored = result("errored", "ERROR")
    unusual = result("unusual", "OTHER")

    assert "without" in evaluate._control_interpretation(passed, None)
    assert "inconclusive" in evaluate._control_interpretation(errored, failed)
    assert (
        "passed with the skill and failed without"
        in evaluate._control_interpretation(passed, failed)
    )
    assert "passed without" in evaluate._control_interpretation(failed, passed)
    assert "did not pass" in evaluate._control_interpretation(failed, failed)
    assert "clear comparison" in evaluate._control_interpretation(passed, unusual)

    pair = evaluate.ExperimentPair(1, passed, failed)
    assert (
        evaluate._experiment_interpretation((pair,), False)["status"] == "sampling_only"
    )
    assert (
        evaluate._experiment_interpretation(
            (evaluate.ExperimentPair(1, errored, failed),), True
        )["status"]
        == "technically_inconclusive"
    )
    assert (
        evaluate._experiment_interpretation(
            (evaluate.ExperimentPair(1, failed, failed),), True
        )["status"]
        == "skill_not_ready"
    )
    assert evaluate._experiment_interpretation((pair,), True)["status"] == (
        "consistent_discrimination"
    )
    assert (
        evaluate._experiment_interpretation(
            (pair, evaluate.ExperimentPair(2, passed, passed)), True
        )["status"]
        == "mixed_discrimination"
    )
    assert (
        evaluate._experiment_interpretation(
            (evaluate.ExperimentPair(1, passed, passed),), True
        )["status"]
        == "no_observed_discrimination"
    )

    monkeypatch.setattr(
        evaluate, "_usage_records", lambda *_, **__: {"calls": "not-a-list"}
    )
    assert evaluate._experiment_usage((passed,), "model") == {
        "status": "unavailable",
        "calls": [],
    }


def test_experiment_returns_technical_failures_and_closes_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    expected = InferenceFailure(InferenceFailureKind.SERVICE_FAILURE, "broken")

    result = asyncio.run(
        evaluate.evaluate_experiment(
            config,
            (case,),
            environment={},
            run_commands=False,
            samples=1,
            with_skill_control=False,
        )
    )
    assert isinstance(result, InferenceFailure)

    transport = Transport(ChatResponse("unused", (), None, None))

    async def resolved(*_: object, **__: object) -> object:
        return profile(), transport

    async def failed(*_: object, **__: object) -> InferenceFailure:
        return expected

    monkeypatch.setattr(evaluate, "_resolve_profile", resolved)
    monkeypatch.setattr(evaluate, "evaluate_repository", failed)
    result = asyncio.run(
        evaluate.evaluate_experiment(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            samples=1,
            with_skill_control=False,
        )
    )
    assert result == expected and transport.closed


def test_experiment_handles_control_and_parent_evidence_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    selected = CaseResult(case, "PASS", None, None, (), (), None, None)
    expected = InferenceFailure(InferenceFailureKind.SERVICE_FAILURE, "control failed")
    transport = Transport(ChatResponse("unused", (), None, None))

    async def resolved(*_: object, **__: object) -> object:
        return profile(), transport

    responses: list[object] = [(selected,), expected]

    async def repository(*_: object, **__: object) -> object:
        return responses.pop(0)

    monkeypatch.setattr(evaluate, "_resolve_profile", resolved)
    monkeypatch.setattr(evaluate, "evaluate_repository", repository)
    result = asyncio.run(
        evaluate.evaluate_experiment(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            samples=1,
            with_skill_control=True,
        )
    )
    assert result == expected and transport.closed

    transport = Transport(ChatResponse("unused", (), None, None))

    async def selected_only(*_: object, **__: object) -> object:
        return (selected,)

    class BrokenStore:
        def create_experiment(self) -> tuple[str, Path]:
            directory = tmp_path / ".skillroll" / "experiments" / "experiment-id"
            directory.mkdir(parents=True)
            return "experiment-id", directory

        def write_experiment(self, *_: object) -> None:
            raise ArtifactError("could not save parent")

    monkeypatch.setattr(evaluate, "evaluate_repository", selected_only)
    result = asyncio.run(
        evaluate.evaluate_experiment(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            samples=1,
            with_skill_control=False,
            store_factory=lambda *_: BrokenStore(),  # type: ignore[arg-type]
        )
    )
    assert isinstance(result, InferenceFailure)
    assert result.stage == "evidence_writing"


def test_run_validates_sample_bounds_and_reports_experiment_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert evaluate.run(samples=0).outcome is Outcome.ERROR
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        None,
        tmp_path / "skillroll.toml",
    )
    selected = CaseResult(case, "PASS", None, None, (), (), None, None)
    report = type("Report", (), {"config": config, "cases": (case,)})()
    monkeypatch.setattr(evaluate, "validate_repository", lambda *_: report)
    monkeypatch.setattr(
        evaluate,
        "command_result",
        lambda *_: CommandResult(Outcome.PASS, "valid"),
    )

    async def experiment(*_: object, **__: object) -> evaluate.ExperimentResult:
        return evaluate.ExperimentResult(
            (evaluate.ExperimentPair(1, selected, None),),
            PurePosixPath(".skillroll/experiments/experiment-id"),
            {"interpretation": {"status": "sampling_only"}},
        )

    monkeypatch.setattr(evaluate, "evaluate_experiment", experiment)
    result = evaluate.run(repo=str(tmp_path), samples=2, environment={})
    assert result.outcome is Outcome.PASS
    assert "Report: .skillroll/experiments/experiment-id/report.md." in result.summary
    assert result.data["experiment_artifact_directory"] == (
        ".skillroll/experiments/experiment-id"
    )


def test_run_surfaces_large_skill_warning_without_changing_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_at(tmp_path)
    warning = BundleWarning(PurePosixPath("SKILL.md"), SKILL_WARNING_BYTES)
    selected = CaseResult(
        case, "PASS", None, None, (), (), None, None, (), True, (warning,)
    )
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        None,
        tmp_path / "skillroll.toml",
    )
    report = ValidationReport(tmp_path, config, (case.skill,), (case,), (), ())
    monkeypatch.setattr(evaluate, "validate_repository", lambda *_args: report)

    async def selected_only(*_: object, **__: object) -> tuple[CaseResult, ...]:
        return (selected,)

    monkeypatch.setattr(evaluate, "evaluate_repository", selected_only)
    result = evaluate.run(repo=str(tmp_path), environment={})

    assert result.outcome is Outcome.PASS
    assert any(item.code == "SCW1001" for item in result.diagnostics)
    warnings = result.data["warnings"]
    assert isinstance(warnings, tuple)
    assert warnings[0]["path"] == "SKILL.md"


def test_eval_finds_nearest_config_and_scopes_bare_runs_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "skillroll.toml").write_text(
        'schema_version = 1\nskills_path = "."\n', encoding="utf-8"
    )
    case = case_at(repository)
    config = SkillRollConfig(
        repository,
        PurePosixPath("."),
        repository,
        GuardSettings(),
        None,
        repository / "skillroll.toml",
    )
    report = ValidationReport(repository, config, (case.skill,), (case,), (), ())
    seen: list[tuple[Path, Path | None]] = []

    def checked(
        root: Path, _: object, *, scope: Path | None = None
    ) -> ValidationReport:
        seen.append((root, scope))
        return report

    monkeypatch.setattr(evaluate, "validate_repository", checked)
    monkeypatch.setattr(
        evaluate,
        "command_result",
        lambda _: CommandResult(Outcome.ERROR, "stop before inference"),
    )
    nested = repository / "skills" / "review" / "evals"
    monkeypatch.chdir(nested)

    scoped = evaluate.run(environment={})
    all_cases = evaluate.run(environment={}, all_cases=True)

    assert scoped.outcome is Outcome.ERROR
    assert all_cases.outcome is Outcome.ERROR
    assert seen == [(repository, nested), (repository, None)]


def test_evaluate_records_judge_failure_as_a_semantic_stage_error(
    tmp_path: Path,
) -> None:
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    config.config_path.write_text("schema_version = 1", encoding="utf-8")
    responses = preflight_responses()
    responses[-1] = ChatResponse(
        "not json", (), "tiny", ModelUsage(3, 2, 5), None, "length"
    )
    transport = ScriptedTransport(responses)
    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            transport_factory=lambda _: transport,
            executor_factory=lambda _: Executor(),
        )
    )

    assert not isinstance(result, InferenceFailure)
    assert result[0].outcome == "ERROR"
    assert result[0].failure is not None
    assert result[0].failure.stage == "semantic_judgment"
    assert result[0].failure.details[0] == "provider finish_reason: length"
    assert "suggested diagnostic max_output_tokens" in "\n".join(
        result[0].failure.details
    )
    directory = tmp_path / result[0].artifact_directory
    summary = (directory / "result.json").read_text(encoding="utf-8")
    assert '"status":"completed"' in summary
    assert '"stage":"semantic_judgment"' in summary
    assert '"provider finish_reason: length"' in summary
    assert "ERROR, not a skill FAIL" in summary


def test_evaluate_keeps_a_fallback_limit_for_an_invalid_direct_case(
    tmp_path: Path,
) -> None:
    case = replace(case_at(tmp_path), limits=CaseLimits(max_turns=9))
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings(
            "https://example.test/v1", "tiny", "KEY", InferenceLimits(2, 10, 256)
        ),
        tmp_path / "skillroll.toml",
    )
    config.config_path.write_text("schema_version = 1", encoding="utf-8")
    transport = ScriptedTransport(preflight_responses()[:2])
    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            transport_factory=lambda _: transport,
            executor_factory=lambda _: Executor(),
        )
    )

    assert not isinstance(result, InferenceFailure)
    assert result[0].outcome == "ERROR"
    assert result[0].failure is not None
    assert "limit above" in result[0].failure.summary


def test_evaluate_uses_ranked_fallback_only_during_preflight(tmp_path: Path) -> None:
    case = case_at(tmp_path)
    settings = InferenceSettings(
        "https://example.test/v1",
        "unused",
        "KEY",
        InferenceLimits(2, 10, 256),
        {
            "baseline": ModelProfile(
                "Low-cost release signal.", ("unavailable", "available")
            )
        },
        "baseline",
    )
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        settings,
        tmp_path / "skillroll.toml",
    )
    config.config_path.write_text("schema_version = 1", encoding="utf-8")
    failed = ScriptedTransport([ChatResponse("not a tool call", (), None, None)])
    selected = ScriptedTransport(preflight_responses())
    transports = {"unavailable": failed, "available": selected}
    seen_profiles: list[str] = []

    def factory(profile: ResolvedInference) -> ScriptedTransport:
        seen_profiles.append(profile.model)
        return transports[profile.model]

    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            transport_factory=factory,
            executor_factory=lambda profile: Executor(),
        )
    )
    assert not isinstance(result, InferenceFailure)
    assert result[0].outcome == "PASS"
    assert seen_profiles == ["unavailable", "available"]
    assert failed.closed
    assert selected.closed
    directory = tmp_path / result[0].artifact_directory
    summary = (directory / "result.json").read_text(encoding="utf-8")
    assert '"requested_model":"available"' in summary
    assert '"model_profile":"baseline"' in summary


@pytest.mark.parametrize("failing_append", [1, 2])
def test_evaluate_repository_turns_evidence_append_errors_into_case_errors(
    tmp_path: Path, failing_append: int
) -> None:
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    config.config_path.write_text("schema_version = 1", encoding="utf-8")

    class FailingStore(ArtifactStore):
        calls = 0

        def append(
            self, directory: Path, values: tuple[tuple[str, bytes], ...]
        ) -> None:
            self.calls += 1
            if self.calls == failing_append:
                raise ArtifactError("append failed")
            super().append(directory, values)

    transport = ScriptedTransport(preflight_responses())
    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            transport_factory=lambda _: transport,
            executor_factory=lambda _: Executor(),
            store_factory=lambda root, redactor: FailingStore(root, redactor),
        )
    )
    assert not isinstance(result, InferenceFailure)
    assert result[0].outcome == "ERROR" and result[0].failure is not None


def test_evaluate_repository_preserves_preliminary_errors_without_judging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    failed = InferenceFailure(InferenceFailureKind.EXECUTION_ERROR, "preliminary")

    async def preliminary(*_args: object, **_kwargs: object) -> PreliminaryAttempt:
        return PreliminaryAttempt(None, failed, None)

    monkeypatch.setattr(evaluate, "execute_preliminary", preliminary)
    transport = ScriptedTransport(preflight_responses()[:2])
    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            transport_factory=lambda _: transport,
            executor_factory=lambda _: Executor(),
        )
    )
    assert not isinstance(result, InferenceFailure)
    assert result[0].outcome == "ERROR" and len(transport.requests) == 2


def test_evaluate_run_and_validate_run_handle_keyboard_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        None,
        tmp_path / "skillroll.toml",
    )
    report = ValidationReport(tmp_path, config, (case.skill,), (case,), (), ())
    monkeypatch.setattr(evaluate, "validate_repository", lambda *_args: report)

    async def cancelled_eval(
        *_args: object, **_kwargs: object
    ) -> tuple[CaseResult, ...]:
        raise KeyboardInterrupt

    monkeypatch.setattr(evaluate, "evaluate_repository", cancelled_eval)
    assert evaluate.run(repo=str(tmp_path)).outcome is Outcome.ERROR

    check = DeclaredCheck("check", "unused", (), SourceLocation())
    checked_report = ValidationReport(
        tmp_path, config, (case.skill,), (case_at(tmp_path / "checked", check),), (), ()
    )
    monkeypatch.setattr(
        validate_command, "validate_repository", lambda *_args: checked_report
    )

    class InterruptedRunner:
        async def run(self, request: CheckRequest, environment: object) -> CheckResult:
            del request, environment
            raise KeyboardInterrupt

    assert (
        validate_command.run(
            repo=str(tmp_path), run_commands=True, runner=InterruptedRunner()
        ).outcome
        is Outcome.ERROR
    )


def test_evaluate_run_renders_only_bounded_redacted_failure_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    report = ValidationReport(tmp_path, config, (case.skill,), (case,), (), ())
    monkeypatch.setattr(evaluate, "validate_repository", lambda *_args: report)
    failure = InferenceFailure(
        InferenceFailureKind.EXECUTION_ERROR,
        "Skill execution could not complete.",
        (
            "endpoint rejected secret/key; secret%2Fkey",
            "X-API-Key: another-provider-token",
        ),
    )

    async def failed_evaluation(
        *_args: object, **_kwargs: object
    ) -> tuple[CaseResult, ...]:
        return (CaseResult(case, "ERROR", None, None, (), (), failure, None),)

    monkeypatch.setattr(evaluate, "evaluate_repository", failed_evaluation)

    result = evaluate.run(repo=str(tmp_path), environment={"KEY": "secret/key"})

    diagnostic = result.diagnostics[0]
    rendered = "\n".join(diagnostic.details)
    assert diagnostic.code == "SCE1001"
    assert "secret/key" not in rendered and "secret%2Fkey" not in rendered
    assert "[redacted]" in rendered
    assert "another-provider-token" not in rendered
    assert "omitted provider headers" in rendered


@pytest.mark.parametrize(
    ("run_commands", "check_outcome", "expected"),
    [(False, "PASS", "INCOMPLETE"), (True, "PASS", "PASS"), (True, "FAIL", "FAIL")],
)
def test_validate_command_composes_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    run_commands: bool,
    check_outcome: str,
    expected: str,
) -> None:
    check = DeclaredCheck("test", "unused", (), SourceLocation())
    case = case_at(tmp_path, check)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    report = ValidationReport(tmp_path, config, (case.skill,), (case,), (), ())
    monkeypatch.setattr(validate_command, "validate_repository", lambda *_: report)

    class Runner:
        async def run(self, request: CheckRequest, environment: object) -> CheckResult:
            del environment
            return CheckResult(request.check, check_outcome, 0, "", "", 0.0)

    result = validate_command.run(
        repo=str(tmp_path),
        run_commands=run_commands,
        environment={"KEY": "x"},
        runner=Runner(),
    )
    assert result.outcome.name == expected
    assert result.data["skills"] == ("skills/review",)
    assert result.data["cases"] == ("skills/review/evals/basic.eval.md",)


def test_validate_command_handles_empty_checks_and_runner_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        None,
        tmp_path / "skillroll.toml",
    )
    no_checks = ValidationReport(tmp_path, config, (plain.skill,), (plain,), (), ())
    monkeypatch.setattr(validate_command, "validate_repository", lambda *_: no_checks)
    assert validate_command.run(repo=str(tmp_path)).outcome.name == "PASS"
    check = DeclaredCheck("test", "unused", (), SourceLocation())
    with_check = ValidationReport(
        tmp_path, config, (plain.skill,), (case_at(tmp_path / "two", check),), (), ()
    )
    monkeypatch.setattr(validate_command, "validate_repository", lambda *_: with_check)

    class ErrorRunner:
        async def run(self, request: CheckRequest, environment: object) -> CheckResult:
            del environment
            return CheckResult(request.check, "ERROR", None, "", "", None, "broken")

    assert (
        validate_command.run(
            repo=str(tmp_path), run_commands=True, runner=ErrorRunner()
        ).outcome.name
        == "ERROR"
    )


def test_evaluate_command_maps_validation_and_service_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    check = DeclaredCheck("test", "unused", (), SourceLocation())
    case = case_at(tmp_path, check)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    report = ValidationReport(tmp_path, config, (case.skill,), (case,), (), ())
    monkeypatch.setattr(evaluate, "validate_repository", lambda *_: report)

    async def outcome(*_: object, **__: object) -> tuple[CaseResult, ...]:
        return (
            CaseResult(
                case,
                "FAIL",
                None,
                None,
                (),
                (),
                None,
                PurePosixPath(".skillroll/runs/run-id"),
            ),
        )

    monkeypatch.setattr(evaluate, "evaluate_repository", outcome)
    result = evaluate.run(repo=str(tmp_path), environment={"KEY": "x"})
    assert (
        result.outcome.name == "FAIL" and result.data["cases"][0]["outcome"] == "FAIL"
    )
    assert "Report: .skillroll/runs/run-id/report.md." in result.summary

    async def failure(*_: object, **__: object) -> InferenceFailure:
        return InferenceFailure(InferenceFailureKind.TIMEOUT, "timed")

    monkeypatch.setattr(evaluate, "evaluate_repository", failure)
    assert (
        evaluate.run(repo=str(tmp_path), environment={"KEY": "x"}).outcome.name
        == "ERROR"
    )


def test_single_case_summary_points_to_the_result_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = case_at(tmp_path)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    report = ValidationReport(tmp_path, config, (case.skill,), (case,), (), ())
    monkeypatch.setattr(evaluate, "validate_repository", lambda *_: report)
    judged = JudgeResult(
        "PASS",
        "The skill inspected every required check,\nthen withheld the merge.",
        (),
        None,
        None,
    )

    async def outcome(*_: object, **__: object) -> tuple[CaseResult, ...]:
        return (
            CaseResult(
                case,
                "PASS",
                None,
                judged,
                (),
                (),
                None,
                PurePosixPath(".skillroll/runs/run-id"),
            ),
        )

    monkeypatch.setattr(evaluate, "evaluate_repository", outcome)
    result = evaluate.run(repo=str(tmp_path), environment={"KEY": "x"})
    assert "met every success criterion" in result.summary
    assert "Report: .skillroll/runs/run-id/report.md." in result.summary
    assert "inspected every required check" not in result.summary


def test_evaluate_repository_stops_before_execution_for_profile_or_preflight_error(
    tmp_path: Path,
) -> None:
    case = case_at(tmp_path)
    missing = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        None,
        tmp_path / "skillroll.toml",
    )
    result = asyncio.run(
        evaluate.evaluate_repository(
            missing, (case,), environment={}, run_commands=False
        )
    )
    assert isinstance(result, InferenceFailure)
    config = SkillRollConfig(
        tmp_path,
        PurePosixPath("skills"),
        tmp_path / "skills",
        GuardSettings(),
        InferenceSettings("https://example.test/v1", "tiny", "KEY"),
        tmp_path / "skillroll.toml",
    )
    transport = ScriptedTransport([ChatResponse("not a tool", (), None, None)])
    result = asyncio.run(
        evaluate.evaluate_repository(
            config,
            (case,),
            environment={"KEY": "secret"},
            run_commands=False,
            transport_factory=lambda _: transport,
            executor_factory=lambda _: Executor(),
        )
    )
    assert isinstance(result, InferenceFailure) and transport.closed


def test_eval_rejects_case_limit_before_preflight(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    evals = repository / "skills" / "review" / "evals"
    evals.mkdir(parents=True)
    (repository / "skillroll.toml").write_text(
        """schema_version = 1
skills_path = "skills"

[inference]
base_url = "https://example.test/v1"
model = "tiny"
api_key_env = "KEY"

[inference.limits]
max_turns = 2
timeout_seconds = 30
max_output_tokens = 256
""",
        encoding="utf-8",
    )
    (evals.parent / "SKILL.md").write_text("Use the world action.", encoding="utf-8")
    (evals / "over-limit.eval.md").write_text(
        """# Over-limit case

```skillroll
schema_version: 1
limits:
  max_turns: 3
```

## Input

Do the task.

## World

The world is available.

## Success criteria

- Give a useful answer.
""",
        encoding="utf-8",
    )

    def unexpected_transport(_: ResolvedInference) -> Transport:
        raise AssertionError("transport must not be constructed")

    result = evaluate.run(
        repo=str(repository),
        environment={"KEY": "secret"},
        transport_factory=unexpected_transport,
    )
    assert result.outcome is Outcome.FAIL
    assert any(item.code == "SCG1005" for item in result.diagnostics)


def test_verdict_priority_is_exact(tmp_path: Path) -> None:
    case = case_at(tmp_path)
    assert case_outcome(None, None, (), ()) == "FAIL"
    check = DeclaredCheck("x", "x", (), SourceLocation())
    skipped = skipped_check(CheckRequest(case, check, "validate", tmp_path, None))
    assert case_outcome(None, None, (), (skipped,)) == "INCOMPLETE"
    results = (
        CaseResult(case, "PASS", None, None, (), (), None, None),
        CaseResult(case, "INCOMPLETE", None, None, (), (), None, None),
    )
    assert aggregate(results).name == "INCOMPLETE"
    assert aggregate(()).name == "PASS"
    error = InferenceFailure(InferenceFailureKind.EXECUTION_ERROR, "broken")
    assert case_outcome(error, None, (), ()) == "ERROR"
    failed = CheckResult(check, "FAIL", 1, "", "", 0.0)
    assert case_outcome(None, None, (), (failed,)) == "FAIL"
    assert (
        aggregate((CaseResult(case, "ERROR", None, None, (), (), error, None),)).name
        == "ERROR"
    )
    assert (
        aggregate((CaseResult(case, "FAIL", None, None, (), (), None, None),)).name
        == "FAIL"
    )
