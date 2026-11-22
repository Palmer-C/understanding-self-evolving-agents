"""公共评测协议的代码实现（W2-3）。

对应 `spec/outline-v0.4.md` §6.3 第 4、5、7 条：

- 第 4 条：配对任务比较，报告多次独立运行的不确定性；
  置信区间的重采样单位应对应**独立任务或任务族**。
- 第 5 条：验证集查询预算 $Q$；超预算强制轮换验证集；封存集查询次数在报告前必须为 0。
- 第 7 条：报告能力维度，避免一个总分遮蔽局部退化。

本文件是**测量工具**，不含任何实验结果。它把自己能被测的部分测了：`--selftest`
在合成数据上验证统计口径与预算纪律，这些合成数据与任何方法的能力无关。

关于统计量：输出的是**通过率差 + 95% 自助区间**，差值以比例为单位。
转换成百分点时须乘以 100。返回的 degraded 字段保留历史判据，科学结论另按设计与范围解释。
区间用百分位自助法，重采样单位由调用者指定（任务或任务族）——这一条不是风格偏好，
同一批数据在两种单位下区间宽度差别很大，选错单位等于把独立样本数报多。
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

# 预注册的最小可检测效应：来自 research-notes-v0.3.md §14，
# 与 spec/propositions.md 中 P1 的 falsifier 使用同一个数。
DEFAULT_MDE = 0.03


class BudgetExceeded(RuntimeError):
    """查询预算用尽。抛出而不是静默放行——静默放行会让 Q 变成摆设。"""


class SealedViolation(RuntimeError):
    """封存集在报告前被查询过。这是协议级错误，不是数值误差。"""


@dataclass
class QueryBudget:
    """验证集查询预算 $Q$。

    口径（§6.3 第 5 条）：每个候选版本最多查询验证集 $Q$ 次；超预算强制轮换新验证集
    并记录累计查询次数；封存集查询次数在报告前必须为 0。
    """

    q: int = 200
    rotation: int = 0
    used_total: int = 0
    rejected: int = 0
    used_by_split: dict[str, int] = field(default_factory=dict)
    _used_this_rotation: int = 0

    def spend(self, split: str, task_id: str, n: int = 1) -> None:
        if split == "sealed":
            # 不拒绝，只记账：拒绝会让"偷看"变成静默失败，账上看不出来
            self.used_by_split["sealed"] = self.used_by_split.get("sealed", 0) + n
            self.used_total += n
            return
        if self._used_this_rotation + n > self.q:
            # 被拒绝的查询没有执行，不计入已用次数；单独记账，
            # 否则"撞过几次上限"这件事在账上完全看不出来。
            self.rejected += n
            raise BudgetExceeded(
                f"本轮已用 {self._used_this_rotation} 次，再加 {n} 次会超过 Q={self.q}；"
                f"按 §6.3 第 5 条须轮换新验证集"
            )
        self._used_this_rotation += n
        self.used_total += n
        self.used_by_split[split] = self.used_by_split.get(split, 0) + n

    def rotate(self) -> int:
        """强制轮换验证集。返回已经发生的轮换次数（1 表示第一次轮换）。"""
        self.rotation += 1
        self._used_this_rotation = 0
        return self.rotation

    @property
    def sealed_queries(self) -> int:
        return self.used_by_split.get("sealed", 0)

    def assert_sealed_untouched(self) -> None:
        if self.sealed_queries:
            raise SealedViolation(
                f"封存集已被查询 {self.sealed_queries} 次；报告任何封存集数字前该数必须为 0"
            )


@dataclass
class TaskRuns:
    """一个任务在若干次独立运行上的判定结果。"""

    task_id: str
    family: str
    split: str
    verdicts: list[bool]

    @property
    def pass_rate(self) -> float:
        if not self.verdicts:
            raise ValueError(f"任务 {self.task_id} 没有判定记录，不能计算通过率")
        return sum(self.verdicts) / len(self.verdicts)

    @property
    def n(self) -> int:
        return len(self.verdicts)


def run_repeated(agent, task, repeats: int, seeds: Sequence[int], out_dir=None) -> TaskRuns:
    """同一任务跑多次独立运行。多次运行是配对比较能给出不确定性的前提。"""
    verdicts = []
    for i, seed in enumerate(seeds[:repeats]):
        trace = agent.run_episode(task, seed=seed, out_dir=out_dir)
        verdicts.append(bool(trace.verdict))
    return TaskRuns(
        task_id=task.task_id, family=task.family, split=task.split, verdicts=verdicts
    )


def _index_runs(runs: Iterable[TaskRuns], arm: str) -> dict[str, TaskRuns]:
    indexed = {}
    for run in runs:
        if run.task_id in indexed:
            raise ValueError(f"{arm} 臂存在重复 task_id：{run.task_id}")
        if not run.verdicts:
            raise ValueError(f"{arm} 臂任务 {run.task_id} 没有判定记录")
        if any(value not in (False, True) for value in run.verdicts):
            raise ValueError(f"{arm} 臂任务 {run.task_id} 的判定须为二元值")
        indexed[run.task_id] = run
    return indexed


def pair_up(a: Iterable[TaskRuns], b: Iterable[TaskRuns]) -> list[tuple[TaskRuns, TaskRuns]]:
    """校验任务记录，双向报告缺项，按 A 臂原顺序返回共同题目。"""
    amap = _index_runs(a, "A")
    bmap = _index_runs(b, "B")
    missing_a = sorted(bmap.keys() - amap.keys())
    missing_b = sorted(amap.keys() - bmap.keys())
    if missing_a:
        print(f"WARNING: 以下题在 A 臂中缺失，已排除出配对比较：{missing_a}")
    if missing_b:
        print(f"WARNING: 以下题在 B 臂中缺失，已排除出配对比较：{missing_b}")
    pairs = []
    for task_id, run_a in amap.items():
        if task_id not in bmap:
            continue
        run_b = bmap[task_id]
        if (run_a.family, run_a.split) != (run_b.family, run_b.split):
            raise ValueError(f"任务 {task_id} 的任务族或划分在两臂中不一致")
        pairs.append((run_a, run_b))
    return pairs


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _resample_diff(pairs, unit: str, rng: random.Random) -> float:
    if unit == "family":
        fams: dict[str, list[tuple[TaskRuns, TaskRuns]]] = {}
        for p in pairs:
            fams.setdefault(p[0].family, []).append(p)
        keys = list(fams)
        pick = [rng.choice(keys) for _ in keys]
        sample = [p for k in pick for p in fams[k]]
    else:
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
    return _mean([a.pass_rate - b.pass_rate for a, b in sample])


def paired_diff(
    a: Iterable[TaskRuns],
    b: Iterable[TaskRuns],
    unit: str = "task",
    mde: float = DEFAULT_MDE,
    n_boot: int = 10000,
    seed: int = 0,
    label: str = "A-B",
) -> dict:
    """配对比较：通过率差、95% 自助区间及历史派生判据字段。

    degraded 保留旧的 P1 派生规则：区间下界不大于零，或差值绝对值小于 mde。
    该字段与原因用于兼容已有分析，命题解释还需结合比较设计、效应方向与适用范围。
    """
    if unit not in {"task", "family"}:
        raise ValueError(f"重采样单位必须是 task 或 family，收到 {unit}")
    if n_boot <= 0:
        raise ValueError("自助次数 n_boot 须为正整数")

    pairs = pair_up(a, b)
    if not pairs:
        raise ValueError("没有可配对的题，比较无法进行")

    diffs = [x.pass_rate - y.pass_rate for x, y in pairs]
    point = _mean(diffs)

    rng = random.Random(seed)
    boot = sorted(_resample_diff(pairs, unit, rng) for _ in range(n_boot))
    lo = boot[int(0.025 * n_boot)]
    hi = boot[min(int(0.975 * n_boot), n_boot - 1)]

    reasons = []
    if lo <= 0:
        reasons.append(f"95% 区间下界 {lo:+.4f} ≤ 0")
    if abs(point) < mde:
        reasons.append(f"点估计 {point:+.4f} 小于预注册 MDE {mde}")
    degraded = bool(reasons)

    return {
        "label": label,
        "unit": unit,
        "n_pairs": len(pairs),
        "n_runs_min": min(min(x.n, y.n) for x, y in pairs),
        "point": point,
        "ci95_low": lo,
        "ci95_high": hi,
        "mde": mde,
        "degraded": degraded,
        "reason": "；".join(reasons) if reasons else "区间下界 > 0 且点估计达到 MDE",
    }


def by_family(a: Iterable[TaskRuns], b: Iterable[TaskRuns]) -> dict[str, dict]:
    """按任务族分列报告（§6.3 第 7 条：避免一个总分遮蔽局部退化）。"""
    pairs = pair_up(a, b)
    fams: dict[str, list[tuple[TaskRuns, TaskRuns]]] = {}
    for x, y in pairs:
        fams.setdefault(x.family, []).append((x, y))
    return {
        fam: {
            "n_pairs": len(ps),
            "point": _mean([x.pass_rate - y.pass_rate for x, y in ps]),
        }
        for fam, ps in sorted(fams.items())
    }


# --------------------------------------------------------------------- selftest


def _syn(family: str, n: int, wins: int, runs: int = 3) -> list[TaskRuns]:
    """合成数据：前 wins 题全通过，其余全失败。与任何方法的能力无关。"""
    out = []
    for i in range(n):
        v = [True] * runs if i < wins else [False] * runs
        out.append(TaskRuns(f"{family}-{i:02d}", family, "train", v))
    return out


def selftest() -> int:
    ok = True

    # 1. 全胜：点估计 1.0，区间应收缩到 1.0 附近，不降级
    r = paired_diff(_syn("f", 16, 16), _syn("f", 16, 0), label="all-win")
    ok &= r["point"] == 1.0 and not r["degraded"] and r["ci95_low"] > 0

    # 2. 全负：点估计 -1.0，区间下界 ≤ 0 → 降级
    r = paired_diff(_syn("f", 16, 0), _syn("f", 16, 16), label="all-lose")
    ok &= r["point"] == -1.0 and r["degraded"] and r["ci95_low"] <= 0

    # 3. 无差异：点估计 0，两种触发条件都应命中
    r = paired_diff(_syn("f", 16, 8), _syn("f", 16, 8), label="tie")
    ok &= r["point"] == 0.0 and r["degraded"]

    # 4. 刚好差 1/16 = 6.25 个百分点：达到 MDE，区间下界仍可能 ≤ 0 → 应降级
    r = paired_diff(_syn("f", 16, 9), _syn("f", 16, 8), label="one-task-gap")
    ok &= abs(r["point"] - 1 / 16) < 1e-9 and r["degraded"] and r["ci95_low"] <= 0

    # 5. 重采样单位可切换；此构造的族级区间不窄于题级区间。
    a = _syn("f1", 8, 6) + _syn("f2", 8, 2)
    b = _syn("f1", 8, 2) + _syn("f2", 8, 6)
    rt = paired_diff(a, b, unit="task", label="unit-task")
    rf = paired_diff(a, b, unit="family", label="unit-family")
    ok &= rt["n_pairs"] == rf["n_pairs"] == 16
    ok &= (rf["ci95_high"] - rf["ci95_low"]) >= (rt["ci95_high"] - rt["ci95_low"])

    # 6. 预算：超 Q 抛错；轮换后额度恢复
    qb = QueryBudget(q=5)
    for _ in range(5):
        qb.spend("select-valid", "t")
    try:
        qb.spend("select-valid", "t")
        ok = False
    except BudgetExceeded:
        pass
    qb.rotate()
    qb.spend("select-valid", "t")
    ok &= qb.rotation == 1 and qb.used_total == 6 and qb.rejected == 1

    # 7. 封存集：查过之后必须抛错，没查过则通过
    qb2 = QueryBudget()
    qb2.assert_sealed_untouched()
    qb2.spend("sealed", "s")
    try:
        qb2.assert_sealed_untouched()
        ok = False
    except SealedViolation:
        pass
    ok &= qb2.sealed_queries == 1

    for name, res in (
        ("all-win", paired_diff(_syn("f", 16, 16), _syn("f", 16, 0))),
        ("one-task-gap", paired_diff(_syn("f", 16, 9), _syn("f", 16, 8))),
    ):
        print(f"{name:14s} point={res['point']:+.4f} "
              f"ci=[{res['ci95_low']:+.4f},{res['ci95_high']:+.4f}] "
              f"degraded={res['degraded']}")
    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="公共评测协议自检（不含任何实验结果）")
    ap.add_argument("--selftest", action="store_true", help="在合成数据上验证统计口径与预算纪律")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
