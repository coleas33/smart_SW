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
    refusals) plus the named members below, each with its reason. Nothing is typed twice. The
    loader, the reading of the guard sources, the section 3 exclusions and the name formatting are
    shared with list-creation-members.ps1 (feature 004, decision 21A) through
    guard-table-helpers.ps1.

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

. (Join-Path $PSScriptRoot 'guard-table-helpers.ps1')

$extractor = Split-Path -Parent $PSScriptRoot

# ---- contracts/guard.md section 1: the families -------------------------------------------

# The last four, the hole callout's variables, joined on review (2026-09-23): the drawing read
# (SwDrawingReader.HoleCalloutVariables, T026) touches them, so every writer of theirs is refused.
$drawingFamilies = @(
    'IDrawingDoc', 'ISheet', 'IView', 'IDisplayDimension', 'IDimension', 'IDimensionTolerance',
    'IAnnotation', 'INote', 'IGtol', 'IGtolFrame', 'IDatumTag', 'ISFSymbol', 'ITableAnnotation',
    'IBomTableAnnotation', 'IBomFeature', 'IRevisionTableAnnotation', 'IGeneralTableFeature',
    'ITitleBlockTableFeature', 'ITitleBlock', 'IDatumTargetSym', 'ICenterMark', 'IWeldSymbol',
    'IDowelSymbol', 'IMultiJogLeader',
    'ICalloutVariable', 'ICalloutLengthVariable', 'ICalloutAngleVariable', 'ICalloutStringVariable'
)
$familyCount = $drawingFamilies.Count

# Decision 136A (2026-10-19) completed the rows: every member of the open, activate, new, load,
# close and quit families of ISldWorks, IModelDoc2 and IModelDocExtension, in every spelling the
# interop declares - the COM twins (IOpenDoc*, IActivateDoc*, INew*) and bare LoadFile, LoadAddIn and
# LoadAdminSettingsFile above all - is named below, and DocumentLifecycleFamilyTests (GuardTests.cs)
# reflects the interop with the family grammar to prove the rows complete. The members left allowed
# (OpenDoc6, OpenDoc7, CloseDoc, NewDocument) are named as well, so the "Not denied" table says why.
#
# Decision 140A (2026-10-19) refuses IModelDoc2's Close, which 136A had to leave allowed, and Save
# and Rebuild, IModelDocExtension's Rebuild with them: the bridge judges its commands against its own
# fixed set and no longer hands their names to ReadOnlyGuard, which had judged remodel.close,
# remodel.save and remodel.rebuild by their member halves.
#
# The same decision names every member of the save, rename, move and copy, replace, release and lock,
# read-only and rebuild families of these three interfaces and of IPartDoc, IAssemblyDoc and, on the
# decision's review, IFeatureManager (three rows more; the drawing families' are writers of their
# family rows already) that the guard did not refuse yet, and SaveBMP and MoveToFolder, which stay
# allowed for the reasons below. DocumentWriteFamilyTests (GuardTests.cs) reflects the interop with
# that family grammar to prove the rows complete. Three kinds of member are refused
# already and are not named here: those Guard/ReadOnlyGuard.cs denies (Save3, SaveAs3, SetSaveFlag,
# EditRebuild3, ForceRebuild3, ForceRebuildAll, and InsertFeatureReplaceFace by its InsertFeature
# prefix); those this table's drawing rows deny by a bare name the document types share (EditRebuild,
# ForceRebuild); and those decision 21A's creation table denies (MoveOrCopy, RotateOrCopy,
# ScaleOrCopy, SaveSelection) - list-creation-members.ps1 reads this table's names as already denied,
# so naming one here would move it out of that table.
$sharedRows = [ordered]@{
    'ISldWorks' = @(
        'ActivateDoc', 'ActivateDoc2', 'ActivateDoc3', 'DocumentVisible', 'CloseAllDocuments',
        'CloseAndReopen', 'CloseAndReopen2', 'QuitDoc', 'NewDocument', 'NewDrawing', 'NewDrawing2',
        'NewPart', 'NewAssembly', 'OpenDoc', 'OpenDoc2', 'OpenDoc3', 'OpenDoc4', 'OpenDoc7',
        'OpenDocSilent', 'OpenModelConfiguration', 'LoadFile2', 'LoadFile3', 'LoadFile4',
        'RunMacro', 'RunMacro2', 'RunCommand', 'RunAttachedMacro', 'RunJournalCmd',
        'IActivateDoc', 'IActivateDoc2', 'IActivateDoc3', 'IOpenDoc', 'IOpenDoc2', 'IOpenDoc3',
        'IOpenDoc4', 'IOpenDoc5', 'IOpenDocSilent', 'INewDocument', 'INewDocument2', 'INewDrawing',
        'INewDrawing2', 'INewPart', 'INewAssembly', 'LoadFile', 'LoadAddIn', 'LoadAdminSettingsFile',
        'UnloadAddIn', 'ExitApp', 'ActivateTaskPane', 'CloseUserNotification', 'CreateNewWindow',
        'PresetNewDrawingParameters', 'SetNewFilename', 'AddFileOpenItem', 'AddFileOpenItem2',
        'AddFileOpenItem3', 'RemoveFileOpenItem', 'RemoveFileOpenItem2', 'OpenDoc6', 'CloseDoc',
        'AddFileSaveAsItem', 'AddFileSaveAsItem2', 'RemoveFileSaveAsItem', 'RemoveFileSaveAsItem2',
        'RunBatchSaveProcess', 'SaveSettings', 'ShowBatchSaveTo3DExperienceDlg',
        'MoveDocument', 'IMoveDocument', 'CopyDocument', 'ICopyDocument', 'CopyAppearance',
        'ReplaceReferencedDocument'
    )
    'IModelDoc2' = @(
        'Close', 'Quit', 'FileReload', 'ReloadOrReplace', 'CloseFamilyTable', 'ClosePrintPreview',
        'ActivateSelectedFeature', 'ActivateFeatureMgrView', 'DeActivateFeatureMgrView',
        'Save', 'Rebuild',
        'Save2', 'SaveAs', 'SaveAs2', 'SaveAs4', 'SaveAsSilent', 'SaveSilent', 'SetSaveAsFileName',
        'SaveBMP', 'EditCopy', 'ForceReleaseLocks', 'IRelease3rdPartyStorage', 'Lock', 'UnLock',
        'LockAllExternalReferences', 'UnlockAllExternalReferences', 'LockFramePoint',
        'UnlockFramePoint', 'LockLightToModel', 'SetReadOnlyState'
    )
    'IModelDocExtension' = @(
        'SetUserPreferenceInteger', 'SetUserPreferenceString', 'SetUserPreferenceDouble',
        'SetUserPreferenceTextFormat', 'LoadDraftingStandard', 'ReloadOrReplace', 'CloseMessageBar',
        'CloseUserNotification',
        'Rebuild',
        'SaveAs', 'SaveAs2', 'SaveDeFeaturedFile', 'SaveDraftingStandard', 'SavePackAndGo',
        'SaveTo3DExperience', 'SaveViewToSolidworks', 'RenameDocument', 'RenameDraftingStandard',
        'MoveDecal', 'CopyDraftingStandard', 'IRelease3rdPartyStorageStore', 'ReleaseStream',
        'EditRebuildAll', 'set_ShowPartRebuildIndicators'
    )
    'IPartDoc' = @(
        'SaveToFile', 'SaveToFile2', 'SaveToFile3'
    )
    'IAssemblyDoc' = @(
        'SaveIsolate', 'CopyWithMates', 'CopyWithMates2', 'ReplaceComponents', 'ReplaceComponents2',
        'ReplacePLMComponents', 'ForceRebuild2', 'set_EnableAssemblyRebuild'
    )
    'IFeatureManager' = @(
        'MoveRotateLiveSectionPlane', 'set_MoveSizeFeatures', 'MoveToFolder'
    )
}

