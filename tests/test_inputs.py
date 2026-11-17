"""Bad input is named, not crashed on: settings and the catalog are checked before any score is computed."""
import json
import os
import subprocess
import sys

import pytest

from dosewise import engine

D = os.path.join(os.path.dirname(__file__), "..", "data")
cat, base = engine.load(f"{D}/catalog.json"), engine.load(f"{D}/baseline.json")


def _run(*args):
    return subprocess.run([sys.executable, "-m", "dosewise", *args], capture_output=True, text=True,
                          cwd=os.path.join(D, ".."))


def _write(tmp_path, name, value):
    p = tmp_path / name
    p.write_text(json.dumps(value), encoding="utf-8")
    return str(p)


# --- settings -------------------------------------------------------------

def test_a_weight_table_given_as_a_number_is_named():
    with pytest.raises(ValueError, match="hazard_by_change must be a map of name to weight"):
        engine.score(cat, base, {"hazard_by_change": 2})


def test_a_single_weight_that_is_text_is_named_with_its_own_key():
    with pytest.raises(ValueError, match=r"receptor_by_tag\.pii must be a number"):
        engine.score(cat, base, {"receptor_by_tag": {"pii": "high"}})


def test_a_boolean_is_not_a_weight():
    with pytest.raises(ValueError, match="uncertainty_no_owner must be a number, not bool"):
        engine.score(cat, base, {"uncertainty_no_owner": True})


def test_an_ignore_pattern_written_as_a_string_used_to_ignore_nothing():
    # A bare string is iterated character by character, so every pattern failed to match
    # and the tables the setting named were scored anyway. It is an error now.
    with pytest.raises(ValueError, match="ignore must be a list of table patterns"):
        engine.score(cat, base, {"ignore": "warehouse.*"})
    kept = {f.asset for f in engine.score(cat, base, {"ignore": ["warehouse.*"]})[0]}
    assert not any(name.startswith("warehouse.") for name in kept)


def test_a_monitor_fraction_above_one_would_empty_the_band():
    with pytest.raises(ValueError, match="monitor_fraction"):
        engine.score(cat, base, {"monitor_fraction": 1.5})
    with pytest.raises(ValueError, match="monitor_fraction"):
        engine.score(cat, base, {"monitor_fraction": 0})


def test_a_growth_ratio_below_one_would_call_every_consumer_rising():
    with pytest.raises(ValueError, match="growth_ratio must be at least 1"):
        engine.score(cat, base, {"growth_ratio": 0.5})


def test_a_reference_case_that_scores_zero_is_refused():
    with pytest.raises(ValueError, match="reference case must score above zero"):
        engine.score(cat, base, {"reference_case": {"hazard": 0}})
    with pytest.raises(ValueError, match="reference_case.queries must be a number, not str"):
        engine.score(cat, base, {"reference_case": {"queries": "a thousand"}})


def test_naming_one_number_of_the_reference_case_keeps_the_rest():
    # The reference case merges like every other table, so a partial override is valid input.
    ref = engine.score(cat, base, {"reference_case": {"queries": 4000}})[1]
    assert ref > engine.reference_score(engine.DEFAULT_CONFIG)


def test_max_hops_must_be_a_whole_number():
    with pytest.raises(ValueError, match="max_hops must be a whole number"):
        engine.score(cat, base, {"max_hops": 2.5})
    with pytest.raises(ValueError, match="max_hops must be a whole number"):
        engine.score(cat, base, {"max_hops": "4"})


def test_a_bad_setting_from_a_file_is_exit_2_without_a_traceback(tmp_path):
    r = _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json",
             "--config", _write(tmp_path, "c.json", {"receptor_by_tag": 2}))
    assert r.returncode == 2 and "receptor_by_tag" in r.stderr
    assert "Traceback" not in r.stderr


# --- catalog --------------------------------------------------------------

def test_usage_null_means_unmeasured_and_does_not_crash():
    # `"usage": null` is how a hand-written catalog says "nothing measured here".
    unmeasured = {"assets": [{"id": "t", "schema": {"a": "int"}, "usage": None},
                             {"id": "u", "schema": {"a": "int"}, "usage": None},
                             {"id": "v", "schema": {"a": "int"}, "usage": {"queries_30d": 10}}],
                  "edges": [{"from": "t", "to": "u"}, {"from": "u", "to": "v"}]}
    mine = {f.change: f for f in engine.score(unmeasured, {"t": {"a": "int", "b": "string"}})[0]}["column_removed"]
    assert mine.risk > 0 and "no usage data" in " ".join(mine.reasons)


