$input_json = [Console]::In.ReadToEnd()
try {
    $data = $input_json | ConvertFrom-Json -ErrorAction Stop
} catch {
    exit 0
}

$filePath = $data.tool_input.file_path
if (-not $filePath -or -not ($filePath -like "*.py")) {
    exit 0
}
if (-not (Test-Path $filePath)) {
    exit 0
}

$projectDir = $env:CLAUDE_PROJECT_DIR
$candidates = @(
    (Join-Path $projectDir "services\kb\.venv\Scripts\ruff.exe"),
    (Join-Path $projectDir "services\dashboard\.venv\Scripts\ruff.exe"),
    (Join-Path $projectDir "fandom_env\Scripts\ruff.exe"),
    (Join-Path $projectDir ".venv\Scripts\ruff.exe")
)

$ruffExe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ruffExe) {
    $cmd = Get-Command ruff -ErrorAction SilentlyContinue
    if ($cmd) { $ruffExe = $cmd.Source }
}
if (-not $ruffExe) {
    exit 0
}

$output = & $ruffExe check --fix $filePath 2>&1
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    [Console]::Error.WriteLine(($output | Out-String))
    exit 2
}

exit 0
