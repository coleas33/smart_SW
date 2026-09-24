<#
.SYNOPSIS
    Pulls the latest smart_SW, rebuilds both sides, runs the gates, and on a first install
    registers the add-in. One command for the update sequence in docs\workstation-runbook.md.

.DESCRIPTION
    The steps, in order, each stopping the script if it fails:

      1. SOLIDWORKS must not be running: a loaded add-in holds SwReview.AddIn.dll open and the
         build would fail on the lock. The SOLIDWORKS interops must be where -SolidWorksRoot
         says, or the build cannot compile.
      2. The checkout must be clean: local edits on a workstation belong in a findings
         document, not in the tree, and a pull over them would tangle the two.
      3. git fetch, show what is about to arrive, git pull --ff-only origin main. A pull that
         cannot fast-forward means someone committed on this machine; that is reported and
         the script stops rather than merging.
      4. uv sync --all-extras in reviewer\, swreview tokenizer fetch (once per machine; a
         vocabulary already in place is left alone; -TokenizerFrom takes a copy carried by
         hand where the web filter blocks the download), then the reviewer's tests - the
         live provider tests deselected, as CI does - and ruff.
      5. dotnet build of extractor\SwReview.sln against -SolidWorksRoot's interops, then its
         tests.
      6. With -Register, extractor\tools\register-addin.ps1 (which checks elevation itself).
         Registration survives rebuilds, so this is for a first install or a moved checkout.
      7. The health reminders: is the standards profile present, is uv on PATH for the
         SOLIDWORKS process, where swreview-extract.exe was built, and which log lines to read
         after the next start.

    Every step is safe to repeat. -SkipTests exists for a quick rebuild and is not the
    normal path; the runbook's health checks assume the gates ran.

    Run it non-elevated, as the account that uses SOLIDWORKS: the reviewer's environment and
    the tokenizer land in that account's profile, and git refuses a checkout owned by another
    account. Register from an elevated prompt with register-addin.ps1 on its own; -Register
    here is for a machine where that account's own prompt is the elevated one.

.PARAMETER Register
    Also run register-addin.ps1 after the build. Needs an elevated prompt.

.PARAMETER SkipTests
    Skip pytest, ruff and dotnet test.

.PARAMETER NoPull
    Build and gate what is checked out, without pulling (a lane with its own commits).

.PARAMETER Configuration
    The build configuration. Defaults to Release, which is what register-addin.ps1 registers.

.PARAMETER SolidWorksRoot
    The SOLIDWORKS installation root. The build compiles against its api\redist interops and
    the registration stages them. Defaults to the standard install location.

.PARAMETER TokenizerFrom
    A copy of the o200k_base vocabulary file carried by hand (from the development machine's
    %LOCALAPPDATA%\SwReview\tokenizer), for a seat that cannot download it. Checked against
    its expected hash exactly as a download is.

.EXAMPLE
    .\extractor\tools\update-workstation.ps1

.EXAMPLE
    .\extractor\tools\update-workstation.ps1 -TokenizerFrom E:\handover\fb374d419588a4632f3f557e76b4b70aebbca790

.EXAMPLE
    .\extractor\tools\update-workstation.ps1 -SolidWorksRoot "D:\SOLIDWORKS Corp\SOLIDWORKS"
#>
[CmdletBinding()]
param(
    [switch] $Register,
    [switch] $SkipTests,
    [switch] $NoPull,
    [string] $Configuration = "Release",
    [string] $SolidWorksRoot = "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS",
    [string] $TokenizerFrom = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$reviewer = Join-Path $repo "reviewer"
$solution = Join-Path $repo "extractor\SwReview.sln"
$swRedist = Join-Path $SolidWorksRoot "api\redist"

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

# An elevated run fills the elevated account's profile, which may not be the engineer's.
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Warning ("This prompt is elevated as $($identity.Name). The reviewer's .venv and the " +
                   "tokenizer go into this account's profile, and git refuses a checkout another " +
                   "account owns. Run this non-elevated as the account that uses SOLIDWORKS, and " +
                   "register with extractor\tools\register-addin.ps1 from an elevated prompt.")
}

# 1. SOLIDWORKS holds the add-in's DLL open while it is loaded, and the build needs its interops.
if (Get-Process -Name SLDWORKS -ErrorAction SilentlyContinue) {
    throw "SOLIDWORKS is running and holds SwReview.AddIn.dll open. Close it and run this again."
}
if (-not (Test-Path (Join-Path $swRedist "SolidWorks.Interop.sldworks.dll"))) {
    throw ("No SOLIDWORKS interops at $swRedist. Pass the installation root with " +
           "-SolidWorksRoot (docs\workstation-runbook.md section 2).")
}

