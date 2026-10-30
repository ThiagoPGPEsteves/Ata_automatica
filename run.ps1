Set-Location -LiteralPath $PSScriptRoot
if (Test-Path ".\.venv\Scripts\python.exe") {
    & ".\.venv\Scripts\python.exe" run.py @args
} else {
    python run.py @args
}
