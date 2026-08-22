import contextlib
import os
import textwrap as tw
from typing import Any, List, Mapping, Optional
from unittest.mock import patch

from conftest import temp_document
from pylsp import uris
from pylsp.workspace import Document, Workspace

import pylsp_ruff.plugin as plugin

_UNSORTED_IMPORTS = tw.dedent(
    """
    from thirdparty import x
    import io
    import asyncio
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
    def foo(): pass
    def bar(): pass
    """
).strip()

_FORMATTED_CODE = tw.dedent(
    """
    def foo():
        pass


    def bar():
        pass
    """
).strip()


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


def test_ruff_format_strips_virtual_documents_path(notebook_workspace):
    virtual_path = os.path.join(
        notebook_workspace.root_path, ".virtual_documents", "foo", "bar.ipynb"
    )
    expected_stripped = os.path.join(notebook_workspace.root_path, "foo", "bar.ipynb")
    doc_uri = uris.from_fs_path(virtual_path)
    notebook_workspace.put_document(doc_uri, _UNFORMATTED_CODE)
    doc = notebook_workspace.get_document(doc_uri)

    with patch("pylsp_ruff.plugin.Popen") as popen_mock:
        mock_instance = popen_mock.return_value
        mock_instance.communicate.return_value = [bytes(), bytes()]
        run_plugin_format(notebook_workspace, doc)

    format_calls = [
        call for call in popen_mock.call_args_list if "format" in call[0][0]
    ]
    assert format_calls, "ruff format was not invoked"
    cmd = format_calls[0][0][0]
    assert f"--stdin-filename={expected_stripped}" in cmd
    assert f"--stdin-filename={virtual_path}" not in cmd


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
