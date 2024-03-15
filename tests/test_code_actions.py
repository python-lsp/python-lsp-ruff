# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.

import tempfile
from textwrap import dedent
from typing import List
from unittest.mock import Mock

import cattrs
import pytest
from lsprotocol.converters import get_converter
from lsprotocol.types import CodeAction, Position, Range
from pylsp import uris
from pylsp.config.config import Config
from pylsp.workspace import Document, Workspace

import pylsp_ruff.plugin as ruff_lint

converter = get_converter()


@pytest.fixture()
def workspace(tmp_path):
    """Return a workspace."""
    ws = Workspace(tmp_path.absolute().as_uri(), Mock())
    ws._config = Config(ws.root_uri, {}, 0, {})
    return ws


codeaction_str = dedent(
    """
    import os
    def f():
        a = 2
    """
)

import_str = dedent(
    """
    import pathlib
    import os
    """
)

codeactions = [
    "Ruff (F401): Remove unused import: `os`",
    "Ruff (F401): Disable for this line",
    "Ruff (F841): Remove assignment to unused variable `a` (unsafe)",
    "Ruff (F841): Disable for this line",
    "Ruff: Fix All (safe fixes)",
]

codeactions_import = [
    "Ruff: Organize imports",
    "Ruff: Fix All (safe fixes)",
    "Ruff (I001): Disable for this line",
]


def temp_document(doc_text, workspace):
    with tempfile.NamedTemporaryFile(
        mode="w", dir=workspace.root_path, delete=False
    ) as temp_file:
        name = temp_file.name
        temp_file.write(doc_text)
    doc = Document(uris.from_fs_path(name), workspace)
    return name, doc


def test_ruff_code_actions(workspace):
    _, doc = temp_document(codeaction_str, workspace)

    workspace._config.update(
        {"plugins": {"ruff": {"select": ["F"], "unsafeFixes": True}}}
    )
    diags = ruff_lint.pylsp_lint(workspace, doc)
    range_ = cattrs.unstructure(
        Range(start=Position(line=0, character=0), end=Position(line=0, character=0))
    )
    actions = ruff_lint.pylsp_code_actions(
        workspace._config, workspace, doc, range=range_, context={"diagnostics": diags}
    )
    actions = converter.structure(actions, List[CodeAction])
    action_titles = list(map(lambda action: action.title, actions))
    assert sorted(codeactions) == sorted(action_titles)


def test_import_action(workspace):
    workspace._config.update(
        {
            "plugins": {
                "ruff": {
                    "extendSelect": ["I"],
                    "extendIgnore": ["F"],
                }
            }
        }
    )
    _, doc = temp_document(import_str, workspace)

    diags = ruff_lint.pylsp_lint(workspace, doc)
    range_ = cattrs.unstructure(
        Range(start=Position(line=0, character=0), end=Position(line=0, character=0))
    )
    actions = ruff_lint.pylsp_code_actions(
        workspace._config, workspace, doc, range=range_, context={"diagnostics": diags}
    )
    actions = converter.structure(actions, List[CodeAction])
    action_titles = list(map(lambda action: action.title, actions))
    assert sorted(codeactions_import) == sorted(action_titles)


def test_fix_all(workspace):
    expected_str = dedent(
        """
        def f():
            pass
        """
    )
    expected_str_safe = dedent(
        """
        def f():
            a = 2
        """
    )
    workspace._config.update(
        {
            "plugins": {
                "ruff": {
                    "unsafeFixes": True,
                }
            }
        }
    )
    _, doc = temp_document(codeaction_str, workspace)
    settings = ruff_lint.load_settings(workspace, doc.path)
    fixed_str = ruff_lint.run_ruff_fix(doc, settings)
    assert fixed_str == expected_str

    workspace._config.update(
        {
            "plugins": {
                "ruff": {
                    "unsafeFixes": False,
                }
            }
        }
    )
    _, doc = temp_document(codeaction_str, workspace)
    settings = ruff_lint.load_settings(workspace, doc.path)
    fixed_str = ruff_lint.run_ruff_fix(doc, settings)
    assert fixed_str == expected_str_safe
