"""任务工作副本的文件工具。工作目录由单个可信进程管理。

进程隔离执行器尚未接入。候选代码和验收命令只能交给独立的执行器。
"""

from __future__ import annotations

import ntpath
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Mapping, NoReturn, Sequence

from .e01_v2_execution import ExecutionUnavailable
from .e01_v2_file_boundary import FileBoundaryViolation, relative_name


class SandboxViolation(RuntimeError):
    pass


def require_isolated_execution() -> NoReturn:
    raise ExecutionUnavailable("当前版本仅支持离线操作，执行候选代码需要操作系统级隔离执行器。")


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    verdict_source: str = "task.verify（执行器报告的命令结果）"

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def as_text(self, limit: int = 4000) -> str:
        out = self.stdout[-limit:]
        err = self.stderr[-limit:]
        return f"exit={self.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"


def _file_name(value: str) -> str:
    try:
        name = relative_name(value)
    except FileBoundaryViolation as exc:
        raise SandboxViolation(str(exc)) from None
    if any(char in '<>"|?*' or ord(char) < 32 for char in name):
        raise SandboxViolation(f"无效文件名：{value}")
    if hasattr(ntpath, "isreserved"):
        reserved = ntpath.isreserved(name)
    else:
        reserved = any(PureWindowsPath(part).is_reserved() for part in name.split("/"))
    if reserved:
        raise SandboxViolation(f"保留文件名：{value}")
    return name


def _is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or (
        hasattr(info, "st_file_attributes") and bool(info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    )


class Sandbox:
    """访问一个可信工作目录内的普通文件。验收文件可由任务初始化，之后只读。"""

    def __init__(self, root: Path, protected: Sequence[str] = ()) -> None:
        self.root = Path(root).resolve()
        self.protected = set(protected)
        self._temporary = None

    @classmethod
    def create_temp(cls, prefix: str = "task") -> "Sandbox":
        if not re.fullmatch(r"[\w-]+", prefix):
            raise SandboxViolation("任务临时目录需要单个名称")
        temporary = tempfile.TemporaryDirectory(prefix=f"{prefix}-")
        sandbox = cls(Path(temporary.name))
        sandbox._temporary = temporary
        return sandbox

    def cleanup(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()

    def _resolve(self, rel: str) -> Path:
        rel = _file_name(rel)
        path = self.root / rel
        current = self.root
        for part in Path(rel).parts:
            current /= part
            try:
                info = current.lstat()
            except FileNotFoundError:
                break
            if _is_link(info):
                raise SandboxViolation(f"任务文件路径含有链接：{rel}")
            if current == path:
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise SandboxViolation(f"只接受普通的单链接文件：{rel}")
            elif not stat.S_ISDIR(info.st_mode):
                raise SandboxViolation(f"父路径不是目录：{rel}")
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root) or resolved == self.root:
            raise SandboxViolation(f"路径越界：{rel}")
        return resolved

    def list_files(self) -> list[str]:
        files = []
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            base = Path(directory)
            dirs[:] = [name for name in dirs if not _is_link((base / name).lstat())]
            for name in names:
                rel = (base / name).relative_to(self.root).as_posix()
                try:
                    self._resolve(rel)
                except SandboxViolation:
                    continue
                files.append(rel)
        return sorted(files)

    def initialize_files(self, files: Mapping[str, str], protected: Sequence[str]) -> None:
        """由任务加载器安装初始文件，包括只读的验收器。"""
        targets = [(self._resolve(rel), content) for rel, content in files.items()]
        keys = {str(path).casefold() for path, _ in targets}
        if len(keys) != len(targets):
            raise SandboxViolation("初始文件存在重复路径")
        if any(not isinstance(content, str) for _, content in targets):
            raise SandboxViolation("初始文件需要文本内容")
        self.protected.update({_file_name(name) for name in protected})
        for path, content in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def read_file(self, rel: str, limit: int = 8000) -> str:
        path = self._resolve(rel)
        if not path.is_file():
            return f"<不存在的文件：{rel}>"
        with path.open(encoding="utf-8", errors="replace") as source:
            return source.read(max(0, limit))

    def write_file(self, rel: str, content: str) -> str:
        path = self._resolve(rel)
        name = path.name.casefold()
        protected = {_file_name(item).casefold() for item in self.protected}
        if (path.relative_to(self.root).as_posix().casefold() in protected
                or name in protected or name.startswith(("test_", "_test.py", "conftest.py"))
                or name.endswith("_test.py")):
            raise SandboxViolation(f"禁止写入验收器文件：{rel}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"已写入 {rel}（{len(content)} 字符）"

    def run(self, command: Sequence[str], timeout: float = 120.0) -> CommandResult:
        require_isolated_execution()


def default_test_command() -> list[str]:
    """任务清单的默认验收命令，由隔离执行器消费。"""
    return [sys.executable, "-m", "unittest", "-q"]
