# python-lsp-ruff

[![PyPi](https://img.shields.io/pypi/v/python-lsp-ruff.svg)](https://pypi.org/project/python-lsp-ruff)
[![Anaconda](https://anaconda.org/conda-forge/python-lsp-ruff/badges/version.svg)](https://anaconda.org/conda-forge/python-lsp-ruff)
[![Python](https://github.com/python-lsp/python-lsp-ruff/actions/workflows/python.yml/badge.svg)](https://github.com/python-lsp/python-lsp-ruff/actions/workflows/python.yml)

`python-lsp-ruff` is a plugin for `python-lsp-server` that adds linting, code action and formatting capabilities that are provided by [ruff](https://github.com/charliermarsh/ruff),
an extremely fast Python linter written in Rust.

## Install

In the same `virtualenv` as `python-lsp-server`:

```shell
pip install python-lsp-ruff
```

There also exists an [AUR package](https://aur.archlinux.org/packages/python-lsp-ruff).

### When using ruff before version 0.1.0
Ruff version `0.1.0` introduced API changes that are fixed in Python LSP Ruff `v1.6.0`. To continue with `ruff<0.1.0` please use `v1.5.3`, e.g. using `pip`:

```sh
pip install "ruff<0.1.0" "python-lsp-ruff==1.5.3"
```

## Usage

This plugin will disable `pycodestyle`, `pyflakes`, `mccabe` and `pyls_isort` by default, unless they are explicitly enabled in the client configuration.
When enabled, all linting diagnostics will be provided by `ruff`.
Sorting of the imports through `ruff` when formatting is enabled by default.
The list of code fixes can be changed via the `pylsp.plugins.ruff.format` option.

Any codes given in the `format` option will only be marked as `fixable` for ruff during the formatting operation, the user has to make sure that these codes are also in the list of codes that ruff checks!

This example configuration for `neovim` shows how to always sort imports when running `textDocument/formatting`:

```lua
lspconfig.pylsp.setup {
	settings = {
		pylsp = {
			plugins = {
				ruff = {
					enabled = true,
					extendSelect = { "I" },
				},
			}
		}
	}
}
```

## Configuration

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
 - `pylsp.plugins.ruff.executable`: Path to the `ruff` executable. Uses `os.executable -m "ruff"` by default.
 - `pylsp.plugins.ruff.ignore`: Error codes to ignore.
 - `pylsp.plugins.ruff.extendIgnore`: Same as ignore, but append to existing ignores.
 - `pylsp.plugins.ruff.lineLength`: Set the line-length for length checks.
 - `pylsp.plugins.ruff.perFileIgnores`: File-specific error codes to be ignored.
 - `pylsp.plugins.ruff.select`: List of error codes to enable.
 - `pylsp.plugins.ruff.extendSelect`: Same as select, but append to existing error codes.
 - `pylsp.plugins.ruff.format`: List of error codes to fix during formatting. The default is `["I"]`, any additional codes are appended to this list.
 - `pylsp.plugins.ruff.unsafeFixes`: boolean that enables/disables fixes that are marked "unsafe" by `ruff`. `false` by default.
 - `pylsp.plugins.ruff.severities`: Dictionary of custom severity levels for specific codes, see [below](#custom-severities).

For more information on the configuration visit [Ruff's homepage](https://beta.ruff.rs/docs/configuration/).

### Custom severities

By default, all diagnostics are marked as warning, except for `"E999"` and all error codes starting with `"F"`, which are displayed as errors.
This default can be changed through the `pylsp.plugins.ruff.severities` option, which takes the error code as a key and any of
`"E"`, `"W"`, `"I"` and `"H"` to be displayed as errors, warnings, information and hints, respectively.
For more information on the diagnostic severities please refer to
[the official LSP reference](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#diagnosticSeverity).

Note that `python-lsp-ruff` does *not* accept regex, and it will *not* check whether the error code exists. If the custom severity level is not displayed,
please check first that the error code is correct and that the given value is one of the possible keys from above.
