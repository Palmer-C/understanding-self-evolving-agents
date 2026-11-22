# AFLOW（arXiv:2410.10762v4）

## 来源
AFLOW: Automating Agentic Workflow Generation，Jiayi Zhang 等，arXiv:2410.10762v4（2025-04-15，ICLR 2025）。代码参考固定为 github.com/FoundationAgents/AFlow 提交 3f457218fc716093fe53f6df8a5d5e6379d66346（2025-12-25）。该公开参考实现含从 MetaGPT 迁移后的边界，原论文历史运行配置尚缺直接绑定。

## 研究问题
解决"agentic workflow（多步 LLM 调用流程）需大量人工设计、难以自动化且泛化差"的失败。明确不在：本文聚焦带数值评估函数的推理任务（Sec 3.2）；不要求人工初始工作流（相较 ADAS/DSPy 需手动 setup，Sec 1）。

## 六问定位
- 改什么：G（工作流结构：节点 N 与代码表示的边 E，即 LLM 调用顺序/条件/循环）+ 部分 P（各节点 prompt）。搜索空间 𝒮 = SAFlow = {(P1..Pn, E, O1..On)}，固定模型 M/温度 τ/格式 F，主要搜 E（代码边）与 P（节点 prompt）及算子 O 组合（Sec 3.1–3.2，式 1）。修改器 = MCTS 变体（算法 H）。θ/L/M 不改（M 在执行期固定）。
- 根据什么改：执行测试（在验证集执行工作流，G(W,T) 得分；每个工作流测 5 次取均值/标准差）+ 树经验（backpropagation 记录修改与成败）。主信号：验证集执行得分。
- 怎样改：搜索（MCTS：soft mixed probability selection + LLM-based expansion + execution evaluation + experience backpropagation，Algorithm 1）。非监督学习。
- 什么时候改：任务后/离线（MCTS 迭代 Nmax=20 轮优化工作流）。最终 W* 进入 version 层（G 被修改）。
- 保留什么：搜索得到的最优工作流 W* 跨 episode、跨任务持久——进入 version 层（G 变化）。树内 experience 保存修改及其相对父候选的成败，用于搜索选择。论文没有规定搜索后销毁或禁止跨搜索保留。跨搜索复用需要另行说明版本、评价范围与读取规则。
- 怎样检验：外部 held-out 测试集（按 1:4 划分验证/测试；HumanEval/MBPP 全量，HotpotQA/DROP 各抽 1000，MATH 617）。跨模型迁移检验 Table 2（用 GPT-4o-mini 搜的工作流套到 DeepSeek-V2.5/GPT-4o/Claude-3.5 执行）。独立封存集：未定位。

## 机制
工作流 W = 节点序列 N={N(M,τ,P,F)} 由代码边 E 连接（Sec 3.1）。优化目标 W*=argmax_{W∈S} G(W,T)（式 2）。AFLOW 用 MCTS 变体，树节点 = 完整工作流（非单节点）；每轮：Select（式 3 soft mixed 概率，正文λ=0.2, α=0.4；附录交换，实际值未决）→ Expand（LLM 优化器改 prompt/代码边生成子工作流）→ Evaluate（验证集测 5 次）→ Backpropagate（记录性能与修改成败）。终止：top-k 连续 n 轮无改进或 Nmax 总轮。算子 O = 预定义节点组合（Generate/Format/Review&Revise/Ensemble/Test/Programmer/Custom）。初始化：空模板 W0，随机种子 42，验证集 20%。

