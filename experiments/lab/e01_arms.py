"""E01 四格的实现（协议：`experiments/protocols/E01.md`）。

本文件只实现四格的**机制**，不含任何实验结果，也不含任何数字。

四格共用同一个 `StaticAgent` 循环与同一个 episode 预算（每个封存题 1 个 episode，
训练集上各 E 个 episode），差别只在三件事：

| 格 | 系统提示里有没有记忆块 | 记忆从哪来 | 任务内有没有多花一次模型调用 |
| --- | --- | --- | --- |
| 1 独立重跑 | 无 | — | 否 |
| 2 只读不写 | 有，$t=0$ 外部构建 | `build_external_memory()`，取自任务集规格的失效模式清单 | 否 |
| 3 每任务适配 | 有，任务内笔记 | `adapt_note()`，产物随任务结束丢弃 | 是（1 次，进副账） |
| 4 跨任务持久 | 有，检索 $M$ | 训练期由 agent 自己的轨迹 + 验收结果写成 | 训练期每题 1 次写入（进副账） |

钱要算在副账上：格 3 的适配调用、格 4 的写入调用都不占 episode 配额，
但会真实花掉模型调用数与 token，所以由 `run_e01.py` 单独记账。
"""

from __future__ import annotations

from typing import Optional

from .static_agent import SYSTEM_PROMPT, StaticAgent
from .tasks import Task
from .taskset_spec import FAMILIES

GRIDS = ("grid1", "grid2", "grid3", "grid4")

GRID_LABELS = {
    "grid1": "独立重跑，取最好的一次",
    "grid2": "持久物在 t=0 外部构建，此后只读不写",
    "grid3": "每任务单独适配，用完即弃",
    "grid4": "跨任务持久更新，记忆在生长",
}


# --------------------------------------------------------------------- 记忆块


def memory_block(items: list[str], header: str = "以下是过去积累的注意事项：") -> str:
    """把若干条记忆拼成一段可注入系统提示的文本。空记忆返回空串（不注入）。"""
    if not items:
        return ""
    body = "\n".join(f"- {t}" for t in items)
    return f"\n\n{header}\n{body}\n"


def build_external_memory() -> list[str]:
    """格 2 的持久物：$t=0$ 由外部构建，此后只读。

    来源是任务集规格里**作者写的**失效模式描述（`taskset_spec.FAMILIES[i]["failure_mode"]`），
    不是 agent 的轨迹，也不含任何参考实现——它只有"这类任务容易在哪错"，没有"怎么改"。
    这样格 2 才测的是"有持久物但从不生长"，而不是"送答案"。
    """
    return [f"{fam}：{spec['failure_mode']}" for fam, spec in sorted(FAMILIES.items())]


# --------------------------------------------------------------------- 检索


def _bigrams(text: str) -> set[str]:
    text = "".join(ch for ch in text if not ch.isspace())
    return {text[i:i + 2] for i in range(len(text) - 1)}


def retrieve(lessons: list[dict], statement: str, k: int = 2) -> list[str]:
    """按字符二元组重叠检索，取前 k 条。

    刻意**不用**任务族标签：族是任务集的元数据，真实 agent 拿不到，
    用它检索等于把标签泄漏进记忆索引。重叠全为 0 时退化为取最近 k 条。
    """
    if not lessons:
        return []
    query = _bigrams(statement)
    scored = []
    for i, item in enumerate(lessons):
        bg = _bigrams(item["text"])
        score = len(query & bg) / max(1, len(bg))
        scored.append((score, i, item["text"]))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [t for _, _, t in scored[:k]]


# --------------------------------------------------------------------- 写入 / 适配


WRITE_PROMPT = """你在一次编程任务上的最终结果如下。

任务陈述：
{statement}

你最后写在 main.py 里的代码：
{code}

验收结果：{verdict}

请写一条不超过 60 字的经验，供以后做同类任务时少犯同样的错。
只输出这一条经验本身，不要写解释、不要写标题、不要复述代码。"""

ADAPT_PROMPT = """下面是你马上要解决的任务。请先诊断这类任务最容易在哪里出错，
写一份不超过 60 字的注意事项（这份注意事项只在本任务内有效，任务结束就丢弃）。

任务陈述：
{statement}

当前仓库里的文件：
{files}

只输出这份注意事项本身，不要写解释、不要动手改代码。"""


def extract_lesson(backend, task: Task, sandbox_code: dict[str, str], verdict: bool) -> tuple[str, dict]:
    """格 4 训练期的写入：由 agent 自己的轨迹 + 验收结果生成一条记忆。

    输入只有三样 agent 本就看得见的东西：任务陈述、它自己最后写的代码、验收器给的结果。
    任务集规格里的正确实现不进沙箱，因此不会泄漏答案。
    返回 (记忆文本, 这次写入调用的花费)。
    """
    code = "\n".join(f"# {name}\n{content}" for name, content in sorted(sandbox_code.items()))
    prompt = WRITE_PROMPT.format(
        statement=task.statement,
        code=code[:4000],
        verdict="通过" if verdict else "未通过",
    )
    reply = backend.generate([{"role": "user", "content": prompt}])
    cost = {
        "calls": 1,
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
    }
    return reply.text.strip().replace("\n", " ")[:200], cost


def adapt_note(backend, task: Task) -> tuple[str, dict]:
    """格 3 的任务内适配：多花一次模型调用换一份只在本任务内有效的笔记。"""
    files = "\n".join(f"- {name}" for name in sorted(task.files))
    prompt = ADAPT_PROMPT.format(statement=task.statement, files=files or "- （空仓库）")
    reply = backend.generate([{"role": "user", "content": prompt}])
    cost = {
        "calls": 1,
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
    }
    return reply.text.strip().replace("\n", " ")[:200], cost


# --------------------------------------------------------------------- 组装 Agent


def build_agent(
    grid: str,
    backend,
    memory_items: Optional[list[str]] = None,
    name: Optional[str] = None,
) -> StaticAgent:
    """按格号造出这一格的 agent。四格共用同一个循环，只有系统提示不同。"""
    if grid not in GRIDS:
        raise ValueError(f"未知格号：{grid}")
    items = list(memory_items or [])
    if grid == "grid2":
        # 格 2 的记忆恒为外部记忆，调用方传什么都不改写它
        items = build_external_memory()
        header = "以下是这个任务集里已知的常见失效模式（只读，任务结束后不会更新）："
    else:
        header = "以下是过去积累的注意事项："
    prompt = SYSTEM_PROMPT + memory_block(items, header)
    return StaticAgent(backend=backend, system_prompt=prompt, name=name or grid)
