# PreToolUse guard: the repo's must-hold rules, enforced instead of requested.
#
# CLAUDE.md "The review gate" asks agents, in prose, never to upload to the
# wiki on their own. The script gate (--apply + FANDOM_DRY_RUN=0) stops
# accidents; this hook stops an agent from clearing it. Exit 2 blocks the tool
# call and hands the message to Claude. Rationale: pnp-knowledge ADR-005.
# Weakening the gate in code (DRY_RUN default, hardcoded --apply) is REVIEW.md's
# job, not this hook's.
#
# Env overrides for the human, set before starting Claude:
#   PNP_ALLOW_WIKI_WRITE=1    run 04_upload.py --apply
#   PNP_ALLOW_MAIN_COMMIT=1   commit directly on main

$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
try { $hook = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { exit 0 }
$in = $hook.tool_input
$cwd = if ($hook.cwd) { $hook.cwd } else { (Get-Location).Path }

function Block([string]$why) {
    [Console]::Error.WriteLine("Blocked by $repo\.claude\hooks\guard.ps1: $why")
    exit 2
}

if ($hook.tool_name -in 'Bash', 'PowerShell') {
    $cmd = [string]$in.command
    # Command position: start, or after a separator / env assignment / path.
    # Keeps text inside commit messages and heredocs from matching.
    $at = '(?m)(^|[;&|(]\s*|\n\s*)(\w+=\S*\s+)*(\S*[\\/])?'

    if ($env:PNP_ALLOW_WIKI_WRITE -ne '1' -and
        $cmd -match "$at(python3?(\.exe)?\s+)?(\S*[\\/])?04_upload\.py\b[^\n;&|]*--apply") {
        Block "04_upload.py --apply writes to the public wiki. The human clears the review gate and runs it. Dry-run (no --apply) is fine. Override: PNP_ALLOW_WIKI_WRITE=1."
    }

    # Commits belong on a branch, made from a worktree; parallel sessions share
    # a checkout's index (pnp-knowledge lost a commit to that once).
    $c = [regex]::Match($cmd, "$at" + 'git\s+(-C\s+("[^"]+"|''[^'']+''|\S+)\s+)?commit\b')
    if ($c.Success -and $env:PNP_ALLOW_MAIN_COMMIT -ne '1') {
        $dir = $cwd
        $cd = [regex]::Matches($cmd.Substring(0, $c.Index), '(?m)(^|[;&|(]\s*)cd\s+("[^"]+"|''[^'']+''|\S+)')
        if ($cd.Count) { $dir = [IO.Path]::Combine($dir, $cd[$cd.Count - 1].Groups[2].Value.Trim('"', "'")) }
        if ($c.Groups[5].Success) { $dir = [IO.Path]::Combine($dir, $c.Groups[5].Value.Trim('"', "'")) }
        $top = git -C $dir rev-parse --show-toplevel 2>$null
        if ($top -and [IO.Path]::GetFullPath($top) -eq $repo -and (git -C $dir branch --show-current) -eq 'main') {
            Block "commit on main. Branch first, from a worktree: git worktree add -b <branch> <dir> origin/main. Override: PNP_ALLOW_MAIN_COMMIT=1."
        }
    }
}
exit 0
