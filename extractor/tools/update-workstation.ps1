<#
.SYNOPSIS
    Pulls the latest smart_SW, rebuilds both sides, runs the gates, and on a first install
    registers the add-in. One command for the update sequence in docs\workstation-runbook.md.

.DESCRIPTION
    The steps, in order, each stopping the script if it fails:

      1. SOLIDWORKS must not be running: a loaded add-in holds SwReview.AddIn.dll open and the
         build would fail on the lock.
      2. The checkout must be clean: local edits on a workstation belong in a findings
         document, not in the tree, and a pull over them would tangle the two.
      3. git fetch, show what is about to arrive, git pull --ff-only origin main. A pull that
         cannot fast-forward means someone committed on this machine; that is reported and
         the script stops rather than merging.
      4. uv sync --all-extras in reviewer\, then the reviewer's tests and ruff.
      5. dotnet build of extractor\SwReview.sln, then its tests.
      6. With -Register, extractor\tools\register-addin.ps1 (which checks elevation itself).
         Registration survives rebuilds, so this is for a first install or a moved checkout.
      7. The health reminders: is the standards profile present, is uv on PATH for the
         SOLIDWORKS process, and which log lines to read after the next start.

    Every step is safe to repeat. -SkipTests exists for a quick rebuild and is not the
    normal path; the runbook's health checks assume the gates ran.

.PARAMETER Register
    Also run register-addin.ps1 after the build. Needs an elevated prompt.

.PARAMETER SkipTests
    Skip pytest, ruff and dotnet test.

.PARAMETER Configuration
    The build configuration. Defaults to Release, which is what register-addin.ps1 registers.

.EXAMPLE
    .\extractor\tools\update-workstation.ps1

.EXAMPLE
    .\extractor\tools\update-workstation.ps1 -Register
#>
[CmdletBinding()]
param(
    [switch] $Register,
    [switch] $SkipTests,
    [string] $Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$reviewer = Join-Path $repo "reviewer"
$solution = Join-Path $repo "extractor\SwReview.sln"

function Invoke-Step {
    param([string] $Name, [scriptblock] $Body)
    Write-Host ""
    Write-Host "== $Name"
    $global:LASTEXITCODE = 0
    & $Body
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE; nothing after it was run."
    }
}

# 1. SOLIDWORKS holds the add-in's DLL open while it is loaded.
if (Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue) {
    throw "SOLIDWORKS is running and holds SwReview.AddIn.dll open. Close it and run this again."
}

# 2. A dirty tree is a handover waiting to be written, not something to pull over.
Push-Location $repo
try {
    $dirty = git status --porcelain
    if ($LASTEXITCODE -ne 0) { throw "git status failed; is $repo a checkout?" }
    if ($dirty) {
        Write-Host $dirty
        throw ("The checkout has local changes (above). Record them in a findings document " +
               "(docs\workstation-runbook.md section 8), then `git stash push -m ""workstation <date>""`, " +
               "and run this again.")
    }

    $before = git rev-parse --short HEAD

    # 3. Pull, fast-forward only.
    Invoke-Step "git fetch origin" { git fetch origin }
    Write-Host "arriving:"
    git log --oneline HEAD..origin/main
    Invoke-Step "git pull --ff-only origin main" { git pull --ff-only origin main }
    $after = git rev-parse --short HEAD
    Write-Host "checkout: $before -> $after"
}
finally {
    Pop-Location
}

# 4. The reviewer.
Push-Location $reviewer
try {
    Invoke-Step "uv sync --all-extras" { uv sync --all-extras }
    if (-not $SkipTests) {
        Invoke-Step "uv run pytest -q" { uv run pytest -q -p no:warnings }
        Invoke-Step "uv run ruff check src tests" { uv run ruff check src tests }
    }
}
finally {
    Pop-Location
}

# 5. The extractor and the add-in.
Invoke-Step "dotnet build ($Configuration)" { dotnet build $solution -c $Configuration --nologo -v q }
if (-not $SkipTests) {
    Invoke-Step "dotnet test ($Configuration)" { dotnet test $solution -c $Configuration --no-build --nologo }
}

# 6. First install or moved checkout only; the script refuses a non-elevated prompt itself.
if ($Register) {
    Invoke-Step "register-addin.ps1" {
        & (Join-Path $PSScriptRoot "register-addin.ps1") -Configuration $Configuration
    }
}

# 7. What to check before and after the next SOLIDWORKS start.
Write-Host ""
Write-Host "== health"
$profile = Join-Path $env:LOCALAPPDATA "SwReview\standards.yaml"
if (Test-Path $profile) {
    Write-Host "standards profile: present at $profile"
} else {
    Write-Host ("standards profile: MISSING at $profile - the Standards tab will refuse until it " +
                "is placed (docs\workstation-runbook.md section 5)")
}
$uvOnPath = Get-Command uv -ErrorAction SilentlyContinue
if ($uvOnPath) {
    Write-Host "uv on PATH: $($uvOnPath.Source)"
} else {
    Write-Host "uv on PATH: NOT FOUND - the Review tab cannot start its backend from SOLIDWORKS"
}
Write-Host "next: start SOLIDWORKS with a part or assembly active, then read"
Write-Host "      Get-Content `$env:LOCALAPPDATA\SwReview\logs\addin.log -Tail 12"
Write-Host "      and run the seven health checks in docs\workstation-runbook.md section 6."
