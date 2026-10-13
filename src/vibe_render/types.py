"""Small result types shared by the host and its command supervisor."""

# A dataclass groups the three outputs of a shell command into one named result.
from collections.abc import Sequence
from dataclasses import dataclass

# Commands may be shell text or literal arguments, such as ["python3", "test.py"].
WorkspaceCommand = str | Sequence[str]


@dataclass
class CommandResult:
    """An exit number plus the command's normal and error messages."""

    exit_code: int
    stdout: str
    stderr: str


class WorkspaceError(RuntimeError):
    """The remote command could not be run or its result could not be trusted."""


class WorkspaceTimeoutError(WorkspaceError):
    """The command exceeded its allotted time; partial output remains available."""

    def __init__(self, message: str, *, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.stdout, self.stderr = stdout, stderr


class WorkspaceOutputLimitError(WorkspaceTimeoutError):
    """Too much output would exceed host memory limits, so the command was stopped."""

    def __init__(self, message: str, *, limit: int, stdout: str, stderr: str):
        super().__init__(message, stdout=stdout, stderr=stderr)
        self.limit = limit
