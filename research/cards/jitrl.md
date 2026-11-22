# JitRL（arXiv:2601.18510v3）

## 来源
标题：Just-In-Time Reinforcement Learning: Continual Learning in LLM Agents Without Gradient Updates；作者：Yibo Li, Zijie Lin, Ailin Deng, Xuan Zhang, Yufei He, Shuo Ji, Tri Cao, Bryan Hooi（National University of Singapore）；年份：2026（ICML 2026）；版本：arXiv:2601.18510v3（2026-06-08）；URL：https://arxiv.org/abs/2601.18510v3；代码：https://github.com/liushiliushi/JitRL；代码提交号：未定位。

## 研究问题
解决部署后权重冻结的智能体无法持续适应、且常规 RL 成本高且易灾难性遗忘的问题（§1：frozen weights、prohibitive computational costs、catastrophic forgetting）。关键信息难文本化的任务（空间推理、时序预测）明确不在实验范围内（§Limitations）。

## 六问定位
- 改什么：运行时策略 π 的 logit 偏置（非 θ/P/M/L/G 任一持久组件）。记忆 M 作为非参经验库跨 episode 累积，写入/检索规则固定；θ 冻结不等于没有持久组件更新。是否跨新任务应按具体实验协议检查。
- 根据什么改：环境结果。LLM 评估器从完成轨迹生成逐步奖励 rt，折扣为 Gt（§4.1）。主信号：环境结果（轨迹反馈 → 逐步奖励 → 折扣回报）。
- 怎样改：强化学习（无梯度；KL 约束策略优化的闭式解，logit 加法更新，§4.3 / Theorem 4.1）。
- 什么时候改：任务后（每 episode 结束写入经验三元组）＋任务中（每步检索并调制 logits，§4.1–§4.3）。
- 保留什么：Algorithm 1 把 M 初始化放在 episode 循环之外。WebArena 每题有5次尝试，不能把跨 episode 无条件等同跨新题；Table 5 冷启动只用不相交任务的记忆，另行提供跨任务使用证据。logit 偏置为当前动作决策量，持久内容是 M；固定记忆操作仍可以产生持久更新。
- 怎样检验：WebArena 每题5次尝试，Avg 与 Final 分别表示全部尝试平均和末次表现。Table 2 的 WebArena-Lite 留出是相对 WebRL 训练数据而言，不能据此说 JitRL 从未在评价题上适应。跨任务冷启动见 Table 5；跨 backbone 见 Table 4。

