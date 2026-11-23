"""任务定义（W2-1 的最小形态；W2-2 在此基础上做成正式任务集）。

一个任务 = 一份任务陈述 + 一份要落到沙箱里的初始文件 + 一条验收命令。
验收命令与验收文件对 Agent 只读，这是 $\\mathcal V$ 与候选修改之间的边界。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .sandbox import CommandResult, Sandbox, default_test_command


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
        sandbox.initialize_files(self.files, self.protected)

    def verify(self, sandbox: Sandbox, timeout: float = 120.0):
        cmd = list(self.test_command) if self.test_command else default_test_command()
        return sandbox.run(cmd, timeout=timeout)


@dataclass(kw_only=True)
class LiteralFixtureTask(Task):
    """脚本自检的固定答案。只比较指定文件的文本，运行轨迹注明判定来源。"""

    fixture_name: str
    fixture_text: str

    def verify(self, sandbox: Sandbox, timeout: float = 120.0) -> CommandResult:
        actual = sandbox.read_file(self.fixture_name, limit=len(self.fixture_text) + 1)
        matched = actual == self.fixture_text and self.fixture_name in sandbox.list_files()
        detail = "固定样例文本一致" if matched else "固定样例文本不同"
        return CommandResult(0 if matched else 1, detail, "", verdict_source="固定样例文本比对（未执行候选代码）")


def materialize_task(task: Task, sandbox: Sandbox) -> Sandbox:
    task.materialize(sandbox)
    return sandbox


def load_task_dir(path: Path) -> Task:
    """从目录读取任务：statement.md + 任意初始文件 + test.json（可选）。"""
    import json

    path = Path(path)
    boundary = Sandbox(path)
    files = {
        name: boundary._resolve(name).read_text(encoding="utf-8")
        for name in boundary.list_files()
        if Path(name).name not in {"statement.md", "test.json"}
    }
    meta = {}
    meta_path = boundary._resolve("test.json")
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    statement_path = boundary._resolve("statement.md")
    return Task(
        task_id=path.name,
        statement=statement_path.read_text(encoding="utf-8") if statement_path.is_file() else "",
        files=files,
        test_command=meta.get("test_command"),
        protected=tuple(meta.get("protected", ())),
        family=meta.get("family", "unclassified"),
        split=meta.get("split", "unassigned"),
    )
