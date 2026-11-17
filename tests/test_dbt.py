"""The dbt importer: models and sources in, a dosewise catalog out."""
import json
import os
import subprocess
import sys

import pytest

from dosewise import dbt, engine

D = os.path.join(os.path.dirname(__file__), "..", "data")

OLD_CUSTOMERS = {"customer_id": {"data_type": "integer"}, "email": {"data_type": "varchar"},
                 "lifetime_value": {"data_type": "numeric"}}
NEW_CUSTOMERS = {"customer_id": {"data_type": "integer"}, "email": {"data_type": "varchar"}}


def _node(uid, resource_type="model", columns=None, depends=(), tags=(), meta=None):
    return {"unique_id": uid, "resource_type": resource_type, "name": uid.rsplit(".", 1)[-1],
            "database": "analytics", "schema": "dbt_dev", "alias": uid.rsplit(".", 1)[-1],
            "tags": list(tags), "config": {"tags": list(tags), "meta": dict(meta or {})},
            "columns": dict(columns or {}), "depends_on": {"macros": [], "nodes": list(depends)},
            "group": None, "meta": {}, "fqn": uid.split(".")}


def _manifest(customers=OLD_CUSTOMERS, orders=None):
    return {
        "metadata": {"dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json",
                     "dbt_version": "1.8.7", "project_name": "jaffle_shop"},
        "nodes": {
            "model.jaffle_shop.stg_customers": _node(
                "model.jaffle_shop.stg_customers", columns={"customer_id": {"data_type": "integer"}},
                depends=["source.jaffle_shop.raw.raw_customers"]),
            "model.jaffle_shop.customers": _node(
                "model.jaffle_shop.customers", columns=customers,
                depends=["model.jaffle_shop.stg_customers"], tags=["pii"],
                meta={"owner": "", "domain": "customer", "queries_30d": 4200, "queries_prev_30d": 2100}),
            "model.jaffle_shop.orders": _node(
                "model.jaffle_shop.orders", columns=orders or {"order_id": {"data_type": "integer"}},
                depends=["model.jaffle_shop.customers"], meta={"owner": "data-team", "sensitivity": 1.9}),
            "seed.jaffle_shop.country_codes": _node("seed.jaffle_shop.country_codes", "seed"),
            "test.jaffle_shop.unique_customers": _node(
                "test.jaffle_shop.unique_customers", "test", depends=["model.jaffle_shop.customers"]),
        },
        "sources": {
            "source.jaffle_shop.raw.raw_customers": _node(
                "source.jaffle_shop.raw.raw_customers", "source", tags=["raw"]),
        },
    }


def _measured(types):
    return {"nodes": {"model.jaffle_shop.customers": {
        "columns": {name: {"type": kind} for name, kind in types.items()}}}}


def _run(*args):
    return subprocess.run([sys.executable, "-m", "dosewise", *args], capture_output=True, text=True,
                          cwd=os.path.join(D, ".."))


