# Secret scrubbers for signal text

Research for wayfinder ticket #156 (map #153, M5 classification), 2026-11-22.
Question: what should replace secrets in signal `title`, `url` and `text` with a
typed marker such as `[secret:aws-key]` during projection? This file reports
facts and measurements. The choice belongs to the spec.

Harness, corpus builder and raw results sit in `docs/research/secret-scrubbers/`
(how to rerun is at the end). Measured on an Apple M5 Max, Python 3.12.16,
one core, `re` from the standard library.

## Short answer

| | Recall (strict) | False-positive windows | Speed per 10,000 chars | Typed marker | Needs |
|---|---|---|---|---|---|
| Hand-written list (v2) | 332/350 = 94.9% | 2 of 624 | 4.6 ms mean, 8.9 p95 | yes, you name them | nothing |
| gitleaks rules, ported to Python | 301/350 = 86.0% | 0 of 624 | 3.7 ms mean, 5.8 p95 | yes, the rule id | one vendored TOML (98 KB, MIT) |
| detect-secrets, file mode, secret value as emitted | 165/350 = 47.1% | 30 of 624 | 10.7 ms mean, 13.3 p95 | yes, 27 plugin names | `pyyaml`, `requests` (Apache-2.0) |
| detect-secrets, file mode, whole-match spans | 194/350 = 55.4% | 33 of 624 | 7.5 ms mean, 8.7 p95 | same | same |
| detect-secrets, adhoc (`scan_line`) mode | 346/350 = 98.9% | 621 of 624 | 31.5 ms mean, 40 p95 | same | same |

- **Recall is strict:** a case counts as caught only when no 10-character run of
  the secret survives in the output. The corpus is 350 fake secrets in 5
  contexts (below), generated at run time.
- **False positives are on 6.2 MB of developer text** in 624 windows of up to
  10,000 characters: 547 windows of this repo's git log, source and docs, the
  rest synthetic UUIDs, hashes, base64, lock files, minified identifiers, URLs
  and terminal logs. Nothing in it is a secret, so every replacement is a false
  positive.
- **The hand-written row is flattering.** I wrote the corpus and the patterns,
  and tuned v2 on v1's false positives on this same corpus. v1, untuned, hit 15
  of 624 windows; every figure is in `results.json`. gitleaks and detect-secrets
  were not tuned.
- **Pure-Python cost of a full rebuild** at 1,000,000 signals (single core):

| Average signal size | hand-written v2 | gitleaks port | detect-secrets (file) |
|---|---|---|---|
| 1,000 chars | 7.7 min | 6.2 min | 11 to 18 min |
| 10,000 chars (the cap, worst case) | 77 min | 62 min | 1.9 to 3 h |

  Scaled linearly from the per-10k means. Titles and URLs are far below 1,000
  chars, so they add little. A normal poll of 100 signals at 5,000 chars is
  about 0.2 s.

## Method

**Corpus, positives** (`corpus.py`, seeded, generated at run time so no
credential-shaped string is committed): 28 secret formats and 2 shapes
(URL credentials, URL query secrets) and a PEM private key, each in up to 4
contexts, 350 cases.

- Formats: AWS access key and secret key, GitHub classic / fine-grained / OAuth,
  OpenAI classic and `sk-proj-`, Anthropic, Slack bot token and webhook, Stripe,
  Google API key, JWT, SendGrid, Twilio, npm, PyPI, GitLab, Hugging Face,
  Telegram, DigitalOcean, Shopify, Linear, Mailchimp, a UUID-shaped key, a
  random password, a 40-hex secret, an opaque bearer token.
- Contexts: `bare` (pasted in a sentence), `assign` (`export NAME=value`),
  `json` (`{"name": "value"}`), `shell` (`curl -H "Authorization: Bearer ..."`),
  `url` (`user:pass@host`, `?token=...&next=...`).
- Five formats carry no prefix (AWS secret key, UUID key, password, hex secret,
  opaque bearer). Only a keyword nearby can reveal them, so `bare` misses on
  those are expected from every candidate.

**Corpus, negatives** (`benign_streams`, pinned to commit `724bef6`):
`git log` in four shapes (full, oneline, `-p`, `--stat`), every tracked source
and markdown file, a `uv.lock` generated from this repo's `pyproject.toml`
(328 KB), synthetic npm `integrity` lines, 700 UUIDs, 1,250 hashes (sha256,
sha1, md5, Docker digests, SSH fingerprints), 100 base64 blobs including data
URIs, minified-JS identifiers, hashed CSS classes, chunk URLs, Xcode
DerivedData paths, URLs with long query strings, request logs, and 20 lines of
keyword look-alikes (`token_count = len(tokens)`, `api_key =
os.environ[...]`, `SECRET_KEY = "changeme"`, `${{ secrets.GITHUB_TOKEN }}`)
repeated 40 times. Cut into 10,000-character windows, the signal cap.

