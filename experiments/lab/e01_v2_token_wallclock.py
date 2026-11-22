"""Offline token and wall-clock hard ceilings for E01 v2 (contract only).

Addresses the next offline prerequisite stated in E01-v2-draft §13-16 and
re-emphasized at lines 39 / 113 / 137: a per-backend-call output-token ceiling
and a whole-run wall-clock stop condition. Draft line 39 specifies the main
resource caps should use backend model call count, with a per-call output token
upper bound and a total wall-clock stop condition: "输出 token 每次上限 ... 总墙钟停止条件".

This module is a PURE OFFLINE CONTRACT. There is no backend, no paid execution,
no OS isolation, and no real clock here. Callers feed SIMULATED token counts and
elapsed seconds; the guard raises ``TokenCeilingExceeded`` / ``WallClockExceeded``
when a hard limit would be crossed. It is deliberately NOT wired into a live
runner: per the honest scope (R11.4), only the synthetic U-extraction stage in
the offline assembly fixture consults it, while prepare/solve/test/retry phases
are not modeled and therefore not under its control.

INTEGRATION GAP (not claimed here): the guard is consulted only on the synthetic
U extraction in ``e01_v2_assembly``. No real token metering, no real wall-clock
timeout, and no paid backend occur. Wiring into a real runner (with real token
counts from the provider response and a real monotonic clock) is a separate
offline step that follows this component work.
"""
from __future__ import annotations
from dataclasses import dataclass
from .e01_v2_design import integer


class TokenCeilingExceeded(RuntimeError):
    """A single backend call would exceed its output-token ceiling."""


class WallClockExceeded(RuntimeError):
    """Cumulative wall-clock for the run would exceed the stop condition."""


@dataclass(frozen=True)
class HardCeiling:
    """Hard ceilings for one run.

    tokens_per_call: maximum output (completion) tokens a single backend call
        may return before it is rejected (draft line 39 "输出 token 每次上限").
    total_wall_clock_seconds: whole-run wall-clock stop condition; the run must
        stop once cumulative elapsed seconds exceed this (draft line 39
        "总墙钟停止条件").
    """

    tokens_per_call: int
    total_wall_clock_seconds: float

    def __post_init__(self):
        integer(self.tokens_per_call, 'tokens_per_call')
        if not 0 <= self.total_wall_clock_seconds < float('inf'):
            raise ValueError('total_wall_clock_seconds must be finite and >= 0')


class HardCeilingGuard:
    """Enforces ``HardCeiling`` on simulated token / wall-clock usage.

    No real resource is consumed. Callers pass the output-token count of a call
    and the elapsed seconds for a unit; the guard raises when a hard limit is
    crossed. ``elapsed_wall_clock`` tracks the cumulative simulated wall-clock so
    the assembly can stop the run at the configured boundary.
    """

    def __init__(self, ceiling: HardCeiling):
        if type(ceiling) is not HardCeiling:
            raise ValueError('HardCeiling required')
        self._ceiling = ceiling
        self._elapsed = 0.0

    @property
    def ceiling(self):
        return self._ceiling

    @property
    def elapsed_wall_clock(self):
        return self._elapsed

    def check_call_tokens(self, completion_tokens: int):
        """Reject a single call whose output tokens exceed the per-call ceiling."""
        integer(completion_tokens, 'completion_tokens')
        if completion_tokens > self._ceiling.tokens_per_call:
            raise TokenCeilingExceeded(
                f'call output tokens {completion_tokens} exceed per-call ceiling '
                f'{self._ceiling.tokens_per_call}')

    def accumulate_wall_clock(self, elapsed_seconds: float):
        """Add a unit's elapsed seconds; reject once the cumulative stop is crossed."""
        if not 0 <= elapsed_seconds < float('inf'):
            raise ValueError('elapsed_seconds must be finite and >= 0')
        self._elapsed += float(elapsed_seconds)
        if self._elapsed > self._ceiling.total_wall_clock_seconds:
            raise WallClockExceeded(
                f'cumulative wall-clock {self._elapsed:g}s exceeds stop condition '
                f'{self._ceiling.total_wall_clock_seconds:g}s')
        return self._elapsed


def run_token_wallclock_demo(root, run_id):
    """Synthetic demonstration of the hard-ceiling contract; no API calls.

    Shows: (a) the per-call token ceiling rejects an over-limit call; (b) the
    wall-clock stop condition rejects once cumulative elapsed exceeds the limit.
    Returns a JSON-serializable record with ``api_calls=0``.
    """
    from pathlib import Path
    root = Path(root)
    identifier = _noop_identifier(run_id)
    permissive = HardCeiling(tokens_per_call=10**9, total_wall_clock_seconds=10**9)
    tight_token = HardCeiling(tokens_per_call=5, total_wall_clock_seconds=10**9)
    tight_clock = HardCeiling(tokens_per_call=10**9, total_wall_clock_seconds=3.0)
    results = {
        'identity': 'synthetic offline hard-ceiling contract; no model, no OS isolation, no paid execution',
        'api_calls': 0, 'run_id': run_id,
        'permissive_call_ok': None, 'permissive_clock_ok': None,
        'token_ceiling_rejected': None, 'wall_clock_stop_rejected': None,
    }
    g = HardCeilingGuard(permissive)
    try:
        g.check_call_tokens(1_000_000)
        g.accumulate_wall_clock(1.0)
        results['permissive_call_ok'] = True
        results['permissive_clock_ok'] = True
    except (TokenCeilingExceeded, WallClockExceeded):
        results['permissive_call_ok'] = False
    g = HardCeilingGuard(tight_token)
    try:
        g.check_call_tokens(6)
        results['token_ceiling_rejected'] = False
    except TokenCeilingExceeded:
        results['token_ceiling_rejected'] = True
    g = HardCeilingGuard(tight_clock)
    try:
        g.accumulate_wall_clock(2.0)
        g.accumulate_wall_clock(2.0)  # 4.0 > 3.0
        results['wall_clock_stop_rejected'] = False
    except WallClockExceeded:
        results['wall_clock_stop_rejected'] = True
    return results


def _noop_identifier(x):
    return x
