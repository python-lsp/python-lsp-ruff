import json
import logging
import re
import sys
from pathlib import PurePath
from subprocess import PIPE, Popen
from typing import Dict, Generator, List, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

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
from pylsp_ruff.settings import PluginSettings, get_converter

log = logging.getLogger(__name__)
logging.getLogger("blib2to3").setLevel(logging.ERROR)
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

DIAGNOSTIC_SEVERITIES = {
    "E": DiagnosticSeverity.Error,
    "W": DiagnosticSeverity.Warning,
    "I": DiagnosticSeverity.Information,
    "H": DiagnosticSeverity.Hint,
}


@hookimpl
def pylsp_settings():
    log.debug("Initializing pylsp_ruff")
    # This plugin disables some enabled-by-default plugins that duplicate Ruff
    # functionality
    settings = {
        "plugins": {
            "ruff": PluginSettings(),
            "pyflakes": {"enabled": False},
            "mccabe": {"enabled": False},
            "pycodestyle": {"enabled": False},
            "pyls_isort": {"enabled": False},
        }
    }
    return converter.unstructure(settings)


@hookimpl(hookwrapper=True)
def pylsp_format_document(workspace: Workspace, document: Document) -> Generator:
    """
    Provide formatting through ruff.

    Parameters
    ----------
    workspace : pylsp.workspace.Workspace
        Current workspace.
    document : pylsp.workspace.Document
        Document to apply ruff on.
    """
    log.debug(f"textDocument/formatting: {document}")
    outcome = yield
    result = outcome.get_result()
    if result:
        source = result[0]["newText"]
    else:
        source = document.source

    settings = load_settings(workspace=workspace, document_path=document.path)
    new_text = run_ruff_format(
        settings=settings, document_path=document.path, document_source=source
    )

    # Avoid applying empty text edit
    if new_text == source:
        return

    range = Range(
        start=Position(line=0, character=0),
        end=Position(line=len(document.lines), character=0),
    )
    text_edit = TextEdit(range=range, new_text=new_text)

    outcome.force_result(converter.unstructure([text_edit]))


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
    settings = load_settings(workspace, document.path)
    checks = run_ruff_check(document=document, settings=settings)
    diagnostics = [create_diagnostic(check=c, settings=settings) for c in checks]
    return converter.unstructure(diagnostics)


def create_diagnostic(check: RuffCheck, settings: PluginSettings) -> Diagnostic:
    """
    Create a LSP diagnostic based on the given RuffCheck object.

    Parameters
    ----------
    check : RuffCheck
        RuffCheck object to convert.
    settings : PluginSettings
        Current settings.

    Returns
    -------
    Diagnostic
    """
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

    # Override severity with custom severity if possible, use default otherwise
    if settings.severities is not None:
        custom_sev = settings.severities.get(check.code, None)
        if custom_sev is not None:
            severity = DIAGNOSTIC_SEVERITIES.get(custom_sev, severity)

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

    code_actions = []
    has_organize_imports = False

    settings = load_settings(workspace=workspace, document_path=document.path)

    for diagnostic in diagnostics:
        code_actions.append(
            create_disable_code_action(document=document, diagnostic=diagnostic)
        )

        if diagnostic.data:  # Has fix
            fix = converter.structure(diagnostic.data, RuffFix)

            # Ignore fix if marked as unsafe and unsafe_fixes are disabled
            if fix.applicability != "safe" and not settings.unsafe_fixes:
                continue

            if diagnostic.code == "I001":
                code_actions.append(
                    create_organize_imports_code_action(
                        document=document, diagnostic=diagnostic, fix=fix
                    )
                )
                has_organize_imports = True
            else:
                code_actions.append(
                    create_fix_code_action(
                        document=document, diagnostic=diagnostic, fix=fix
                    ),
                )

    checks = run_ruff_check(document=document, settings=settings)
    checks_with_fixes = [c for c in checks if c.fix]
    checks_organize_imports = [c for c in checks_with_fixes if c.code == "I001"]

    if not has_organize_imports and checks_organize_imports:
        check = checks_organize_imports[0]
        fix = check.fix  # type: ignore
        diagnostic = create_diagnostic(check=check, settings=settings)
        code_actions.extend(
            [
                create_organize_imports_code_action(
                    document=document, diagnostic=diagnostic, fix=fix
                ),
                create_disable_code_action(document=document, diagnostic=diagnostic),
            ]
        )

    if checks_with_fixes:
        code_actions.append(
            create_fix_all_code_action(document=document, settings=settings),
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
    document: Document,
    settings: PluginSettings,
) -> CodeAction:
    title = "Ruff: Fix All"
    kind = CodeActionKind.SourceFixAll

    new_text = run_ruff_fix(document=document, settings=settings)
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
                character=edit.location.column - 1,
            ),
            end=Position(
                line=edit.end_location.row - 1,
                character=edit.end_location.column - 1,
            ),
        )
        edits.append(TextEdit(range=range, new_text=edit.content))
    return edits


def run_ruff_check(document: Document, settings: PluginSettings) -> List[RuffCheck]:
    result = run_ruff(
        document_path=document.path,
        document_source=document.source,
        settings=settings,
    )
    try:
        result = json.loads(result)
    except json.JSONDecodeError:
        result = []  # type: ignore
    return converter.structure(result, List[RuffCheck])


def run_ruff_fix(document: Document, settings: PluginSettings) -> str:
    result = run_ruff(
        document_path=document.path,
        document_source=document.source,
        fix=True,
        settings=settings,
    )
    return result