**Both whitespace forms.** `clean_text` collapses whitespace, so a stored
signal is one line. Every run is repeated on the raw text (newlines) and on the
collapsed text. Collapsing changed little: recall identical for every
candidate; false-positive windows identical except detect-secrets, 30 to 22
(fewer line breaks, fewer quoted strings per line). Numbers above are the newline form;
`results.json` has both.

**Timing** is `perf_counter` around one scrub call per window, 624 windows, no
warm-up trimming. Start-up: gitleaks port 23 ms cold (parse TOML, compile 217
rules), detect-secrets 71 ms (imports, plugin setup).

## Hand-written pattern list

What I wrote (`scrubbers.py`, `_HAND` and `_KV`): 28 regexes (provider prefixes
for AWS, GitHub, Anthropic, OpenAI, Slack, Stripe, Google, JWT, SendGrid, Twilio,
npm, PyPI, GitLab, Hugging Face, Telegram, DigitalOcean, Shopify, Linear,
Postman, Mailchimp; plus URL credentials, URL query secrets, `Bearer` and `Basic`
values), PEM private-key blocks (header through `END`, or to the
end of the text when truncated), and one `NAME[:=]value` rule for
names containing `secret|token|password|api_key|...`.

- **Catches:** all prefixed formats in all contexts, URL credentials, URL
  query secrets (11/11, the only candidate to do it in full), the whole PEM
  block. Misses 18 cases: all prefixless formats pasted `bare` (15), plus 3
  `shell` passwords whose symbols (`!#%^&*`) stop the bearer pattern.
- **False positives:**
  - v1, first draft: 15 windows, 260 replacements, 250 of them one synthetic
    pattern, `token_count=3&session=abc...`, where the key rule swallowed
    `3&session=...`.
  - The rest were real code: `{"secrets": CheckOutcome.CANCELLED}`,
    `SECRET_URL = "https://bank.example.com/accounts/4417"`,
    `"1Password": "com.1password.1password"`, `{token.STRING`.
  - v2 added a key-suffix denylist (`_count`, `_id`, `_url`, `_name`, ...), a
    dotted-identifier and `://` exclusion, and a cut at `&name=`. Left: 1
    distinct false positive, `com.1password.1password`, seen in 2 windows
    (git log and source).
- **Cost of that tuning:** a value rule that needs "a digit and a letter, or
  entropy 3.5+" misses short or all-letter passwords (`hunter2` is 7 chars and
  below the 8-char floor). Recall on the `generic-password` kind is 6/12.
- **Gotcha found by the stress run:** my first key pattern began with an
  unbounded `[A-Za-z0-9_.-]*` and took 2.2 s on 10,000 `a` characters
  (quadratic). Bounding it to `{0,40}` brought that to 19 ms. gitleaks bounds
  the same prefix with `{0,50}?` for this reason. Any hand-written
  `key...=value` rule needs the same care, because signal text is untrusted.
- **Typed marker:** native; the label is whatever the pattern is named.
- **Maintenance:** yours. No provider list updates arrive on their own.
- **License / dependencies:** none; standard library.

## gitleaks rule set

gitleaks is a Go binary. Its rules are data: `config/gitleaks.toml` at tag
`v8.30.1` (3,209 lines, 222 `[[rules]]`, MIT, vendored here as `gitleaks.toml`).
I ported the engine in about 120 lines of Python (`GitleaksPort`): lowercase
keyword prefilter, regex, secret group, entropy floor (`<=` rejects), global
and per-rule allowlists (regexes against secret, match or line; stopwords;
`condition`), as described in the config's own comments.

- **Porting cost:** Go RE2 syntax needed translating for 25 rules: mid-pattern
  `(?i)` (Go applies it to the rest of the enclosing group and across `|`,
  Python needs `(?i:...)` and the scope reopened after each `|`), `\z`, and
  `[[:alnum:]]`. 217 of 221 regex rules load. The 4 left out are path-scoped
  (`freemius-secret-key` on `.php`, `hashicorp-tf-password` on `.tf`/`.hcl`,
  `kubernetes-secret-yaml` on `.yaml`/`.yml`, `nuget-config-password` on
  `nuget.config`): they fire only on those file names, and a signal has none. My first two ports differed from the real
  binary (a wrong flag scope and a wrong secret-group choice, 26 cases) and
  the path-scoped rules fired on text with no file name; the final port is
  checked against the binary below.
- **Fidelity check:** the real `gitleaks` 8.30.1 binary, run over the same 350
  cases and 624 windows as files, flags the same 301 cases as the port and
  none of the windows. The port is exactly as accurate as the tool.
