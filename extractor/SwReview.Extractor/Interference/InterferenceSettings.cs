using System;
using SwReview.Extractor.Ir;
using IrSettings = SwReview.Extractor.Ir.InterferenceSettings;

namespace SwReview.Extractor.Interference;

/// <summary>
/// The five <c>IInterferenceDetectionMgr</c> properties a run writes, named exactly as
/// SOLIDWORKS names them.
///
/// It exists so <see cref="InterferenceRunSettings.ApplyTo"/> - the actual mapping from
/// command-line flags to API properties - can be asserted on a machine with no seat
/// (T065). The interop implementation is a thin adapter in
/// <see cref="SwInterferenceSource"/> that routes each setter through <c>SwGate</c>.
/// </summary>
public interface IInterferenceManagerProperties
{
    bool TreatCoincidenceAsInterference { set; }

    bool TreatSubAssembliesAsComponents { set; }

    bool IncludeMultibodyPartInterferences { set; }

    bool IgnoreHiddenBodies { set; }

    bool CreateFastenersFolder { set; }
}

/// <summary>
/// T069. The <c>IInterferenceDetectionMgr</c> properties one interference run uses, and
/// the echo of those properties into <c>Interference.settings</c>.
///
/// The echo is not decoration. "No interference found" means nothing on its own: with
/// <c>TreatCoincidenceAsInterference</c> off a press fit at exactly zero clearance is
/// invisible, and with the fasteners folder excluded every screw-into-tapped-hole pair
/// disappears. The reviewer states the settings alongside the result so an engineer can
/// see what the run was blind to (constitution Principle I).
///
/// Defaults match the SOLIDWORKS Interference Detection dialog as it opens: coincidence is
/// not an interference, subassemblies are single components, multibody interferences inside
/// one part are not included, hidden bodies are not ignored.
/// </summary>
public sealed class InterferenceRunSettings
{
    /// <summary>
    /// <c>CreateFastenersFolder</c> is always on, whatever <see cref="Fasteners"/> says.
    /// It is what populates <c>IInterference.IsFastener</c>, and that flag is the only way
    /// to honour <c>--fasteners exclude|only</c> at all (research R12, T069).
    /// </summary>
    public const bool AlwaysCreateFastenersFolder = true;

    /// <summary><c>--coincident-as-interference</c> → <c>TreatCoincidenceAsInterference</c>.</summary>
    public bool TreatCoincidentAsInterference { get; set; }

    /// <summary><c>--subassemblies-as-components</c> → <c>TreatSubAssembliesAsComponents</c>.</summary>
    public bool TreatSubassembliesAsComponents { get; set; }

    /// <summary>
    /// <c>IncludeMultibodyPartInterferences</c>. contracts/cli.md lists no flag for it, so
    /// the console leaves it at the dialog default; the add-in and the bridge may set it.
    /// </summary>
    public bool IncludeMultibody { get; set; }

    /// <summary><c>--ignore-hidden</c> → <c>IgnoreHiddenBodies</c>.</summary>
    public bool IgnoreHidden { get; set; }

    /// <summary>
    /// <c>--fasteners include|exclude|only</c>. Not a manager property: the manager has no
    /// "fasteners only" mode, so this filters the results by
    /// <c>IInterference.IsFastener</c> after detection (see <see cref="Keeps"/>).
    /// </summary>
    public FastenerFolderTreatment Fasteners { get; set; } = FastenerFolderTreatment.Include;

    /// <summary>
    /// The mapping. <c>--fasteners</c> is not here: the manager has no such property, and
    /// <c>CreateFastenersFolder</c> is turned ON for every treatment because that is what
    /// populates the <c>IsFastener</c> flag the filter then reads.
    /// </summary>
    public void ApplyTo(IInterferenceManagerProperties manager)
    {
        if (manager == null)
        {
            throw new ArgumentNullException(nameof(manager));
        }

        manager.TreatCoincidenceAsInterference = TreatCoincidentAsInterference;
        manager.TreatSubAssembliesAsComponents = TreatSubassembliesAsComponents;
        manager.IncludeMultibodyPartInterferences = IncludeMultibody;
        manager.IgnoreHiddenBodies = IgnoreHidden;
        manager.CreateFastenersFolder = AlwaysCreateFastenersFolder;
    }

    /// <summary>Whether a result with this <c>IsFastener</c> flag survives <see cref="Fasteners"/>.</summary>
    public bool Keeps(bool isFastener)
    {
        switch (Fasteners)
        {
            case FastenerFolderTreatment.Exclude:
                return !isFastener;
            case FastenerFolderTreatment.Only:
                return isFastener;
            default:
                return true;
        }
    }

    /// <summary>A fresh copy, so one run's settings cannot be mutated through another's IR.</summary>
    public InterferenceRunSettings Clone() => new InterferenceRunSettings
    {
        TreatCoincidentAsInterference = TreatCoincidentAsInterference,
        TreatSubassembliesAsComponents = TreatSubassembliesAsComponents,
        IncludeMultibody = IncludeMultibody,
        IgnoreHidden = IgnoreHidden,
        Fasteners = Fasteners,
    };

    /// <summary>
    /// The IR echo. A new instance every call: every <c>Interference</c> owns its own
    /// settings object so serialization cannot alias one run's settings across results.
    /// </summary>
    public IrSettings ToIr() => new IrSettings
    {
        TreatCoincidentAsInterference = TreatCoincidentAsInterference,
        TreatSubassembliesAsComponents = TreatSubassembliesAsComponents,
        IncludeMultibody = IncludeMultibody,
        IgnoreHidden = IgnoreHidden,
        FastenerFolderTreatment = Fasteners,
    };

    /// <summary>Parses <c>--fasteners include|exclude|only</c>. Throws on anything else.</summary>
    public static FastenerFolderTreatment ParseFastenerTreatment(string? value)
    {
        switch ((value ?? "include").Trim().ToLowerInvariant())
        {
            case "include":
                return FastenerFolderTreatment.Include;
            case "exclude":
                return FastenerFolderTreatment.Exclude;
            case "only":
                return FastenerFolderTreatment.Only;
            default:
                throw new ArgumentException(
                    $"--fasteners must be include, exclude or only; got '{value}'.", nameof(value));
        }
    }
}