def run_ruff_format(
    settings: PluginSettings,
    document_path: str,
    document_source: str,
) -> str:
    fixable_codes = ["I"]
    if settings.format:
        fixable_codes.extend(settings.format)
    extra_arguments = [
        f"--fixable={','.join(fixable_codes)}",
    ]
    result = run_ruff(
        settings=settings,
        document_path=document_path,
        document_source=document_source,
        fix=True,
        extra_arguments=extra_arguments,
    )
    return result


def run_ruff(
    settings: PluginSettings,
    document_path: str,
    document_source: str,
    fix: bool = False,
    extra_arguments: Optional[List[str]] = None,
) -> str:
    """
    Run ruff on the given document and the given arguments.

    Parameters
    ----------
    settings : PluginSettings
        Settings to use.
    document_path : str
        Path to file to run ruff on.
    document_source : str
        Document source or to apply ruff on.
        Needed when the source differs from the file source, e.g. during formatting.
    fix : bool
        Whether to run fix or no-fix.
    extra_arguments : List[str]
        Extra arguments to pass to ruff.

    Returns
    -------
    String containing the result in json format.
    """
    executable = settings.executable
    arguments = build_arguments(document_path, settings, fix, extra_arguments)

    if executable is not None:
        log.debug(f"Calling {executable} with args: {arguments} on '{document_path}'")
        try:
            cmd = [executable]
            cmd.extend(arguments)
            p = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        except Exception:
            log.error(f"Can't execute ruff with given executable '{executable}'.")
    else:
        cmd = [sys.executable, "-m", "ruff"]
        cmd.extend(arguments)
        p = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    (stdout, stderr) = p.communicate(document_source.encode())

    if p.returncode != 0:
        log.error(f"Error running ruff: {stderr.decode()}")

    return stdout.decode()


def build_arguments(
    document_path: str,
    settings: PluginSettings,
    fix: bool = False,
    extra_arguments: Optional[List[str]] = None,
) -> List[str]:
    """
    Build arguments for ruff.

    Parameters
    ----------
    document : pylsp.workspace.Document
        Document to apply ruff on.
    settings : PluginSettings
        Settings to use for arguments to pass to ruff.
    fix : bool
        Whether to execute with --fix.
    extra_arguments : List[str]
        Extra arguments to pass to ruff.

    Returns
    -------
    List containing the arguments.
    """
    args = []
    # Suppress update announcements
    args.append("--quiet")
    # Suppress exit 1 when violations were found
    args.append("--exit-zero")
    # Use the json formatting for easier evaluation
    args.append("--output-format=json")
    if fix:
        args.append("--fix")
    else:
        # Do not attempt to fix -> returns file instead of diagnostics
        args.append("--no-fix")
    # Always force excludes
    args.append("--force-exclude")
    # Pass filename to ruff for per-file-ignores, catch unsaved
    if document_path != "":
        args.append(f"--stdin-filename={document_path}")

    if settings.config:
        args.append(f"--config={settings.config}")

    if settings.line_length:
        args.append(f"--line-length={settings.line_length}")

    if settings.unsafe_fixes:
        args.append("--unsafe-fixes")

    if settings.exclude:
        args.append(f"--exclude={','.join(settings.exclude)}")

    if settings.select:
        args.append(f"--select={','.join(settings.select)}")

    if settings.extend_select:
        args.append(f"--extend-select={','.join(settings.extend_select)}")

    if settings.ignore:
        args.append(f"--ignore={','.join(settings.ignore)}")

    if settings.extend_ignore:
        args.append(f"--extend-ignore={','.join(settings.extend_ignore)}")

    if settings.per_file_ignores:
        for path, errors in settings.per_file_ignores.items():
            if not PurePath(document_path).match(path):
                continue
            args.append(f"--ignore={','.join(errors)}")

    if extra_arguments:
        args.extend(extra_arguments)

    args.extend(["--", "-"])

    return args


def load_settings(workspace: Workspace, document_path: str) -> PluginSettings:
    """
    Load settings from pyproject.toml file in the project path.

    Parameters
    ----------
    workspace : pylsp.workspace.Workspace
        Current workspace.
    document_path : str
        Path to the document to apply ruff on.

    Returns
    -------
    PluginSettings read via lsp.
    """
    config = workspace._config
    _plugin_settings = config.plugin_settings("ruff", document_path=document_path)
    plugin_settings = converter.structure(_plugin_settings, PluginSettings)

    pyproject_file = find_parents(
        workspace.root_path, document_path, ["pyproject.toml"]
    )

    config_in_pyproject = False
    if pyproject_file:
        try:
            with open(pyproject_file[0], "rb") as f:
                toml_dict = tomllib.load(f)
                if "tool" in toml_dict and "ruff" in toml_dict["tool"]:
                    config_in_pyproject = True
        except tomllib.TOMLDecodeError:
            log.warn("Error while parsing toml file, ignoring config.")

    ruff_toml = find_parents(
        workspace.root_path, document_path, ["ruff.toml", ".ruff.toml"]
    )

    # Check if pyproject is present, ignore user settings if toml exists
    if config_in_pyproject or ruff_toml:
        log.debug("Found existing configuration for ruff, skipping pylsp config.")
        # Leave config to pyproject.toml
        return PluginSettings(
            enabled=plugin_settings.enabled,
            executable=plugin_settings.executable,
            unsafe_fixes=plugin_settings.unsafe_fixes,
            extend_ignore=plugin_settings.extend_ignore,
            extend_select=plugin_settings.extend_select,
            format=plugin_settings.format,
            severities=plugin_settings.severities,
        )

    return plugin_settings
