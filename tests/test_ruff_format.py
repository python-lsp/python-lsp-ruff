import contextlib
import tempfile
import textwrap as tw
from typing import Any, List, Mapping, Optional
from unittest.mock import Mock

import pytest
from pylsp import uris
from pylsp.config.config import Config
from pylsp.workspace import Document, Workspace

import pylsp_ruff.plugin as plugin

_UNSORTED_IMPORTS = tw.dedent(
    """
    from thirdparty import x
    import io
    import asyncio
    """
).strip()

_UNUSED_IMPORTS = tw.dedent(
    """
    import unused_import
    """
).strip()

_SORTED_IMPORTS = tw.dedent(
    """
    import asyncio
    import io

    from thirdparty import x
    """
).strip()

_UNFORMATTED_CODE = tw.dedent(
    """
    def foo(): return asyncio.subprocess.DEVNULL
    def bar(): return x(io.DEFAULT_BUFFER_SIZE)
    """
).strip()

_FORMATTED_CODE = tw.dedent(
    """
    def foo():
        return asyncio.subprocess.DEVNULL


    def bar():
        return x(io.DEFAULT_BUFFER_SIZE)
    """
).strip()


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


def run_plugin_format(workspace: Workspace, doc: Document) -> str:
    class TestResult:
        result: Optional[List[Mapping[str, Any]]]

        def __init__(self):
            self.result = None

        def get_result(self):
            return self.result

        def force_result(self, r):
            self.result = r

    generator = plugin.pylsp_format_document(workspace, doc)
    result = TestResult()
    with contextlib.suppress(StopIteration):
        generator.send(None)
        generator.send(result)

    if result.result:
        return result.result[0]["newText"]
    return ""


def test_ruff_format_only(workspace):
    txt = f"{_UNSORTED_IMPORTS}\n{_UNFORMATTED_CODE}"
    want = f"{_UNSORTED_IMPORTS}\n\n\n{_FORMATTED_CODE}\n"
    _, doc = temp_document(txt, workspace)
    got = run_plugin_format(workspace, doc)
    assert want == got


def test_ruff_format_disabled(workspace):
    _, doc = temp_document(_UNFORMATTED_CODE, workspace)
    workspace._config.update(
        {"plugins": {"ruff": {"format": ["I001"], "formatEnabled": False}}}
    )
    got = run_plugin_format(workspace, doc)
    assert got == ""


def test_ruff_format_and_sort_imports(workspace):
    txt = f"{_UNSORTED_IMPORTS}\n{_UNFORMATTED_CODE}"
    want = f"{_SORTED_IMPORTS}\n\n\n{_FORMATTED_CODE}\n"
    _, doc = temp_document(txt, workspace)
    workspace._config.update(
        {
            "plugins": {
                "ruff": {
                    "format": ["I001"],
                }
            }
        }
    )
    got = run_plugin_format(workspace, doc)
    assert want == got


def test_ruff_format_via_all(workspace):
    # If `pylsp.plugins.ruff.format` contains "ALL", formatting should apply
    # the automatic fixes for unsorted-imports (I001) and unused-import (F401)
    txt = f"{_UNUSED_IMPORTS}\n{_UNSORTED_IMPORTS}\n{_UNFORMATTED_CODE}"
    want = f"{_SORTED_IMPORTS}\n\n\n{_FORMATTED_CODE}\n"
    _, doc = temp_document(txt, workspace)
    workspace._config.update(
        {
            "plugins": {
                "ruff": {
                    "format": ["ALL"],
                }
            }
        }
    )
    got = run_plugin_format(workspace, doc)
    assert want == got
