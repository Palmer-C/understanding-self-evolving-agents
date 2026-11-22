param([string]$OutDir)

if (-not $OutDir) { $OutDir = Join-Path $PSScriptRoot 'files\papers' }

$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$logf = Join-Path $OutDir '_download_log.txt'
"=== run $(Get-Date -Format o) ===" | Out-File $logf -Encoding utf8

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

$UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
$n = 0
foreach ($item in $papers) {
  $parts = $item -split '\|'
  $id = $parts[0]; $name = $parts[1]
  $dst = Join-Path $OutDir ($name + '__' + $id + '.pdf')
  $ok = $false
  if (Test-Path $dst) {
    $sz0 = (Get-Item $dst).Length
    if ($sz0 -gt 20000) { "SKIP  $id  $name  (exists $([math]::Round($sz0/1KB,1)) KB)" | Add-Content $logf -Encoding utf8; $ok = $true; $n++ }
  }
  if (-not $ok) {
    foreach ($px in @($null, 'http://127.0.0.1:7890')) {
      try {
        if ($px) { Invoke-WebRequest -Uri ('https://arxiv.org/pdf/' + $id) -OutFile $dst -Proxy $px -TimeoutSec 60 -UseBasicParsing -UserAgent $UA }
        else     { Invoke-WebRequest -Uri ('https://arxiv.org/pdf/' + $id) -OutFile $dst -TimeoutSec 60 -UseBasicParsing -UserAgent $UA }
        $sz = (Get-Item $dst).Length
        if ($sz -gt 20000) {
          "OK    $id  $name  $([math]::Round($sz/1KB,1)) KB  via=$px" | Add-Content $logf -Encoding utf8
          $ok = $true; $n++; break
        } else { Remove-Item $dst -Force -ErrorAction SilentlyContinue }
      } catch { }
    }
  }
  if (-not $ok) { "FAIL  $id  $name" | Add-Content $logf -Encoding utf8 }
  Start-Sleep -Seconds 3
}
"=== done: $n / $($papers.Count) ===" | Add-Content $logf -Encoding utf8