- **Catches:** 301/350. Misses, with reasons visible in the rules:
  - Prefixless secrets `bare` (expected), and the generic rule's own
    allowlist and stopwords drop some passwords (`generic-password` 4/12).
  - Rules that are narrower than my fakes: OpenAI needs the `T3BlbkFJ` marker
    (my classic `sk-` fakes lack it, and my `sk-proj-` fakes use 20-character
    segments where the rule wants 58 or 74), Hugging Face is
    letters-only (`[a-z]{34}`; my fakes include digits), Mailchimp and
    Telegram fire only with `mailchimp` / `telegr` nearby. In each case the
    `bare` form is missed and keyword contexts are caught (9/12 for most;
    Telegram 6/12).
  - **URL credentials and query secrets: 0/11.** No rule covers
    `https://user:pass@host`. The generic rule requires the value to be
    followed by a quote, whitespace, `;` or end of text, so
    `?token=VALUE&next=/home` is missed while `?token=VALUE` at the end is
    caught. The binary agrees.
  - Private key blocks: caught, 3/3.
- **False positives:** 0 of 624 windows, with or without whitespace
  collapsing. Entropy floors and the 1,446-word stopword list on the generic rule do the work;
  git SHAs, UUIDs, base64 and lock-file hashes all passed.
- **Speed:** 3.7 ms per 10k chars; the keyword prefilter skips most of the 217
  rules per window. Slowest worst case I could build: 10,000 repeats of
  `curl -H ` took 228 ms (`.*?` inside the curl rule). The real binary scanned
  all 6.2 MB in 0.19 s wall, about 12x faster than the port.
- **Typed marker:** the rule id (`aws-access-token`, `github-pat`,
  `generic-api-key`, ...), 217 stable slugs. Spans come straight from the
  regex group, so replacement is exact.
- **Maintenance:** very active. v8.30.1 released 2026-03-21; last commit
  2026-10-23; not archived; 554 open issues. Updating rules is re-vendoring a
  file and rerunning this harness.
