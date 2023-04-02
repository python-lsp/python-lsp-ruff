# python-lsp-ruff

[![PyPi](https://img.shields.io/pypi/v/python-lsp-ruff.svg)](https://pypi.org/project/python-lsp-ruff)
[![Anaconda](https://anaconda.org/conda-forge/python-lsp-ruff/badges/version.svg)](https://anaconda.org/conda-forge/python-lsp-ruff)
[![Python](https://github.com/python-lsp/python-lsp-ruff/actions/workflows/python.yml/badge.svg)](https://github.com/python-lsp/python-lsp-ruff/actions/workflows/python.yml)

Linter plugin for pylsp based using ruff.
Formatting via `ruff`'s `--fix` is available since v1.3.0.

## Install

In the same `virtualenv` as `python-lsp-server`:

```shell
pip install python-lsp-ruff
```

There also exists an [AUR package](https://aur.archlinux.org/packages/python-lsp-ruff).

# Usage

This plugin will disable `flake8`, `pycodestyle`, `pyflakes` and `mccabe` by default.
When enabled, all linting diagnostics will be provided by `ruff`.

# Configuration

Configuration options can be passed to the python-language-server. If a `pyproject.toml`
file is present in the project, `python-lsp-ruff` will use these configuration options.
Note that any configuration options (except for `extendIgnore` and `extendSelect`, see
[this issue](https://github.com/python-lsp/python-lsp-ruff/issues/19)) passed to ruff via
`pylsp` are ignored if the project has a `pyproject.toml`.

The plugin follows [python-lsp-server's
configuration](https://github.com/python-lsp/python-lsp-server/#configuration). These are
the valid configuration keys:

 - `pylsp.plugins.ruff.enabled`: boolean to enable/disable the plugin. `true` by default.
 - `pylsp.plugins.ruff.config`: Path to optional `pyproject.toml` file.
 - `pylsp.plugins.ruff.exclude`: Exclude files from being checked by `ruff`.
 - `pylsp.plugins.ruff.executable`: Path to the `ruff` executable. Assumed to be in PATH by default.
 - `pylsp.plugins.ruff.ignore`: Error codes to ignore.
 - `pylsp.plugins.ruff.extendIgnore`: Same as ignore, but append to existing ignores.
 - `pylsp.plugins.ruff.lineLength`: Set the line-length for length checks.
 - `pylsp.plugins.ruff.perFileIgnores`: File-specific error codes to be ignored.
 - `pylsp.plugins.ruff.select`: List of error codes to enable.
 - `pylsp.plugins.ruff.extendSelect`: Same as select, but append to existing error codes.

For more information on the configuration visit [Ruff's homepage](https://beta.ruff.rs/docs/configuration/).
