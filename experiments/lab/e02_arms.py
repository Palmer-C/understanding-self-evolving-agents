"""E02 六臂的保留实现（协议：`experiments/protocols/E02.md`）。

本文件实现反馈构造与 Agent 组装，不含实验结果。
六臂共用 `StaticAgent` 循环与 episode 预算；构造时使用同一份
`SYSTEM_PROMPT_NO_VERIFY`，提示只列出列目录、读文件、写文件。
当前 `StaticAgent` 仍保留 `run_tests` 分派入口，提示未列出不等于执行器强制禁用。
归档运行 `E02-20260924T153511Z-421eac` 的 528 条保存轨迹中该工具调用为零；运行未绑定当时源码，
不能仅凭本文件恢复历史工具权限。

| 臂 | 写记忆时看到的信号 |
| --- | --- |
| `arm_base` | 不写记忆，不注入经验条目 |
| `arm_formal` | 验收器判定（通过 / 未通过）与完整输出 |
| `arm_exec` | 同一次执行输出，删去退出码与总结行；回溯等细节仍可能透露成败 |
| `arm_review` | 同一后端的独立只读评审请求，包含显式判定 |
| `arm_self` | 同一后端的独立自评措辞请求，包含显式判定 |
| `arm_noise` | 形式判定按固定翻转率处理；执行输出仍保留 |

`review` 与 `self` 都只向后端提交新的 user 消息，不继承求解历史。
载荷由保留代码中的 `_render_code` 构造，包含任务文件并截取前 4000 字符。
这里沿用的“学习式评审”“内在自评”和四层次顺序是旧协议命名与待检验假设，
不证明由不同模型、保留自身历史的角色或已成立的反馈强弱排序组成。
各反馈臂分别求解训练任务并生成经验，完整方案的差值也不能只归因于一句措辞。
"""

from __future__ import annotations

import random
import re
import sys
from typing import Optional

from .static_agent import StaticAgent
from .tasks import Task

ARMS = ("arm_base", "arm_formal", "arm_exec", "arm_review", "arm_self", "arm_noise")

# 有反馈的臂（arm_base 不写记忆，因此没有反馈）
FEEDBACK_ARMS = ("arm_formal", "arm_exec", "arm_review", "arm_self", "arm_noise")

# 验证层级的梯子，从高到低；P2b 的单调性按这个顺序检验
LADDER = ("arm_formal", "arm_exec", "arm_review", "arm_self")

ARM_LABELS = {
    "arm_base": "无反馈基线：不写、不检索任何持久物",
    "arm_formal": "形式化 / 可执行验证：验收器判定 + 完整输出",
    "arm_exec": "环境结果：原始执行输出，无对错标签",
    "arm_review": "学习式评审：另一模型只读代码给评审与判定",
    "arm_self": "内在自评：做题者自己回看代码给判断",
    "arm_noise": "受控噪声对照：形式判定按固定翻转率翻转",
}

DEFAULT_NOISE_RATE = 0.30

# --------------------------------------------------------------------- 系统提示

# 协议 §2.3 的提示设计：工具表不列 run_tests，并告知 Agent 不会收到执行结果。
# 这段提示不负责强制工具权限；当前 StaticAgent 仍保留该工具的分派入口。
SYSTEM_PROMPT_NO_VERIFY = """你是一个编程 Agent。目标：修改当前仓库，使验收命令通过。

每轮回复可以写任意长度的推理，但最多只能包含一行工具调用，格式严格为：
CALL <工具名> <一行 JSON 参数>
可用工具：
- list_files {}
- read_file {"path": "相对路径"}
- write_file {"path": "相对路径", "content": "完整文件内容"}
认为已经完成时，写单独一行：FINISH

约束：
- 不要修改或新建任何测试文件，验收器不在你的可写范围内。
- 先读再改；想清楚后一次写对，写完就 FINISH。
- 运行环境不会给你任何执行结果，也不会告诉你是否正确，所以不要试图调用不存在的执行工具。
"""


# --------------------------------------------------------------------- 反馈通道

# 明确给出对错的总结行：arm_exec 必须删掉它们，否则它就等于 arm_formal
_SUMMARY_RE = re.compile(
    r"^(exit=-?\d+|OK|FAILED\b.*|Ran \d+ tests?.*)$"
)

_VERDICT_RE = re.compile(r"判定\s*[:：]\s*(通过|未通过)")


def strip_verdict(text: str) -> str:
    """删掉退出码与测试总结行，只留原始执行输出（协议 §2.2）。"""
    kept = [ln for ln in text.splitlines() if not _SUMMARY_RE.match(ln.strip())]
    out = "\n".join(kept).strip()
    return out or "（本次执行没有产生任何可读输出）"


def formal_feedback(res) -> tuple[str, bool]:
    """层级 1：验收器的判定 + 完整输出。判定由 `res.ok` 给出，不是模型自评。"""
    text = f"验收结果：{'通过' if res.ok else '未通过'}\n{res.as_text()}"
    return text, bool(res.ok)


