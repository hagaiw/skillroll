from skillroll.outcomes import Outcome


def test_outcome_exit_codes_are_stable() -> None:
    assert {item.name: item.exit_code for item in Outcome} == {
        "PASS": 0,
        "FAIL": 1,
        "INCOMPLETE": 2,
        "ERROR": 3,
    }