# ---- section 2: the writer grammar --------------------------------------------------------

$writerPattern = '^(set_|Set|ISet|Add|IAdd|Insert|IInsert|Delete|Remove|Edit|Modify|Change|Reset|' +
    'Activate|Attach|Detach|Update|Replace|Break|Hide|Show|Move|Align|Suppress|Unsuppress|Rebuild|' +
    'Convert|Create|ICreate|Make|Lock|Unlock|Sort|Split|Merge|Rotate|Scale|Flip|Link|Unlink|Import|' +
    'Explode|Clear|Apply|Restore|Save|Dissolve|Expand|Collapse|Reload|Rename|New|Paste|Copy|Cut|Drag|' +
    'Close|Quit|Open|Load|Unload|Regenerate|Reorder|Auto|Dimension|Reverse|Swap|Toggle|Enable|' +
    'Disable|Select|Purge|Relink|Resolve|Crop|Unbreak|Force|Hatch|Offset|Position|Freeze|Unfreeze)'

# The reader prefixes ($ReaderPrefixes, Test-Reader) are guard-table-helpers.ps1's.
function Test-Writer([string] $name) {
    if (Test-Reader $name) { return $false }
    return [regex]::IsMatch($name, $writerPattern)
}

# ---- section 3: the exclusions, each with its reason --------------------------------------

