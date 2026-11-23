# 原始文献

以 [来源索引](sources.csv) 和[书稿书目](../book/bib/references.bib)中的作者、题名、版次和原始链接定位所引原文。部分索引行记有研究时的本地文件名，公开版提供索引，论文请从原出版入口获取。

从仓库根目录运行以下命令可下载一个指定版次。把示例编号替换为待核对条目。已独立取得原件 SHA-256 时，加上 -ExpectedSha256 和 64 位摘要即可校验。脚本默认写入 references/files/papers；不同版次使用不同文件名。仅需阅读或构建时可跳过下载。

~~~powershell
.\references\download_papers.ps1 -ArxivId 2305.16291v1
~~~
