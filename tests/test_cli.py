import pytest

from deployment_agent import cli
from deployment_agent.agent.graph import run_agent


def test_repository_argument_must_be_owner_and_repo():
    with pytest.raises(ValueError, match="OWNER/REPOSITORY"):
        run_agent("not-a-repository", "deploy it")


def test_cli_preview_declines_publication_by_default(monkeypatch, capsys):
    preview = {
        "preview_changes": [
            {"repository": "acme/service", "path": "values.yaml", "diff": "+replicaCount: 3\n"}
        ]
    }
    monkeypatch.setattr(
        "sys.argv",
        ["deployment-agent", "--repo", "acme/service", "--requirement", "deploy"],
    )
    monkeypatch.setattr(cli, "run_agent", lambda *_: preview)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "no")
    monkeypatch.setattr(
        cli,
        "publish_agent_result",
        lambda _: pytest.fail("Declined preview must not publish"),
    )

    cli.main()

    assert "No PR was created" in capsys.readouterr().out


def test_cli_yes_publishes_preview_non_interactively(monkeypatch, capsys):
    preview = {
        "preview_changes": [
            {"repository": "acme/service", "path": "values.yaml", "diff": "+replicaCount: 3\n"}
        ]
    }
    published = {"pull_request_urls": ["https://github.com/acme/service/pull/1"]}
    monkeypatch.setattr(
        "sys.argv",
        [
            "deployment-agent",
            "--repo",
            "acme/service",
            "--requirement",
            "deploy",
            "--yes",
        ],
    )
    monkeypatch.setattr(cli, "run_agent", lambda *_: preview)
    monkeypatch.setattr(cli, "publish_agent_result", lambda _: published)

    cli.main()

    assert "https://github.com/acme/service/pull/1" in capsys.readouterr().out