$guard = Read-GuardSources $extractor
$exclusions = New-GuardExclusions $guard
$exclusions['OpenDoc6'] = "the console attach's read-only open of a part or assembly (``SwSession.OpenReadOnly``), checked with ``IsOpenedReadOnly`` after it (decision 136A); the confirmed drawing's open calls the qualified key through its own allowlist guard (``contracts/confirmed-open.md``)"
$exclusions['OpenDoc7'] = "feature 004's open of the re-modeler's own copy (``remodel.open``, a bare read call site under ``RemodelGuard``) and ``probe remodel``'s reopen of its throwaway part; found by the read audit (T003)"
$exclusions['NewDocument'] = "``probe remodel``'s throwaway part (feature 004 T032, under ``RemodelProbeGuard``, which exempts only the members ``ReadOnlyGuard`` refused when it was written); found by the read audit (T003)"
$exclusions['SaveBMP'] = "the capture's image of a view (``SwCaptureView`` gates the bare name on the session's read-only gate, after ``CaptureService`` checked the image's extension with ``AssertSaveAs``): it writes a bitmap of the graphics window, which the capture turns into its PNG under the directory the host chose, and cannot write a document; ``SaveAs3``, which can, stays refused (decision 140A)"
$exclusions['MoveToFolder'] = "``probe remodel``'s PROBE-5, which moves a feature of its throwaway part into a folder (``SwRemodelProbeHost`` gates the bare name under ``RemodelProbeGuard``, which hands it to ``ReadOnlyGuard``, as it does ``NewDocument``); never the engineer's document, which ``probe remodel`` refuses to run beside. ``RemodelGuardTests`` keeps it as its example of a bare writer the denylist misses, the reason the re-modeler's writes are interface-qualified (decision 140A's review)"

function Test-AlreadyDenied([string] $name) {
    return (Test-DeniedBy $name $guard.BaseDenied $guard.BasePrefixes)
}

# ---- the reflection -----------------------------------------------------------------------

$assembly = Open-InteropMetadata $SwRedist

$version = $assembly.GetName().Version.ToString()
$rows = New-Object System.Collections.Generic.List[object]
$newNames = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$excludedSeen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
$grammarMatches = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)

foreach ($family in $drawingFamilies) {
    $refused = New-Object System.Collections.Generic.List[string]
    $already = New-Object System.Collections.Generic.List[string]
    foreach ($name in (Get-PublicMethodNames $assembly $family)) {
        if (-not (Test-Writer $name)) { continue }
        [void] $grammarMatches.Add($name)
        if ($exclusions.Contains($name)) { [void] $excludedSeen.Add($name); continue }
        if (Test-AlreadyDenied $name) { $already.Add($name) } else { $refused.Add($name); [void] $newNames.Add($name) }
    }
    $rows.Add([pscustomobject]@{ Interface = $family; Refused = $refused; Already = $already })
}

$sharedOut = New-Object System.Collections.Generic.List[object]
foreach ($entry in $sharedRows.GetEnumerator()) {
    $declared = Get-PublicMethodNames $assembly $entry.Key
    $refused = New-Object System.Collections.Generic.List[string]
    $already = New-Object System.Collections.Generic.List[string]
    foreach ($name in ($entry.Value | Sort-Object { $_ } -CaseSensitive)) {
        if ($declared -notcontains $name) { throw "$($entry.Key).$name is not on the $version interop; fix contracts/guard.md section 1." }
        if ($exclusions.Contains($name)) { [void] $excludedSeen.Add($name); continue }
        if (Test-AlreadyDenied $name) { $already.Add($name) } else { $refused.Add($name); [void] $newNames.Add($name) }
    }
    $sharedOut.Add([pscustomobject]@{ Interface = $entry.Key; Refused = $refused; Already = $already })
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
    $lines.Add("/// Feature 011 (T004, contracts/guard.md): every writer of the $familyCount drawing families and the named")
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
$out.Add("writer of the $familyCount drawing families and the named members of the $($sharedRows.Count) shared families")
$out.Add('(`011-drawing-context/contracts/guard.md`). **This section is generated, never transcribed**: it')
$out.Add('is the output of `extractor/tools/list-writer-members.ps1` over `SolidWorks.Interop.sldworks`')
$out.Add("$version, read as metadata, and ``Guard/ReadOnlyGuard.Drawing.cs`` is generated by the same run")
$out.Add('with `-CSharp`. `DrawingFamilyDenylistTests` (in `GuardTests.cs`) parses the table below and')
$out.Add('`DrawingFamilyCompletenessTests` reflects the interop to prove it complete. The "Already denied"')
$out.Add('column names members an earlier feature (or a denied prefix) refuses; they are not added twice.')
$out.Add("$($newNames.Count) names are new; $($grammarMatches.Count) distinct names match the writer grammar on the $familyCount families.")
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
$out.Add("Interfaces of the $familyCount whose every writer was already denied: " + (($rows | Where-Object { $_.Refused.Count -eq 0 -and $_.Already.Count -gt 0 } | ForEach-Object { "``$($_.Interface)`` ($(Format-Names $_.Already))" }) -join '; ') + '.')
$out.Add("Interfaces of the $familyCount with no writer on this interop: " + (($rows | Where-Object { $_.Refused.Count -eq 0 -and $_.Already.Count -eq 0 } | ForEach-Object { "``$($_.Interface)``" }) -join ', ') + '.')
$out.Add('')
$out.Add('| Not denied (feature 011) | Why |')
$out.Add('|---|---|')
$excludedSorted = [string[]] @($excludedSeen)
[Array]::Sort($excludedSorted, [StringComparer]::Ordinal)
foreach ($name in $excludedSorted) {
    $out.Add("| ``$name`` | $($exclusions[$name]) |")
}
$out | ForEach-Object { Write-Output $_ }
