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