## 实验
六基准 HumanEval/MBPP/MATH/GSM8K/HotpotQA/DROP。执行模型 GPT-4o-mini（主）、DeepSeek-V2.5、GPT-4o、Claude-3.5；优化器 Claude-3.5-sonnet。Nmax=20（ADAS 30）。
- 原论文报告的六基准等权平均为 80.3，对所列最强手工基线 CoT SC 的 76.0 和 ADAS 的 67.2，相对提升约为 5.7% 与 19.5%。按展示均值相减，差为 4.3 与 13.1 个分数点。各基准为 HotpotQA 73.5、DROP 80.6、HumanEval 94.7、MBPP 83.4、GSM8K 93.5、MATH 56.2。条件为 GPT-4o-mini 执行、划分后的测试集、三次测试均值，见 Table 1。前两项是 F1，中间两项是 pass@1，后两项是解题率。
- 原论文报告：AFLOW 搜出的工作流在 GPT-4o 上 HumanEval 达 96.2、Claude 95.4、DeepSeek 93.9，多数优于基线，条件：HumanEval 测试集三次平均，Table 2（"Ours*" 为 DeepSeek 搜、GPT-4o-mini 执行）。
- Appendix D 的 HumanEval 测试执行表报告，DeepSeek 执行 AFLOW(gpt-4o-mini) 的分数为 0.9390、费用为 0.0291 美元，GPT-4o IO 为 0.9389、0.6371 美元。论文正文报告费用比 4.55%，展示费用值重算约为 4.57%，差异来源尚未确定。两个分数点估计接近，统计等效仍需相应比较证据。该表费用范围为划分后测试集的执行 token 按当时模型价格折算，不含工作流搜索。

## 成本
搜索开销：Nmax=20 轮 × 每工作流验证集测 5 次（Sec 4 Evaluation）；优化器 Claude-3.5-sonnet，执行器各 API 模型。
- 原论文报告：Pareto 成本仅按测试集 token 用量计（Sec 5.1 指标 "track token usage"），离线 MCTS（20 轮×5 次验证）的一次性开销不计入该成本（未定位精确 LLM 调用总数与金额）。"回本所需任务数"未量化（未定位）。

## 证据
Sec 3.1/3.2/4；Table 1（主结果）、Table 2（跨模型）、Fig 4（Pareto 成本）、Fig 5/6（迭代曲线）、Appendix D（成本明细）。固定公开提交的选择逻辑位于 scripts/optimizer_utils/data_utils.py，第16–17行默认 alpha=0.2、lambda=0.3，第67行将得分乘以100，第78–109行先减最大得分后计算指数混合概率。ScEnsemble 与 Programmer 位于 scripts/operators.py。原论文式(3)和附录 A.6 的参数冲突及原运行配置缺口继续保留。

## 局限与风险
- 预算对等对照缺失：基线含多尝试方法（CoT SC 5 答案、MedPrompt 3 答案 5 票、Self Refine、MultiPersona），Pareto 前沿将 AFLOW 的"测试执行成本"与 GPT-4o IO 单调用比较（4.55%）。"给扁平采样器与 AFLOW 同等搜索预算、取 best-of-N"的预算对等对照：未定位——这正是本书关心的反例缺口。
- 搜索成本不计入比较：Pareto 成本只算测试推理 token，Fig 4 图注明示是划分后的测试集执行总费用，不能说成本口径不透明，也不能假定离线成本已实际摊销。包含搜索、验证与部署的全流程回本估计未定位。
- 跨模型非完全无关：Table 2 显示用 DeepSeek 搜的工作流套到 GPT-4o-mini 明显弱于用 GPT-4o-mini 本身搜的，原文自陈"不同模型需要不同工作流"，这说明相对为目标执行模型所得工作流存在下降。但迁移工作流在 GPT-4o-mini 上仍高于其 IO 基线，不能把这个差值解释成迁移后低于不更新系统。
- 评测泄漏风险：推理基准（GSM8K/MATH）与训练数据潜在重叠未讨论；独立封存集：未定位。

## 本章角色
反例（最贴近本书"演化成本与回本点"反例：用 MCTS 大量离线搜索改 G，但其成本比较只计测试推理、缺预算对等的 best-of-N 对照，且未量化回本点）。

## 可实验性
需简化（MCTS 搜索 + 多模型 API 成本高；可在 lab 用小模型与单一推理任务复现核心：代码表示工作流 + MCTS 搜边/提示 + 验证集评分，但需补"同等预算 best-of-N 对照"以回应本书反例）。

## 写作用途
支撑"更新的成本与回本点"与"收益归属"讨论——用于区分明确的测试执行成本口径与尚未回答的全流程预算问题；跨模型比较已经做过，不能写成缺失。

## 2026-09-30 16:15班原文冲突登记

本地v4 PDF第7页式(3)说明lambda=0.2、alpha=0.4，第19页附录A.6详细算法第36行却写lambda=0.4、alpha=0.2。前者是均匀混合权重，后者是分数指数系数，不能互换后假装同一设置。当前未核对固定执行代码/原始配置，因此实际运行值未决；正文第9章已明确保留冲突。
