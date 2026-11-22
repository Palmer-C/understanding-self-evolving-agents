"""E03 / E03c 的实现（协议：`experiments/protocols/E03.md`）。

本文件只实现两个轴的**机制**，不含任何实验结果，也不含任何数字。

E03c 与 E03 共用同一批运行（`spec/outline-v0.4.md` §6.1 的硬要求）：训练集上采一批
**来源记录**，五条经验条目（raw / summary / structured / solver / domain）全部由同一条
来源记录渲染出来。这样固定的是来源记录；不同渲染仍可能改变条目内容、长度与检索结果，
不能把比较差异单独归因于形式或拟合目标。

| 轴 | 臂 | 条目怎么来的 |
| --- | --- | --- |
| E03 形式 | `form_raw` | 原样截取来源记录（工具序列 + 最后代码 + 验收输出），**不经模型加工** |
| E03 形式 | `form_summary` | 模型把来源记录压成 ≤60 字自然语言，不带字段 |
| E03 形式 | `form_structured` | 模型写成带字段条目：事实 / 适用 / 不适用 |
| E03c 拟合目标 | `fit_solver` | 模型写成"针对当前这个模型的补丁"（第二人称，指名模型倾向） |
| E03c 拟合目标 | `fit_domain` | 模型写成"与谁读它无关的任务域事实"，带适用/不适用条件 |

读取者维度（换模型）由运行器 `run_e03.py` 决定用哪个后端，不在这里。
"""

from __future__ import annotations

from typing import Optional

from .e01_arms import memory_block
from .e02_arms import SYSTEM_PROMPT_NO_VERIFY
from .static_agent import StaticAgent

# 形式轴（E03）
FORM_ARMS = ("form_raw", "form_summary", "form_structured")

# 拟合目标轴（E03c）。读取者后缀由运行器拼：_same / _cross
FIT_TARGETS = ("fit_solver", "fit_domain")

# 族留出拆分 A 上跑的臂（P3 的主判据）
SPLIT_A_ARMS = ("base_same",) + FORM_ARMS

# 标准拆分 B 上跑的臂（P3b 的主判据）
SPLIT_B_ARMS = (
    "base_same",
    "base_cross",
    "fit_solver_same",
    "fit_solver_cross",
    "fit_domain_same",
    "fit_domain_cross",
)

ARM_LABELS = {
    "base_same": "无记忆基线（同模型）：不写、不检索任何持久物",
    "base_cross": "无记忆基线（换模型）：换模型臂的静态基线，缺它无法分离模型强弱",
    "form_raw": "原始轨迹条目：工具序列 + 最后代码 + 验收输出，不经模型加工",
    "form_summary": "摘要条目：≤60 字自然语言，不带任何结构字段",
    "form_structured": "结构化条目：事实 / 适用 / 不适用 三字段",
    "fit_solver_same": "拟合到求解器，同模型读：写成针对当前模型的补丁",
    "fit_solver_cross": "拟合到求解器，换模型读",
    "fit_domain_same": "拟合到问题域，同模型读：写成与读取者无关的任务域事实",
    "fit_domain_cross": "拟合到问题域，换模型读",
}

# `form_raw` 天然最长。长度是形式的一部分（协议 §7 第 1 条），
# 但截断长度必须写死并写进结果，否则"原始"两个字没有定义。
RAW_ITEM_CHARS = 600

# 渲染时给模型看的来源材料上限
SOURCE_CHARS = 3000


# --------------------------------------------------------------------- 来源记录


def source_record(task, code: dict[str, str], res, trace) -> dict:
    """把一次无记忆 episode 压成一条来源记录。

    五条经验条目全部由它渲染，所以它必须包含 agent 本就看得见的东西
    （任务陈述、它自己写的代码）与实验台才看得见的东西（真实验收结果、验收输出原文）。
    任务集规格里的正确实现不进沙箱，因此不会泄漏答案。
    """
    # 工具名记在 tool_result 步骤的 detail["tool"] 上（见 static_agent.run_episode
    # 第 133 行）；轨迹里没有单独的 "tool_call" 步骤，按 kind 取会取到空列表。
    tools = [s.detail.get("tool", "?") for s in trace.steps if s.kind == "tool_result"]
    return {
        "task_id": task.task_id,
        "family": task.family,
        "statement": task.statement,
        "code": code,
        "verdict": bool(res.ok),
        "verify_text": res.as_text(),
        "tool_calls": tools,
    }


