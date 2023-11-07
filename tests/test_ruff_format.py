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
    return pytest.fail()


def test_ruff_format(workspace):
    # imports incorrectly ordered,
    # body of foo has a line that's too long
    # def bar() line missing whitespace above
    txt = tw.dedent(
        """
        from thirdparty import x
        import io
        import asyncio

        def foo():
            print("this is a looooooooooooooooooooooooooooooooooooooooooooong line that should exceed the usual line-length limit which is normally eighty-eight columns")
        def bar():
            pass
        """  # noqa: E501
    ).lstrip()
    want = tw.dedent(
        """
        import asyncio
        import io

        from thirdparty import x


        def foo():
            print(
                "this is a looooooooooooooooooooooooooooooooooooooooooooong line that should exceed the usual line-length limit which is normally eighty-eight columns"
            )


        def bar():
            pass
        """  # noqa: E501
    ).lstrip()
    _, doc = temp_document(txt, workspace)
    got = run_plugin_format(workspace, doc)
    assert want == got, f"want:\n{want}\n\ngot:\n{got}"
