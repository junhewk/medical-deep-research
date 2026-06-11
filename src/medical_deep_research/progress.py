"""Monotonic run-progress tracking shared by all runtimes.

The agent loop is not linear: rewind checkpoints and agentic tool choices can
revisit earlier phases (e.g. searching again after verification).  Percentages
derived from phase identity alone therefore jump backwards in the trace.

``ProgressTracker`` makes progress a function of *work done* instead:

- The percent value never decreases.  Each unit of work consumes a fraction of
  the headroom up to the next milestone, so progress keeps rising slowly even
  when the agent goes back to an earlier phase.
- A phase floor is applied only on the *first* entry to a phase.  Re-entering
  an earlier phase holds the percent steady and labels the phase with the pass
  number (``"searching (pass 2)"``) so the trace stays readable.
- ``complete()`` is the only way to reach 100; everything else is capped at 97.
"""

from __future__ import annotations

PHASE_ORDER: list[str] = [
    "init",
    "planning",
    "searching",
    "screening",
    "ranking",
    "fulltext",
    "appraising",
    "verifying",
    "evaluating",
    "synthesizing",
    "translating",
    "diagnostics",
    "complete",
]

# Applied on the FIRST entry to a phase only.
PHASE_FLOORS: dict[str, int] = {
    "planning": 5,
    "searching": 20,
    "screening": 45,
    "ranking": 55,
    "fulltext": 62,
    "appraising": 70,
    "verifying": 78,
    "evaluating": 82,
    "synthesizing": 88,
    "translating": 96,
    "diagnostics": 96,
}

# Asymptotic targets: advance() consumes headroom toward the smallest
# milestone above the current percent.
PHASE_MILESTONES: dict[str, int] = {
    "planning": 18,
    "searching": 44,
    "screening": 54,
    "ranking": 60,
    "fulltext": 68,
    "appraising": 76,
    "verifying": 82,
    "evaluating": 86,
    "synthesizing": 96,
    "translating": 97,
    "diagnostics": 97,
}

_HARD_CAP = 97
_HEADROOM_FRACTION = 0.15

_MILESTONE_VALUES = sorted(set(PHASE_MILESTONES.values()) | {_HARD_CAP})


class ProgressTracker:
    """Monotonic percent + phase pass labels for a single research run."""

    def __init__(self) -> None:
        self._percent = 0
        self._passes: dict[str, int] = {}
        self._current_phase: str | None = None
        self._completed = False

    @property
    def percent(self) -> int:
        return self._percent

    @property
    def current_phase(self) -> str | None:
        return self._current_phase

    def phase_label(self, phase: str) -> str:
        count = self._passes.get(phase, 1)
        return phase if count <= 1 else f"{phase} (pass {count})"

    def enter(self, phase: str) -> tuple[str, int]:
        """Register a (re-)entry into ``phase``.

        Returns ``(label, percent)``.  The floor jump happens only on the
        first-ever entry; coming back to an earlier phase increments its pass
        counter and holds the percent.
        """
        if phase != self._current_phase:
            if phase in self._passes:
                self._passes[phase] += 1
            else:
                self._passes[phase] = 1
                self._percent = max(self._percent, PHASE_FLOORS.get(phase, self._percent))
            self._current_phase = phase
        return self.phase_label(phase), self._percent

    def advance(self, phase: str | None = None) -> int:
        """Record one unit of work; returns the (non-decreasing) percent.

        ``phase`` is accepted for call-site readability and to implicitly
        enter the phase when the caller has not done so explicitly.
        """
        if phase is not None:
            self.enter(phase)
        if self._completed:
            return self._percent
        target = self._next_milestone_above(self._percent)
        gap = target - self._percent
        if gap > 0:
            self._percent = min(target, self._percent + max(1, round(gap * _HEADROOM_FRACTION)))
        self._percent = min(self._percent, _HARD_CAP)
        return self._percent

    def complete(self) -> int:
        """Mark the run finished; the only path to 100."""
        self._completed = True
        self._percent = 100
        return self._percent

    @staticmethod
    def _next_milestone_above(percent: int) -> int:
        for value in _MILESTONE_VALUES:
            if value > percent:
                return value
        return _HARD_CAP
