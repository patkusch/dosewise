import argparse
import dataclasses
import json
import sys

from . import __version__, engine, report


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
    p.add_argument("--csv", help="also write a spreadsheet-friendly CSV here")
    p.add_argument("--json", help="also write results here")
    p.add_argument("--fail-on", choices=["Act", "Monitor"], help="exit 1 if any finding reaches this band (for CI)")
    a = p.parse_args(argv)
    if a.write_baseline:
        try:
            cat = engine.load(a.catalog)
        except FileNotFoundError as e:
            p.exit(2, f"dosewise: can't find {e.filename}\n")
        with open(a.write_baseline, "w") as f:
            json.dump({x["id"]: x["schema"] for x in cat["assets"]}, f, indent=1, sort_keys=True)
        return 0
    if not a.baseline:
        p.exit(2, "dosewise: --baseline is required unless you pass --write-baseline\n")
    try:
        cfg = engine.load(a.config) if a.config else None
        if a.max_hops is not None:
            cfg = {**(cfg or {}), "max_hops": a.max_hops}
        findings, ref = engine.score(engine.load(a.catalog), engine.load(a.baseline), cfg)
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
            sys.stdout.write(f"  hazard {f.hazard} x dose {f.dose} x exposure {f.exposure} x receptor {f.receptor} x uncertainty {f.uncertainty}\n")
        return 0
    shown = [f for f in findings if f.band in a.only.split(",")] if a.only else findings
    cat_ids = {x["id"] for x in engine.load(a.catalog)["assets"]}
    for e in engine.load(a.catalog).get("edges", []):
        for end in (e["from"], e["to"]):
            if end not in cat_ids:
                sys.stderr.write(f"dosewise: warning: lineage mentions {end}, which is not in the catalog\n")
    sys.stdout.write((report.github if a.format == "github" else report.markdown)(shown, ref))
    if a.json:
        with open(a.json, "w") as f:
            json.dump([dataclasses.asdict(x) for x in findings], f, indent=2, sort_keys=True)
    if a.stability:
        st = engine.stability(engine.load(a.catalog), engine.load(a.baseline), cfg)
        sys.stdout.write("\n## Do the verdicts hold up?\n\nShare of weight changes (each weight made 1.5x bigger or smaller) that keep the same band:\n\n")
        for f in shown:
            if f.risk > 0:
                sys.stdout.write(f"- {f.asset} ({f.change}): {st[(f.asset, f.change)]:.0%}\n")
    if a.html:
        with open(a.html, "w") as f:
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
