using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace SwReview.Extractor.Sw;

/// <summary>
/// Turns <c>OpenDoc6</c>'s two out parameters into member names.
///
/// "error 2, warning 0" is not evidence; "swFileNotFoundError" is. The obvious
/// implementation does not work: both enums are BIT-valued but NEITHER carries
/// <c>[Flags]</c>, so <c>((swFileLoadError_e)1026).ToString()</c> returns the string
/// "1026" rather than naming the two bits. The bits are therefore decomposed explicitly
/// here, and any bit this table does not know is printed as hex rather than dropped - a
/// later service pack adding a bit must stay visible (Principle I).
///
/// The table is a copy of the interop values, not a reference to them, so the decode is
/// pure and unit-testable on a machine with no SOLIDWORKS. Values pinned by reflecting
/// C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.swconst.dll
/// (SOLIDWORKS 2024 SP5) on 2026-09-13:
///
///   swFileLoadError_e   - underlying int, no [Flags]; 25 members, bits 0x00000001
///                         (swGenericError) through 0x01000000 (swConnectedIsOffline),
///                         every member a distinct single bit.
///   swFileLoadWarning_e - underlying int, no [Flags]; 21 members, bits 0x00000001
///                         (swFileLoadWarning_IdMismatch) through 0x00100000
///                         (swFileLoadWarning_MissingExternalReferences).
///
/// The two enums reuse the same low bits for different meanings (2 is
/// swFileNotFoundError but swFileLoadWarning_ReadOnly), which is why they get separate
/// tables and separate entry points.
/// </summary>
public static class FileLoadErrors
{
    /// <summary>swFileLoadError_e, lowest bit first.</summary>
    private static readonly string[] ErrorNames =
    {
        "swGenericError",                 // 0x00000001
        "swFileNotFoundError",            // 0x00000002
        "swIdMatchError",                 // 0x00000004
        "swReadOnlyWarn",                 // 0x00000008
        "swSharingViolationWarn",         // 0x00000010
        "swDrawingANSIUpdateWarn",        // 0x00000020
        "swSheetScaleUpdateWarn",         // 0x00000040
        "swNeedsRegenWarn",               // 0x00000080
        "swBasePartNotLoadedWarn",        // 0x00000100
        "swFileAlreadyOpenWarn",          // 0x00000200
        "swInvalidFileTypeError",         // 0x00000400
        "swDrawingsOnlyRapidDraftWarn",   // 0x00000800
        "swViewOnlyRestrictions",         // 0x00001000
        "swFutureVersion",                // 0x00002000
        "swViewMissingReferencedConfig",  // 0x00004000
        "swDrawingSFSymbolConvertWarn",   // 0x00008000
        "swFileWithSameTitleAlreadyOpen", // 0x00010000
        "swLiquidMachineDoc",             // 0x00020000
        "swLowResourcesError",            // 0x00040000
        "swNoDisplayData",                // 0x00080000
        "swAddinInteruptError",           // 0x00100000
        "swFileRequiresRepairError",      // 0x00200000
        "swFileCriticalDataRepairError",  // 0x00400000
        "swApplicationBusy",              // 0x00800000
        "swConnectedIsOffline",           // 0x01000000
    };

    /// <summary>swFileLoadWarning_e, lowest bit first.</summary>
    private static readonly string[] WarningNames =
    {
        "swFileLoadWarning_IdMismatch",                            // 0x00000001
        "swFileLoadWarning_ReadOnly",                              // 0x00000002
        "swFileLoadWarning_SharingViolation",                      // 0x00000004
        "swFileLoadWarning_DrawingANSIUpdate",                     // 0x00000008
        "swFileLoadWarning_SheetScaleUpdate",                      // 0x00000010
        "swFileLoadWarning_NeedsRegen",                            // 0x00000020
        "swFileLoadWarning_BasePartNotLoaded",                     // 0x00000040
        "swFileLoadWarning_AlreadyOpen",                           // 0x00000080
        "swFileLoadWarning_DrawingsOnlyRapidDraft",                // 0x00000100
        "swFileLoadWarning_ViewOnlyRestrictions",                  // 0x00000200
        "swFileLoadWarning_ViewMissingReferencedConfig",           // 0x00000400
        "swFileLoadWarning_DrawingSFSymbolConvert",                // 0x00000800
        "swFileLoadWarning_RevolveDimTolerance",                   // 0x00001000
        "swFileLoadWarning_ModelOutOfDate",                        // 0x00002000
        "swFileLoadWarning_DimensionsReferencedIncorrectlyToModels", // 0x00004000
        "swFileLoadWarning_ComponentMissingReferencedConfig",      // 0x00008000
        "swFileLoadWarning_InvisibleDoc_LinkedDesignTableUpdateFail", // 0x00010000
        "swFileLoadWarning_MissingDesignTable",                    // 0x00020000
        "swFileLoadWarning_AutomaticRepair",                       // 0x00040000
        "swFileLoadWarning_CriticalDataRepair",                    // 0x00080000
        "swFileLoadWarning_MissingExternalReferences",             // 0x00100000
    };

    /// <summary>
    /// Both out parameters as one clause, e.g.
    /// <c>error 2 (swFileNotFoundError), warning 0 (none)</c>. The raw numbers stay: they
    /// are what the SOLIDWORKS API documentation is searched by.
    /// </summary>
    public static string Describe(int errors, int warnings) =>
        string.Format(
            CultureInfo.InvariantCulture,
            "error {0} ({1}), warning {2} ({3})",
            errors,
            DescribeErrors(errors),
            warnings,
            DescribeWarnings(warnings));

    /// <summary>The swFileLoadError_e bits set in <paramref name="errors"/>.</summary>
    public static string DescribeErrors(int errors) => DescribeBits(errors, ErrorNames);

    /// <summary>The swFileLoadWarning_e bits set in <paramref name="warnings"/>.</summary>
    public static string DescribeWarnings(int warnings) => DescribeBits(warnings, WarningNames);

    /// <summary>
    /// Names every known bit, lowest first, and appends whatever is left over as hex. The
    /// value is read as an unsigned bit pattern so bit 31 decodes as a bit rather than as a
    /// negative number.
    /// </summary>
    private static string DescribeBits(int value, string[] names)
    {
        if (value == 0)
        {
            return "none";
        }

        uint bits = unchecked((uint)value);
        uint residual = bits;
        var found = new List<string>();

        for (int index = 0; index < names.Length; index++)
        {
            uint bit = 1u << index;
            if ((bits & bit) != 0)
            {
                found.Add(names[index]);
                residual &= ~bit;
            }
        }

        var described = new StringBuilder();
        described.Append(string.Join("|", found.ToArray()));

        if (residual != 0)
        {
            if (found.Count > 0)
            {
                described.Append(" + ");
            }

            described.Append("unknown bits 0x")
                .Append(residual.ToString("X8", CultureInfo.InvariantCulture));
        }

        return described.ToString();
    }
}
