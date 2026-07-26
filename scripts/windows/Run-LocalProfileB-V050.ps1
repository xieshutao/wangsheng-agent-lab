param(
  [Parameter(Mandatory=$true)][string]$RepositoryPath,
  [Parameter(Mandatory=$true)][string]$PrivateOutputRoot,
  [Parameter(Mandatory=$true)][string]$ModelPath,
  [Parameter(Mandatory=$true)][string]$LlamaServerPath,
  [Parameter(Mandatory=$true)][string]$LlamaBenchJson,
  [Parameter(Mandatory=$true)][int]$ServerPid,
  [Parameter(Mandatory=$true)][string]$ServerLogDir,
  [string]$ExpectedGitCommit
)
$ErrorActionPreference = "Stop"
Set-Location $RepositoryPath
$output = Join-Path $PrivateOutputRoot "profile-b-qwen3-4b-q5km"
python -m wangsheng.cli run-local-episodes `
  --project-root $RepositoryPath `
  --output-dir $output `
  --model "qwen3-4b-q5km" `
  --profile-id "profile-b-qwen3-4b-q5km" `
  --model-repository "Qwen/Qwen3-4B-GGUF" `
  --model-path $ModelPath `
  --quantization "Q5_K_M" `
  --context-size 8192 `
  --gpu-offload "full" `
  --runtime-binary $LlamaServerPath `
  --runtime-release "b9637" `
  --runtime-commit "aedb2a5" `
  --server-pid $ServerPid `
  --server-stdout-log (Join-Path $ServerLogDir "profile-b-qwen3-4b-q5km-stdout.log") `
  --server-stderr-log (Join-Path $ServerLogDir "profile-b-qwen3-4b-q5km-stderr.log") `
  --llama-bench-json $LlamaBenchJson `
  --expected-git-commit $ExpectedGitCommit `
  --server-arg="--ctx-size=8192" `
  --server-arg="--n-gpu-layers=999" `
  --server-arg="--parallel=1" `
  --server-arg="--flash-attn=on" `
  --server-arg="--no-context-shift"
