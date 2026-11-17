"""The scoring engine. Plain arithmetic, no model, same input gives the same output.

Risk = Hazard x Exposure x Receptor sensitivity x Uncertainty
"""
from __future__ import annotations

import fnmatch
import json
import math
from collections import deque
from dataclasses import dataclass, field

DEFAULT_CONFIG = {
    "max_hops": 4,
    "hop_decay": 0.5,
    "hazard_by_change": {"column_removed": 1.0, "type_changed": 0.8, "column_added": 0.2, "table_removed": 1.0, "type_widened": 0.2},
    "receptor_by_tag": {"pii": 2.0, "finance": 1.8, "executive": 1.5, "dashboard": 1.3},
    "receptor_by_domain": {"finance": 1.8, "customer": 1.5},
    "uncertainty_unknown_column_lineage": 0.5,
    "uncertainty_unknown_usage": 0.5,
    # The action line is pinned to a written reference case, not fitted to the data:
    # one quarter of the columns removed, 1,000 queries a month one hop away,
    # a PII consumer, and nothing missing from the evidence.
    "reference_case": {"hazard": 1.0, "dose": 0.25, "queries": 1000, "receptor": 2.0, "uncertainty": 1.0},
    "monitor_fraction": 0.25,
    "exposure_floor": 0.3,
    "growth_ratio": 1.5,
    "ignore": [],  # table id patterns to skip, e.g. "scratch.*"
    # old type, new type: changes that keep every existing value readable
    "safe_type_changes": [["int", "bigint"], ["float", "double"], ["varchar", "text"], ["string", "text"]],
    "key_column_multiplier": 1.5,
    "uncertainty_no_owner": 0.5,
}


@dataclass
class Finding:
    asset: str
    change: str
    columns: list
    hazard: float
    dose: float
    exposure: float
    receptor: float
    uncertainty: float
    risk: float
    band: str
    naive_downstream: int
    naive_rank: int = 0
    rank: int = 0
    reasons: list = field(default_factory=list)
    domain: str = ""
    consumers: list = field(default_factory=list)  # [asset, hops away, queries a month or null]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def diff_schemas(baseline: dict, assets: dict, safe=()):
    """Real changes only: what is different from the saved baseline."""
    out = []
    for aid, old in baseline.items():
        if aid not in assets:
            out.append((aid, "table_removed", sorted(old), len(old)))
    for aid, asset in assets.items():
        old, new = baseline.get(aid), asset["schema"]
        if old is None:
            continue
        removed = sorted(set(old) - set(new))
        added = sorted(set(new) - set(old))
        retyped = sorted(c for c in set(old) & set(new) if old[c] != new[c])
        wide = [c for c in retyped if [old[c], new[c]] in [list(x) for x in safe]]
        retyped = [c for c in retyped if c not in wide]
        for kind, cols in (("column_removed", removed), ("type_changed", retyped), ("type_widened", wide), ("column_added", added)):
            if cols:
                out.append((aid, kind, cols, len(old)))
    return out


def child_map(edges):
    children = {}
    for e in edges:
        children.setdefault(e["from"], []).append(e)
    return children


def downstream(children, start, max_hops, touched=None):
    """Breadth-first walk with the shortest hop count to each consumer.

    `touched` is the set of columns that changed. None means every column counts (a removed table,
    or a standing issue that is not about one column), so column-level lineage does not filter.
    """
    seen, queue, unknown_edges = {start: 0}, deque([(start, 0)]), 0
    touched = None if touched is None else set(touched)
    while queue:
        node, hop = queue.popleft()
        if hop >= max_hops:
            continue
        for e in children.get(node, []):
            cols = e.get("columns")
            if hop == 0 and touched is not None and cols is not None and not set(cols) & touched:
                continue  # column-level lineage says this consumer never reads the changed columns
            if e["to"] in seen:
                continue
            seen[e["to"]] = hop + 1
            if hop == 0 and cols is None:
                unknown_edges += 1
            queue.append((e["to"], hop + 1))
    seen.pop(start)
    return seen, unknown_edges


def band(risk, cfg):
    ref = reference_score(cfg)
    if risk >= ref:
        return "Act"
    if risk >= ref * cfg["monitor_fraction"]:
        return "Monitor"
    return "No Action"


