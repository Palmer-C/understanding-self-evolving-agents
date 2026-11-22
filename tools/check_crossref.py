#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_crossref.py — 全书交叉引用一致性审计（Hy3 · 稿件交叉检查）

不修改任何源文件；纯标准库；输出可读报告到 stdout 与（可选）--out 文件。

检查项：
  A. 未定义引用：每个 \\ref / \\cref / \\Cref / \\eqref / \\autoref / \\pageref /
     \\nameref 的 key 必须在全书 .tex（chapters/backmatter/frontmatter/figures/build）
     中至少有一个 \\label 定义；否则记为 ERROR（与 LaTeX 构建的 undef 警告交叉印证）。
  B. 重复标签：同一 key 被 \\label 定义多次 -> LaTeX 仅警告并取"最后定义"，
     \\ref 可能静默指向错误位置；记 WARNING，需人工裁定。
  C. 浮动体类型不一致：key 前缀 fig:/tab:/tbl:/eq:/eqn: 与 \\label 所在环境
     （figure / table / equation 族）不符 -> 疑似改号/复制粘贴错误，记 WARNING。
  D. 浮动体完整性：每个 table/figure 环境应含 \\caption 与 \\label；缺失记 INFO/WARNING。
  E. 孤立标签：定义但从未被引用 -> INFO（部分为有意，如命题标签按名引用）。

