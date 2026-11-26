# 公开预览的材料与复算

E01、E02 的汇总沿用原件。E03 拆分 A 的汇总及检查点记为 72/80，保存轨迹的逐次判定合计为 70/80。两者冲突仍待裁定，依赖该基线的收益与成本效率比较继续暂停。十条历史命题均为 open。E03v2 只取得离线工件证据。

E03 公开汇总中的两段错误回溯以 <TEMP>/ 代替用户临时目录，保留测试文件名和其余文本。这个副本可复算判定计数与成本。研究原始记忆文本的长度、字符相似度或逐字节身份时需要私有原件。inputs.json 分别记录原件与公开副本的 SHA-256 和修改的字段；读取器校验公开副本的实际字节。E12 节选只把来源位置改写为库内相对路径。

E03-provenance-audit.json 和 E03-record-index.csv 供查阅原始审计及轨迹标识。此包仅含选定的轨迹，原始 SHA 用于识别档案。完整运行档案与维护记录由作者另外保存。以下命令从解压根目录运行，部分入口会在解压目录生成派生文件；建议保留初始 ZIP 供复核。

从仓库根目录运行以下命令，可用 XeLaTeX 从保存的数据重绘第 4 章的五组配对差与区间、第 8 章的教学成本曲线。请选择尚不存在的输出目录。已经排版的两张原图随书提供。

~~~text
python calculations/redraw_quantitative_figures.py --out-dir ../redrawn-figures
~~~

experiments/protocols/ 中的协议记录设计当时的计划。E05v2 后来完成了一次小规模装置检查，覆盖一个任务族的两道训练题，封存集未评价。当前入口的执行条件见首页。任务规格可离线生成；固定脚本与预期文本的比较只用于核对流程。

E05 v3 协议提到的 v2 试跑报告和 v3 运行脚本保存在完整维护档案中。读者可打开 [E05 v2 的六份序列记录](../experiments/runs/E05v2-20260929T143245Z-d7a8db/sequences/)，从每个 `complete.json` 的 `events` 找到对应轨迹。在源码包根目录运行 `python calculations/reproduce_skill_audit.py`，即可核对九个回合的验收、参考注入和调用数，并按原配置校验 14 份历史源码及协议快照。

可靠性审计把权限观察与记账节选当作历史证据读取。构建任务目录后可使用 E11/E12 默认入口查看本机生成的离线清单。附录 D 分别标出了随包命令和需要完整实验档案的命令。

~~~text
python calculations/compare_e03_baseline.py
python experiments/lab/eval.py --selftest
python -m unittest experiments.lab.test_eval_pairing -v
python calculations/reproduce_platform_appendices.py
python calculations/reproduce_rl_arithmetic.py
python calculations/reproduce_workflow_arithmetic.py
python calculations/reproduce_parameter_arithmetic.py
python calculations/reproduce_memory_operations.py
python -m unittest calculations.test_ch06_operation_demo
python calculations/reproduce_appendix_a.py -o analysis/appendix-a-export-check.json
python calculations/reproduce_ch15_case.py -o analysis/ch15-export-check.json
python calculations/reproduce_timing_audit.py
python experiments/lab/trigger_signals.py --run E01-20260923T152230Z-90acda
python -m unittest experiments.lab.test_e11_timing_v2 -v
python calculations/reproduce_reliability_audit.py
python calculations/audit_ch14_cosine_bound.py
python calculations/audit_sample_size.py
python -m unittest experiments.lab.test_e01_v2_token_wallclock -v
python -m experiments.lab.build_taskset --no-lab-run
python -m experiments.lab.run_e11_v2
python -m experiments.lab.run_e12_v2
python calculations/reproduce_context_audit.py
python calculations/reproduce_skill_audit.py
~~~

第13章时机复算从8个训练轨迹读取初始系统提示，再从 `analysis/e01-grid4-prompt-index.csv` 的80行复算封存题中各条经验的出现次数。每行含题号、重复序号、两个从0起的经验编号及原始轨迹摘要值。读者包还保留一份可直接核对的封存轨迹，完整的八十份原件保存在维护档案。给时机复算命令加 `--output 新文件.json` 可将结果另存。

### 核对第 9 章 AFlow 测试文件

