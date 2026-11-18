"""Compare flag-off and flag-on measurement runs per app."""

import json
import statistics
import sys
from collections import defaultdict


def load(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def pct(xs, q):
    if not xs:
        return 0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def summarize(rows):
    by_app = defaultdict(list)
    for r in rows:
        by_app[r["app"]].append(r)
    out = {}
    for app, rs in by_app.items():
        walked = [r for r in rs if "bytesTotal" in r]
        cpu = [r["cpuPercent"] for r in rs if "cpuPercent" in r]
        roles = defaultdict(int)
        for r in walked:
            for role, n in r.get("bytesByRole", {}).items():
                roles[role] += n
        out[app] = {
            "ticks": len(rs),
            "median KB": statistics.median([r["bytesTotal"] for r in walked]) / 1000 if walked else 0,
            "p90 KB": pct([r["bytesTotal"] for r in walked], 0.9) / 1000,
            "median ms": statistics.median([r["walkMs"] for r in walked]) if walked else 0,
            "p90 ms": pct([r["walkMs"] for r in walked], 0.9),
            "over 2s": sum(not r["finishedWithin2s"] for r in walked),
            "over 50KB": sum(r["over50KB"] for r in walked),
            "timeouts": sum(r["timeouts"] for r in walked),
            "no window": sum("noWindow" in r for r in rs),
            "mean CPU %": statistics.mean(cpu) if cpu else None,
            "flag already on": any(r.get("flagAlreadyOn") for r in rs),
            "top roles": sorted(roles.items(), key=lambda kv: -kv[1])[:5],
        }
    return out


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.1f}"
    return str(v)


def main():
    runs = {}
    for path in sys.argv[1:]:
        rows = load(path)
        mode = rows[0]["mode"] if rows else path
        runs[mode] = summarize(rows)
    apps = sorted({a for s in runs.values() for a in s})
    cols = ["ticks", "median KB", "p90 KB", "median ms", "p90 ms", "over 2s", "over 50KB",
            "timeouts", "no window", "mean CPU %", "flag already on"]
    for app in apps:
        print(f"\n## {app}")
        print("| | " + " | ".join(runs) + " |")
        print("|---|" + "---|" * len(runs))
        for c in cols:
            print(f"| {c} | " + " | ".join(fmt(runs[m].get(app, {}).get(c)) for m in runs) + " |")
        for m in runs:
            top = runs[m].get(app, {}).get("top roles", [])
            print(f"\ntop roles ({m}): " + ", ".join(f"{r} {n // 1000}KB" for r, n in top))


if __name__ == "__main__":
    main()
