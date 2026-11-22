"""静态 Agent —— E01 的格 1 基线，也是全书所有对照的起点。

它的定义只有两条：

1. 每次任务都从**同一个**固定的 $A_0$ 出发：固定系统提示、固定工具集、固定循环；
2. 任务内可以随意推理与重试，但任务结束时不写任何持久物，$A$ 不变。

第 2 条由代码强制而不是靠注释：`persistent_writes` 在任何一次运行后必须为空，
非空即视为实验台被改坏，直接报错。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .backends import ScriptedBackend
from .budget import Budget, BudgetExceeded, Stopwatch, Usage, check_within
from .sandbox import Sandbox, SandboxViolation
from .tasks import Task
from .trace import EpisodeTrace, new_run_id

SYSTEM_PROMPT = """你是一个编程 Agent。目标：修改当前仓库，使验收命令通过。

每轮回复可以写任意长度的推理，但最多只能包含一行工具调用，格式严格为：
CALL <工具名> <一行 JSON 参数>
可用工具：
- list_files {}
- read_file {"path": "相对路径"}
- write_file {"path": "相对路径", "content": "完整文件内容"}
- run_tests {}
认为已经完成时，写单独一行：FINISH

约束：
- 不要修改或新建任何测试文件，验收器不在你的可写范围内。
- 先读再改；改完就跑验收，用验收输出决定下一步。
- 验收失败时，根据报错定位到具体位置再改，不要整篇重写。
"""

CALL_RE = re.compile(r"^CALL\s+(\w+)\s+(\{.*\})\s*$", re.MULTILINE)
FINISH_RE = re.compile(r"^FINISH\s*$", re.MULTILINE)


class StaticAgent:
    """固定 $A_0$，无跨任务持久状态。"""

    agent_id = "static-agent-v1"

    def __init__(self, backend=None, system_prompt: str = SYSTEM_PROMPT, name: Optional[str] = None) -> None:
        self.backend = backend or ScriptedBackend(["list_files {}"])
        self.system_prompt = system_prompt
        self.name = name or self.agent_id

    # ---- 工具 ----
    def _dispatch(self, sandbox: Sandbox, tool: str, args: dict, usage: Usage) -> str:
        usage.tool_calls += 1
        if tool == "list_files":
            return "\n".join(sandbox.list_files())
        if tool == "read_file":
            return sandbox.read_file(args["path"])
        if tool == "write_file":
            return sandbox.write_file(args["path"], args["content"])
        if tool == "run_tests":
            usage.test_runs += 1
            return "（验收由 verify() 执行；此处不重复运行）"
        raise SandboxViolation(f"未知工具：{tool}")

    # ---- 一个 episode ----
    def run_episode(
        self,
        task: Task,
        budget: Optional[Budget] = None,
        sandbox: Optional[Sandbox] = None,
        seed: Optional[int] = None,
        out_dir: Optional[Path] = None,
        test_timeout: float = 120.0,
        materialize: bool = True,
    ) -> EpisodeTrace:
        budget = budget or Budget()
        owns_sandbox = sandbox is None
        sandbox = sandbox or Sandbox.create_temp(prefix=task.task_id)
        if materialize:
            task.materialize(sandbox)

        trace = EpisodeTrace(
            run_id=new_run_id("static"),
            agent=self.name,
            task_id=task.task_id,
            seed=seed,
            started_at=datetime.now(timezone.utc).isoformat(),
            budget=budget.as_dict(),
        )
        usage = Usage()
        watch = Stopwatch()
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task.statement},
        ]
        trace.add("system", self.system_prompt)

        verdict = False
        try:
            while True:
                check_within(budget, usage, watch.tick())
                usage.steps += 1
                reply = self.backend.generate(messages)
                usage.add_call(reply.prompt_tokens, reply.completion_tokens)
                messages.append({"role": "assistant", "content": reply.text})
                trace.add("model", reply.text, tokens=reply.completion_tokens)

                if FINISH_RE.search(reply.text):
                    break
                m = CALL_RE.search(reply.text)
                if not m:
                    trace.add("error", "回复中没有可解析的 CALL 或 FINISH")
                    break
                tool, raw_args = m.group(1), m.group(2)
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError as exc:
                    trace.add("error", f"参数不是合法 JSON：{exc}", raw=raw_args)
                    continue
                try:
                    result = self._dispatch(sandbox, tool, args, usage)
                except (SandboxViolation, KeyError) as exc:
                    result = f"工具调用被拒绝：{exc}"
                if tool == "run_tests":
                    res = task.verify(sandbox, timeout=test_timeout)
                    result = f"验收结果：{'通过' if res.ok else '未通过'}\n{res.as_text()}"
                trace.add("tool_result", result, tool=tool, args=args)
                messages.append({"role": "user", "content": result})
        except BudgetExceeded as exc:
            trace.add("error", f"预算用尽：{exc}")
        finally:
            usage.wall_seconds = watch.tick()
            res = task.verify(sandbox, timeout=test_timeout)
            verdict = bool(res.ok)
            trace.add("verdict", "通过" if verdict else "未通过", exit=res.returncode)

        if getattr(self.backend, "name", "") == "scripted":
            usage.notes.append(
                "ScriptedBackend 的 token 数是字符数/4 的估算，不是真实计费 token，不得用于成本账"
            )
        trace.usage = usage.as_dict()
        trace.verdict = verdict
        trace.verdict_source = "task.verify（真实执行验收命令）"

        if trace.persistent_writes:
            raise RuntimeError(
                f"静态 Agent 产生了持久写入 {trace.persistent_writes}：它已经不是格 1 基线"
            )
        if out_dir is not None:
            trace.write(Path(out_dir))
        if owns_sandbox:
            sandbox.cleanup()
        return trace
