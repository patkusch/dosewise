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
    a = p.parse_args(argv)
    cfg = engine.load(a.config) if a.config else None
    findings, ref = engine.score(engine.load(a.catalog), engine.load(a.baseline), cfg)
    sys.stdout.write(report.markdown(findings, ref))
    if a.json:
        with open(a.json, "w") as f:
            json.dump([dataclasses.asdict(x) for x in findings], f, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
