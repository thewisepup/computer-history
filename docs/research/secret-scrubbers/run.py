"""Run every candidate over the corpus: recall, false positives, speed.

    python run.py --repo <checkout> --rev <commit> [--lockfile uv.lock] [--gitleaks-bin gitleaks] \
                  [--json results.json]

Needs `detect-secrets==1.5.0` (see requirements.txt) and Python 3.11+. Secrets are generated at
run time (corpus.py); nothing credential-shaped is stored in the repo.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path

from corpus import WINDOW, benign_streams, collapse, corpus_manifest, secret_cases, windows
from scrubbers import GitleaksPort, candidates


def recover(orig: str, clean: str) -> list[str]:
    """The text each `[secret:x]` marker replaced, found by walking both strings."""
    import re

    parts = re.split(r"\[secret:[a-z0-9-]+\]", clean)
    out, pos = [], 0
    for a, b in zip(parts, parts[1:]):
        s = orig.find(a, pos) + len(a) if a else pos
        e = orig.find(b, s) if b else len(orig)
        out.append(orig[s:e])
        pos = e
    return out


def leaks(needle: str, out: str, k: int = 10) -> bool:
    """True when any k-character run of the secret is still in the output (a partial leak)."""
    return any(needle[i : i + k] in out for i in range(max(1, len(needle) - k + 1)))


def main() -> None:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--rev", required=True)
    ap.add_argument("--lockfile", type=Path)
    ap.add_argument("--gitleaks-bin", default="gitleaks")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()

    cands = candidates()
    cases = secret_cases()
    streams = benign_streams(a.repo, a.rev, a.lockfile)
    res: dict = {"manifest": corpus_manifest(streams), "cases": len(cases), "candidates": {}}
    forms = {"newlines": lambda t: t, "collapsed": collapse}

    for name, fn in cands.items():
        r: dict = {"unported_rules": getattr(getattr(fn, "__self__", None), "unported", [])}
        for form, tf in forms.items():
            f: dict = {}
            # recall
            by_ctx, by_kind = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
            typed = loose = 0
            for c in cases:
                txt = tf(c.text)
                out, labels = fn(txt)
                loose += c.needle not in out
                ok = not leaks(c.needle, out)
                for d, k in ((by_ctx, c.context), (by_kind, c.kind)):
                    d[k][0] += ok
                    d[k][1] += 1
                typed += ok and bool(labels)
            tot = sum(v[0] for v in by_ctx.values())
            f["recall"] = {"removed": tot, "of": len(cases), "pct": round(100 * tot / len(cases), 1)}
            f["recall_loose"] = {"removed": loose, "note": "secret string absent, even if all but a prefix survives"}
            f["recall_by_context"] = {k: f"{v[0]}/{v[1]}" for k, v in by_ctx.items()}
            f["missed_kinds"] = {k: f"{v[0]}/{v[1]}" for k, v in by_kind.items() if v[0] < v[1]}
            # false positives + speed
            fp: dict = {}
            times: list[float] = []
            labels_seen: Counter[str] = Counter()
            examples: dict[str, Counter] = defaultdict(Counter)
            for cat, stream in streams.items():
                ws = windows(tf(stream))
                hit_windows = spans = chars = 0
                for w in ws:
                    t0 = time.perf_counter()
                    out, labels = fn(w)
                    times.append(time.perf_counter() - t0)
                    if labels:
                        hit_windows += 1
                        spans += len(labels)
                        labels_seen.update(labels)
                        for lab, rep in zip(labels, recover(w, out)):
                            chars += len(rep)
                            examples[cat][f"{lab}: {rep[:50]!r}"] += 1
                fp[cat] = {"windows": len(ws), "windows_hit": hit_windows, "replacements": spans, "chars_replaced": chars}
            f["false_positives"] = fp
            f["fp_windows_hit"] = sum(v["windows_hit"] for v in fp.values())
            f["fp_windows"] = sum(v["windows"] for v in fp.values())
            f["fp_replacements"] = sum(v["replacements"] for v in fp.values())
            f["fp_labels"] = labels_seen.most_common(8)
            f["fp_examples"] = {k: v.most_common(4) for k, v in examples.items()}
            f["ms_per_10k_chars"] = {
                "mean": round(1000 * statistics.mean(times), 2),
                "median": round(1000 * statistics.median(times), 2),
                "p95": round(1000 * sorted(times)[int(0.95 * len(times))], 2),
                "max": round(1000 * max(times), 2),
            }
            r[form] = f
        res["candidates"][name] = r
        print(name, r["newlines"]["recall"], r["newlines"]["fp_windows_hit"], r["newlines"]["ms_per_10k_chars"], flush=True)

    res["gitleaks_binary"] = gitleaks_cross_check(a.gitleaks_bin, cases, streams, GitleaksPort())
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res["gitleaks_binary"], indent=1))


def gitleaks_cross_check(binary: str, cases, streams, port: GitleaksPort) -> dict:
    """Run the real gitleaks binary over the same material and compare with the Python port."""
    out: dict = {}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "pos").mkdir()
        for i, c in enumerate(cases):
            (root / "pos" / f"{i:04d}.txt").write_text(c.text)
        (root / "neg").mkdir()
        wins = [(cat, w) for cat, s in streams.items() for w in windows(s)]
        for i, (cat, w) in enumerate(wins):
            (root / "neg" / f"{i:04d}.txt").write_text(w)
        rep = root / "r.json"
        for sub in ("pos", "neg"):
            t0 = time.perf_counter()
            subprocess.run(
                [binary, "dir", str(root / sub), "--no-banner","-f", "json", "-r", str(rep), "--exit-code", "0", "--max-target-megabytes", "5"],
                capture_output=True,
            )
            dt = time.perf_counter() - t0
            findings = json.loads(rep.read_text() or "[]") if rep.exists() else []
            rep.unlink(missing_ok=True)
            files = {Path(f["File"]).name for f in findings}
            if sub == "pos":
                idx = {int(Path(f).stem) for f in files}
                port_idx = {i for i, c in enumerate(cases) if port.scrub(c.text)[1]}
                removed_port = {i for i, c in enumerate(cases) if c.needle not in port.scrub(c.text)[0]}
                out["positives"] = {
                    "binary_files_flagged": len(idx),
                    "port_cases_flagged": len(port_idx),
                    "agree": len(idx & port_idx),
                    "binary_only": len(idx - port_idx),
                    "port_only": len(port_idx - idx),
                    "cases": len(cases),
                }
            else:
                idx = {int(Path(f).stem) for f in files}
                port_idx = {i for i, (cat, w) in enumerate(wins) if port.scrub(w)[1]}
                by_rule = Counter(f["RuleID"] for f in findings)
                out["benign"] = {
                    "binary_windows_flagged": len(idx),
                    "binary_findings": len(findings),
                    "port_windows_flagged": len(port_idx),
                    "agree": len(idx & port_idx),
                    "binary_only": len(idx - port_idx),
                    "port_only": len(port_idx - idx),
                    "windows": len(wins),
                    "binary_top_rules": by_rule.most_common(6),
                    "binary_wall_seconds_incl_startup": round(dt, 2),
                }
    return out


if __name__ == "__main__":
    main()
