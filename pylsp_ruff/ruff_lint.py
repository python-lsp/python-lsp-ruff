import json
import logging
from pathlib import PurePath
from subprocess import PIPE, Popen, SubprocessError

from pylsp import hookimpl, lsp
from pylsp._utils import find_parents
from pylsp.workspace import Document, Workspace

log = logging.getLogger(__name__)

UNNECESSITY_CODES = {
    "F401",  # `module` imported but unused
    "F504",  # % format unused named arguments
    "F522",  # .format(...) unused named arguments
    "F523",  # .format(...) unused positional arguments
    "F841",  # local variable `name` is assigned to but never used
}


@hookimpl
def pylsp_settings():
    # flake8 and pycodestyle disabled by default with this plugin
    return {
        "plugins": {
            "ruff": {
                "enabled": True,
                "config": None,
                "exclude": None,
                "executable": "ruff",
                "ignore": None,
                "lineLength": None,
                "perFileIgnores": None,
                "select": None,
            },
            "flake8": {"enabled": False},
            "pycodestyle": {"enabled": False},
        }
    }


@hookimpl
def pylsp_lint(workspace: Workspace, document: Document) -> list:
    """
    Register ruff as the linter.

    Parameters
    ----------
    workspace : pylsp.workspace.Workspace
        Current workspace.
    document : pylsp.workspace.Document
        Document to apply ruff on.

    Returns
    -------
    List of dicts containing the diagnostics.
    """
    config = workspace._config
    settings = config.plugin_settings("ruff", document_path=document.path)
    log.debug(f"Got ruff settings: {settings}")

    args_dict = load_config(workspace, document)
    ruff_executable = args_dict.pop("executable")
    args = build_args(document, args_dict)

    output = run_ruff_lint(ruff_executable, document, args)
    return parse_ruff_stdout(output)


def run_ruff_lint(ruff_executable: str, document: Document, arguments: list) -> str:
    """
    Run ruff on the given document and the given arguments.

    Parameters
    ----------
    ruff_executable : str
        Path to the executable.
    document : pylsp.workspace.Document
        File to run ruff on.
    arguments : list
        Arguments to provide for ruff.

    Returns
    -------
    String containing the result in json format.
    """
    log.debug(f"Calling {ruff_executable} with args: {arguments} on '{document.path}'")
    try:
        cmd = [ruff_executable]
        cmd.extend(arguments)
        p = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    except SubprocessError as e:
        # Ruff doesn't yet support calling with python -m ruff,
        # see https://github.com/charliermarsh/ruff/issues/593
        log.error(f"Error running {ruff_executable}: {e}")
    (stdout, stderr) = p.communicate(document.source.encode())

    if stderr:
        log.error(f"Error running ruff: {stderr.decode()}")
    return stdout.decode()


def parse_ruff_stdout(stdout: str) -> list:
    """
    Convert the ruff stdout to a list of Python dicts.

    See the flake8 implementation for the resulting format of dicts.

    Parameters
    ----------
    stdout : str
        Standard output of the ruff process.

    Returns
    -------
    List of dicts containing the diagnostics.
    """
    result_list = []

    # Catch empty list
    if stdout == "":
        return []

    diagnostics = json.loads(stdout)

    for diagnostic in diagnostics:
        result_dict = {}
        result_dict["source"] = "ruff"
        result_dict["code"] = diagnostic["code"]

        # Convert range to LSP specification
        result_dict["range"] = {  # type: ignore
            "start": {
                # Adapt range to LSP specification (zero-based)
                "line": diagnostic["location"]["row"] - 1,
                "character": diagnostic["location"]["column"] - 1,
            },
            "end": {
                "line": diagnostic["end_location"]["row"] - 1,
                "character": diagnostic["end_location"]["column"] - 1,
            },
        }

        result_dict["message"] = diagnostic["message"]

        # Ruff intends to implement severity codes in the future,
        # see https://github.com/charliermarsh/ruff/issues/645.
        result_dict["severity"] = lsp.DiagnosticSeverity.Warning
        if diagnostic["code"] == "E999" or diagnostic["code"][0] == "F":
            result_dict["severity"] = lsp.DiagnosticSeverity.Error

        if diagnostic["code"] in UNNECESSITY_CODES:
            result_dict["tags"] = [lsp.DiagnosticTag.Unnecessary]  # type: ignore

        result_list.append(result_dict)

    return result_list


def build_args(document: Document, options: dict) -> list:
    """
    Build arguments for ruff.

    Parameters
    ----------
    document : pylsp.workspace.Document
        Document to apply ruff on.
    options : dict
        Dict of arguments to pass to ruff.

    Returns
    -------
    List containing the arguments.
    """
    # Suppress update announcements
    args = ["--quiet"]
    # Use the json formatting for easier evaluation
    args.extend(["--format=json"])
    # Do not attempt to fix -> returns file instead of diagnostics
    args.extend(["--no-fix"])
    # Always force excludes
    args.extend(["--force-exclude"])
    # Pass filename to ruff for per-file-ignores, catch unsaved
    if document.path != "":
        args.extend(["--stdin-filename", document.path])

    # Convert per-file-ignores dict to right format
    per_file_ignores = options.pop("per-file-ignores")

    if per_file_ignores:
        for path, errors in per_file_ignores.items():
            errors = (",").join(errors)
            if PurePath(document.path).match(path):
                args.extend([f"--ignore={errors}"])

    for arg_name, arg_val in options.items():
        if arg_val is None:
            continue
        arg = None
        if isinstance(arg_val, list):
            arg = "--{}={}".format(arg_name, ",".join(arg_val))
        else:
            arg = "--{}={}".format(arg_name, arg_val)
        args.append(arg)

    args.extend(["--", "-"])

    return args


def load_config(workspace: Workspace, document: Document) -> dict:
    """
    Load settings from pyproject.toml file in the project path.

    Parameters
    ----------
    workspace : pylsp.workspace.Workspace
        Current workspace.
    document : pylsp.workspace.Document
        Document to apply ruff on.

    Returns
    -------
    Dictionary containing the settings to use when calling ruff.
    """
    config = workspace._config
    _settings = config.plugin_settings("ruff", document_path=document.path)

    pyproject_file = find_parents(
        workspace.root_path, document.path, ["pyproject.toml"]
    )

    # Check if pyproject is present, ignore user settings if toml exists
    if pyproject_file:
        log.debug(
            f"Found pyproject file: {str(pyproject_file[0])}, "
            + "skipping pylsp config."
        )

        # Leave config to pyproject.toml
        settings = {
            "config": None,
            "exclude": None,
            "executable": _settings.get("executable", "ruff"),
            "ignore": None,
            "line-length": None,
            "per-file-ignores": None,
            "select": None,
        }

    else:
        # Default values are given by ruff
        settings = {
            "config": _settings.get("config", None),
            "exclude": _settings.get("exclude", None),
            "executable": _settings.get("executable", "ruff"),
            "ignore": _settings.get("ignore", None),
            "line-length": _settings.get("lineLength", None),
            "per-file-ignores": _settings.get("perFileIgnores", None),
            "select": _settings.get("select", None),
        }

    return settings
