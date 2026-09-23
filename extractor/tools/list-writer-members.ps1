<#
.SYNOPSIS
    Generates feature 011's read-only guard table from the SOLIDWORKS interop (T004).

.DESCRIPTION
    Loads SolidWorks.Interop.sldworks from $SwRedist as METADATA ONLY (reflection-only load: no
    interop code runs and SOLIDWORKS is never started), applies sections 1 to 3 of
    specs/011-drawing-context/contracts/guard.md, and prints either

      * the "Feature 011" section of specs/004-resilient-remodeler/contracts/guard-allowlist.md
        (the default), or
      * with -CSharp, the whole of extractor/SwReview.Extractor/Guard/ReadOnlyGuard.Drawing.cs.

    Both come from the same run, so the table and the guard cannot drift apart. The output is
    pasted whole: the table is regenerated, never transcribed.

    What is "already denied" is read from the guard's own source, Guard/ReadOnlyGuard.cs (the
    quoted names of DeniedMemberSet and DeniedPrefixArray), and the exclusions of section 3 from
    Guard/RemodelGuard.cs (the bare names of the stage-1 allowlist keys and RemodelGuard's own
    refusals) plus the named members below, each with its reason. Nothing is typed twice.

.PARAMETER SwRedist
    The interop folder. Defaults to the path extractor/Directory.Build.props names.

.PARAMETER CSharp
    Print the generated C# file instead of the markdown section.

.EXAMPLE
    powershell -NoProfile -File extractor/tools/list-writer-members.ps1 > table.md
    powershell -NoProfile -File extractor/tools/list-writer-members.ps1 -CSharp > ReadOnlyGuard.Drawing.cs
