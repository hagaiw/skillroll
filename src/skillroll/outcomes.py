"""Stable command outcomes and process exit codes."""

from enum import Enum


class Outcome(Enum):
    """The four ways a SkillRoll command can finish."""

    PASS = 0
    FAIL = 1
    INCOMPLETE = 2
    ERROR = 3

    @property
    def exit_code(self) -> int:
        """Return the stable process exit code for this outcome."""
        return int(self.value)
