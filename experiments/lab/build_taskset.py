"""构建任务集 v1（W2-2）。

规格在 `taskset_spec.py`，本文件只负责三件事：

1. **算期望值**：用**正确实现**跑出每个用例的结果，落成字面量断言。
   期望值不是手写的，因此不会因为算错而写出一个"看起来对"的测试。
2. **写任务目录**：把**含缺陷的实现**写进沙箱要用的初始文件，测试文件里只有字面量。
   正确实现不进任务目录——沙箱内文件对 Agent 可读，带了参考实现任务就退化成复制。
3. **机器校验**：含缺陷版本必须至少失败一条断言，正确版本必须通过全部断言。
   任一条不满足就整体失败，不产出半成品任务集。

用法：
    python experiments/lab/build_taskset.py                 # 构建并校验仓库自带的可信规格
    python experiments/lab/build_taskset.py --out <目录>     # 指定输出根
    python experiments/lab/build_taskset.py --lab-run       # 需要操作系统级隔离执行器
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import types
from pathlib import Path

if __package__ in (None, ""):  # 直接以脚本方式运行时补上仓库根
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.lab.sandbox import ExecutionUnavailable, Sandbox, require_isolated_execution  # noqa: E402
from experiments.lab.tasks import load_task_dir  # noqa: E402
from experiments.lab.taskset_spec import FAMILIES, SPLIT_BY_INDEX  # noqa: E402

MODULE_NAME = "main"
TEST_FILE = "test_main.py"


def load_module(src: str) -> types.ModuleType:
    mod = types.ModuleType(MODULE_NAME)
    exec(compile(src, f"{MODULE_NAME}.py", "exec"), mod.__dict__)
    return mod


def run_case(src: str, script: list[str], probe: str):
    """在全新模块状态上执行 script，返回 probe 的值。"""
    mod = load_module(src)
    # script 与 probe 共用一个环境：用例里 probe 可能引用 script 定义的中间名（如快照）
    env = {"m": mod}
    for line in script:
        exec(line, env)
    return eval(probe, env)


TEST_TEMPLATE = '''"""验收测试（自动生成，期望值由正确实现在构建期算出）。

