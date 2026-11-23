# 深入理解自进化 Agent

作者：shawn。全书围绕一个问题展开：一个 Agent 从经验中改变了什么，又怎样检验这种变化？本公开源码预览包含 16 章、7 个附录、参考文献索引、配图和选定的实验记录。

## 阅读与复算

从仓库根目录运行。编译书稿需要 Windows 中文字体、XeLaTeX、latexmk 和 biber。成功后可打开 book/main.pdf。

~~~powershell
powershell -ExecutionPolicy Bypass -File .\book\build.ps1
~~~

使用 Python 3 可直接核对样本量例题和历史成本，或查看 E01 小规模试验的离线计划。三条命令均无需模型凭据。

~~~text
python calculations/audit_sample_size.py
python experiments/lab/cost_report.py
python -m experiments.lab.run_e01 --trial
~~~

本版没有配置运行不受信任候选程序所需的独立执行环境。E03 拆分 A 的两份档案分别给出 72/80 和 70/80，依赖它们的基线比较暂停。十条正式命题仍为 open；E03v2 的离线检查只核验了工件。[公开材料与复算命令](analysis/README.md) · [命题表](spec/propositions.md) · [原文索引](references/sources.csv)

## 内容速览

| 篇 | 章 | 主题 | 一句话核心 | 关联实验 |
|---|---|---|---|---|
| 一 · 定义问题与建立评价方法 | [1](book/chapters/ch01.tex) | 从自主执行到自进化 | 会做任务不等于会改自己：先给"自进化"一个可证伪的定义 | — |
| | [2](book/chapters/ch02.tex) | 三层时间尺度下的自进化框架 | 一步、一个回合、一个版本：经验如何跨任务留下来 | — |
| | [3](book/chapters/ch03.tex) | 如何检验持续改进 | E01 四格试跑采用相同的回合配额；实际调用量有何差别，跨零区间又允许怎样的判断？ | E01 |
| 二 · 模型参数之外的学习机制 | [4](book/chapters/ch04.tex) | 从运行轨迹到可信反馈 | E02 栈案例：完成说明声称已经弹出栈顶，为什么代码只返回了元素？ | E02 |
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

## 许可范围

| 材料 | 许可 |
|---|---|
| 原创书稿、排版 PDF、原创配图、研究与分析说明、写作规范文本 | [CC BY-NC-SA 4.0](LICENSE-CC-BY-NC-SA-4.0.txt)，分享及改编须署名、标记修改并遵守非商业与相同方式共享条件。 |
| 作者编写的构建脚本、离线复算与实验工具、实验协议与题库、归档源码快照、项目自产 CSV/JSON 及来源索引 | [Apache-2.0](LICENSE-APACHE-2.0.txt)，分发时须遵守许可中的声明保留与修改标示等条件。 |

第三方文献、上游代码与嵌入字体分别适用原许可。定量图附有[字体与来源说明](book/figures/generated/FONT-NOTICES.md)。
