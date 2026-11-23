# 公开预览的材料与复算

E01、E02 的汇总沿用原件。E03 拆分 A 的汇总及检查点记为 72/80，保存轨迹的逐次判定合计为 70/80。两者冲突仍待裁定，依赖该基线的收益与成本效率比较继续暂停。十条历史命题均为 open。E03v2 只取得离线工件证据。

E03 公开汇总中的两段错误回溯以 <TEMP>/ 代替用户临时目录，保留测试文件名和其余文本。这个副本可复算判定计数与成本。研究原始记忆文本的长度、字符相似度或逐字节身份时需要私有原件。inputs.json 分别记录原件与公开副本的 SHA-256 和修改的字段；读取器校验公开副本的实际字节。E12 节选只把来源位置改写为库内相对路径。

E03-provenance-audit.json 和 E03-record-index.csv 供查阅原始审计及轨迹标识。此包仅含选定的轨迹，原始 SHA 用于识别档案。完整运行档案与维护记录由作者另外保存。以下命令从解压根目录运行，部分入口会在解压目录生成派生文件；建议保留初始 ZIP 供复核。

从仓库根目录运行以下命令，可用 XeLaTeX 从保存的数据重绘第 4 章的五组配对差与区间、第 8 章的教学成本曲线。请选择尚不存在的输出目录。已经排版的两张原图随书提供。

~~~text
python calculations/redraw_quantitative_figures.py --out-dir ../redrawn-figures
~~~

experiments/protocols/ 中的协议记录设计当时的计划。E05v2 后来完成了一次小规模装置检查，覆盖一个任务族的两道训练题，封存集未评价。当前入口的执行条件见首页。任务规格可离线生成；固定脚本与预期文本的比较只用于核对流程。

E05v2 审计按原配置校验 14 份纯文本源码快照。可靠性审计把权限观察与记账节选当作历史证据读取。构建任务目录后可使用 E11/E12 默认入口查看本机生成的离线清单。附录 D 分别标出了随包命令和需要完整实验档案的命令。

~~~text
python calculations/compare_e03_baseline.py
python experiments/lab/eval.py --selftest
python -m unittest experiments.lab.test_eval_pairing -v
python calculations/reproduce_platform_appendices.py
python calculations/reproduce_rl_arithmetic.py
python calculations/reproduce_workflow_arithmetic.py
python calculations/reproduce_memory_operations.py
python -m unittest calculations.test_ch06_operation_demo
python calculations/reproduce_appendix_a.py -o analysis/appendix-a-export-check.json
python calculations/reproduce_ch15_case.py -o analysis/ch15-export-check.json
python calculations/reproduce_timing_audit.py
python -m unittest experiments.lab.test_e11_timing_v2 -v
python calculations/reproduce_reliability_audit.py
python calculations/audit_ch14_cosine_bound.py
python calculations/audit_sample_size.py --output analysis/sample-size-export-check.json
python -m unittest experiments.lab.test_e01_v2_token_wallclock -v
python -m experiments.lab.build_taskset --no-lab-run
python -m experiments.lab.run_e11_v2
python -m experiments.lab.run_e12_v2
python calculations/reproduce_context_audit.py
python calculations/reproduce_skill_audit.py
~~~
