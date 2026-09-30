$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskScript = Join-Path $PSScriptRoot 'scripts\label_actions.py'
$taskRun = Join-Path $PSScriptRoot 'results\stage-2-3-runs'
$taskFiles = @('permission-v2.jsonl','gate-v1.jsonl','gate-v2.jsonl','stress-v1.jsonl','stress-bad.jsonl')
foreach ($taskFile in $taskFiles) {
    if (-not (Test-Path (Join-Path $taskRun $taskFile))) { throw "Missing completed output: $taskFile" }
}
$taskPermission = (Get-Content (Join-Path $taskRun 'permission-v2.jsonl') -First 1 | ConvertFrom-Json).config_id
$taskGateV1 = (Get-Content (Join-Path $taskRun 'gate-v1.jsonl') -First 1 | ConvertFrom-Json).config_id
$taskGateV2 = (Get-Content (Join-Path $taskRun 'gate-v2.jsonl') -First 1 | ConvertFrom-Json).config_id
$taskStressV1 = (Get-Content (Join-Path $taskRun 'stress-v1.jsonl') -First 1 | ConvertFrom-Json).config_id
$taskStressBad = (Get-Content (Join-Path $taskRun 'stress-bad.jsonl') -First 1 | ConvertFrom-Json).config_id
& $taskPython $taskScript --judgments results\stage-2-3-runs\permission-v2.jsonl --config $taskPermission --out results\stage-2-3-runs\permission-labels.jsonl
& $taskPython $taskScript --judgments results\stage-2-3-runs\gate-v1.jsonl --judgments results\stage-2-3-runs\gate-v2.jsonl --config $taskGateV1 --config $taskGateV2 --out results\stage-2-3-runs\gate-labels.jsonl
& $taskPython $taskScript --judgments results\stage-2-3-runs\stress-v1.jsonl --judgments results\stage-2-3-runs\stress-bad.jsonl --config $taskStressV1 --config $taskStressBad --out results\stage-2-3-runs\stress-labels.jsonl
Write-Host 'Label worksheets created. Review actions blind to confidence, then set correct/reviewer/reason/label_status.' -ForegroundColor Green
Write-Host 'When adjudication is complete, run .\Finish-Stage23.ps1'
