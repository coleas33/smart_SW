import json

import pytest
from typer.testing import CliRunner

from swreview.engineering_context.cli import app
from swreview.ir.loader import save_package
from tests.support.packages import build_package

runner = CliRunner()


@pytest.fixture
def workspace(tmp_path):
    package_dir = tmp_path / "extracted"
    save_package(build_package(), package_dir)
    return package_dir, tmp_path / "private-context"


def invoke_json(args):
    result = runner.invoke(app, [*map(str, args), "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_offline_requirement_approval_edit_history_and_force(workspace):
    package, store = workspace
    created = invoke_json(["init", package, "--store", store])
    assert created["revision"] == 1
    updated = invoke_json(
        [
            "requirement",
            package,
            "--store",
            store,
            "--id",
            "req:1",
            "--kind",
            "component",
            "--entity",
            "cmp:0001",
            "--text",
            "Support operating load",
            "--expected-head",
            created["head_digest"],
        ]
    )
    shown = invoke_json(["show", package, "--store", store])
    first = shown["records"][0]
    assert first["decision"] == "draft"
    assert first["binding"]["status"] == "matched_snapshot"
    assert shown["native_model_state"] == "not_observed"
    approved = invoke_json(
        [
            "confirm",
            package,
            "--store",
            store,
            "--id",
            "req:1",
            "--actor",
            "fictional-engineer",
            "--expected-head",
            updated["head_digest"],
            "--record-digest",
            first["record_digest"],
            "--dependency-digest",
            first["dependency_digest"],
        ]
    )
    assert invoke_json(["show", package, "--store", store])["records"][0]["decision"] == "confirmed"
    edited = invoke_json(
        [
            "requirement",
            package,
            "--store",
            store,
            "--id",
            "req:1",
            "--kind",
            "component",
            "--entity",
            "cmp:0001",
            "--text",
            "Support revised load",
            "--expected-head",
            approved["head_digest"],
        ]
    )
    after = invoke_json(["show", package, "--store", store])
    assert after["records"][0]["decision"] == "needs_review"
    assert after["confirmation_count"] == 1
    invoke_json(
        [
            "force",
            package,
            "--store",
            store,
            "--id",
            "force:1",
            "--kind",
            "component",
            "--entity",
            "cmp:0001",
            "--magnitude",
            "2",
            "--unit",
            "kN",
            "--direction",
            "0,0,-1",
            "--expected-head",
            edited["head_digest"],
        ]
    )
    force = next(
        r
        for r in invoke_json(["show", package, "--store", store])["records"]
        if r["record"]["kind"] == "applied_force"
    )
    assert force["resolved_force"]["magnitude_n"] == pytest.approx(2000.0)
    assert force["resolved_force"]["vector_n"] == [0.0, 0.0, -2000.0]


def test_stale_digest_and_changed_package_cannot_confirm(workspace):
    package, store = workspace
    initial = invoke_json(["init", package, "--store", store])
    updated = invoke_json(
        [
            "requirement",
            package,
            "--store",
            store,
            "--id",
            "req:1",
            "--kind",
            "document",
            "--entity",
            "doc:1",
            "--text",
            "Clear requirement",
            "--expected-head",
            initial["head_digest"],
        ]
    )
    shown = invoke_json(["show", package, "--store", store])["records"][0]
    args = [
        "confirm",
        str(package),
        "--store",
        str(store),
        "--id",
        "req:1",
        "--actor",
        "fictional-engineer",
        "--expected-head",
        updated["head_digest"],
        "--record-digest",
        "a" * 64,
        "--dependency-digest",
        shown["dependency_digest"],
    ]
    assert runner.invoke(app, args).exit_code == 1
    args[-3] = shown["record_digest"]
    (package / "package.json").write_bytes((package / "package.json").read_bytes() + b"\n")
    assert runner.invoke(app, args).exit_code == 1
    assert invoke_json(["show", package, "--store", store])["records"][0]["binding"]["needs_review"]


def test_refuses_cad_store_unknown_target_and_bad_vectors(workspace):
    package, store = workspace
    assert (
        runner.invoke(app, ["init", str(package), "--store", str(package / "sidecar")]).exit_code
        == 1
    )
    initial = invoke_json(["init", package, "--store", store])
    bad = runner.invoke(
        app,
        [
            "force",
            str(package),
            "--store",
            str(store),
            "--id",
            "force:1",
            "--kind",
            "component",
            "--entity",
            "cmp:0001",
            "--magnitude",
            "1",
            "--direction",
            "0,0,0",
            "--expected-head",
            initial["head_digest"],
        ],
    )
    assert bad.exit_code == 1
    assert invoke_json(["show", package, "--store", store])["revision"] == 1


def test_review_explicit_injection_is_bounded_recorded_and_read_only(workspace, tmp_path):
    from swreview.agent.providers.fake import FakeProvider, ScriptedToolCall, ScriptedTurn
    from swreview.agent.runner import start_review
    from swreview.engineering_context.store import ContextStore

    package, store = workspace
    initial = invoke_json(["init", package, "--store", store])
    invoke_json(
        [
            "requirement",
            package,
            "--store",
            store,
            "--id",
            "req:1",
            "--kind",
            "component",
            "--entity",
            "cmp:0001",
            "--text",
            "Support the operating load.",
            "--expected-head",
            initial["head_digest"],
        ]
    )
    artifact = ContextStore(store).load()
    provider = FakeProvider(
        model="fake",
        script=(
            ScriptedTurn(
                text="Input requires engineering review.",
                tool_calls=(ScriptedToolCall("get_engineering_context_summary"),),
            ),
        ),
    )
    run = start_review(
        package, tmp_path / "review", provider=provider, engineering_context=artifact
    )
    try:
        assert str(artifact.context_id) in run.opening_message
        summary = json.loads(
            (tmp_path / "review" / "engineering-context-summary.json").read_bytes()
        )
        assert summary["native_model_state"] == "not_observed"
        assert summary["counts"]["records"] == 1
        session = run.start()
        assert any(step.tool == "get_engineering_context_summary" for step in session.steps)
        assert ContextStore(store).load() == artifact
    finally:
        run.close()


def test_default_review_does_not_attach_or_load_context(workspace, tmp_path):
    from swreview.agent.providers.fake import FakeProvider, ScriptedTurn
    from swreview.agent.runner import start_review

    package, _ = workspace
    output = tmp_path / "default-review"
    output.mkdir()
    (output / "engineering-context-summary.json").write_text('{"context_id":"stale"}')
    run = start_review(
        package,
        output,
        provider=FakeProvider(model="fake", script=(ScriptedTurn(text="No context supplied."),)),
    )
    try:
        assert run.context.engineering_context is None
        assert "Engineer-supplied inputs" not in run.opening_message
        assert not (tmp_path / "default-review" / "engineering-context-summary.json").exists()
    finally:
        run.close()


def test_cli_diagnostics_do_not_echo_private_input_paths(workspace):
    package, store = workspace
    initial = invoke_json(["init", package, "--store", store])
    result = runner.invoke(
        app,
        [
            "force",
            str(package),
            "--store",
            str(store),
            "--id",
            "force:1",
            "--kind",
            "component",
            "--entity",
            "cmp:0001",
            "--magnitude",
            "2",
            "--direction",
            r"C:\FICT-SOURCE.sldprt,0,0",
            "--expected-head",
            initial["head_digest"],
        ],
    )
    assert result.exit_code == 1
    assert "FICT-SOURCE" not in result.output
    missing = runner.invoke(app, ["show", str(package / "PRIVATE-MISSING"), "--store", str(store)])
    assert missing.exit_code == 1
    assert "PRIVATE-MISSING" not in missing.output


def test_cli_withheld_evidence_refusal_is_handled_without_traceback(workspace, tmp_path):
    _, store = workspace
    result = runner.invoke(
        app, ["init", str(tmp_path / "benchmarks/answer_keys/PRIVATE-CASE"), "--store", str(store)]
    )
    assert result.exit_code == 1
    assert "withheld benchmark data" in result.stderr
    assert "PRIVATE-CASE" not in result.output


def test_installed_review_cli_explicit_context_option(workspace, tmp_path):
    from swreview.cli import app as main_app

    package, store = workspace
    initial = invoke_json(["init", package, "--store", store])
    invoke_json(
        [
            "requirement",
            package,
            "--store",
            store,
            "--id",
            "req:cli",
            "--kind",
            "document",
            "--entity",
            "doc:1",
            "--text",
            "Inspect the operating requirements.",
            "--expected-head",
            initial["head_digest"],
        ]
    )
    output = tmp_path / "explicit-review"
    result = runner.invoke(
        main_app,
        [
            "review",
            str(package),
            "--out",
            str(output),
            "--provider",
            "fake",
            "--engineering-context",
            str(store),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["provider"] == "fake"
    summary = json.loads((output / "engineering-context-summary.json").read_bytes())
    assert summary["context_id"] == initial["context_id"]
    assert summary["counts"]["records"] == 1
    assert (output / "report.md").exists()
