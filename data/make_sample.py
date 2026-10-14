"""Writes the invented sample catalog and its baseline. Run once; the output is committed."""
import json

def t(n, **kw):
    kw.setdefault("owner", "data-team")
    return {"id": n, "platform": n.split(".")[0], "name": n, "schema": {f"c{i}": "string" for i in range(kw.pop("cols", 9))}, **kw}

assets = [
    t("warehouse.addresses", usage={"queries_30d": 2400}, tags=[]),
    t("postgres.addresses", usage={"queries_30d": 12}),
    t("warehouse.customers", usage={"queries_30d": 5200}, tags=["pii"]),
    t("warehouse.orders", usage={"queries_30d": 8000}, tags=["finance"]),
    t("warehouse.refunds", usage={"queries_30d": 300}),
    t("warehouse.web_events", usage={"queries_30d": 40}, owner=None),
]
for i in range(6):                      # postgres.addresses has lots of downstream, nobody reads it
    assets.append(t(f"postgres.stage_{i}", usage={"queries_30d": None}))
assets += [
    t("looker.revenue_board", usage={"queries_30d": 900}, tags=["executive"]),
    t("looker.address_map", usage={"queries_30d": 600}),
    t("looker.churn", usage={"queries_30d": 3000}, tags=["pii"]),
    t("warehouse.sessions", usage={"queries_30d": 20}, standing_issues=["nullable key"]),
    t("warehouse.promo_codes", usage={"queries_30d": 5}, standing_issues=["no description", "mixed case names"]),
    t("warehouse.legacy_fx", usage={"queries_30d": 0}, standing_issues=["no owner"]),
]
edges = [
    {"from": "warehouse.addresses", "to": "looker.address_map", "columns": ["c0", "c1"]},
    {"from": "warehouse.customers", "to": "looker.churn", "columns": ["c0", "c1"]},
    {"from": "warehouse.orders", "to": "looker.revenue_board", "columns": ["c0"]},
    {"from": "warehouse.refunds", "to": "looker.revenue_board"},
    {"from": "warehouse.web_events", "to": "looker.churn"},
]
edges += [{"from": "postgres.addresses", "to": "postgres.stage_0"}]
edges += [{"from": f"postgres.stage_{i}", "to": f"postgres.stage_{i+1}"} for i in range(5)]
baseline = {a["id"]: dict(a["schema"]) for a in assets}
def edit(aid, drop=(), retype=()):
    schema = next(a for a in assets if a["id"] == aid)["schema"]
    for c in drop:
        del schema[c]
    for c in retype:
        schema[c] = "int"
edit("warehouse.addresses", drop=["c0", "c1"])
edit("postgres.addresses", drop=["c0", "c1"])
edit("warehouse.customers", drop=["c0", "c1"])
edit("warehouse.orders", retype=["c0"])
edit("warehouse.web_events", retype=["c8"])
json.dump({"assets": assets, "edges": edges}, open("data/catalog.json", "w"), indent=1)
json.dump(baseline, open("data/baseline.json", "w"), indent=1)
