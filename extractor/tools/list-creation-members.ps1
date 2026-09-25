<#
.SYNOPSIS
    Generates the owner's decision 21A read-only guard table (feature 004, T166) from the
    SOLIDWORKS interop: the creation family.

.DESCRIPTION
    Loads SolidWorks.Interop.sldworks from $SwRedist as METADATA ONLY (reflection-only load: no
    interop code runs and SOLIDWORKS is never started), applies the three rules of the "Decision
    21A" section of specs/004-resilient-remodeler/contracts/guard-allowlist.md to IFeatureManager,
    IModelDoc2, IPartDoc and IModelDocExtension, and prints either

      * the generated part of that section (the default), or
      * with -CSharp, the whole of extractor/SwReview.Extractor/Guard/ReadOnlyGuard.Creation.cs.

    Both come from the same run, so the table and the guard cannot drift apart. The output is
    pasted whole: the table is regenerated, never transcribed.

    What is "already denied" is read from the guard's own source - Guard/ReadOnlyGuard.cs (the
    quoted names of DeniedMemberSet and DeniedPrefixArray) and Guard/ReadOnlyGuard.Drawing.cs
    (feature 011's generated array) - and the structural exclusions from Guard/RemodelGuard.cs,
    through guard-table-helpers.ps1, which list-writer-members.ps1 shares. The reads the grammar
    reaches are named below, each with its reason. Nothing is typed twice. Because feature 011's
    array counts as already denied here, a new interop is regenerated in that order:
    list-writer-members.ps1 first, then this script.

.PARAMETER SwRedist
    The interop folder. Defaults to the path extractor/Directory.Build.props names.

.PARAMETER CSharp
    Print the generated C# file instead of the markdown.

.EXAMPLE
    powershell -NoProfile -File extractor/tools/list-creation-members.ps1 > table.md
    powershell -NoProfile -File extractor/tools/list-creation-members.ps1 -CSharp > ReadOnlyGuard.Creation.cs
#>
[CmdletBinding()]
param(
    [string] $SwRedist = 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist',
    [switch] $CSharp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'guard-table-helpers.ps1')

$extractor = Split-Path -Parent $PSScriptRoot

# ---- the families -------------------------------------------------------------------------

# The interfaces feature creation is reached through.
$creationFamilies = @('IFeatureManager', 'IModelDoc2', 'IPartDoc', 'IModelDocExtension')

# ---- rule 1: the creation grammar ---------------------------------------------------------

# Applied ordinally, after the reader prefixes. The optional I is a member's COM twin.
$creationPattern = '^I?(Feature|Insert|Create|Add|Mirror|Make|Sketch|SimpleHole|SimpleFeature|HoleWizard|AdvancedHole)'

function Test-Creation([string] $name) {
    if (Test-Reader $name) { return $false }
    return [regex]::IsMatch($name, $creationPattern)
}

# ---- rule 2: named creators the grammar does not reach ------------------------------------

# One entry per row of the generated table: the interface, its members, and what they build. Each
# member must be declared on its interface and must not be a grammar match, already denied or
# excluded; any of those means this list is wrong, and the run stops. The list is a reading of the
# API help, not a pattern, so no check here can prove it complete: on review (2026-09-25, T169) it
# was read again over every public method of the four that is neither a reader nor a grammar match
# and that the guard allowed, which added the last rows of each interface below.
$namedCreators = @(
    @{ Interface = 'IFeatureManager'; Members = @('PreSplitBody', 'PreSplitBody2', 'PostSplitBody', 'PostSplitBody2')
       Builds = 'the split-body feature, begun with `Pre` and finished with `Post`' }
    @{ Interface = 'IFeatureManager'; Members = @('PreTrimSurface', 'PostTrimSurface')
       Builds = 'the trim-surface feature, begun with `Pre` and finished with `Post`' }
    @{ Interface = 'IFeatureManager'; Members = @('PreIntersect', 'PreIntersect2', 'PostIntersect')
       Builds = 'the intersect feature, begun with `Pre` and finished with `Post`' }
    @{ Interface = 'IFeatureManager'; Members = @('FinishCornerRelief')
       Builds = 'the last call of the corner-relief builder begun with `AddCornerReliefType` and `AddCornerReliefCorner`' }
    @{ Interface = 'IFeatureManager'; Members = @('FinishSMNormalCut')
       Builds = 'the last call of the sheet-metal normal-cut builder begun with `AddSMNormalCutType` and `AddSMNormalCut`' }
    @{ Interface = 'IFeatureManager'; Members = @('EndVariablePitchHelix')
       Builds = 'the last call of the variable-pitch helix builder begun with `InsertVariablePitchHelix`' }
    @{ Interface = 'IFeatureManager'; Members = @('EditDeleteFace')
       Builds = 'deletes, patches or fills faces as a Delete Face feature: a builder named with an edit verb' }
    @{ Interface = 'IFeatureManager'; Members = @('ConvertLoftOrSweepToNetBlend')
       Builds = 'converts a loft or a sweep into a net blend feature' }
    @{ Interface = 'IFeatureManager'; Members = @('FilletXpertMakeCorner')
       Builds = 'a fillet corner feature, which FilletXpert creates or changes' }
    @{ Interface = 'IModelDoc2'; Members = @('PreTrimSurface', 'PostTrimSurface')
       Builds = 'the trim-surface feature, the obsolete `IModelDoc2` spelling of the pair' }
    @{ Interface = 'IModelDoc2'; Members = @('DeriveSketch')
       Builds = 'a derived sketch' }
    @{ Interface = 'IModelDoc2'; Members = @('Paste')
       Builds = 'pastes what the clipboard holds into the document' }
    @{ Interface = 'IModelDoc2'; Members = @('Scale')
       Builds = 'scales the part, as the refused `IFeatureManager.InsertScale` does' }
    @{ Interface = 'IModelDoc2'; Members = @('NameView')
       Builds = 'a named view of the current orientation, kept in the document' }
    @{ Interface = 'IModelDoc2'; Members = @('SkToolsAutoConstr')
       Builds = 'the relations that constrain the active sketch, which the refused `SketchAddConstraints` adds one call at a time' }
    @{ Interface = 'IModelDoc2'; Members = @('SplitOpenSegment', 'SplitClosedSegment')
       Builds = 'splits a sketch segment, adding the segments and points it is split into: the obsolete `IModelDoc2` spelling of the `ISketchManager` pair' }
    @{ Interface = 'IModelDocExtension'; Members = @('MoveOrCopy', 'RotateOrCopy', 'ScaleOrCopy')
       Builds = 'the move, rotate and scale body features, which can copy the bodies they move' }
    @{ Interface = 'IModelDocExtension'; Members = @('GeodesicSketchOffset')
       Builds = 'a geodesic sketch offset, the sibling of the refused, Euclidean `SketchOffsetOnSurface`' }
    @{ Interface = 'IModelDocExtension'; Members = @('SaveSelection')
       Builds = 'a selection set of the selected entities, kept in the document' }
    @{ Interface = 'IModelDocExtension'; Members = @('Capture3DView')
       Builds = 'a 3D View of the part or assembly, kept in the document' }
    @{ Interface = 'IModelDocExtension'; Members = @('BreakAllExternalFileReferences2')
       Builds = 'the original parts'' features, inserted when asked to, as it breaks every external reference' }
)

# ---- rule 3: the exclusions, each with its reason -----------------------------------------

$guard = Read-GuardSources $extractor
$drawingDenied = @(Get-QuotedNames (Join-Path $extractor 'SwReview.Extractor\Guard\ReadOnlyGuard.Drawing.cs') 'DrawingFamilyDeniedMembers =' '};')
if ($drawingDenied.Count -lt 100) { throw 'ReadOnlyGuard.Drawing.cs parsed as nearly empty; check the marker in this script.' }
$alreadyDeniedNames = @($guard.BaseDenied) + $drawingDenied

$exclusions = New-GuardExclusions $guard

# The reads the grammar reaches. Every one must be a grammar match on the four interfaces, or the
# run stops: a stale exclusion would hide a later interop's writer of the same name.
$reads = [ordered]@{
    'FeatureById'               = 'a lookup: returns the feature with a given id, already in the tree, and writes nothing'
    'IFeatureById'              = 'the COM twin of the lookup `FeatureById`'
    'FeatureByName'             = 'a lookup: returns the feature with a given name, already in the tree, and writes nothing'
    'IFeatureByName'            = 'the COM twin of the lookup `FeatureByName`'
    'FeatureByPositionReverse'  = 'a lookup: returns the feature at a position counted from the end of the tree, and writes nothing'
    'IFeatureByPositionReverse' = 'the COM twin of the lookup `FeatureByPositionReverse`'
    'FeatureFolderLocation'     = 'a lookup: returns the folder a feature sits in; feature 004''s `remodel.folder` verifies membership with it (`BridgeDispatcher`, `RemodelDocument`)'
    'CreateMassProperty'        = 'a read: returns the mass-property calculator `PropertyDumper` reads the mass override through; it writes nothing to the document'
    'CreateMassProperty2'       = 'a read: returns the mass-property calculator `PropertyDumper` reads mass and volume through, as the re-modeler''s geometry gate and PROBE-8 do; it writes nothing to the document'
    'CreateMeasure'             = 'a read: returns the measure tool `SwMeasureSource` reads distances through; it writes nothing to the document'
}
foreach ($entry in $reads.GetEnumerator()) {
    if ($exclusions.Contains($entry.Key)) { throw "$($entry.Key) is excluded twice; fix the reads list." }
    $exclusions[$entry.Key] = $entry.Value
}

function Test-AlreadyDenied([string] $name) {
    return (Test-DeniedBy $name $alreadyDeniedNames $guard.BasePrefixes)
}

# ---- the reflection -----------------------------------------------------------------------

$assembly = Open-InteropMetadata $SwRedist
$version = $assembly.GetName().Version.ToString()

$declaredBy = @{}
foreach ($family in $creationFamilies) { $declaredBy[$family] = Get-PublicMethodNames $assembly $family }

$rows = New-Object System.Collections.Generic.List[object]
$newNames = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$excludedSeen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$alreadySeen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$grammarMatches = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)

