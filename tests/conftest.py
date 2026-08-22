import tempfile
from unittest.mock import Mock

import pytest
from pylsp import uris
from pylsp.config.config import Config
from pylsp.workspace import Document, Workspace


@pytest.fixture()
def workspace(tmp_path):
    """Return a workspace."""
    ws = Workspace(tmp_path.absolute().as_uri(), Mock())
    ws._config = Config(ws.root_uri, {}, 0, {})
    return ws


@pytest.fixture()
def notebook_workspace(tmp_path):
    """Workspace with a notebook and `ruff.toml`.

    Structure created under `tmp_path`:
        .
        ├── .virtual_documents
        │   └── foo
        │       └── bar.ipynb
        └── foo
            ├── bar.ipynb
            └── ruff.toml
    """
    virtual_dir = tmp_path / ".virtual_documents" / "foo"
    real_dir = tmp_path / "foo"
    virtual_dir.mkdir(parents=True)
    real_dir.mkdir(parents=True)

    (virtual_dir / "bar.ipynb").write_text("")
    (real_dir / "bar.ipynb").write_text("")
    (real_dir / "ruff.toml").write_text("")

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
