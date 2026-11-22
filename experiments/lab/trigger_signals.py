"""更新时机的三个可计算触发信号（第 13 章 13.2 的落点）。

协议背景：`spec/outline-v0.4.md` §13.2 要求"错误集中、分布漂移与经验新颖性"三个信号可计算。
本文件把它们算在**已有运行的真实轨迹**上，因此它不产生新的能力证据，
只回答一件事：在一次真实的训练过程里，这三个信号各自长什么样、按阈值门控会省掉多少写入。

用法：
    python experiments/lab/trigger_signals.py --run E01-20260923T152230Z-90acda

三个信号的定义（都只用运行期就能拿到的量，不需要未来信息）：

1. **错误集中** ``error_run``：截至当前、末尾连续失败的次数。
   它衡量"这次失败是不是孤立的"；孤立失败通常不值得触发一次持久更新。
2. **分布漂移** ``drift``：最近 $w$ 个 episode 的失败率与此前 $w$ 个的差的绝对值。
   它衡量"失败是不是突然变多的"，用于区分"一直做不好"与"刚刚开始变差"。
3. **经验新颖性** ``novelty``：本次要写入的经验与已有经验的最大字符二元组 Jaccard 相似度，
   取 $1-$ 相似度作为新颖性。它衡量"这条经验是不是已经在记忆里了"。

本文件不判断"该不该触发"——那是各章协议的事。它只给信号值与门控后的写入量。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.lab.e01_arms import _bigrams  # noqa: E402

RUNS_ROOT = REPO_ROOT / "experiments" / "runs"
RESULTS_ROOT = REPO_ROOT / "experiments" / "results"


def jaccard(a: str, b: str) -> float:
    """字符二元组 Jaccard 相似度；两段空文本视为完全相似（无可比内容）。"""
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def load_train_episodes(run_dir: Path, arm: str) -> list[dict]:
    """按目录名里的序号顺序读一个臂的训练期轨迹。"""
    root = run_dir / "traces" / arm / "train"
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir(), key=lambda p: p.name):
        tf = d / "trace.json"
        if not tf.is_file():
            continue
        trace = json.loads(tf.read_text(encoding="utf-8"))
        out.append({
            "dir": d.name,
            "task_id": trace.get("task_id", ""),
            "verdict": bool(trace.get("verdict")),
            "calls": int((trace.get("usage") or {}).get("calls", 0)),
            "wall": float((trace.get("usage") or {}).get("wall_seconds", 0.0)),
        })
    return out


def error_runs(verdicts: list[bool]) -> list[int]:
    """末尾连续失败次数：第 i 个 episode 写入时，往前数连续多少个失败。"""
    out, run = [], 0
    for ok in verdicts:
        run = 0 if ok else run + 1
        out.append(run)
    return out


def drift(verdicts: list[bool], window: int = 4) -> list[float]:
    """最近窗口与前一个窗口的失败率之差的绝对值；前面不足两个窗口时给 0。"""
    out = []
    for i in range(len(verdicts)):
        if i + 1 < 2 * window:
            out.append(0.0)
            continue
        cur = verdicts[i + 1 - window:i + 1]
        prev = verdicts[i + 1 - 2 * window:i + 1 - window]
        fr = lambda xs: sum(1 for x in xs if not x) / len(xs)  # noqa: E731
        out.append(abs(fr(cur) - fr(prev)))
    return out


def novelty_series(texts: list[str]) -> list[float]:
    """逐条算新颖性：与**此前**已有经验的最大相似度，取 1 减它。

    刻意只与过去的经验比——与未来的比会用到运行期拿不到的信息。
    """
    out = []
    seen: list[str] = []
    for t in texts:
        if not seen:
            out.append(1.0)
        else:
            out.append(1.0 - max(jaccard(t, s) for s in seen))
        seen.append(t)
    return out


def quantile(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    ys = sorted(xs)
    i = min(len(ys) - 1, max(0, int(round(q * (len(ys) - 1)))))
    return ys[i]


def analyze(run_dir: Path, arm: str, lessons: list[str]) -> dict:
    eps = load_train_episodes(run_dir, arm)
    if not eps:
        return {"arm": arm, "n_episodes": 0}
    verdicts = [e["verdict"] for e in eps]
    er = error_runs(verdicts)
    dr = drift(verdicts)
    texts = lessons[: len(eps)]
    if len(texts) < len(eps):  # 经验不足时用任务号占位，保证信号序列等长
        texts = texts + [e["task_id"] for e in eps[len(texts):]]
    nv = novelty_series(texts)

    # 门控：只有"连续失败 >= 2"或"新颖性 >= 0.5"时才写入
    gate = [(e >= 2) or (n >= 0.5) for e, n in zip(er, nv)]
    n_writes = len(eps)
    n_kept = sum(gate)

    return {
        "arm": arm,
        "n_episodes": n_writes,
        "fail_rate": round(sum(1 for v in verdicts if not v) / n_writes, 4),
        "error_run": {
            "max": max(er),
            "mean": round(sum(er) / len(er), 4),
            "p50": quantile([float(x) for x in er], 0.5),
            "n_ge2": sum(1 for x in er if x >= 2),
        },
        "drift": {
            "max": round(max(dr), 4),
            "mean": round(sum(dr) / len(dr), 4),
            "n_ge_half": sum(1 for x in dr if x >= 0.5),
        },
        "novelty": {
            "min": round(min(nv), 4),
            "mean": round(sum(nv) / len(nv), 4),
            "p50": round(quantile(nv, 0.5), 4),
            "n_below_half": sum(1 for x in nv if x < 0.5),
        },
        "gating": {
            "rule": "error_run >= 2 或 novelty >= 0.5 才写入",
            "n_writes_total": n_writes,
            "n_writes_kept": n_kept,
            "saved_fraction": round(1 - n_kept / n_writes, 4),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="更新时机的三个触发信号")
    ap.add_argument("--run", required=True, help="运行目录名，例如 E01-20260923T152230Z-90acda")
    ap.add_argument("--arms", default="", help="逗号分隔的臂名；默认读 summary.json 里的全部臂")
    args = ap.parse_args(argv)

    run_dir = RUNS_ROOT / args.run
    if not run_dir.is_dir():
        print(f"ERROR: 找不到运行目录 {run_dir}")
        return 2
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))

    # 记忆文本：优先取各臂自己的写入；E01 的格 4 在 summary["memory"]["grid4_lessons"]
    lessons_by_arm: dict[str, list[str]] = {}
    mem = summary.get("memory") or {}
    if "grid4_lessons" in mem:
        lessons_by_arm["grid4"] = [x["text"] for x in mem["grid4_lessons"]]
    for arm, items in mem.items():
        if arm.endswith("_lessons"):
            lessons_by_arm[arm.replace("_lessons", "")] = [x["text"] for x in items]

    arms = [a for a in args.arms.split(",") if a] or sorted(lessons_by_arm) or ["grid4"]
    out = {
        "run_id": args.run,
        "protocol": "spec/outline-v0.4.md §13.2（三个可计算触发信号）",
        "signals": [analyze(run_dir, a, lessons_by_arm.get(a, [])) for a in arms],
    }
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    stem = f"triggers-{args.run}"
    (RESULTS_ROOT / f"{stem}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (RESULTS_ROOT / f"{stem}.md").write_text(render_md(out), encoding="utf-8")
    print(render_md(out))
    return 0


def render_md(o: dict) -> str:
    lines = [
        f"# 更新时机的三个触发信号 · 运行 {o['run_id']}",
        "",
        f"> 协议：`{o['protocol']}`。原始记录：`experiments/runs/{o['run_id']}/`。",
        "> 本表由 `experiments/lab/trigger_signals.py` 生成；数字来自该运行的真实轨迹，不含人工填写。",
        "> 本表**不判断该不该触发**，只报信号值与门控后的写入量。",
        "",
        "| 臂 | 训练 episode 数 | 失败率 | 错误集中（最大 / 均值） | 漂移（最大 / 均值） | 新颖性（最小 / 均值） | 门控后保留写入 | 省下比例 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in o["signals"]:
        if s.get("n_episodes", 0) == 0:
            lines.append(f"| {s['arm']} | 0 | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {s['arm']} | {s['n_episodes']} | {s['fail_rate']:.4f} | "
            f"{s['error_run']['max']} / {s['error_run']['mean']:.4f} | "
            f"{s['drift']['max']:.4f} / {s['drift']['mean']:.4f} | "
            f"{s['novelty']['min']:.4f} / {s['novelty']['mean']:.4f} | "
            f"{s['gating']['n_writes_kept']}/{s['gating']['n_writes_total']} | "
            f"{s['gating']['saved_fraction']:.4f} |"
        )
    lines += [
        "",
        "信号口径：",
        "",
        "- 错误集中 = 写入时往前数末尾连续失败的次数。",
        "- 漂移 = 最近 4 个 episode 的失败率与前 4 个的差的绝对值；不足两个窗口记 0。",
        "- 新颖性 = 1 减去本次经验与此前已有经验的最大字符二元组 Jaccard 相似度。",
        "- 门控规则（示例，非协议）：错误集中 ≥ 2 或 新颖性 ≥ 0.5 才写入。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
