"""Pure deterministic predicates over one completed skill attempt."""

from __future__ import annotations

from dataclasses import dataclass

from skillroll.models import Assertion


@dataclass(frozen=True, slots=True)
class AssertionResult:
    """One visible fact about one authored assertion."""

    ordinal: int
    assertion: Assertion
    passed: bool
    observed: str


def evaluate_assertions(
    assertions: tuple[Assertion, ...], final_output: str
) -> tuple[AssertionResult, ...]:
    """Evaluate optional exact final-output facts independently."""
    results: list[AssertionResult] = []
    for ordinal, assertion in enumerate(assertions, start=1):
        passed: bool
        observed: str
        if assertion.kind == "final_output_contains":
            expected = assertion.expected_text
            assert expected is not None
            passed = expected in final_output
            observed = (
                "final output contains the requested literal"
                if passed
                else "final output did not contain the requested literal"
            )
        elif assertion.kind == "final_output_not_contains":
            expected = assertion.expected_text
            assert expected is not None
            passed = expected not in final_output
            observed = (
                "final output omitted the forbidden literal"
                if passed
                else "final output contained the forbidden literal"
            )
        elif assertion.kind == "final_output_equals":
            expected = assertion.expected_text
            assert expected is not None
            passed = final_output == expected
            observed = (
                "final output exactly matched"
                if passed
                else "final output did not exactly match"
            )
        else:
            raise AssertionError(f"Unsupported assertion kind: {assertion.kind}")
        results.append(AssertionResult(ordinal, assertion, passed, observed))
    return tuple(results)
