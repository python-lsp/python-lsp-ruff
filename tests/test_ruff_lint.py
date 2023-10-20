# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.

import os
import sys
import tempfile
from unittest.mock import Mock, patch

import pytest
from pylsp import lsp, uris
from pylsp.config.config import Config
from pylsp.workspace import Document, Workspace

import pylsp_ruff.plugin as ruff_lint

DOC_URI = uris.from_fs_path(__file__)
DOC = r"""import pylsp

t = "TEST"

def using_const():
    a = 8 + 9
    return t
"""


@pytest.fixture()
def workspace(tmp_path):
    """Return a workspace."""
    ws = Workspace(tmp_path.absolute().as_uri(), Mock())
    ws._config = Config(ws.root_uri, {}, 0, {})
    return ws


def temp_document(doc_text, workspace):
    with tempfile.NamedTemporaryFile(
        mode="w", dir=workspace.root_path, delete=False
    ) as temp_file:
        name = temp_file.name
        temp_file.write(doc_text)
    doc = Document(uris.from_fs_path(name), workspace)
    return name, doc


def test_ruff_unsaved(workspace):
    doc = Document("", workspace, DOC)
    diags = ruff_lint.pylsp_lint(workspace, doc)
    msg = "Local variable `a` is assigned to but never used"
    unused_var = [d for d in diags if d["message"] == msg][0]

    assert unused_var["source"] == "ruff"
    assert unused_var["code"] == "F841"
    assert unused_var["range"]["start"] == {"line": 5, "character": 4}
    assert unused_var["range"]["end"] == {"line": 5, "character": 5}
    assert unused_var["severity"] == lsp.DiagnosticSeverity.Error
    assert unused_var["tags"] == [lsp.DiagnosticTag.Unnecessary]


def test_ruff_lint(workspace):
    name, doc = temp_document(DOC, workspace)
    try:
        diags = ruff_lint.pylsp_lint(workspace, doc)
        msg = "Local variable `a` is assigned to but never used"
        unused_var = [d for d in diags if d["message"] == msg][0]

        assert unused_var["source"] == "ruff"
        assert unused_var["code"] == "F841"
        assert unused_var["range"]["start"] == {"line": 5, "character": 4}
        assert unused_var["range"]["end"] == {"line": 5, "character": 5}
        assert unused_var["severity"] == lsp.DiagnosticSeverity.Error
        assert unused_var["tags"] == [lsp.DiagnosticTag.Unnecessary]
    finally:
        os.remove(name)


def test_ruff_config_param(workspace):
    with patch("pylsp_ruff.plugin.Popen") as popen_mock:
        mock_instance = popen_mock.return_value
        mock_instance.communicate.return_value = [bytes(), bytes()]
        ruff_conf = "/tmp/pyproject.toml"
        workspace._config.update(
            {
                "plugins": {
                    "ruff": {
                        "config": ruff_conf,
                        "extendSelect": ["D", "F"],
                        "extendIgnore": ["E"],
                    }
                }
            }
        )
        _name, doc = temp_document(DOC, workspace)
        ruff_lint.pylsp_lint(workspace, doc)
        (call_args,) = popen_mock.call_args[0]
        assert "ruff" in call_args
        assert f"--config={ruff_conf}" in call_args
        assert "--extend-select=D,F" in call_args
        assert "--extend-ignore=E" in call_args


def test_ruff_executable_param(workspace):
    with patch("pylsp_ruff.plugin.Popen") as popen_mock:
        mock_instance = popen_mock.return_value
        mock_instance.communicate.return_value = [bytes(), bytes()]

        ruff_executable = "/tmp/ruff"
        workspace._config.update({"plugins": {"ruff": {"executable": ruff_executable}}})

        _name, doc = temp_document(DOC, workspace)
        ruff_lint.pylsp_lint(workspace, doc)

        (call_args,) = popen_mock.call_args[0]
        assert ruff_executable in call_args


def get_ruff_settings(workspace, doc, config_str):
    """Write a ``pyproject.toml``, load it in the workspace, and return the ruff
    settings.

    This function creates a ``pyproject.toml``; you'll have to delete it yourself.
    """

    with open(
        os.path.join(workspace.root_path, "pyproject.toml"), "w+", encoding="utf-8"
    ) as f:
        f.write(config_str)

    return ruff_lint.load_settings(workspace, doc.path)


def test_ruff_settings(workspace):
    config_str = r"""[tool.ruff]
ignore = ["F841"]
exclude = [
    "blah/__init__.py",
    "file_2.py"
]
extend-select = ["D"]
[tool.ruff.per-file-ignores]
"test_something.py" = ["F401"]
"""

    doc_str = r"""
print('hi')
import os
def f():
    a = 2
"""

    doc_uri = uris.from_fs_path(os.path.join(workspace.root_path, "__init__.py"))
    workspace.put_document(doc_uri, doc_str)

    ruff_settings = get_ruff_settings(
        workspace, workspace.get_document(doc_uri), config_str
    )

    # Check that user config is ignored
    empty_keys = [
        "config",
        "line_length",
        "exclude",
        "select",
        "ignore",
        "per_file_ignores",
    ]
    for k in empty_keys:
        assert getattr(ruff_settings, k) is None

    with patch("pylsp_ruff.plugin.Popen") as popen_mock:
        mock_instance = popen_mock.return_value
        mock_instance.communicate.return_value = [bytes(), bytes()]

        doc = workspace.get_document(doc_uri)
        diags = ruff_lint.pylsp_lint(workspace, doc)

    call_args = popen_mock.call_args[0][0]
    assert call_args == [
        str(sys.executable),
        "-m",
        "ruff",
        "--quiet",
        "--exit-zero",
        "--output-format=json",
        "--no-fix",
        "--force-exclude",
        f"--stdin-filename={os.path.join(workspace.root_path, '__init__.py')}",
        "--",
        "-",
    ]

    workspace._config.update(
        {
            "plugins": {
                "ruff": {
                    "extendIgnore": ["D104"],
                    "severities": {"E402": "E", "D103": "I"},
                }
            }
        }
    )

    diags = ruff_lint.pylsp_lint(workspace, doc)

    _list = []
    for diag in diags:
        _list.append(diag["code"])
    # Assert that ignore, extend-ignore and extend-select is working as intended
    assert "E402" in _list
    assert "D103" in _list
    assert "D104" not in _list
    assert "F841" not in _list

    # Check custom severities
    for diag in diags:
        if diag["code"] == "E402":
            assert diag["severity"] == 1
        if diag["code"] == "D103":
            assert diag["severity"] == 3

    # Excludes
    doc_uri = uris.from_fs_path(os.path.join(workspace.root_path, "blah/__init__.py"))
    workspace.put_document(doc_uri, doc_str)

    ruff_settings = get_ruff_settings(
        workspace, workspace.get_document(doc_uri), config_str
    )

    doc = workspace.get_document(doc_uri)
    diags = ruff_lint.pylsp_lint(workspace, doc)
    assert diags == []

    # For per-file-ignores
    doc_uri_per_file_ignores = uris.from_fs_path(
        os.path.join(workspace.root_path, "blah/test_something.py")
    )
    workspace.put_document(doc_uri_per_file_ignores, doc_str)

    doc = workspace.get_document(doc_uri)
    diags = ruff_lint.pylsp_lint(workspace, doc)

    for diag in diags:
        assert diag["code"] != "F401"

    os.unlink(os.path.join(workspace.root_path, "pyproject.toml"))
