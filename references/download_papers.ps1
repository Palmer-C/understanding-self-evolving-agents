param(
    [Parameter(Position=0)][string]$OutDir,
    [ValidatePattern('^(?:[0-9]{4}\.[0-9]{4,5}|[a-zA-Z][a-zA-Z.-]*/[0-9]{7})v[1-9][0-9]*\z')]
    [string]$ArxivId,
    [ValidatePattern('^[0-9a-fA-F]{64}\z')][string]$ExpectedSha256
)

$ErrorActionPreference = 'Stop'
if ($ExpectedSha256 -and -not $ArxivId) { throw '-ExpectedSha256 requires a versioned -ArxivId.' }
if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot 'files\papers' }
$OutDir = [IO.Path]::GetFullPath($OutDir)
[IO.Directory]::CreateDirectory($OutDir) | Out-Null
$logf = Join-Path $OutDir '_download_log.txt'
"=== run $(Get-Date -Format o) ===" | Add-Content -LiteralPath $logf -Encoding utf8

$papers = @(
  '2507.21046|survey-self-evolving-agents',
  '2602.06052|survey-agent-memory-second-half',
  '2210.03629|react',
  '2303.17651|self-refine',
  '2310.01798|self-correct-negative-result',
  '2303.11366|reflexion',
  '2305.16291|voyager',
  '2310.03714|dspy',
  '2408.08435|adas',
  '2410.10762|aflow',
  '2507.19457|gepa',
  '2510.04618|ace-agentic-context-engineering',
  '2505.22954|darwin-godel-machine',
  '2506.01716|self-challenging',
  '2505.03335|absolute-zero',
  '2508.03680|agent-lightning',
  '2608.17528|agent-lightning-v1',
  '2603.19461|hyperagents',
  '2502.12110|a-mem',
  '2506.15841|mem1',
  '2601.18510|jitrl',
  '2601.01885|agemem-agentic-memory',
  '2603.04549|a-mac',
  '2509.25911|mem-alpha',
  '2509.24704|memgen',
  '2603.11768|ssgm-stability-safety-memory',
  '2510.00615|acon-context-compression',
  '2602.19320|anatomy-agentic-memory',
  '2605.09330|trap-of-trajectory',
  '2603.14597|d-mem',
  '2607.29377|zero-mem',
  '2601.03236|magma'
)

if ($ArxivId) {
    $baseId = $ArxivId -replace 'v[0-9]+$', ''
    $name = 'arxiv'
    foreach ($item in $papers) {
        $parts = $item.Split('|')
        if ($parts[0] -ceq $baseId) { $name = $parts[1]; break }
    }
    # Only accept an index filename for this paper and this exact version.
    # Extract the short name, never join a CSV-supplied path to the output directory.
    $index = Join-Path $PSScriptRoot 'sources.csv'
    if ([IO.File]::Exists($index)) {
        $safeId = [regex]::Escape($ArxivId.Replace('/', '-'))
        $pattern = '^files/papers/([A-Za-z0-9][A-Za-z0-9_-]*)__' + $safeId + '\.pdf\z'
        $names = @(Import-Csv -LiteralPath $index -Encoding UTF8 | ForEach-Object {
            if ($_.arxiv_id -ceq $baseId -and $_.local_pdf -cmatch $pattern) { $Matches[1] }
        } | Select-Object -Unique)
        if ($names.Count -eq 1) { $name = $names[0] }
    }
    $papers = @("$ArxivId|$name")
}

$pdfInfo = Get-Command -Name pdfinfo -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
function Get-CheckedPdfHash([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $header = [byte[]]::new(8)
        if ($stream.Read($header, 0, $header.Length) -ne 8 -or
            [Text.Encoding]::ASCII.GetString($header) -notmatch '^%PDF-[12]\.[0-9]$') {
            throw 'Missing PDF header.'
        }
        $tailLength = [int][Math]::Min(4096, $stream.Length)
        $stream.Seek(-$tailLength, [IO.SeekOrigin]::End) | Out-Null
        $reader = [IO.BinaryReader]::new($stream)
        $tailText = [Text.Encoding]::ASCII.GetString($reader.ReadBytes($tailLength))
        if ($tailText -notmatch 'startxref\s+([0-9]+)\s+%%EOF\s*\z' -or
            [long]$Matches[1] -ge $stream.Length) {
            throw 'Missing or invalid final PDF cross-reference offset or EOF marker.'
        }
        $stream.Position = [long]$Matches[1]
        $target = [Text.Encoding]::ASCII.GetString($reader.ReadBytes(80))
        if ($target -cnotmatch '^(xref\b|[0-9]+\s+[0-9]+\s+obj\b)') {
            throw 'PDF offset does not point to a cross-reference table or stream object.'
        }
        if ($pdfInfo) {
            & $pdfInfo.Source $Path | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'pdfinfo could not read the PDF.' }
        }
        $stream.Position = 0
        $hasher = [Security.Cryptography.SHA256]::Create()
        try {
            $digest = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
        } finally {
            $hasher.Dispose()
        }
        if ($ExpectedSha256 -and $digest -ine $ExpectedSha256) {
            throw 'PDF SHA-256 does not match the specified digest.'
        }
        return $digest
    } finally {
        $stream.Dispose()
    }
}

$succeeded = 0
$requested = $false
foreach ($item in $papers) {
    $id, $name = $item.Split('|')
    $dst = Join-Path $OutDir ($name + '__' + $id.Replace('/', '-') + '.pdf')
    $url = 'https://arxiv.org/pdf/' + $id
    $stage = Join-Path $OutDir ([guid]::NewGuid().ToString('N') + '.part')
    try {
        if ([IO.File]::Exists($dst)) {
            $digest = Get-CheckedPdfHash $dst
            $result = 'CACHED'
        } else {
            if ($requested) { Start-Sleep -Seconds 3 }
            $requested = $true
            Invoke-WebRequest -Uri $url -OutFile $stage -TimeoutSec 60 -UseBasicParsing
            $digest = Get-CheckedPdfHash $stage
            # Move within one directory. A concurrent winner cannot be overwritten.
            [IO.File]::Move($stage, $dst)
            $result = 'SAVED'
        }
        "$result $url $([IO.Path]::GetFileName($dst)) sha256=$digest" | Add-Content -LiteralPath $logf -Encoding utf8
        $succeeded++
    } catch {
        $message = "FAIL $url $($_.Exception.Message)"
        $message | Add-Content -LiteralPath $logf -Encoding utf8
        Write-Warning $message
    } finally {
        [IO.File]::Delete($stage)
    }
}
"=== done: $succeeded / $($papers.Count) ===" | Add-Content -LiteralPath $logf -Encoding utf8
if ($succeeded -ne $papers.Count) { exit 1 }
exit 0
