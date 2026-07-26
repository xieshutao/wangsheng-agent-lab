param([Parameter(Mandatory=$true)][int]$ProcessId)
$ErrorActionPreference = "Stop"
$process = Get-Process -Id $ProcessId -ErrorAction Stop
Stop-Process -Id $ProcessId -Force
$process.WaitForExit()
Write-Output "Stopped llama-server PID $ProcessId"
