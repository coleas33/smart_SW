using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using Xunit;

namespace SwReview.AddIn.Tests;

/// <summary>
/// Where the Remodel page's shipped files live, and how a test renders inside one.
///
/// The convention <see cref="ReviewPageFiles"/> and <see cref="ModelCheckPageFiles"/> already
/// use, for the same reason: the files are read from the build output, which is the copy the
/// add-in actually serves, so a page file that never reaches `web/` fails the scan instead of
/// passing it from source. The web folder itself and the contract reader are reused rather than
/// restated - there is one answer to "which folder is the virtual host" in this assembly.
/// </summary>
internal static class RemodelPageFiles
{
    /// <summary>The Remodel page's folder inside the mapped web folder.</summary>
    public static string Folder =>
        Path.Combine(ReviewPageFiles.WebFolder, "Remodel", "RemodelPage");

    /// <summary>The shared helpers every page loads (T080).</summary>
    public static string SharedFolder => Path.Combine(ReviewPageFiles.WebFolder, "shared");

    /// <summary>The URL the add-in navigates the Remodel tab to.</summary>
    public const string PageUrl = "https://swreview.invalid/Remodel/RemodelPage/index.html";

    /// <summary>`index.html` as shipped.</summary>
    public static string IndexHtml() => Read("index.html");

    /// <summary>One page file, by name relative to <see cref="Folder"/>.</summary>
    public static string Read(string name)
    {
        AssertPresent();
        string path = Path.Combine(Folder, name);
        Assert.True(File.Exists(path), $"{name} is missing from {Folder}.");
        return File.ReadAllText(path);
    }

    /// <summary>
    /// Every script the page runs: its own, and the shared helpers it loads from the same
    /// virtual host. `shared/dom.js` is in here because the page's rules are its rules - it is
    /// where this page's text reaches the DOM (T080).
    /// </summary>
    public static IReadOnlyList<KeyValuePair<string, string>> Scripts()
    {
        AssertPresent();

        List<KeyValuePair<string, string>> scripts = new[] { Folder, SharedFolder }
            .Where(Directory.Exists)
            .SelectMany(folder => Directory.GetFiles(folder, "*.js", SearchOption.AllDirectories))
            .Where(path => !path.Split(Path.DirectorySeparatorChar).Contains("vendor"))
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .Select(path => new KeyValuePair<string, string>(
                path.Substring(ReviewPageFiles.WebFolder.Length).TrimStart(Path.DirectorySeparatorChar),
                File.ReadAllText(path)))
            .ToList();

        Assert.True(
            scripts.Count >= 2,
            $"The Remodel page ships no script beside {SharedFolder}; check the Content items "
                + "in SwReview.AddIn.csproj.");
        return scripts;
    }

    /// <summary>
    /// The closed list of `status` stages, read out of the `status` row of
    /// `contracts/pane-remodel-messages.md` rather than restated in a test. A second copy of a
    /// closed list is a closed list with a stale copy.
    ///
    /// Three callers share it, and they are the three places a stage can enter the page:
    /// <see cref="BackendRemodelPipelineTests"/> for the pipeline's own phase stages,
    /// <see cref="RemodelHostTests"/> for everything the host posts, and the list the add-in
    /// filters its backend-lifecycle fan-out through.
    /// </summary>
    public static IReadOnlyCollection<string> StatusStages()
    {
        foreach (string raw in ReviewPageFiles.ReadContract("pane-remodel-messages.md").Split('\n'))
        {
            string line = raw.TrimEnd('\r');
            if (!line.StartsWith("| `status`", StringComparison.Ordinal))
            {
                continue;
            }

            var stages = new HashSet<string>(
                Regex.Matches(line, "\"([a-z_]+)\"")
                    .Cast<Match>()
                    .Select(match => match.Groups[1].Value),
                StringComparer.Ordinal);

            Assert.True(
                stages.Count == 10,
                "contracts/pane-remodel-messages.md's `status` row did not parse: " + line);
            return stages;
        }

        throw new InvalidOperationException(
            "contracts/pane-remodel-messages.md has no `status` row in its unsolicited table.");
    }

    private static void AssertPresent() =>
        Assert.True(
            Directory.Exists(Folder),
            $"The Remodel page was not copied to {Folder}; check the Content items in "
                + "SwReview.AddIn.csproj.");
}

