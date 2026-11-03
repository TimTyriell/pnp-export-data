# PreToolUse guard: the repo's must-hold rules, enforced instead of requested.
#
# CLAUDE.md "The review gate" asks agents, in prose, never to upload to the
# wiki on their own. The script gate (--apply + FANDOM_DRY_RUN=0) stops
# accidents; this hook stops an agent from clearing it. Exit 2 blocks the tool
# call and hands the message to Claude. Rationale: pnp-knowledge ADR-005.
# Weakening the gate in code (DRY_RUN default, hardcoded --apply) is REVIEW.md's
# job, not this hook's.
#
# Overrides for the human: .claude/guards.env (see guards.env.example) or
# an env var of the same name on the Claude process:
#   PNP_ALLOW_WIKI_WRITE=1    run 04_upload.py --apply
#   PNP_ALLOW_MAIN_COMMIT=1   commit directly on main
#   PNP_ALLOW_GUARD_EDIT=1    edit .claude/hooks/, settings.json, guards.env
# Path rules see the Edit/Write tools, not shell writes (`>`, Set-Content);
# review covers that gap (pnp-knowledge ADR-005).

$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
try { $hook = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
$in = $hook.tool_input
$cwd = if ($hook.cwd) { $hook.cwd } else { (Get-Location).Path }

# Overrides: .claude/guards.env (gitignored; every switch is listed in
# guards.env.example), re-read on every call. An environment variable of the
# same name on the Claude process works too. Only the human sets either.
$switches = @{}
$envFile = Join-Path $repo '.claude\guards.env'
if (Test-Path $envFile) {
    foreach ($l in Get-Content $envFile) {
        if ($l -match '^\s*(PNP_ALLOW_\w+)\s*=\s*(\S*)') { $switches[$Matches[1]] = $Matches[2] }
    }
}
function Allowed([string]$name) {
    ([Environment]::GetEnvironmentVariable($name) -eq '1') -or ($switches[$name] -eq '1')
}

function Block([string]$why) {
    [Console]::Error.WriteLine("Blocked by $repo\.claude\hooks\guard.ps1: $why")
    exit 2
}

# Path of $p relative to this repo, '/'-separated, or $null when outside it.
function RepoRel([string]$p) {
    if (-not $p) { return $null }
    if (-not [IO.Path]::IsPathRooted($p)) { $p = Join-Path $cwd $p }
    $full = [IO.Path]::GetFullPath($p)
    if (-not $full.StartsWith("$repo\", 'OrdinalIgnoreCase')) { return $null }
    return $full.Substring($repo.Length + 1) -replace '\\', '/'
}

if ($hook.tool_name -in 'Edit', 'Write', 'MultiEdit') {
    $rel = RepoRel $in.file_path
    if (-not $rel) { exit 0 }
    if ($rel -match '^\.claude/(hooks/|settings(\.local)?\.json$|guards\.env)' -and -not (Allowed 'PNP_ALLOW_GUARD_EDIT')) {
        Block "the guards protect themselves: .claude/hooks/, settings.json and guards.env are the human's to change. Override: PNP_ALLOW_GUARD_EDIT=1 in .claude/guards.env."
    }
    exit 0
}

if ($hook.tool_name -in 'Bash', 'PowerShell') {
    $cmd = [string]$in.command
    # Command position: start, or after a separator / env assignment / path.
    $at = '(?m)(^|[;&|(]\s*|\n\s*)(\w+=\S*\s+)*(\S*[\\/])?'
    # Rules about *running* a script scan the whole command, so wrappers
    # (`nohup`, `bash -c "..."`) can't hide a call. Text that is only a
    # message is cut first: heredoc bodies and -m/--message/--body/--title.
    $scan = [regex]::Replace($cmd, '(?s)<<-?\s*[''"]?(\w+)[''"]?.*?\n\s*\1\b', '')
    $scan = [regex]::Replace($scan, '(-m|--message|--body|--title)\s+("[^"]*"|''[^'']*'')', '')

    # guards.env holds the overrides, so only the human writes it.
    if ($scan -match 'guards\.env' -and
        $scan -match '>|\b(Set-Content|Add-Content|Out-File|tee|cp|mv|Copy-Item|Move-Item|New-Item|Remove-Item|rm)\b|sed\s+-i' -and
        -not (Allowed 'PNP_ALLOW_GUARD_EDIT')) {
        Block "only the human writes .claude/guards.env. Ask them to flip the switch."
    }
    # Run as a script: python / python3.11 / py with any flags and path, or ./x.py.
    $py = '(\bpy(thon[\d.]*)?(\.exe)?(\s+-\S+)*\s+(\S*[\\/])?|(^|[\s;&|(''"])\.[\\/])'

    if (-not (Allowed 'PNP_ALLOW_WIKI_WRITE') -and
        $scan -match "${py}04_upload\.py\b[^\n;&|]*--apply") {
        Block "04_upload.py --apply writes to the public wiki. The human clears the review gate and runs it. Dry-run (no --apply) is fine. Override: PNP_ALLOW_WIKI_WRITE=1 in .claude/guards.env."
    }

    # Commits belong on a branch, made from a worktree; parallel sessions share
    # a checkout's index (pnp-knowledge lost a commit to that once).
    $c = [regex]::Match($cmd, "$at" + 'git\s+(-C\s+("[^"]+"|''[^'']+''|\S+)\s+)?commit\b')
    if ($c.Success -and -not (Allowed 'PNP_ALLOW_MAIN_COMMIT')) {
        $dir = $cwd
        $cd = [regex]::Matches($cmd.Substring(0, $c.Index), '(?m)(^|[;&|(]\s*)cd\s+("[^"]+"|''[^'']+''|\S+)')
        if ($cd.Count) { $dir = [IO.Path]::Combine($dir, $cd[$cd.Count - 1].Groups[2].Value.Trim('"', "'")) }
        if ($c.Groups[5].Success) { $dir = [IO.Path]::Combine($dir, $c.Groups[5].Value.Trim('"', "'")) }
        $top = git -C $dir rev-parse --show-toplevel 2>$null
        if ($top -and [IO.Path]::GetFullPath($top) -eq $repo -and (git -C $dir branch --show-current) -eq 'main') {
            Block "commit on main. Branch first, from a worktree: git worktree add -b <branch> <dir> origin/main. Override: PNP_ALLOW_MAIN_COMMIT=1 in .claude/guards.env."
        }
    }
}
exit 0
