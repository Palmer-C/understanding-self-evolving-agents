"""实验成本核算：把已完成的运行账目聚合成人读表。

用途：附录 F（实验成本核算）的所有实测数字由本脚本产出，不手工抄写。

用法：
    python experiments/lab/cost_report.py                 # 打印全部已完成运行
    python experiments/lab/cost_report.py --json          # 落盘 analysis/cost-ledger-reproduction.json

口径说明（写进附录 F）：
- E01/E02 的 ledger 调用与 token 合计已含 side_* 分项，不再相加；E03 臂账覆盖评价回合，来源与渲染另行核查。
- 后端不返回价格，usd 一律为 null；本表只报实物量：调用次数 / 提示 token / 生成 token / 墙钟秒。
- 墙钟秒包含网络等待，因此它是"本机本时段"的量，不是可移植的机器成本。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.path.join(ROOT, "experiments", "results")
sys.path.insert(0, ROOT)
from experiments.lab.archive_inputs import required_summaries

# 已完成的运行：run_id -> (实验名, 结果文件名, 是否已判决/是否为试跑)
RUNS = [
    ("E01", "E01-20260923T152230Z-90acda", "正式试验运行（四格）"),
    ("E02", "E02-20260924T153511Z-421eac", "正式运行（验证层级六臂）"),
    ("E03", "E03-20260925T152453Z-254845", "十臂历史汇总；A/base_same判定与成本记录冲突，暂停效应及效率解释"),
]


def aggregate(d: dict) -> dict:
    """按臂聚合账目；兼容 ledger 为 {arm: {...}} 与 {split: {arm: {...}}} 两种形状。"""
    out = {}
    ledger = d["ledger"]
    if not ledger:
        raise ValueError('Required ledger is empty')
    for key, val in ledger.items():
        if not isinstance(val, dict):
            continue
        if all(isinstance(v, dict) for v in val.values()) and val:
            for arm, row in val.items():  # 两级：split -> arm
                out[f"{key}/{arm}"] = row
        else:
            out[key] = val
    return out


def row_total(row: dict) -> dict:
    required=("episodes", "calls", "prompt_tokens", "completion_tokens", "wall_seconds")
    missing=[k for k in required if k not in row]
    if missing:
        raise ValueError(f'Required cost fields missing: {missing}')
    return {
        "episodes": int(row.get("episodes", 0)),
        "calls": int(row.get("calls", 0)),
        "prompt_tokens": int(row.get("prompt_tokens", 0)),
        "completion_tokens": int(row.get("completion_tokens", 0)),
        "wall_seconds": float(row.get("wall_seconds", 0.0)),
        "side_calls": int(row.get("side_calls", 0)),
        "side_prompt_tokens": int(row.get("side_prompt_tokens", 0)),
        "side_completion_tokens": int(row.get("side_completion_tokens", 0)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="落盘 analysis/cost-ledger-reproduction.json，不覆盖历史账")
    ap.add_argument("--root",type=Path,default=Path(ROOT))
    args = ap.parse_args()

    data=required_summaries(args.root)
    # Fail before any output if a ledger is incomplete.
    prepared={run:{k:row_total(v) for k,v in aggregate(d).items()} for run,d in data.items()}
    if any(not arms for arms in prepared.values()):
        raise ValueError('A required run has no usable ledger arms')
    print('历史汇总复算：不是校正后的有效记录集或完整生命周期成本。')
    print('E03 A/base_same与保存轨迹冲突；基线收益及成本效率解释暂停。')
    report = []
    for exp, run_id, note in RUNS:
        d = data[run_id]
        arms = prepared[run_id]
        total = {
            "episodes": sum(a["episodes"] for a in arms.values()),
            "calls": sum(a["calls"] for a in arms.values()),
            "prompt_tokens": sum(a["prompt_tokens"] for a in arms.values()),
            "completion_tokens": sum(a["completion_tokens"] for a in arms.values()),
            "wall_seconds": sum(a["wall_seconds"] for a in arms.values()),
            "side_calls": sum(a["side_calls"] for a in arms.values()),
            "side_prompt_tokens": sum(a["side_prompt_tokens"] for a in arms.values()),
            "side_completion_tokens": sum(a["side_completion_tokens"] for a in arms.values()),
        }
        entry = {
            "experiment": exp,
            "run_id": run_id,
            "note": note,
            "model": d.get("config", {}).get("model") or d.get("config", {}).get("model_same"),
            "model_cross": d.get("config", {}).get("model_cross"),
            "git_head": d.get("config", {}).get("git_head"),
            "wall_seconds_total": d.get("wall_seconds_total"),
            "arms": arms,
            "total": total,
            "pending_arms": d.get("pending_arms"),
            "pending_reason": d.get("pending_reason"),
        }
        report.append(entry)

        print(f"== {exp} {run_id}  ({note})")
        print(f"   model={entry['model']} cross={entry['model_cross']} git_head={entry['git_head']}")
        print(f"   {'臂':<26}{'episodes':>9}{'calls':>8}{'prompt':>10}{'compl':>9}{'wall_s':>10}")
        for arm, a in arms.items():
            print(f"   {arm:<26}{a['episodes']:>9}{a['calls']:>8}{a['prompt_tokens']:>10}"
                  f"{a['completion_tokens']:>9}{a['wall_seconds']:>10.1f}")
        print(f"   {'合计':<26}{total['episodes']:>9}{total['calls']:>8}{total['prompt_tokens']:>10}"
              f"{total['completion_tokens']:>9}{total['wall_seconds']:>10.1f}")
        if entry["pending_arms"]:
            print(f"   待补臂={entry['pending_arms']} 原因={entry['pending_reason']}")
        ep = max(total["episodes"], 1)
        derived = {
            "calls_per_episode": total["calls"] / ep,
            "prompt_tokens_per_episode": total["prompt_tokens"] / ep,
            "completion_tokens_per_episode": total["completion_tokens"] / ep,
            "wall_seconds_per_episode": total["wall_seconds"] / ep,
            "side_share_of_calls": (total["side_calls"] / total["calls"]
                                    if total["calls"] else 0.0),
        }
        print("   每 episode 均值: calls=%.2f prompt=%.0f completion=%.0f wall=%.2fs, 副账调用占比=%.3f"
              % (derived["calls_per_episode"], derived["prompt_tokens_per_episode"],
                 derived["completion_tokens_per_episode"], derived["wall_seconds_per_episode"],
                 derived["side_share_of_calls"]))
        entry["derived"] = derived
        print()

    grand = {
        "episodes": sum(e["total"]["episodes"] for e in report),
        "calls": sum(e["total"]["calls"] for e in report),
        "prompt_tokens": sum(e["total"]["prompt_tokens"] for e in report),
        "completion_tokens": sum(e["total"]["completion_tokens"] for e in report),
        "wall_seconds": sum(e["total"]["wall_seconds"] for e in report),
    }
    print(f"== {len(report)}次已列明运行的历史汇总合计")
    print("   episodes=%d calls=%d prompt_tokens=%d completion_tokens=%d wall_seconds=%.1f"
          % (grand["episodes"], grand["calls"], grand["prompt_tokens"],
             grand["completion_tokens"], grand["wall_seconds"]))
    print("   总 token=%d（提示 %.1f%% / 生成 %.1f%%）"
          % (grand["prompt_tokens"] + grand["completion_tokens"],
             100.0 * grand["prompt_tokens"] / max(grand["prompt_tokens"] + grand["completion_tokens"], 1),
             100.0 * grand["completion_tokens"] / max(grand["prompt_tokens"] + grand["completion_tokens"], 1)))
    print()

    if args.json:
        out = args.root / "analysis" / "cost-ledger-reproduction.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({'identity':'historical_summary_reproduction_not_corrected_effective_cost',
                       'input_manifest':'analysis/inputs.json',
                       'E03_A_base_same':'unresolved verdict and usage conflict; suspend baseline-relative efficiency',
                       'runs':report,'grand_total':grand}, fh, ensure_ascii=False, indent=2)
        print(f"[ok] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
