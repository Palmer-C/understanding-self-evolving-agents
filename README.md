# 深入理解自进化 Agent
## 经验如何变成可检验的能力变化

作者：shawn。本公开预览收录 2026 年 11 月 22 日修订稿的 16 章、7 个附录、图源、参考文献索引，以及选定的实验材料与离线工具。

## 📑 内容速览

五篇十六章，从"怎么定义自进化"讲到"能证明到什么程度"：

| 篇 | 章 | 主题 | 一句话核心 | 关联实验 |
|---|---|---|---|---|
| 一 · 定义问题与建立评价方法 | [1](book/chapters/ch01.tex) | 从自主执行到自进化 | 会做任务不等于会改自己：先给"自进化"一个可证伪的定义 | — |
| | [2](book/chapters/ch02.tex) | 三层时间尺度下的自进化框架 | task / episode / version 三个尺度，只有 version 层的变化算自进化 | — |
| | [3](book/chapters/ch03.tex) | 如何检验持续改进 | 等预算四格（E01）：正向点估计配上跨零区间，为什么判不了"更新更好" | E01 |
| 二 · 模型参数之外的学习机制 | [4](book/chapters/ch04.tex) | 从运行轨迹到可信反馈 | 反馈质量六臂（E02）：流畅的反思文字预测不了真正的失败位置 | E02 |
| | [5](book/chapters/ch05.tex) | 记忆如何转化为可复用的经验 | 形式、容量与读取者如何影响迁移：直接比较、来源冲突与缺失对照 | E03、E03c |
| | [6](book/chapters/ch06.tex) | 记忆操作的学习化：从规则到策略 | 记什么、怎么检索，交给固定规则、自主组织还是学习策略 | E03b |
| | [7](book/chapters/ch07.tex) | 指令与上下文的自动优化 | 固定指令、人工修改、自动搜索，固定查询预算比一比 | E04 |
| | [8](book/chapters/ch08.tex) | 工具与技能的生成、验证和复用 | 技能有生命周期和成本交点：低于临界重复次数，固化不划算 | E05 |
| | [9](book/chapters/ch09.tex) | 工作流与多 Agent 结构的演化 | 结构搜索要受限、要等预算，验证与失败分支的成本也要记账 | E06 |
| 三 · 参数学习与更高层自我修改 | [10](book/chapters/ch10.tex) | 从外部经验到模型参数 | 外部经验灌进参数：回归集、训练/推理预算分开记，警惕能力遗忘 | E08 |
| | [11](book/chapters/ch11.tex) | 经验数据、自生成课程与 Agent 强化学习 | 课程会漂移、奖励会被投机：多数答案一致，不等于多数答案正确 | E07、E09 |
| | [12](book/chapters/ch12.tex) | 代码自修改与元进化 | 会改代码的 Agent 再改自己：元层修改的受限原型与迁移检验 | E10 |
| 四 · 长期运行与系统工程 | [13](book/chapters/ch13.tex) | 何时进化：触发条件与资源预算 | 事件触发 vs 周期 vs 每任务，漂移时差距是否扩大 | E11 |
| | [14](book/chapters/ch14.tex) | 可靠性、隔离与可恢复的更新 | 退化可测、检测有时延、恢复有边界；接地频率留作开放问题 | E12、E02b |
| 五 · 贯穿案例与研究边界 | [15](book/chapters/ch15.tex) | 试验审计与迁移设计 | 沿保存案例追踪输入、持久物、执行与验收，再设计迁移对照 | E01–E05 分阶段证据 |
| | [16](book/chapters/ch16.tex) | 理论边界与研究议程 | 十个研究问题：已有观察、适用条件与下一项比较 | 全部 |


## 阅读与复算

从本目录运行以下命令。PDF 构建使用 Windows、与 ctex 相容的中文字体和 PATH 中的 XeLaTeX、latexmk、biber。

~~~powershell
powershell -ExecutionPolicy Bypass -File .\book\build.ps1
~~~

成品在 book/main.pdf。以下两个入口使用 Python 3 和包内材料，分别核对统计例题和历史成本账。

~~~text
python calculations/audit_sample_size.py
python experiments/lab/cost_report.py
~~~

[分析说明](analysis/README.md)说明所选材料、脱敏改动和复算边界。[参考文献索引](references/sources.csv)给出原文入口。历史命题及状态见[命题表](spec/propositions.md)。

## 📄 许可证

项目按材料类型分别授权。下表适用于作者有权授权的部分。

| 材料 | 许可证 | 适用范围 |
|---|---|---|
| 书稿、配图与写作文档 | [CC BY-NC-SA 4.0](LICENSE-CC-BY-NC-SA-4.0.txt) | 书稿 LaTeX 源码及其排版 PDF、原创配图与图源、`spec/`、`research/`、`agent/` 下的写作记录、`analysis/` 下的说明及保留的规范文本、来源索引说明，以及项目 README 和 CHARTER。 |
| 工具、实验装置与项目自产数据 | [Apache-2.0](LICENSE-APACHE-2.0.txt) | `book/build.ps1`、`references/download_papers.ps1`、`agent/` 下的脚本、`tools/`、`calculations/`、`experiments/`（含协议、题库和结果）、`analysis/` 下项目生成的 CSV、JSON 和离线核验输出，以及 `references/sources.csv` 中项目编制的索引。 |

可以在非商业条件下分享和改编书稿，须署名、附许可链接并标明修改；公开分享改编作品时须采用相同许可。Apache-2.0 允许商业使用和再分发，分发时须遵守许可中的署名、声明保留和修改标示等条件。

引文、论文、上游代码以及材料中注明其他来源的内容，权利由各自权利人保留。来源索引提供题名、版本和原始入口；下载脚本只协助定位原文。第三方材料的再使用应核对原出处的许可。
