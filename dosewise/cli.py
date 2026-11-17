import argparse
import dataclasses
import json
import sys

from . import __version__, engine, report

BANDS = ("Act", "Monitor", "No Action")
PREVIOUS_KEYS = {"asset", "change", "risk", "band"}


def parse_bands(text):
    """The bands the user named, matched without case, with an unknown name reported.

    `--only act` used to print an empty report and exit 0, which reads as "nothing needs action".
    """
    picked = []
    for raw in text.split(","):
        name = raw.strip()
        match = next((b for b in BANDS if b.lower() == name.lower()), None)
        if match is None:
            sys.stderr.write(f"dosewise: warning: {name or '(nothing)'} is not a band, choose from {', '.join(BANDS)}\n")
        elif match not in picked:
            picked.append(match)
    return picked


def load_previous(path):
    """An earlier --json result. Anything else is named, because the report reads four keys from it."""
    data = engine.load(path)
    wanted = ", ".join(sorted(PREVIOUS_KEYS))
    if not isinstance(data, list) or not all(isinstance(x, dict) and PREVIOUS_KEYS <= set(x) for x in data):
        raise ValueError(f"{path} is not an earlier --json result: expected a list of findings, each with {wanted}")
    return data


def main(argv=None):
    p = argparse.ArgumentParser(prog="dosewise", description=__doc__)
    p.add_argument("--version", action="version", version=f"dosewise {__version__}")
    p.add_argument("--catalog", required=True, help="catalog JSON: assets and lineage edges")
    p.add_argument("--baseline", required=False, help="saved schema baseline JSON")
    p.add_argument("--config", help="optional JSON overriding the scoring settings")
    p.add_argument("--only", help="show only these bands, e.g. Act,Monitor (the exit code still looks at everything)")
    p.add_argument("--stability", action="store_true", help="also check how often each verdict survives nudging the weights")
    p.add_argument("--explain", metavar="ASSET", help="print the full breakdown for one asset and stop")
    p.add_argument("--max-hops", type=int, help="how many steps of lineage to follow (default 4)")
    p.add_argument("--write-baseline", metavar="FILE", help="save the catalog's current schemas as a new baseline and stop")
    p.add_argument("--html", help="also write a single-page HTML report here")
    p.add_argument("--format", choices=["markdown", "github"], default="markdown", help="github prints Actions annotations")
    p.add_argument("--min-risk", type=float, help="hide findings below this risk score")
    p.add_argument("--quiet", action="store_true", help="print one summary line instead of the report")
    p.add_argument("--top", type=int, help="show only the N highest-risk findings")
    p.add_argument("--since", metavar="JSON", help="compare with an earlier --json result and list what changed")
    p.add_argument("--csv", help="also write a spreadsheet-friendly CSV here")
    p.add_argument("--json", help="also write results here")
    p.add_argument("--fail-on", choices=["Act", "Monitor"], help="exit 1 if any finding reaches this band (for CI)")
    a = p.parse_args(argv)
    if a.top is not None and a.top < 1:
        p.exit(2, "dosewise: --top must be at least 1, or the report would be empty\n")
    if a.write_baseline:
        try:
            cat = engine.load(a.catalog)
        except FileNotFoundError as e:
            p.exit(2, f"dosewise: can't find {e.filename}\n")
        with open(a.write_baseline, "w", encoding="utf-8") as f:
            json.dump({x["id"]: x["schema"] for x in cat["assets"]}, f, indent=1, sort_keys=True)
        return 0
    if not a.baseline:
        p.exit(2, "dosewise: --baseline is required unless you pass --write-baseline\n")
    try:
        cfg = engine.load(a.config) if a.config else None
        if a.max_hops is not None:
            cfg = {**(cfg or {}), "max_hops": a.max_hops}
        catalog = engine.load(a.catalog)
        baseline = engine.load(a.baseline)
        findings, ref = engine.score(catalog, baseline, cfg)
    except FileNotFoundError as e:
        p.exit(2, f"dosewise: can't find {e.filename}\n")
    except ValueError as e:
        if isinstance(e, json.JSONDecodeError):
            p.exit(2, f"dosewise: that file is not valid JSON ({e})\n")
        p.exit(2, f"dosewise: {e}\n")
    except json.JSONDecodeError as e:
        p.exit(2, f"dosewise: that file is not valid JSON ({e})\n")
    except KeyError as e:
        p.exit(2, f"dosewise: the catalog is missing the field {e}\n")
    if a.explain:
        hits = [f for f in findings if f.asset == a.explain]
        if not hits:
            p.exit(2, f"dosewise: no finding for {a.explain}\n")
        for f in hits:
            sys.stdout.write(f"{f.asset} ({f.change}): risk {f.risk}, {f.band}\n")
            for r in f.reasons:
                sys.stdout.write(f"  - {r}\n")
            for n, h, q in f.consumers:
                sys.stdout.write(f"  downstream: {n}, {h} step(s) away, " + (f"{q} queries a month" if q is not None else "no usage data") + "\n")
            sys.stdout.write(f"  hazard {f.hazard} x dose {f.dose} x exposure {f.exposure} x receptor {f.receptor} x uncertainty {f.uncertainty}\n")
        return 0
    if a.only is None:
        shown = findings
    else:
        bands = parse_bands(a.only)  # parsed once: a typo is one warning, not one per finding
        shown = [f for f in findings if f.band in bands]
    if a.min_risk is not None:
        shown = [f for f in shown if f.risk >= a.min_risk]
    if a.top:
        shown = shown[: a.top]
    cat_ids = {x["id"] for x in catalog["assets"]}
    for e in catalog.get("edges", []):
        for end in (e["from"], e["to"]):
            if end not in cat_ids:
                sys.stderr.write(f"dosewise: warning: lineage mentions {end}, which is not in the catalog\n")
    if a.quiet:
        sys.stdout.write("dosewise: " + ", ".join(f"{b} {sum(f.band == b for f in findings)}" for b in ("Act", "Monitor", "No Action")) + "\n")
    else:
        sys.stdout.write((report.github if a.format == "github" else report.markdown)(shown, ref))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump([dataclasses.asdict(x) for x in findings], f, indent=2, sort_keys=True)
    if a.since:
        try:
            previous = load_previous(a.since)
        except FileNotFoundError as e:
            p.exit(2, f"dosewise: can't find {e.filename}\n")
        except json.JSONDecodeError as e:
            p.exit(2, f"dosewise: {a.since} is not valid JSON ({e})\n")
        except ValueError as e:
            p.exit(2, f"dosewise: {e}\n")
        sys.stdout.write(report.since(findings, previous))
    if a.stability:
        st = engine.stability(catalog, baseline, cfg)
        sys.stdout.write("\n## Do the verdicts hold up?\n\nShare of weight changes (each weight made 1.5x bigger or smaller) that keep the same band:\n\n")
        for f in shown:
            if f.risk > 0:
                sys.stdout.write(f"- {f.asset} ({f.change}): {st[(f.asset, f.change)]:.0%}\n")
    if a.html:
        with open(a.html, "w", encoding="utf-8") as f:
            f.write(report.html(findings, ref))
    if a.csv:
        report.write_csv(findings, a.csv)
    if a.fail_on:
        hit = {"Act": ("Act",), "Monitor": ("Act", "Monitor")}[a.fail_on]
        if any(f.band in hit for f in findings):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
