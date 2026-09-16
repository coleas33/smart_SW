<#
.SYNOPSIS
    Registers (or unregisters) the SwReview SOLIDWORKS add-in for COM.

.DESCRIPTION
    Two steps, in this order, because the second cannot succeed without the first:

      1. Stage SolidWorks.Interop.{sldworks,swconst,swpublished}.dll from the seat's
         api\redist folder into the add-in's build output.

         regasm has to load swpublished to reflect over ISwAddin while registering, and
         SwReview.AddIn.csproj sets <Private>false</Private> so the build deliberately does
         not copy the seat's interops. api\redist is not on any assembly probing path and
         adding it to PATH does nothing - assembly binding ignores PATH. Without this step a
         clean build fails to register with:

             RegAsm : error RA0000 : Could not load file or assembly
             'SolidWorks.Interop.swpublished, Version=32.5.0.48, ...'

         This is not redistribution: the files are copied from the local installation, on a
         machine that already has the seat, into extractor\**\bin\, which is not tracked.

      2. Run the 64-bit regasm with /codebase. The [ComRegisterFunction] in SwReviewAddIn.cs,
         which regasm invokes, writes the registry state SOLIDWORKS reads - both the HKLM
         SOLIDWORKS AddIns keys and, for the account running this script:

             HKCU\SOFTWARE\SOLIDWORKS\AddInsStartup\{5C4D2E7A-9B31-4A6E-8F0C-2D7B1E934A55} = 1

    So after a successful run SwReview is already ticked in Tools > Add-ins the next time
    SOLIDWORKS starts; there is no box to tick. A box that is clear there means the add-in
    failed to load - SOLIDWORKS clears that flag when it does - and the explanation is in
    %LOCALAPPDATA%\SwReview\logs\addin.log (docs\addin-load-fix.md).

    The one caveat is the elevated prompt: the flag is written under HKCU, so if this script
    ran as a different admin account than the one that uses SOLIDWORKS, it landed in that
    account's hive and the engineer does have to tick the box once.

    Build the solution first; this script registers what is already in the output folder.
    Close SOLIDWORKS before running it - a loaded add-in holds its own assembly open.

.PARAMETER SolidWorksRoot
    The SOLIDWORKS installation root. Its api\redist subfolder is where the interops come
    from. Defaults to the standard install location.

.PARAMETER Configuration
    The build configuration whose output is registered. Defaults to Release.

.PARAMETER Unregister
    Undo a registration: runs regasm /unregister instead of regasm /codebase. The staged
    interops are left in place - they are build output, and the folder is not tracked.

.EXAMPLE
    .\register-addin.ps1

.EXAMPLE
    .\register-addin.ps1 -Configuration Debug

.EXAMPLE
    .\register-addin.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string] $SolidWorksRoot = "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS",
    [string] $Configuration = "Release",
    [switch] $Unregister
)

$ErrorActionPreference = "Stop"

# regasm writes HKCR and HKLM. Checked before anything is copied, so a non-elevated run
# changes nothing at all rather than half of it.
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw ("register-addin.ps1 writes HKCR and HKLM and must run elevated. " +
           "Open an x64 'Windows PowerShell (Admin)' prompt and run it again.")
}

$addInDirectory = Join-Path $PSScriptRoot "..\SwReview.AddIn\bin\x64\$Configuration\net48"
if (-not (Test-Path $addInDirectory)) {
    throw ("No $Configuration build output at $addInDirectory. " +
           "Run: dotnet build extractor\SwReview.sln -c $Configuration")
}
$addInDirectory = (Resolve-Path $addInDirectory).Path

$addIn = Join-Path $addInDirectory "SwReview.AddIn.dll"
if (-not (Test-Path $addIn)) {
    throw "SwReview.AddIn.dll is not in $addInDirectory; build the solution first."
}

# Staged for the unregister too: regasm /unregister loads the assembly to reflect over it,
# so it needs the interops exactly as the register does.
$redist = Join-Path $SolidWorksRoot "api\redist"
if (-not (Test-Path $redist)) {
    throw ("No SOLIDWORKS interops at $redist. " +
           "Pass -SolidWorksRoot with the installation root of this seat.")
}

$interops = @(
    "SolidWorks.Interop.sldworks.dll",
    "SolidWorks.Interop.swconst.dll",
    "SolidWorks.Interop.swpublished.dll"
)

foreach ($interop in $interops) {
    $source = Join-Path $redist $interop
    if (-not (Test-Path $source)) {
        throw "$source is missing; this seat's api\redist does not carry the add-in's interops."
    }

    Copy-Item -Path $source -Destination $addInDirectory -Force
    Write-Host "staged  $interop -> $addInDirectory"
}

$regasm = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\regasm.exe"
if (-not (Test-Path $regasm)) {
    throw "The 64-bit regasm is not at $regasm; the add-in is x64 and the 32-bit one will not do."
}

if ($Unregister) {
    Write-Host "running $regasm /unregister $addIn"
    & $regasm /unregister $addIn
} else {
    Write-Host "running $regasm /codebase $addIn"
    & $regasm /codebase $addIn
}

if ($LASTEXITCODE -ne 0) {
    throw "regasm failed with exit code $LASTEXITCODE; nothing was registered."
}

if ($Unregister) {
    Write-Host "unregistered SwReview.AddIn. The staged interops were left in the output folder."
} else {
    Write-Host ("registered SwReview.AddIn, and enabled it for $($identity.Name): " +
                "SwReview should already be ticked in Tools > Add-ins when SOLIDWORKS starts.")
    Write-Host ("If the box is clear there, the add-in failed to load - read " +
                "%LOCALAPPDATA%\SwReview\logs\addin.log. If SOLIDWORKS runs as a different " +
                "account than this one, tick the box once for it.")
}
