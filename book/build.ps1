# build.ps1 —— 编译全书
# 从仓库根目录运行 powershell -File .\book\build.ps1。
# 含非 ASCII 字符的目录可能影响 biber 读取 main.bcf；可用 -BuildRoot 选择 ASCII 临时目录。
# 引擎：XeLaTeX（ctex + Windows 字体集），参考文献：biber，由 latexmk 统一调度。

param(
    [switch]$Clean,
    [string]$BuildRoot,
    [string]$Latexmk = 'latexmk'
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
# 每次在独立目录构建，避免复用上一次编译的中间文件。
$latexmkCommand = Get-Command -Name $Latexmk -CommandType Application -ErrorAction Stop | Select-Object -First 1
$tmp = if ($BuildRoot) { $BuildRoot } else { [System.IO.Path]::GetTempPath() }
if (-not $tmp) { throw '请使用 -BuildRoot 指定可写的临时构建目录。' }
$tmp = [System.IO.Path]::GetFullPath($tmp)
[System.IO.Directory]::CreateDirectory($tmp) | Out-Null
$work = Join-Path $tmp "seab-build-$([System.Diagnostics.Process]::GetCurrentProcess().Id)-$([Guid]::NewGuid().ToString('N'))"
$latexmk = $latexmkCommand.Source
$outdir = Join-Path $here 'build'

if ($Clean -and (Test-Path $work)) { Remove-Item $work -Recurse -Force }
if (-not (Test-Path $work)) { New-Item -ItemType Directory -Force -Path $work | Out-Null }
foreach ($sub in @('build', 'build\chapters', 'build\frontmatter', 'build\backmatter')) {
    $d = Join-Path $work $sub
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
}

# 同步源文件（排除构建目录与产物）
Get-ChildItem -Path $here -Recurse -File | Where-Object {
    $_.FullName -notlike '*\build\*' -and (
        $_.Extension -ne '.pdf' -or
        $_.FullName.StartsWith((Join-Path $here 'figures\generated\'), [System.StringComparison]::OrdinalIgnoreCase)
    )
} | ForEach-Object {
    $rel = $_.FullName.Substring($here.Length).TrimStart('\')
    $dst = Join-Path $work $rel
    $dd = Split-Path -Parent $dst
    if (-not (Test-Path $dd)) { New-Item -ItemType Directory -Force -Path $dd | Out-Null }
    Copy-Item -LiteralPath $_.FullName -Destination $dst -Force -ErrorAction Stop
}
Push-Location $work
try {
    # xdvipdfmx 按 TFM 字体名读取 ToUnicode 映射。直接使用当前 TeX Live 自带的映射，
    # 让求和号、分隔符和黑板粗体字母可以复制，字体和排版参数仍取自原稿。
    $kpsewhich = Get-Command kpsewhich -CommandType Application -ErrorAction Stop | Select-Object -First 1
    $mathMaps = [ordered]@{ 'cmex10' = 'omx.cmap'; 'msbm10' = 'umsb.cmap' }
    foreach ($font in $mathMaps.Keys) {
        $name = $mathMaps[$font]
        $map = & $kpsewhich.Source '--path=$TEXMFDIST/tex/latex/mmap' $name
        if ($LASTEXITCODE -ne 0 -or -not $map -or -not [IO.File]::Exists($map)) {
            throw "TeX Live mmap resource unavailable: $name (font $font)."
        }
        # 若源树已有同名字体资源，报告冲突并保留它。
        [IO.File]::Copy($map, (Join-Path $work $font), $false)
    }
    $log = & $latexmk -xelatex -interaction=nonstopmode -file-line-error -outdir=build main.tex 2>&1 | Out-String
    $code = $LASTEXITCODE
} catch {
    $log = "PDF build preparation failed: $($_.Exception.Message)"
    [Console]::Error.WriteLine($log)
    $code = 1
} finally {
    Pop-Location
}

function Install-StagedPdf($staged, $destination, $backup) {
    if ([IO.File]::Exists($destination)) {
        [IO.File]::Replace($staged, $destination, $backup)
    } else {
        [IO.File]::Move($staged, $destination)
    }
}

function Get-PdfSha256($path) {
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [IO.File]::OpenRead($path)
        try {
            return [BitConverter]::ToString($algorithm.ComputeHash($stream))
        } finally {
            $stream.Dispose()
        }
    } finally {
        $algorithm.Dispose()
    }
}

function Publish-BookPdf($source) {
    $prefix = Join-Path $outdir ("publish-" + [guid]::NewGuid().ToString('N'))
    $targets = @(
        @{Path=(Join-Path $outdir 'main.pdf'); Stage="$prefix-build.tmp"; Backup="$prefix-build.bak"}
        @{Path=(Join-Path $here 'main.pdf'); Stage="$prefix-reader.tmp"; Backup="$prefix-reader.bak"}
    )
    $expected = Get-PdfSha256 $source
    $installed = 0
    try {
        foreach ($target in $targets) {
            [IO.File]::Copy($source, $target.Stage)
        }
        foreach ($target in $targets) {
            Install-StagedPdf $target.Stage $target.Path $target.Backup
            $installed++
        }
        foreach ($target in $targets) {
            $actual = Get-PdfSha256 $target.Path
            if ($actual -cne $expected) {
                throw "PDF SHA-256 mismatch: $($target.Path)"
            }
        }
    } catch {
        # 只还原本轮已安装的目标。替换前已有文件时保留原件，首次发布则移除新件。
        for ($i = $installed - 1; $i -ge 0; $i--) {
            $target = $targets[$i]
            try {
                if ([IO.File]::Exists($target.Backup)) {
                    if ([IO.File]::Exists($target.Path)) {
                        [IO.File]::Replace($target.Backup, $target.Path, $target.Stage)
                    } else {
                        [IO.File]::Move($target.Backup, $target.Path)
                    }
                } else {
                    [IO.File]::Delete($target.Path)
                }
            } catch {
                # 继续还原另一个目标。无法还原的备份留在原位置供恢复。
                [Console]::Error.WriteLine("PDF rollback failed for $($target.Path): $($_.Exception.Message)")
            }
        }
        throw
    } finally {
        foreach ($target in $targets) {
            [IO.File]::Delete($target.Stage)
        }
    }
    foreach ($target in $targets) {
        [IO.File]::Delete($target.Backup)
    }
}

$ErrorActionPreference = 'Stop'
[IO.Directory]::CreateDirectory($outdir) | Out-Null
# 编译目录彼此独立。共享的日志、状态和两份 PDF 每次只允许一个构建进程更新。
$publishLock = [IO.File]::Open((Join-Path $outdir '.publish.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
try {
    [IO.File]::Delete((Join-Path $outdir 'build-status.txt'))
    $log | Out-File (Join-Path $outdir 'build.log') -Encoding utf8

    $srcPdf = Join-Path $work 'build\main.pdf'

    # undef 判据：只看 latexmk 收敛之后的最终 main.log，不再扫 latexmk 的 stdout。
    # 旧判据用 -match 'Undefined (citation|reference)'（大小写不敏感），把 LaTeX 的汇总行
    # "There were undefined references." 也算成一条；首轮 pass 必然出该行（\include 的章节 aux
    # 要等 aux 收敛），于是 undef 虚高且不随收敛归零。同时真实条目
    # "LaTeX Warning: Reference `x' undefined" 反而不匹配该模式——既误报又漏报。
    # 新判据只认带名字的条目行，并显式排除汇总行；来源是最终 pass 的日志，故收敛后即为 0。
    # 修复（2026-09-20 第 6 班）：原先 main.log 缺失时 $undef 记 0，build-status 会出现
    # "假绿"（第 3 班 handoff 已登记该风险）。现在缺失时记 -1，明确表示"无法验证"：
    # 出现 undef=-1 时必须以 exit != 0 为准，不得把 -1 当作 0 通过验收。
    # 修复（2026-09-20 第 6 班）：Join-Path 在本机 PS 5.1 以 -File 子进程方式运行时，
    # 会把 $finalLog 偶发赋成 null（同一份脚本连续跑几次，finalLog 时有时无，
    # 而紧邻的 $srcPdf 用同样的 Join-Path 却是好的）。加一道显式拼接回退，
    # 并把实际使用的工作目录写进 build-diag.txt，便于下一班核对 undef 判据的来源。
    $finalLog = Join-Path $work 'build\main.log'
    if (-not $finalLog) { $finalLog = "$work\build\main.log" }
    $undefCount = -1
    @("tmp=[$tmp]", "work=[$work]", "finalLog=[$finalLog]") | Out-File (Join-Path $outdir 'build-diag.txt') -Encoding utf8
    if ($finalLog -and (Test-Path -LiteralPath $finalLog)) {
        $undef = @(Get-Content -LiteralPath $finalLog | Where-Object {
            ($_ -match 'Reference\s+.+\s+undefined' -or $_ -match 'Citation\s+.+\s+undefined') -and
            $_ -notmatch 'There were undefined'
        })
        $undefCount = $undef.Count
    } else {
        $undef = @()
    }
    $errs  = ($log -split "`n") | Where-Object { $_ -match ':\d+:\s' -and $_ -notmatch 'Latexmk' }

    # 先清掉上一轮的产物报告，避免"本次干净但 errors.txt 仍写着上一次的错"这种误判
    foreach ($old in @('undefined.txt', 'errors.txt')) {
        $p = Join-Path $outdir $old
        if (Test-Path $p) { Remove-Item $p -Force }
    }
    if ($undef.Count -gt 0) { $undef | Select-Object -First 40 | Out-File (Join-Path $outdir 'undefined.txt') -Encoding utf8 }
    if ($errs.Count -gt 0)  { $errs  | Select-Object -First 40 | Out-File (Join-Path $outdir 'errors.txt') -Encoding utf8 }

    $publishable = ($code -eq 0 -and [IO.File]::Exists($srcPdf) -and $undefCount -eq 0 -and $errs.Count -eq 0)
    if ($publishable) {
        try {
            Publish-BookPdf $srcPdf
        } catch {
            [Console]::Error.WriteLine("PDF publication failed: $($_.Exception.Message)")
            $publishable = $false
            $code = 1
        }
    }
    if (-not $publishable -and $code -eq 0) { $code = 1 }
    @("exit=$code", "pdf=$publishable", "undef=$undefCount", "errors=$($errs.Count)") |
        Out-File (Join-Path $outdir 'build-status.txt') -Encoding utf8
} finally {
    $publishLock.Dispose()
}
exit $code
