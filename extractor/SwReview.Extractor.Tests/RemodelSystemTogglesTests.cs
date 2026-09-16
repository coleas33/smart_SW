using System;
using System.Collections.Generic;
using SwReview.Extractor.Guard;
using SwReview.Extractor.Rms;
using SwReview.Extractor.Sw;
using Xunit;

namespace SwReview.Extractor.Tests;

/// <summary>
/// T052. The three system toggles and the one application flag the run sets, and restores in a
/// <c>finally</c> (research R5.6).
///
/// Every one of them is a dialog. In an add-in a dialog is a hang, not an error: the message box
/// opens on the SOLIDWORKS thread the run is holding and nothing answers it.
///
///   - <c>swInputDimValOnCreate = 10</c>: leaving it on is recorded upstream as "the single most
///     expensive failure in this repo's history" - every dimension call opens a modal and the
///     script appears to hang;
///   - <c>swShowErrorsEveryRebuild = 77</c>: a rebuild with errors raises What's Wrong;
///   - <c>swWarnSaveUpdateErrors = 329</c>: the "save anyway?" dialog;
///   - <c>ISldWorks.CommandInProgress = true</c>: PROBE-1's modal suppression for a refused
///     <c>ReorderFeature</c>. It is a <b>property</b>, not a fourth <c>swUserPreferenceToggle_e</c>
///     value, which is why it carries its own allowlist key
///     (<c>ISldWorks.set_CommandInProgress</c>) rather than riding on
///     <c>SetUserPreferenceToggle</c>.
///
/// The values are asserted as the integers the code composes, never as the names it writes.
///
/// <b>A toggle whose original value could not be read refuses the start.</b> Guessing one and
/// "restoring" it at the end would leave the engineer's SOLIDWORKS in a state nobody chose,
/// which is exactly the class of silent write this feature exists to make impossible.
/// </summary>
public class RemodelSystemTogglesTests
{
    /// <summary>
    /// The four settings, and nothing else, so the set-and-restore is testable without a
    /// SOLIDWORKS seat.
    /// </summary>
    private sealed class ToggleHostFake : IRemodelToggleHost
    {
        private readonly Dictionary<int, bool> _toggles = new Dictionary<int, bool>
        {
            { RemodelSystemToggles.InputDimValOnCreate, true },
            { RemodelSystemToggles.ShowErrorsEveryRebuild, true },
            { RemodelSystemToggles.WarnSaveUpdateErrors, true },
        };

        /// <summary>Every call made, in order, as <c>get:10</c> or <c>set:10=false</c>.</summary>
        public List<string> Calls { get; } = new List<string>();

        /// <summary>A toggle whose original value the seat will not answer for.</summary>
        public int? UnreadableToggle { get; set; }

        /// <summary>True when <c>get_CommandInProgress</c> throws.</summary>
        public bool CommandInProgressUnreadable { get; set; }

        /// <summary>Toggles whose set throws, to pin the partial-set rollback.</summary>
        public HashSet<int> UnsettableToggles { get; } = new HashSet<int>();

        public bool CommandInProgress { get; set; }

        public bool Toggle(int toggle) => _toggles[toggle];

        public void Preset(int toggle, bool value) => _toggles[toggle] = value;

        public bool GetUserPreferenceToggle(int toggle)
        {
            Calls.Add("get:" + toggle);
            if (UnreadableToggle == toggle)
            {
                throw new InvalidOperationException("the seat did not answer");
            }

            return _toggles[toggle];
        }

        public void SetUserPreferenceToggle(int toggle, bool value)
        {
            Calls.Add("set:" + toggle + "=" + (value ? "true" : "false"));
            if (UnsettableToggles.Contains(toggle))
            {
                throw new InvalidOperationException("the seat refused the set");
            }

            _toggles[toggle] = value;
        }

        public bool GetCommandInProgress()
        {
            Calls.Add("get:CommandInProgress");
            if (CommandInProgressUnreadable)
            {
                throw new InvalidOperationException("the seat did not answer");
            }

            return CommandInProgress;
        }

        public void SetCommandInProgress(bool value)
        {
            Calls.Add("set:CommandInProgress=" + (value ? "true" : "false"));
            CommandInProgress = value;
        }
    }

    // ------------------------------------------------------------------ the constants

    [Fact]
    public void TheThreeToggleValuesAreTheIntegersTheContractNames()
    {
        Assert.Equal(10, RemodelSystemToggles.InputDimValOnCreate);
        Assert.Equal(77, RemodelSystemToggles.ShowErrorsEveryRebuild);
        Assert.Equal(329, RemodelSystemToggles.WarnSaveUpdateErrors);
    }

