$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskRun = Join-Path $PSScriptRoot 'results\stage-2-3-runs'
$taskPermission = (Get-Content (Join-Path $taskRun 'permission-v2.jsonl') -First 1 | ConvertFrom-Json).config_id
$taskGateV1 = (Get-Content (Join-Path $taskRun 'gate-v1.jsonl') -First 1 | ConvertFrom-Json).config_id
$taskGateV2 = (Get-Content (Join-Path $taskRun 'gate-v2.jsonl') -First 1 | ConvertFrom-Json).config_id
$taskStressV1 = (Get-Content (Join-Path $taskRun 'stress-v1.jsonl') -First 1 | ConvertFrom-Json).config_id
$taskStressBad = (Get-Content (Join-Path $taskRun 'stress-bad.jsonl') -First 1 | ConvertFrom-Json).config_id
foreach ($taskLabels in @('permission-labels.jsonl','gate-labels.jsonl','stress-labels.jsonl')) {
    & $taskPython scripts\label_actions.py --validate (Join-Path $taskRun $taskLabels)
    if ($LASTEXITCODE) { throw "Invalid label file: $taskLabels" }
}
& $taskPython scripts\build_permissions.py --judgments results\stage-2-3-runs\permission-v2.jsonl --labels results\stage-2-3-runs\permission-labels.jsonl --config $taskPermission --out results\stage-2-3-runs\receipts
if ($LASTEXITCODE) { throw 'Permission receipt failed' }
& $taskPython scripts\evaluate_correction.py --before results\stage-2-3-runs\gate-v1.jsonl --after results\stage-2-3-runs\gate-v2.jsonl --labels results\stage-2-3-runs\gate-labels.jsonl --before-config $taskGateV1 --after-config $taskGateV2 --label v1-to-v2 --out results\stage-2-3-runs\receipts
if ($LASTEXITCODE) { throw 'Correction gate failed' }
& $taskPython scripts\evaluate_correction.py --before results\stage-2-3-runs\stress-v1.jsonl --after results\stage-2-3-runs\stress-bad.jsonl --labels results\stage-2-3-runs\stress-labels.jsonl --before-config $taskStressV1 --after-config $taskStressBad --label v1-to-bad --out results\stage-2-3-runs\receipts
if ($LASTEXITCODE) { throw 'Stress gate failed' }
Write-Host 'Stage 2/3 receipts created. Restart or refresh the Assay UI.' -ForegroundColor Green
