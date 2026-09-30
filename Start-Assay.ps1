$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:ASSAY_ALLOW_MODEL_CALLS = '0'
& "$PSScriptRoot\.venv\Scripts\python.exe" -m streamlit run app/workbench.py --server.address 127.0.0.1 --server.port 8502 --browser.gatherUsageStats false
