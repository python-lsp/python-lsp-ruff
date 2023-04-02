import json
import logging
import re
import sys
from pathlib import PurePath
from subprocess import PIPE, Popen
from typing import Dict, List

from lsprotocol.converters import get_converter
from lsprotocol.types import (
    CodeAction,
    CodeActionContext,
    CodeActionKind,
    Diagnostic,
    DiagnosticSeverity,
    DiagnosticTag,
    Position,
    Range,
    TextEdit,
    WorkspaceEdit,
)
from pylsp import hookimpl
from pylsp._utils import find_parents
from pylsp.config.config import Config
from pylsp.workspace import Document, Workspace

from pylsp_ruff.ruff import Check as RuffCheck
from pylsp_ruff.ruff import Fix as RuffFix

log = logging.getLogger(__name__)
converter = get_converter()

DIAGNOSTIC_SOURCE = "ruff"

# shamelessly borrowed from:
# https://github.com/charliermarsh/ruff-lsp/blob/2a0e2ea3afefdbf00810b8df91030c1c6b59d103/ruff_lsp/server.py#L214
NOQA_REGEX = re.compile(
    r"(?i:# (?:(?:ruff|flake8): )?(?P<noqa>noqa))"
    r"(?::\s?(?P<codes>([A-Z]+[0-9]+(?:[,\s]+)?)+))?"
)

UNNECESSITY_CODES = {
    "F401",  # `module` imported but unused
    "F504",  # % format unused named arguments
    "F522",  # .format(...) unused named arguments
    "F523",  # .format(...) unused positional arguments
    "F841",  # local variable `name` is assigned to but never used
}


@hookimpl
def pylsp_settings():
    log.debug("Initializing pylsp_ruff")
    # this plugin disables flake8, mccabe, and pycodestyle by default
    return {
        "plugins": {
            "ruff": {
                "enabled": True,
                "config": None,
                "exclude": None,
                "executable": "ruff",
                "ignore": None,
                "extendIgnore": None,
                "lineLength": None,
                "perFileIgnores": None,
                "select": None,
                "extendSelect": None,
            },
            "pyflakes": {"enabled": False},
            "flake8": {"enabled": False},
            "mccabe": {"enabled": False},
            "pycodestyle": {"enabled": False},
        }
    }


@hookimpl
def pylsp_lint(workspace: Workspace, document: Document) -> List[Dict]:
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
    checks = run_ruff_check(workspace, document)
    diagnostics = [create_diagnostic(c) for c in checks]
    return converter.unstructure(diagnostics)


def create_diagnostic(check: RuffCheck) -> Diagnostic:
    # Adapt range to LSP specification (zero-based)
    range = Range(
        start=Position(
            line=check.location.row - 1,
            character=check.location.column - 1,
        ),
        end=Position(
            line=check.end_location.row - 1,
            character=check.end_location.column - 1,
        ),
    )

    # Ruff intends to implement severity codes in the future,
    # see https://github.com/charliermarsh/ruff/issues/645.
    severity = DiagnosticSeverity.Warning
    if check.code == "E999" or check.code[0] == "F":
        severity = DiagnosticSeverity.Error

    tags = []
    if check.code in UNNECESSITY_CODES:
        tags = [DiagnosticTag.Unnecessary]

    return Diagnostic(
        source=DIAGNOSTIC_SOURCE,
        code=check.code,
        range=range,
        message=check.message,
        severity=severity,
        tags=tags,
        data=check.fix,
    )


