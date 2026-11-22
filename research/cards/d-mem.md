# D-MEM（arXiv:2603.14597v1）

## 来源
标题：D-MEM: Dopamine-Gated Agentic Memory via Reward Prediction Error Routing；作者：Yuru Song（UC San Diego）、Qi Xin（Carnegie Mellon University）；年份：2026；版本：arXiv:2603.14597v1 [q-bio.NC]（2026-03-15）；URL：https://arxiv.org/abs/2603.14597；代码：https://github.com/london-and-tequila/dmem（摘要给出仓库地址）；代码快照固定为 `68410d0568b2ccbdc859f451c3494a72e814c505`，公开结果自报的执行提交解析为 `e6f4043daf099cfb39263c865972661d89e5a44b`。
元数据与固定 v1 的 15 页原文已核对。代码只读检查覆盖噪声构造、会话展开、缓存计量与结果导出，公开 JSON 已按固定快照独立重计。模型复现状态为未运行。

## 研究问题
解决"append-and-evolve-all"式长期记忆系统（以 A-MEM 为代表）的规模瓶颈：把每条用户话语都送进昂贵的 $O(N^2)$ 记忆演化管线，带来严重写入延迟、无界 API token 成本与噪声导致的上下文污染（Abstract、§1、§3.2）。目标是用生物启发的快/慢路由，只在信息价值足够时才触发深度演化。噪声条件下的鲁棒评估由本文自建基准 LoCoMo-Noise 承担（§2）。

## 六问定位
- 改什么：记忆 M 的写入/演化触发与结构化重构（活动知识图），以及一个 $O(1)$ 快速缓冲；不训练持久策略参数（推理器/基座冻结）。属本书谱系"把最贵动作变成可观测门"的**规则档触发门**。
- 根据什么改：启发式路由分数（自称"智能体版 RPE"）——输入语义 Surprise 与长期 Utility 的阈值判据（§4.1–§4.2）。主信号是启发式分数本身，不是学习到的价值函数。
- 怎样改：规则门（阈值路由）。无梯度、无策略训练；按阈值分入三个离散档位。
- 什么时候改：任务中/逐轮（每条用户话语在线评估）；高 RPE 输入才触发慢路（§4.2）。
- 保留什么：知识图（活动记忆）跨会话累积；低 RPE 输入或旁路、或进 STM 缓冲（§4.2–§4.3）。
- 怎样检验：LoCoMo-Noise（$\rho=0.75$）上的长期记忆准确性（Table 1）与 token 效率（§5.2）；路由行为分析（§6.1）。

## 机制
- 快/慢解耦（§4）：一个轻量、并行的 Critic Router 计算每条输入的 Agentic RPE，充当"多巴胺门"。
- RPE 分数（§4.1，p.5）：
  $RPE(x_t)=\min\big(1.0,\ \mathbb I(\mathrm{Utility}(x_t)\ge\tau)\cdot[\mathrm{Utility}(x_t)\times(\mathrm{Surprise}(x_t)+\beta)]\big)$
  $\mathbb I(\cdot)$ 为硬效用阈值 $\tau$ 的指示函数；Utility 低于 $\tau$ 时 RPE 严格短路为零，"丢弃高惊喜但无意义"的对话噪声。$\beta$ 为"效用安全网"（原文例 $\beta=0.4$），保证高价值但预期中的输入（Surprise≈0）仍有足以触发短期记忆构建的基线 RPE。
