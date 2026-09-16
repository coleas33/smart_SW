using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using SwReview.Extractor.Bridge;
using SwReview.Extractor.Capture;
using SwReview.Extractor.Dump;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Interference;
using SwReview.Extractor.Ir;
using SwReview.Extractor.Measure;
using SwReview.Extractor.Tests.Fakes;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T072, the command half. The dispatcher is driven with fakes, so every branch a client can
/// reach is exercised without SOLIDWORKS: the four commands, the guard, the circuit breaker,
/// and every way a request can be wrong.
///
/// The shapes asserted here are the ones Serve/PROTOCOL.md promises the Python client.
/// </summary>
public class BridgeDispatcherTests : IDisposable
{
    private readonly string _captureDirectory;
    private readonly FakeCaptureView _captureView = new FakeCaptureView();

    public BridgeDispatcherTests()
    {
        _captureDirectory = Path.Combine(
            Path.GetTempPath(), "swreview-tests", Guid.NewGuid().ToString("N"));
    }

    public void Dispose()
    {
        if (Directory.Exists(_captureDirectory))
        {
            Directory.Delete(_captureDirectory, recursive: true);
        }
    }

    // ---- the envelope ------------------------------------------------------------

    [Fact]
    public void Dispatch_UnknownCommand_ListsTheOnesItAnswers()
    {
        BridgeResponse response = Dispatch(Request("1", "rebuild"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("interference", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Dispatch_CommandNamedAfterAMutatingApi_IsRefusedByTheGuard()
    {
        // The guard sees the command name itself, so a handler for it could never be added
        // by accident (research R4).
        BridgeResponse response = Dispatch(Request("1", "Save3"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("read-only", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Dispatch_EchoesTheRequestId()
    {
        Assert.Equal("abc", Dispatch(Request("abc", BridgeCommands.Ping)).Id);
    }

    [Fact]
    public void Dispatch_CircuitOpen_IsItsOwnStatusNotAnError()
    {
        // The client must stop asking rather than retry, and must record failed coverage.
        var view = new FakeCaptureView
        {
            ThrowOnZoom = new CircuitOpenError("SOLIDWORKS stopped answering"),
        };

        BridgeResponse response = Dispatch(
            Request("1", BridgeCommands.Capture, "{\"persist_ref\":\"cmVm\"}"), view);

        Assert.Equal(BridgeStatus.CircuitOpen, response.Status);
        Assert.Null(response.Result);
    }

    // ---- ping --------------------------------------------------------------------

    [Fact]
    public void Ping_SaysWhichDocumentTheWorkerIsOn()
    {
        BridgeResponse response = Dispatch(Request("1", BridgeCommands.Ping));

        var result = Assert.IsType<PingResult>(response.Result);
        Assert.True(result.Pong);

        // The literal, not the constant: PROTOCOL.md says ping reports the host's own
        // ProtocolVersion and that a client compares against it, and remodel_client.py's
        // REMODEL_PROTOCOL_VERSION is "1.1". A comparison of the constant with itself would
        // pass at any value, which is how the two ends came apart.
        Assert.Equal("1.1", result.Protocol);
        Assert.Equal(SwBridgeDispatcher.ProtocolVersion, result.Protocol);
        Assert.Equal(@"C:\work\bracket-assy.SLDASM", result.Document);
        Assert.Equal("Default", result.Configuration);
        Assert.Equal(3, result.ComponentCount);
    }

    // ---- capture -----------------------------------------------------------------

    [Fact]
    public void Capture_ReturnsTheIrRowAndAnAbsolutePath()
    {
        BridgeResponse response = Dispatch(
            Request("2", BridgeCommands.Capture, "{\"persist_ref\":\"cmVm\",\"view\":\"iso\"}"));

        Assert.Equal(BridgeStatus.Ok, response.Status);
        var result = Assert.IsType<CaptureCommandResult>(response.Result);
        Assert.Equal("captures/cap-0001.png", result.Capture!.File);
        Assert.True(Path.IsPathRooted(result.Path));
        Assert.True(File.Exists(result.Path));
        Assert.Null(result.Gap);
    }

    [Fact]
    public void Capture_WritesWhereTheHostSaidNotWhereTheClientSaid()
    {
        // A path in a request would be a filesystem write the agent controls (research R4).
        BridgeResponse response = Dispatch(
            Request(
                "2",
                BridgeCommands.Capture,
                "{\"persist_ref\":\"cmVm\",\"out\":\"C:\\\\somewhere-else\"}"));

        var result = Assert.IsType<CaptureCommandResult>(response.Result);
        Assert.StartsWith(_captureDirectory, result.Path!, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void Capture_UnknownView_IsRefusedBeforeAnythingRuns()
    {
        BridgeResponse response = Dispatch(
            Request("2", BridgeCommands.Capture, "{\"persist_ref\":\"cmVm\",\"view\":\"behind\"}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Empty(_captureView.Calls);
    }

    [Fact]
    public void Capture_MissingPersistRef_NamesTheField()
    {
        BridgeResponse response = Dispatch(Request("2", BridgeCommands.Capture, "{}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("persist_ref", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Capture_ThatFails_StillReturnsTheGap()
    {
        // The client records unresolved coverage instead of losing the request.
        var view = new FakeCaptureView { SelectFailure = "deleted: the entity no longer exists" };

        BridgeResponse response = Dispatch(
            Request("2", BridgeCommands.Capture, "{\"persist_ref\":\"cmVm\"}"), view);

        Assert.Equal(BridgeStatus.Error, response.Status);
        var result = Assert.IsType<CaptureCommandResult>(response.Result);
        Assert.Null(result.Capture);
        Assert.NotNull(result.Gap);
        Assert.Equal(CaptureService.GapEntityKind, result.Gap!.EntityKind);
    }

    [Fact]
    public void Capture_IdsContinueAcrossRequestsOnOneConnection()
    {
        var dispatcher = NewDispatcher(_captureView);

        var first = (CaptureCommandResult)dispatcher.Dispatch(
            Request("1", BridgeCommands.Capture, "{\"persist_ref\":\"a\"}")).Result!;
        var second = (CaptureCommandResult)dispatcher.Dispatch(
            Request("2", BridgeCommands.Capture, "{\"persist_ref\":\"b\"}")).Result!;

        Assert.Equal("cap:0001", first.Capture!.Id);
        Assert.Equal("cap:0002", second.Capture!.Id);
    }

    // ---- measure -----------------------------------------------------------------

    [Fact]
    public void Measure_ReturnsMetresWithTheirUnit()
    {
        var reading = new MeasureReading(0.0123, 0.0123, 0.0, 0.0);
        BridgeResponse response = Dispatch(
            Request(
                "3",
                BridgeCommands.Measure,
                "{\"persist_ref_a\":\"aa\",\"persist_ref_b\":\"bb\"}"),
            measure: new FakeMeasureSource(reading));

        var result = Assert.IsType<MeasureCommandResult>(response.Result);
        Assert.Equal(0.0123, result.Distance!.Value);
        Assert.Equal(LengthUnit.M, result.Distance.Unit);
        Assert.Equal(LengthUnit.M, result.DeltaZ!.Unit);
    }

    [Fact]
    public void Measure_PassesBothReferencesThrough()
    {
        var source = new FakeMeasureSource(new MeasureReading(1.0, 1.0, 0.0, 0.0));
        Dispatch(
            Request(
                "3",
                BridgeCommands.Measure,
                "{\"persist_ref_a\":\"aa\",\"persist_ref_b\":\"bb\"}"),
            measure: source);

        Assert.Equal("aa", source.LastA);
        Assert.Equal("bb", source.LastB);
    }

    [Fact]
    public void Measure_UnsupportedPairing_IsAnErrorWithASentenceNotANumber()
    {
        BridgeResponse response = Dispatch(
            Request(
                "3",
                BridgeCommands.Measure,
                "{\"persist_ref_a\":\"aa\",\"persist_ref_b\":\"bb\"}"),
            measure: new FakeMeasureSource("The Measure tool has no answer for this pairing."));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Null(response.Result);
        Assert.Contains("no answer", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Measure_MissingReference_NamesTheField()
    {
        BridgeResponse response = Dispatch(
            Request("3", BridgeCommands.Measure, "{\"persist_ref_a\":\"aa\"}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("persist_ref_b", response.Error!, StringComparison.Ordinal);
    }

    // ---- interference ------------------------------------------------------------

    [Fact]
    public void Interference_NoComponentIds_ChecksTheWholeAssembly()
    {
        var detector = new FakeInterferenceDetector();
        Dispatch(Request("4", BridgeCommands.Interference, "{}"), interference: detector);

        Assert.Empty(Assert.Single(detector.Scopes));
    }

    [Fact]
    public void Interference_TwoComponentIds_ChecksThatPair()
    {
        var detector = new FakeInterferenceDetector();
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");

        Dispatch(
            Request(
                "4",
                BridgeCommands.Interference,
                "{\"component_ids\":[\"cmp:0001\",\"cmp:0002\"]}"),
            interference: detector,
            handles: new[] { a, b });

        Assert.Equal(new object[] { a, b }, Assert.Single(detector.Scopes));
    }

    [Fact]
    public void Interference_MoreThanTwoComponentIds_ChecksEveryUnorderedPair()
    {
        var detector = new FakeInterferenceDetector();
        Dispatch(
            Request(
                "4",
                BridgeCommands.Interference,
                "{\"component_ids\":[\"cmp:0001\",\"cmp:0002\",\"cmp:0003\"]}"),
            interference: detector);

        Assert.Equal(3, detector.Scopes.Count);
    }

    [Fact]
    public void Interference_OneComponentId_IsRefused()
    {
        BridgeResponse response = Dispatch(
            Request("4", BridgeCommands.Interference, "{\"component_ids\":[\"cmp:0001\"]}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
    }

    [Fact]
    public void Interference_UnknownComponentId_IsRefusedByNameNotDropped()
    {
        // Dropping it would report "no interference" for a pair that was never checked.
        BridgeResponse response = Dispatch(
            Request(
                "4",
                BridgeCommands.Interference,
                "{\"component_ids\":[\"cmp:0001\",\"cmp:9999\"]}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("cmp:9999", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Interference_ReadsTheSettingsFromTheRequest()
    {
        var detector = new FakeInterferenceDetector();
        Dispatch(
            Request(
                "4",
                BridgeCommands.Interference,
                "{\"settings\":{\"treat_coincident_as_interference\":true,\"ignore_hidden\":true,"
                + "\"fastener_folder_treatment\":\"only\"}}"),
            interference: detector);

        Assert.True(detector.Properties.TreatCoincidenceAsInterferenceValue);
        Assert.True(detector.Properties.IgnoreHiddenBodiesValue);
        Assert.False(detector.Properties.TreatSubAssembliesAsComponentsValue);
        Assert.Equal(FastenerFolderTreatment.Only, detector.ConfiguredWith!.Fasteners);
    }

    [Fact]
    public void Interference_OmittedSettings_UseTheDialogDefaults()
    {
        var detector = new FakeInterferenceDetector();
        Dispatch(Request("4", BridgeCommands.Interference, "{}"), interference: detector);

        Assert.False(detector.Properties.TreatCoincidenceAsInterferenceValue);
        Assert.True(detector.Properties.CreateFastenersFolderValue);
    }

    [Fact]
    public void Interference_BadSettingType_IsAnErrorNamingTheField()
    {
        BridgeResponse response = Dispatch(
            Request(
                "4",
                BridgeCommands.Interference,
                "{\"settings\":{\"ignore_hidden\":\"yes please\"}}"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("ignore_hidden", response.Error!, StringComparison.Ordinal);
    }

    [Fact]
    public void Interference_ReturnsTheRowsAndTheGaps()
    {
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");
        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(3.2e-9, a, b) });

        BridgeResponse response = Dispatch(
            Request("4", BridgeCommands.Interference, "{}"), interference: detector, handles: new[] { a, b });

        var result = Assert.IsType<InterferenceCommandResult>(response.Result);
        Assert.Equal(InterferenceStatus.Computed, Assert.Single(result.Interferences).Status);

        // Until T069's workstation check, the volume unit is an assumption and says so.
        Assert.Contains(
            result.Gaps, g => g.EntityKind == InterferenceRunner.VolumeUnitGapEntityKind);
    }

    [Fact]
    public void Interference_TruncateAfter_IsHonoured()
    {
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");
        var detector = new FakeInterferenceDetector(scope => new IInterferenceResult[]
        {
            new FakeInterferenceResult(1e-9, a, b),
            new FakeInterferenceResult(2e-9, a, b),
        });

        BridgeResponse response = Dispatch(
            Request("4", BridgeCommands.Interference, "{\"truncate_after\":1}"),
            interference: detector,
            handles: new[] { a, b });

        var result = Assert.IsType<InterferenceCommandResult>(response.Result);
        Assert.Equal(
            new[] { InterferenceStatus.Computed, InterferenceStatus.Truncated },
            result.Interferences.Select(i => i.Status));
    }

    [Fact]
    public void Interference_ConfigurationDefaultsToTheAttachedOne()
    {
        var a = new FakeComponent("cmp:0001");
        var b = new FakeComponent("cmp:0002");
        var detector = new FakeInterferenceDetector(
            scope => new IInterferenceResult[] { new FakeInterferenceResult(1e-9, a, b) });

        BridgeResponse response = Dispatch(
            Request("4", BridgeCommands.Interference, "{}"), interference: detector, handles: new[] { a, b });

        var result = Assert.IsType<InterferenceCommandResult>(response.Result);
        Assert.Equal("Default", Assert.Single(result.Interferences).Configuration);
    }

    // ---- the remodel.* command shapes (T059) -------------------------------------
    //
    // contracts/bridge-remodel.md is normative for the request and response shape of every
    // remodel.* command, and the shapes are asserted here as a TABLE rather than one command
    // at a time. The central property of the family - "no command that writes takes a document
    // parameter", so the engineer's file is unreachable rather than validated - is a property
    // of the whole table, and a per-command assertion would pass a thirteenth command added
    // later without anyone noticing.

    /// <summary>
    /// The names a path or a document would arrive under, if one ever could: every spelling
    /// that has actually appeared in a bridge request, this family's two included.
    ///
    /// <b>It is the same set as <c>remodel_client.DOCUMENT_PARAM_NAMES</c></b>
    /// (reviewer/src/swreview/bridge/remodel_client.py), because the two ends check the same
    /// property over the same table and a name added on one side and not the other makes a
    /// thirteenth command pass here and fail there. <c>scope_document</c> and the
    /// <c>scope_document_a</c> / <c>_b</c> pair are what this same bridge already calls a
    /// document in <c>capture</c> and <c>measure</c>, so they belong here more than any
    /// spelling nobody has ever sent.
    /// </summary>
    private static readonly string[] DocumentParameterVocabulary =
    {
        "source_path", "copy_path", "path", "document", "document_path", "scope_document",
        "scope_document_a", "scope_document_b", "model",
    };

    [Fact]
    public void RemodelCommands_AreTheTwelveTheContractNames()
    {
        Assert.Equal(
            new[]
            {
                "remodel.probe_scope",
                "remodel.open",
                "remodel.snapshot",
                "remodel.rename",
                "remodel.reorder",
                "remodel.folder",
                "remodel.describe",
                "remodel.equation",
                "remodel.rebuild",
                "remodel.geometry",
                "remodel.save",
                "remodel.close",
            },
            RemodelCommands.All);

        // The family is named by its prefix, and the four 1.0 commands are outside it.
        Assert.All(RemodelCommands.All, command => Assert.True(RemodelCommands.IsRemodelCommand(command)));
        Assert.All(BridgeCommands.All, command => Assert.False(RemodelCommands.IsRemodelCommand(command)));
    }

    [Fact]
    public void RemodelCommandTable_HasOneRowPerCommand()
    {
        Assert.Equal(
            RemodelCommands.All,
            RemodelCommandTable.Commands.Select(shape => shape.Command).ToArray());
    }

    [Fact]
    public void RemodelCommandTable_NoCommandOnTheScopeTakesADocumentParameter()
    {
        // The property, over the whole table: once the scope exists, RemodelScope holds the
        // only IModelDoc2 the run can reach and nothing in a request can name another.
        foreach (RemodelCommandShape shape in RemodelCommandTable.Commands)
        {
            if (shape.Stage != RemodelCommandStage.OnScope)
            {
                continue;
            }

            Assert.All(
                shape.ParameterNames,
                name => Assert.DoesNotContain(
                    name, DocumentParameterVocabulary, StringComparer.OrdinalIgnoreCase));
            Assert.False(shape.NamesAPath, shape.Command + " names a path");
        }
    }

    [Fact]
    public void RemodelCommandTable_ExactlyTwoCommandsNameAPath_AndBothRunBeforeTheScopeExists()
    {
        string[] naming = RemodelCommandTable.Commands
            .Where(shape => shape.NamesAPath)
            .Select(shape => shape.Command)
            .ToArray();

        Assert.Equal(new[] { RemodelCommands.ProbeScope, RemodelCommands.Open }, naming);
        Assert.All(
            naming,
            command => Assert.Equal(
                RemodelCommandStage.BeforeScope, RemodelCommandTable.For(command).Stage));
    }

    [Fact]
    public void RemodelCommandTable_AfterOpenReturns_NoCommandInTheFamilyAcceptsAPathAgain()
    {
        // Everything but the two pre-scope commands, checked as a list so a new command cannot
        // be added to the family without appearing here.
        string[] afterOpen = RemodelCommandTable.Commands
            .Where(shape => shape.Stage == RemodelCommandStage.OnScope)
            .Select(shape => shape.Command)
            .ToArray();

        Assert.Equal(
            new[]
            {
                RemodelCommands.Snapshot,
                RemodelCommands.Rename,
                RemodelCommands.Reorder,
                RemodelCommands.Folder,
                RemodelCommands.Describe,
                RemodelCommands.Equation,
                RemodelCommands.Rebuild,
                RemodelCommands.Geometry,
                RemodelCommands.Save,
                RemodelCommands.Close,
            },
            afterOpen);

        Assert.All(afterOpen, command => Assert.False(RemodelCommandTable.For(command).NamesAPath));
    }

    [Fact]
    public void RemodelCommandTable_EveryAddressingParameterIsAPersistRef()
    {
        // Never a name and never an index: names change and indices change on every reorder.
        string[] addressing = RemodelCommandTable.Commands
            .SelectMany(shape => shape.AddressingParameterNames)
            .Distinct(StringComparer.Ordinal)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToArray();

        Assert.Equal(
            new[]
            {
                "anchor_persist_ref",
                "feature_persist_ref",
                "folder_persist_ref",
                "member_persist_refs",
                "persist_ref",
            },
            addressing);

        Assert.All(
            addressing,
            name => Assert.True(
                name.EndsWith("persist_ref", StringComparison.Ordinal)
                || name.EndsWith("persist_refs", StringComparison.Ordinal),
                name));
    }

    [Fact]
    public void RemodelRename_TakesAPersistRefAndANewName_AndHasNoDimensionForm()
    {
        // FR-030: v1 addresses no dimension at all, and IDimension.set_Name is off the
        // stage-1 allowlist, so there is nowhere for a dimension form to arrive.
        Assert.Equal(
            new[] { "persist_ref", "new_name" },
            RemodelCommandTable.For(RemodelCommands.Rename).ParameterNames);

        Assert.All(
            RemodelCommandTable.Commands.SelectMany(shape => shape.ParameterNames),
            name => Assert.DoesNotContain("dimension", name, StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void RemodelReorder_LocationIsTheClosedSetBeforeAfter()
    {
        Assert.Equal(new[] { "before", "after" }, RemodelReorderLocations.All);

        RemodelReorderParams parsed = RemodelReorderParams.Read(
            Request(
                "1",
                RemodelCommands.Reorder,
                "{\"feature_persist_ref\":\"YQ==\",\"anchor_persist_ref\":\"Yg==\","
                + "\"location\":\"after\"}"));
        Assert.Equal(RemodelReorderLocations.After, parsed.Location);

        RemodelCommandError refused = Assert.Throws<RemodelCommandError>(() => RemodelReorderParams.Read(
            Request(
                "1",
                RemodelCommands.Reorder,
                "{\"feature_persist_ref\":\"YQ==\",\"anchor_persist_ref\":\"Yg==\","
                + "\"location\":\"somewhere\"}")));
        Assert.Contains("before", refused.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void RemodelEquation_OpIsTheClosedSetAddSetDelete()
    {
        Assert.Equal(new[] { "add", "set", "delete" }, RemodelEquationOps.All);

        Assert.Equal(
            RemodelEquationOps.Set,
            RemodelEquationParams.Read(
                Request(
                    "1",
                    RemodelCommands.Equation,
                    "{\"op\":\"set\",\"index\":2,\"text\":\"\\\"w\\\" = 120\"}")).Op);

        Assert.Throws<RemodelCommandError>(() => RemodelEquationParams.Read(
            Request("1", RemodelCommands.Equation, "{\"op\":\"replace\",\"index\":2}")));
    }

    [Fact]
    public void RemodelFolder_OpIsTheClosedSetCreateRenameDissolve()
    {
        // dissolve stays in the protocol so stage 2 adds a handler branch and an allowlist
        // entry rather than a new command; the handler answers not_in_v1 (T063).
        Assert.Equal(new[] { "create", "rename", "dissolve" }, RemodelFolderOps.All);

        Assert.Equal(
            RemodelFolderOps.Dissolve,
            RemodelFolderParams.Read(
                Request(
                    "1",
                    RemodelCommands.Folder,
                    "{\"op\":\"dissolve\",\"folder_persist_ref\":\"Zg==\"}")).Op);

        Assert.Throws<RemodelCommandError>(() => RemodelFolderParams.Read(
            Request("1", RemodelCommands.Folder, "{\"op\":\"merge\"}")));
    }

    [Fact]
    public void RemodelParams_MissingRequiredField_NamesIt()
    {
        Assert.Contains(
            "persist_ref",
            Assert.Throws<RemodelCommandError>(() => RemodelRenameParams.Read(
                Request("1", RemodelCommands.Rename, "{\"new_name\":\"Fillet-Outer\"}"))).Message,
            StringComparison.Ordinal);

        Assert.Contains(
            "source_path",
            Assert.Throws<RemodelCommandError>(() => RemodelProbeScopeParams.Read(
                Request("1", RemodelCommands.ProbeScope, "{}"))).Message,
            StringComparison.Ordinal);

        Assert.Contains(
            "probe_id",
            Assert.Throws<RemodelCommandError>(() => RemodelOpenParams.Read(
                Request(
                    "1",
                    RemodelCommands.Open,
                    "{\"source_path\":\"C:\\\\work\\\\bracket.SLDPRT\","
                    + "\"copy_path\":\"C:\\\\runs\\\\copy\\\\bracket-RMS.SLDPRT\","
                    + "\"run_id\":\"r1\"}"))).Message,
            StringComparison.Ordinal);
    }

    [Fact]
    public void RemodelResultShapes_CarryTheContractsFieldNames()
    {
        // One row of contracts/bridge-remodel.md's command table per assertion, read off the
        // wire rather than off the property names, because the wire is what the Python client
        // sees. remodel.geometry's GeometryReading is the one row not here: it is the geometry
        // phase's record, and the command's shape - no parameters at all, because there is
        // nothing to name - is asserted in the table cases above.
        Assert.Equal(
            new[] { "probe_id", "source_path", "scope_signals" },
            Keys(new RemodelProbeScopeResult()));
        Assert.Equal(
            new[]
            {
                "document_path", "tag", "feature_count", "scope_signals", "configurations",
                "document_length_unit", "source_attestation",
            },
            Keys(new RemodelOpenResult()));
        Assert.Equal(
            new[]
            {
                "order", "names", "descriptions", "equations", "unreadable_equation_indexes",
                "rebuild_errors", "feature_count",
            },
            Keys(new RemodelSnapshotResult()));
        Assert.Equal(new[] { "previous_name", "new_name" }, Keys(new RemodelRenameResult()));
        Assert.Equal(
            new[]
            {
                "previous_anchor_persist_ref", "previous_location", "previous_index", "new_index",
            },
            Keys(new RemodelReorderResult()));
        Assert.Equal(
            new[] { "folder_persist_ref", "name", "member_persist_refs" },
            Keys(new RemodelFolderResult()));
        Assert.Equal(new[] { "previous_text" }, Keys(new RemodelDescribeResult()));
        Assert.Equal(
            new[]
            {
                "index", "count_before", "count_after", "previous_text", "round_trip_text",
                "helper_path",
            },
            Keys(new RemodelEquationResult()));
        Assert.Equal(
            new[] { "rebuild_errors", "whats_wrong", "elapsed_ms", "feature_errors" },
            Keys(new RemodelRebuildResult()));
        Assert.Equal(
            new[] { "path", "errors", "warnings", "save_flag_after" },
            Keys(new RemodelSaveResult()));
        Assert.Equal(new[] { "closed", "copy_deleted" }, Keys(new RemodelCloseResult()));
    }

    [Fact]
    public void RemodelErrorResult_CarriesTheStableTokenAndADetail()
    {
        // The 1.0 envelope's one addition: on status "error" a remodel.* response carries
        // {error_code, detail} instead of null, so the client maps a refusal to a class
        // without matching on prose.
        var error = new RemodelErrorResult(
            RemodelErrorCodes.SourceNotOpen, "source_path", @"C:\work\bracket.SLDPRT");

        Assert.Equal(new[] { "error_code", "detail" }, Keys(error));
        Assert.Equal("source_not_open", error.ErrorCode);
        Assert.Equal(@"C:\work\bracket.SLDPRT", error.Detail!["source_path"]);
        Assert.Contains(RemodelErrorCodes.NotInV1, RemodelErrorCodes.All);
    }

    [Fact]
    public void Dispatch_UnknownRemodelCommand_IsAnErrorResultAndNeverAnException()
    {
        BridgeResponse response = Dispatch(Request("1", "remodel.frobnicate"));

        Assert.Equal(BridgeStatus.Error, response.Status);
        Assert.Contains("remodel.frobnicate", response.Error!, StringComparison.Ordinal);
    }

    /// <summary>The wire keys of a result object, in declaration order.</summary>
    private static string[] Keys(object result)
    {
        using (JsonDocument document = JsonDocument.Parse(
            JsonSerializer.Serialize(result, result.GetType(), BridgeCodec.Options)))
        {
            return document.RootElement.EnumerateObject().Select(member => member.Name).ToArray();
        }
    }

    // ---- helpers -----------------------------------------------------------------

    private static BridgeRequest Request(string id, string command, string? paramsJson = null)
    {
        string line = paramsJson == null
            ? $"{{\"id\":\"{id}\",\"command\":\"{command}\"}}"
            : $"{{\"id\":\"{id}\",\"command\":\"{command}\",\"params\":{paramsJson}}}";

        // Built through the codec so the tests exercise the same parse the pipe does. The
        // guard check happens in Dispatch, not here, so a denied name still gets this far.
        return JsonSerializer.Deserialize<BridgeRequest>(line, BridgeCodec.Options)!;
    }

    private BridgeResponse Dispatch(
        BridgeRequest request,
        FakeCaptureView? capture = null,
        IMeasureSource? measure = null,
        FakeInterferenceDetector? interference = null,
        FakeComponent[]? handles = null)
    {
        return NewDispatcher(capture ?? _captureView, measure, interference, handles).Dispatch(request);
    }

    private SwBridgeDispatcher NewDispatcher(
        FakeCaptureView capture,
        IMeasureSource? measure = null,
        FakeInterferenceDetector? interference = null,
        FakeComponent[]? handles = null)
    {
        var services = new BridgeServices(
            capture,
            measure ?? new FakeMeasureSource("no measure source in this test"),
            new FakeInterferenceSource(interference ?? new FakeInterferenceDetector()),
            Index(handles),
            _captureDirectory)
        {
            SwVersion = "32.5.0",
            DocumentPath = @"C:\work\bracket-assy.SLDASM",
            Configuration = "Default",
        };

        // The command handling, with the secret question answered "yes" - the scopes have
        // their own tests in BridgeSecretPolicyTests.
        return new SwBridgeDispatcher(services, NoSecretPolicy.Instance);
    }

    /// <summary>
    /// A three-component index: cmp:0001, cmp:0002 and cmp:0003, the last two patterned, so
    /// a request can name ids the way the Python side reads them out of package.json.
    /// </summary>
    private static ComponentIndex Index(FakeComponent[]? handles)
    {
        var tree = new ComponentTreeResult { ActiveConfiguration = "Default" };
        tree.Nodes.Add(new ComponentNode
        {
            Key = "bracket-assy-1",
            DocumentPath = @"C:\work\bracket-assy.SLDASM",
            Handle = handles != null && handles.Length > 0 ? handles[0] : null,
        });
        tree.Nodes.Add(new ComponentNode
        {
            Key = "housing-1",
            DocumentPath = @"C:\work\housing.SLDPRT",
            Handle = handles != null && handles.Length > 1 ? handles[1] : null,
        });
        tree.Nodes.Add(new ComponentNode
        {
            Key = "screw-1",
            DocumentPath = @"C:\work\screw.SLDPRT",
            PatternId = "pat:screws",
            Handle = handles != null && handles.Length > 2 ? handles[2] : null,
        });

        return new ComponentIndex(tree);
    }
}
