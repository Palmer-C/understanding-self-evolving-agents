# E05v2 运行所用源码

本目录保存运行 `E05v2-20260929T143245Z-d7a8db` 当时登记的 13 份 Python 源码和 1 份协议。它们以文本资料分发，供读者查看和校验。当前运行入口在 `experiments/lab/`。

每份快照保留原来记录的 LF 字节。文件名在原名之后添加 `.txt`，例如 `sandbox.py.txt`。运行配置 `experiments/runs/E05v2-20260929T143245Z-d7a8db/config.json` 的 `design.source_sha256` 列出了全部 14 项 SHA-256，其中 `protocol` 对应 `E05-v2.md.txt`。从仓库根目录运行 `python calculations/reproduce_skill_audit.py` 可逐项核对哈希并复算已归档的事件与资源用量。

这些快照与公开首版已经收录的同名源码逐一比对，再按原运行登记的哈希核验。其用途为历史复算。快照继承对应工具及实验协议的 Apache-2.0 许可。