@hookimpl
def pylsp_code_actions(
    config: Config,
    workspace: Workspace,
    document: Document,
    range: Dict,
    context: Dict,
) -> List[Dict]:
    """
    Provide code actions through ruff.

    Parameters
    ----------
    config : pylsp.config.config.Config
        Current workspace.
    workspace : pylsp.workspace.Workspace
        Current workspace.
    document : pylsp.workspace.Document
        Document to apply ruff on.
    range : Dict
        Range argument given by pylsp. Not used here.
    context : Dict
        CodeActionContext given as dict.

    Returns
    -------
    List of dicts containing the code actions.
    """
    log.debug(f"textDocument/codeAction: {document} {range} {context}")

    _context = converter.structure(context, CodeActionContext)
    diagnostics = _context.diagnostics
    diagnostics_with_fixes = [d for d in diagnostics if d.data]

    code_actions = []
    has_organize_imports = False

    for diagnostic in diagnostics_with_fixes:
        fix = converter.structure(diagnostic.data, RuffFix)

        if diagnostic.code == "I001":
            code_actions.append(
                create_organize_imports_code_action(document, diagnostic, fix)
            )
            has_organize_imports = True
        else:
            code_actions.extend(
                [
                    create_fix_code_action(document, diagnostic, fix),
                    create_disable_code_action(document, diagnostic),
                ]
            )

    checks = run_ruff_check(workspace, document)
    checks_with_fixes = [c for c in checks if c.fix]
    checks_organize_imports = [c for c in checks_with_fixes if c.code == "I001"]

    if not has_organize_imports and checks_organize_imports:
        check = checks_organize_imports[0]
        fix = check.fix  # type: ignore
        diagnostic = create_diagnostic(check)
        code_actions.append(
            create_organize_imports_code_action(document, diagnostic, fix),
        )

    if checks_with_fixes:
        code_actions.append(
            create_fix_all_code_action(workspace, document),
        )

    return converter.unstructure(code_actions)


def create_fix_code_action(
    document: Document,
    diagnostic: Diagnostic,
    fix: RuffFix,
) -> CodeAction:
    title = f"Ruff ({diagnostic.code}): {fix.message}"
    kind = CodeActionKind.QuickFix

    text_edits = create_text_edits(fix)
    workspace_edit = WorkspaceEdit(changes={document.uri: text_edits})
    return CodeAction(
        title=title,
        kind=kind,
        diagnostics=[diagnostic],
        edit=workspace_edit,
    )


def create_disable_code_action(
    document: Document,
    diagnostic: Diagnostic,
) -> CodeAction:
    title = f"Ruff ({diagnostic.code}): Disable for this line"
    kind = CodeActionKind.QuickFix

    line = document.lines[diagnostic.range.start.line].rstrip("\r\n")
    match = NOQA_REGEX.search(line)
    has_noqa = match is not None
    has_codes = match and match.group("codes") is not None
    # `foo  # noqa: OLD` -> `foo  # noqa: OLD,NEW`
    if has_noqa and has_codes:
        new_line = f"{line},{diagnostic.code}"
    # `foo  # noqa` -> `foo  # noqa: NEW`
    elif has_noqa:
        new_line = f"{line}: {diagnostic.code}"
    # `foo` -> `foo  # noqa: NEW`
    else:
        new_line = f"{line}  # noqa: {diagnostic.code}"

    range = Range(
        start=Position(line=diagnostic.range.start.line, character=0),
        end=Position(line=diagnostic.range.start.line, character=len(line)),
    )
    text_edit = TextEdit(range=range, new_text=new_line)
    workspace_edit = WorkspaceEdit(changes={document.uri: [text_edit]})
    return CodeAction(
        title=title,
        kind=kind,
        diagnostics=[diagnostic],
        edit=workspace_edit,
    )


def create_organize_imports_code_action(
    document: Document,
    diagnostic: Diagnostic,
    fix: RuffFix,
) -> CodeAction:
    title = f"Ruff: {fix.message}"
    kind = CodeActionKind.SourceOrganizeImports

    text_edits = create_text_edits(fix)
    workspace_edit = WorkspaceEdit(changes={document.uri: text_edits})
    return CodeAction(
        title=title,
        kind=kind,
        diagnostics=[diagnostic],
        edit=workspace_edit,
    )


