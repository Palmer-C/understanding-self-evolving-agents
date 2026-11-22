"""E11 三个更新时机臂的实现：写入调度、预算匹配与漂移段划分（协议：`experiments/protocols/E11.md`）。

本文件只实现**机制与可在本地验证的判据**，不含任何实验结果，也不含任何数字结论。
三个臂（协议 §3）共用同一个写入预算 $W$——**预算匹配优先于效果比较**，
因为 P5 说的是单位资源收益，而不是"谁最终更强"。

信号本身不在本文件重算，直接复用 `trigger_signals.py`（`error_runs` / `drift` / `novelty_series`），
以保证第 13 章 §13.2 已报告的信号值与本协议用的是同一份定义。

协议里能被本地验证的部分全部集中在 `--selftest`（§10）。
自检**不调用任何模型**，与任何方法的能力无关。
"""

from __future__ import annotations

from dataclasses import dataclass

from .trigger_signals import drift as drift_signal
from .trigger_signals import error_runs, novelty_series

ARMS = ("per_task", "periodic", "event")


# --------------------------------------------------------------------- 写入调度


@dataclass
class WriteSchedule:
    """一条序列上的写入调度结果。

    `writes` 是被放行的写入下标（episode 序号，从 0 开始）；
    `over_budget` 是被预算拒掉的写请求次数——协议 §4 要求它单独计数，
    静默丢弃会让"撞过几次上限"这件事在账上完全看不出来。
    """

    writes: list[int] = None  # type: ignore[assignment]
    over_budget: int = 0
    signal_calls: int = 0

    def __post_init__(self) -> None:
        if self.writes is None:
            self.writes = []

    def as_dict(self) -> dict:
        return {
            "writes": list(self.writes),
            "over_budget": self.over_budget,
            "signal_calls": self.signal_calls,
        }


def schedule(arm: str, n_episodes: int, w_budget: int = 4,
             period: int = 3, signals: list[float] | None = None,
             threshold: float = 0.5) -> WriteSchedule:
    """按臂名排出一条序列上的写入时机，并强制预算 $W$。

    - `per_task`：每个 episode 都请求写入 → 长序列上必然先撞预算，这是它的代价本身；
    - `periodic`：每 `period` 个 episode 请求一次；
    - `event`：`signals[i] >= threshold` 时请求一次；缺 `signals` 时不写入，
      而不是退化为 `per_task`——退化会让"无信号"看起来和"每次都写"一样。
    """
    if arm not in ARMS:
        raise ValueError(f"未知臂名：{arm}")
    out = WriteSchedule()
    for i in range(n_episodes):
        if arm == "per_task":
            want = True
        elif arm == "periodic":
            want = (i % max(1, period) == 0)
        else:
            if signals is None:
                out.signal_calls = 0
                break
            out.signal_calls += 1
            want = signals[i] >= threshold
        if not want:
            continue
        if len(out.writes) >= w_budget:
            out.over_budget += 1
            continue
        out.writes.append(i)
    return out


def signals_for(verdicts: list[bool], lesson_texts: list[str] | None = None,
                window: int = 4) -> list[float]:
    """把三个信号逐位取最大值，压成一条可判的标量序列。

    协议 §4：`error_run` / `drift` / `novelty` 都不调用模型，因此这里 `signal_calls` 计入
    也不产生真实 token——但调用次数仍然入账，因为换成模型实现时这个数必须变成真实消耗。
    """
    er = error_runs(verdicts)
    dr = drift_signal(verdicts, window=window)
    nv = novelty_series(lesson_texts or [""] * len(verdicts))
    return [float(max(a, b, c)) for a, b, c in zip(er, dr, nv)]


# --------------------------------------------------------------------- 漂移段


def split_sequence(n: int) -> tuple[list[int], list[int]]:
    """把一条长度为 $n$ 的序列按中点切成漂移前 / 漂移后两段（协议 §5）。

    中点之后**全部**换族：不许半途穿插，穿插会让"漂移是否发生"变成一个连续量而不是一个指示量。
    """
    mid = n // 2
    return list(range(mid)), list(range(mid, n))


