"""Start-up cost and worst-case inputs for each candidate.

    python extras.py [--json extras.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import scrubbers as s

STRESS = {
    "10k of 'a'": "a" * 10_000,
    "10k of 'key=' repeated": "key=" * 2_500,
    "10k of 'curl -H ' repeated": "curl -H " * 1_250,
    "10k of 'token: ' repeated": "token: " * 1_430,
    "10k base64 alphabet no spaces": ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/" * 160)[:10_000],
    "10k of quoted words": '"abc" ' * 1_660,
    "10k hex digits": "0123456789abcdef" * 625,
    "10k of '-----BEGIN PRIVATE KEY-----' with no end": "-----BEGIN PRIVATE KEY-----\n" + "A" * 9_900,
    "10k of 'password' repeated": "password " * 1_100,
}


def main() -> None:
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    out: dict = {"python": sys.version.split()[0], "startup_ms": {}, "stress_ms": {}}

    t = time.perf_counter()
    gl = s.GitleaksPort()
    out["startup_ms"]["gitleaks-port (parse TOML + compile 221 rules, cold)"] = round(1000 * (time.perf_counter() - t))
    t = time.perf_counter()
    s.GitleaksPort()
    out["startup_ms"]["gitleaks-port (second construction)"] = round(1000 * (time.perf_counter() - t))
    t = time.perf_counter()
    import re

    out["startup_ms"]["hand-written (import-time compile, already done)"] = 0
    t = time.perf_counter()
    ds = s.DetectSecrets("file", True)
    out["startup_ms"]["detect-secrets (import + settings + plugins)"] = round(1000 * (time.perf_counter() - t))

    fns = {
        "hand-written v2": s.handwritten_v2,
        "gitleaks-port": gl.scrub,
        "detect-secrets (file mode)": ds.scrub,
    }
    for name, text in STRESS.items():
        for cname, fn in fns.items():
            t = time.perf_counter()
            fn(text)
            out["stress_ms"].setdefault(name, {})[cname] = round(1000 * (time.perf_counter() - t), 1)
    print(json.dumps(out, indent=1))
    if a.json:
        a.json.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
