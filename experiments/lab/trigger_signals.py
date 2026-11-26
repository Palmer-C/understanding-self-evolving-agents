"""按训练回合顺序复算归档判定与经验（第 13 章）。

连续失败数和相邻窗口失败率绝对差取自已保存的判定。字符二元组新颖性取自
与回合一一对应的经验文本。示例门限只用于回放这些固定记录。

python experiments/lab/trigger_signals.py --run E01-20260923T152230Z-90acda
默认打印 Markdown。加 --output-dir <新目录> 可同时保存 JSON 和 Markdown。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.lab.e01_arms import _bigrams  # noqa: E402

RUNS_ROOT = REPO_ROOT / "experiments" / "runs"
ARCHIVED_E01 = "E01-20260923T152230Z-90acda"


def jaccard(a: str, b: str) -> float:
    """字符二元组 Jaccard 相似度；两段空文本视为完全相似（无可比内容）。"""
    sa, sb = _bigrams(a), _bigrams(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def load_train_episodes(run_dir: Path, arm: str) -> list[dict]:
    """Read <task_id>-e<N> directories in numeric order, with one trace per position from zero."""
    root = run_dir / "traces" / arm / "train"
    if not root.is_dir():
        return []
    indexed = {}
    for d in root.iterdir():
        tf = d / "trace.json"
        if not d.is_dir():
            continue
        match = re.fullmatch(r"(.+)-e([0-9]+)", d.name)
        if not match:
            if tf.exists():
                raise ValueError(f"无法确定训练回合编号（应为 <task_id>-e<N>）：{d.name}")
            continue
        index = int(match[2])
        if index in indexed:
            raise ValueError(f"训练回合编号重复：{index}")
        if not tf.is_file():
            raise ValueError(f"训练回合缺少 trace.json：{d.name}")
        trace = json.loads(tf.read_text(encoding="utf-8"))
        if (not isinstance(trace, dict) or trace.get("task_id") != match[1]
                or type(trace.get("verdict")) is not bool):
            raise ValueError(f"训练轨迹的任务号或布尔判定无效：{d.name}")
        indexed[index] = {
            "dir": d.name,
            "task_id": trace["task_id"],
            "verdict": trace["verdict"],
            "calls": int((trace.get("usage") or {}).get("calls", 0)),
            "wall": float((trace.get("usage") or {}).get("wall_seconds", 0.0)),
        }
    if sorted(indexed) != list(range(len(indexed))):
        raise ValueError(f"训练回合编号应从 0 开始且连续：{arm}")
    return [indexed[i] for i in range(len(indexed))]


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


def aligned_texts(episodes: list[dict], lessons: list) -> list[str]:
    """Accept aligned archive records or an explicit ordered list of lesson texts."""
    if not isinstance(lessons, list):
        raise ValueError("经验必须以列表保存")
    if lessons and len(lessons) != len(episodes):
        raise ValueError("经验数与训练回合数不同，无法逐回合对齐")
    if any(isinstance(row, dict) for row in lessons) and not all(isinstance(row, dict) for row in lessons):
        raise ValueError("同一组经验不可混用原始记录和纯文本")
    texts = []
    for i, (episode, lesson) in enumerate(zip(episodes, lessons)):
        if isinstance(lesson, dict):
            if (type(lesson.get("index")) is not int or lesson["index"] != i
                    or lesson.get("source_task") != episode["task_id"]
                    or lesson.get("source_verdict") is not episode["verdict"]):
                raise ValueError(f"第 {i} 个经验的编号、来源任务或判定未与训练回合对齐")
            text = lesson.get("text")
        else:
            text = lesson
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"第 {i} 个经验缺少有效文本")
        texts.append(text)
    return texts


def analyze(run_dir: Path, arm: str, lessons: list) -> dict:
    episodes = load_train_episodes(run_dir, arm)
    texts = aligned_texts(episodes, lessons)
    if not episodes:
        return {"arm": arm, "n_episodes": 0}
    verdicts = [e["verdict"] for e in episodes]
    errors = error_runs(verdicts)
    shifts = drift(verdicts)
    report = {
        "arm": arm,
        "n_episodes": len(episodes),
        "fail_rate": round(sum(not v for v in verdicts) / len(episodes), 4),
        "error_run": {
            "max": max(errors), "mean": round(sum(errors) / len(errors), 4),
            "p50": quantile([float(x) for x in errors], 0.5), "n_ge2": sum(x >= 2 for x in errors),
        },
        "drift": {
            "max": round(max(shifts), 4), "mean": round(sum(shifts) / len(shifts), 4),
            "n_ge_half": sum(x >= 0.5 for x in shifts),
        },
        "novelty": None,
        "gating": None,
    }
    if texts:
        novelty = novelty_series(texts)
        n_kept = sum(e >= 2 or n >= 0.5 for e, n in zip(errors, novelty))
        report["novelty"] = {
            "min": round(min(novelty), 4), "mean": round(sum(novelty) / len(novelty), 4),
            "p50": round(quantile(novelty, 0.5), 4), "n_below_half": sum(x < 0.5 for x in novelty),
        }
        report["gating"] = {
            "rule": "error_run >= 2 或 novelty >= 0.5 才写入",
            "n_writes_total": len(texts), "n_writes_kept": n_kept,
            "saved_fraction": round(1 - n_kept / len(texts), 4),
        }
    return report


def write_reports(output_dir: Path, report: dict, markdown: str) -> None:
    """Stage both reports on the target filesystem before making the new directory visible."""
    if os.path.lexists(output_dir):
        raise FileExistsError(f"输出目录已存在：{output_dir}")
    with tempfile.TemporaryDirectory(dir=output_dir.parent, prefix=".trigger-report-") as tmp:
        stage = Path(tmp) / "reports"
        stage.mkdir()
        stem = "triggers-" + report["run_id"]
        (stage / f"{stem}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
        (stage / f"{stem}.md").write_text(markdown, encoding="utf-8")
        if os.path.lexists(output_dir):
            raise FileExistsError(f"输出目录已存在：{output_dir}")
        stage.rename(output_dir)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="从归档训练轨迹复算三个触发信号")
    ap.add_argument("--run", required=True, help="运行目录名，例如 E01-20260923T152230Z-90acda")
    ap.add_argument("--arms", default="", help="逗号分隔的训练臂名；默认选择有经验档案的训练臂")
    ap.add_argument("--output-dir", type=Path, help="将 JSON 与 Markdown 写入一个尚不存在的新目录")
    args = ap.parse_args(argv)
    if args.run in (".", "..") or not args.run or any(c in args.run for c in "/\\:"):
        ap.error("--run 应为单个运行目录名")
    run_dir = RUNS_ROOT / args.run
    try:
        summary_path = run_dir / "summary.json"
        raw = summary_path.read_bytes()
        if args.run == ARCHIVED_E01:
            manifest = json.loads((REPO_ROOT / "analysis/inputs.json").read_text(encoding="utf-8-sig"))
            try:
                expected = manifest["summaries"][ARCHIVED_E01]["sha256"]
            except (KeyError, TypeError):
                raise ValueError("analysis/inputs.json 缺少固定 E01 汇总的 SHA-256") from None
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f"固定 E01 汇总的 SHA-256 与 analysis/inputs.json 不符：{summary_path}")
        summary = json.loads(raw)
        if not isinstance(summary, dict):
            raise ValueError("运行归档应为 JSON 对象")
        memory = summary.get("memory", {})
        if not isinstance(memory, dict):
            raise ValueError("运行归档缺少可识别的 memory 对象")
        available = {d.parent.name for d in (run_dir / "traces").glob("*/train") if d.is_dir()}
        if args.run == ARCHIVED_E01 and "grid4" not in available:
            raise ValueError("固定 E01 归档缺少 traces/grid4/train 训练目录")
        lesson_groups = {}
        for name in available:
            # E01 stores '<arm>_lessons'; E02 uses '<arm>' directly.
            keys = [key for key in (name + "_lessons", name) if key in memory]
            if len(keys) == 2:
                raise ValueError(f"同一训练臂存在两组经验来源：{name}")
            if keys:
                lesson_groups[name] = memory[keys[0]]
        arms = [s.strip() for s in args.arms.split(",")] if args.arms else sorted(lesson_groups or available)
        if not arms or len(set(arms)) != len(arms) or set(arms) - available:
            raise ValueError("请指定有训练轨迹的臂；臂名须唯一")
        out = {
            "run_id": args.run, "protocol": "spec/outline-v0.4.md §13.2（三个可计算触发信号）",
            "signals": [analyze(run_dir, arm, lesson_groups.get(arm, [])) for arm in arms],
        }
        markdown = render_md(out)
        if args.output_dir is not None:
            write_reports(args.output_dir, out, markdown)
    except (OSError, ValueError) as exc:
        ap.error(str(exc))
    print(markdown)
    return 0


def render_md(o: dict) -> str:
    lines = [
        f"# 更新时机的三个触发信号 · 运行 {o['run_id']}",
        "",
        f"> 协议：`{o['protocol']}`。原始记录：`experiments/runs/{o['run_id']}/`。",
        "> 回算对象是按训练回合编号排序的归档判定和已保存经验。末两列表示示例规则会保留或过滤多少条已存经验。",
        "",
        "| 臂 | 训练回合数 | 失败率 | 错误集中（最大 / 均值） | 漂移（最大 / 均值） | 新颖性（最小 / 均值） | 回算放行条数 | 回算未放行比例 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in o["signals"]:
        if s.get("n_episodes", 0) == 0:
            lines.append(f"| {s['arm']} | 0 | — | — | — | — | — | — |")
            continue
        details = "无经验文本 | — | —"
        if s["novelty"] is not None:
            details = (f"{s['novelty']['min']:.4f} / {s['novelty']['mean']:.4f} | "
                       f"{s['gating']['n_writes_kept']}/{s['gating']['n_writes_total']} | "
                       f"{s['gating']['saved_fraction']:.4f}")
        lines.append(
            f"| {s['arm']} | {s['n_episodes']} | {s['fail_rate']:.4f} | "
            f"{s['error_run']['max']} / {s['error_run']['mean']:.4f} | "
            f"{s['drift']['max']:.4f} / {s['drift']['mean']:.4f} | "
            f"{details} |"
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
