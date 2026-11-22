# Mem-α（MEM-α，arXiv:2509.25911v1）

## 来源
标题：MEM-α: Learning Memory Construction via Reinforcement Learning
作者：Yu Wang, Ryuichi Takanobu, Zhiqi Liang, Yuzhen Mao, Yuanzhe Hu, Julian McAuley, Xiaojian Wu（Anuttacon、UCSD、Stanford）
年份：2025（arXiv:2509.25911v1，2025-09-30）
URL：https://arxiv.org/abs/2509.25911
公开代码固定为 `9c0e1f6482f8ea7a322012a8155247966285946f`。2026年11月16日复核，官方 main 仍指向该提交。原表的训练命令、合并配置与检查点绑定尚待补齐。

## 研究问题
现有记忆增强 agent 依赖预定义指令与固定工具，模型缺乏"存什么、如何结构化、何时更新"的能力（Introduction，行 17–53）。
Mem-α 用 RL 让 agent 通过交互与反馈学习记忆构建策略，并显式排除 Conflict Resolution 维度（Section 3.4，行 348–351）。

## 六问定位
- 改什么：训练更新θ中的记忆构建策略，运行时策略操作M；记忆架构含 core/episodic/semantic 三组件，但架构与 RL 解耦、可替换（Section 3.3，行 336–339）。学到的是"写入哪些记忆、如何组织"，而非记忆结构本身。
- 根据什么改：环境结果；主信号是下游 QA 正确率奖励 r1，由固定的解耦 RAG 管线（BM25 + 冻结 Qwen3-32B 生成器）计算（Section 3.1.2、3.1.3）。
- 怎样改：原文采用 GRPO，并描述去掉 KL 项以鼓励探索（Section 3.2）。固定公开4B训练脚本显式开启系数0.001的策略 KL 损失，默认训练配置关闭奖励侧 KL，策略更新代码将 KL 项加入损失。原表所用的有效配置仍待原始运行绑定。
- 什么时候改：任务后（离线 RL 微调）；按信息块顺序逐步写入记忆（Section 3.1.1）。
- 保留什么：微调后的策略参数 θ 持久化（version 层）；最终记忆 Mn 为 episode 内产物。
- 怎样检验：同分布验证集（Table 1）+ MemoryAgentBench 分布外测试集（Table 2）；长度泛化到 400k+ token 作为额外检验。

## 机制
任务设定：agent 顺序处理对话块 C={c1..cn}，步 t 可发出写操作序列 a_t=(a1..aKt)，动作集 A_write={memory insert, memory update, memory delete}，参数含 record id、memory type、content（Section 3.1.1）。
记忆实例化三组件：Core（≤512 token，仅整体重写）、Semantic（事实列表，支持 insert/update/delete）、Episodic（带时间戳事件，支持 insert/update/delete）（Section 3.3）。
奖励 rt = r1 + r2,t + βr3 + γr4：r1 正确率（全局）、r2 工具格式、r3 压缩（1−lm/lc）、r4 记忆内容合法性（Qwen3-32B 评判）（Section 3.1.2）。
原文主实验写 β=0.05、γ=1（Section 4.1，原PDF第7页），消融默认写 β=0.05、γ=0.1（Section 4.4，第8页）。固定公开4B脚本显式传递压缩系数0.05与内容系数0.1，奖励管理器将它们乘到相应分项。该脚本解释当前可读实现，原表的历史系数继续待核。
策略优化按原文用 GRPO。KL的论文描述与公开配置分别按上述来源读取。

