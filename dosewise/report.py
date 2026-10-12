from __future__ import annotations

import csv


def markdown(findings, ref):
    acts = [f for f in findings if f.band == "Act"]
    zero = [f for f in findings if f.risk == 0]
    lines = ["# Dosewise report", "",
             f"{len(findings)} findings. {len(acts)} need action. {len(zero)} score exactly zero.",
             "By band: " + ", ".join(f"{b} {sum(f.band == b for f in findings)}" for b in ("Act", "Monitor", "No Action")) + ".",
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


def html(findings, ref):
    import html as h
    rows = "".join(
        f"<tr class='{f.band.replace(' ', '').lower()}'><td>{f.rank}</td><td>{f.naive_rank}</td><td>{h.escape(f.asset)}</td>"
        f"<td>{h.escape(f.change)}</td><td>{f.risk}</td><td>{f.band}</td><td>{h.escape('; '.join(f.reasons))}</td></tr>"
        for f in findings)
    acts = sum(f.band == "Act" for f in findings)
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Dosewise report</title>
<style>body{{font:15px system-ui;margin:2rem auto;max-width:70rem;padding:0 1rem}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:.4rem .6rem;border-bottom:1px solid #8884;text-align:left;vertical-align:top}}
.act td:nth-child(6){{color:#b00020;font-weight:700}}.monitor td:nth-child(6){{color:#9a6700;font-weight:700}}.noaction{{opacity:.6}}</style>
<h1>Dosewise report</h1><p>{len(findings)} findings, {acts} need action. Action line {ref:.2f}.
"Was" is the rank by downstream count alone.</p>
<table><tr><th>Rank<th>Was<th>Asset<th>Change<th>Risk<th>Band<th>Why</tr>{rows}</table>
"""


def github(findings, ref):
    """GitHub Actions annotations: Act shows as an error, Monitor as a warning."""
    out = []
    for f in findings:
        if f.band in ("Act", "Monitor"):
            level = "error" if f.band == "Act" else "warning"
            out.append(f"::{level} title=Dosewise {f.band}::{f.asset} {f.change} risk {f.risk}. " + "; ".join(f.reasons))
    return "\n".join(out) + ("\n" if out else "")
