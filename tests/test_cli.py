from __future__ import annotations

import io
import os

from fable_table_engine import cli


def test_load_dotenv_sets_missing_values(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join([
            "# comment",
            "ANTHROPIC_API_KEY=test-key",
            "FABLE_ENV='development'",
        ]),
        encoding="utf-8",
    )

    cli.load_dotenv(env_path)

    assert os.environ["ANTHROPIC_API_KEY"] == "test-key"
    assert os.environ["FABLE_ENV"] == "development"


def test_load_dotenv_does_not_override_existing_values(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "existing")
    env_path = tmp_path / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=replacement\n", encoding="utf-8")

    cli.load_dotenv(env_path)

    assert os.environ["ANTHROPIC_API_KEY"] == "existing"


def test_terminal_app_reports_missing_api_key_for_new_session(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    stdin = io.StringIO("new\nquit\n")
    stdout = io.StringIO()

    code = cli.TerminalApp(root=tmp_path, stdin=stdin, stdout=stdout).run()

    assert code == 0
    output = stdout.getvalue()
    assert "ANTHROPIC_API_KEY is not set" in output
    assert "home>" in output


def test_main_help_and_version(capsys):
    assert cli.main(["--help"]) == 0
    assert "Usage: fable-play" in capsys.readouterr().out

    assert cli.main(["--version"]) == 0
    assert "fable-table-engine" in capsys.readouterr().out
