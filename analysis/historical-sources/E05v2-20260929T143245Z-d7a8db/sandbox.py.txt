"""文件与命令沙箱。

任务工作副本一律建在临时目录下，Agent 只能看见这一个目录。
验收器（测试）由本模块执行，返回结果给 Agent；**测试文件本身不在可写集合里**，
这样 $\\mathcal V$ 与候选修改处在独立边界上（spec/outline-v0.4.md §6.3 第 8 条）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

FORBIDDEN_WRITE_SUFFIXES = ("test_", "_test.py", "conftest.py")


class SandboxViolation(RuntimeError):
    pass


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def as_text(self, limit: int = 4000) -> str:
        out = self.stdout[-limit:]
        err = self.stderr[-limit:]
        return f"exit={self.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"


class Sandbox:
    """一个任务一个目录；写入路径必须解析后仍落在该目录内。"""

    def __init__(self, root: Path, protected: Sequence[str] = ()) -> None:
        self.root = Path(root).resolve()
        self.protected = set(protected)

    @classmethod
    def create_temp(cls, prefix: str = "task") -> "Sandbox":
        root = Path(tempfile.mkdtemp(prefix=f"{prefix}-"))
        return cls(root)

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _resolve(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root)):
            raise SandboxViolation(f"路径越界：{rel}")
        return p

    def list_files(self) -> list[str]:
        return sorted(
            str(p.relative_to(self.root)).replace("\\", "/")
            for p in self.root.rglob("*")
            if p.is_file()
        )

    def read_file(self, rel: str, limit: int = 8000) -> str:
        p = self._resolve(rel)
        if not p.is_file():
            return f"<不存在的文件：{rel}>"
        return p.read_text(encoding="utf-8", errors="replace")[:limit]

    def write_file(self, rel: str, content: str) -> str:
        p = self._resolve(rel)
        name = p.name
        if name in self.protected or any(name.startswith(s) for s in FORBIDDEN_WRITE_SUFFIXES):
            raise SandboxViolation(f"禁止写入验收器文件：{rel}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {rel}（{len(content)} 字符）"

    def run(self, command: Sequence[str], timeout: float = 120.0) -> CommandResult:
        try:
            proc = subprocess.run(
                list(command),
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            return CommandResult(proc.returncode, proc.stdout, proc.stderr)
        except subprocess.TimeoutExpired as exc:
            return CommandResult(-1, exc.stdout or "", exc.stderr or "", timed_out=True)


def default_test_command() -> list[str]:
    """默认验收命令。

    注意：本机 PyPI 不可达导致 pytest 无法安装（已登记 agent/BLOCKERS.md），
    因此内置冒烟任务使用标准库 unittest。正式任务集（W2-2）若要用 pytest，
    需先恢复安装能力，或在任务定义里显式给出可运行的命令。
    """
    return [sys.executable, "-m", "unittest", "-q"]
