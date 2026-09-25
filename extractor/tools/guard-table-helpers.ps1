<#
.SYNOPSIS
    What the read-only guard's table generators share. Dot-sourced by them; never run on its own.

.DESCRIPTION
    Two scripts generate a denial table for specs/004-resilient-remodeler/contracts/guard-allowlist.md
    and the C# block of the same run:

      * list-writer-members.ps1 - feature 011, every writer of the drawing families;
      * list-creation-members.ps1 - feature 004, the owner's decision 21A, the creation family.

    Both read SolidWorks.Interop.sldworks as METADATA ONLY (a reflection-only load: no interop code
    runs and SOLIDWORKS is never started), both read what is already denied from the guard's own
    source, and both apply the exclusions of specs/011-drawing-context/contracts/guard.md section 3.
    Those pieces live here, once, so the two tables cannot disagree about them.
#>

Set-StrictMode -Version Latest

# 011 contracts/guard.md section 2: a name starting with one of these is a reader, whatever else it
# matches. Both grammars check it first.
$ReaderPrefixes = @('get_', 'Get', 'IGet', 'Is')

function Test-Reader([string] $name) {
    foreach ($prefix in $ReaderPrefixes) {
        if ($name.StartsWith($prefix, [StringComparison]::Ordinal)) { return $true }
    }
    return $false
}

# ---- the guard's own source ---------------------------------------------------------------

function Get-QuotedNames([string] $path, [string] $startMarker, [string] $endMarker) {
    $text = [IO.File]::ReadAllText($path)
    $start = $text.IndexOf($startMarker, [StringComparison]::Ordinal)
    if ($start -lt 0) { throw "'$startMarker' not found in $path" }
    $end = $text.IndexOf($endMarker, $start, [StringComparison]::Ordinal)
    if ($end -lt 0) { throw "'$endMarker' not found after '$startMarker' in $path" }
    $block = $text.Substring($start, $end - $start)
    # Comments are dropped first, so a name quoted in a comment is not a denial.
    $block = [regex]::Replace($block, '//[^\r\n]*', '')
    return @([regex]::Matches($block, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value })
}

<#
    The quoted names of ReadOnlyGuard.cs (DeniedMemberSet, DeniedPrefixArray) and RemodelGuard.cs
    (the stage-1 allowlist keys, and RemodelGuard's own refusals), read from the files themselves so
    nothing is typed twice. $extractor is the folder holding SwReview.sln.
#>
function Read-GuardSources([string] $extractor) {
    $guardSource = Join-Path $extractor 'SwReview.Extractor\Guard\ReadOnlyGuard.cs'
    $remodelSource = Join-Path $extractor 'SwReview.Extractor\Guard\RemodelGuard.cs'

    $sources = [pscustomobject]@{
        BaseDenied      = @(Get-QuotedNames $guardSource 'DeniedMemberSet = new HashSet' '};')
        BasePrefixes    = @(Get-QuotedNames $guardSource 'DeniedPrefixArray =' '};')
        StageOneKeys    = @(Get-QuotedNames $remodelSource 'AllowedKeySet = new HashSet' '};')
        RemodelRefusals = @(Get-QuotedNames $remodelSource 'ExcludedMemberSet = new HashSet' '};')
    }

    if ($sources.BaseDenied.Count -lt 50 -or $sources.BasePrefixes.Count -lt 1 -or $sources.StageOneKeys.Count -lt 10) {
        throw 'The guard sources parsed as nearly empty; check the markers in this script.'
    }

    return $sources
}

<#
    011 contracts/guard.md section 3's two structural exclusions, each with its reason: the bare name
    of a stage-1 allowlist key, and a member RemodelGuard refuses itself. A generator adds its own
    named exclusions to the dictionary this returns.
#>
function New-GuardExclusions($sources) {
    $exclusions = [ordered]@{}
    foreach ($key in $sources.StageOneKeys) {
        $bare = $key.Substring($key.LastIndexOf('.') + 1)
        $exclusions[$bare] = "the bare name of feature 004's stage-1 allowlist key ``$key``; denying it would make that key override a read-only denial and move ``Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredFive``"
    }
    foreach ($member in $sources.RemodelRefusals) {
        $exclusions[$member] = "refused by feature 004's ``RemodelGuard`` itself (``ExcludedMembers``), whose test asserts ``ReadOnlyGuard`` does not refuse it"
    }
    return $exclusions
}

# True when $name is on $deniedNames (case-insensitively, as the guard matches) or starts with one of
# $deniedPrefixes.
function Test-DeniedBy([string] $name, $deniedNames, $deniedPrefixes) {
    if ($deniedNames -contains $name) { return $true }   # -contains is case-insensitive, as the guard is
    foreach ($prefix in $deniedPrefixes) {
        if ($name.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

# ---- the reflection -----------------------------------------------------------------------

<#
    Loads SolidWorks.Interop.sldworks from $redist for its metadata only, resolving the assemblies it
    references from the same folder.
#>
function Open-InteropMetadata([string] $redist) {
    $interop = Join-Path $redist 'SolidWorks.Interop.sldworks.dll'
    if (-not (Test-Path $interop)) { throw "No interop at '$interop'; pass -SwRedist." }

    # The handler runs later, whenever reflection meets a referenced assembly, after this function
    # has returned; GetNewClosure gives it its own copy of $redist.
    $handler = {
        param($sender, $eventArgs)
        $name = (New-Object Reflection.AssemblyName $eventArgs.Name).Name
        $candidate = Join-Path $redist "$name.dll"
        if (Test-Path $candidate) { return [Reflection.Assembly]::ReflectionOnlyLoadFrom($candidate) }
        return [Reflection.Assembly]::ReflectionOnlyLoad($eventArgs.Name)
    }.GetNewClosure()
    [AppDomain]::CurrentDomain.add_ReflectionOnlyAssemblyResolve([ResolveEventHandler] $handler)

    return [Reflection.Assembly]::ReflectionOnlyLoadFrom($interop)
}

function Get-PublicMethodNames($assembly, [string] $interfaceName) {
    $type = $assembly.GetType("SolidWorks.Interop.sldworks.$interfaceName", $true)
    return @($type.GetMethods([Reflection.BindingFlags]'Public, Instance') |
        ForEach-Object { $_.Name } | Sort-Object -Unique)
}

# ---- the output ---------------------------------------------------------------------------

# Backticked names in ordinal order, comma-separated; '-' for none.
function Format-Names($names) {
    if ($names.Count -eq 0) { return '-' }
    $sorted = [string[]] @($names)
    [Array]::Sort($sorted, [StringComparer]::Ordinal)
    return (($sorted | ForEach-Object { "``$_``" }) -join ', ')
}