def reference_score(cfg):
    r = cfg["reference_case"]
    return r["hazard"] * r["dose"] * math.log10(1 + r["queries"] * cfg["hop_decay"] ** 0) * r["receptor"] * r["uncertainty"]


def queries(asset, key="queries_30d"):
    """What a table is asked for, or None when nothing was measured. `usage: null` means unmeasured."""
    return (asset.get("usage") or {}).get(key)


def receptor_weight(asset, cfg):
    if "sensitivity" in asset:
        return float(asset["sensitivity"])  # you know better than the tags
    w = 1.0
    for t in asset.get("tags", []):
        w = max(w, cfg["receptor_by_tag"].get(t, 1.0))
    w = max(w, cfg["receptor_by_domain"].get(asset.get("domain"), 1.0))
    if asset.get("platform") in ("looker", "tableau", "powerbi"):
        w = max(w, cfg["receptor_by_tag"].get("dashboard", 1.0))
    return w


def merge_config(cfg):
    """Your settings on top of the defaults. A table of weights is merged, so naming one tag keeps the rest."""
    out = dict(DEFAULT_CONFIG)
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


NUMBER_SETTINGS = ("hop_decay", "exposure_floor", "growth_ratio", "monitor_fraction",
                   "key_column_multiplier", "uncertainty_unknown_column_lineage", "uncertainty_unknown_usage",
                   "uncertainty_no_owner")
WEIGHT_TABLES = ("hazard_by_change", "receptor_by_tag", "receptor_by_domain")
REFERENCE_KEYS = ("hazard", "dose", "queries", "receptor", "uncertainty")


