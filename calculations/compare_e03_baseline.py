"""按题目和重复编号对照 E03 拆分 A 的归档汇总与轨迹索引。"""
import argparse
import sys
import csv
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.lab.archive_inputs import load_summary

RUN = "E03-20260925T152453Z-254845"
INDEX = "analysis/E03-record-index.csv"
INDEX_SHA = "3210a23231ad9bb2f3badc7d14ab64f8d8dc353d43e2653df58c52ad7c11d1fd"


def read_bound(root, name, expected):
    data = (root / name).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"文件字节与已核对的索引不符：{name}")
    return data.decode("utf-8-sig")


def verdict(value):
    if value not in ("True", "False"):
        raise ValueError(f"索引判定无效：{value!r}")
    return value == "True"


def compare(root):
    summary = load_summary(root, RUN)
    if summary["config"]["run_id"] != RUN:
        raise ValueError("汇总运行编号不匹配")
    tasks = summary["verdicts"]["A"]["base_same"]
    if len(tasks) != 16 or any(len(values) != 5 for values in tasks.values()):
        raise ValueError("历史基线题目或重复数不一致")
    expected = {}
    for task, values in tasks.items():
        for repeat, value in enumerate(values):
            if type(value) is not bool:
                raise ValueError("汇总判定必须为布尔值")
            expected[(task, repeat)] = value
    pairs = {}
    disagreements = []
    counts = {name: 0 for name in ("同过", "同败", "仅汇总过", "仅索引轨迹过")}
    text = read_bound(root, INDEX, INDEX_SHA)
    for row in csv.DictReader(io.StringIO(text)):
        if (row["split"], row["arm"]) != ("A", "base_same"):
            continue
        key = (row["task_id"], int(row["repeat"]))
        if key not in expected or key in pairs:
            raise ValueError("索引中存在意外或重复的题目／重复编号")
        stored = expected[key]
        indexed = verdict(row["trace"])
        if stored != verdict(row["summary"]) or stored != verdict(row["partial"]):
            raise ValueError("公开汇总与索引中的汇总／检查点栏不一致")
        if verdict(row["matches"]) != (stored == indexed):
            raise ValueError("索引的 matches 标记与分项判定不一致")
        pairs[key] = indexed
        if stored == indexed:
            counts["同过" if stored else "同败"] += 1
        else:
            counts["仅汇总过" if stored else "仅索引轨迹过"] += 1
            disagreements.append({"题目": key[0], "重复编号（从零计）": key[1],
                                  "汇总": stored, "轨迹索引": indexed})
    if pairs.keys() != expected.keys():
        raise ValueError("索引不完整")
    return {"比较次数": len(pairs), "汇总通过": sum(expected.values()),
            "轨迹索引通过": sum(pairs.values()), "逐次计数": counts,
            "分歧": disagreements, "结论": "现有公开材料无法裁定有效历史尝试。"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="含分析清单和轨迹索引的仓库根目录")
    args = parser.parse_args()
    try:
        print(json.dumps(compare(args.root), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, "核对失败：" + str(exc) + "\n")