def test_queries_written_as_text_are_named():
    with pytest.raises(ValueError, match="queries_30d must be a number, not str"):
        engine.score({"assets": [{"id": "t", "schema": {"a": "int"}, "usage": {"queries_30d": "10"}}]}, {})


def test_a_boolean_query_count_is_not_a_measurement():
    with pytest.raises(ValueError, match="queries_30d must be a number, not bool"):
        engine.score({"assets": [{"id": "t", "schema": {"a": "int"}, "usage": {"queries_30d": True}}]}, {})


def test_an_asset_without_a_string_id_is_named():
    with pytest.raises(ValueError, match="needs a string id"):
        engine.score({"assets": [{"schema": {"a": "int"}}]}, {})


def test_lists_written_as_strings_are_named():
    # "pii" iterated as a string yields the tags "p" and "i", so the sensitivity was silently lost.
    for key in ("tags", "key_columns", "standing_issues"):
        bad = {"assets": [{"id": "t", "schema": {"a": "int"}, key: "pii"}]}
        with pytest.raises(ValueError, match=f"{key} must be a list of strings"):
            engine.score(bad, {})


def test_sensitivity_must_be_a_number():
    with pytest.raises(ValueError, match="sensitivity must be a number"):
        engine.score({"assets": [{"id": "t", "schema": {"a": "int"}, "sensitivity": "high"}]}, {})


def test_edges_must_be_a_list_of_steps_with_both_ends():
    with pytest.raises(ValueError, match="edges must be a list"):
        engine.score({"assets": [{"id": "t", "schema": {"a": "int"}}], "edges": {"from": "t"}}, {})
    with pytest.raises(ValueError, match="every edge needs"):
        engine.score({"assets": [{"id": "t", "schema": {"a": "int"}}], "edges": [{"from": "t"}]}, {})
    with pytest.raises(ValueError, match="columns must be a list of column names"):
        engine.score({"assets": [{"id": "t", "schema": {"a": "int"}}],
                      "edges": [{"from": "t", "to": "t", "columns": "a"}]}, {})


def test_a_catalog_that_is_not_an_object_is_named():
    with pytest.raises(ValueError, match="the catalog must be a JSON object"):
        engine.score([], {})
    with pytest.raises(ValueError, match='the catalog needs an "assets" list'):
        engine.score({"nodes": {}}, {})


def test_a_bad_catalog_from_a_file_is_exit_2_without_a_traceback(tmp_path):
    r = _run("--catalog", _write(tmp_path, "c.json", {"assets": [{"id": "t", "schema": {"a": "int"},
                                                                 "usage": {"queries_30d": "lots"}}]}),
             "--baseline", f"{D}/baseline.json")
    assert r.returncode == 2 and "queries_30d must be a number" in r.stderr
    assert "Traceback" not in r.stderr


def test_the_shipped_config_example_still_validates():
    engine.check_config(engine.load(f"{D}/config.example.json"))


# --- tables the baseline knows nothing about ------------------------------

def test_a_first_harvest_from_a_tool_that_lists_no_columns_does_not_divide_by_zero():
    # A catalog built from dbt's manifest, or a warehouse the client could not describe,
    # has tables whose saved schema is an empty map. Adding columns to one of those used to
    # end the whole run with ZeroDivisionError, because dose is columns over saved columns.
    catalog = {"assets": [{"id": "raw.orders", "schema": {"id": "int", "total": "int"}},
                          {"id": "dash.revenue", "schema": {"total": "int"}, "usage": {"queries_30d": 4000}}],
               "edges": [{"from": "raw.orders", "to": "dash.revenue"}]}
    found = engine.score(catalog, {"raw.orders": {}})[0]
    (f,) = [x for x in found if x.change == "column_added"]
    assert f.dose == 1.0 and f.risk > 0
    assert "no saved columns" in f.reasons[0]


def test_removing_a_table_with_no_saved_columns_crashed_and_now_reaches_its_consumers():
    catalog = {"assets": [{"id": "dash.revenue", "schema": {"total": "int"}, "usage": {"queries_30d": 4000}}],
               "edges": [{"from": "raw.orders", "to": "dash.revenue", "columns": ["total"]}]}
    (f,) = [x for x in engine.score(catalog, {"raw.orders": {}})[0] if x.asset == "raw.orders"]
    assert f.change == "table_removed" and f.dose == 1.0
    # Column-level lineage must not hide the dashboard: the whole table is gone, not one column.
    assert f.naive_downstream == 1
    assert f.risk > 0


