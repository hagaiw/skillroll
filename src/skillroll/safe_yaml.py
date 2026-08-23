"""Bounded metadata YAML parsing, isolated from the rest of the application."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml


class MetadataError(ValueError):
    """An author-facing error in a ``skillroll`` metadata fence."""


class _NoDuplicateSafeLoader(yaml.SafeLoader):
    pass


def _mapping(loader: _NoDuplicateSafeLoader, node: yaml.MappingNode) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=False)
        if not isinstance(key, str):
            raise MetadataError("metadata mapping keys must be text")
        if key in result:
            raise MetadataError(f"metadata repeats the '{key}' key")
        result[key] = loader.construct_object(value_node, deep=False)
    return result


_NoDuplicateSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping
)


def _measure(value: object, depth: int = 1) -> tuple[int, int]:
    if isinstance(value, Mapping):
        children = tuple(_measure(item, depth + 1) for item in value.values())
    elif isinstance(value, list):
        children = tuple(_measure(item, depth + 1) for item in value)
    else:
        children = ()
    return 1 + sum(item[0] for item in children), max(
        (depth, *(item[1] for item in children))
    )


def load_metadata(source: str) -> dict[str, Any]:
    """Load one small mapping without aliases, tags, or duplicate keys."""
    if len(source.encode("utf-8")) > 64 * 1024:
        raise MetadataError("metadata is larger than 64 KiB")
    try:
        nodes = list(yaml.compose_all(source, Loader=_NoDuplicateSafeLoader))
    except yaml.YAMLError as error:
        raise MetadataError("metadata is not valid safe YAML") from error
    if len(nodes) != 1 or nodes[0] is None:
        raise MetadataError("metadata must contain exactly one YAML document")
    node = nodes[0]
    if any(isinstance(item, yaml.AliasEvent) for item in yaml.parse(source)):
        raise MetadataError("metadata cannot use YAML aliases")
    if node.tag != yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG:
        raise MetadataError("metadata must be a mapping")
    try:
        value = yaml.load(source, Loader=_NoDuplicateSafeLoader)
    except (MetadataError, yaml.YAMLError) as error:
        raise MetadataError(str(error)) from error
    if not isinstance(value, dict):
        raise MetadataError("metadata must be a mapping")
    nodes_count, depth = _measure(value)
    if nodes_count > 1000 or depth > 20:
        raise MetadataError("metadata is too deeply nested or has too many values")
    return value