## 实验
基础模型：Qwen3-4B（主），训练于 32×H100、lr 1e-6、batch 32、grpo n=8、3 天、205 步（Section 4.1，行 495–497）。
训练数据：4,139 实例经分层抽样得 562（Table 6、Table 7）。
验证任务集为SQuAD、HotpotQA、PerLTQA、TREC-C、NLU、PubMed、BookSum七集（Table 1）。LME(S)属于另组测试任务（Table 2）。
测试任务集：MemoryAgentBench 九集，含 RULER-QA、InfBench-Sum、LongMemEval 等（Table 2、Table 8）。
固定v1的Table 1均值字段为0.642。作者2025年10月29日在[官方更正](https://github.com/wangyu-ustc/Mem-alpha/issues/4#issuecomment-3461913009)中将验证集训练版均值改为0.619，按七个数据集等权平均。原PDF字段与作者更正各自保留来源身份。
原论文报告：0.592（测试集平均），条件：MemoryAgentBench 测试集 + Qwen3-4B，见 Table 2。
固定v1 Table 3的未微调基座均值字段为0.389，按其七个显示列复算为0.3914。上述作者更正未单列这一行，原始未舍入分项和汇总身份仍待核，不据这两个口径构造新的训练增益。
原论文报告：训练最大 30k token、泛化到 >400k（Multi-Doc 最高 474K），条件：MemoryAgentBench 长文档，见 Abstract 与 Section 4.2（行 513–515）。

## 成本
训练：32× H100 GPU、约 3 天、205 步、batch 32、grpo rollout n=8、lr 1e-6（Section 4.1，行 495–497）。
评测：BM25 检索 + 冻结 Qwen3-32B 生成器；各方法记忆 token 占用见 Table 1/2/3。
成本覆盖：上列训练与评测配置属于Mem-α，不混入DGM分阶段评测规模；端到端美元总账未定位。

## 证据
节号：Section 3.1.1（任务设定）、3.1.2（奖励）、3.1.3（RAG 评测）、3.2（GRPO）、3.3（记忆实例化）、3.4（训练数据）、4.1（设定）、4.2（主结果）、4.3（RL 增益）、4.4（消融）。
表号/图号：Table 1（验证）、Table 2（测试）、Table 3（RL 增益）、Table 4（超参消融）、Table 6/7（训练统计）、Table 8（测试统计）、Figure 3（记忆架构）。
固定公开实现见 `scripts/train_memory_grpo_qwen3-4b-4node-compression0.05-content0.1.sh`、`verl/workers/reward_manager/naive.py` 与 `verl/workers/actor/dp_actor.py`。完整提交为 `9c0e1f6482f8ea7a322012a8155247966285946f`。本轮只读代码与公开说明，未运行模型训练，原始有效配置和训练日志绑定继续待核。

## 局限与风险
显式排除 Conflict Resolution 维度，因缺少真实评测基准（Section 3.4，行 348–351）。
训练数据受算力限制，每数据集上限约 100 实例（Appendix A，行 1452–1456）。
r4 由 Qwen3-32B 作内容评判，存在评判器偏差，原文未专门讨论 reward hacking。
评测泄漏风险：r1 正确率奖励与最终报告共用 BM25+Qwen3-32B 口径；同分布验证集可能高估，长度泛化测试仍属 MemoryAgentBench 同类基准。

## 本章角色
第6章训练记忆构建策略的实例。架构及接口由设计者提供，RL学习的是给定接口下的策略；不能将其表述为结构本身被学习，或把谱系档位称为普遍能力排名。

## 可实验性
需简化（需解耦 RAG 评测管线 + 三组件记忆架构 + GRPO 训练，难以在本仓库轻量复现）。

## 写作用途
支撑在指定架构与工具接口上训练记忆构建策略；不称记忆结构或全部规则均被学习。长度泛化的具体成绩和范围按原表报告。

## 2026-10-02 02:xx 班来源核验（Hy3 · R3）

本地 PDF `references/files/papers/mem-alpha__2509.25911.pdf`（22 页）全文抽取（pypdf），关键数字逐项命中：
- 验证集平均 **0.642**（Table 1, p7/8/9）、测试集平均 **0.592**（Table 2, p8/21）、无 RL 基座 **0.389**（Table 3, p7/8）；长度泛化 >**400k**（Abstract p1/2、§4.2 p7，Multi-Doc 最高 **474K** p7/8）。
- 训练数据 **4,139** 抽样得 **562**（Table 6/7, p6/7/14）；**32×H100**、**205** 步、lr **1e-6**（§4.1, p7）；β=**0.05**/γ=**1**（p7/8/9/21）。
- γ 冲突：主实验 p7 写 γ=1、消融 p8 写默认 γ=0.1（均配合 β=0.05）—— 与本书 ch06:600 登记的“权重冲突复现待核项”一致，卡已如实保留。
- 与卡中数值**全一致，无差异**。
原论文页/表：Table 1（p7）、Table 2（p8）、Table 3（p7）、Table 6/7（p6/7/14）、§4.1（p7）、Abstract（p1/2）。
正文落点：ch05:702、ch06:188/209/210/319/322/349/600/634/685。
关闭本卡 R3（Hy3 一手核验，非独立人类评审）。