/// <summary>
/// The Remodel page, loaded from the add-in's own virtual host in an offscreen WebView2, with a
/// script evaluated inside it.
///
/// The boot is <see cref="OffscreenReviewPage.WithPage(string, Action{Microsoft.Web.WebView2.Core.CoreWebView2}, Func{Microsoft.Web.WebView2.Core.CoreWebView2, System.Threading.Tasks.Task})"/>
/// - the same page file server, the same real page URL, the same real CSP - because the
/// pages share an origin and must not be tested under five different approximations of it.
/// Only the prelude differs: this one renders through `window.SwReviewRemodel`.
///
/// `window.chrome.webview` exists in this host as it does in the add-in, so the page posts its
/// `ready` normally; nothing answers it, which is exactly the state the page is in before the
/// host replies, and rendering does not depend on it.
/// </summary>
internal static class OffscreenRemodelPage
{
    /// <summary>
    /// Evaluates a JS function body in the loaded page and parses what it returned. The body
    /// runs with the page's own renderers in scope - `remodel(result)`, `plan(summary)`,
    /// `append(change)` and `run(path)` - plus `describe(node)`, which reports what actually
    /// landed in the DOM.
    /// </summary>
    public static JsonElement Evaluate(string body)
    {
        string? raw = null;

        OffscreenReviewPage.WithPage(
            RemodelPageFiles.PageUrl,
            null,
            async page =>
            {
                // Through the DevTools protocol rather than injected into the document, so the
                // page's own CSP neither blocks it nor is weakened by it.
                raw = await page.ExecuteScriptAsync(Prelude + body + Epilogue);
            });

        Assert.False(
            string.IsNullOrEmpty(raw) || raw == "null",
            "The page script threw before it could report: " + (raw ?? "<nothing>")
                + Environment.NewLine + body);

        string json = JsonDocument.Parse(raw!).RootElement.GetString()
            ?? throw new InvalidOperationException("The page script returned no value: " + raw);
        return JsonDocument.Parse(json).RootElement.Clone();
    }

    private const string Prelude = @"
(function () {
  function api() {
    var found = window.SwReviewRemodel;
    if (!found || typeof found.renderResult !== 'function'
        || typeof found.renderPlan !== 'function'
        || typeof found.appendChange !== 'function'
        || typeof found.renderRun !== 'function') {
      throw new Error('Remodel/RemodelPage/remodel.js must set window.SwReviewRemodel with ' +
        'renderResult, renderPlan, appendChange and renderRun (T133): the tests render through ' +
        'the same functions the tab renders through.');
    }
    return found;
  }

  function remodel(result) {
    api().renderResult(result);
    return document.body;
  }

  function plan(summary) {
    api().renderPlan(summary);
    return document.body;
  }

  function append(change) {
    api().appendChange(change);
    return document.body;
  }

  function run(path) {
    api().renderRun(path);
    return document.body;
  }

  function describe(node) {
    var handlers = 0;
    var all = node.getElementsByTagName('*');
    for (var i = 0; i < all.length; i++) {
      var attributes = all[i].attributes;
      for (var j = 0; j < attributes.length; j++) {
        if (/^on/i.test(attributes[j].name)) { handlers++; }
      }
    }
    return {
      ok: true,
      text: node.textContent,
      html: node.innerHTML,
      injected: node.querySelectorAll('img,script,iframe,svg,object,embed,link,style').length,
      handlers: handlers
    };
  }

  function texts(selector) {
    var found = document.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].textContent); }
    return out;
  }

  function attrs(selector, name) {
    var found = document.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < found.length; i++) { out.push(found[i].getAttribute(name)); }
    return out;
  }

  function nodes(selector) {
    var found = document.querySelectorAll(selector);
    var out = [];
    for (var i = 0; i < found.length; i++) {
      var first = found[i].firstChild;
      out.push({
        node_type: first ? first.nodeType : 0,
        value: first ? first.nodeValue : null,
        children: found[i].getElementsByTagName('*').length
      });
    }
    return out;
  }

  try {
";

    private const string Epilogue = @"
  } catch (error) {
    return JSON.stringify({ ok: false, error: '' + ((error && error.message) || error) });
  }
}());
";
}

/// <summary>
/// One `remodel.result` payload and one plan summary
/// (`contracts/pane-remodel-messages.md`, `contracts/run-artifacts.md`) for the page tests to
/// render.
///
/// Written out as a literal rather than produced by running the Python planner: these tests are
/// about what the page does with the shape, the contract is what both sides agree on, and a
/// fixture generated by one side would only prove that side consistent with itself. The values
/// are chosen so every branch the page has is reachable - all four change outcomes, a rebuild
/// entry per reason shape, a geometry gate with its coverage limits, an accepted proposal and a
/// rejected one.
/// </summary>
internal static class RemodelResultSample
{
    /// <summary>The eight `RunState` values of data-model.md section 11, in its order.</summary>
    public static readonly string[] RunStates =
    {
        "planned", "judging", "applying", "verifying", "saved", "truncated", "failed", "discarded",
    };

