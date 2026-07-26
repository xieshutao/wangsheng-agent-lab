param(
  [Parameter(Mandatory=$true)][string]$LlamaServerPath,
  [Parameter(Mandatory=$true)][string]$ModelPath,
  [Parameter(Mandatory=$true)][string]$ModelAlias,
  [Parameter(Mandatory=$true)][string]$ProfileId,
  [Parameter(Mandatory=$true)][string]$LogDir,
  [int]$ContextSize = 8192,
  [int]$Port = 8080,
  [int]$GpuLayers = 999
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$stdout = Join-Path $LogDir "$ProfileId-stdout.log"
$stderr = Join-Path $LogDir "$ProfileId-stderr.log"
$record = Join-Path $LogDir "$ProfileId-launch.json"
$args = @(
  "--host", "127.0.0.1",
  "--port", "$Port",
  "--model", $ModelPath,
  "--alias", $ModelAlias,
  "--ctx-size", "$ContextSize",
  "--n-gpu-layers", "$GpuLayers",
  "--parallel", "1",
  "--flash-attn", "on",
  "--no-context-shift"
)
$process = Start-Process -FilePath $LlamaServerPath -ArgumentList $args -PassThru `
  -RedirectStandardOutput $stdout -RedirectStandardError $stderr
@{
  schema_version = "wangsheng.llama_server_launch.v1"
  profile_id = $ProfileId
  process_id = $process.Id
  executable = [IO.Path]::GetFileName($LlamaServerPath)
  model = [IO.Path]::GetFileName($ModelPath)
  arguments = $args
  started_at_utc = [DateTime]::UtcNow.ToString("o")
  stdout = $stdout
  stderr = $stderr
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $record
Write-Output "PID=$($process.Id)"
Write-Output "LAUNCH_RECORD=$record"
