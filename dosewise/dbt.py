"""Read dbt artifacts, so a run can start from a real catalog instead of a hand-written file.

A dbt manifest lists every model and source with the columns declared in YAML and the lineage
between them, which is exactly what a change is compared against. `dbt docs generate` also writes a
catalog.json holding the columns and types the warehouse actually has; pass it and the column types
come from there, which is what makes a type change visible.

The asset id is the dbt unique_id (`model.jaffle_shop.stg_customers`), because it is stable across
runs and unique across packages. A table's own settings come from its `meta`:

    meta:
      owner: data-team          # an empty owner means nobody owns it, which raises uncertainty
      domain: finance
      sensitivity: 1.9
      queries_30d: 5200
      queries_prev_30d: 4100
      key_columns: [order_id]
      standing_issues: [nullable key]
"""
from __future__ import annotations

RESOURCE_TYPES = ("model", "source", "snapshot")
META_NUMBERS = ("sensitivity", "queries_30d", "queries_prev_30d")


def _node_map(manifest, section):
    part = manifest.get(section)
    if part is None:
        return {}
    if not isinstance(part, dict):
        raise ValueError(f"manifest {section} must be a map of node id to node")
    return part


def nodes_of(manifest):
    """The models, sources and snapshots in a manifest, by unique_id."""
    if not isinstance(manifest, dict):
        raise ValueError("a dbt manifest must be a JSON object")
    if not isinstance(manifest.get("nodes"), dict):
        raise ValueError('this is not a dbt manifest: it has no "nodes" map (run dbt parse or dbt build first)')
    found = {}
    for section in ("sources", "nodes"):
        for uid, node in _node_map(manifest, section).items():
            if isinstance(node, dict) and node.get("resource_type") in RESOURCE_TYPES:
                found[uid] = node
    if not found:
        raise ValueError("the manifest has no models, sources or snapshots to score")
    return found


def measured_columns(catalog):
    """The columns and types from `dbt docs generate`, by unique_id."""
    if catalog is None:
        return {}
    if not isinstance(catalog, dict) or not any(isinstance(catalog.get(s), dict) for s in ("nodes", "sources")):
        raise ValueError("that is not a dbt catalog.json: it has no nodes or sources map (make one with dbt docs generate)")
    measured = {}
    for section in ("sources", "nodes"):
        for uid, node in (catalog.get(section) or {}).items():
            if isinstance(node, dict) and isinstance(node.get("columns"), dict):
                measured[uid] = node["columns"]
    return measured


def type_of(entry):
    """The type a declared or measured column carries, or None when nobody knows it."""
    if isinstance(entry, str):
        return entry or None
    if isinstance(entry, dict):
        for key in ("type", "data_type"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def columns_of(node, measured=None):
    """Column name to type: what dbt measured, with the YAML's declared type as the fallback.

    Types are lowercased because a warehouse reports them in its own case (Snowflake gives
    INTEGER, Postgres integer) and a change of case is not a change of type. A column nobody
    described is kept as "unknown" rather than dropped, so adding it later still reads as a change
    instead of appearing out of nowhere.
    """
    declared = node.get("columns") or {}
    if not isinstance(declared, dict):
        raise ValueError(f"{node.get('unique_id', '?')}: columns must be a map of column name to its description")
    measured = measured if isinstance(measured, dict) else {}
    names = list(measured) + [n for n in declared if n not in measured]
    return {str(n): (type_of(measured.get(n)) or type_of(declared.get(n)) or "unknown").lower() for n in names}


def meta_of(node):
    """`meta` from the config block and from the node itself, with the node winning."""
    meta = {}
    for source in ((node.get("config") or {}).get("meta"), node.get("meta")):
        if isinstance(source, dict):
            meta.update(source)
    return meta


def tags_of(node):
    tags = set()
    for source in (node.get("tags"), (node.get("config") or {}).get("tags")):
        if isinstance(source, list):
            tags.update(t for t in source if isinstance(t, str))
    return sorted(tags)


def asset_of(uid, node, measured=None):
    """One dosewise asset, with the settings dbt already knows about."""
    meta = meta_of(node)
    asset = {"id": uid, "schema": columns_of(node, measured)}
    tags = tags_of(node)
    if tags:
        asset["tags"] = tags
    domain = meta.get("domain") or node.get("group")
    if isinstance(domain, str) and domain:
        asset["domain"] = domain
    if "owner" in meta:
        owner = meta["owner"]
        if owner is not None and not isinstance(owner, str):
            raise ValueError(f"{uid}: meta.owner must be text or empty")
        asset["owner"] = owner or ""  # an empty owner is not the same as an untracked one
    for key in META_NUMBERS:
        if key not in meta:
            continue
        value = meta[key]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{uid}: meta.{key} must be a number, not {type(value).__name__}")
        if key == "sensitivity":
            asset[key] = value
        else:
            asset.setdefault("usage", {})[key] = value
    for key in ("key_columns", "standing_issues"):
        value = meta.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{uid}: meta.{key} must be a list of strings")
        if value:
            asset[key] = value
    return asset


def edges_of(nodes):
    """Lineage from depends_on, keeping only the steps between tables this catalog holds."""
    edges = set()
    for uid, node in nodes.items():
        depends = (node.get("depends_on") or {}).get("nodes") or []
        if not isinstance(depends, list):
            continue
        for parent in depends:
            if parent in nodes and parent != uid:
                edges.add((parent, uid))
    return [{"from": a, "to": b} for a, b in sorted(edges)]


def catalog_from_manifest(manifest, catalog=None):
    """A dosewise catalog built from a dbt manifest, optionally with types from dbt's own catalog."""
    nodes = nodes_of(manifest)
    measured = measured_columns(catalog)
    return {"assets": [asset_of(uid, node, measured.get(uid)) for uid, node in sorted(nodes.items())],
            "edges": edges_of(nodes)}