foreach ($family in $creationFamilies) {
    $refused = New-Object System.Collections.Generic.List[string]
    $already = New-Object System.Collections.Generic.List[string]
    foreach ($name in $declaredBy[$family]) {
        if (-not (Test-Creation $name)) { continue }
        [void] $grammarMatches.Add($name)
        # Already denied is asked first: a name an earlier table or a prefix refuses is not this
        # table's to leave allowed. InsertFeatureTreeFolder2 is the case - the bare name of a
        # stage-1 key, and refused by the InsertFeature prefix all along.
        if (Test-AlreadyDenied $name) { $already.Add($name); [void] $alreadySeen.Add($name); continue }
        if ($exclusions.Contains($name)) { [void] $excludedSeen.Add($name); continue }
        $refused.Add($name); [void] $newNames.Add($name)
    }
    $rows.Add([pscustomobject]@{ Interface = $family; Refused = $refused; Already = $already })
}

foreach ($name in $reads.Keys) {
    if (-not $grammarMatches.Contains($name)) { throw "$name is no creation-grammar match on the $version interop; drop it from the reads list." }
}

$namedNew = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($named in $namedCreators) {
    if ($creationFamilies -notcontains $named.Interface) { throw "$($named.Interface) is not one of the four interfaces." }
    foreach ($name in $named.Members) {
        $key = "$($named.Interface).$name"
        if ($declaredBy[$named.Interface] -notcontains $name) { throw "$key is not on the $version interop; fix the named creators." }
        if (Test-Creation $name) { throw "$key is a creation-grammar match; the grammar already reaches it." }
        if ($exclusions.Contains($name)) { throw "$key is excluded; a named creator is denied." }
        if (Test-AlreadyDenied $name) { throw "$key is already denied; drop it from the named creators." }
        [void] $namedNew.Add($name)
        [void] $newNames.Add($name)
    }
}

