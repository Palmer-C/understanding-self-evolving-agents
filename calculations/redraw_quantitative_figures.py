"""从公开数值重绘第 4、8 章的两张 PDF。依赖书稿使用的 XeLaTeX 与 PGFPlots。"""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))

from experiments.lab.archive_inputs import load_summary

E02_RUN = "E02-20260924T153511Z-421eac"
E02_ARMS = ("arm_formal", "arm_exec", "arm_review", "arm_self", "arm_noise")
COST_INPUT = "calculations/ch08-cost-teaching-2026-09-30.json"


def effect_rows(root):
    """Read archived paired intervals and convert proportions to percentage points."""
    gains = load_summary(root, E02_RUN)["gains_vs_base"]
    if set(gains) != set(E02_ARMS):
        raise ValueError("E02 归档中的比较组与图示不一致。")
    rows = []
    for arm in E02_ARMS:
        gain = gains[arm]
        if (gain["unit"], gain["n_pairs"], gain["n_runs_min"]) != ("task", 16, 5):
            raise ValueError(f"E02 对照条件与图注不一致（{arm}）。")
        lower, point, upper = (gain[k] for k in ("ci95_low", "point", "ci95_high"))
        if not all(math.isfinite(v) for v in (lower, point, upper)) or not -1 <= lower <= point <= upper <= 1:
            raise ValueError(f"E02 区间无效（{arm}）。")
        rows.append((lower * 100, point * 100, upper * 100))
    return rows


def cost_rows(root):
    """Verify each published integer coordinate against the constructed cost model."""
    data = json.loads((root / COST_INPUT).read_text(encoding="utf-8-sig"))
    if data["kind"] != "constructed_exact_cost_example_not_experiment" or data["model_calls"] != 0:
        raise ValueError("第 8 章输入须为费用教学示例。")
    params = data["assumptions"]
    k = data["k"]
    if k != list(range(11)) or params["maintenance_at_k"] != 6:
        raise ValueError("教学示例须包含 0 至 10 次复用与第六次前的维护费用。")
    base = [params["replan_fixed"] + params["replan_per_use"] * x for x in k]
    static = [params["skill_fixed"] + params["skill_per_use"] * x for x in k]
    maintained = [y + (params["maintenance_cost"] if x >= params["maintenance_at_k"] else 0)
                  for x, y in zip(k, static)]
    if (base, static, maintained) != (data["replan"], data["static_skill"], data["maintained_skill"]):
        raise ValueError("第 8 章归档数列与随图费用公式不一致。")
    return list(zip(k, base, static, maintained))


def document(body):
    return r"""\documentclass[tikz,border=5pt]{standalone}
\usepackage[UTF8]{ctex}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\definecolor{series}{HTML}{254C6A}
\begin{document}
\begin{tikzpicture}
""" + body + r"""
\end{tikzpicture}
\end{document}
"""


def effect_plot(rows):
    labels = ",".join(arm.replace("_", r"\_") for arm in E02_ARMS)
    lines = [r"""\begin{axis}[
width=15cm,height=6cm,axis lines=left,xmin=-42,xmax=10,
xtick={-40,-30,-20,-10,0,10},xmajorgrids,grid style={gray!20},
y dir=reverse,ymin=-0.5,ymax=4.5,ytick={0,1,2,3,4},
yticklabels={""" + labels + r"""},xlabel={相对无记忆基线的回合通过率差（百分点）},
title={E02：任务配对差及归档的 95\% 自助法区间},
tick label style={font=\small}]
\draw[dashed,gray] (axis cs:0,-0.5) -- (axis cs:0,4.5);"""]
    for y, (lower, point, upper) in enumerate(rows):
        lines.extend([
            rf"\draw[series,thick,|-|] (axis cs:{lower:.8g},{y}) -- (axis cs:{upper:.8g},{y});",
            rf"\fill[series] (axis cs:{point:.8g},{y}) circle[radius=2pt];",
        ])
    lines.append(r"\end{axis}")
    return document("\n".join(lines))


def cost_plot(rows):
    panels = []
    for index, title in [(2, "固定边际费用"), (3, "第六次复用前增加维护费")]:
        base = " ".join(f"({row[0]},{row[1]})" for row in rows)
        skill = " ".join(f"({row[0]},{row[index]})" for row in rows)
        position = r"at={(left.east)},anchor=west,xshift=13mm," if panels else "name=left,"
        ylabel = "" if panels else "ylabel={假设费用单位（非实测）},"
        equalities = [row for row in rows if row[1] == row[index]]
        markers = "\n".join(
            rf"\node[anchor=north west,font=\scriptsize] at (axis cs:{k},{fee}) {{$k={k}$ 平价}};"
            for k, fee, *_ in equalities
        )
        panels.append(r"\begin{axis}[" + position + ylabel + "title={" + title + r"""},
width=8.1cm,height=6.1cm,axis lines=left,
xmin=0,xmax=10.2,ymin=0,ymax=55,xtick={0,2,4,6,8,10},ytick={0,10,20,30,40,50},
xlabel={复用次数 $k$},ymajorgrids,grid style={gray!20},tick label style={font=\small},
legend pos=north west,legend style={draw=none,font=\footnotesize}]
\addplot[gray,densely dashed,thick] coordinates {""" + base + r"""};
\addlegendentry{重新规划}
\addplot[series,thick,mark=*,mark size=1.6pt] coordinates {""" + skill + r"""};
\addlegendentry{技能侧累计费用}
""" + markers + r"\end{axis}")
    return document("\n".join(panels))


def render(out_dir):
    if out_dir.exists() or out_dir.is_symlink():
        raise FileExistsError("输出目录已存在，请指定新目录。")
    if not out_dir.parent.is_dir():
        raise FileNotFoundError("输出目录的上一级目录不存在。")
    sources = {"ch04-e02-effects": effect_plot(effect_rows(ROOT)),
               "ch08-cost-teaching": cost_plot(cost_rows(ROOT))}
    engine = shutil.which("xelatex")
    if not engine:
        raise RuntimeError("需要书稿使用的 XeLaTeX，并安装 ctex、standalone 和 pgfplots。")
    # Finish both PDFs before reserving the destination. Nothing is written to the book.
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        for stem, source in sources.items():
            tex = work / f"{stem}.tex"
            tex.write_text(source, encoding="utf-8")
            result = subprocess.run([engine, "-no-shell-escape", "-halt-on-error",
                                     "-interaction=nonstopmode", tex.name], cwd=work,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if result.returncode:
                output = result.stdout.decode(errors="replace").splitlines()
                reason = next((line for line in output if line.startswith("!")), "请检查 TeX 宏包和中文字体。")
                raise RuntimeError(f"{stem} 编译失败。{reason}")
        out_dir.mkdir()
        created = []
        try:
            for stem in sources:
                target = out_dir / f"{stem}.pdf"
                with (work / target.name).open("rb") as src, target.open("xb") as dest:
                    created.append(target)
                    shutil.copyfileobj(src, dest)
        except OSError:
            for path in created:
                path.unlink()
            if not any(out_dir.iterdir()):
                out_dir.rmdir()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path, help="两个 PDF 的新目录，上一级须存在")
    args = parser.parse_args()
    try:
        render(args.out_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(args.out_dir.resolve())


if __name__ == "__main__":
    main()
