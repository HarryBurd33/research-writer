"""Reproduce ONLY the fictional B-shared-control fixture; standard library only.
Not a general-purpose meta-analysis library or a recommended universal estimator.

Chosen analysis: combine North's active arms using the exact combined sample
variance, then use independent study mean differences. Random effects uses
DerSimonian–Laird tau^2 and a modified Hartung–Knapp interval (variance floor
at the conventional inverse-weight variance). A normal common-effect interval
is a sensitivity analysis; only three studies means heterogeneity is uncertain.
"""
import json
import math
import platform
from pathlib import Path

HERE = Path(__file__).resolve().parent
data = json.loads((HERE / "inputs.json").read_text())
z = 1.959963984540054
rows = []
for study in data["studies"]:
    arms = study["arms"]
    n = sum(a["n"] for a in arms)
    mean = sum(a["n"] * a["mean"] for a in arms) / n
    variance = sum((a["n"] - 1) * a["sd"] ** 2 + a["n"] * (a["mean"] - mean) ** 2 for a in arms) / (n - 1)
    control = study["control"]
    effect = mean - control["mean"]
    effect_variance = variance / n + control["sd"] ** 2 / control["n"]
    se = math.sqrt(effect_variance)
    rows.append({"study": study["study"], "active_n": n, "active_mean": mean,
                 "active_sd": math.sqrt(variance), "control_n": control["n"],
                 "mean_difference": effect, "variance": effect_variance,
                 "normal_95_ci": [effect - z * se, effect + z * se]})

weights = [1 / row["variance"] for row in rows]
sum_w = sum(weights)
fixed = sum(w * row["mean_difference"] for w, row in zip(weights, rows)) / sum_w
q = sum(w * (row["mean_difference"] - fixed) ** 2 for w, row in zip(weights, rows))
k = len(rows)
df = k - 1
c = sum_w - sum(w * w for w in weights) / sum_w
tau2 = max(0.0, (q - df) / c)
random_weights = [1 / (row["variance"] + tau2) for row in rows]
random_sum_w = sum(random_weights)
pooled = sum(w * row["mean_difference"] for w, row in zip(random_weights, rows)) / random_sum_w
hk_scale = sum(w * (row["mean_difference"] - pooled) ** 2 for w, row in zip(random_weights, rows)) / df
modified_hk_se = math.sqrt(max(1.0, hk_scale) / random_sum_w)
# Exact Student t quantile for 2 degrees of freedom: F(t)=.5+t/(2 sqrt(t^2+2)).
assert df == 2
y = 2 * .975 - 1
t_critical = math.sqrt(2 * y * y / (1 - y * y))
fixed_se = math.sqrt(1 / sum_w)

# Independent invariance check: reversing arm order must not change North.
north = data["studies"][0]
reverse_arms = list(reversed(north["arms"]))
reverse_mean = sum(a["n"] * a["mean"] for a in reverse_arms) / sum(a["n"] for a in reverse_arms)
assert math.isclose(reverse_mean, rows[0]["active_mean"])
assert sum(row["active_n"] + row["control_n"] for row in rows) == 400
assert math.isclose(rows[0]["mean_difference"], 5.0)

result = {
    "case_id": data["case_id"],
    "runtime": {"python": platform.python_version(), "libraries": "Python standard library: json, math, platform, pathlib"},
    "studies": rows,
    "pooled_random_effects": {"method": "DerSimonian–Laird; modified Hartung–Knapp t interval", "mean_difference": pooled,
        "95_ci": [pooled - t_critical * modified_hk_se, pooled + t_critical * modified_hk_se],
        "tau_squared": tau2, "Q": q, "Q_df": df, "I_squared_percent": max(0.0, (q - df) / q) * 100,
        "hk_scale": hk_scale, "modified_hk_se": modified_hk_se, "t_critical": t_critical},
    "sensitivity_common_effect_normal": {"mean_difference": fixed, "95_ci": [fixed-z*fixed_se, fixed+z*fixed_se]},
    "checks": {"combined_arm_order_invariant": True, "total_unique_participants": 400, "North_effect_arithmetic": 5.0}
}
print(json.dumps(result, indent=2))