# 2. A dirty tree is a handover waiting to be written, not something to pull over.
Push-Location $repo
try {
    $dirty = git status --porcelain
    if ($LASTEXITCODE -ne 0) { throw "git status failed; is $repo a checkout?" }
    if ($dirty) {
        Write-Host $dirty
        throw ("The checkout has local changes (above). A findings document belongs in " +
               "%LOCALAPPDATA%\SwReview\handover\<date>\, not in the checkout " +
               "(docs\workstation-runbook.md section 8): move it there, record anything else " +
               "in it, then `git stash push --include-untracked -m ""workstation <date>""` " +
               "(a plain stash leaves untracked files behind) and run this again.")
    }

    $before = git rev-parse --short HEAD

    # 3. Pull, fast-forward only - and only on main. A workstation that keeps its own
    #    documentation commits on a lane (the two-lane arrangement the pilot seat uses)
    #    cannot fast-forward onto origin/main; it merges origin/main into the lane by hand
    #    and runs this script with -NoPull to build and gate what is checked out.
    $branch = git rev-parse --abbrev-ref HEAD
    Invoke-Step "git fetch origin" { git fetch origin }
    Write-Host "arriving:"
    git log --oneline HEAD..origin/main
    if ($branch -ne 'main') {
        if (-not $NoPull) {
            throw ("The checkout is on '$branch', not main, so this script will not pull: a lane " +
                   "with its own commits cannot fast-forward onto origin/main. Merge it yourself " +
                   "(git merge origin/main), then run this again with -NoPull to build and test " +
                   "what is checked out.")
        }
        Write-Host "on '$branch' with -NoPull: building what is checked out"
    }
    elseif ($NoPull) {
        Write-Host "-NoPull: building what is checked out"
    }
    else {
        Invoke-Step "git pull --ff-only origin main" { git pull --ff-only origin main }
    }
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
    # The o200k_base vocabulary every token count uses lives in a per-user cache, never in the
    # repository (specs\008-checks-first-review\contracts\tokenizer.md). The fetch downloads it
    # once; a file already in place with the expected hash is left alone and nothing is fetched.
    # Where the web filter blocks the download, -TokenizerFrom takes the file carried by hand.
    if ($TokenizerFrom) {
        Invoke-Step "uv run swreview tokenizer fetch --from" { uv run swreview tokenizer fetch --from $TokenizerFrom }
    } else {
        Invoke-Step "uv run swreview tokenizer fetch" { uv run swreview tokenizer fetch }
    }
    if (-not $SkipTests) {
        # SWREVIEW_REQUIRE_TOKENIZER=1 turns a missing vocabulary into failing tests rather than
        # skipped ones, so a seat without it cannot pass the gate by testing less. The live
        # provider tests are deselected, as CI does: a key in this environment must not make the
        # gate call a paid API. 008 T106 runs the live test on its own.
        Invoke-Step "uv run pytest -q" {
            $env:SWREVIEW_REQUIRE_TOKENIZER = "1"
            try { uv run pytest -q -p no:warnings -m "not live" }
            finally { Remove-Item Env:SWREVIEW_REQUIRE_TOKENIZER -ErrorAction SilentlyContinue }
        }
        Invoke-Step "uv run ruff check src tests" { uv run ruff check src tests }
    }
}
finally {
    Pop-Location
}

# 5. The extractor and the add-in, against this seat's interops.
Invoke-Step "dotnet build ($Configuration)" { dotnet build $solution -c $Configuration --nologo -v q "-p:SwRedist=$swRedist" }
if (-not $SkipTests) {
    Invoke-Step "dotnet test ($Configuration)" { dotnet test $solution -c $Configuration --no-build --nologo }
}

# 6. First install or moved checkout only; the script refuses a non-elevated prompt itself.
if ($Register) {
    Invoke-Step "register-addin.ps1" {
        & (Join-Path $PSScriptRoot "register-addin.ps1") -Configuration $Configuration -SolidWorksRoot $SolidWorksRoot
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
# Every probe and dump task calls swreview-extract by its bare name; nothing puts it on PATH.
$extract = Join-Path $repo "extractor\SwReview.Extractor.Console\bin\x64\$Configuration\net48\swreview-extract.exe"
if (Test-Path $extract) {
    Write-Host "swreview-extract: $extract"
    Write-Host "      for this shell: Set-Alias swreview-extract `"$extract`""
} else {
    Write-Host "swreview-extract: NOT BUILT at $extract"
}
Write-Host "next: start SOLIDWORKS with a part or assembly active, then read"
Write-Host "      Get-Content `$env:LOCALAPPDATA\SwReview\logs\addin.log -Tail 12"
Write-Host "      and run the seven health checks in docs\workstation-runbook.md section 6."