def segment_failure_rate(verdicts: list[bool], idx: list[int]) -> float:
    """一段内的累计失败率（越低越好）。空段返回 NaN 由调用方处理——补 0 会把"没数据"伪装成"全通过"。"""
    if not idx:
        return float("nan")
    return 1.0 - (sum(1 for i in idx if verdicts[i]) / len(idx))


def delta_widening(base: list[bool], arm: list[bool]) -> float:
    """漂移前后"该臂相对基线的优势"变化（协议 §5）：

    $\\Delta = (L^{\\text{base}}_{\\text{after}} - L^{\\text{arm}}_{\\text{after}})
             - (L^{\\text{base}}_{\\text{before}} - L^{\\text{arm}}_{\\text{before}})$

    其中 $L$ 是**失败率**，越低越好，所以"优势"写成"基线减该臂"。
    符号约定因此是：$\\Delta > 0$ = 漂移之后该臂相对基线更好（差距扩大）；
    $\\Delta < 0$ = 差距缩小或反向。写成 $L^{\\text{arm}} - L^{\\text{base}}$ 会把符号反过来，
    这一点必须在结果里写明，不能靠读者自己推。
    """
    before, after = split_sequence(len(base))
    adv_after = segment_failure_rate(base, after) - segment_failure_rate(arm, after)
    adv_before = segment_failure_rate(base, before) - segment_failure_rate(arm, before)
    return adv_after - adv_before


# --------------------------------------------------------------------- selftest


def selftest() -> int:
    ok = True

    # 1. 三个信号在已知序列上的取向
    v = [True, True, False, False, False, True]
    ers = error_runs(v)
    ok &= ers[-1] == 0 and ers[4] == 3  # 末尾连续失败 3 次后在第 5 位被通过打散
    dr = drift_signal(v, window=2)
    ok &= len(dr) == len(v)
    nv = novelty_series(["同一条经验", "同一条经验", "完全不同的内容"])
    ok &= nv[-1] > nv[1]  # 重复写入 → 新颖性低；换内容 → 新颖性高

    # 2. 预算匹配：三臂都不超过 W，超限记 over_budget 而不是静默截断
    W = 4
    per = schedule("per_task", n_episodes=10, w_budget=W)
    ok &= len(per.writes) == W and per.over_budget == 6
    pod = schedule("periodic", n_episodes=10, w_budget=W, period=3)
    ok &= pod.writes == [0, 3, 6, 9] and pod.over_budget == 0
    long_per = schedule("per_task", n_episodes=12, w_budget=W, period=3)
    ok &= len(long_per.writes) == W and long_per.over_budget == 8

    # 3. event 臂：没给 signals 时不写入（而不是退化成 per_task）
    ev_none = schedule("event", n_episodes=10, w_budget=W)
    ok &= ev_none.writes == [] and ev_none.over_budget == 0
    sig = [0.0, 0.0, 0.0, 0.9, 0.0, 0.0, 0.0, 0.8, 0.0, 0.0]
    ev = schedule("event", n_episodes=10, w_budget=W, signals=sig, threshold=0.5)
    ok &= ev.writes == [3, 7] and ev.signal_calls == 10

    # 4. 漂移段：中点之后全部换段，两段并起来还是原序列
    before, after = split_sequence(8)
    ok &= before == [0, 1, 2, 3] and after == [4, 5, 6, 7]
    ok &= sorted(before + after) == list(range(8))

    # 5. 合成序列上 Δ 的符号方向：漂移后半段变好 → Δ > 0
    base = [True, True, False, False, False, False, False, False]  # 后半段基线全败
    good = [True, True, True, True, True, True, True, True]        # 该臂后半段全通过
    ok &= delta_widening(base, good) > 0
    ok &= abs(delta_widening([True] * 8, [True] * 8)) < 1e-9        # 无差别 → Δ = 0

    print(f"per_task_writes={len(per.writes)} over_budget={per.over_budget} "
          f"event_writes={ev.writes} widening={delta_widening(base, good):+.4f}")
    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
