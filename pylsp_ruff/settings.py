from dataclasses import dataclass, fields
from typing import Dict, List, Optional

import lsprotocol.converters
from cattrs.gen import make_dict_structure_fn, make_dict_unstructure_fn, override


@dataclass
class PluginSettings:
    enabled: bool = True
    executable: Optional[str] = None
    config: Optional[str] = None
    line_length: Optional[int] = None

    exclude: Optional[List[str]] = None

    select: Optional[List[str]] = None
    extend_select: Optional[List[str]] = None

    ignore: Optional[List[str]] = None
    extend_ignore: Optional[List[str]] = None
    per_file_ignores: Optional[Dict[str, List[str]]] = None

    format: Optional[List[str]] = None

    unsafe_fixes: bool = False

    severities: Optional[Dict[str, str]] = None


def to_camel_case(snake_str: str) -> str:
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def to_camel_case_unstructure(converter, klass):
    return make_dict_unstructure_fn(
        klass,
        converter,
        **{a.name: override(rename=to_camel_case(a.name)) for a in fields(klass)},
    )


def to_camel_case_structure(converter, klass):
    return make_dict_structure_fn(
        klass,
        converter,
        **{a.name: override(rename=to_camel_case(a.name)) for a in fields(klass)},
    )


def get_converter():
    converter = lsprotocol.converters.get_converter()
    unstructure_hook = to_camel_case_unstructure(converter, PluginSettings)
    structure_hook = to_camel_case_structure(converter, PluginSettings)
    converter.register_unstructure_hook(PluginSettings, unstructure_hook)
    converter.register_structure_hook(PluginSettings, structure_hook)
    return converter