def render_raw(rec: dict) -> str:
    """形式 1：原样截取，不经模型加工（0 次调用）。"""
    code = "\n".join(f"# {n}\n{c}" for n, c in sorted(rec["code"].items()))
    tools = " → ".join(t.split()[0] for t in rec["tool_calls"]) or "（无工具调用）"
    body = (
        f"来源任务 {rec['task_id']}（族 {rec['family']}）："
        f"工具序列 {tools}；"
        f"验收{'通过' if rec['verdict'] else '未通过'}；"
        f"验收输出 {rec['verify_text'][:400]}\n最后写下的代码：\n{code}"
    )
    return body[:RAW_ITEM_CHARS]


def _source_material(rec: dict) -> str:
    """四种模型渲染提示词里的"来源材料"部分，只有写作指令不同。raw 另按 render_raw 截取。"""
    code = "\n".join(f"# {n}\n{c}" for n, c in sorted(rec["code"].items()))
    return (
        f"任务陈述：\n{rec['statement']}\n\n"
        f"最后写下的代码：\n{code}\n\n"
        f"验收结果：{'通过' if rec['verdict'] else '未通过'}\n"
        f"验收输出原文：\n{rec['verify_text'][:800]}"
    )[:SOURCE_CHARS]


# --------------------------------------------------------------------- 渲染提示词
#
# 四种模型渲染共用同一段来源材料，写作指令不同；raw 另按 render_raw 截取。
# 同源不保证输出内容、长度或后续检索相同。

_SUMMARY_INSTR = """请写一条不超过 60 字的经验，供以后做同类任务时少犯同样的错。
只输出这一条经验本身，不要写解释、不要写标题、不要复述代码、不要加任何字段标记。"""

_STRUCTURED_INSTR = """请把这条来源记录整理成一条结构化经验，严格按下面三行输出，每行都以给出的前缀开头：
事实：<这条记录里关于任务本身的客观事实，不超过 50 字>
适用：<什么条件下该照这条做，不超过 30 字>
不适用：<什么条件下照这条做反而有害，不超过 30 字>
不要写这三行以外的任何内容。"""

_SOLVER_INSTR = """请把这条来源记录写成一条**针对刚才做题的那个模型**的补丁。
要求：
1. 用第二人称（"你"），直接指出这个模型在这类任务上的倾向或容易犯的错；
2. 可以依赖这个模型的具体习惯、措辞、默认行为；
3. 不超过 60 字，只输出这一条补丁本身，不要写解释或标题。"""

_DOMAIN_INSTR = """请把这条来源记录写成一条**与谁读它无关**的任务域事实。
要求：
1. 不出现"你"这个称呼，不指任何模型的习惯或倾向；
2. 只写关于这类任务本身的事实与不变量，任何读到它的人或模型都能用；
3. 严格按下面三行输出：
事实：<关于任务本身的客观事实，不超过 50 字>
适用：<什么条件下成立，不超过 30 字>
不适用：<什么条件下不成立，不超过 30 字>
不要写这三行以外的任何内容。"""

_RENDER_INSTR = {
    "form_summary": _SUMMARY_INSTR,
    "form_structured": _STRUCTURED_INSTR,
    "fit_solver": _SOLVER_INSTR,
    "fit_domain": _DOMAIN_INSTR,
}

RENDER_KINDS = tuple(_RENDER_INSTR)


def render_with_model(backend, rec: dict, kind: str) -> tuple[str, dict]:
    """用模型把来源记录渲染成指定形式的条目。返回 (条目文本, 副账开销)。"""
    if kind not in _RENDER_INSTR:
        raise ValueError(f"未知渲染类型：{kind}")
    prompt = (
        "下面是一次编程任务的来源记录。\n\n"
        f"{_source_material(rec)}\n\n"
        f"{_RENDER_INSTR[kind]}"
    )
    reply = backend.generate([{"role": "user", "content": prompt}])
    cost = {
        "calls": 1,
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
    }
    text = reply.text.strip().replace("\r", " ")[:400]
    return text, cost


# --------------------------------------------------------------------- 组装 Agent


def build_agent(arm: str, backend, memory_items: Optional[list[str]] = None,
                name: Optional[str] = None) -> StaticAgent:
    """按臂造 agent。所有臂共用同一个循环与同一段系统提示，只有注入的记忆块不同。"""
    base = arm.split("_cross")[0].split("_same")[0] if arm.startswith("fit_") else arm
    if base.startswith("base"):
        items: list[str] = []
    else:
        items = list(memory_items or [])
    header = "以下是过去积累的注意事项："
    prompt = SYSTEM_PROMPT_NO_VERIFY + memory_block(items, header)
    return StaticAgent(backend=backend, system_prompt=prompt, name=name or arm)
