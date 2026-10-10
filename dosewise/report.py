from __future__ import annotations

import csv


def markdown(findings, ref):
    acts = [f for f in findings if f.band == "Act"]
    zero = [f for f in findings if f.risk == 0]
    lines = ["# Dosewise report", "",
             f"{len(findings)} findings. {len(acts)} need action. {len(zero)} score exactly zero.",
             f"Action line (from the written reference case): {ref:.2f}", "",
             "| rank | was (by downstream count) | asset | change | risk | band |", "|---|---|---|---|---|---|"]
    for f in findings:
        lines.append(f"| {f.rank} | {f.naive_rank} | {f.asset} | {f.change} | {f.risk} | {f.band} |")
    lines += ["", "## Why", ""]
    for f in findings:
        if f.risk > 0:
            lines.append(f"**{f.asset}** ({f.change}, {f.band}): " + "; ".join(f.reasons) + ".")
            lines.append(f"  Hazard {f.hazard} x dose {f.dose} x exposure {f.exposure} x receptor {f.receptor} x uncertainty {f.uncertainty} = {f.risk}")
            lines.append("")
    if zero:
        lines += ["## Scored zero", "", "These are real, but nothing about them changed, so they are not today's problem:", ""]
        lines += [f"- {f.asset}: {f.change.split(':')[-1]}" for f in zero]
    return "\n".join(lines) + "\n"


def write_csv(findings, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "naive_rank", "asset", "change", "risk", "band", "why"])
        for x in findings:
            w.writerow([x.rank, x.naive_rank, x.asset, x.change, x.risk, x.band, "; ".join(x.reasons)])