- **License / dependencies:** MIT; Python side needs `tomllib` (3.11+, the
  repo's floor) and `re`.

## detect-secrets (library)

Yelp's `detect-secrets` 1.5.0, run as a library with every plugin enabled and
default filters (`detect_secrets.settings.transient_settings`, plugins from
`get_mapping_from_secret_type_to_class()`), line by line through
`core.scan._scan_line` and `_is_filtered_out`. Those are private functions:
the public `scan_line` hard-wires adhoc mode and discards offsets. Its README
describes the approach as "heuristically crafted regex statements".

- **Plugins:** 27: 21 provider detectors (AWS, Azure, Slack, Stripe, GitHub,
  GitLab, JWT, Telegram, Twilio, ...), `Secret Keyword`, `Basic Auth
  Credentials`, `Private Key`, `Public IP`, and the two entropy plugins
  (`Base64 High Entropy String`, `Hex High Entropy String`). It has no Anthropic,
  Google API key, Hugging Face, Linear, DigitalOcean or Shopify detector; the
  entropy plugins catch some of those only inside quotes.
- **Two modes, very different:**
  - **File mode** (what `detect-secrets scan` does): entropy plugins read only
    quoted strings. Recall 47.1% as emitted.
  - **Adhoc mode** (`scan_line`, the documented library entry): entropy plugins
    also scan unquoted words with `enable_eager_search=True`. Recall 98.9% only
    because it flags nearly everything: 520,155 replacements in 6.2 MB, 621 of
    624 windows hit, the most common "secrets" being `the`, `and`, `None`,
    `import`, `https`. It is unusable on screen text.
- **Output shape problems** (these make recall lower than the plugin list
  suggests, and are why the table has two file-mode rows):
  - Regex plugins return only the capture group as `secret_value`, not the
    match. For a GitHub token that is `ghp`, so scrubbing by `secret_value`
    leaves `[secret:github-token]_E1SkHbn88Hx...`. The whole-match row re-runs the
    plugin's `denylist` regexes to take the full span, which fixes GitHub but
    not the next two.
  - `JSON Web Token`: the regex ends with a lazy `*?`, so it matches
    `header.payload.` and the signature survives (0/12 stripped).
  - `Private Key`: matches the `-----BEGIN ... PRIVATE KEY-----` header line
    only. The base64 body is untouched (0/3).
  - There are no offsets; replacing means `str.replace` of the value, which
    also replaces other occurrences of the same string.
- **False positives:** 30 of 624 windows (22 of 578 collapsed), 509
  replacements. Breakdown: `sha512-...` npm `integrity` strings and base64
  blobs flagged as Base64 High Entropy (325 hits, all in lock-file and blob
  windows); `Secret Keyword` on `password`, `changeme`, `YOUR_API_KEY_HERE` in
  look-alike lines (168); hex strings in tests and git log (`c3a1f0e2d4b69785`, a
  SHA-256 digest literal in a test, 12); `Basic Auth` on `user:pw@` in docs (4); `Public
  IP` on `21.0.13.1`, a version string in a diff (7, whole-match row only).
  UUIDs and git SHAs were not flagged: the `is_potential_uuid` and
  `is_sequential_string` filters work, but its lock-file filter is keyed on a
  file name, which a signal does not have.
- **Speed:** 10.7 ms per 10k chars on newline text and 6.9 on collapsed (the
  plugins run once per line, so many short lines cost more than one long one).
  Start-up 71 ms. About 1.5 to 3 times the cost of the other two.
- **Typed marker:** `secret.type` strings ("AWS Access Key", "Slack Token",
  "Secret Keyword", ...) slugify to usable markers; the entropy plugins' labels
  say nothing about what the secret is.
- **Maintenance:** last release 1.5.0 on 2024-05-06 (two and a half years ago);
  last commit 2026-04-02 (a security-review workflow); not archived; 198 open
  issues. Apache-2.0. Dependencies: `pyyaml`, `requests` (optional extras for
  gibberish and word-list filters, not installed here).

## Cross-cutting facts

- **Line orientation.** detect-secrets is per-line; gitleaks' port and my
  patterns see the whole text. The PEM block and the `generic-api-key`
  terminator rule behave differently once newlines are collapsed. Recall did
  not change on this corpus.
- **Spans, not strings.** For a scrubber that must not leak the tail of a
  token, the useful shape is `(start, end, label)` from a regex group. gitleaks
  and hand-written give that; detect-secrets gives a string that may be a
  fragment.
- **Short-circuit cost.** Both gitleaks (keywords) and hand-written (no
  keyword step) are dominated by regex scanning. A cheap prefilter (is there a
  `-`, `_`, `=`, `:`, `/` near a long token) could cut both; I did not try it.
- **Coverage gaps shared by all three:** prefixless secrets with no keyword
  nearby, passwords shorter than the rules' floors, secrets split across
  lines by accessibility fragments, and anything in an image.

## Not done, not verified

- The corpus holds no real credentials by design, so I cannot say how each
  scrubber handles the formats' real-world variants beyond the shapes the
  providers document. Format shapes were written from memory of the providers'
  public docs, not checked against each provider's current spec.
- The false-positive corpus is this repo plus synthetic text. It has no
  rendered web pages, chat transcripts or PDFs, which `ax-text` signals also
  carry. Any scrubber should be re-measured on a sample of real signals. I did
  not read the live database.
- Real average signal size is unknown to me; the 1,000- and 10,000-character
  rows bracket it.
- One machine, one run; the timing columns are medians of single passes with
  variance of a few percent between my reruns (hand-written 4.5 to 4.9 ms).
- Nothing under `computer_history/` changed; this branch adds only docs.

## Reproduce

```bash
python3.12 -m venv /tmp/ss-venv && /tmp/ss-venv/bin/pip install -r docs/research/secret-scrubbers/requirements.txt
cd /tmp && mkdir lockgen && cp <repo>/pyproject.toml lockgen/ && mkdir lockgen/computer_history && touch lockgen/computer_history/__init__.py && (cd lockgen && uv lock)
cd <repo>/docs/research/secret-scrubbers
/tmp/ss-venv/bin/python run.py --repo <repo> --rev 724bef6d6885c49ff412beb9614ec6d194f9444b \
    --lockfile /tmp/lockgen/uv.lock --json results.json   # needs the gitleaks binary on PATH for the fidelity check
/tmp/ss-venv/bin/python extras.py --json extras.json       # start-up and worst-case inputs
```

Files: `scrubbers.py` (the candidates), `corpus.py` (secrets and benign text),
`run.py`, `extras.py`, `gitleaks.toml` (v8.30.1 rules, MIT), `results.json`,
`extras.json`.

## Sources

- gitleaks rules: https://github.com/gitleaks/gitleaks/blob/v8.30.1/config/gitleaks.toml
  (config comments describe entropy, allowlist, stopword and keyword semantics);
  license https://github.com/gitleaks/gitleaks/blob/v8.30.1/LICENSE (MIT).
- detect-secrets: https://github.com/Yelp/detect-secrets (README, `plugins/`,
  `core/scan.py`, `plugins/base.py`); version 1.5.0 from PyPI; Apache-2.0.
- Repository metadata (release dates, last commit, archived flag, issue
  counts) from the GitHub API on 2026-11-22.
