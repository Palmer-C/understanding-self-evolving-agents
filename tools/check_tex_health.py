# tools/check_tex_health.py
# 正文健康度检查：在编译之前先挡住三类"看起来能通过编译、其实是脏的"问题。
# 用法：
#   python tools/check_tex_health.py [<文件或目录> ...]
# 不传参数时检查 book/ 下除 build/ 之外的全部 .tex。
#
# 检查项（全部为 error，退出码 1）：
#   1. 混入非预期文字系统的字符（西里尔 / 谚文 / 假名 / 泰文 / 天城体 / 阿拉伯 / 希伯来）。
#      希腊字母是本书数学符号的正常用字，不在检查范围内。
#   2. Markdown 粗体 **...**（tex 里必须写 \textbf{}）。
#   3. 单个反引号（历史上四次导致 XeLaTeX 进数学模式）。
#      成对的 ``...'' 是本书沿用的中文引号写法，不算问题。
#   4. 花括号不平衡。
#   5. \texttt{}、数学模式与 label 之外的裸露下划线（tex 里 _ 必须转义）。
#   6. 数字后未经转义的百分号（会把该行后续正文吞成注释）。
#
# 说明：本工具只看字符与 dagger 完整性，不判断语义；语义问题由 tools/check_consistency.py 管。
#       注释行（以 % 开头）不参与字符层检查。

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 正文不该出现的文字系统。希腊字母不在其中——$\theta$ 是本书正常用字。
FORBIDDEN_RANGES = [
    ("西里尔", r"[Ѐ-ӿ]"),
    ("谚文", r"[가-힯]"),
    ("日文假名", r"[぀-ヿ]"),
    ("泰文", r"[฀-๿]"),
    ("天城体", r"[ऀ-ॿ]"),
    ("阿拉伯", r"[؀-ۿ]"),
    ("希伯来", r"[֐-׿]"),
]

ALLOWED_PUNCT = set("—→←↔℃±…·°′″§¶†‡•−")
CMD_NAMES = ("texttt", "path", "url", "nolinkurl", "input", "include", "label", "ref", "eqref", "autoref", "cite", "caption")


def _blank_brace_span(s: str, start: int) -> str:
    """从头一个左花括号开始，把配对的整段替换成等长空白；找不到配对就原样返回。"""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                return s[:start] + " " * (end - start) + s[end:]
    return s


def _strip_safe_spans(s: str) -> str:
    """把合法的下划线容器（数学模式、\\texttt{} 等）替换成等长空白，便于找裸露下划线。"""
    out = re.sub(r"\$[^$\n]*\$", lambda m: " " * len(m.group()), s)
    out = re.sub(r"\\\[.*?\\\]", lambda m: " " * len(m.group()), out, flags=re.S)
    out = re.sub(r"\$\$.*?\$\$", lambda m: " " * len(m.group()), out, flags=re.S)
    out = re.sub(r"\\\(.*?\\\)", lambda m: " " * len(m.group()), out, flags=re.S)
    env = r"\\begin\{(equation|align|alignat|gather|multline|eqnarray|flalign)\*?\}.*?\\end\{\1\*?\}"
    out = re.sub(env, lambda m: " " * len(m.group()), out, flags=re.S)
    # 代码环境里的下划线与反引号都是字面量，不参与检查
    code = r"\\begin\{(lstlisting|verbatim|semiverbatim)\*?\}.*?\\end\{\1\*?\}"
    out = re.sub(code, lambda m: " " * len(m.group()), out, flags=re.S)
    for name in CMD_NAMES:
        pat = "\\" + name + "{"
        pos = out.find(pat)
        while pos >= 0:
            out = _blank_brace_span(out, pos + len(pat) - 1)
            pos = out.find(pat, pos + 1)
    return out


def check_file(path: Path):
    errors = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        return [f"{path}: 无法读取（{exc}）"]

    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:  # 传入的是仓库外的路径
        rel = path
    lines = text.splitlines()

    # 1. 文字系统（跳过注释行）
    for lineno, line in enumerate(lines, 1):
        if line.lstrip().startswith("%"):
            continue
        for name, pattern in FORBIDDEN_RANGES:
            for m in re.finditer(pattern, line):
                ctx = line[max(0, m.start() - 12): m.start() + 12].strip()
                errors.append(f"{rel}:{lineno} 混入{name}字符「{m.group()}」，上下文：{ctx}")

    # 2. Markdown 粗体（数学模式里的 $k^{**}$ 这类写法是合法的，先剥掉数学段）
    no_math = re.sub(r"\$[^$\n]*\$", " ", text)
    for lineno, line in enumerate(no_math.splitlines(), 1):
        if "**" in line:
            errors.append(f"{rel}:{lineno} Markdown 粗体 ** 应改为 \\textbf{{}}")

    # 3. 单个反引号（`` 成对出现是中文引号，去掉后再看有没有落单的；注释行不查）
    for lineno, line in enumerate(lines, 1):
        if line.lstrip().startswith("%"):
            continue
        rest = line.replace("``", "").replace("''", "")
        if "`" in rest:
            errors.append(f"{rel}:{lineno} 单个反引号应改为 \\texttt{{}}")

    # 4. 花括号平衡（跳过转义与注释）
    stripped_lines = [("" if l.lstrip().startswith("%") else l) for l in lines]
    stripped = "\n".join(stripped_lines).replace(r"\%", "").replace(r"\{", "").replace(r"\}", "")
    depth = 0
    for i, ch in enumerate(stripped):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                lineno = stripped[:i].count("\n") + 1
                errors.append(f"{rel}:{lineno} 多出一个右花括号")
                depth = 0
    if depth != 0:
        errors.append(f"{rel} 花括号不平衡：多出 {depth} 个左括号")

    # 5. 裸露下划线
    safe = _strip_safe_spans("\n".join(stripped_lines))
    for m in re.finditer(r"(?<!\\)_", safe):
        lineno = safe[: m.start()].count("\n") + 1
        errors.append(f"{rel}:{lineno} 裸露下划线，应写 \\_")

    # 6. 仅检查注释起点紧邻数字的情形，避免把正常行尾注释误报为正文。
    # 代码环境按字面量处理；逐行只看第一个未转义百分号。
    percent_scan = re.sub(
        r"\\begin\{(lstlisting|verbatim|semiverbatim)\*?\}.*?\\end\{\1\*?\}",
        lambda m: "".join("\n" if c == "\n" else " " for c in m.group()),
        text, flags=re.S,
    )
    for lineno, line in enumerate(percent_scan.splitlines(), 1):
        if line.lstrip().startswith("%"):
            continue
        m = re.search(r"(?<!\\)%", line)
        if m and m.start() > 0 and line[m.start() - 1].isdigit():
            errors.append(f"{rel}:{lineno} 数字后裸露百分号会截断正文，应写 \\%")

    return errors


def main() -> int:
    args = [Path(a) for a in sys.argv[1:]]
    files = []
    if args:
        for a in args:
            if a.is_dir():
                files += sorted(a.rglob("*.tex"))
            else:
                files.append(a)
    else:
        files = sorted((ROOT / "book").rglob("*.tex"))
    files = [f for f in files if "build" not in f.parts]

    total = 0
    per_file = {}
    for f in files:
        errs = check_file(f)
        if errs:
            per_file[str(f.relative_to(ROOT))] = errs
        total += len(errs)

    for name in sorted(per_file):
        for e in per_file[name][:20]:
            print(f"ERROR   {e}")
    print(f"检查文件数：{len(files)}，问题文件 {len(per_file)}，errors={total}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
