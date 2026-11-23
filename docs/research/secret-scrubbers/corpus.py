"""The corpus: fake secrets in real formats, and realistic developer text with none.

Every secret is generated at run time from a seeded RNG, so no credential-shaped string is
committed (the gitleaks pre-commit hook would rightly object) and no secret is real.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import string
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

WINDOW = 10_000  # the signal text cap


def collapse(text: str) -> str:
    """What `computer_history.text.clean_text` does to whitespace."""
    return " ".join(text.split())


# ------------------------------------------------------------------ secrets


@dataclass
class Case:
    kind: str  # format name
    context: str  # bare | assign | json | shell | url
    text: str  # snippet containing the secret
    secret: str  # the value that must not survive scrubbing
    needle: str  # substring whose absence proves it was removed (PEM: one body line)


def _alnum(r: random.Random, n: int, alphabet: str = string.ascii_letters + string.digits) -> str:
    return "".join(r.choice(alphabet) for _ in range(n))


def _hex(r: random.Random, n: int) -> str:
    return "".join(r.choice("0123456789abcdef") for _ in range(n))


def _b64url(r: random.Random, nbytes: int) -> str:
    return base64.urlsafe_b64encode(r.randbytes(nbytes)).decode().rstrip("=")


def _jwt(r: random.Random) -> str:
    h = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip("=")
    p = base64.urlsafe_b64encode(
        json.dumps({"sub": _hex(r, 8), "name": "Test User", "iat": 1700000000}).encode()
    ).decode().rstrip("=")
    return f"{h}.{p}.{_b64url(r, 32)}"


def _pem(r: random.Random) -> tuple[str, str]:
    body = [base64.b64encode(r.randbytes(48)).decode() for _ in range(12)]
    return "-----BEGIN RSA PRIVATE KEY-----\n" + "\n".join(body) + "\n-----END RSA PRIVATE KEY-----", body[3]


# name -> (generator, env var name used in assign/json/shell contexts)
SECRETS: dict[str, tuple] = {
    "aws-access-key": (lambda r: "AKIA" + _alnum(r, 16, "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"), "AWS_ACCESS_KEY_ID"),
    "aws-secret-key": (lambda r: _alnum(r, 40, string.ascii_letters + string.digits + "/+"), "AWS_SECRET_ACCESS_KEY"),
    "github-pat-classic": (lambda r: "ghp_" + _alnum(r, 36), "GITHUB_TOKEN"),
    "github-pat-fine": (lambda r: "github_pat_" + _alnum(r, 22) + "_" + _alnum(r, 59), "GH_TOKEN"),
    "github-oauth": (lambda r: "gho_" + _alnum(r, 36), "GITHUB_OAUTH"),
    "openai-classic": (lambda r: "sk-" + _alnum(r, 48), "OPENAI_API_KEY"),
    "openai-project": (lambda r: "sk-proj-" + _alnum(r, 20) + "T3BlbkFJ" + _alnum(r, 20), "OPENAI_API_KEY"),
    "anthropic": (lambda r: "sk-ant-api03-" + _alnum(r, 93, string.ascii_letters + string.digits + "_-") + "AA", "ANTHROPIC_API_KEY"),
    "slack-bot": (lambda r: f"xoxb-{r.randint(10**11, 10**12)}-{r.randint(10**11, 10**12)}-{_alnum(r, 24)}", "SLACK_BOT_TOKEN"),
    "slack-webhook": (lambda r: f"https://hooks.slack.com/services/T{_alnum(r, 8, string.ascii_uppercase + string.digits)}/B{_alnum(r, 10, string.ascii_uppercase + string.digits)}/{_alnum(r, 24)}", "SLACK_WEBHOOK_URL"),
    "stripe-live": (lambda r: "sk_live_" + _alnum(r, 24), "STRIPE_SECRET_KEY"),
    "google-api": (lambda r: "AIza" + _alnum(r, 35, string.ascii_letters + string.digits + "_-"), "GOOGLE_API_KEY"),
    "jwt": (_jwt, "ACCESS_TOKEN"),
    "sendgrid": (lambda r: "SG." + _alnum(r, 22, string.ascii_letters + string.digits + "_-") + "." + _alnum(r, 43, string.ascii_letters + string.digits + "_-"), "SENDGRID_API_KEY"),
    "twilio": (lambda r: "SK" + _hex(r, 32), "TWILIO_API_KEY"),
    "npm": (lambda r: "npm_" + _alnum(r, 36), "NPM_TOKEN"),
    "pypi": (lambda r: "pypi-AgEIcHlwaS5vcmc" + _alnum(r, 70, string.ascii_letters + string.digits + "_-"), "PYPI_TOKEN"),
    "gitlab": (lambda r: "glpat-" + _alnum(r, 20, string.ascii_letters + string.digits + "_-"), "GITLAB_TOKEN"),
    "huggingface": (lambda r: "hf_" + _alnum(r, 34), "HF_TOKEN"),
    "telegram": (lambda r: f"{r.randint(10**9, 10**10 - 1)}:AA" + _alnum(r, 33, string.ascii_letters + string.digits + "_-"), "TELEGRAM_BOT_TOKEN"),
    "digitalocean": (lambda r: "dop_v1_" + _hex(r, 64), "DIGITALOCEAN_TOKEN"),
    "shopify": (lambda r: "shpat_" + _hex(r, 32), "SHOPIFY_ACCESS_TOKEN"),
    "linear": (lambda r: "lin_api_" + _alnum(r, 40), "LINEAR_API_KEY"),
    "mailchimp": (lambda r: _hex(r, 32) + "-us12", "MAILCHIMP_API_KEY"),
    "heroku-uuid-key": (lambda r: str(uuid.UUID(int=r.getrandbits(128), version=4)), "HEROKU_API_KEY"),
    "generic-password": (lambda r: _alnum(r, 14, string.ascii_letters + string.digits + "!#%^&*"), "DB_PASSWORD"),
    "generic-hex-secret": (lambda r: _hex(r, 40), "CLIENT_SECRET"),
    "opaque-bearer": (lambda r: _alnum(r, 40), "AUTH_TOKEN"),
}

# kinds whose format carries no prefix: only a keyword in context can reveal them
PREFIXLESS = {"aws-secret-key", "heroku-uuid-key", "generic-password", "generic-hex-secret", "opaque-bearer"}


def secret_cases(seed: int = 7, per: int = 3) -> list[Case]:
    r = random.Random(seed)
    cases: list[Case] = []
    for kind, (gen, var) in SECRETS.items():
        for _ in range(per):
            v = gen(r)
            lower = var.lower()
            ctxs = {
                "bare": f"I pasted the value {v} into the chat by mistake, can you rotate it?",
                "assign": f"export {var}={v}",
                "json": json.dumps({lower: v, "region": "us-east-1"}),
                "shell": f'curl -s -H "Authorization: Bearer {v}" https://api.example.com/v1/me',
            }
            for ctx, text in ctxs.items():
                cases.append(Case(kind, ctx, text, v, v))
    for _ in range(per):
        v = _alnum(r, 20)
        for pre in ("https", "postgres"):
            cases.append(Case("url-credential", "url", f"git clone {pre}://octocat:{v}@example.com/org/repo.git", v, v))
    for q in ("token", "access_token", "api_key", "key", "sig"):
        v = _alnum(r, 32)
        cases.append(Case("url-query", "url", f"https://app.example.com/callback?state=ok&{q}={v}&next=/home", v, v))
    for _ in range(per):
        pem, line = _pem(r)
        cases.append(Case("private-key", "bare", f"cat id_rsa\n{pem}\n$ ", pem, line))
    return cases


# ------------------------------------------------------------------- benign


def _run(args: list[str], cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False).stdout


def benign_streams(repo: Path, rev: str, lockfile: Path | None, seed: int = 11) -> dict[str, str]:
    """Category -> text. Nothing here is a secret; every detection is a false positive."""
    r = random.Random(seed)
    s: dict[str, str] = {}

    s["git-log"] = "\n".join(
        [
            _run(["git", "log", "-n", "400", "--format=fuller", rev], repo),
            _run(["git", "log", "-n", "400", "--oneline", rev], repo),
            _run(["git", "log", "-n", "30", "-p", rev], repo),
            _run(["git", "log", "-n", "60", "--stat", rev], repo),
        ]
    )

    files = _run(["git", "ls-tree", "-r", "--name-only", rev], repo).split("\n")
    code = [f for f in files if f.endswith((".py", ".swift", ".sql", ".sh", ".toml", ".yml", ".yaml"))]
    docs = [f for f in files if f.endswith(".md")]
    rd = lambda fs: "\n".join(_run(["git", "show", f"{rev}:{f}"], repo) for f in fs if f)
    s["source-code"] = rd(code)
    s["markdown-docs"] = rd(docs)

    lock = [lockfile.read_text()] if lockfile and lockfile.is_file() else []
    npm = "\n".join(
        f'    "node_modules/{_alnum(r, 8, string.ascii_lowercase)}": {{\n      "version": "{r.randint(1,9)}.{r.randint(0,30)}.{r.randint(0,9)}",\n'
        f'      "resolved": "https://registry.npmjs.org/x/-/x-1.0.0.tgz",\n      "integrity": "sha512-{base64.b64encode(r.randbytes(64)).decode()}"\n    }},'
        for _ in range(250)
    )
    s["lockfiles"] = "\n".join(lock + [npm])

    s["uuids"] = "\n".join(
        f'{{"session_id": "{uuid.UUID(int=r.getrandbits(128), version=4)}", "request_id": "{uuid.UUID(int=r.getrandbits(128), version=4)}", "ts": {1700000000 + i}}}'
        for i in range(400)
    ) + "\n" + "\n".join(f"INFO trace_id={uuid.UUID(int=r.getrandbits(128), version=4)} span=ok" for i in range(300))

    s["hashes"] = "\n".join(
        f"{hashlib.sha256(r.randbytes(8)).hexdigest()}  file{i}.tar.gz\n"
        f"{hashlib.sha1(r.randbytes(8)).hexdigest()} commit {i}\n"
        f"md5: {hashlib.md5(r.randbytes(8)).hexdigest()}\n"
        f"Digest: sha256:{hashlib.sha256(r.randbytes(8)).hexdigest()}\n"
        f"SHA256:{base64.b64encode(hashlib.sha256(r.randbytes(8)).digest()).decode().rstrip('=')} (ED25519)"
        for i in range(250)
    )

    s["base64-blobs"] = "\n".join(
        [
            f'<img src="data:image/png;base64,{base64.b64encode(r.randbytes(r.choice([200, 800, 3000]))).decode()}">'
            for _ in range(20)
        ]
        + [
            f'const payload = "{base64.b64encode(r.randbytes(r.randint(30, 300))).decode()}";\nvalue: {base64.b64encode(r.randbytes(40)).decode()}'
            for _ in range(80)
        ]
    )

    ident = lambda n: _alnum(r, n, string.ascii_letters)
    s["minified-and-ids"] = "\n".join(
        [
            "function " + ident(2) + "(e,t){return e." + ident(14) + "(t)||this." + ident(22) + "[t]}var " + ident(30) + "=window." + ident(26) + "||{};"
            for _ in range(250)
        ]
        + [f"<div class=\"css-{_alnum(r, 6)} {ident(18)}-{_alnum(r, 5)}\">" for _ in range(150)]
        + [f"https://cdn.example.com/_next/static/chunks/{_hex(r, 8)}-{_hex(r, 16)}.js?v={_hex(r, 10)}" for _ in range(150)]
        + [f"/Users/dev/Library/Developer/Xcode/DerivedData/App-{_alnum(r, 28, string.ascii_lowercase)}/Build/Products/Debug/App.app" for _ in range(100)]
        + [f"com.apple.{ident(12)}.{ident(16)}-{_hex(r, 8)}" for _ in range(100)]
    )

    s["urls-and-queries"] = "\n".join(
        f"https://example.com/search?q={ident(8)}+{ident(6)}&page={i}&utm_source=newsletter&utm_campaign={ident(14)}&ref={_hex(r, 12)}&sort=desc&key=title&token_count={i}&session={_hex(r, 16)}"
        for i in range(250)
    )

    s["terminal"] = "\n".join(
        [
            _run(["git", "log", "-n", "80", "--graph", "--format=%h %d %s", rev], repo),
        ]
        + [f"[{i:04d}] INFO request id={_alnum(r, 12)} user=u{r.randint(1, 99)} took={r.randint(1, 900)}ms status=200 bytes={r.randint(10, 99999)}" for i in range(300)]
    )

    s["keyword-lookalikes"] = "\n".join(
        [
            'token_count = len(tokens)',
            'api_key = os.environ["OPENAI_API_KEY"]',
            'password_field = "password"',
            'SECRET_KEY = "changeme"',
            'password: ${DB_PASSWORD}',
            'auth_token = request.headers.get("Authorization")',
            "secret_name: my-app-secret",
            '"apiKey": "YOUR_API_KEY_HERE"',
            "key_length = 4096",
            "def get_access_token(self) -> str:",
            "max_tokens=1024, temperature=0.2",
            "keyboard_shortcut_key: cmd+shift+p",
            "primary_key INTEGER PRIMARY KEY AUTOINCREMENT",
            "export const authToken = useAuthToken();",
            "Token usage: 12,403 input / 981 output",
            "git remote add origin https://github.com/thewisepup/computer-history.git",
            "password=$(security find-generic-password -s foo -w)",
            "secret: ${{ secrets.GITHUB_TOKEN }}",
            "Authorization: Bearer ${TOKEN}",
            "curl -H 'X-Api-Key: $API_KEY' https://example.com",
        ]
        * 40
    )
    return s


def windows(stream: str, size: int = WINDOW) -> list[str]:
    return [stream[i : i + size] for i in range(0, len(stream), size) if len(stream[i : i + size]) > size // 2]


def corpus_manifest(streams: dict[str, str]) -> dict:
    return {
        k: {"chars": len(v), "windows": len(windows(v)), "sha256": hashlib.sha256(v.encode()).hexdigest()[:16]}
        for k, v in streams.items()
    }
