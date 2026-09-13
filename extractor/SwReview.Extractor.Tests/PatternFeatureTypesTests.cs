using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using SwReview.Extractor.Dump;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// Pins ComponentTreeDumper.PatternFeatureTypes, the set of GetTypeName2 names the
/// component-tree walk accepts as an assembly component pattern.
///
/// A wrong or missing name here fails silently, which is why it is worth pinning: the
/// pattern feature is simply not recognised, PatternId stays null, the grouping that
/// collapses N identical fastener findings into one never happens, and the "pattern
/// listed no component instances" gap never fires either. There is no exception, no gap,
/// and no log line to notice.
///
/// The set is private, so it is read by reflection rather than by widening the production
/// surface for a test. If the field is renamed this test fails loudly, which is intended.
/// </summary>
public class PatternFeatureTypesTests
{
    // PROVENANCE for the expected set, reproduced 2026-09-13 on the pilot workstation
    // (SOLIDWORKS 2024 SP5, C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS). The 2024 help
    // page that publishes the GetTypeName2 table is not reachable from this machine, and a
    // hand-transcribed copy of it would be unauditable, so the citable source is the
    // installed binaries. Each command below is one line so it can be pasted into
    // powershell.exe as-is; no network and no SOLIDWORKS session is needed.
    //
    // (1) Internal feature classes in the assembly module. SOLIDWORKS names these
    //     mo<TypeName>_c, and the API module's string table (command 2) confirms the
    //     mo<X>_c -> "<X>" correspondence for every name that appears in both.
    //
    //     powershell -NoProfile -Command "$b=[IO.File]::ReadAllBytes('C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldasmu.dll'); $a=[Text.Encoding]::ASCII.GetString($b); $u=[Text.Encoding]::Unicode.GetString($b); foreach($n in 'moLocalChainPattern_c','moChainPatternFeat_c','moMirrorCompFeat_c','moMirrorComponent_c','moDerivedCirPattern_c','moTablePattern_c'){'{0,-22} ascii={1} utf16={2}' -f $n,[regex]::Matches($a,$n).Count,[regex]::Matches($u,$n).Count}"
    //
    //     moLocalChainPattern_c  ascii=7  utf16=0
    //     moChainPatternFeat_c   ascii=0  utf16=0
    //     moMirrorCompFeat_c     ascii=19 utf16=0
    //     moMirrorComponent_c    ascii=0  utf16=0
    //     moDerivedCirPattern_c  ascii=2  utf16=0
    //     moTablePattern_c       ascii=4  utf16=0
    //
    //     The class names are stored as ASCII; the utf16 column is zero throughout and is
    //     printed only to show that the UTF-16 encoding was searched as well.
    //
    // (2) The bare type-name strings in the API module, decoded BOTH ways the way command
    //     (1) is, and matched on identifier boundaries so a hit inside a longer identifier
    //     does not count. The lookbehind/lookahead pair below is written out in full in the
    //     pasted command; it is the regex (?<![A-Za-z0-9_]) NAME (?![A-Za-z0-9_]).
    //
    //     powershell -NoProfile -Command "$b=[IO.File]::ReadAllBytes('C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldapiu.dll'); $a=[Text.Encoding]::ASCII.GetString($b); $u=[Text.Encoding]::Unicode.GetString($b); foreach($n in 'LocalChainPattern','ChainPatternFeat','MirrorCompFeat','MirrorComponent'){'{0,-18} raw ascii={1,3} utf16={2}   boundary ascii={3} utf16={4}' -f $n,[regex]::Matches($a,$n).Count,[regex]::Matches($u,$n).Count,[regex]::Matches($a,'(?<![A-Za-z0-9_])'+$n+'(?![A-Za-z0-9_])').Count,[regex]::Matches($u,'(?<![A-Za-z0-9_])'+$n+'(?![A-Za-z0-9_])').Count}"
    //
    //     LocalChainPattern  raw ascii=  5 utf16=1   boundary ascii=0 utf16=1
    //     ChainPatternFeat   raw ascii= 94 utf16=0   boundary ascii=0 utf16=0
    //     MirrorCompFeat     raw ascii=  4 utf16=0   boundary ascii=0 utf16=0
    //     MirrorComponent    raw ascii=107 utf16=1   boundary ascii=0 utf16=0
    //
    //     The boundary-matched count is zero in BOTH encodings for every name here except
    //     the one UTF-16 LocalChainPattern hit. That hit sits inside a contiguous UTF-16
    //     run of type names that follows swFeatureNameID_e exactly - "CurvePattern
    //     SketchPattern APattern TablePattern DimPattern LocalLPattern LocalCirPattern
    //     LocalCurvePattern LocalSketchPattern LocalChainPattern GroundPlane", i.e. ids
    //     103..113 in order.
    //
    //     The large raw ASCII counts are NOT type names. They are substrings of longer C++
    //     symbol names, which is what command (2b) prints: ChainPatternFeat's 94 raw hits
    //     are dominated by auChainPatternFeatureData_c (91) and MirrorComponent's 107 by
    //     auMirrorComponentFeatureData_c (97) - i.e. the IChainPatternFeatureData /
    //     IMirrorComponentFeatureData interface column of the GetTypeName2 table, not the
    //     type-name column. The single raw UTF-16 MirrorComponent hit is inside the
    //     unrelated string "MirrorComponentsFolderLocation".
    //
    // (2b) What the raw ASCII hits are actually inside, top three containers per name.
    //
    //     powershell -NoProfile -Command "$b=[IO.File]::ReadAllBytes('C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldapiu.dll'); $a=[Text.Encoding]::ASCII.GetString($b); foreach($n in 'ChainPatternFeat','MirrorComponent'){[regex]::Matches($a,'[A-Za-z0-9_]*'+$n+'[A-Za-z0-9_]*') | ForEach-Object {$_.Value} | Group-Object | Sort-Object Count -Descending | Select-Object -First 3 | ForEach-Object {'{0,4}  {1}' -f $_.Count,$_.Name}}"
    //
    //       91  auChainPatternFeatureData_c
    //        1  AVauChainPatternFeatureData_c
    //        1  AUIChainPatternFeatureData
    //       97  auMirrorComponentFeatureData_c
    //        1  classauMirrorComponentFeatureData_c
    //        1  iApiMirrorComponents4
    //
    // (3) The installed enum, which is the cross-check these names are NOT corroborated by:
    //
    //     powershell -NoProfile -Command "$t=[Reflection.Assembly]::LoadFrom('C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.swconst.dll').GetType('SolidWorks.Interop.swconst.swFeatureNameID_e'); [Enum]::GetNames($t) | Where-Object {$_ -match 'Pattern|Mirror'} | ForEach-Object {'{0} = {1}' -f $_,[int][Enum]::Parse($t,$_)}"
    //
    //     swFmMirrorSolid = 4        swFmCurvePattern = 103    swFmLocalCurvePattern = 110
    //     swFmCirPattern = 5         swFmSketchPattern = 104   swFmLocalSketchPattern = 111
    //     swFmLPattern = 6           swFmFillPattern = 105     swFmLocalChainPattern = 112
    //     swFmMirrorPattern = 7      swFmTablePattern = 106    swFmMirrorComponent = 116
    //     swFmDerivedLPattern = 28   swFmDimPattern = 107
    //     swFmFlatPattern = 38       swFmLocalLPattern = 108
    //                                swFmLocalCirPattern = 109
    //
    // What that evidence does and does not support:
    //
    //   - LocalChainPattern is ADDED. Both binaries carry it (moLocalChainPattern_c, and
    //     the bare string at enum position 112); moChainPatternFeat_c does not exist.
    //   - MirrorCompFeat is ADDED. moMirrorCompFeat_c exists with 19 hits and
    //     moMirrorComponent_c has none.
    //   - ChainPatternFeat and MirrorComponent are KEPT, not replaced. swFeatureNameID_e
    //     spells swFmMirrorComponent (116) and has no swFmMirrorCompFeat, so the enum, if
    //     anything, reads the other way. The set is used for membership only - one
    //     HashSet.Contains against whatever GetTypeName2 returned - so an extra name costs
    //     nothing and cannot false-positive: no feature returns a name that does not
    //     exist. Dropping a name SOLIDWORKS 2024 does in fact return would silently
    //     regress grouping, which is the same failure being fixed here, in the other
    //     direction. The type-name census is what can refute either string against a real
    //     model on the workstation; until it does, nothing is removed.
    //   - DerivedCirPattern is KEPT, and its stated confirmation basis does not hold:
    //     swFeatureNameID_e has swFmDerivedLPattern = 28 and no swFmDerivedCirPattern at
    //     all. moDerivedCirPattern_c does exist in sldasmu.dll, so the name is real; the
    //     enum simply does not enumerate it.
    //   - TablePattern is commented out in ComponentTreeDumper rather than deleted; the
    //     reasoning is recorded at that line.
    //
    // Ordinal-sorted, so the pin survives a reordering of the declaration but not a change
    // of membership.
    private static readonly string[] Expected =
    {
        "ChainPatternFeat",
        "DerivedCirPattern",
        "DerivedLPattern",
        "LocalChainPattern",
        "LocalCirPattern",
        "LocalCurvePattern",
        "LocalLPattern",
        "LocalSketchPattern",
        "MirrorCompFeat",
        "MirrorComponent",
    };

    [Fact]
    public void PatternFeatureTypes_IsExactlyTheSetTheProvenanceSupports()
    {
        HashSet<string> actual = ReadPatternFeatureTypes();

        Assert.Equal(Expected, actual.OrderBy(name => name, StringComparer.Ordinal).ToArray());
    }

    private static HashSet<string> ReadPatternFeatureTypes()
    {
        FieldInfo? field = typeof(ComponentTreeDumper).GetField(
            "PatternFeatureTypes", BindingFlags.NonPublic | BindingFlags.Static);

        Assert.True(
            field != null,
            "ComponentTreeDumper.PatternFeatureTypes was renamed or removed; this test pins it.");

        return (HashSet<string>)field!.GetValue(null)!;
    }
}
