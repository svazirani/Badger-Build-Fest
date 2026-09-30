$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$taskEnv = Join-Path $PSScriptRoot '.env'
if (Test-Path $taskEnv) {
    foreach ($taskLine in Get-Content -LiteralPath $taskEnv) {
        if ($taskLine -match '^\s*(OPENAI_API_KEY|OPENAI_MODEL)\s*=\s*(.*)\s*$') {
            Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2].Trim()
        }
    }
}
if (-not $env:OPENAI_API_KEY) { throw 'OPENAI_API_KEY is missing. Add it to .env before running.' }
$taskModel = if ($env:OPENAI_MODEL) { $env:OPENAI_MODEL } else { 'gpt-5-mini' }

Write-Host "Assay Stage 2/3 will make 270 paid OpenAI API calls with $taskModel." -ForegroundColor Yellow
Write-Host 'Actual list-price cost is calculated from input, cached-input, and output usage returned by OpenAI.'
$taskApproval = Read-Host 'Type I ACCEPT 270 OPENAI CALLS to continue'
if ($taskApproval -cne 'I ACCEPT 270 OPENAI CALLS') {
    throw 'Usage was not accepted. No model calls were made.'
}

$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskRunner = Join-Path $PSScriptRoot 'scripts\run_frozen_eval.py'
$taskOut = Join-Path $PSScriptRoot 'results\stage-2-3-runs'
New-Item -ItemType Directory -Path $taskOut -Force | Out-Null
$env:ASSAY_ALLOW_MODEL_CALLS = '1'
try {
    & $taskPython $taskRunner --plan results\stage-2-3-plans\permission.json --out results\stage-2-3-runs\permission-v2.jsonl --model $taskModel --backend openai --prompt v2 --execute --i-accept-usage
    if ($LASTEXITCODE) { throw "Permission run failed with exit code $LASTEXITCODE" }
    & $taskPython $taskRunner --plan results\stage-2-3-plans\gate.json --out results\stage-2-3-runs\gate-v1.jsonl --model $taskModel --backend openai --prompt v1 --execute --i-accept-usage
    if ($LASTEXITCODE) { throw "Gate v1 run failed with exit code $LASTEXITCODE" }
    & $taskPython $taskRunner --plan results\stage-2-3-plans\gate.json --out results\stage-2-3-runs\gate-v2.jsonl --model $taskModel --backend openai --prompt v2 --execute --i-accept-usage
    if ($LASTEXITCODE) { throw "Gate v2 run failed with exit code $LASTEXITCODE" }
    & $taskPython $taskRunner --plan results\stage-2-3-plans\stress.json --out results\stage-2-3-runs\stress-v1.jsonl --model $taskModel --backend openai --prompt v1 --execute --i-accept-usage
    if ($LASTEXITCODE) { throw "Stress v1 run failed with exit code $LASTEXITCODE" }
    & $taskPython $taskRunner --plan results\stage-2-3-plans\stress.json --out results\stage-2-3-runs\stress-bad.jsonl --model $taskModel --backend openai --prompt bad --execute --i-accept-usage
    if ($LASTEXITCODE) { throw "Stress bad run failed with exit code $LASTEXITCODE" }
} finally {
    Remove-Item Env:\ASSAY_ALLOW_MODEL_CALLS -ErrorAction SilentlyContinue
}
Write-Host 'Runs complete. Next: .\Prepare-Stage23-Labels.ps1' -ForegroundColor Green
