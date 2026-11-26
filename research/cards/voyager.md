# VOYAGER（arXiv:2305.16291v2）

## 来源
VOYAGER: An Open-Ended Embodied Agent with Large Language Models，Guanzhi Wang 等，arXiv:2305.16291v2（2023-10-19），https://voyager.minedojo.org 。论文未标注历史运行提交。另核作者实现快照 55e45a880755d0c8c66ca7fb5fe7962ac8974f89（2023-07-27），用于定位检索、执行、准入三处代码。

## 研究问题
解决开放世界（Minecraft）中 LLM 智能体无法"持续探索、逐步积累并跨任务复用技能"的失败——即缺乏终身学习能力。明确不在实验范围内：不微调模型参数（黑盒 GPT-4，Sec 1 "bypasses … finetuning"）；不做 3D 感知/传感器运动控制（依赖 Mineflayer 高层 API，Sec 3.2）；不与基于屏幕像素输入的 Minecraft 智能体做 apple-to-apple 比较（Sec 3.2）。

## 六问定位
- 改什么：L（技能库，可执行代码写入向量库）为主角；θ/P/M 均不改（黑盒 GPT-4，无微调，指令为固定模板）。自动课程承担 G 中"任务提议"角色，但持久写入 version 层的只有 L。修改器 = 搜索空间 𝒮（程序空间 + 技能检索）与优化算法 H（迭代提示机制：GPT-4 生成代码并依反馈重生成）。
- 根据什么改：环境结果（Minecraft 执行反馈、库存/装备/生物等状态）、执行错误（解释器 trace）、模型自评（self-verification，另一 GPT-4 充当 critic 判定成功并给 critique）。主信号：self-verification 的成功/失败判定 + 环境执行结果。
- 怎样改：程序生成（code as action）+ 反思（把环境反馈、执行错误、critique 回填 prompt 再生成）。非监督学习、非强化学习。
- 什么时候改：任务后（self-verification 确认任务完成 → 提交技能入库）；事件触发（连续 4 轮代码生成仍卡住 → 向课程请求新任务）。成功触发准入检查，约定排除的整理任务会被跳过。
- 保留什么：技能库跨 episode、跨任务持久——明确进入 version 层（系统持久组件 L 被修改）。episode 内推理轨迹属 step/episode 层，不持久；仅入库技能进入 version。
- 怎样检验：外部 held-out——重置到新 Minecraft 世界、清空库存，对未见任务做零样本泛化（Table 2，最大 50 次提示迭代）；同环境（MineDojo）内用 Table 1 科技树掌握度与消融 Fig 9 检验。独立封存测试集：未定位。

## 机制
三组件（Sec 2）。
(1) 自动课程（Sec 2.1）：GPT-4 基于"发现尽可能多的事物"总体目标，按探索进度与智能体状态自底向上提议任务；温度 0.1；可视为 in-context novelty search。
(2) 技能库（Sec 2.2 / Fig 4）：每个技能 = 可执行 JavaScript 程序（Mineflayer 接口，PDF p6 §3.1）；向量库 key = 程序描述的 embedding（描述由 GPT-3.5 生成，编码模型为 text-embedding-ada-002），value = 程序本身；生成提示默认取至多五个已索引技能。执行时可调用库中全部程序与控制原语。检索名单、执行环境可见程序与本次真正调用的函数各有不同的证据。
(3) 迭代提示机制（Sec 2.3）：每轮执行生成代码得环境反馈与执行错误，回填 GPT-4 重生成；self-verification 由另一 GPT-4 判定成功/失败并给 critique；成功后进入准入分支。固定快照的 SkillManager 会跳过向箱子存放多余物品的整理任务。卡住 4 轮则换任务。