def test_a_table_that_is_new_since_the_baseline_is_not_a_finding():
    catalog = {"assets": [{"id": "new.thing", "schema": {"a": "int"}}]}
    assert not [f for f in engine.score(catalog, {})[0] if not f.change.startswith("standing:")]


def test_a_baseline_written_from_a_catalog_with_an_empty_schema_is_quiet(tmp_path):
    catalog = _write(tmp_path, "c.json", {"assets": [{"id": "raw.orders", "schema": {}},
                                                     {"id": "raw.users", "schema": {"id": "int"}}]})
    base = str(tmp_path / "b.json")
    assert _run("--catalog", catalog, "--write-baseline", base).returncode == 0
    r = _run("--catalog", catalog, "--baseline", base, "--quiet")
    assert r.returncode == 0 and "Act 0" in r.stdout and "Traceback" not in r.stderr


# --- flags ----------------------------------------------------------------

def test_top_below_one_is_refused_instead_of_being_ignored():
    # `--top 0` is falsy, so the limit was never applied and the full report came out;
    # `--top -1` sliced off the last finding instead of the first.
    for value in ("0", "-1"):
        r = _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json", "--top", value)
        assert r.returncode == 2 and "--top must be at least 1" in r.stderr
        assert "Traceback" not in r.stderr


def test_only_matches_bands_without_case():
    quiet = _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json", "--only", "act", "--quiet")
    assert quiet.returncode == 0 and quiet.stderr == ""
    assert "warehouse.customers" in _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json",
                                         "--only", "act,monitor").stdout


def test_an_unknown_band_is_one_warning_per_run_not_one_per_finding():
    r = _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json", "--only", "act,Nope")
    assert r.returncode == 0 and r.stderr.count("Nope is not a band") == 1
    assert "Nothing to show." in _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json",
                                      "--only", "Nope").stdout


def test_since_refuses_a_file_that_is_not_an_earlier_json_result(tmp_path):
    same = _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json",
                "--since", _write(tmp_path, "baseline.json", base))
    assert same.returncode == 2 and "is not an earlier --json result" in same.stderr
    assert "Traceback" not in same.stderr
    listed = _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json",
                  "--since", _write(tmp_path, "list.json", ["a"]))
    assert listed.returncode == 2 and "is not an earlier --json result" in listed.stderr
    broken = tmp_path / "broken.json"
    broken.write_text("{oops", encoding="utf-8")
    bad = _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json", "--since", str(broken))
    assert bad.returncode == 2 and "not valid JSON" in bad.stderr and "Traceback" not in bad.stderr


def test_a_json_result_missing_a_key_the_report_needs_is_named(tmp_path):
    r = _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json",
             "--since", _write(tmp_path, "half.json", [{"asset": "a", "change": "column_added"}]))
    assert r.returncode == 2 and "each with asset, band, change, risk" in r.stderr


# --- github annotations ---------------------------------------------------

def test_github_annotations_escape_their_own_data():
    # Workflow command data must escape %, CR and LF. Every reason here carries a percentage
    # ("2 of 9 columns (22%)"), and %0A in the middle of it is decoded as a newline by Actions.
    out = _run("--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json",
               "--format", "github").stdout
    assert out.count("::error") == 1 and "%" in out
    stripped = out.replace("%25", "").replace("%0D", "").replace("%0A", "")
    assert "%" not in stripped
    assert out.count("\n") == out.count("::error") + out.count("::warning")


def test_a_table_name_cannot_break_out_of_an_annotation(tmp_path):
    odd = {"assets": [{"id": "a::b%0Ainjected", "schema": {"c": "int"}},
                      {"id": "down", "schema": {"c": "int"}, "usage": {"queries_30d": 5000}, "tags": ["pii"]}],
           "edges": [{"from": "a::b%0Ainjected", "to": "down"}]}
    r = _run("--catalog", _write(tmp_path, "c.json", odd),
             "--baseline", _write(tmp_path, "b.json", {"a::b%0Ainjected": {"c": "int", "d": "int"}}),
             "--format", "github")
    assert r.returncode == 0
    assert "%250A" in r.stdout and "%0A" not in r.stdout.replace("%250A", "")
    assert r.stdout.count("\n") == 1
