using System;
using System.Collections.Generic;
using System.Threading;
using SolidWorks.Interop.sldworks;
using SwReview.AddIn.Review;
using SwReview.AddIn.ToolService;
using SwReview.Extractor.Sw;

namespace SwReview.AddIn.Tests;

/// <summary>
/// A tool service with no pipe, no SOLIDWORKS and two distinct secrets.
///
/// Shared by the two suites that drive a real <see cref="ToolServiceGate"/>:
/// <see cref="ToolServiceWiringTests"/>, which pins what the gate does, and
/// <see cref="RemodelHostTests"/>, which pins what the Remodel tab makes of it when the gate is
/// wired to its host the way the add-in wires it (decision 24A).
/// </summary>
internal sealed class FakeToolService : IToolService
{
    public FakeToolService(int ordinal, string? documentPath = null)
    {
        PipeName = "swreview-fake-" + ordinal;
        ReviewBridge = new BridgeConfig(PipeName, "review-secret-" + ordinal);
        GeneralChatBridge = new BridgeConfig(PipeName, "chat-secret-" + ordinal);
        RemodelBridge = new BridgeConfig(PipeName, "remodel-secret-" + ordinal);
        RemodelSeatAvailable = false;
        DocumentPath = documentPath ?? @"C:\models\bracket-" + ordinal + ".sldasm";
        Session = new FakeSession();
    }

    public string PipeName { get; }

    public string DocumentPath { get; }

    public BridgeConfig ReviewBridge { get; }

    public BridgeConfig GeneralChatBridge { get; }

    public BridgeConfig RemodelBridge { get; }

    public bool RemodelSeatAvailable { get; }

    public ISwSession Session { get; }

    public bool Disposed { get; private set; }

    /// <summary>
    /// The thread the gate stopped it on. Recorded because the real stop joins an accept
    /// thread, every client thread and the pump - so it must not be the SOLIDWORKS
    /// application thread.
    /// </summary>
    public int DisposedThreadId { get; private set; }

    /// <summary>What the gate wrote into this service's own tool-service log.</summary>
    public List<string> LogLines { get; } = new List<string>();

    public void WriteLog(string line) => LogLines.Add(line);

    public void Dispose()
    {
        DisposedThreadId = Thread.CurrentThread.ManagedThreadId;
        Disposed = true;
    }

    /// <summary>Identity only: the tests assert which scope `entity.show` was handed, never
    /// what it did with it. Touching a member would need SOLIDWORKS.</summary>
    private sealed class FakeSession : ISwSession
    {
        public IModelDoc2 Document => throw new NotSupportedException("no SOLIDWORKS in a test.");

        public IConfiguration Configuration =>
            throw new NotSupportedException("no SOLIDWORKS in a test.");

        public string? SwVersion => null;

        public SwGate Gate { get; } = new SwGate();
    }
}