实现：单遍扫描 \\begin/\\end/\\label/\\caption/引用宏，维护环境栈与浮动体索引栈。
LaTeX 注释行（% 起）内的宏跳过。cleveref 多键 \\cref{a,b,c} 按逗号拆分。
"""
import argparse
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAPTERS = [
    os.path.join(ROOT, "book", "chapters", "*.tex"),
    os.path.join(ROOT, "book", "backmatter", "*.tex"),
    os.path.join(ROOT, "book", "frontmatter", "*.tex"),
    os.path.join(ROOT, "book", "figures", "*.tex"),
    # 注意：不扫描 book/build/*.tex —— 它们是 gen_*.py 生成的独立产物（如 ch05-e03-block.tex），
    # 并不被 \input 进正文；扫描它们会把"生成副本的标签"误报为与源文件重复。
    # 交叉引用以"实际编译进文档的源"为准（chapters/backmatter/frontmatter/figures），与 check_calcnum 一致。
]

REF_MACROS = {
    "ref": False, "cref": True, "Cref": True, "eqref": False,
    "autoref": False, "pageref": False, "nameref": False,
}

FLOAT_ENVS = {"table", "table*", "figure", "figure*"}
EQUATION_ENVS = {
    "equation", "equation*", "align", "align*", "gather", "gather*",
    "displaymath", "multline", "multline*", "flalign", "flalign*",
    "split", "cases", "subequations",
}

PREFIX_ENV = {
    "fig:": "figure", "tab:": "table", "tbl:": "table",
    "eq:": "equation", "eqn:": "equation",
    "alg:": "algorithm", "algorithm:": "algorithm",
}


def env_class(name):
    if name in FLOAT_ENVS:
        return "table" if name.startswith("table") else "figure"
    if name in EQUATION_ENVS:
        return "equation"
    return "other"


def balanced_brace_content(text, start):
    assert text[start] == "{"
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return text[start + 1:], n


def find_brace_key(text, brace_open):
    content, _ = balanced_brace_content(text, brace_open)
    return content.strip()


def in_comment(text, pos):
    """pos 之前到行首是否含未转义 %（LaTeX 注释）。"""
    line_start = text.rfind("\n", 0, pos) + 1
    seg = text[line_start:pos]
    idx = seg.find("%")
    if idx < 0:
        return False
    if idx > 0 and seg[idx - 1] == "\\":
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="写报告到此文件（utf-8）")
    ap.add_argument("--only", help="只扫含此子串的文件名（调试）")
    args = ap.parse_args()

    files = []
    for pat in CHAPTERS:
        files.extend(glob.glob(pat))
    if args.only:
        files = [f for f in files if args.only in os.path.basename(f)]
    files.sort()

    labels = {}          # key -> [(file, line, envclass)]
    refs = []            # (file, line, macro, key)
    floats = []          # [file, envname, line, has_caption, has_label]

    for f in files:
        with open(f, encoding="utf-8") as fh:
            text = fh.read()

        def line_of(pos):
            return text.count("\n", 0, pos) + 1

        # Listings defines its counter-bound label as an option, not a label macro.
        for m in re.finditer(r"\\begin\{lstlisting\}\[([^\n]*)\]", text):
            if not in_comment(text, m.start()):
                option = re.search(r"(?:^|,)\s*label\s*=\s*\{?([^,}\]\s]+)", m.group(1))
                if option:
                    labels.setdefault(option.group(1), []).append((f, line_of(m.start()), "listing"))
        for m in re.finditer(r"\\hyperref\[([^\]]+)\]", text):
            if not in_comment(text, m.start()):
                refs.append((f, line_of(m.start()), "hyperref", m.group(1)))

        events = []
        for m in re.finditer(r"\\label\s*\{", text):
            if not in_comment(text, m.start()):
                events.append((m.start(), "label", m.start() + len("\\label")))
        for macro, multi in REF_MACROS.items():
            for m in re.finditer(r"\\" + macro + r"\s*\{", text):
                if not in_comment(text, m.start()):
                    events.append((m.start(), "ref", (macro, m.start() + len("\\" + macro))))
        for m in re.finditer(r"\\begin\s*\{([a-zA-Z*]+)\}", text):
            if not in_comment(text, m.start()):
                events.append((m.start(), "begin", m.group(1)))
        for m in re.finditer(r"\\end\s*\{([a-zA-Z*]+)\}", text):
            if not in_comment(text, m.start()):
                events.append((m.start(), "end", m.group(1)))
        for m in re.finditer(r"\\caption\s*(\*|\[)?", text):
            if not in_comment(text, m.start()):
                events.append((m.start(), "caption", None))

        events.sort(key=lambda e: e[0])

        stack = []        # 环境名栈
        float_idx = []   # floats 下标栈（仅 table/figure/equation 族）

        for pos, kind, payload in events:
            if kind == "begin":
                stack.append(payload)
                if env_class(payload) != "other":
                    floats.append([f, payload, line_of(pos), False, False])
                    float_idx.append(len(floats) - 1)
            elif kind == "end":
                if stack and stack[-1] == payload:
                    stack.pop()
                elif payload in stack:
                    while stack and stack[-1] != payload:
                        s = stack.pop()
                        if env_class(s) != "other" and float_idx and floats[float_idx[-1]][1] == s:
                            float_idx.pop()
                    if stack:
                        stack.pop()
                if float_idx and floats[float_idx[-1]][1] == payload:
                    float_idx.pop()
            elif kind == "caption":
                # 标记最外层 table/figure 浮动体
                for i in float_idx:
                    if floats[i][1] in FLOAT_ENVS:
                        floats[i][3] = True
                        break
                else:
                    if float_idx:
                        floats[float_idx[-1]][3] = True
            elif kind == "label":
                key = find_brace_key(text, payload)
                if not key:
                    continue
                ecls = env_class(floats[float_idx[-1]][1]) if float_idx else "other"
                labels.setdefault(key, []).append((f, line_of(pos), ecls))
                if float_idx:
                    floats[float_idx[-1]][4] = True
            elif kind == "ref":
                macro, bo = payload
                content = find_brace_key(text, bo)
                if not content:
                    continue
                keys = [k.strip() for k in content.split(",")] if REF_MACROS[macro] else [content.strip()]
                for k in keys:
                    if k:
                        refs.append((f, line_of(bo), macro, k))

    # ---- 分析 ----
    out = []
    out.append("=== 全书交叉引用一致性审计 (check_crossref.py) ===")
    out.append("扫描文件: %d" % len(files))
    out.append("标签定义(label): %d 个 key" % len(labels))
    out.append("引用出现(ref): %d 处" % len(refs))
    out.append("浮动/公式环境: %d 个" % len(floats))
    out.append("")

    undef = [(f, ln, macro, k) for (f, ln, macro, k) in refs if k not in labels]
    out.append("--- A. 未定义引用 (ERROR 若 >0) ---")
    out.append("未定义引用数: %d" % len(undef))
    for f, ln, macro, k in undef:
        out.append("  [%s:%d] \\%s{%s} 无对应 \\label" % (os.path.basename(f), ln, macro, k))
    out.append("")

    dups = {k: v for k, v in labels.items() if len(v) > 1}
    out.append("--- B. 重复标签 (WARNING，需裁定) ---")
    out.append("重复标签数: %d" % len(dups))
    for k, occ in dups.items():
        locs = ", ".join("%s:%d(%s)" % (os.path.basename(x[0]), x[1], x[2]) for x in occ)
        out.append("  %s -> %s" % (k, locs))
    out.append("")

    mism = []
    for f, ln, macro, k in refs:
        if k not in labels:
            continue
        colon = k.find(":")
        exp_env = PREFIX_ENV.get(k[:colon + 1]) if colon >= 0 else None
        if exp_env is None:
            continue
        actual = labels[k][0][2]
        if actual != "other" and actual != exp_env:
            mism.append((f, ln, macro, k, actual, exp_env))
    out.append("--- C. 浮动体类型不一致 (WARNING) ---")
    out.append("类型不一致数: %d" % len(mism))
    for f, ln, macro, k, actual, exp_env in mism:
        out.append("  [%s:%d] \\%s{%s} 前缀指向 %s，但 \\label 位于 %s 环境"
                   % (os.path.basename(f), ln, macro, k, exp_env, actual))
    out.append("")

    out.append("--- D. 浮动体完整性 (caption/label) ---")
    tf = [fl for fl in floats if fl[1] in FLOAT_ENVS]
    missing_cap = [fl for fl in tf if not fl[3]]
    missing_lab = [fl for fl in tf if not fl[4]]
    out.append("table/figure 总数: %d" % len(tf))
    out.append("缺 \\caption 的 table/figure: %d" % len(missing_cap))
    for fl in missing_cap:
        out.append("  [%s:%d] \\begin{%s}" % (os.path.basename(fl[0]), fl[2], fl[1]))
    out.append("缺 \\label 的 table/figure: %d" % len(missing_lab))
    for fl in missing_lab:
        out.append("  [%s:%d] \\begin{%s}" % (os.path.basename(fl[0]), fl[2], fl[1]))
    out.append("")

    ref_keys = set(k for _, _, _, k in refs)
    orphans = [k for k in labels if k not in ref_keys]
    out.append("--- E. 孤立标签 (INFO，部分为有意) ---")
    out.append("孤立标签数: %d" % len(orphans))
    for k in sorted(orphans):
        occ = labels[k][0]
        out.append("  %s [%s:%d, %s]" % (k, os.path.basename(occ[0]), occ[1], occ[2]))
    out.append("")

    out.append("=== 汇总 ===")
    out.append("A 未定义引用=%d (期望 0，与 LaTeX undef=0 交叉印证)" % len(undef))
    out.append("B 重复标签=%d (WARNING 待裁定)" % len(dups))
    out.append("C 类型不一致=%d (WARNING)" % len(mism))
    out.append("D 缺caption=%d / 缺label=%d" % (len(missing_cap), len(missing_lab)))
    out.append("E 孤立标签=%d (INFO)" % len(orphans))
    verdict = "CLEAN" if (not undef and not dups and not mism
                          and not missing_cap and not missing_lab) else "FINDINGS"
    out.append("判定: %s" % verdict)

    report = "\n".join(out)
    print(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fo:
            fo.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