## 机制
- 记忆构造：动态非参记忆 M={(si,ai,Gi)}，Gi 为 (si,ai) 后累积折扣回报；每 episode 结束由 LLM Evaluator 生成逐步奖励 rt（映射 E:τ→{rt}），Gt=Σγ^(u-t)ru（式(3)）；原始状态抽象为紧凑 st（§4.1）。
- 测试时价值估计：检索 top-k 近邻 N(s)；bV(s)=平均 Gi（式(4)）；bQ(s,a) 已知动作取回报均值（式(5)），未见动作取乐观 bonus（式(6)）；bA(s,a)=bQ−bV（式(7)）（§4.2）。
- 策略更新：KL 约束优化 π*=argmax E_a[Â]−(1/β)DKL(π'||πθ)（式(8)）；闭式解 π*(a|s)∝πθ(a|s)exp(βA)（式(9)）；映射至 logit：z'(s,a)=z(s,a)+β·bA(s,a)（式(10)）（§4.3）。
- 它把什么当"策略"：被冻结 base model 的动作分布 πθ（候选动作由 base model 产出），经 logit 加法偏置后恢复为最优策略 π*；即 RL 学的是"任务策略（选哪个动作）"，而非记忆操作（§4.3 / Related Work "treats memory as a non-parametric policy distribution... soft updates directly on the LLM's logits"）。
- 经验条目如何变成 logit 偏置：存储的 (st,at,Gt) 经检索得 bA(s,a)，再按式(10) 加到 base logits；未知动作初始化 z=0（App F）。
- 闭式解约束：KL 散度约束于冻结参考策略 πθ（β 为温度），证明为 KL 约束优势最大化的精确闭式解（Theorem 4.1）；非平稳策略下价值/优势估计一致性见 Theorem 4.2 / 4.3。
- 记忆操作是否被学习：否。写入=存三元组（固定）、检索=Jaccard/向量相似度（固定，式(24)/App F）、价值估计=回报均值（固定式(4)–(5)）、遗忘=未定位（原文未给显式遗忘机制，仅靠记忆增长与探索 bonus 自然偏移）。RL 仅用于任务策略 logit 调制。
- 拟合目标：记忆内容 (st,at,Gt) 拟合到问题域（环境动态的经验回报分布，§4.1 "capturing the environment's empirical distribution"）；但 logit 调制目标依赖冻结求解器的候选集，换 base model 后偏置作用域变化（§Limitations "re-weights actions over the candidate set proposed by the base model"）。

## 实验
- 基础模型：训练免费方法用 Gemini-2.5-flash；对比 WebRL/SFT 用 Llama-3.1-70B-Instruct、GRPO 用 Qwen3-32B；任务集：WebArena（L=5 episode）、Jericho（Library/Zork1/Zork3，50 episode）。
- 原论文报告：JitRL 在 WebArena 微平均 Success Rate Avg=46.98、Final=51.35，超过 Reflexion 42.12、AWM 40.32、Memory 43.00，条件：WebArena 五网站 × L=5 episode + Gemini-2.5-flash（Table 1, §5.2.1）。
- 原论文报告：WebArena-Lite held-out 上 JitRL 平均 60.00，超过 WebRL 46.06 与 SFT 23.00，条件：WebArena-Lite（其余 WebArena 用于训练 WebRL）+ 同评估环境（Table 2, §5.2.1）。
- 原论文报告：Jericho 上 JitRL Library Avg=25.9/Final=30、Zork1 Avg=53.0/Final=69、Zork3 Avg=3.1/Final=5，超过 GRPO 与各训练免费基线，条件：Jericho 三游戏 × 50 episode（Table 3, §5.2.2）。
- 原论文报告：跨 backbone GPT-5-mini / DeepSeek-V3.2 下 JitRL 多数居首，条件：WebArena Admin+Reddit + 两 backbone（Table 4, §5.3）。

## 成本
- 固定v3表9报告JitRL约 $290 的API运行费用，并列WebRL约 $9,900 的GPU训练周期费用估算。正文据此报告大于30倍的金额差异。两项的计价基础与覆盖阶段分别见§5.7及Appendix R，使用时需保留该比较范围。
- 训练：无梯度更新；评测用 Gemini-2.5-flash 等 API（§5.1）。

## 证据
- 非参记忆 + logit 调制框架：§4 / Fig 2 / Related Work（"treats memory as a non-parametric policy distribution... soft updates directly on the LLM's logits"）。
- 闭式解证明：§4.3 Theorem 4.1、App B 推导、Eq(8)(9)(10)。
- 任务策略被学、记忆操作未被学：§4.1（存储三元组固定）、§4.2（检索/均值固定）、§4.3（logit 更新仅作用于动作分布）、§Limitations（依赖 base model 候选集）。
- 收益来源比较：Table 8 使用相同记忆检索结果比较 Logit Update 与 Prompt Update，为该设置下两种利用方式的差异提供证据；不能外推为所有任务中唯一的增益来源。
- 代码路径：未定位（仅仓库 URL）。

## 局限与风险
- 依赖冻结 base model 候选集，无法发现 base model 不会生成的动作（§Limitations）。
- 依赖 LLM 评估器给准确逐步奖励；信用分配错误会污染优势估计（§Limitations）。
- 不适于关键信息难文本化的任务（空间推理、时序预测）（§Limitations）。
- 评测泄漏风险：未定位。
- 记忆操作未被学习：写入/检索/价值估计均为固定规则，本书谱系中"记忆操作的学习化"仍处规则档（见本章角色）。

## 本章角色
反例（用于澄清谱系边界：RL 被用于"任务策略"而非"记忆操作"，记忆操作仍为固定规则；本书用它防止把"用了 RL"误归为"RL 增强演化层"）。

## 可实验性
可另行设计简化实现；需要确认候选动作、评分或 logit 接口、检索与奖励构造均能复现。现有通用文本 API 可用，不代表已经具备论文所需控制接口；本书未运行该方法。

## 写作用途
支撑第 6 章谱系边界判断——证明"用 RL"不等于"学记忆操作"，JitRL 把 RL 用在任务策略上，记忆操作仍属规则档。

## 2026-10-02 02:xx 班来源核验（Hy3 · R3）

本地 PDF `references/files/papers/jitrl__2601.18510.pdf`（27 页）全文抽取（pypdf），关键数字逐项命中：
- WebArena（Table 1, p6）：JitRL Avg **46.98**/Final **51.35**，超 Reflexion **42.12**/AWM **40.32**/Memory **43.00**。
- WebArena-Lite（Table 2, p6）：JitRL 平均 **60.00**，超 WebRL **46.06**/SFT **23.00**。
- Jericho（Table 3, p6）：Library Avg **25.9**/Final 30、Zork1 Avg **53.0**/Final **69**、Zork3 Avg **3.1**/Final **5**。
- 成本（Table 9, p8）：JitRL 约 **$290**，WebRL 约 **$9,900**，节省 >**30×**。
- 与卡中全部报告值**全一致，无差异**。
原论文页/表：Table 1（p6）、Table 2（p6）、Table 3（p6）、Table 9（p8）；§4–§5。
正文落点：ch01:522、ch05:352、ch06:188/209/239/242/319/322/349/600/634/644/673。
关闭本卡 R3（Hy3 一手核验，非独立人类评审）。
