import csv

from dosewise import report
from dosewise.engine import Finding


def finding(asset, change, risk, band, **kw):
    base = dict(asset=asset, change=change, columns=[], hazard=1.0, dose=0.5, exposure=1.0, receptor=1.0, uncertainty=1.0,
                risk=risk, band=band, naive_downstream=2, naive_rank=1, rank=1, reasons=["two dashboards read it"], domain="finance", consumers=[])
    base.update(kw)
    return Finding(**base)


ACT = finding("db.orders", "column_removed", 4.2, "Act", rank=1, naive_rank=3, reasons=["a PII dashboard reads it", "1,000 queries a month"])
WATCH = finding("db.users", "type_changed", 1.1, "Monitor", rank=2, naive_rank=1, domain="customer")
QUIET = finding("db.logs", "column_added: note", 0.0, "No Action", rank=3, naive_rank=2, domain="", reasons=[])
ALL = [ACT, WATCH, QUIET]


def test_the_report_opens_with_the_counts_by_band_and_how_many_score_exactly_zero():
    md = report.markdown(ALL, 2.5)
    assert "3 findings. 1 need action. 1 score exactly zero." in md
    assert "By band: Act 1, Monitor 1, No Action 1." in md
    assert "Action line (from the written reference case): 2.50" in md


def test_the_table_shows_each_finding_with_its_rank_and_where_a_count_only_ranker_would_have_put_it():
    md = report.markdown(ALL, 2.5)
    assert "| rank | was (by downstream count) | asset | change | risk | band |" in md
    assert "| 1 | 3 | db.orders | column_removed | 4.2 | Act |" in md
    assert "| 3 | 2 | db.logs | column_added: note | 0.0 | No Action |" in md


def test_the_why_section_explains_only_findings_that_scored_and_shows_the_arithmetic():
    md = report.markdown(ALL, 2.5)
    why = md.split("## Why")[1].split("## ")[0]
    assert "**db.orders** (column_removed, Act): a PII dashboard reads it; 1,000 queries a month." in why
    assert "Hazard 1.0 x dose 0.5 x exposure 1.0 x receptor 1.0 x uncertainty 1.0 = 4.2" in why
    assert "db.logs" not in why


def test_risk_is_added_up_by_domain_biggest_first_with_a_label_for_no_domain():
    md = report.markdown([ACT, WATCH, finding("db.x", "type_changed", 0.5, "Monitor", domain="")], 2.5)
    domains = md.split("## Risk by domain")[1].split("## ")[0].strip().splitlines()
    assert domains == ["- finance: 4.20", "- customer: 1.10", "- (no domain): 0.50"]


def test_things_that_scored_zero_are_listed_separately_as_not_todays_problem():
    md = report.markdown(ALL, 2.5)
    assert "## Scored zero" in md
    assert "- db.logs: note" in md
    assert "not today's problem" in md


def test_an_empty_report_says_there_is_nothing_to_show_and_has_no_sections_to_fill():
    md = report.markdown([], 2.5)
    assert "0 findings. 0 need action. 0 score exactly zero." in md
    assert "Nothing to show." in md
    assert "## Risk by domain" not in md and "## Scored zero" not in md


def test_github_annotations_mark_act_as_an_error_and_monitor_as_a_warning_and_skip_the_rest():
    lines = report.github(ALL, 2.5).strip().splitlines()
    assert lines[0].startswith("::error title=Dosewise Act::db.orders column_removed risk 4.2. a PII dashboard reads it; 1,000 queries")
    assert lines[1].startswith("::warning title=Dosewise Monitor::db.users type_changed risk 1.1.")
    assert len(lines) == 2
    assert report.github([QUIET], 2.5) == ""


def test_since_lists_what_is_new_what_was_resolved_and_what_changed_band():
    previous = [
        {"asset": "db.orders", "change": "column_removed", "risk": 2.0, "band": "Monitor"},
        {"asset": "db.gone", "change": "column_removed", "risk": 3.0, "band": "Act"},
        {"asset": "db.zero", "change": "x", "risk": 0.0, "band": "No Action"},
    ]
    out = report.since([ACT, WATCH, QUIET], previous)
    assert "## Since the last run" in out
    assert "- new: db.users (type_changed), Monitor" in out
    assert "- resolved: db.gone (column_removed)" in out
    assert "- moved: db.orders (column_removed) Monitor to Act" in out
    assert "db.zero" not in out, "something that was already zero is not a resolution"
    assert "db.logs" not in out, "a new finding that scores zero is not news"


def test_since_says_when_nothing_changed():
    previous = [{"asset": a.asset, "change": a.change, "risk": a.risk, "band": a.band} for a in ALL]
    assert "- nothing changed" in report.since(ALL, previous)


def test_the_page_escapes_what_it_shows_so_an_odd_table_name_cannot_inject_markup():
    nasty = finding("<script>alert(1)</script>", "column_removed", 3.0, "Act", reasons=["a & b < c"])
    page = report.html([nasty], 2.5)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "a &amp; b &lt; c" in page
    assert "<tr class='act'>" in page
    assert "1 findings, 1 need action. Action line 2.50." in page


def test_each_band_gets_its_own_row_style():
    page = report.html(ALL, 2.5)
    assert "<tr class='act'>" in page and "<tr class='monitor'>" in page and "<tr class='noaction'>" in page


def test_the_csv_has_a_header_one_row_per_finding_and_the_reasons_joined(tmp_path):
    path = tmp_path / "out.csv"
    report.write_csv(ALL, str(path))
    rows = list(csv.reader(path.open(encoding="utf-8", newline="")))
    assert rows[0] == ["rank", "naive_rank", "asset", "change", "risk", "band", "why"]
    assert rows[1] == ["1", "3", "db.orders", "column_removed", "4.2", "Act", "a PII dashboard reads it; 1,000 queries a month"]
    assert len(rows) == 4
    assert rows[3][-1] == ""
