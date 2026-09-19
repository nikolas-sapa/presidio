import argparse
import os
import pytest
from io import StringIO
from presidio_cli import cli
from presidio_cli.config import PresidioCLIConfig as RealPresidioCLIConfig


@pytest.fixture()
def problems(mocker):
    problem1 = mocker.Mock(
        line=1,
        column=7,
        score=1.0,
        level="error",
        type="PERSON",
        explanation=None,
        recognizer_result={},
    )
    problem2 = mocker.Mock(
        line=2,
        column=17,
        score=0.85,
        level="warning",
        type="PERSON",
        explanation="some example",
        recognizer_result={},
    )
    return [problem1, problem2]


def make_args(**overrides):
    args = {
        "stdin": False,
        "config_data": None,
        "config_file": None,
        "files": ("tests/",),
        "format": "auto",
        "no_warnings": False,
        "threshold": None,
    }
    args.update(overrides)
    return args


def make_conf(mocker, threshold=0.25):
    conf = mocker.Mock()
    conf.threshold = threshold
    conf.locale = None
    return conf


def test_find_files_recursively(temp_workspace, config):
    assert sorted(cli.find_files_recursively([temp_workspace], config)) == [
        os.path.join(temp_workspace, "dos.yml"),
        os.path.join(temp_workspace, "empty.txt"),
        os.path.join(temp_workspace, "errorfile"),
        os.path.join(temp_workspace, "non-ascii", "éçäγλνπ¥", "utf-8"),
        os.path.join(temp_workspace, *["s"] * 15, "file"),
        os.path.join(temp_workspace, "sub", "directory.txt", "empty.txt"),
    ]


@pytest.mark.parametrize(
    "arg_format",
    [
        "auto",
        "standard",
        "colored",
        "github",
        "parsable",
    ],
)
def test_show_problems(arg_format, problems):
    filepath = "./example.txt"

    rc = cli.show_problems(problems, filepath, arg_format, False)
    assert rc == 2


def test_show_problems_no_warnings_filters(problems, capsys):
    rc = cli.show_problems(problems, "example.txt", "standard", True)
    assert rc == 1
    out = capsys.readouterr().out
    assert "PERSON" in out
    assert "some example" not in out


def test_github_format_uses_workflow_commands(problems):
    error_line = cli.Format.github(problems[0], "pii.txt")
    assert error_line.startswith("::error file=pii.txt,line=1,col=7::")
    assert "[PERSON]" in error_line

    warning_line = cli.Format.github(problems[1], "pii.txt")
    assert warning_line.startswith("::warning file=pii.txt,line=2,col=17::")


def test_github_format_escapes_values(mocker):
    problem = mocker.Mock(
        line=1,
        column=1,
        score=1.0,
        level="error",
        type="PERSON",
        explanation="a%b\nc",
        recognizer_result={},
    )
    line = cli.Format.github(problem, "dir/a,b:c.txt")
    assert "file=dir/a%2Cb%3Ac.txt" in line
    assert line.endswith("a%25b%0Ac")


