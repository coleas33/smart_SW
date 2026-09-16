using SolidWorks.Interop.sldworks;

namespace SwReview.Extractor.Dump;

/// <summary>
/// T038. The SOLIDWORKS side of <see cref="IEquationReader"/>: interop calls and nothing
/// else, so that every decision <see cref="EquationDumper"/> makes is testable without a
/// seat (the same split as <see cref="IFeatureReader"/> and <see cref="SwFeatureReader"/>).
///
/// Every member here is ONE interop call, and <see cref="EquationDumper"/> names each of
/// them to the gate, so nothing is gated twice and the read-only guard still sees the
/// production member names. That is why this class holds no <c>SwGate</c>: there is no
/// multi-call member for it to gate internally.
///
/// Interop notes, verified against the 2024 SP5 interop:
///   - <c>Equation</c>, <c>Value</c>, <c>GlobalVariable</c> and <c>Disabled</c> are indexed
///     properties (<c>string</c>, <c>double</c>, <c>bool</c>, <c>bool</c>), not methods.
///   - <c>GlobalVariable(i)</c> is read instead of parsing the equation text: a global and a
///     driven dimension are not reliably told apart from the text (research R5).
///   - nothing on the mutating side is touched: <c>Add3</c>, <c>Delete</c>,
///     <c>SetEquationAndConfigurationOption</c> and the suppression setters exist on this
///     same interface, and the dumper never reaches them.
/// </summary>
public sealed class SwEquationReader : IEquationReader
{
    public object? Document(ScopedComponent component)
    {
        if (component == null)
        {
            throw new System.ArgumentNullException(nameof(component));
        }

        var handle = component.Node.Handle as IComponent2;
        return handle == null ? null : handle.GetModelDoc2() as IModelDoc2;
    }

    public object? Manager(object document) => ((IModelDoc2)document).GetEquationMgr();

    public int Count(object manager) => Mgr(manager).GetCount();

    public string? Text(object manager, int index) => Mgr(manager).Equation[index];

    public bool GlobalVariable(object manager, int index) => Mgr(manager).GlobalVariable[index];

    public double Value(object manager, int index) => Mgr(manager).Value[index];

    private static IEquationMgr Mgr(object manager) => (IEquationMgr)manager;
}