- 语义惊异（§4.1，p.5–6）：$S_{raw}(x_t)=\max_{m_i\in M}\cos(E(x_t),E(m_i))$；为对抗嵌入各向异性，用最近 $k$ 个相似度维持滑窗均值 $\mu_{sim}$ 与标准差 $\sigma_{sim}$，做 Z-score 归一再过 sigmoid：$\mathrm{Surprise}(x_t)=\sigma\big((\mu_{sim}-S_{raw})/\max(\sigma_{sim},\epsilon)\big)$。该步骤无额外 LLM 开销。注意：这是生物启发的触发门分数，**不是**标准时序差分误差。
- 长期效用（§4.1，p.6）：用受约束的轻量 LLM 调用（最小 JSON schema）做生命周期分类——Transient（零信息寒暄/瞬时状态，强制 $\mathrm{Utility}=0$）/ Short-Term（天到周）/ Persistent（月到永久）。
- 常规分层路由（§4.2，p.6，warmup 例外见后）：阈值 $\theta_{low}=0.3$、$\theta_{high}=0.7$ 分三档——SKIP（$RPE<\theta_{low}$，跳过主记忆构建与演化，原始文本仍写入 Shadow Buffer）/ CONSTRUCT_ONLY（$\theta_{low}\le RPE<\theta_{high}$，做节点构建并存进 $O(1)$ 的 STM 缓冲）/ FULL_EVOLUTION（$RPE\ge\theta_{high}$，"多巴胺释放"，激活 $O(N)$ 深度重构，稀疏执行）。
- 无额外 LLM token 的检索增强（§4.3，p.6–7）：并行一个轻量 BM25 稀疏索引，用 Reciprocal Rank Fusion 与向量索引融合；并维护 $O(1)$ 的 Shadow Buffer（FIFO 双端队列），把被 SKIP 的输入原样存入，供低置信检索时的两段式回退，防对抗性"失忆"。
- 冷启动（§4.2 末，p.6）：$t<N_{warmup}$ 时记忆稀疏会迫使 $\mathrm{Surprise}\to1.0$；为防寒暄触发昂贵 FULL_EVOLUTION，前 $N_{warmup}$ 轮所有超过 $\theta_{low}$ 的输入一律强制进 CONSTRUCT_ONLY。

## 实验
- 基准：LoCoMo-Noise（本文提出，§2.2，p.3 / Fig 1）：原始 LoCoMo 会话作事实"针"（位置严格保留）→ GPT-4o-mini 合成三类噪声（Phatic Fillers 40% / Status Updates 30% / Tangent Remarks 30%）→ 按噪声比 $\rho$ 均匀随机交错插入；主评估保留原文配置标记 $\rho=0.75$，其新增噪声比与最终噪声占比的分母表述存在冲突，实际噪声占比仍待原运行核对。
- 基础模型：GPT-4o-mini（主表）。
- 原论文报告（Table 1，p.7；$\rho=0.75$，GPT-4o-mini）：A-MEM（同步）Overall F1 0.336 / Single 0.208 / Temp 0.408 / Open 0.111 / Multi 0.365 / Adv 0.388 / 总 token 1,648K；D-MEM 0.369 / 0.246 / 0.440 / 0.085 / 0.412 / 0.412 / 319K（−80%）。
- 原论文报告（Table 2，p.12，干净 LoCoMo，199 题，F1/BLEU-1 %）：A-MEM Overall 35.94、Single 44.7、Multi 27.0；D-MEM Overall 37.4/31.2、Single 21.6/16.4、Multi 42.7/31.9（Multi-hop 高出 A-MEM 15.7 个百分点）；D-MEM Open-domain 呈现 F1 10.4 而 BLEU-1 33.7 的落差。
- 原论文报告（Table 3，p.15，消融，$\rho=0.75$）：v1（线性 RPE，跳过率 9.6%，489K）/ v2（严格剪枝，$\beta=0.1$，跳过率 68.5%，Overall 0.291，497K）/ v3（效用安全网，$\beta=0.4$，跳过率 41.1%，531K）/ v4（Final，加 BM25+Shadow Buffer，跳过率 41.1%，319K）。
- 路由图文尚未对齐。§6.1 正文与 Fig 3 图注把真实对话轮跳过率写为 53.9%，注入噪声轮为 43.2%。Fig 3(b) 柱图却将真实轮 SKIP 标为 39.6%，53.9% 标在 CONSTRUCT 柱上，噪声轮 SKIP 仍为 43.2%（noise n=308，real n=419）。实际跳过率及两类输入的比较方向须由原始路由记录核对。Fig 3(a) 中的 SKIP 决策位于低 Utility 区，按该图示范围解释。
- 本节数字均为引用；本书未复现该方法。