def test_show_problems_auto_gh(problems, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_WORKFLOW", "true")

    filepath = "./example.txt"
    rc = cli.show_problems(problems, filepath, "auto", False)
    assert rc == 2


def test_show_problems_auto_color(problems, monkeypatch, mocker):
    monkeypatch.setenv("TERM", "xterm-256color")
    mocker.patch("sys.stdout")
    filepath = "./example.txt"
    rc = cli.show_problems(problems, filepath, "auto", False)
    assert rc == 2


def test_run_current_dir(temp_workspace, mocker):
    os.chdir(temp_workspace)
    mocker.patch("sys.argv", ["", "."])
    ec = mocker.patch("sys.exit")
    cli.run()
    # temp workspace contains PII fixtures, so findings are printed
    ec.assert_called_once_with(1)


def test_run_with_config(temp_workspace, mocker):
    with open(os.path.join(temp_workspace, ".presidiocli"), "w") as f:
        f.write("extends: default\n")

    os.chdir(temp_workspace)
    mocker.patch("sys.argv", ["-c", ".presidiocli", "."])
    ec = mocker.patch("sys.exit")
    cli.run()
    # temp workspace contains PII fixtures, so findings are printed
    ec.assert_called_once_with(1)


def test_run_preserves_config_threshold_when_flag_is_omitted(mocker):
    mocked_args = mocker.Mock(**make_args())
    conf = make_conf(mocker)
    config = mocker.patch("presidio_cli.cli.PresidioCLIConfig", return_value=conf)
    mocker.patch("presidio_cli.cli.find_files_recursively", return_value=[])
    mocker.patch("os.path.isfile", return_value=False)
    mocker.patch("argparse.ArgumentParser.parse_args", return_value=mocked_args)
    ec = mocker.patch("sys.exit")

    cli.run()

    config.assert_called_once_with(content="extends: default")
    assert conf.threshold == 0.25
    ec.assert_called_once_with(0)


def test_run_overrides_loaded_config_threshold(mocker, tmp_path):
    config_file = tmp_path / "config.yml"
    config_file.write_text("threshold: 0.25\n")

    mocked_args = mocker.Mock(**make_args(config_file=str(config_file), threshold=0.7))
    loaded_thresholds = []
    captured = {}

    def build_config(*args, **kwargs):
        conf = RealPresidioCLIConfig(*args, **kwargs)
        loaded_thresholds.append(conf.threshold)
        captured["conf"] = conf
        return conf

    mocker.patch("presidio_cli.cli.PresidioCLIConfig", side_effect=build_config)
    mocker.patch("presidio_cli.cli.find_files_recursively", return_value=[])
    mocker.patch("argparse.ArgumentParser.parse_args", return_value=mocked_args)
    ec = mocker.patch("sys.exit")

    cli.run()

    assert loaded_thresholds == [0.25]
    assert captured["conf"].threshold == 0.7
    ec.assert_called_once_with(0)


def test_run_respects_config_selection_before_threshold_override(mocker):
    mocked_args = mocker.Mock(
        **make_args(config_data="extends: limited", config_file="custom.yaml")
    )
    conf = make_conf(mocker)
    config = mocker.patch("presidio_cli.cli.PresidioCLIConfig", return_value=conf)
    mocker.patch("presidio_cli.cli.find_files_recursively", return_value=[])
    mocker.patch("os.path.isfile", return_value=False)
    mocker.patch("argparse.ArgumentParser.parse_args", return_value=mocked_args)
    ec = mocker.patch("sys.exit")

    cli.run()

    config.assert_called_once_with(content="extends: limited")
    assert conf.threshold == 0.25
    ec.assert_called_once_with(0)


def test_run_accepts_explicit_zero_threshold(mocker):
    mocked_args = mocker.Mock(**make_args(threshold=0.0))
    conf = make_conf(mocker)
    config = mocker.patch("presidio_cli.cli.PresidioCLIConfig", return_value=conf)
    mocker.patch("presidio_cli.cli.find_files_recursively", return_value=[])
    mocker.patch("os.path.isfile", return_value=False)
    mocker.patch("argparse.ArgumentParser.parse_args", return_value=mocked_args)
    ec = mocker.patch("sys.exit")

    cli.run()

    config.assert_called_once_with(content="extends: default")
    assert conf.threshold == 0.0
    ec.assert_called_once_with(0)


@pytest.mark.parametrize("value", ["-0.1", "1.1", "not-a-number"])
def test_threshold_value_rejects_invalid_values(value):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.threshold_value(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0", 0.0), ("0.7", 0.7), ("1", 1.0)],
)
def test_threshold_value_accepts_valid_values(value, expected):
    assert cli.threshold_value(value) == expected


def test_run_with_stdin(mocker):
    mocked_args = mocker.Mock(**make_args(stdin=True, files=()))
    conf = make_conf(mocker)
    mocker.patch("presidio_cli.cli.PresidioCLIConfig", return_value=conf)
    mocker.patch("presidio_cli.cli.find_files_recursively", return_value=[])
    mocker.patch("presidio_cli.cli.analyze", return_value=[])
    mocker.patch("argparse.ArgumentParser.parse_args", return_value=mocked_args)
    mocker.patch("sys.stdin", StringIO("Example input"))
    ec = mocker.patch("sys.exit")
    cli.run()
    ec.assert_called_once_with(0)