断言是字面量，不含参考实现：沙箱内的文件对 Agent 可读，
测试里若带一份正确实现，任务会退化成复制。
"""

import importlib
import unittest

import main


def fresh():
    """每个用例都重载模块，避免模块级状态在用例之间串味。"""
    return importlib.reload(main)


class TestBehaviour(unittest.TestCase):
{body}


if __name__ == "__main__":
    unittest.main()
'''


def render_case(index: int, script: list[str], probe: str, expected: object) -> str:
    lines = [f"    def test_case_{index}(self):", "        m = fresh()"]
    lines += [f"        {line}" for line in script]
    lines.append(f"        self.assertEqual({probe}, {expected!r})")
    return "\n".join(lines)


def build_variant(family: str, idx: int, spec: dict, out_root: Path) -> dict:
    task_id = f"{family}-{idx:02d}"
    split = SPLIT_BY_INDEX[idx]

    expected, buggy_actual, failures = [], [], 0
    for case in spec["cases"]:
        exp = run_case(spec["fixed"], case["script"], case["probe"])
        got = run_case(spec["buggy"], case["script"], case["probe"])
        expected.append(exp)
        buggy_actual.append(got)
        if got != exp or type(got) is not type(exp):
            failures += 1

    if failures == 0:
        raise AssertionError(
            f"{task_id}: 含缺陷实现通过了全部 {len(expected)} 条断言——这一题没有缺陷，"
            f"必须修规格而不是放宽校验"
        )
    if len(spec["cases"]) < 3:
        raise AssertionError(f"{task_id}: 断言只有 {len(spec['cases'])} 条，协议要求 ≥3")

    # 只覆盖已知的四份文件，从不删除目录。
    # 理由：一次抹掉 60+ 个文件会触发本机的大批量删除保护，也会让上一次构建的残留无从追查；
    # 覆盖写入是幂等的，残留文件由下面的扫描报出来，交给人工处置。
    task_dir = out_root / family / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    (task_dir / "statement.md").write_text(
        spec["statement"].strip() + "\n", encoding="utf-8"
    )
    (task_dir / f"{MODULE_NAME}.py").write_text(spec["buggy"], encoding="utf-8")

    body = "\n\n".join(
        render_case(i, case["script"], case["probe"], exp)
        for i, (case, exp) in enumerate(zip(spec["cases"], expected))
    )
    (task_dir / TEST_FILE).write_text(TEST_TEMPLATE.format(body=body), encoding="utf-8")

    (task_dir / "test.json").write_text(
        json.dumps(
            {
                "test_command": None,
                "protected": [TEST_FILE],
                "family": family,
                "split": split,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "task_id": task_id,
        "family": family,
        "split": split,
        "entry": spec.get("entry", ""),
        "n_cases": len(expected),
        "n_failing_cases": failures,
    }


def lab_run(task_dir: Path) -> bool:
    """用实验台把任务真跑一遍：初始代码必须失败。返回 True 表示符合预期。"""
    require_isolated_execution()
    task = load_task_dir(task_dir)
    sandbox = Sandbox.create_temp(prefix=task.task_id)
    try:
        task.materialize(sandbox)
        res = task.verify(sandbox, timeout=60.0)
        return not res.ok
    finally:
        sandbox.cleanup()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="构建任务集 v1")
    ap.add_argument("--out", default="experiments/tasks/v1")
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument("--lab-run", action="store_true", help="实跑初始代码，需要操作系统级隔离执行器")
    modes.add_argument("--no-lab-run", action="store_true", help="只构建并校验可信规格（默认）")
    args = ap.parse_args(argv)
    if args.lab_run:
        try:
            require_isolated_execution()
        except ExecutionUnavailable as exc:
            ap.error(str(exc))

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    rows = []
    expected_ids: set[str] = set()
    for family, fs in FAMILIES.items():
        variants = fs["variants"]
        if len(variants) != 8:
            raise AssertionError(
                f"{family}: 有 {len(variants)} 个变体，划分规则按 8 个/族设计，"
                f"少于 8 个会让某个用途缺题"
            )
        for idx, spec in enumerate(variants, start=1):
            expected_ids.add(f"{family}-{idx:02d}")
            rows.append(build_variant(family, idx, spec, out_root))

    known_files = {"statement.md", f"{MODULE_NAME}.py", TEST_FILE, "test.json"}
    stale = sorted(
        [str(p.relative_to(out_root)).replace("\\", "/")
         for p in out_root.rglob("*")
         if p.is_dir() and p.parent.name in FAMILIES and p.name not in expected_ids]
        + [str(p.relative_to(out_root)).replace("\\", "/")
           for p in out_root.rglob("*")
           if p.is_file() and p.parent.parent.name in FAMILIES and p.name not in known_files]
    )
    if stale:
        print(f"WARNING: 规格里已没有、但仍留在输出目录的条目：{stale}")
        print("         它们不在 index.csv 中，加载器不会读到；需要清理时人工删除。")

    if args.lab_run:
        bad = [r["task_id"] for r in rows if not lab_run(out_root / r["family"] / r["task_id"])]
        if bad:
            print(f"FAIL: 以下任务的初始代码竟然通过了验收：{bad}")
            return 1

    index_path = out_root / "index.csv"
    with index_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    by_split: dict[str, int] = {}
    for r in rows:
        by_split[r["split"]] = by_split.get(r["split"], 0) + 1
    print(f"tasks   = {len(rows)}")
    print(f"families= {len(FAMILIES)}")
    print(f"splits  = {by_split}")
    print(f"lab_run = {'all initial code fails (expected)' if args.lab_run else 'skipped'}")
    print(f"index   = {index_path}")
    print("BUILD OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
