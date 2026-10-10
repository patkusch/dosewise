import argparse
import dataclasses
import json
import sys

from . import engine, report


def main(argv=None):
    p = argparse.ArgumentParser(prog="dosewise", description=__doc__)
    p.add_argument("--catalog", required=True, help="catalog JSON: assets and lineage edges")
    p.add_argument("--baseline", required=True, help="saved schema baseline JSON")
    p.add_argument("--config", help="optional JSON overriding the scoring settings")
    p.add_argument("--json", help="also write results here")
    p.add_argument("--fail-on", choices=["Act", "Monitor"], help="exit 1 if any finding reaches this band (for CI)")
    a = p.parse_args(argv)
    try:
        cfg = engine.load(a.config) if a.config else None
        findings, ref = engine.score(engine.load(a.catalog), engine.load(a.baseline), cfg)
    except FileNotFoundError as e:
        p.exit(2, f"dosewise: can't find {e.filename}\n")
    except json.JSONDecodeError as e:
        p.exit(2, f"dosewise: that file is not valid JSON ({e})\n")
    except KeyError as e:
        p.exit(2, f"dosewise: the catalog is missing the field {e}\n")
    sys.stdout.write(report.markdown(findings, ref))
    if a.json:
        with open(a.json, "w") as f:
            json.dump([dataclasses.asdict(x) for x in findings], f, indent=2, sort_keys=True)
    if a.fail_on:
        hit = {"Act": ("Act",), "Monitor": ("Act", "Monitor")}[a.fail_on]
        if any(f.band in hit for f in findings):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