    /// <summary>What the tier-1 gate cannot detect, printed on every run (data-model.md 3.4).</summary>
    public static readonly string[] CoverageLimits =
    {
        "a reflection",
        "a rigid rotation about a symmetry axis",
        "compensating add and remove pairs",
        "any difference occupying no volume",
        "surface- and wire-body differences",
        "a difference produced by the baseline rebuild itself",
    };

    /// <summary>A feature name as SOLIDWORKS hands it over when someone types it in.</summary>
    public const string HostileFeatureName = "<img src=x onerror=alert(1)>";

    /// <summary>A description the model wrote, which is the least trusted string on the page.</summary>
    public const string HostileDescription =
        "Mounting slot</script><script>alert(2)</script>";

    /// <summary>A rebuild-list reason's detail, assembled out of the model's own names.</summary>
    public const string HostileRebuildDetail =
        "<iframe src=javascript:alert(3)></iframe> parent feat:0061 is in 6-Quarantine";

    /// <summary>A run folder path with the quotes that break a hand-built attribute.</summary>
    public const string HostileRunPath =
        "C:\\SwReviewRuns\\\"><img src=x onerror=alert(4)>\\20260916-142201-bracket-remodel";

    public static string ResultJson(
        string featureName = "Cut-Extrude1", string? rebuildDetail = null) =>
        JsonSerializer.Serialize(
            Result(featureName, rebuildDetail ?? "parent feat:0061 is in 6-Quarantine"));

    /// <summary>The `remodel.change` the host pushes while the run is applying.</summary>
    public static string LiveChangeJson() =>
        JsonSerializer.Serialize(Change(5, "describe", "feat:0055", "Shell1", "applied"));

    public static string PlanSummaryJson(string? descriptionText = null) =>
        JsonSerializer.Serialize(PlanSummary(descriptionText ?? "Mounting slot"));

    private static object Result(string featureName, string rebuildDetail) => new
    {
        state = "saved",
        changes = new object[]
        {
            Change(1, "rename", "feat:0019", featureName, "applied"),
            Failed(2, "reorder", "feat:0042", "Fillet3"),
            Change(3, "describe", "feat:0007", "Boss-Extrude2", "rolled_back"),
            Attempting(4, "folder.create", "feat:0003", "3-Core"),
        },
        grade_before = Grade(24, 7, 3, 2, 6, 0.706),
        grade_after = Grade(30, 1, 3, 2, 6, 0.882),
        geometry = new
        {
            before = Reading("copy_at_open", 0.00123456789),
            after = Reading("copy_at_end", 0.00123456789),
            gate = new
            {
                verdict = "pass",
                profile = "IDENTITY",
                tier_1 = new { ran = true, verdict = "pass", reason = (string?)null },
                tier_2 = (object?)null,
                deltas = new object[]
                {
                    new
                    {
                        quantity = "volume_m3",
                        before = 0.00123456789,
                        after = 0.00123456789,
                        absolute = 0.0,
                        relative = 0.0,
                        bound = 1e-9,
                        within = true,
                    },
                    new
                    {
                        quantity = "face_count",
                        before = 214.0,
                        after = 214.0,
                        absolute = 0.0,
                        relative = 0.0,
                        bound = 0.0,
                        within = true,
                    },
                },
                material_changed = false,
                coverage_limits = CoverageLimits,
                diagnosis = (string?)null,
            },
            tolerances = new
            {
                volume_rel = 1e-9,
                area_rel = 1e-9,
                com_rel = 1e-9,
                moment_rel = 1e-9,
                face_count = "exact",
                body_count = "exact",
                calibrated = true,
                calibration_ref = "PROBE-8 2026-09-16",
            },
        },
        rebuild_list = new object[]
        {
            new
            {
                feature_id = "feat:0044",
                name = "Fillet7",
                reason = "backward_reference",
                detail = rebuildDetail,
                blocking_edge = new { parent_id = "feat:0061", child_id = "feat:0044" },
            },
            new
            {
                feature_id = "feat:0012",
                name = "Sketch3",
                reason = "shared_sketch",
                detail = "consumed by Boss-Extrude2 and Cut-Extrude4",
                blocking_edge = (object?)null,
            },
            new
            {
                feature_id = "feat:0071",
                name = "Unknown1",
                reason = "unclassified",
                detail = "GetTypeName2 is not in rms_types.yaml",
                blocking_edge = (object?)null,
            },
        },
        attestation = new
        {
            path = @"C:\work\bracket.SLDPRT",
            length_bytes = 482913,
            last_write_utc = "2026-09-14T09:11:03Z",
            sha256 = "0fb1c2",
            source_design_id = "dsn:4f2a91c0d3b7",
            recorded_at = "2026-09-16T14:22:01Z",
            rechecked_at = "2026-09-16T14:41:55Z",
            matches = (bool?)true,
            copy_path = @"C:\SwReviewRuns\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT",
            copy_sha256_after_save = "9ac41d",
        },
    };

