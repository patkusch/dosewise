import json, os, subprocess, sys
from dosewise import engine

D = os.path.join(os.path.dirname(__file__), "..", "data")
cat, base = engine.load(f"{D}/catalog.json"), engine.load(f"{D}/baseline.json")
F, REF = engine.score(cat, base)
by = {(f.asset, f.change): f for f in F}


def test_twin_tables_broken_identically_rank_by_who_is_exposed():
    a, b = by[("warehouse.addresses", "column_removed")], by[("postgres.addresses", "column_removed")]
    assert (a.hazard, a.dose) == (b.hazard, b.dose)
    assert a.naive_downstream < b.naive_downstream      # a blast-radius ranker puts postgres first
    assert a.risk > b.risk and a.rank < b.rank          # real exposure reverses it


def test_missing_evidence_raises_the_score():
    b = by[("postgres.addresses", "column_removed")]
    assert b.uncertainty > 1.0
    assert b.risk > 0


def test_column_lineage_filters_consumers_that_never_read_the_column():
    f = by[("warehouse.web_events", "type_changed")]
    assert f.naive_downstream == 1  # unknown column lineage: still counted, with uncertainty
    g = by[("warehouse.orders", "type_changed")]
    assert g.naive_downstream == 1


def test_unchanged_standing_issues_score_exactly_zero():
    z = [f for f in F if f.change.startswith("standing:")]
    assert len(z) == 4 and all(f.risk == 0 and f.band == "No Action" for f in z)


def test_healthy_catalog_is_silent():
    f, _ = engine.score(cat, {a["id"]: a["schema"] for a in cat["assets"]})
    assert all(x.risk == 0 for x in f)


def test_same_input_same_output():
    assert [x.risk for x in engine.score(cat, base)[0]] == [x.risk for x in F]


def test_bands_use_the_written_reference_case():
    assert engine.band(REF, engine.DEFAULT_CONFIG) == "Act"
    assert engine.band(REF * 0.3, engine.DEFAULT_CONFIG) == "Monitor"
    assert engine.band(REF * 0.1, engine.DEFAULT_CONFIG) == "No Action"


def test_cli_runs():
    r = subprocess.run([sys.executable, "-m", "dosewise", "--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json"],
                       capture_output=True, text=True, cwd=os.path.join(D, ".."))
    assert r.returncode == 0 and "Dosewise report" in r.stdout


def test_unmeasured_consumers_never_make_exposure_zero():
    assert by[("postgres.addresses", "column_removed")].exposure > 0


def _cli(*extra):
    return subprocess.run([sys.executable, "-m", "dosewise", "--catalog", f"{D}/catalog.json", "--baseline", f"{D}/baseline.json", *extra],
                          capture_output=True, text=True, cwd=os.path.join(D, ".."))


def test_fail_on_act_exits_nonzero_when_something_needs_action():
    assert _cli("--fail-on", "Act").returncode == 1
    assert _cli().returncode == 0


def test_unowned_table_scores_higher_than_the_same_table_with_an_owner():
    owned = {**cat, "assets": [dict(a, owner="x") if a["id"] == "warehouse.web_events" else a for a in cat["assets"]]}
    f2, _ = engine.score(owned, base)
    mine = {(f.asset, f.change): f for f in f2}[("warehouse.web_events", "type_changed")]
    assert by[("warehouse.web_events", "type_changed")].risk > mine.risk


