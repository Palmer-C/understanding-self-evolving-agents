"""E12 退化与可恢复更新的实现：退化符号、幅度分档、回滚触发（协议：`experiments/protocols/E12.md`）。

本文件只实现**机制与可在本地验证的判据**，不含任何实验结果，也不含任何数字结论。

唯一的符号口径（协议 §1，与 `spec/propositions.md` 一致，2026-09-28 审计已修掉旧表的反向写法）：

$$
D = \\text{旧版本得分} - \\text{新版本得分}, \\qquad D > 0 \\text{ 表示退化}
$$

协议里能被本地验证的部分全部集中在 `--selftest`（§10）。自检**不调用任何模型**。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

ARMS = ("control_no_update", "small", "medium", "large", "corrupt")

# 协议 §3：三档幅度按**运行前可数的量**定义，不按结果切。
SMALL_ITEMS = 1
MEDIUM_ITEMS = 3

# 协议 §4：回滚触发线，运行前写死。
DEFAULT_D_CRIT = 0.10


# --------------------------------------------------------------------- 退化量


def regression_score(verdicts: list[bool]) -> float:
    """回归集得分 = 题均通过率。空集返回 NaN——返回 0 会把"没数据"伪装成"全失败"。"""
    if not verdicts:
        return float("nan")
    return sum(1 for v in verdicts if v) / len(verdicts)


def degradation(before: list[bool], after: list[bool]) -> float:
    """$D = \\text{旧} - \\text{新}$。$D>0$ 是退化，$D<0$ 是改善。"""
    return regression_score(before) - regression_score(after)


def noise_floor(control_before: list[list[bool]], control_after: list[list[bool]]) -> float:
    """噪声底线：`control_no_update` 臂上，同一版本跑两遍所得 $D$ 的标准差（协议 §2）。

    底线是**测出来的**，不是常数。用常数当底线等于替数据做了"多大算退化"的决定。
    """
    ds = [degradation(a, b) for a, b in zip(control_before, control_after) if a and b]
    if not ds:
        return float("nan")
    return statistics.pstdev(ds) if len(ds) > 1 else 0.0


def is_regression(d: float, floor: float, d_crit: float = DEFAULT_D_CRIT) -> bool:
    """是否判定为退化：同时要求超过触发线 $d_{\\text{crit}}$ 与噪声底线。

    只看触发线会把抖动判成退化；只看底线会让"明显但略超底线"的退化被放过。
    """
    if d != d:  # NaN：没有数据，不能判
        return False
    return (d >= d_crit) and (d > max(floor, 0.0))


# --------------------------------------------------------------------- 幅度分档


@dataclass
class UpdateSize:
    """一次更新对持久物的实际改动量（协议 §3 的事后复核量）。"""

    items_added: int = 0
    items_rewritten: int = 0
    bytes_delta: int = 0

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def classify_size(size: UpdateSize) -> str:
    """按**可观测的改动量**分档，不读模型的自我报告（协议 §3）。

    `large` 的判据是"对既有条目做过重写"，而不是"字节变更多"——
    字节数能被格式差异（换行、转义）拉动，重写与否才是幅度本身。
    """
    if size.items_rewritten > 0:
        return "large"
    if size.items_added >= MEDIUM_ITEMS:
        return "medium"
    if size.items_added >= SMALL_ITEMS:
        return "small"
    return "control_no_update"


# --------------------------------------------------------------------- 回滚


@dataclass
class Snapshot:
    """持久物快照：回滚时用它恢复（协议 §4）。"""

    items: tuple[str, ...] = ()

    @classmethod
    def of(cls, items: list[str]) -> "Snapshot":
        return cls(tuple(items))

    def restore(self) -> list[str]:
        return list(self.items)


def rollback(current: list[str], snapshot: Snapshot) -> list[str]:
    """丢弃当前更新、回到快照。返回恢复后的持久物。"""
    return snapshot.restore()


# --------------------------------------------------------------------- selftest


def selftest() -> int:
    ok = True

    # 1. 符号约定：变差 → D>0；变好 → D<0；无变化 → D=0
    old = [True, True, True, True]
    worse = [True, True, False, False]
    ok &= degradation(old, worse) == 0.5
    ok &= degradation(worse, old) == -0.5
    ok &= degradation(old, old) == 0.0

    # 2. 噪声底线由 control 臂测出，不是常数
    ctrl_a = [[True, True, True, True], [True, False, True, True]]
    ctrl_b = [[True, True, True, True], [False, False, True, True]]
    floor = noise_floor(ctrl_a, ctrl_b)
    ok &= floor >= 0 and floor == floor  # 非 NaN
    ok &= noise_floor([], []) != noise_floor([], [])  # 空输入 → NaN，不能当 0 用

    # 3. 触发线 + 底线共同决定，且 NaN 不能判成退化
    ok &= is_regression(0.25, floor)
    ok &= not is_regression(0.01, floor)  # 未达触发线
    ok &= not is_regression(float("nan"), floor)  # 没数据不能判

    # 4. 幅度分档看可观测量，不看字节数
    ok &= classify_size(UpdateSize(items_added=1, bytes_delta=10)) == "small"
    ok &= classify_size(UpdateSize(items_added=3, bytes_delta=10)) == "medium"
    ok &= classify_size(UpdateSize(items_added=1, items_rewritten=1, bytes_delta=10)) == "large"
    ok &= classify_size(UpdateSize(items_added=1, bytes_delta=10_000)) == "small"

    # 5. 回滚：回到快照，恢复后的内容等于更新前
    before_items = ["经验 A", "经验 B"]
    snap = Snapshot.of(before_items)
    after_items = before_items + ["错误的经验 C"]
    ok &= rollback(after_items, snap) == before_items
    ok &= rollback(after_items, snap) != after_items

    # 6. 得分口径：空集是 NaN 而不是 0
    ok &= regression_score([]) != regression_score([])

    print(f"degradation={{+{degradation(old, worse):.2f}}} floor={floor:.4f} "
          f"size_large={classify_size(UpdateSize(1, 1, 1))}")
    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
