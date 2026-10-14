"""The scoring engine. Plain arithmetic, no model, same input gives the same output.

Risk = Hazard x Exposure x Receptor sensitivity x Uncertainty
"""
from __future__ import annotations

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


def load(path):
    with open(path) as f:
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


def downstream(edges, start, max_hops, touched):
    """Breadth-first walk with the shortest hop count to each consumer."""
    children = {}
    for e in edges:
        children.setdefault(e["from"], []).append(e)
    seen, queue, unknown_edges = {start: 0}, deque([(start, 0)]), 0
    while queue:
        node, hop = queue.popleft()
        if hop >= max_hops:
            continue
        for e in children.get(node, []):
            cols = e.get("columns")
            if hop == 0 and cols is not None and not set(cols) & set(touched):
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


def receptor_weight(asset, cfg):
    w = 1.0
    for t in asset.get("tags", []):
        w = max(w, cfg["receptor_by_tag"].get(t, 1.0))
    w = max(w, cfg["receptor_by_domain"].get(asset.get("domain"), 1.0))
    if asset.get("platform") in ("looker", "tableau", "powerbi"):
        w = max(w, cfg["receptor_by_tag"].get("dashboard", 1.0))
    return w


def check_config(cfg):
    """Fail early and plainly on a typo, instead of silently ignoring it."""
    unknown = set(cfg) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    if not 0 < cfg.get("hop_decay", 0.5) <= 1:
        raise ValueError("hop_decay must be above 0 and at most 1")
    if cfg.get("max_hops", 1) < 1:
        raise ValueError("max_hops must be at least 1")


def score(catalog, baseline, cfg=None):
    check_config(cfg or {})
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}
    ids = [a["id"] for a in catalog["assets"]]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"the same asset id appears more than once: {', '.join(dupes)}")
    assets = {a["id"]: a for a in catalog["assets"]}
    edges = catalog.get("edges", [])
    findings = []
    for aid, kind, cols, ncols in diff_schemas(baseline, assets, cfg["safe_type_changes"]):
        seen, unknown_edges = downstream(edges, aid, cfg["max_hops"], cols)
        dose = len(cols) / ncols
        hazard = cfg["hazard_by_change"][kind]
        keys = set(assets.get(aid, {}).get("key_columns", [])) & set(cols)
        if keys:
            hazard *= cfg["key_column_multiplier"]
        reasons = [f"{kind.replace('_', ' ')} on {len(cols)} of {ncols} columns ({dose:.0%})"]
        if keys:
            reasons.append(f"touches key column(s) {sorted(keys)}, which makes it worse")
        weighted, unmeasured, receptor = 0.0, 0, 1.0
        for node, hop in seen.items():
            q = assets.get(node, {}).get("usage", {}).get("queries_30d")
            if q is None:
                unmeasured += 1
            else:
                weighted += q * cfg["hop_decay"] ** (hop - 1)
            if node in assets:
                receptor = max(receptor, receptor_weight(assets[node], cfg))
        # Unmeasured is not unused: if anything is downstream, exposure never drops to zero.
        exposure = max(math.log10(1 + weighted), cfg["exposure_floor"]) if seen else 0.0
        unc = 1.0
        if seen:
            unc += cfg["uncertainty_unknown_usage"] * unmeasured / len(seen)
            unc += cfg["uncertainty_unknown_column_lineage"] * unknown_edges / max(1, sum(1 for e in edges if e["from"] == aid))
        a = assets.get(aid, {})
        if "owner" in a and not a["owner"]:
            unc += cfg["uncertainty_no_owner"]
            reasons.append("nobody owns this table, so nobody is accountable: missing evidence raises uncertainty")
        if not seen:
            reasons.append("nothing downstream reads the changed columns")
        else:
            reasons.append(f"{len(seen)} downstream, {weighted:.0f} weighted queries a month after distance decay")
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
                                round(unc, 3), round(risk, 2), b, len(seen), reasons=reasons))
    # Standing issues (problems that were already there and have not changed) score zero.
    for a in catalog["assets"]:
        for issue in a.get("standing_issues", []):
            seen, _ = downstream(edges, a["id"], cfg["max_hops"], [])
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
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}
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