#>
[CmdletBinding()]
param(
    [string] $SwRedist = 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist',
    [switch] $CSharp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$extractor = Split-Path -Parent $PSScriptRoot
$guardSource = Join-Path $extractor 'SwReview.Extractor\Guard\ReadOnlyGuard.cs'
$remodelSource = Join-Path $extractor 'SwReview.Extractor\Guard\RemodelGuard.cs'

# ---- contracts/guard.md section 1: the families -------------------------------------------

$drawingFamilies = @(
    'IDrawingDoc', 'ISheet', 'IView', 'IDisplayDimension', 'IDimension', 'IDimensionTolerance',
    'IAnnotation', 'INote', 'IGtol', 'IGtolFrame', 'IDatumTag', 'ISFSymbol', 'ITableAnnotation',
    'IBomTableAnnotation', 'IBomFeature', 'IRevisionTableAnnotation', 'IGeneralTableFeature',
    'ITitleBlockTableFeature', 'ITitleBlock', 'IDatumTargetSym', 'ICenterMark', 'IWeldSymbol',
    'IDowelSymbol', 'IMultiJogLeader'
)

$sharedRows = [ordered]@{
    'ISldWorks' = @(
        'ActivateDoc', 'ActivateDoc2', 'ActivateDoc3', 'DocumentVisible', 'CloseAllDocuments',
        'CloseAndReopen', 'CloseAndReopen2', 'QuitDoc', 'NewDocument', 'NewDrawing', 'NewDrawing2',
        'NewPart', 'NewAssembly', 'OpenDoc', 'OpenDoc2', 'OpenDoc3', 'OpenDoc4', 'OpenDoc7',
        'OpenDocSilent', 'OpenModelConfiguration', 'LoadFile2', 'LoadFile3', 'LoadFile4',
        'RunMacro', 'RunMacro2', 'RunCommand', 'RunAttachedMacro', 'RunJournalCmd'
    )
    'IModelDocExtension' = @(
        'SetUserPreferenceInteger', 'SetUserPreferenceString', 'SetUserPreferenceDouble',
        'SetUserPreferenceTextFormat'
    )
}

# ---- section 2: the writer grammar --------------------------------------------------------

$readerPrefixes = @('get_', 'Get', 'IGet', 'Is')
$writerPattern = '^(set_|Set|ISet|Add|IAdd|Insert|IInsert|Delete|Remove|Edit|Modify|Change|Reset|' +
    'Activate|Attach|Detach|Update|Replace|Break|Hide|Show|Move|Align|Suppress|Unsuppress|Rebuild|' +
    'Convert|Create|ICreate|Make|Lock|Unlock|Sort|Split|Merge|Rotate|Scale|Flip|Link|Unlink|Import|' +
    'Explode|Clear|Apply|Restore|Save|Dissolve|Expand|Collapse|Reload|Rename|New|Paste|Copy|Cut|Drag|' +
    'Close|Quit|Open|Load|Unload|Regenerate|Reorder|Auto|Dimension|Reverse|Swap|Toggle|Enable|' +
    'Disable|Select|Purge|Relink|Resolve|Crop|Unbreak|Force|Hatch|Offset|Position|Freeze|Unfreeze)'

function Test-Writer([string] $name) {
    foreach ($prefix in $readerPrefixes) {
        if ($name.StartsWith($prefix, [StringComparison]::Ordinal)) { return $false }
    }
    return [regex]::IsMatch($name, $writerPattern)
}

# ---- section 3: the exclusions, each with its reason --------------------------------------

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

$baseDenied = Get-QuotedNames $guardSource 'DeniedMemberSet = new HashSet' '};'
$basePrefixes = Get-QuotedNames $guardSource 'DeniedPrefixArray =' '};'
$stageOneKeys = Get-QuotedNames $remodelSource 'AllowedKeySet = new HashSet' '};'
$remodelRefusals = Get-QuotedNames $remodelSource 'ExcludedMemberSet = new HashSet' '};'

if ($baseDenied.Count -lt 50 -or $basePrefixes.Count -lt 1 -or $stageOneKeys.Count -lt 10) {
    throw 'The guard sources parsed as nearly empty; check the markers in this script.'
}

$exclusions = [ordered]@{}
foreach ($key in $stageOneKeys) {
    $bare = $key.Substring($key.LastIndexOf('.') + 1)
    $exclusions[$bare] = "the bare name of feature 004's stage-1 allowlist key ``$key``; denying it would make that key override a read-only denial and move ``Allowlist_KeysOverridingAReadOnlyDenial_AreExactlyTheDeclaredFive``"
}
foreach ($member in $remodelRefusals) {
    $exclusions[$member] = "refused by feature 004's ``RemodelGuard`` itself (``ExcludedMembers``), whose test asserts ``ReadOnlyGuard`` does not refuse it"
}
$exclusions['OpenDoc6'] = "the extractor's one sanctioned read-only open of a model (``SwSession.OpenReadOnly``); the confirmed drawing's open calls the qualified key through its own allowlist guard (``contracts/confirmed-open.md``)"
$exclusions['OpenDoc7'] = "feature 004's open of the re-modeler's own copy (``remodel.open``, a bare read call site under ``RemodelGuard``) and ``probe remodel``'s reopen of its throwaway part; found by the read audit (T003)"
$exclusions['NewDocument'] = "``probe remodel``'s throwaway part (feature 004 T032, under ``RemodelProbeGuard``, which exempts only the members ``ReadOnlyGuard`` refused when it was written); found by the read audit (T003)"

function Test-AlreadyDenied([string] $name) {
    if ($baseDenied -contains $name) { return $true }   # -contains is case-insensitive, as the guard is
    foreach ($prefix in $basePrefixes) {
        if ($name.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

# ---- the reflection -----------------------------------------------------------------------

$interop = Join-Path $SwRedist 'SolidWorks.Interop.sldworks.dll'
if (-not (Test-Path $interop)) { throw "No interop at '$interop'; pass -SwRedist." }

$resolve = [ResolveEventHandler] {
    param($sender, $eventArgs)
    $name = (New-Object Reflection.AssemblyName $eventArgs.Name).Name
    $candidate = Join-Path $SwRedist "$name.dll"
    if (Test-Path $candidate) { return [Reflection.Assembly]::ReflectionOnlyLoadFrom($candidate) }
    return [Reflection.Assembly]::ReflectionOnlyLoad($eventArgs.Name)
}
[AppDomain]::CurrentDomain.add_ReflectionOnlyAssemblyResolve($resolve)
$assembly = [Reflection.Assembly]::ReflectionOnlyLoadFrom($interop)

function Get-PublicMethodNames([string] $interfaceName) {
    $type = $assembly.GetType("SolidWorks.Interop.sldworks.$interfaceName", $true)
    return @($type.GetMethods([Reflection.BindingFlags]'Public, Instance') |
        ForEach-Object { $_.Name } | Sort-Object -Unique)
}

$version = $assembly.GetName().Version.ToString()
$rows = New-Object System.Collections.Generic.List[object]
$newNames = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$excludedSeen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$grammarMatches = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)

foreach ($family in $drawingFamilies) {
    $refused = New-Object System.Collections.Generic.List[string]
    $already = New-Object System.Collections.Generic.List[string]
    foreach ($name in (Get-PublicMethodNames $family)) {
        if (-not (Test-Writer $name)) { continue }
        [void] $grammarMatches.Add($name)
        if ($exclusions.Contains($name)) { [void] $excludedSeen.Add($name); continue }
        if (Test-AlreadyDenied $name) { $already.Add($name) } else { $refused.Add($name); [void] $newNames.Add($name) }
    }
    $rows.Add([pscustomobject]@{ Interface = $family; Refused = $refused; Already = $already })
}

$sharedOut = New-Object System.Collections.Generic.List[object]
foreach ($entry in $sharedRows.GetEnumerator()) {
    $declared = Get-PublicMethodNames $entry.Key
    $refused = New-Object System.Collections.Generic.List[string]
    $already = New-Object System.Collections.Generic.List[string]
    foreach ($name in ($entry.Value | Sort-Object { $_ } -CaseSensitive)) {
        if ($declared -notcontains $name) { throw "$($entry.Key).$name is not on the $version interop; fix contracts/guard.md section 1." }
        if ($exclusions.Contains($name)) { [void] $excludedSeen.Add($name); continue }
        if (Test-AlreadyDenied $name) { $already.Add($name) } else { $refused.Add($name); [void] $newNames.Add($name) }
    }
    $sharedOut.Add([pscustomobject]@{ Interface = $entry.Key; Refused = $refused; Already = $already })
}

function Format-Names($names) {
    if ($names.Count -eq 0) { return '-' }
    $sorted = [string[]] @($names)
    [Array]::Sort($sorted, [StringComparer]::Ordinal)
    return (($sorted | ForEach-Object { "``$_``" }) -join ', ')
}

$sortedNew = [string[]] @($newNames)
[Array]::Sort($sortedNew, [StringComparer]::Ordinal)

if ($CSharp) {
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add('// Generated by extractor/tools/list-writer-members.ps1 from SolidWorks.Interop.sldworks')
    $lines.Add("// $version (metadata only). Do not edit by hand: regenerate, and paste the markdown section")
    $lines.Add('// of the same run into specs/004-resilient-remodeler/contracts/guard-allowlist.md.')
    $lines.Add('')
    $lines.Add('namespace SwReview.Extractor.Guard;')
    $lines.Add('')
    $lines.Add('/// <summary>')
    $lines.Add('/// Feature 011 (T004, contracts/guard.md): every writer of the 24 drawing families and the named')
    $lines.Add('/// members of the shared families, generated from the 2024 SP5 interop and merged into')
    $lines.Add('/// <see cref="ReadOnlyGuard"/>''s denied set by its static constructor. The "Feature 011" table of')
    $lines.Add('/// guard-allowlist.md is the same run''s markdown; DrawingFamilyDenylistTests parses it and')
    $lines.Add('/// DrawingFamilyCompletenessTests reflects the interop to prove it complete.')
    $lines.Add('/// </summary>')
    $lines.Add('public static partial class ReadOnlyGuard')
    $lines.Add('{')
    $lines.Add('    /// <summary>The generated feature 011 denials, bare names in ordinal order.</summary>')
    $lines.Add('    private static readonly string[] DrawingFamilyDeniedMembers =')
    $lines.Add('    {')
    foreach ($name in $sortedNew) { $lines.Add("        `"$name`",") }
    $lines.Add('    };')
    $lines.Add('}')
    $lines | ForEach-Object { Write-Output $_ }
    return
}

$out = New-Object System.Collections.Generic.List[string]
$out.Add('**Feature 011 (drawing context, read only)** refuses, before any new drawing read lands, every')
$out.Add('writer of the 24 drawing families and the named members of the two shared families')
$out.Add('(`011-drawing-context/contracts/guard.md`). **This section is generated, never transcribed**: it')
$out.Add('is the output of `extractor/tools/list-writer-members.ps1` over `SolidWorks.Interop.sldworks`')
$out.Add("$version, read as metadata, and ``Guard/ReadOnlyGuard.Drawing.cs`` is generated by the same run")
$out.Add('with `-CSharp`. `DrawingFamilyDenylistTests` (in `GuardTests.cs`) parses the table below and')
$out.Add('`DrawingFamilyCompletenessTests` reflects the interop to prove it complete. The "Already denied"')
$out.Add('column names members an earlier feature (or a denied prefix) refuses; they are not added twice.')
$out.Add("$($newNames.Count) names are new; $($grammarMatches.Count) distinct names match the writer grammar on the 24 families.")
$out.Add('')
$out.Add('| Members refused (feature 011) | Interface; already denied |')
$out.Add('|---|---|')
$allRows = New-Object System.Collections.Generic.List[object]
foreach ($row in $rows) { $allRows.Add($row) }
foreach ($row in $sharedOut) { $allRows.Add($row) }
foreach ($row in $allRows) {
    # A row names at least one new member: DenylistTable.Parse reads the members from the first
    # cell and refuses a row that has none, so an interface whose writers are all denied already
    # is named in the sentence below instead.
    if ($row.Refused.Count -eq 0) { continue }
    $out.Add("| $(Format-Names $row.Refused) | ``$($row.Interface)``; already denied: $(Format-Names $row.Already) |")
}
$out.Add('')
$out.Add('Interfaces of the 24 whose every writer was already denied: ' + (($rows | Where-Object { $_.Refused.Count -eq 0 -and $_.Already.Count -gt 0 } | ForEach-Object { "``$($_.Interface)`` ($(Format-Names $_.Already))" }) -join '; ') + '.')
$out.Add('Interfaces of the 24 with no writer on this interop: ' + (($rows | Where-Object { $_.Refused.Count -eq 0 -and $_.Already.Count -eq 0 } | ForEach-Object { "``$($_.Interface)``" }) -join ', ') + '.')
$out.Add('')
$out.Add('| Not denied (feature 011) | Why |')
$out.Add('|---|---|')
$excludedSorted = [string[]] @($excludedSeen)
[Array]::Sort($excludedSorted, [StringComparer]::Ordinal)
foreach ($name in $excludedSorted) {
    $out.Add("| ``$name`` | $($exclusions[$name]) |")
}
$out | ForEach-Object { Write-Output $_ }
