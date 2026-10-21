using System;
using System.Linq;
using System.Text.Json;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Owner decision 154A, the owner's follow-up ("A Field + don't block", feature 002 T171): the run root is a
/// field of the Review tab's Settings, against the real page in an offscreen WebView2.
///
/// The field shows the run root the settings name, and a save sends the folder in it - `run_root` on
/// `settings.save` - which the host checks by the run root rule. A save never fails for the run root: when
/// the folder chosen, or the run root left in force, is one the rule refuses, the save's `settings.saved`
/// carries `run_root_refusal`, and the page shows it under the field, in the class's sentence with the
/// class and the message in a fold, or with no labels the message as it is. The note stays until the next
/// save, which says again whether the run root is refused.
/// </summary>
public sealed class ReviewPageRunRootTests
{
    private const string Chosen = @"D:\Fictional\runs";

    private const string RefusalMessage =
        "The folder chosen for runs is on a network share or a mapped network drive, and runs are made only in a "
        + "local folder reached by its own path, so the run root was not changed; the other settings were saved. "
        + "Choose a local folder for runs, then save again.";

    private static readonly object Refusal = new
    {
        error_class = "RunRootRefused",
        message = RefusalMessage,
        retryable = false,
    };

    private const string Field = @"
var field = document.getElementById('run-root');
var note = document.getElementById('run-root-note');
var fold = note.querySelector('details');
return JSON.stringify({
  value: field.value,
  hidden: note.hidden,
  visible: h.visibleText(note),
  fold: fold ? fold.textContent : '',
  text: note.textContent,
  save: document.getElementById('save-state').textContent
});";

    [Fact]
    public void TheFieldShowsTheRunRootTheSettingsName()
    {
        ReviewPageDriver.Run(
            driver => driver.RunRoot = @"C:\Fictional\runs-here",
            async driver =>
            {
                JsonElement field = await driver.Read(Field);

                Assert.Equal(@"C:\Fictional\runs-here", field.GetProperty("value").GetString());
                Assert.True(field.GetProperty("hidden").GetBoolean());
            });
    }

    [Fact]
    public void ASaveSendsTheFolderInTheField()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            await driver.Read("document.getElementById('run-root').value = '  " + Chosen.Replace(@"\", @"\\") + "  '; return JSON.stringify({ok: true});");

            await driver.Click("save-settings");
            await driver.Until(() => driver.Posted("settings.save").Length == 1, "the save");

            Assert.Equal(Chosen, driver.Posted("settings.save").Single().GetProperty("run_root").GetString());
        });
    }

    /// <summary>
    /// A save whose run root was refused is a save: the Save line says it is saved, and the note under the
    /// field says, first, the class's sentence - the way on - with the class and the message in a fold.
    /// </summary>
    [Fact]
    public void ASaveWhoseRunRootWasRefusedIsSavedAndSaysSoUnderTheField()
    {
        ReviewPageDriver.Run(
            driver => driver.InitialRoutes.Add(("GET", "/labels", 200, LabelsSample.Json())),
            async driver =>
            {
                driver.RunRootRefusal = Refusal;

                await driver.Click("save-settings");
                await driver.Settle();

                JsonElement field = await driver.Read(Field);
                Assert.Equal("Saved.", field.GetProperty("save").GetString());
                Assert.False(field.GetProperty("hidden").GetBoolean());
                string visible = field.GetProperty("visible").GetString()!.Trim();
                Assert.StartsWith(LabelsSample.RunRootRefused, visible, StringComparison.Ordinal);
                Assert.DoesNotContain("RunRootRefused", visible, StringComparison.Ordinal);
                Assert.Contains("RunRootRefused", field.GetProperty("fold").GetString()!, StringComparison.Ordinal);
                Assert.Contains(RefusalMessage, field.GetProperty("fold").GetString()!, StringComparison.Ordinal);
            });
    }

    [Fact]
    public void WithNoLabelsTheNoteUnderTheFieldIsTheMessage()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            driver.RunRootRefusal = Refusal;

            await driver.Click("save-settings");
            await driver.Settle();

            JsonElement field = await driver.Read(Field);
            Assert.False(field.GetProperty("hidden").GetBoolean());
            Assert.Equal(RefusalMessage, field.GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// The note stays through the `init` a save asks for, and goes with the next save whose answer says
    /// nothing of the run root.
    /// </summary>
    [Fact]
    public void TheNoteStaysUntilASaveSaysNothingOfTheRunRoot()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            driver.RunRootRefusal = Refusal;
            await driver.Click("save-settings");
            await driver.Until(() => driver.Posted("ready").Length >= 2, "the init the save asks for");
            await driver.Settle();
            Assert.False((await driver.Read(Field)).GetProperty("hidden").GetBoolean());

            driver.RunRootRefusal = null;
            await driver.Click("save-settings");
            await driver.Settle();

            JsonElement field = await driver.Read(Field);
            Assert.True(field.GetProperty("hidden").GetBoolean());
            Assert.Equal(string.Empty, field.GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// A save whose restart failed was still a save (owner decision 150A): its `BackendNotRestarted` answer
    /// carries what the save says of the run root, and the page shows it under the field as for any save.
    /// </summary>
    [Fact]
    public void ASaveWhoseRestartFailedStillShowsTheNoteUnderTheField()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            driver.SettingsSaveError = new
            {
                error_class = "BackendNotRestarted",
                message = "the settings are saved, but the review backend did not restart with them.",
                retryable = true,
                run_root_refusal = Refusal,
            };

            await driver.Click("save-settings");
            await driver.Settle();

            JsonElement field = await driver.Read(Field);
            Assert.False(field.GetProperty("hidden").GetBoolean());
            Assert.Equal(RefusalMessage, field.GetProperty("text").GetString());
        });
    }

    /// <summary>
    /// A save refused before anything was judged or written - a turn running, a setting the host refuses -
    /// says nothing of the run root, so the note stays as the last save left it.
    /// </summary>
    [Fact]
    public void ASaveRefusedBeforeAnythingWasSavedLeavesTheNoteAsItWas()
    {
        ReviewPageDriver.Run(null, async driver =>
        {
            driver.RunRootRefusal = Refusal;
            await driver.Click("save-settings");
            await driver.Until(() => driver.Posted("ready").Length >= 2, "the init the save asks for");
            await driver.Settle();

            driver.SettingsSaveError = new { error_class = "TurnRunning", message = "FICT a turn is running", retryable = true };
            await driver.Click("save-settings");
            await driver.Settle();

            JsonElement field = await driver.Read(Field);
            Assert.False(field.GetProperty("hidden").GetBoolean());
            Assert.Equal(RefusalMessage, field.GetProperty("text").GetString());
            Assert.Contains("FICT a turn is running", field.GetProperty("save").GetString()!, StringComparison.Ordinal);
        });
    }
}
