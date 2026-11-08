#!/usr/bin/env python3
"""Render synthetic quantitative and conceptual figures using Python's standard library."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from xml.sax.saxutils import escape

BASE = Path(__file__).resolve().parent
INPUTS = ("measurements.csv", "protocol.txt", "erroneous-diagram.json")
OUTPUTS = ("measurements.svg", "protocol.svg", "erroneous-reference.svg", "statistics.json", "provenance.json")


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def number(value):
    return f"{value:.6g}"


def read_measurements(path):
    groups = {}
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["time_min", "replicate", "concentration_mg_L"]:
            raise ValueError("Expected exact CSV headers: time_min,replicate,concentration_mg_L")
        for row in reader:
            time = float(row["time_min"])
            value = float(row["concentration_mg_L"])
            replicate = int(row["replicate"])
            if not math.isfinite(time) or not math.isfinite(value):
                raise ValueError("Missing or nonfinite measurements are invalid; zero is valid")
            group = groups.setdefault(time, {})
            if replicate in group:
                raise ValueError("Duplicate replicate")
            group[replicate] = value
    if not groups:
        raise ValueError("No measurements")
    result = []
    for time, replicates in sorted(groups.items()):
        if set(replicates) != {1, 2, 3}:
            raise ValueError("Each time requires replicate IDs 1, 2, 3")
        values = [replicates[index] for index in (1, 2, 3)]
        result.append({"time_min": time, "values_mg_L": values, "n": len(values),
                       "mean_mg_L": statistics.mean(values),
                       "sample_sd_mg_L": statistics.stdev(values)})
    return result


def document(title, body, provenance, height=520):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" '
            f'viewBox="0 0 900 {height}" role="img" aria-labelledby="title description">\n'
            f'<title id="title">{escape(title)}</title>\n'
            f'<desc id="description">{escape(provenance["description"])}</desc>\n'
            f'<metadata>{escape(encoded(provenance))}</metadata>\n'
            '<rect width="100%" height="100%" fill="white"/>\n'
            '<g font-family="Arial, sans-serif" font-size="16" fill="#17252d">\n'
            + body + '</g>\n</svg>\n')


def label(x, y, content, **attrs):
    options = " ".join(f'{key.replace("_", "-")}="{escape(str(value))}"' for key, value in attrs.items())
    return f'<text x="{number(x)}" y="{number(y)}" {options}>{escape(content)}</text>\n'


def plot(rows, provenance):
    left, right, top, bottom = 105, 805, 85, 365
    times = [row["time_min"] for row in rows]
    low = min(0, *(row["mean_mg_L"] - row["sample_sd_mg_L"] for row in rows))
    high = max(0, *(row["mean_mg_L"] + row["sample_sd_mg_L"] for row in rows))
    # Scale is calculated from the supplied data; no observations are altered.
    span = high - low or 1
    high += span * .12
    tx = lambda t: left + (t - min(times)) / (max(times) - min(times) or 1) * (right - left)
    ty = lambda value: bottom - (value - low) / (high - low) * (bottom - top)
    body = label(450, 32, "Synthetic concentration measurements", text_anchor="middle", font_size="23")
    body += label(450, 57, "Mean ± sample SD; n = 3 per time; SD is not a confidence interval", text_anchor="middle", font_size="14")
    for tick in range(5):
        value = low + tick * (high - low) / 4
        y = ty(value)
        body += f'<path d="M {left} {y:.6f} H {right}" stroke="#dce2e5"/>\n'
        body += label(left - 12, y + 5, number(value), text_anchor="end")
    body += f'<path d="M {left} {top} V {bottom} H {right}" fill="none" stroke="#17252d"/>\n'
    points = " ".join(f'{tx(row["time_min"]):.6f},{ty(row["mean_mg_L"]):.6f}' for row in rows)
    body += f'<polyline points="{points}" fill="none" stroke="#14647a" stroke-width="2"/>\n'
    for row in rows:
        x = tx(row["time_min"])
        y = ty(row["mean_mg_L"])
        upper = ty(row["mean_mg_L"] + row["sample_sd_mg_L"])
        lower = ty(row["mean_mg_L"] - row["sample_sd_mg_L"])
        body += f'<path d="M {x:.6f} {upper:.6f} V {lower:.6f} M {x-7:.6f} {upper:.6f} H {x+7:.6f} M {x-7:.6f} {lower:.6f} H {x+7:.6f}" stroke="#14647a" stroke-width="2"/>\n'
        body += f'<circle cx="{x:.6f}" cy="{y:.6f}" r="5" fill="#14647a"/>\n'
        body += label(x, bottom + 25, number(row["time_min"]), text_anchor="middle")
        body += label(x, upper - 12, number(row["mean_mg_L"]), text_anchor="middle", font_weight="bold")
    body += label(450, 425, "Time (min)", text_anchor="middle")
    body += '<text transform="translate(28 225) rotate(-90)" text-anchor="middle">Concentration (mg/L)</text>\n'
    body += label(105, 464, "Synthetic triplicates from measurements.csv; error bars use sample SD (denominator n − 1).", font_size="14")
    body += label(105, 487, "Zero at 0 min and decrease at 2 min are retained; line connects means only.", font_size="14")
    return document("Synthetic mean concentration ± sample SD", body, provenance)


def diagram(steps, provenance, erroneous=False):
    title = "ERROR FIXTURE — reject against protocol" if erroneous else "Conceptual protocol order"
    body = label(450, 40, title, text_anchor="middle", font_size="23")
    for i, step in enumerate(steps):
        x = 35 + 220 * i
        body += f'<rect x="{x}" y="85" width="165" height="70" rx="8" fill="#e6f1f4" stroke="#14647a"/>\n'
        body += label(x + 82.5, 127, step, text_anchor="middle", font_size="21")
        if i < len(steps) - 1:
            body += f'<path d="M {x+175} 120 H {x+207} l -8 -6 m 8 6 l -8 6" fill="none" stroke="#17252d" stroke-width="2"/>\n'
    body += label(35, 202, "Order follows protocol.txt; synthetic example, not a validated laboratory procedure.", font_size="16")
    body += label(35, 230, "No reagent, timing, organism, or causal mechanism is implied.", font_size="16")
    if erroneous:
        body += label(35, 260, "Planted error: fix and stain are reversed. This fixture is not evidence.", font_size="16")
    return document(title, body, provenance, height=295)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=BASE / "generated")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    # Never let regeneration overwrite source files, directly or through symlinks.
    if output == BASE or output in BASE.parents:
        parser.error("Output directory must be separate from the source directory and its ancestors")
    if any((output / name).is_symlink() for name in OUTPUTS):
        parser.error("Refusing output symlinks")
    if any((output / name).exists() and any((output / name).samefile(BASE / source)
           for source in (*INPUTS, "generate.py")) for name in OUTPUTS):
        parser.error("Refusing output hard links to inputs or generator")
    rows = read_measurements(BASE / INPUTS[0])
    protocol = (BASE / INPUTS[1]).read_text(encoding="utf-8")
    steps = re.findall(r"^\d+\. ([a-z]+)$", protocol, re.MULTILINE)
    if len(steps) != 4 or len(set(steps)) != 4:
        raise ValueError("This example supports exactly four distinct protocol steps")
    fixture = json.loads((BASE / INPUTS[2]).read_text(encoding="utf-8"))
    if len(fixture["steps"]) != 4:
        raise ValueError("Error fixture must contain four steps")
    provenance = {"description": "Original synthetic fixture; no observed study results or generated numerical imagery.",
                  "sources_sha256": {name: hashlib.sha256((BASE / name).read_bytes()).hexdigest() for name in INPUTS},
                  "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "analysis": "statistics.mean and statistics.stdev; sample SD, denominator n-1; n=3",
                  "command": "python3 docs/examples/scientific-figures/generate.py",
                  "formats": "Editable SVG text and paths; JSON statistics. No PDF/PNG or proprietary layered format."}
    artifacts = {"measurements.svg": plot(rows, provenance), "protocol.svg": diagram(steps, provenance),
                 "erroneous-reference.svg": diagram(fixture["steps"], provenance, erroneous=True),
                 "statistics.json": encoded(rows), "provenance.json": encoded(provenance)}
    output.mkdir(parents=True, exist_ok=True)
    for name, content in artifacts.items():
        (output / name).write_text(content, encoding="utf-8", newline="\n")
    print(f"Wrote {len(artifacts)} deterministic artifacts to {output}")


if __name__ == "__main__":
    main()