def test_missing_file_gives_a_plain_message_not_a_traceback():
    r = subprocess.run([sys.executable, "-m", "dosewise", "--catalog", "nope.json", "--baseline", f"{D}/baseline.json"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "can't find nope.json" in r.stderr and "Traceback" not in r.stderr


def test_a_dropped_table_is_scored_like_every_column_removed():
    gone = {**cat, "assets": [a for a in cat["assets"] if a["id"] != "warehouse.customers"]}
    f, _ = engine.score(gone, base)
    d = {(x.asset, x.change): x for x in f}[("warehouse.customers", "table_removed")]
    assert d.dose == 1.0 and d.risk > by[("warehouse.customers", "column_removed")].risk


def test_csv_has_one_row_per_finding(tmp_path):
    out = tmp_path / "r.csv"
    assert _cli("--csv", str(out)).returncode == 0
    lines = out.read_text().strip().splitlines()
    assert lines[0].startswith("rank,") and len(lines) == len(F) + 1


def test_each_scored_finding_says_what_would_change_its_verdict():
    for f in F:
        if f.risk > 0 and f.band != "Act":
            assert any("would move to" in r for r in f.reasons)


def test_only_filters_the_report_but_not_the_exit_code():
    r = _cli("--only", "Act", "--fail-on", "Act")
    assert "postgres.addresses" not in r.stdout and "warehouse.customers" in r.stdout
    assert r.returncode == 1


def test_stability_is_a_share_between_zero_and_one_and_zero_findings_never_flip():
    st = engine.stability(cat, base)
    assert all(0 <= v <= 1 for v in st.values())
    assert all(st[(f.asset, f.change)] == 1.0 for f in F if f.change.startswith("standing:"))
    assert "Do the verdicts hold up?" in _cli("--stability").stdout


def test_a_cycle_in_the_lineage_does_not_hang_or_count_the_table_as_its_own_consumer():
    loop = {**cat, "edges": cat["edges"] + [{"from": "looker.address_map", "to": "warehouse.addresses"}]}
    f, _ = engine.score(loop, base)
    d = {(x.asset, x.change): x for x in f}[("warehouse.addresses", "column_removed")]
    assert d.naive_downstream == 1


def test_explain_prints_one_assets_breakdown():
    r = _cli("--explain", "postgres.addresses")
    assert r.returncode == 0 and "no usage data" in r.stdout and "warehouse" not in r.stdout
    assert _cli("--explain", "nope").returncode == 2


def test_max_hops_limits_how_far_lineage_is_followed():
    near = {(f.asset, f.change): f for f in engine.score(cat, base, {"max_hops": 1})[0]}
    assert near[("postgres.addresses", "column_removed")].naive_downstream == 1
    assert by[("postgres.addresses", "column_removed")].naive_downstream == 4
    assert "--max-hops" in _cli("--help").stdout


def test_a_typo_in_the_config_is_an_error_not_silently_ignored(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="unknown setting"):
        engine.score(cat, base, {"hop_decays": 0.5})
    bad = tmp_path / "c.json"
    bad.write_text('{"hop_decay": 5}')
    r = _cli("--config", str(bad))
    assert r.returncode == 2 and "hop_decay" in r.stderr


def test_the_example_config_is_valid_and_runs():
    assert _cli("--config", f"{D}/config.example.json").returncode == 0


def test_a_fresh_baseline_makes_the_catalog_look_healthy(tmp_path):
    out = tmp_path / "b.json"
    assert subprocess.run([sys.executable, "-m", "dosewise", "--catalog", f"{D}/catalog.json", "--write-baseline", str(out)]).returncode == 0
    r = subprocess.run([sys.executable, "-m", "dosewise", "--catalog", f"{D}/catalog.json", "--baseline", str(out), "--only", "Act,Monitor"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "0 need action" in r.stdout


def test_html_report_escapes_and_lists_every_finding(tmp_path):
    out = tmp_path / "r.html"
    assert _cli("--html", str(out)).returncode == 0
    text = out.read_text()
    assert text.count("<tr class=") == len(F) and "<script" not in text


def test_package_version_matches_pyproject():
    import dosewise, re
    text = open(os.path.join(D, "..", "pyproject.toml")).read()
    assert re.search(rf'version = "{re.escape(dosewise.__version__)}"', text)


def test_a_sensitive_domain_raises_receptor_weight():
    plain = engine.receptor_weight({"id": "x"}, engine.DEFAULT_CONFIG)
    fin = engine.receptor_weight({"id": "x", "domain": "finance"}, engine.DEFAULT_CONFIG)
    assert plain == 1.0 and fin == 1.8


def test_changing_a_key_column_is_worse_than_changing_an_ordinary_one():
    keyed = {**cat, "assets": [dict(a, key_columns=["c0"]) if a["id"] == "warehouse.customers" else a for a in cat["assets"]]}
    k = {(f.asset, f.change): f for f in engine.score(keyed, base)[0]}[("warehouse.customers", "column_removed")]
    assert k.risk > by[("warehouse.customers", "column_removed")].risk
    assert any("key column" in r for r in k.reasons)


def test_report_summarises_counts_by_band():
    assert "By band: Act 1, Monitor 3, No Action 5." in _cli().stdout


def test_github_format_marks_act_as_error_and_monitor_as_warning():
    out = _cli("--format", "github").stdout
    assert out.count("::error") == 1 and out.count("::warning") == 3


def test_results_do_not_depend_on_the_order_of_assets_or_edges():
    import random
    for seed in range(5):
        r = random.Random(seed)
        shuffled = {"assets": r.sample(cat["assets"], len(cat["assets"])), "edges": r.sample(cat["edges"], len(cat["edges"]))}
        f, _ = engine.score(shuffled, base)
        assert [(x.asset, x.change, x.risk, x.rank) for x in f] == [(x.asset, x.change, x.risk, x.rank) for x in F]


def test_format_doc_lists_every_exit_code_the_cli_uses():
    text = open(os.path.join(D, "..", "docs", "format.md")).read()
    assert all(f"| {c} |" in text for c in (0, 1, 2))


def test_version_flag():
    import dosewise
    assert _cli("--version").stdout.strip() == f"dosewise {dosewise.__version__}"


def test_duplicate_asset_ids_are_rejected_plainly(tmp_path):
    bad = {**cat, "assets": cat["assets"] + [cat["assets"][0]]}
    p = tmp_path / "dup.json"
    p.write_text(__import__("json").dumps(bad))
    r = subprocess.run([sys.executable, "-m", "dosewise", "--catalog", str(p), "--baseline", f"{D}/baseline.json"],
                       capture_output=True, text=True, cwd=os.path.join(D, ".."))
    assert r.returncode == 2 and "more than once" in r.stderr


def test_lineage_pointing_at_an_unknown_table_warns_but_still_runs(tmp_path):
    bad = {**cat, "edges": cat["edges"] + [{"from": "warehouse.customers", "to": "ghost.table"}]}
    p = tmp_path / "ghost.json"
    p.write_text(__import__("json").dumps(bad))
    r = subprocess.run([sys.executable, "-m", "dosewise", "--catalog", str(p), "--baseline", f"{D}/baseline.json"],
                       capture_output=True, text=True, cwd=os.path.join(D, ".."))
    assert r.returncode == 0 and "ghost.table" in r.stderr


def test_top_limits_the_table_to_the_highest_risk_rows():
    out = _cli("--top", "2").stdout
    assert out.count("| warehouse.") + out.count("| postgres.") == 2 and "warehouse.customers" in out


def test_a_report_with_nothing_in_it_says_so():
    assert "Nothing to show." in _cli("--only", "Nope").stdout


def test_a_widening_type_change_is_much_milder_than_a_breaking_one():
    b2 = {k: dict(v) for k, v in base.items()}
    b2["warehouse.orders"]["c0"] = "int"
    cat2 = {**cat, "assets": [dict(a, schema=dict(a["schema"], c0="bigint")) if a["id"] == "warehouse.orders" else a for a in cat["assets"]]}
    f = {(x.asset, x.change): x for x in engine.score(cat2, b2)[0]}
    wide = f[("warehouse.orders", "type_widened")]
    assert wide.hazard == 0.2 and wide.risk < by[("warehouse.orders", "type_changed")].risk


def test_a_removal_alongside_an_addition_is_flagged_as_a_possible_rename():
    cat2 = {**cat, "assets": [dict(a, schema={**{k: v for k, v in a["schema"].items()}, "new_a": "string", "new_b": "string"}) if a["id"] == "warehouse.customers" else a for a in cat["assets"]]}
    f = {(x.asset, x.change): x for x in engine.score(cat2, base)[0]}[("warehouse.customers", "column_removed")]
    assert any("rename" in r for r in f.reasons)
    assert not any("rename" in r for r in by[("warehouse.customers", "column_removed")].reasons)


def test_since_lists_new_resolved_and_moved_findings(tmp_path):
    first = tmp_path / "first.json"
    assert _cli("--json", str(first)).returncode == 0
    same = _cli("--since", str(first)).stdout
    assert "nothing changed" in same
    healed = tmp_path / "b.json"
    healed.write_text(__import__("json").dumps({a["id"]: a["schema"] for a in cat["assets"]}))
    r = subprocess.run([sys.executable, "-m", "dosewise", "--catalog", f"{D}/catalog.json", "--baseline", str(healed), "--since", str(first)],
                       capture_output=True, text=True, cwd=os.path.join(D, ".."))
    assert "resolved: warehouse.customers" in r.stdout


def test_scoring_doc_matches_the_defaults():
    text = open(os.path.join(D, "..", "docs", "scoring.md")).read()
    c = engine.DEFAULT_CONFIG
    assert str(c["exposure_floor"]) in text and str(c["key_column_multiplier"]) in text
    assert str(c["hazard_by_change"]["type_widened"]) in text and str(c["receptor_by_tag"]["pii"]) in text


def test_non_ascii_table_names_survive_every_output(tmp_path):
    odd = {"assets": [{"id": "dw.café", "schema": {"a": "int", "b": "int"}, "usage": {"queries_30d": 10}},
                      {"id": "dw.übersicht", "schema": {"a": "int"}, "usage": {"queries_30d": 10}}],
           "edges": [{"from": "dw.café", "to": "dw.übersicht"}]}
    (tmp_path / "c.json").write_text(__import__("json").dumps(odd, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "b.json").write_text(__import__("json").dumps({"dw.café": {"a": "int", "b": "int", "c": "int"}, "dw.übersicht": {"a": "int"}}), encoding="utf-8")
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "dosewise", "--catalog", str(tmp_path / "c.json"), "--baseline", str(tmp_path / "b.json"),
                        "--html", str(tmp_path / "o.html"), "--csv", str(tmp_path / "o.csv"), "--json", str(tmp_path / "o.json")],
                       capture_output=True, text=True, encoding="utf-8", cwd=os.path.join(D, ".."))
    assert r.returncode == 0 and "café" in (tmp_path / "o.html").read_text(encoding="utf-8")


def test_a_large_catalog_scores_quickly():
    import time
    n = 3000
    assets = [{"id": f"t{i}", "schema": {"a": "int", "b": "int"}, "usage": {"queries_30d": i % 50}} for i in range(n)]
    edges = [{"from": f"t{i}", "to": f"t{(i * 7 + 1) % n}"} for i in range(n)]
    baseline = {a["id"]: {"a": "int", "b": "int", "c": "int"} for a in assets}
    t0 = time.time()
    f, _ = engine.score({"assets": assets, "edges": edges}, baseline)
    assert len(f) == n and time.time() - t0 < 5


def test_explain_lists_each_consumer_with_distance_and_usage():
    out = _cli("--explain", "warehouse.addresses").stdout
    assert "downstream: looker.address_map, 1 step(s) away, 600 queries a month" in out
    assert "no usage data" in _cli("--explain", "postgres.addresses").stdout
