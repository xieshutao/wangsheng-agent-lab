param(
  [Parameter(Mandatory=$true)][string]$LlamaBenchPath,
  [Parameter(Mandatory=$true)][string]$ModelPath,
  [Parameter(Mandatory=$true)][string]$OutputJson,
  [int]$GpuLayers = 999
)

$ErrorActionPreference = "Stop"
$cases = @(
  @{ n_prompt = 512;  n_gen = 0 },
  @{ n_prompt = 2048; n_gen = 0 },
  @{ n_prompt = 0;    n_gen = 128 },
  @{ n_prompt = 2048; n_gen = 128 }
)
$results = @()
foreach ($case in $cases) {
  $raw = & $LlamaBenchPath `
    -m $ModelPath `
    -p $case.n_prompt `
    -n $case.n_gen `
    -r 5 `
    -ngl $GpuLayers `
    -o json
  if ($LASTEXITCODE -ne 0) {
    throw "llama-bench failed for prompt=$($case.n_prompt), generation=$($case.n_gen)"
  }
  $parsed = $raw | ConvertFrom-Json
  foreach ($entry in @($parsed)) {
    $entry | Add-Member -NotePropertyName n_prompt -NotePropertyValue $case.n_prompt -Force
    $entry | Add-Member -NotePropertyName n_gen -NotePropertyValue $case.n_gen -Force
    $entry | Add-Member -NotePropertyName repetitions -NotePropertyValue 5 -Force
    $results += $entry
  }
}
$parent = Split-Path -Parent $OutputJson
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$results | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 $OutputJson
Write-Output "LLAMA_BENCH_JSON=$OutputJson"
