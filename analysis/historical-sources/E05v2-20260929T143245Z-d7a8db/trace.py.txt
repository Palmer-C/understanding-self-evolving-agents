"""轨迹与运行记录。

每条轨迹就是一个 episode $e$ 的完整记录：谁跑的、跑了什么、花了多少、判定结果是什么。
落盘格式统一为 JSON，便于 `experiments/results/` 的结果表按 run_id 回溯。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def new_run_id(prefix: str = "run") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"


@dataclass
class TraceStep:
    index: int
    kind: str  # system | model | tool_call | tool_result | error | verdict
    content: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class EpisodeTrace:
    run_id: str
    agent: str
    task_id: str
    seed: Optional[int]
    started_at: str
    steps: list[TraceStep] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    verdict: Optional[bool] = None
    verdict_source: str = "unknown"
    persistent_writes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def add(self, kind: str, content: str, **detail: Any) -> None:
        self.steps.append(TraceStep(index=len(self.steps), kind=kind, content=content, detail=detail))

    def as_dict(self) -> dict:
        return asdict(self)

    def write(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "trace.json"
        path.write_text(json.dumps(self.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path