    /// <summary>
    /// Three, not four. <c>CommandInProgress</c> is a property and is deliberately absent from
    /// this list; a fourth entry here would be a member name handed to
    /// <c>SetUserPreferenceToggle</c> that means something else entirely.
    /// </summary>
    [Fact]
    public void TheToggleListIsExactlyThoseThreeInThatOrder()
    {
        Assert.Equal(
            new[]
            {
                RemodelSystemToggles.InputDimValOnCreate,
                RemodelSystemToggles.ShowErrorsEveryRebuild,
                RemodelSystemToggles.WarnSaveUpdateErrors,
            },
            RemodelSystemToggles.SuppressedToggles);
    }

    // ---------------------------------------------------------------- read, set, restore

    [Fact]
    public void ApplyReadsAllFourBeforeItSetsAnyOfThem()
    {
        var host = new ToggleHostFake();

        RemodelSystemToggles.Apply(host, Gate());

        Assert.Equal(
            new[]
            {
                "get:10", "get:77", "get:329", "get:CommandInProgress",
                "set:10=false", "set:77=false", "set:329=false", "set:CommandInProgress=true",
            },
            host.Calls);
    }

    [Fact]
    public void ApplyTurnsTheThreeDialogsOffAndTheCommandFlagOn()
    {
        var host = new ToggleHostFake();

        RemodelSystemToggles.Apply(host, Gate());

        Assert.False(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
        Assert.False(host.Toggle(RemodelSystemToggles.ShowErrorsEveryRebuild));
        Assert.False(host.Toggle(RemodelSystemToggles.WarnSaveUpdateErrors));
        Assert.True(host.CommandInProgress);
    }

    [Fact]
    public void RestorePutsEveryOriginalValueBack()
    {
        var host = new ToggleHostFake();
        host.Preset(RemodelSystemToggles.ShowErrorsEveryRebuild, false);
        host.CommandInProgress = false;

        RemodelSystemToggles restore = RemodelSystemToggles.Apply(host, Gate());
        restore.Restore();

        Assert.True(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
        Assert.False(host.Toggle(RemodelSystemToggles.ShowErrorsEveryRebuild));
        Assert.True(host.Toggle(RemodelSystemToggles.WarnSaveUpdateErrors));
        Assert.False(host.CommandInProgress);
    }

    /// <summary>
    /// Restoring twice is not two restores. A run that both restores in its own <c>finally</c>
    /// and is disposed by the host must not write the same four settings again.
    /// </summary>
    [Fact]
    public void RestoreIsIdempotent()
    {
        var host = new ToggleHostFake();
        RemodelSystemToggles restore = RemodelSystemToggles.Apply(host, Gate());
        restore.Restore();
        int calls = host.Calls.Count;

        restore.Restore();

        Assert.Equal(calls, host.Calls.Count);
    }

    // ---------------------------------------------------------------- the finally

    [Fact]
    public void WithinRestoresOnTheHappyPath()
    {
        var host = new ToggleHostFake();
        bool ran = false;

        RemodelSystemToggles.Within(host, Gate(), () => ran = true);

        Assert.True(ran);
        Assert.True(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
        Assert.False(host.CommandInProgress);
    }

    [Fact]
    public void WithinRestoresWhenTheBodyThrowsAndLetsTheExceptionThrough()
    {
        var host = new ToggleHostFake();

        var thrown = Assert.Throws<InvalidOperationException>(() =>
            RemodelSystemToggles.Within(host, Gate(), () => throw new InvalidOperationException("the run failed")));

        Assert.Equal("the run failed", thrown.Message);
        Assert.True(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
        Assert.True(host.Toggle(RemodelSystemToggles.ShowErrorsEveryRebuild));
        Assert.True(host.Toggle(RemodelSystemToggles.WarnSaveUpdateErrors));
        Assert.False(host.CommandInProgress);
    }

    /// <summary>
    /// Recovery of a previous run's leftovers. A run that died with the dialogs suppressed
    /// leaves them suppressed; the recovering run reads <b>what is actually there</b>, records
    /// that as the original, and restores to it. It does not restore to a value it thinks the
    /// engineer probably had, because nothing in this process knows that, and a guessed restore
    /// is a silent write to the engineer's settings.
    /// </summary>
    [Fact]
    public void RecoveryOfAPreviousRunsLeftoversRestoresWhatWasActuallyThere()
    {
        var host = new ToggleHostFake();
        host.Preset(RemodelSystemToggles.InputDimValOnCreate, false);
        host.Preset(RemodelSystemToggles.ShowErrorsEveryRebuild, false);
        host.Preset(RemodelSystemToggles.WarnSaveUpdateErrors, false);
        host.CommandInProgress = true;

        RemodelSystemToggles.Within(host, Gate(), () => { });

        Assert.False(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
        Assert.False(host.Toggle(RemodelSystemToggles.ShowErrorsEveryRebuild));
        Assert.False(host.Toggle(RemodelSystemToggles.WarnSaveUpdateErrors));
        Assert.True(host.CommandInProgress);
    }

    // ------------------------------------------------------- an unreadable original

    [Theory]
    [InlineData(10)]
    [InlineData(77)]
    [InlineData(329)]
    public void AToggleWhoseOriginalValueCouldNotBeReadRefusesTheStart(int toggle)
    {
        var host = new ToggleHostFake { UnreadableToggle = toggle };

        var error = Assert.Throws<InvalidOperationException>(() => RemodelSystemToggles.Apply(host, Gate()));

        Assert.Contains(toggle.ToString(), error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void ARefusedStartSetsNothingAtAll()
    {
        var host = new ToggleHostFake { UnreadableToggle = RemodelSystemToggles.WarnSaveUpdateErrors };

        Assert.Throws<InvalidOperationException>(() => RemodelSystemToggles.Apply(host, Gate()));

        Assert.DoesNotContain(host.Calls, call => call.StartsWith("set:", StringComparison.Ordinal));
        Assert.True(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
    }

    [Fact]
    public void ACommandInProgressFlagThatCouldNotBeReadRefusesTheStartToo()
    {
        var host = new ToggleHostFake { CommandInProgressUnreadable = true };

        var error = Assert.Throws<InvalidOperationException>(() => RemodelSystemToggles.Apply(host, Gate()));

        Assert.Contains("CommandInProgress", error.Message, StringComparison.Ordinal);
        Assert.DoesNotContain(host.Calls, call => call.StartsWith("set:", StringComparison.Ordinal));
    }

    /// <summary>
    /// A set that fails halfway leaves nothing changed either: the settings already written are
    /// put back before the refusal is raised, because the run is not starting and the engineer's
    /// SOLIDWORKS must not keep two of its four settings.
    /// </summary>
    [Fact]
    public void ASetThatFailsHalfwayRestoresTheOnesThatAlreadyLanded()
    {
        var host = new ToggleHostFake();
        host.UnsettableToggles.Add(RemodelSystemToggles.WarnSaveUpdateErrors);

        Assert.Throws<InvalidOperationException>(() => RemodelSystemToggles.Apply(host, Gate()));

        Assert.True(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
        Assert.True(host.Toggle(RemodelSystemToggles.ShowErrorsEveryRebuild));
        Assert.False(host.CommandInProgress);
    }

    [Fact]
    public void ApplyRefusesToBeCalledWithoutAHost()
    {
        Assert.Throws<ArgumentNullException>(() => RemodelSystemToggles.Apply(null!, Gate()));
    }

    [Fact]
    public void WithinRefusesToBeCalledWithoutABody()
    {
        Assert.Throws<ArgumentNullException>(() => RemodelSystemToggles.Within(new ToggleHostFake(), Gate(), null!));
    }

    /// <summary>
    /// A guard that refuses exactly one key. It is what proves the two allowlist entries are
    /// load-bearing rather than decorative: if the writes did not go through the gate, a guard
    /// that refuses their keys would not be able to stop them.
    /// </summary>
    private sealed class RefusingGuard : ICallGuard
    {
        private readonly string _refused;

        public RefusingGuard(string refused)
        {
            _refused = refused;
        }

        public void Assert(string interopMemberName)
        {
            if (string.Equals(interopMemberName, _refused, StringComparison.Ordinal))
            {
                throw new MutatingCallError(interopMemberName, "refused by this test's guard.");
            }
        }
    }

    // --------------------------------------------- the gate every one of the four goes through

    /// <summary>
    /// The four writes change the engineer's application-wide SOLIDWORKS settings, so they are
    /// gated exactly like every other write the re-modeler makes: through <see cref="SwGate"/>,
    /// under the two interface-qualified keys contracts/guard-allowlist.md gives them. Without
    /// this they could never appear in the <c>gated=</c> set SC-004 is audited against.
    /// </summary>
    [Fact]
    public void EverySetGoesThroughTheGateUnderItsAllowlistKey()
    {
        var observer = new RecordingGateObserver();
        var host = new ToggleHostFake();

        RemodelSystemToggles.Apply(host, Gate(observer: observer)).Restore();

        Assert.Contains(RemodelSystemToggles.ToggleMember, observer.Members);
        Assert.Contains(RemodelSystemToggles.CommandInProgressMember, observer.Members);
        Assert.Empty(observer.Refusals);

        // And the keys the gate saw are the keys the stage-1 allowlist carries.
        Assert.Contains(RemodelSystemToggles.ToggleMember, RemodelGuard.AllowedKeys);
        Assert.Contains(RemodelSystemToggles.CommandInProgressMember, RemodelGuard.AllowedKeys);
    }

    [Fact]
    public void AGuardThatRefusesTheToggleKeyBlocksTheStartAndSetsNothing()
    {
        var host = new ToggleHostFake();

        Assert.Throws<MutatingCallError>(() =>
            RemodelSystemToggles.Apply(host, Gate(new RefusingGuard(RemodelSystemToggles.ToggleMember))));

        Assert.DoesNotContain(host.Calls, call => call.StartsWith("set:", StringComparison.Ordinal));
        Assert.True(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
    }

    [Fact]
    public void AGuardThatRefusesTheCommandFlagKeyPutsTheThreeTogglesBack()
    {
        var host = new ToggleHostFake();

        Assert.Throws<MutatingCallError>(() => RemodelSystemToggles.Apply(
            host, Gate(new RefusingGuard(RemodelSystemToggles.CommandInProgressMember))));

        Assert.True(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
        Assert.True(host.Toggle(RemodelSystemToggles.ShowErrorsEveryRebuild));
        Assert.True(host.Toggle(RemodelSystemToggles.WarnSaveUpdateErrors));
        Assert.False(host.CommandInProgress);
    }

    /// <summary>
    /// The restore is the call that matters most when SOLIDWORKS is sick, and a run that dies
    /// is exactly the run that trips the breaker. It is guarded and observed, and deliberately
    /// <b>not</b> counted against the circuit, so an open circuit cannot leave the engineer's
    /// four settings flipped.
    /// </summary>
    [Fact]
    public void AnOpenCircuitDoesNotStopTheRestore()
    {
        var host = new ToggleHostFake();
        SwGate gate = Gate();
        RemodelSystemToggles toggles = RemodelSystemToggles.Apply(host, gate);

        Action boom = () => throw new InvalidOperationException("SOLIDWORKS stopped answering");
        while (!gate.Breaker.IsOpen)
        {
            Assert.Throws<InvalidOperationException>(() => gate.Call("GetSaveFlag", boom));
        }

        toggles.Restore();

        Assert.True(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
        Assert.True(host.Toggle(RemodelSystemToggles.ShowErrorsEveryRebuild));
        Assert.True(host.Toggle(RemodelSystemToggles.WarnSaveUpdateErrors));
        Assert.False(host.CommandInProgress);
    }

    // ----------------------------------------------------------- a restore that fails halfway

    /// <summary>
    /// A restore that throws on its first write must still attempt the other three. The one
    /// that matters is <c>CommandInProgress</c>: left <c>true</c> it suppresses modals for the
    /// rest of the engineer's SOLIDWORKS session, and it is written last.
    /// </summary>
    [Fact]
    public void ARestoreWhoseFirstSetThrowsStillPutsBackTheOtherThreeAndSurfaces()
    {
        var host = new ToggleHostFake();
        RemodelSystemToggles toggles = RemodelSystemToggles.Apply(host, Gate());
        host.UnsettableToggles.Add(RemodelSystemToggles.InputDimValOnCreate);

        var failure = Assert.Throws<AggregateException>(() => toggles.Restore());

        Assert.Single(failure.InnerExceptions);
        Assert.True(host.Toggle(RemodelSystemToggles.ShowErrorsEveryRebuild));
        Assert.True(host.Toggle(RemodelSystemToggles.WarnSaveUpdateErrors));
        Assert.False(host.CommandInProgress);

        // The one that failed is the only one still holding the run's value.
        Assert.False(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));
    }

    /// <summary>
    /// A restore that did not finish is not "restored". The next one - the host's own
    /// <c>finally</c>, or <c>remodel.close</c> - finishes the job, and writes only what is
    /// still outstanding, so idempotence and recovery are the same mechanism.
    /// </summary>
    [Fact]
    public void ARestoreThatDidNotFinishIsFinishedByTheNextOne()
    {
        var host = new ToggleHostFake();
        RemodelSystemToggles toggles = RemodelSystemToggles.Apply(host, Gate());
        host.UnsettableToggles.Add(RemodelSystemToggles.InputDimValOnCreate);
        Assert.Throws<AggregateException>(() => toggles.Restore());

        host.UnsettableToggles.Clear();
        int calls = host.Calls.Count;
        toggles.Restore();

        Assert.True(host.Toggle(RemodelSystemToggles.InputDimValOnCreate));

        // One write, not four: the three that already landed are not written again.
        Assert.Equal(calls + 1, host.Calls.Count);
    }

    // ---------------------------------------------------------------------------- helpers

    /// <summary>
    /// The gate the toggles are handed. The real <see cref="RemodelGuard"/> by default, so the
    /// tests run against the allowlist the product uses rather than a permissive stand-in.
    /// </summary>
    private static SwGate Gate(ICallGuard? guard = null, RecordingGateObserver? observer = null) =>
        new SwGate(new CircuitBreaker(), guard ?? new RemodelGuard()) { Observer = observer };
}
