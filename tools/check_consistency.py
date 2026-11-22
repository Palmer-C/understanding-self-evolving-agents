# tools/check_consistency.py
# 提交正文前的自动检查。用法：
#   python tools/check_consistency.py
# 退出码 0 = 无 error；1 = 有 error（warning 不计入）
#
# 检查项：
#   1. 禁用词（agent/style-guide.md 第一节）
#   2. \data{} 的三个身份是否合法
#   3. 命题编号是否存在于 spec/propositions.md
#   4. 术语是否与 spec/glossary.md 的禁用别名冲突
#   5. 引用的 key 是否在 book/bib/references.bib 中登记

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BANNED = [
    "需要注意的是", "值得注意的是", "值得一提的是", "不难看出", "由此可见",
    "综上所述", "在当今快速发展的", "随着", "在……的背景下", "具有重要的意义",
    "提供了有力支撑", "发挥了重要作用", "很大程度上", "各式各样", "种种",
]
# "随着" 需排除 "随着 X 增大而增大" 这类合法物理表述
BANNED_SOFT = {"随着", "由此可见"}

DATA_IDS = {"cited", "calc", "measured"}


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def main() -> int:
    errors, warnings = [], []

    tex_files = sorted((ROOT / "book").rglob("*.tex"))
    if not tex_files:
        errors.append("未找到任何 .tex 文件")
    body_files = [f for f in tex_files if "build" not in f.parts]

    propositions = read(ROOT / "spec" / "propositions.md")
    prop_ids = set(re.findall(r"^\|\s*(P\d+b?)\s*\|", propositions, flags=re.M))

    glossary = read(ROOT / "spec" / "glossary.md")
    alias = set()
    for line in glossary.splitlines():
        parts = [c.strip() for c in line.strip().strip("|").split("|")]
        # 跳过 markdown 表格的对齐行（|---|---|...），否则会把「---」当成禁用别名
        if parts and all(c and set(c) <= {"-", ":"} for c in parts):
            continue
        if len(parts) >= 5 and parts[4] and parts[4] != "—":
            alias.update(a for a in parts[4].split("、") if a)

    bib = read(ROOT / "book" / "bib" / "references.bib")
    bib_keys = set(re.findall(r"^@\w+\{([^,]+),", bib, flags=re.M))

    for f in body_files:
        text = read(f)
        rel = f.relative_to(ROOT)

        for w in BANNED:
            for m in re.finditer(re.escape(w), text):
                line = text[: m.start()].count("\n") + 1
                if w in BANNED_SOFT and re.search(
                    re.escape(w) + r"[^。\n]{0,12}(增大|增加|提高|上升|变化)", text[m.start(): m.start() + 40]
                ):
                    continue
                errors.append(f"{rel}:{line} 禁用词「{w}」")

        for m in re.finditer(r"\\data\{([^}]+)\}", text):
            ident = m.group(1).strip()
            line = text[: m.start()].count("\n") + 1
            if ident not in DATA_IDS:
                errors.append(f"{rel}:{line} 非法数字身份「{ident}」，应为 cited/calc/measured")

        for m in re.finditer(r"\b(P\d+b?)\b", text):
            pid = m.group(1)
            line = text[: m.start()].count("\n") + 1
            if prop_ids and pid not in prop_ids:
                warnings.append(f"{rel}:{line} 命题 {pid} 未在 spec/propositions.md 登记")

        for a in alias:
            if a and a in text:
                line = text.find(a)
                line = text[:line].count("\n") + 1
                warnings.append(f"{rel}:{line} 使用了禁用别名「{a}」")

        for m in re.finditer(r"\\cite\{([^}]+)\}", text):
            for key in m.group(1).split(","):
                key = key.strip()
                line = text[: m.start()].count("\n") + 1
                if bib_keys and key not in bib_keys:
                    errors.append(f"{rel}:{line} 未登记的引用 key「{key}」")

    print(f"检查文件数：{len(body_files)}")
    for w in warnings[:40]:
        print(f"WARNING {w}")
    for e in errors[:40]:
        print(f"ERROR   {e}")
    print(f"errors={len(errors)} warnings={len(warnings)}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
