# WangSheng v0.5 Local Model Runtime Guide

This guide implements the frozen `LOCAL_MODEL_BASELINE_SPEC_V0.5.md`. It does not download models, change the 25 evaluation scenarios, or move local traces into Git.

## 1. Frozen topology

```text
WangSheng run-local-episodes
  -> http://127.0.0.1:8080/v1/chat/completions
  -> pinned llama-server
  -> pinned GGUF model
```

`llama-server` is an inference process only. WangSheng remains the sole owner of tools, Gateway validation, Executor state changes, completion evaluation and traces.

## 2. Required files on the target PC

- pinned llama.cpp `llama-server` and `llama-bench` binaries;
- one approved official Qwen GGUF file;
- a private artifact directory outside the Git repository;
- Python 3.10+ and this repository installed with `pip install -e ".[dev]"`;
- NVIDIA driver tools, including `nvidia-smi`, for the RTX profile.

Before a formal run, record SHA-256 for both the runtime binary and model file. The CLI does this again in the private manifest.

## 3. Start the local server

Use the PowerShell launcher:

```powershell
.\scripts\windows\Start-LlamaServerV050.ps1 `
  -LlamaServerPath "D:\llama.cpp\llama-server.exe" `
  -ModelPath "D:\models\Qwen3-8B-Q4_K_M.gguf" `
  -ModelAlias "qwen3-8b-q4km" `
  -ProfileId "profile-a-qwen3-8b-q4km" `
  -LogDir "D:\wangsheng-private\server-logs"
```

The launcher binds to `127.0.0.1`, fixes one slot, enables flash attention, disables context shifting and writes a launch record. Do not expose the port to LAN or a tunnel.

## 4. Verify the runtime before testing

```powershell
python -m wangsheng.cli local-preflight `
  --base-url "http://127.0.0.1:8080/v1" `
  --model "qwen3-8b-q4km"
```

The command requires:

- `/health` reachable;
- `/v1/models` containing the exact alias;
- `/props` exposing a verifiable tool-aware chat template;
- loopback binding.

Then run the unrelated five-request synthetic tool contract:

```powershell
python -m wangsheng.cli local-synthetic-contract `
  --base-url "http://127.0.0.1:8080/v1" `
  --model "qwen3-8b-q4km" `
  --output "D:\wangsheng-private\synthetic-pre.jsonl"
```

Formal behavior testing is blocked unless this returns 5/5.

## 5. Run llama-bench

Create a JSON artifact with at least five repetitions for prompt processing and generation. Keep the exact command in the private experiment record. The formal WangSheng command requires this JSON file and copies it into the private artifact root.

## 6. Run the formal 25 episodes

Profile A example:

```powershell
.\scripts\windows\Run-LocalProfileA-V050.ps1 `
  -RepositoryPath "D:\src\wangsheng-agent-lab" `
  -PrivateOutputRoot "D:\wangsheng-private\v050-local" `
  -ModelPath "D:\models\Qwen3-8B-Q4_K_M.gguf" `
  -LlamaServerPath "D:\llama.cpp\llama-server.exe" `
  -LlamaBenchJson "D:\wangsheng-private\bench\profile-a.json" `
  -ServerPid 12345 `
  -ServerLogDir "D:\wangsheng-private\server-logs"
```

Profile B uses `Run-LocalProfileB-V050.ps1` and the official Qwen3-4B Q5_K_M file.

The output directory must be fresh and outside the repository. Each profile is run once. Provider retries are zero. A malformed tool call, timeout, OOM or server crash is a formal failure and is not selectively rerun.

## 7. Output and privacy

The private root contains manifests, telemetry, results, reports, traces, synthetic-contract records, logs and checksums. Public Git may contain only a sanitized report, aggregate metrics, exact hashes and reproduction instructions.

Do not commit:

- GGUF files;
- llama.cpp binaries;
- raw contexts or traces;
- server logs;
- private filesystem paths;
- local performance artifacts.

## 8. Stop the server

```powershell
.\scripts\windows\Stop-LlamaServerV050.ps1 -ProcessId 12345
```

After the 25th episode, the formal runner executes the same five-request synthetic contract without restarting the server and records memory drift.