def _write(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


# --- what becomes what ----------------------------------------------------

def test_models_and_sources_become_assets_and_tests_and_seeds_do_not():
    catalog = dbt.catalog_from_manifest(_manifest())
    ids = [a["id"] for a in catalog["assets"]]
    assert ids == ["model.jaffle_shop.customers", "model.jaffle_shop.orders",
                   "model.jaffle_shop.stg_customers", "source.jaffle_shop.raw.raw_customers"]


def test_depends_on_becomes_lineage_between_tables_only():
    # The test node depends on the customers model, and the model on the source: only the
    # step between two tables is lineage, or every dbt test would look like a consumer.
    catalog = dbt.catalog_from_manifest(_manifest())
    assert catalog["edges"] == [
        {"from": "model.jaffle_shop.customers", "to": "model.jaffle_shop.orders"},
        {"from": "model.jaffle_shop.stg_customers", "to": "model.jaffle_shop.customers"},
        {"from": "source.jaffle_shop.raw.raw_customers", "to": "model.jaffle_shop.stg_customers"},
    ]


def test_the_result_is_a_catalog_the_engine_accepts():
    engine.check_catalog(dbt.catalog_from_manifest(_manifest()))


def test_a_column_without_a_declared_type_is_kept_as_unknown():
    manifest = _manifest(customers={"customer_id": {"data_type": "integer"}, "note": {"description": ""}})
    schema = {a["id"]: a["schema"] for a in dbt.catalog_from_manifest(manifest)["assets"]}
    assert schema["model.jaffle_shop.customers"] == {"customer_id": "integer", "note": "unknown"}


# --- meta -----------------------------------------------------------------

def test_meta_settings_are_carried_over():
    assets = {a["id"]: a for a in dbt.catalog_from_manifest(_manifest())["assets"]}
    customers, orders = assets["model.jaffle_shop.customers"], assets["model.jaffle_shop.orders"]
    assert customers["tags"] == ["pii"] and customers["domain"] == "customer"
    assert customers["owner"] == ""  # empty, not missing: nobody owns it
    assert customers["usage"] == {"queries_30d": 4200, "queries_prev_30d": 2100}
    assert orders["owner"] == "data-team" and orders["sensitivity"] == 1.9


def test_an_owner_left_out_is_not_the_same_as_an_empty_one():
    # docs/format.md: leave `owner` out if you do not track owners, include it empty if nobody owns
    # the table: the empty one raises uncertainty.
    inferred = {a["id"]: a for a in dbt.catalog_from_manifest(_manifest())["assets"]}
    assert "owner" not in inferred["model.jaffle_shop.stg_customers"]
    assert inferred["model.jaffle_shop.customers"]["owner"] == ""


def test_owner_null_raises_uncertainty_in_the_score():
    catalog = dbt.catalog_from_manifest(_manifest(customers=NEW_CUSTOMERS))
    found = engine.score(catalog, {"model.jaffle_shop.customers": OLD_CUSTOMERS})
    mine = [f for f in found[0] if f.asset == "model.jaffle_shop.customers"
            and f.change == "column_removed"][0]
    assert any("nobody owns this table" in r for r in mine.reasons)


def test_a_boolean_is_not_a_query_count_in_meta():
    manifest = _manifest()
    manifest["nodes"]["model.jaffle_shop.orders"]["config"]["meta"]["queries_30d"] = True
    with pytest.raises(ValueError, match=r"meta.queries_30d must be a number"):
        dbt.catalog_from_manifest(manifest)


def test_meta_lists_must_be_lists():
    manifest = _manifest()
    manifest["nodes"]["model.jaffle_shop.orders"]["config"]["meta"]["key_columns"] = "order_id"
    with pytest.raises(ValueError, match=r"meta.key_columns must be a list of strings"):
        dbt.catalog_from_manifest(manifest)


# --- inputs that are not dbt ---------------------------------------------

def test_a_file_that_is_not_a_manifest_is_named():
    with pytest.raises(ValueError, match="not a dbt manifest"):
        dbt.catalog_from_manifest({"foo": 1})
    with pytest.raises(ValueError, match="not a dbt manifest"):
        dbt.catalog_from_manifest({"nodes": []})
    with pytest.raises(ValueError, match="manifest sources must be a map"):
        dbt.catalog_from_manifest({"nodes": {}, "sources": []})
    with pytest.raises(ValueError, match="no models, sources or snapshots"):
        dbt.catalog_from_manifest({"nodes": {}})
    with pytest.raises(ValueError, match="must be a JSON object"):
        dbt.catalog_from_manifest([1, 2])


def test_a_file_that_is_not_a_dbt_catalog_is_named():
    with pytest.raises(ValueError, match="not a dbt catalog.json"):
        dbt.catalog_from_manifest(_manifest(), {"metadata": {}})
    assert dbt.measured_columns(None) == {}


# --- through the command line --------------------------------------------

def test_a_manifest_run_writes_a_baseline_and_the_next_run_compares_against_it(tmp_path):
    old = _write(tmp_path, "old.json", _manifest())
    new = _write(tmp_path, "new.json", _manifest(customers=NEW_CUSTOMERS))
    base = str(tmp_path / "base.json")
    first = _run("--from-dbt", old, "--write-baseline", base)
    assert first.returncode == 0, first.stderr
    second = _run("--from-dbt", new, "--baseline", base)
    assert second.returncode == 0, second.stderr
    assert "column_removed" in second.stdout and "model.jaffle_shop.customers" in second.stdout
    assert "type_changed" not in second.stdout


def test_types_differing_only_in_case_are_not_a_change(tmp_path):
    # dbt's catalog reports warehouse case: Snowflake says INTEGER where YAML says integer, and a
    # change of case is not a change of type. Without this, handing over a catalog once and not the
    # next time invented a type change on every column.
    base = str(tmp_path / "base.json")
    old = _write(tmp_path, "old.json", _manifest())
    assert _run("--from-dbt", old, "--dbt-catalog", _write(tmp_path, "cat.json", _measured(OLD_CUSTOMERS)),
                "--write-baseline", base).returncode == 0
    same = _run("--from-dbt", old, "--baseline", base)
    assert same.returncode == 0 and "type_changed" not in same.stdout
    assert "column_removed" not in same.stdout and "0 need action" in same.stdout


def test_a_new_column_from_dbt_is_a_finding(tmp_path):
    base = str(tmp_path / "base.json")
    assert _run("--from-dbt", _write(tmp_path, "old.json", _manifest()), "--write-baseline", base).returncode == 0
    grown = dict(OLD_CUSTOMERS, phone={"data_type": "varchar"})
    r = _run("--from-dbt", _write(tmp_path, "new.json", _manifest(customers=grown)), "--baseline", base)
    assert r.returncode == 0 and "column_added" in r.stdout


def test_the_command_line_refuses_mixed_sources(tmp_path):
    manifest = _write(tmp_path, "m.json", _manifest())
    both = _run("--from-dbt", manifest, "--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json")
    assert both.returncode == 2 and "not both" in both.stderr
    orphan = _run("--dbt-catalog", _write(tmp_path, "c.json", _measured(OLD_CUSTOMERS)),
                  "--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json")
    assert orphan.returncode == 2 and "--from-dbt" in orphan.stderr
    neither = _run("--baseline", f"{D}/baseline.json")
    assert neither.returncode == 2 and "not both" in neither.stderr
    not_dbt = _run("--from-dbt", _write(tmp_path, "x.json", {"foo": 1}), "--baseline", f"{D}/baseline.json")
    assert not_dbt.returncode == 2 and "Traceback" not in not_dbt.stderr
