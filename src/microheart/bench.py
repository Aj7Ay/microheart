"""Small benchmark helpers: percentiles and a one-line summary."""
import math


def percentile(values, p):
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return ordered[k]


def summary(label, seconds):
    ms = [s * 1000 for s in seconds]
    return (f"{label:<34} n={len(ms):<3} min={min(ms):7.0f}  p50={percentile(ms, 50):7.0f}  "
            f"p95={percentile(ms, 95):7.0f}  max={max(ms):7.0f}  (ms)")
