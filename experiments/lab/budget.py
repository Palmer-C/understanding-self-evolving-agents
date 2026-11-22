"""预算与成本账。

口径（spec/outline-v0.4.md §6.3 第 4、6 条）：
- 配对任务比较，报告多次独立运行的不确定性；
- 重试、候选筛选、模型评审与失败运行都计入资源账。

价格纪律：本模块不内置任何价格表。未拿到有出处的定价表时 `usd` 一律为 None
并把 `unpriced` 置真，避免凭印象填价格。定价表由 P-1 在 `calculations/pricing.yaml` 给出。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Optional


class BudgetExceeded(RuntimeError):
    """预算用尽。抛出而不是静默截断——截断会让结果表少记资源。"""


@dataclass
class Budget:
    """一次 episode 的资源上限。所有字段都是硬上限，超了就中断并记账。"""

    max_calls: int = 8
    max_steps: int = 12
    max_prompt_tokens: int = 200_000
    max_completion_tokens: int = 20_000
    max_wall_seconds: float = 600.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Usage:
    calls: int = 0
    steps: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    wall_seconds: float = 0.0
    tool_calls: int = 0
    test_runs: int = 0
    unpriced: bool = True
    usd: Optional[float] = None
    notes: list[str] = field(default_factory=list)

    def add_call(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.calls += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens

    def as_dict(self) -> dict:
        return asdict(self)


class Stopwatch:
    """只负责计时，避免把 time 调用散落在各处导致口径不一致。"""

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self.elapsed = 0.0

    def tick(self) -> float:
        self.elapsed = time.perf_counter() - self._start
        return self.elapsed


def check_within(budget: Budget, usage: Usage, elapsed: float) -> None:
    """在任何一次消耗之后调用；超限即抛。"""
    if usage.calls >= budget.max_calls:
        raise BudgetExceeded(f"模型调用数达到上限 {budget.max_calls}")
    if usage.steps >= budget.max_steps:
        raise BudgetExceeded(f"步数达到上限 {budget.max_steps}")
    if usage.prompt_tokens > budget.max_prompt_tokens:
        raise BudgetExceeded(f"提示 token 达到上限 {budget.max_prompt_tokens}")
    if usage.completion_tokens > budget.max_completion_tokens:
        raise BudgetExceeded(f"生成 token 达到上限 {budget.max_completion_tokens}")
    if elapsed > budget.max_wall_seconds:
        raise BudgetExceeded(f"墙钟时间达到上限 {budget.max_wall_seconds}s")