## 实验
基础模型 gpt-4-0314 + gpt-3.5-turbo-0301，embedding text-embedding-ada-002，除课程外温度 0。环境 MineDojo + Mineflayer。对照 ReAct / Reflexion / AutoGPT。
- 原论文报告：160 次提示迭代内发现 63 种独特物品，是其余对照的 3.3×，条件：MineDojo，GPT-4，最大 160 提示迭代（Sec 3.3 / Fig 1）。
- 原论文报告：解锁科技树木质级快 15.3×、石质 8.5×、铁质 6.4×，且唯一解锁钻石级，条件：MineDojo，GPT-4，Table 1（提示迭代数均值）。
- 原论文报告：VOYAGER 在零样本新世界任务上 Diamond Pickaxe 19±3(3/3)、Golden Sword 18±7(3/3)、Lava Bucket 21±5(3/3)、Compass 18±2(3/3)，对照 w/o Skill Library 为 36(2/3)、30±9(3/3)、27±9(3/3)、26±3(3/3)，条件：新世界重置、最大 50 提示迭代，Table 2。

## 成本
推理/搜索 = 提示迭代次数（技能生成多轮，封顶 4 轮/任务）。评测独立成本数字：未定位。
- 原论文报告：GPT-4 API 比 GPT-3.5 贵 15×，条件：Sec 4 "Cost" 段。技能在探索任务中经迭代提示生成并入库，后续任务复用，但"回本所需任务数"未量化（未定位）。

## 证据
Sec 2.1/2.2/2.3；Table 1（科技树）、Table 2（零样本泛化）、Fig 9（消融）；Sec 3.4 消融。代码路径：未定位（文中仅给项目站）。

## 局限与风险
- 有无技能库对照支持所报告设置中的组件作用，但提示迭代配额并不对齐 token、模型调用与所有离线成本，不能直接证明同等总资源下胜过更多重试。Table 1 探索任务与 Table 2 新世界任务须分别解释；Fig 9 的模型替换也不是冻结同一技能库后的读取者迁移实验。
- 负结果：随机课程使发现物品数下降 93%；去掉 self-verification 下降 73%（Sec 3.4）。
- 风险：自动课程偶发不可达任务（"铜剑"等幻觉）；self-verification 偶发误判；GPT-4 偶用无效燃料/不存在 API（Sec 4）。评测泄漏风险：探索/科技树在同一环境内，无独立封存集（未定位）。

## 本章角色
主角（version 层 L 变化的实例：技能写入并跨任务检索，有 w/o Skill Library 对照；入库含 GPT-4 自评，效果与成本结论受具体评价范围限制）。

## 可实验性
需简化（Minecraft 环境复现成本高；技能库/课程/迭代提示机制可在 lab 用更小代码环境复现核心：程序生成 + 向量库检索 + 成功才入库）。

## 写作用途
支撑"只有进入 version 层（如 L 技能库）的持久组件变化才算自进化"的判断，并说明有无组件对照、准入判断与完整预算归因是不同层次的证据。

## 2026-09-30 16:15班机制表述修正

Figure4（本地PDF第4页）将GPT-3.5生成程序描述与Embedding编码分成不同步骤；不能称GPT-3.5直接生成向量。§2.3（第5页）为环境反馈、解释器错误、自评三类信号，不是三个独立可靠等级；自评请求读取当前状态与任务。技能依赖并非文本经验完全没有的成本。

## 2026-10-01 18:xx 班来源核验（Hy3 · R3）
- 一手来源：本地 PDF `references/files/papers/voyager__2305.16291.pdf`（42 页，v2，封面 2305.16291v2 [cs.AI] 19 Oct 2023）全文抽取核对。
- 关键数字逐项命中：160 提示迭代内发现 63 独特物品 = 3.3×（Fig 1）；科技树 木质 15.3× / 石质 8.5× / 铁质 6.4×、唯一解锁钻石（Table 1）；零样本新世界（Fig 8 / 零样本泛化表）：VOYAGER Ours Diamond Pickaxe 19±3(3/3)、Golden Sword 18±7(3/3)、Lava Bucket 21±5(3/3)、Compass 18±2(3/3)，对照 w/o Skill Library 36(2/3)、30±9(3/3)、27±9(3/3)、26±3(3/3)；GPT-4 API 贵 15×（Sec 4）；随机课程 -93%、去 self-verification -73%（Sec 3.4）。
- 结论：与本地 PDF 全一致（注：零样本数值位于 Fig 8 / 附录零样本泛化表，与卡中"Table 2"标注指向同一张零样本表），关闭本卡 R3。
