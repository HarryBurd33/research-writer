#!/usr/bin/env python3
"""Reproduce a bounded Many Labs 1 framing reanalysis; Python standard library."""
import csv
import json
import math
from pathlib import Path


def pool(effects):
    weights = [1 / variance for _, variance in effects]
    total = sum(weights)
    mean = sum(w * y for w, (y, _) in zip(weights, effects)) / total
    q = sum(w * (y - mean) ** 2 for w, (y, _) in zip(weights, effects))
    df = len(effects) - 1
    c = total - sum(w * w for w in weights) / total
    tau2 = max(0, (q - df) / c)
    random_weights = [1 / (v + tau2) for _, v in effects]
    random_total = sum(random_weights)
    random_mean = sum(w * y for w, (y, _) in zip(random_weights, effects)) / random_total
    def estimate(mu, precision):
        se = math.sqrt(1 / precision)
        return {"OR": math.exp(mu), "CI95": [math.exp(mu - 1.959963984540054 * se),
                                                math.exp(mu + 1.959963984540054 * se)]}
    return {"common_effect": estimate(mean, total),
            "DL_random_effects": estimate(random_mean, random_total),
            "Q": q, "df": df, "tau2": tau2,
            "I2_percent": max(0, (q - df) / q) * 100 if q else 0}


def main():
    with Path(__file__).with_name("extracted-site-counts.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len({r["site"] for r in rows}) == 36
    keys = ["loss_risky", "loss_certain", "gain_risky", "gain_certain"]
    totals = {key: sum(int(r[key]) for r in rows) for key in keys}
    assert list(totals.values()) == [2059, 1038, 1200, 1974]
    n = sum(totals.values())
    missing = sum(int(r["missing"]) for r in rows)
    assert (n, missing, n + missing) == (6271, 73, 6344)
    effects = []
    for row in rows:
        a, b, c, d = (int(row[key]) for key in keys)
        assert min(a, b, c, d) > 0  # No continuity corrections are needed here.
        effects.append((math.log(a * d / (b * c)), 1/a + 1/b + 1/c + 1/d))
    result = pool(effects)
    expected = [(result["common_effect"]["OR"], 3.3112866263920773),
                (result["DL_random_effects"]["OR"], 3.324510636000973),
                (result["Q"], 37.011606401298934),
                (result["tau2"], 0.006356444607632024),
                (result["I2_percent"], 5.435069149628523)]
    assert all(math.isclose(x, y, rel_tol=1e-12, abs_tol=1e-12) for x, y in expected)
    loo = [{"omitted_site": row["site"], "OR": pool(effects[:i] + effects[i+1:])["DL_random_effects"]["OR"]}
           for i, row in enumerate(rows)]
    bounds = [min(r["OR"] for r in loo), max(r["OR"] for r in loo)]
    assert all(math.isclose(x, y, rel_tol=1e-12) for x, y in
               zip(bounds, [3.2535559371917957, 3.3725674100705336]))
    print(json.dumps({"sites": len(rows), "N_observed": n, "missing": missing,
                      "cells": totals, **result, "leave_one_out_OR_range": bounds,
                      "leave_one_out": loo, "frozen_expectations_passed": True}, indent=2))


if __name__ == "__main__":
    main()
