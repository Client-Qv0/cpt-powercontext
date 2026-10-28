"""Domain errors with actionable messages."""

from __future__ import annotations


class SpecAnchorError(RuntimeError):
    """Base class for expected, user-facing failures."""


class DatabaseUnavailable(SpecAnchorError):
    """seekdb / OceanBase is not reachable or not initialised."""


class MiniMaxError(SpecAnchorError):
    """The MiniMax request failed or returned an unusable answer."""


class PatchError(SpecAnchorError):
    """The model response was not a safe, applicable unified diff."""


class StateError(SpecAnchorError):
    """PowerContext state could not be written or read."""


class VerificationError(SpecAnchorError):
    """The sample project did not behave as the acceptance criteria require."""