## 成本
- 原论文 Table 1 在 $\rho=0.75$ 配置下报告总 token 从 1,648K 降到 319K。公开归档的 A-MEM 记录含 1,102,209 个记忆摄入 token，最终 D-MEM 的 727 轮摄入均计 0，总账为 318,810 token 与 call_count=199。两份结果的元数据均记录启用缓存，所指提交的代码在缓存命中时直接返回旧响应。call_count 在存在 usage 时递增，单题问答还包含查询生成，逐请求归属仍待核。该报告差额不能单独确立从空缓存完整建库的费用降幅，需补齐匹配缓存与初始化条件的计量。
- 原论文报告（§7）：D-MEM 自身仍引入一个轻量 LLM Utility 分类器的每轮开销，作者提出用知识蒸馏或纯嵌入估计器消除。
- 训练：无梯度更新（纯规则路由）。

## 证据
- 机制：§4.1（RPE 公式、语义惊异、效用分类）、§4.2（Critic Router、分层路由阈值、冷启动）、§4.3（BM25/RRF、Shadow Buffer）；页码 p.5–7。
- 数字据 Table 1（p.7，§5.2）、Table 2（p.12，§A.1）与 Table 3（p.15，Appendix B）核对。图示见 Fig 2（p.8，RPE 分档分解）、Fig 3（p.9，§6.1）、Fig 4（p.13）与 Fig 5（p.14）。
- 基准：§2.2（p.3，噪声注入方法）、Fig 1（p.3）。
- 固定原文为 `references/files/papers/d-mem__2603.14597.pdf`（15 页，v1）。公开仓库 https://github.com/london-and-tequila/dmem 已固定到 `68410d0568b2ccbdc859f451c3494a72e814c505`，逐文件 Git blob 与 SHA-256 清单、执行版本绑定和独立重计保存在本轮来源支持工件中。

## 局限与风险
- 原论文自陈（§7，p.9）：①LoCoMo-Noise 的噪声分布（40% Filler / 30% Status / 30% Tangent）是对真实对话动态的受控近似，非自然噪声；②单跳检索不及 A-MEM（干净 LoCoMo 上 21.6 vs 44.7），因 $\theta_{low}=0.3$ 为最大化 75% 噪声下效率而偏激进，作者建议降到 0.2 或动态控制器；③Utility 分类器每轮仍有 LLM 开销；④多智能体共享记忆图为未来工作。
- 名称风险：把该分数称为"奖励预测误差"提示了生物灵感，但它由效用、惊异与阈值构成启发式路由规则，不估计某个策略的价值函数；不能仅凭名称声称它已估计价值。
- 外推风险：本文对 A-MEM 的 $O(N^2)$ 描述是针对特定实现/负载的报告，不能据此断言所有 A-MEM 实现的单次写入都是 $O(N^2)$（渐近复杂度≠实测延迟）。
- 评测泄漏风险：未定位。

## 本章角色
对照（规则门 / 触发门）。用于把"何时演化"变成一道可观测的门，并给出可测中间量"演化触发率"；在本书中作为学习策略的对照而非其下位替代。

## 可实验性
其"触发门 + 分档路由"抽象可在 `experiments/lab` 离线复现为纯规则门对照（不调用模型时可用确定性代理替换 Utility/Surprise 打分）；完整复现需嵌入与 LLM 打分接口。本书未运行该方法。

## 写作用途
支撑第 6 章"规则门是强化学习的对照，不是它的下位替代"与§6.6"触发门的收益要从门前开始计算"，以及第 13 章 §13.3"Gate 自己也是一次决策：阈值两侧的代价"。
