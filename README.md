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

Any codes given in the `format` option will only be marked as `fixable` for ruff during the formatting operation, the user has to make sure that these codes are also in the list of codes that ruff checks!


## Configuration

Configuration options can be passed to the python-language-server. If a `pyproject.toml`
file is present in the project, `python-lsp-ruff` will ignore specific options (see below).

The plugin follows [python-lsp-server's configuration](https://github.com/python-lsp/python-lsp-server/#configuration).
This example configuration using for `neovim` shows the possible optionsL

```lua
pylsp = {
  plugins = {
    ruff = {
      enabled = true,  -- Enable the plugin
      executable = "<path-to-ruff-bin>",  -- Custom path to ruff
      path = "<path_to_custom_ruff_toml>",  -- Custom config for ruff to use
      extendSelect = { "I" },  -- Rules that are additionally used by ruff
      extendIgnore = { "C90" },  -- Rules that are additionally ignored by ruff
      format = { "I" },  -- Rules that are marked as fixable by ruff that should be fixed when running textDocument/formatting
      severities = { ["D212"] = "I" },  -- Optional table of rules where a custom severity is desired
      unsafeFixes = false,  -- Whether or not to offer unsafe fixes as code actions. Ignored with the "Fix All" action

      -- Rules that are ignored when a pyproject.toml or ruff.toml is present:
      lineLength = 88,  -- Line length to pass to ruff checking and formatting
      exclude = { "__about__.py" },  -- Files to be excluded by ruff checking
      select = { "F" },  -- Rules to be enabled by ruff
      ignore = { "D210" },  -- Rules to be ignored by ruff
      perFileIgnores = { ["__init__.py"] = "CPY001" },  -- Rules that should be ignored for specific files
      preview = false,  -- Whether to enable the preview style linting and formatting.
      targetVersion = "py310",  -- The minimum python version to target (applies for both linting and formatting).
    },
  }
}
```

For more information on the configuration visit [Ruff's homepage](https://beta.ruff.rs/docs/configuration/).

### Custom severities

By default, all diagnostics are marked as warning, except for `"E999"` and all error codes starting with `"F"`, which are displayed as errors.
This default can be changed through the `pylsp.plugins.ruff.severities` option, which takes the error code as a key and any of
`"E"`, `"W"`, `"I"` and `"H"` to be displayed as errors, warnings, information and hints, respectively.
For more information on the diagnostic severities please refer to
[the official LSP reference](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#diagnosticSeverity).

With `v2.0.0` it is also possible to use patterns to match codes. Rules match if the error code starts with the given pattern. If multiple patterns match the error code, `python-lsp-ruff` chooses the one with the most amount of matching characters.


## Code formatting

With `python-lsp-ruff>1.6.0` formatting is done using [ruffs own formatter](https://docs.astral.sh/ruff/formatter/).
In addition, rules that should be fixed during the `textDocument/formatting` request can be added with the `format` option.

Coming from previous versions the only change is that `isort` rules are **not** applied by default.
To enable sorting of imports using ruff's isort functionality, add `"I"` to the list of `format` rules. 


## Code actions

`python-lsp-ruff` supports code actions as given by possible fixes by `ruff`. `python-lsp-ruff` also supports [unsafe fixes](https://docs.astral.sh/ruff/linter/#fix-safety).
Fixes considered unsafe by `ruff` are marked `(unsafe)` in the code action.
The `Fix all` code action *only* consideres safe fixes.