前面的工作流算术可以直接运行。要核对表中“档案复算”一行，还需取得作者发布的 `results.tar.gz`。将该文件放在当前目录，或在命令中给出其实际路径。[AFlow 作者公布的下载入口](https://github.com/FoundationAgents/AFlow/blob/3f457218fc716093fe53f6df8a5d5e6379d66346/README.md#reproduce-the-results-in-the-paper)

~~~text
python calculations/reproduce_workflow_arithmetic.py --aflow-archive results.tar.gz -o analysis/aflow-archive-check.json
~~~

输出文件须使用新文件名。入口按 SHA-256 核对作者档案，在压缩包内逐行读取 18 份测试目录 CSV，记录每份文件的题行数、得分总和与题目标识摘要，并用验证文件核对 MATH 重复项。表中每个可计算的档案均值对三次运行等权，MATH 留空。HumanEval 另列每次运行的最大累计费用。核对过程在本机进行。

报告中的 `aflow_archive.answer_score_check` 汇总了三项能从存档答文重算的测试。DROP 以竖线拆开参考答案与预测，取所有组合中最高的词元 F1。HotpotQA 用完整预测计算词元 F1。GSM8K 取预测中的最后一个数，与参考数的绝对误差不超过 0.000001 即得分。固定归档中三项分别有 2,400、2,400 和 3,165 条记录，共 7,965 条。每份文件的 `answer_score_check` 给出 `matching_rows`、`rows`、允许的得分误差（绝对值 10⁻¹²）与超差记录号。这里核的是 AFlow 当时保存答案的评分规则。[同期评测实现](https://github.com/FoundationAgents/MetaGPT/tree/39ae68225b06472b9b1377603e255d20aee5560d/metagpt/ext/aflow/benchmark)

要找第 9 章的两个姓名例子，可在 DROP 各文件下看 `multiple_prediction_full_credit_csv_records`。它列出含两个或更多不同的非空预测、且重算取得满分的记录。文件名排序后的前两份都有第 757 条。这里将表头计为第 1 条，一条引号内的题文可以跨多行。

### 核对第 10 章 SEAL 连续编辑热图

取作者固定版本中整个 `continual_self_edits` 结果目录，保留八个运行子目录及总汇总的相对位置。下面假定它位于当前目录。[作者发布的九份汇总](https://github.com/Continual-Intelligence/SEAL/tree/6d9c9f9ee392c6cc618e771f399d436d190f6ca4/general-knowledge/results/continual_self_edits)

~~~text
python calculations/reproduce_parameter_arithmetic.py --seal-results continual_self_edits -o analysis/seal-cells.json
~~~

程序核对九份输入的内容后，按材料位置计算 44 个已观察格的均值、组内标准差的算术平均及合并样本方差所得的标准误。首轮编辑前评价全部八个位置，此后只计算已经学习的位置。输出另存为新文件。

### 核对第 13 章 D-MEM 的带噪问答

从作者发布的固定版本取三个 JSON 文件。一个是 LoCoMo 原数据，另两个是带噪问答的 A-MEM 与 D-MEM 输出。为缩短命令，分别保存为 `locomo10.json`、`amem.json`、`dmem.json`，保留下载内容。程序会核对三份文件的 SHA-256。[LoCoMo 原数据](https://github.com/snap-research/locomo/blob/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376/data/locomo10.json) · [A-MEM 输出](https://github.com/london-and-tequila/dmem/blob/68410d0568b2ccbdc859f451c3494a72e814c505/results/dmem/eval_a-mem_gpt-4o-mini_noise75_gpt-4o-mini_0313_0925.json) · [D-MEM 输出](https://github.com/london-and-tequila/dmem/blob/68410d0568b2ccbdc859f451c3494a72e814c505/results/dmem/eval_d-mem_gpt-4o-mini_noise75_gpt-4o-mini_0313_1713.json)

~~~text
python calculations/reproduce_dmem_table1.py --locomo locomo10.json --a-mem amem.json --d-mem dmem.json
~~~

默认将报告写到终端。程序按同一组题比对题类、预测与参考答案，分别给出归档评分和 47 道对抗题的拒答短语命中数。两种方法的回答都来自作者归档。
