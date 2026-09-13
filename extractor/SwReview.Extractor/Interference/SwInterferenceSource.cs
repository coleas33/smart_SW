using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SwReview.Extractor.Sw;

namespace SwReview.Extractor.Interference;

/// <summary>
/// The real <see cref="IInterferenceSource"/>: <c>IAssemblyDoc.InterferenceDetectionManager</c>
/// (research R12). Every member goes through <see cref="SwGate"/>, so the read-only guard
/// sees the call and a dead session opens the circuit breaker.
///
/// This class is compiled but not unit tested - it is nothing but interop calls. The logic
/// that decides what to do with the results lives in <see cref="InterferenceRunner"/>,
/// which is tested against a fake detector.
/// </summary>
public sealed class SwInterferenceSource : IInterferenceSource
{
    private readonly ISwSession _session;

    public SwInterferenceSource(ISwSession session)
    {
        _session = session ?? throw new ArgumentNullException(nameof(session));
    }

    public IInterferenceDetector Open()
    {
        var assembly = _session.Document as IAssemblyDoc;
        if (assembly == null)
        {
            throw new InvalidOperationException(
                "Interference detection needs an assembly; this document is not one.");
        }

        var manager = _session.Gate.Call(
            "InterferenceDetectionManager",
            () => assembly.InterferenceDetectionManager) as IInterferenceDetectionMgr;

        if (manager == null)
        {
            throw new InvalidOperationException(
                "SOLIDWORKS returned no InterferenceDetectionManager for this assembly.");
        }

        return new SwInterferenceDetector(_session, manager);
    }

    private sealed class SwInterferenceDetector : IInterferenceDetector
    {
        private readonly ISwSession _session;
        private readonly IInterferenceDetectionMgr _manager;

        public SwInterferenceDetector(ISwSession session, IInterferenceDetectionMgr manager)
        {
            _session = session;
            _manager = manager;
        }

        /// <summary>
        /// The mapping itself lives in <see cref="InterferenceRunSettings.ApplyTo"/>, which
        /// is unit tested; this only supplies the adapter that puts each setter through the
        /// gate.
        /// </summary>
        public void Configure(InterferenceRunSettings settings) =>
            settings.ApplyTo(new GatedManagerProperties(_session.Gate, _manager));

        /// <summary>
        /// The manager has no scope property: it checks the components that are selected
        /// when detection runs, and the whole assembly when nothing is (research R12).
        /// Selection is not a model change, so the read-only guard allows it.
        /// </summary>
        public void Scope(IReadOnlyList<object> componentHandles)
        {
            IModelDoc2 document = _session.Document;
            _session.Gate.Call("ClearSelection2", () => document.ClearSelection2(true));

            if (componentHandles == null || componentHandles.Count == 0)
            {
                return;
            }

            bool append = false;
            foreach (object handle in componentHandles)
            {
                var component = handle as IComponent2;
                if (component == null)
                {
                    throw new InvalidOperationException(
                        "An interference pair carried something that is not an IComponent2.");
                }

                bool appendThis = append;
                bool selected = _session.Gate.Call(
                    "Component.Select4", () => component.Select4(appendThis, null, false));

                if (!selected)
                {
                    string name = _session.Gate.Call("Name2", () => component.Name2) ?? "(unnamed)";
                    throw new InvalidOperationException(
                        $"'{name}' could not be selected, so detection cannot be scoped to it.");
                }

                append = true;
            }
        }

        public int GetInterferenceCount() =>
            _session.Gate.Call("GetInterferenceCount", () => _manager.GetInterferenceCount());

        public IReadOnlyList<IInterferenceResult> GetInterferences()
        {
            var raw = _session.Gate.Call("GetInterferences", () => _manager.GetInterferences()) as object[];
            if (raw == null)
            {
                return new IInterferenceResult[0];
            }

            var results = new List<IInterferenceResult>(raw.Length);
            foreach (object item in raw)
            {
                var interference = item as IInterference;
                if (interference != null)
                {
                    results.Add(new SwInterferenceResult(_session, interference));
                }
            }

            return results;
        }

        public void Done() => _session.Gate.Call("InterferenceMgr.Done", () => _manager.Done());
    }

    /// <summary>
    /// The five manager properties, each written through <see cref="SwGate"/> so the
    /// read-only guard sees the member name and the circuit breaker counts the failure.
    /// </summary>
    private sealed class GatedManagerProperties : IInterferenceManagerProperties
    {
        private readonly SwGate _gate;
        private readonly IInterferenceDetectionMgr _manager;

        public GatedManagerProperties(SwGate gate, IInterferenceDetectionMgr manager)
        {
            _gate = gate;
            _manager = manager;
        }

        public bool TreatCoincidenceAsInterference
        {
            set
            {
                bool v = value;
                _gate.Call(
                    "TreatCoincidenceAsInterference",
                    () => { _manager.TreatCoincidenceAsInterference = v; });
            }
        }

        public bool TreatSubAssembliesAsComponents
        {
            set
            {
                bool v = value;
                _gate.Call(
                    "TreatSubAssembliesAsComponents",
                    () => { _manager.TreatSubAssembliesAsComponents = v; });
            }
        }

        public bool IncludeMultibodyPartInterferences
        {
            set
            {
                bool v = value;
                _gate.Call(
                    "IncludeMultibodyPartInterferences",
                    () => { _manager.IncludeMultibodyPartInterferences = v; });
            }
        }

        public bool IgnoreHiddenBodies
        {
            set
            {
                bool v = value;
                _gate.Call("IgnoreHiddenBodies", () => { _manager.IgnoreHiddenBodies = v; });
            }
        }

        public bool CreateFastenersFolder
        {
            set
            {
                bool v = value;
                _gate.Call("CreateFastenersFolder", () => { _manager.CreateFastenersFolder = v; });
            }
        }
    }

    private sealed class SwInterferenceResult : IInterferenceResult
    {
        private readonly ISwSession _session;
        private readonly IInterference _interference;

        public SwInterferenceResult(ISwSession session, IInterference interference)
        {
            _session = session;
            _interference = interference;
        }

        public double Volume =>
            _session.Gate.Call("Interference.Volume", () => _interference.Volume);

        public IReadOnlyList<object> Components
        {
            get
            {
                var raw = _session.Gate.Call(
                    "Interference.Components", () => _interference.Components) as object[];
                return raw ?? new object[0];
            }
        }

        public bool IsFastener =>
            _session.Gate.Call("Interference.IsFastener", () => _interference.IsFastener);

        public bool IsPossibleInterference =>
            _session.Gate.Call(
                "Interference.IsPossibleInterference", () => _interference.IsPossibleInterference);
    }
}