    private static object Grade(
        int checkedCount, int failed, int warned, int unresolved, int outOfScope, double fraction) => new
    {
        // `checked` is a C# keyword and the contract's field name; the escape is the
        // identifier, and the serialized property is still `checked`.
        @checked = checkedCount,
        failed,
        warned,
        skipped = 0,
        unresolved,
        out_of_scope = outOfScope,
        fraction,
        unresolved_rule_ids = new[] { "rms.params.units", "rms.refs.direction" },
    };

    private static object Reading(string subject, double volume) => new
    {
        at = "2026-09-16T14:22:31Z",
        source_sha256 = "0fb1c2",
        subject,
        status = 0,
        accuracy_level = 2,
        recalculated = true,
        volume_m3 = volume,
        surface_area_m2 = 0.0456,
        center_of_mass_m = new[] { 0.01, 0.02, 0.03 },
        principal_moments = new[] { 1.1e-5, 2.2e-5, 3.3e-5 },
        mass_kg = 3.21,
        density = 2600.0,
        material_name = "1060 Alloy",
        solid_body_count = 1,
        sheet_body_count = 0,
        face_count = 214,
        edge_count = 642,
        residual = (object?)null,
    };

    private static object Change(int seq, string kind, string featureId, string name, string status) =>
        new
        {
            seq,
            at = "2026-09-16T14:22:31.481Z",
            kind,
            subject = new { feature_id = featureId, name, persist_ref = "YmFzZTY0" },
            before = new { index = 42, anchor = "Cut-Extrude2", location = "after" },
            after = new { index = 61, anchor = "Chamfer1", location = "after" },
            rebuild_errors_before = 0,
            rebuild_errors_after = 0,
            status,
            error_code = (string?)null,
            error = (string?)null,
            target_path =
                @"C:\SwReviewRuns\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT",
            elapsed_ms = 310,
        };

    private static object Failed(int seq, string kind, string featureId, string name) => new
    {
        seq,
        at = "2026-09-16T14:22:34.002Z",
        kind,
        subject = new { feature_id = featureId, name, persist_ref = "YmFzZTY1" },
        before = new { index = 42, anchor = "Cut-Extrude2", location = "after" },
        after = (object?)null,
        rebuild_errors_before = 0,
        rebuild_errors_after = 0,
        status = "failed",
        error_code = "ReorderRefused",
        error = "the anchor moved before the change could be applied",
        target_path = @"C:\SwReviewRuns\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT",
        elapsed_ms = 44,
    };

    private static object Attempting(int seq, string kind, string featureId, string name) => new
    {
        seq,
        at = "2026-09-16T14:22:40.114Z",
        kind,
        subject = new { feature_id = featureId, name, persist_ref = "YmFzZTY2" },
        before = (object?)null,
        after = (object?)null,
        rebuild_errors_before = 0,
        rebuild_errors_after = (int?)null,
        status = "attempting",
        error_code = (string?)null,
        error = (string?)null,
        target_path = @"C:\SwReviewRuns\20260916-142201-bracket-remodel\copy\bracket-RMS.SLDPRT",
        elapsed_ms = (int?)null,
    };

    /// <summary>
    /// The plan summary `remodel.planned` carries, cut down to what the judgement section of the
    /// page reads: what the model proposed, what the rules accepted, and what they refused.
    /// </summary>
    private static object PlanSummary(string descriptionText) => new
    {
        plan_revision = 2,
        run_id = "20260916-142201-bracket-remodel",
        state = "planned",
        moves = 12,
        folders = 6,
        descriptions = new object[]
        {
            new
            {
                feature_id = "feat:0007",
                before = string.Empty,
                text = descriptionText,
                source = "model",
                rationale = "the slot carries the mounting bolts",
                provider = "openai",
                model = "a-model-id",
                validation = "accepted",
            },
        },
        globals = new object[]
        {
            new
            {
                name = "shell_thickness",
                expression = "3",
                rationale = "three features share the same wall",
                provider = "openai",
                model = "a-model-id",
                validation = "accepted",
                order_index = 1,
            },
        },
        rejected_proposals = new object[]
        {
            new
            {
                at = "2026-09-16T14:31:02Z",
                tool = "propose_global",
                arguments = new { name = "PlateWidth", expression = "50" },
                reason = "global name must be lower_snake_case, 2 to 32 characters",
                rule = "global.name_pattern",
                provider = "openai",
                model = "a-model-id",
            },
        },
        deviations = new object[]
        {
            new
            {
                kind = "fillet_default_core",
                feature_id = "feat:0052",
                chosen = "3-Core",
                rationale = "no radius was readable",
                report_line = "reviewed as structural; move to Quarantine if cosmetic",
            },
        },
    };
}