$sortedNew = [string[]] @($newNames)
[Array]::Sort($sortedNew, [StringComparer]::Ordinal)

if ($CSharp) {
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add('// Generated by extractor/tools/list-creation-members.ps1 from SolidWorks.Interop.sldworks')
    $lines.Add("// $version (metadata only). Do not edit by hand: regenerate, and paste the markdown of the")
    $lines.Add('// same run into the "Decision 21A" section of specs/004-resilient-remodeler/contracts/guard-allowlist.md.')
    $lines.Add('')
    $lines.Add('namespace SwReview.Extractor.Guard;')
    $lines.Add('')
    $lines.Add('/// <summary>')
    $lines.Add('/// Decision 21A (feature 004, 2026-09-25, the owner): the creation family of IFeatureManager,')
    $lines.Add('/// IModelDoc2, IPartDoc and IModelDocExtension - every creation-grammar match and named creator')
    $lines.Add('/// no earlier table or denied prefix refused - generated from the 2024 SP5 interop and merged into')
    $lines.Add('/// <see cref="ReadOnlyGuard"/>''s denied set by its static constructor. The "Decision 21A" tables of')
    $lines.Add('/// guard-allowlist.md are the same run''s markdown; CreationFamilyDenylistTests parses them and')
    $lines.Add('/// CreationFamilyCompletenessTests reflects the interop to prove them complete. Only')
    $lines.Add('/// <see cref="RemodelProbeGuard"/> exempts any of them, for the throwaway part it builds.')
    $lines.Add('/// </summary>')
    $lines.Add('public static partial class ReadOnlyGuard')
    $lines.Add('{')
    $lines.Add('    /// <summary>The generated decision 21A denials, bare names in ordinal order.</summary>')
    $lines.Add('    private static readonly string[] CreationFamilyDeniedMembers =')
    $lines.Add('    {')
    foreach ($name in $sortedNew) { $lines.Add("        `"$name`",") }
    $lines.Add('    };')
    $lines.Add('}')
    $lines | ForEach-Object { Write-Output $_ }
    return
}

$grammarNew = $newNames.Count - $namedNew.Count
$out = New-Object System.Collections.Generic.List[string]
$out.Add('**The generated tables (decision 21A).** This part is **generated, never transcribed**: it is the')
$out.Add('output of `extractor/tools/list-creation-members.ps1` over `SolidWorks.Interop.sldworks`')
$out.Add("$version, read as metadata, and ``Guard/ReadOnlyGuard.Creation.cs`` is generated by the same run with")
$out.Add('`-CSharp`. `CreationFamilyDenylistTests` (in `CreationFamilyGuardTests.cs`) parses the three tables')
$out.Add('below and `CreationFamilyCompletenessTests` reflects the interop to prove them complete. The')
$out.Add('"already denied" column names members an earlier table or a denied prefix refuses; they are not')
$out.Add("added twice. On the four interfaces $($grammarMatches.Count) distinct names match the creation grammar:")
$out.Add("$($alreadySeen.Count) already denied, $($excludedSeen.Count) left allowed and $grammarNew new; the named creators add $($namedNew.Count),")
$out.Add("so the tables deny $($newNames.Count) new names.")
$out.Add('')
$out.Add('| Members refused (decision 21A) | Interface; already denied |')
$out.Add('|---|---|')
foreach ($row in $rows) {
    # A row names at least one new member: DenylistTable.Parse refuses a row that has none.
    if ($row.Refused.Count -eq 0) { throw "$($row.Interface) has no new creation member; the table's shape assumes one." }
    $out.Add("| $(Format-Names $row.Refused) | ``$($row.Interface)``; already denied: $(Format-Names $row.Already) |")
}
$out.Add('')
$out.Add('| Named creators refused (decision 21A) | Interface; what it builds |')
$out.Add('|---|---|')
foreach ($named in $namedCreators) {
    $out.Add("| $(Format-Names $named.Members) | ``$($named.Interface)``; $($named.Builds) |")
}
$out.Add('')
$out.Add('| Not denied (decision 21A) | Why |')
$out.Add('|---|---|')
$excludedSorted = [string[]] @($excludedSeen)
[Array]::Sort($excludedSorted, [StringComparer]::Ordinal)
foreach ($name in $excludedSorted) {
    $out.Add("| ``$name`` | $($exclusions[$name]) |")
}
$out | ForEach-Object { Write-Output $_ }