def create_fix_all_code_action(
    workspace: Workspace,
    document: Document,
) -> CodeAction:
    title = "Ruff: Fix All"
    kind = CodeActionKind.SourceFixAll

    new_text = run_ruff_fix(workspace, document)
    range = Range(
        start=Position(line=0, character=0),
        end=Position(line=len(document.lines), character=0),
    )
    text_edit = TextEdit(range=range, new_text=new_text)
    workspace_edit = WorkspaceEdit(changes={document.uri: [text_edit]})
    return CodeAction(
        title=title,
        kind=kind,
        edit=workspace_edit,
    )


def create_text_edits(fix: RuffFix) -> List[TextEdit]:
    edits = []
    for edit in fix.edits:
        range = Range(
            start=Position(
                line=edit.location.row - 1,
                character=edit.location.column,  # yes, no -1
            ),
            end=Position(
                line=edit.end_location.row - 1,
                character=edit.end_location.column,  # yes, no -1
            ),
        )
        edits.append(TextEdit(range=range, new_text=edit.content))
    return edits


def run_ruff_check(workspace: Workspace, document: Document) -> List[RuffCheck]:
    result = run_ruff(workspace, document)
    try:
        result = json.loads(result)
    except json.JSONDecodeError:
        result = []  # type: ignore
    return converter.structure(result, List[RuffCheck])


def run_ruff_fix(workspace: Workspace, document: Document) -> str:
    result = run_ruff(workspace, document, fix=True)
    return result


def run_ruff(workspace: Workspace, document: Document, fix: bool = False) -> str:
    """
    Run ruff on the given document and the given arguments.

    Parameters
    ----------
    workspace : pyls.workspace.Workspace
        Workspace to run ruff in.
    document : pylsp.workspace.Document
        File to run ruff on.
    fix : bool
        Whether to run fix or no-fix.

    Returns
    -------
    String containing the result in json format.
    """
    config = load_config(workspace, document)
    executable = config.pop("executable")
    arguments = build_arguments(document, config, fix)

    log.debug(f"Calling {executable} with args: {arguments} on '{document.path}'")
    try:
        cmd = [executable]
        cmd.extend(arguments)
        p = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    except Exception:
        log.debug(f"Can't execute {executable}. Trying with '{sys.executable} -m ruff'")
        cmd = [sys.executable, "-m", "ruff"]
        cmd.extend(arguments)
        p = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    (stdout, stderr) = p.communicate(document.source.encode())

    if stderr:
        log.error(f"Error running ruff: {stderr.decode()}")

    return stdout.decode()


def build_arguments(document: Document, options: Dict, fix: bool = False) -> List[str]:
    """
    Build arguments for ruff.

    Parameters
    ----------
    document : pylsp.workspace.Document
        Document to apply ruff on.
    options : Dict
        Dict of arguments to pass to ruff.

    Returns
    -------
    List containing the arguments.
    """
    # Suppress update announcements
    args = ["--quiet"]
    # Use the json formatting for easier evaluation
    args.extend(["--format=json"])
    if fix:
        args.extend(["--fix"])
    else:
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


def load_config(workspace: Workspace, document: Document) -> Dict:
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
            "extend-ignore": _settings.get("extendIgnore", None),
            "line-length": None,
            "per-file-ignores": None,
            "select": None,
            "extend-select": _settings.get("extendSelect", None),
        }

    else:
        # Default values are given by ruff
        settings = {
            "config": _settings.get("config", None),
            "exclude": _settings.get("exclude", None),
            "executable": _settings.get("executable", "ruff"),
            "ignore": _settings.get("ignore", None),
            "extend-ignore": _settings.get("extendIgnore", None),
            "line-length": _settings.get("lineLength", None),
            "per-file-ignores": _settings.get("perFileIgnores", None),
            "select": _settings.get("select", None),
            "extend-select": _settings.get("extendSelect", None),
        }

    return settings