def exec_feedback(res) -> tuple[str, Optional[bool]]:
    """层级 2：只有原始执行输出，没有对错标签。

    返回值第二项是**实验台私下记录**的"退出码为 0"，它不出现在给 Agent 的文本里，
    只用于算错误更新率（协议 §5）。
    """
    text = "下面是这次执行产生的原始输出（没有给出通过与否的判定）：\n" + strip_verdict(res.as_text())
    return text, bool(res.returncode == 0 and not res.timed_out)


REVIEW_PROMPT = """你是评审者。下面是一个编程任务和提交者最后写在仓库里的代码。
你不执行任何代码，只能读代码。请指出它最可能错在哪里。

任务陈述：
{statement}

代码：
{code}

要求：
1. 先写不超过 60 字的具体问题，指出位置或条件；
2. 最后一行严格写成：判定：通过 或 判定：未通过

不要写代码，不要复述任务，不要写与判定无关的内容。"""


SELF_PROMPT = """下面是你刚刚完成的编程任务，以及你最后写在仓库里的代码。
你没有运行过它，也没有任何人或测试告诉过你结果。请回看自己的代码，
判断它是否满足任务要求，并指出最可能错的地方。

任务陈述：
{statement}

代码：
{code}

要求：
1. 先写不超过 60 字的判断依据；
2. 最后一行严格写成：判定：通过 或 判定：未通过

不要写代码，不要动手改，不要假设已经跑过测试。"""


def _model_judgement(backend, prompt: str) -> tuple[str, Optional[bool], dict]:
    """学习式评审 / 内在自评共用的模型判定通道。"""
    reply = backend.generate([{"role": "user", "content": prompt}])
    text = reply.text.strip()
    m = _VERDICT_RE.search(text)
    implied = None
    if m:
        implied = m.group(1) == "通过"
    cost = {
        "calls": 1,
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
    }
    return text, implied, cost


def review_feedback(backend, task: Task, code: dict[str, str]) -> tuple[str, Optional[bool], dict]:
    """旧协议层级 3：同一后端接收独立的只读评审提示，不继承求解历史。"""
    prompt = REVIEW_PROMPT.format(statement=task.statement, code=_render_code(code))
    return _model_judgement(backend, prompt)


def self_feedback(backend, task: Task, code: dict[str, str]) -> tuple[str, Optional[bool], dict]:
    """旧协议层级 4：同一后端接收独立的自评措辞提示，不继承求解历史。"""
    prompt = SELF_PROMPT.format(statement=task.statement, code=_render_code(code))
    return _model_judgement(backend, prompt)


def noise_feedback(res, rng: random.Random, rate: float) -> tuple[str, bool, bool]:
    """受控噪声对照：把形式判定按固定翻转率翻转。

    返回 (给 Agent 的文本, 翻转后的判定, 本次是否发生翻转)。
    """
    truth = bool(res.ok)
    flipped = rng.random() < rate
    shown = (not truth) if flipped else truth
    text = f"验收结果：{'通过' if shown else '未通过'}\n{res.as_text()}"
    return text, shown, flipped


def _render_code(code: dict[str, str]) -> str:
    body = "\n".join(f"# {name}\n{content}" for name, content in sorted(code.items()))
    return body[:4000]


# --------------------------------------------------------------------- 写记忆

LESSON_PROMPT = """你在一次编程任务上的尝试结束，下面是这次尝试得到的反馈。

任务陈述：
{statement}

你最后写在仓库里的代码：
{code}

这次得到的反馈：
{feedback}

请写一条不超过 60 字的经验，供以后做同类任务时少犯同样的错。
只输出这一条经验本身，不要写解释、不要写标题、不要复述代码。"""


def extract_lesson(backend, task: Task, code: dict[str, str], feedback: str) -> tuple[str, dict]:
    """六臂共用的写入：只有 `{feedback}` 一处不同（协议 §2.1）。"""
    prompt = LESSON_PROMPT.format(
        statement=task.statement,
        code=_render_code(code),
        feedback=feedback[:3000],
    )
    reply = backend.generate([{"role": "user", "content": prompt}])
    cost = {
        "calls": 1,
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
    }
    return reply.text.strip().replace("\n", " ")[:200], cost


# --------------------------------------------------------------------- 组装 Agent


def build_agent(arm: str, backend, memory_items: Optional[list[str]] = None,
                name: Optional[str] = None) -> StaticAgent:
    """六臂共用同一个循环；`arm_base` 不注入任何记忆块。"""
    if arm not in ARMS:
        raise ValueError(f"未知臂名：{arm}")
    items = [] if arm == "arm_base" else list(memory_items or [])
    from .e01_arms import memory_block  # 局部导入：与 E01 共用同一段拼装逻辑

    prompt = SYSTEM_PROMPT_NO_VERIFY + memory_block(items)
    return StaticAgent(backend=backend, system_prompt=prompt, name=name or arm)
