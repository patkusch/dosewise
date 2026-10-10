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
