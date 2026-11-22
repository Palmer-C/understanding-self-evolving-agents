"""任务定义（W2-1 的最小形态；W2-2 在此基础上做成正式任务集）。

一个任务 = 一份任务陈述 + 一份要落到沙箱里的初始文件 + 一条验收命令。
验收命令与验收文件对 Agent 只读，这是 $\\mathcal V$ 与候选修改之间的边界。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .sandbox import Sandbox, default_test_command


@dataclass
class Task:
    task_id: str
    statement: str
    files: dict[str, str] = field(default_factory=dict)
    test_command: Sequence[str] | None = None  # None 表示用默认验收命令
    protected: Sequence[str] = ()
    family: str = "unclassified"  # 任务族标签，W2-2 用来做划分与迁移检验
    split: str = "unassigned"  # train / select-valid / regression / heldout / sealed

    def materialize(self, sandbox: Sandbox) -> None:
        for rel, content in self.files.items():
            p = sandbox.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

    def verify(self, sandbox: Sandbox, timeout: float = 120.0):
        cmd = list(self.test_command) if self.test_command else default_test_command()
        return sandbox.run(cmd, timeout=timeout)


def materialize_task(task: Task, sandbox: Sandbox) -> Sandbox:
    task.materialize(sandbox)
    return sandbox


def load_task_dir(path: Path) -> Task:
    """从目录读取任务：statement.md + 任意初始文件 + test.json（可选）。"""
    import json

    path = Path(path)
    files: dict[str, str] = {}
    for p in path.rglob("*"):
        if p.is_file() and p.name not in {"statement.md", "test.json"}:
            files[str(p.relative_to(path)).replace("\\", "/")] = p.read_text(encoding="utf-8")
    meta = {}
    meta_path = path / "test.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return Task(
        task_id=path.name,
        statement=(path / "statement.md").read_text(encoding="utf-8") if (path / "statement.md").is_file() else "",
        files=files,
        test_command=meta.get("test_command"),
        protected=tuple(meta.get("protected", ())),
        family=meta.get("family", "unclassified"),
        split=meta.get("split", "unassigned"),
    )