def is_number(value):
    """A real number. True and False are ints in Python, and a boolean is not a weight."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_config(cfg):
    """Fail early and plainly on a typo, instead of silently ignoring it or dying with a traceback."""
    unknown = set(cfg) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    merged = merge_config(cfg)
    if "max_hops" in cfg:
        max_hops = cfg["max_hops"]
        if not is_number(max_hops) or max_hops < 1 or max_hops != int(max_hops):
            raise ValueError("max_hops must be a whole number of at least 1")
    for key in NUMBER_SETTINGS:
        if key in cfg and not is_number(cfg[key]):
            raise ValueError(f"{key} must be a number, not {type(cfg[key]).__name__}")
    for key in WEIGHT_TABLES:
        if key not in cfg:
            continue
        if not isinstance(cfg[key], dict):
            raise ValueError(f"{key} must be a map of name to weight, not {type(cfg[key]).__name__}")
        for name, weight in cfg[key].items():
            if not is_number(weight):
                raise ValueError(f"{key}.{name} must be a number, not {type(weight).__name__}")
    # The reference case merges like every other table, so naming one of its numbers keeps the rest.
    case = merged["reference_case"]
    if not isinstance(case, dict):
        raise ValueError(f"reference_case must be a map of {', '.join(REFERENCE_KEYS)}")
    for key in REFERENCE_KEYS:
        if not is_number(case[key]):
            raise ValueError(f"reference_case.{key} must be a number, not {type(case[key]).__name__}")
    if "ignore" in cfg:
        if not isinstance(cfg["ignore"], list) or not all(isinstance(p, str) for p in cfg["ignore"]):
            raise ValueError('ignore must be a list of table patterns, as in ["scratch.*"]')
    for pair in cfg.get("safe_type_changes", []):
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(t, str) for t in pair)):
            raise ValueError("safe_type_changes must be a list of [old type, new type] pairs")
    if not 0 < cfg.get("hop_decay", 0.5) <= 1:
        raise ValueError("hop_decay must be above 0 and at most 1")
    if not 0 < cfg.get("monitor_fraction", 0.25) <= 1:
        raise ValueError("monitor_fraction must be above 0 and at most 1, or the Monitor band would be empty")
    if cfg.get("exposure_floor", 0.3) < 0:
        raise ValueError("exposure_floor cannot be negative")
    if cfg.get("growth_ratio", 1.5) < 1:
        raise ValueError("growth_ratio must be at least 1, or every ordinary consumer counts as rising")
    if cfg.get("key_column_multiplier", 1.0) <= 0:
        raise ValueError("key_column_multiplier must be above 0")
    for key in ("uncertainty_unknown_column_lineage", "uncertainty_unknown_usage", "uncertainty_no_owner"):
        if cfg.get(key, 0) < 0:
            raise ValueError(f"{key} cannot be negative")
    if reference_score(merged) <= 0:
        raise ValueError("the reference case must score above zero, or everything would need action")


def check_catalog(catalog):
    """Name what is wrong with the input, rather than failing on the first score it computes."""
    if not isinstance(catalog, dict):
        raise ValueError("the catalog must be a JSON object with assets and edges")
    if not isinstance(catalog.get("assets"), list):
        raise ValueError('the catalog needs an "assets" list')
    edges = catalog.get("edges", [])
    if not isinstance(edges, list):
        raise ValueError("edges must be a list of from/to steps")
    for a in catalog["assets"]:
        if not isinstance(a, dict):
            raise ValueError("every asset must be a JSON object with an id and a schema")
        if not isinstance(a.get("id"), str) or not a["id"]:
            raise ValueError("every asset needs a string id")
        aid = a["id"]
        if not isinstance(a.get("schema"), dict):
            raise ValueError(f"{aid}: schema must be a map of column name to type")
        usage = a.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise ValueError(f'{aid}: usage must be a map such as {{"queries_30d": 20}}, or null when nothing is measured')
        for key in ("queries_30d", "queries_prev_30d"):
            q = (usage or {}).get(key)
            if q is None:
                continue
            if not is_number(q):
                raise ValueError(f"{aid}: {key} must be a number, not {type(q).__name__}")
            if q < 0:
                raise ValueError(f"{aid}: {key} cannot be negative")
        for key in ("tags", "key_columns", "standing_issues"):
            value = a.get(key)
            if value is not None and (not isinstance(value, list) or not all(isinstance(x, str) for x in value)):
                raise ValueError(f"{aid}: {key} must be a list of strings")
        if "sensitivity" in a and not is_number(a["sensitivity"]):
            raise ValueError(f"{aid}: sensitivity must be a number, not {type(a['sensitivity']).__name__}")
    for e in edges:
        if not isinstance(e, dict) or not isinstance(e.get("from"), str) or not isinstance(e.get("to"), str):
            raise ValueError('every edge needs a "from" and a "to" table id')
        cols = e.get("columns")
        if cols is not None and (not isinstance(cols, list) or not all(isinstance(c, str) for c in cols)):
            raise ValueError(f"edge {e['from']} to {e['to']}: columns must be a list of column names")


def score(catalog, baseline, cfg=None):
    check_config(cfg or {})
    cfg = merge_config(cfg)
    check_catalog(catalog)
    ids = [a["id"] for a in catalog["assets"]]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"the same asset id appears more than once: {', '.join(dupes)}")
    assets = {a["id"]: a for a in catalog["assets"]}
    edges = catalog.get("edges", [])
    children = child_map(edges)
    findings = []
    def skipped(aid):
        return any(fnmatch.fnmatch(aid, pat) for pat in cfg["ignore"])

    for aid, kind, cols, ncols in diff_schemas(baseline, assets, cfg["safe_type_changes"]):
        if skipped(aid):
            continue
        # A removed table reaches every consumer, whatever columns its edges name.
        seen, unknown_edges = downstream(children, aid, cfg["max_hops"], None if kind == "table_removed" else cols)
        if ncols:
            dose = len(cols) / ncols
            reasons = [f"{kind.replace('_', ' ')} on {len(cols)} of {ncols} columns ({dose:.0%})"]
        else:
            # The saved schema had no columns for this table, so there is no share to take:
            # whatever is known about the table changed.
            dose = 1.0
            reasons = [f"{kind.replace('_', ' ')} on a table with no saved columns, so it counts as the whole table"]
        hazard = cfg["hazard_by_change"][kind]
        keys = set(assets.get(aid, {}).get("key_columns", [])) & set(cols)
        if keys:
            hazard *= cfg["key_column_multiplier"]
        if keys:
            reasons.append(f"touches key column(s) {sorted(keys)}, which makes it worse")
        if kind == "column_removed" and aid in assets:
            fresh = set(assets[aid]["schema"]) - set(baseline[aid])
            if len(fresh) >= len(cols):
                reasons.append(f"{len(fresh)} column(s) were added in the same change, so this may be a rename")
        weighted, unmeasured, receptor, rising = 0.0, 0, 1.0, 0
        for node, hop in seen.items():
            q = queries(assets.get(node, {}))
            if q is None:
                unmeasured += 1
            else:
                prev = queries(assets.get(node, {}), "queries_prev_30d")
                if prev and q >= prev * cfg["growth_ratio"]:
                    rising += 1
                weighted += q * cfg["hop_decay"] ** (hop - 1)
            if node in assets:
                receptor = max(receptor, receptor_weight(assets[node], cfg))
        # Unmeasured is not unused: if anything is downstream, exposure never drops to zero.
        exposure = max(math.log10(1 + weighted), cfg["exposure_floor"]) if seen else 0.0
        unc = 1.0
        if seen:
            unc += cfg["uncertainty_unknown_usage"] * unmeasured / len(seen)
            unc += cfg["uncertainty_unknown_column_lineage"] * unknown_edges / max(1, len(children.get(aid, [])))
        a = assets.get(aid, {})
        if "owner" in a and not a["owner"]:
            unc += cfg["uncertainty_no_owner"]
            reasons.append("nobody owns this table, so nobody is accountable: missing evidence raises uncertainty")
        if not seen:
            reasons.append("nothing downstream reads the changed columns")
        else:
            reasons.append(f"{len(seen)} downstream, {weighted:.0f} weighted queries a month after distance decay")
        if rising:
            reasons.append(f"{rising} consumer(s) are queried at least {cfg['growth_ratio']}x more than the month before")
        if unmeasured:
            reasons.append(f"{unmeasured} consumer(s) have no usage data, which raises uncertainty rather than lowering risk")
        if receptor > 1:
            reasons.append(f"most sensitive consumer weighs {receptor}x")
        risk = hazard * dose * exposure * receptor * unc
        b = band(risk, cfg)
        ref = reference_score(cfg)
        if b != "Act" and risk > 0:
            target, name = (ref, "Act") if b == "Monitor" else (ref * cfg["monitor_fraction"], "Monitor")
            reasons.append(f"would move to {name} if the risk were {target / risk:.1f}x higher")
        if unc > 1:
            reasons.append("filling in the missing evidence could move this up or down")
        findings.append(Finding(aid, kind, cols, hazard, round(dose, 4), round(exposure, 3), receptor,
                                round(unc, 3), round(risk, 2), b, len(seen), reasons=reasons, domain=assets.get(aid, {}).get("domain") or "",
                                consumers=[[n, h, queries(assets.get(n, {}))] for n, h in sorted(seen.items(), key=lambda x: (x[1], x[0]))]))
    # Standing issues (problems that were already there and have not changed) score zero.
    for a in catalog["assets"]:
        if skipped(a["id"]):
            continue
        for issue in a.get("standing_issues", []):
            seen, _ = downstream(children, a["id"], cfg["max_hops"])
            findings.append(Finding(a["id"], "standing:" + issue, [], 0, 0, 0, 1.0, 1.0, 0.0, "No Action",
                                    len(seen), reasons=["unchanged since the baseline, so nothing new has happened"]))
    for i, f in enumerate(sorted(findings, key=lambda f: (-f.naive_downstream, f.asset, f.change)), 1):
        f.naive_rank = i
    for i, f in enumerate(sorted(findings, key=lambda f: (-f.risk, f.asset, f.change)), 1):
        f.rank = i
    return sorted(findings, key=lambda f: f.rank), reference_score(cfg)


def stability(catalog, baseline, cfg=None, factor=1.5):
    """How often does each finding keep its band when one weight at a time is made 1.5x bigger or smaller?

    The weights are starting guesses, so a verdict that flips when one is nudged is a verdict to trust less.
    """
    import copy
    cfg = merge_config(cfg)
    base_f, _ = score(catalog, baseline, cfg)
    keys = [(g, k) for g in ("hazard_by_change", "receptor_by_tag") for k in cfg[g]] + [("hop_decay", None)]
    runs = 0
    same = {(f.asset, f.change): 0 for f in base_f}
    for g, k in keys:
        for m in (factor, 1 / factor):
            c = copy.deepcopy(cfg)
            if k is None:
                c[g] = min(0.99, c[g] * m)
            else:
                c[g][k] *= m
            runs += 1
            for f in score(catalog, baseline, c)[0]:
                if f.band == next(b.band for b in base_f if (b.asset, b.change) == (f.asset, f.change)):
                    same[(f.asset, f.change)] += 1
    return {k: v / runs for k, v in same.items()}
