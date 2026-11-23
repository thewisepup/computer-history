# OpenRouter models for classification under $20/month

Research for wayfinder ticket #155 (map #153), read 2026-11-22. Facts only:
the model pick belongs to #158.

Every price, endpoint and capability below was read on **2026-11-22** from
OpenRouter's public API (`GET https://openrouter.ai/api/v1/models`,
`GET https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints`,
`GET https://openrouter.ai/api/v1/endpoints/zdr`) and its docs. OpenRouter
passes provider prices through with no inference markup; buying credits costs
5.5% ($0.80 minimum)
([faq](https://openrouter.ai/docs/faq.md#pricing-and-fees)). The monthly
figures below exclude that fee. Prices and endpoint lists change; re-read
before building.

## The task, as costed

- 6 windows per call, shared prompt (instructions, project and work-type
  lists, schema) counted once per call.
- Input per window X is 1K, 3K or 6K tokens; output is about 150 tokens per
  window. 30-day month.
- **Assumption (mine, not the ticket's):** the shared prompt is 1,500 tokens
  per call, on top of the 6 windows' content. It moves the totals by 1-5%
  (see "Sensitivity"), so the table is not fragile to it.
- 5-minute windows cap out at 288 a day, so the "300 active windows a day"
  column is slightly above what 24 hours can hold; read it as the ceiling.

## Candidates

Ten models across seven vendors. Prices are $ per million tokens at the
model's listed (standard-tier) rate. "Cache read" is the discounted rate for
the repeated prompt prefix.

| Model | Input | Output | Cache read | Cache write | Context | Max out |
|---|---|---|---|---|---|---|
| `openai/gpt-oss-120b` | 0.05 | 0.25 | 0.05 | none | 131,072 | 117,964 |
| `deepseek/deepseek-v4-flash` | 0.09 | 0.18 | 0.018 | none | 1,048,576 | 393,216 |
| `anthropic/claude-haiku-5.5` | 0.10 | 0.50 | 0.01 | 0.125 (5 min), 0.20 (1 h) | 1,000,000 | 128,000 |
| `openai/gpt-6-luna` | 0.10 | 0.50 | 0.01 | 0.125 | 1,050,000 | 128,000 |
| `qwen/qwen3.8-flash` | 0.15 | 0.47 | 0.016 | 0.20 (Alibaba main endpoint only) | 1,000,000 | 131,072 |
| `mistralai/mistral-small-2603` | 0.15 | 0.60 | 0.015 | none | 262,144 | 209,715 |
| `google/gemini-3.1-flash-lite` | 0.25 | 1.50 | 0.025 | 0.083 | 1,048,576 | 65,536 |
| `openai/gpt-5.4-mini` | 0.75 | 4.50 | 0.075 | none | 400,000 | 128,000 |
| `google/gemini-3.6-flash` | 0.75 | 3.75 | 0.075 | 0.042 | 1,048,576 | 65,536 |
| `anthropic/claude-sonnet-5.5` | 2.00 | 10.00 | 0.10 | 2.50 (5 min), 4.00 (1 h) | 1,000,000 | 128,000 |

Source: `/api/v1/models` `pricing` and `context_length` fields (read
2026-11-22). Notes:

- Haiku 5.5 and gpt-6-luna reprice above 100K and 272K prompt tokens
  respectively (`pricing.overrides`); irrelevant at 1-6K per window.
- `gpt-oss-120b` and `deepseek-v4-flash` have many hosts at different
  prices. The row is the model's headline price; ranges are in the next
  section.
- Gemini's `pricing` also lists `internal_reasoning` at the output rate, so
  thinking tokens bill as output on the Google models. Whether the other
  candidates bill hidden reasoning as output, and how many tokens each
  emits by default on this task, I did not measure.
- Each candidate's `supported_parameters` includes `structured_outputs` and
  `response_format` at the model level.

### Endpoint price range (cheapest to dearest, standard tier)

| Model | Range across hosts |
|---|---|
| `gpt-oss-120b` | 0.03/0.15 (Near AI) to 0.35/0.75 (Cerebras); 23 hosts |
| `deepseek-v4-flash` | 0.0146/0.029 (Baidu) to 0.21/0.56 (Azure); 13 endpoints |
| `gemini-3.1-flash-lite` | flex 0.125/0.75, standard 0.25/1.50, priority 0.45/2.70 |
| `gemini-3.6-flash` | flex 0.375/1.875, standard 0.75/3.75, priority 1.35/6.75 |
| `gpt-6-luna` | flex 0.05/0.25, standard 0.10/0.50, fast 0.20/1.00 |
| `gpt-5.4-mini` | flex 0.375/2.25, standard 0.75/4.50, fast 1.50/9.00 |
| Anthropic, Qwen, Mistral | one price across endpoints (Mistral: 0.15/0.60 on `mistral/zdr`, 0.165/0.66 on eu/us) |

Source: per-model `/endpoints` calls, 2026-11-22. Flex tiers are "lower
price, lower processing priority"
([service tiers](https://openrouter.ai/docs/guides/features/service-tiers.md));
a background classifier could tolerate that, but I did not test latency.

OpenRouter also lists `:batch` variants at roughly half price (for example
`anthropic/claude-haiku-5.5:batch` 0.05/0.25) through the Batch API, which has
a 24 h completion window as the only option
([batch quickstart](https://openrouter.ai/docs/batch-quickstart.md)). I did
not verify how batches interact with ZDR or `data_collection` routing, and
the monthly table does not use batch prices.

## Monthly cost

Formula, per month: `windows/day x 30 x X x in_price` for window content,
plus `windows/day / 6 x 30 x 1,500 x in_price` for the shared prompt, plus
`windows/day x 30 x 150 x out_price`. No caching, standard tier, listed
price, no 5.5% credit fee, no hidden reasoning tokens.

Legend: **bold** fits $5/month; plain fits $20/month; ~~struck~~ exceeds $20.

| Model | 100/d 1K | 100/d 3K | 100/d 6K | 200/d 1K | 200/d 3K | 200/d 6K | 300/d 1K | 300/d 3K | 300/d 6K |
|---|---|---|---|---|---|---|---|---|---|
| `gpt-oss-120b` | **$0.30** | **$0.60** | **$1.05** | **$0.60** | **$1.20** | **$2.10** | **$0.90** | **$1.80** | **$3.15** |
| `deepseek-v4-flash` | **$0.42** | **$0.96** | **$1.77** | **$0.84** | **$1.92** | **$3.54** | **$1.26** | **$2.88** | $5.31 |
| `claude-haiku-5.5` | **$0.60** | **$1.20** | **$2.10** | **$1.20** | **$2.40** | **$4.20** | **$1.80** | **$3.60** | $6.30 |
| `gpt-6-luna` | **$0.60** | **$1.20** | **$2.10** | **$1.20** | **$2.40** | **$4.20** | **$1.80** | **$3.60** | $6.30 |
| `qwen3.8-flash` | **$0.77** | **$1.67** | **$3.02** | **$1.55** | **$3.35** | $6.05 | **$2.32** | $5.02 | $9.07 |
| `mistral-small-2603` | **$0.83** | **$1.73** | **$3.08** | **$1.67** | **$3.46** | $6.17 | **$2.50** | $5.20 | $9.25 |
| `gemini-3.1-flash-lite` | **$1.61** | **$3.11** | $5.36 | **$3.23** | $6.22 | $10.72 | **$4.84** | $9.34 | $16.09 |
| `gpt-5.4-mini` | **$4.84** | $9.34 | $16.09 | $9.68 | $18.68 | ~~$32.17~~ | $14.51 | ~~$28.01~~ | ~~$48.26~~ |
| `gemini-3.6-flash` | **$4.50** | $9.00 | $15.75 | $9.00 | $18.00 | ~~$31.50~~ | $13.50 | ~~$27.00~~ | ~~$47.25~~ |
| `claude-sonnet-5.5` | $12.00 | ~~$24.00~~ | ~~$42.00~~ | ~~$24.00~~ | ~~$48.00~~ | ~~$84.00~~ | ~~$36.00~~ | ~~$72.00~~ | ~~$126.00~~ |

Reading it:

- **Fit $5 at every volume and size in the grid:** `gpt-oss-120b`
  (max $3.15).
- **Fit $5 except 300/day at 6K:** `deepseek-v4-flash` ($5.31 there).
- **Fit $20 everywhere in the grid; $5 where noted:**
  - `claude-haiku-5.5`, `gpt-6-luna` (max $6.30): $5 up to 200/day at 6K and
    300/day at 3K.
  - `qwen3.8-flash` (max $9.07): $5 up to 200/day at 3K and 300/day at 1K.
  - `mistral-small-2603` (max $9.25): the same $5 cells as Qwen.
- `gemini-3.1-flash-lite` fits $20 everywhere (max $16.09); $5 only at 1K
  per window, or 100/day at 3K.
- `gpt-5.4-mini` and `gemini-3.6-flash` fit $20 at 100/day (any size), at
  200/day up to 3K ($18.68, $18.00), and at 300/day only at 1K; $5 only at
  100/day and 1K.
- `claude-sonnet-5.5` fits $20 only at 100/day and 1K ($12.00); never $5.

Daily window count each model affords at 3K per window, $20 / $5 per month:
gpt-oss-120b 3,333 / 833; deepseek-v4-flash 2,086 / 521; haiku-5.5 and
gpt-6-luna 1,666 / 416; qwen3.8-flash 1,194 / 298; mistral-small 1,154 /
288; gemini-3.1-flash-lite 642 / 160; gpt-5.4-mini 214 / 53; gemini-3.6-flash
222 / 55; sonnet-5.5 83 / 20.

### Sensitivity

- **Shared prompt size.** Dropping the 1,500-token shared prompt entirely
  moves 300/day at 6K by under 4% for every model (for example Haiku $6.30
  to $6.08).
- **Caching the shared prompt.** Pricing the 1,500 shared tokens at the
  cache-read rate saves 1-5% (Haiku, 200/day at 3K: $2.40 to $2.27), because
  window content, not the shared prompt, dominates. Caching also needs the
  next call to arrive inside the cache's life: Anthropic's default TTL is 5
  minutes, Gemini's implicit cache averages 3-5 minutes
  ([prompt caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching.md)),
  and 6 five-minute windows span 30 minutes, so if calls are made as
  windows close the prefix will have expired between calls; caching helps
  mainly when a backlog is classified back to back.
- **Hidden reasoning output.** The table counts 150 output tokens a window.
  A model that emits 1,000 reasoning tokens per window at $0.50/M adds
  $4.50/month at 300/day; at Sonnet's $10/M it adds $90/month. I did not
  measure reasoning tokens per candidate.
- **Credit fee.** Add 5.5% to anything actually paid.

## Prompt caching

Source: [OpenRouter prompt caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching.md),
read 2026-11-22.

| Vendor | How | Read / write price vs input |
|---|---|---|
| Anthropic (Haiku 5.5, Sonnet 5.5) | `cache_control` breakpoint or top-level `cache_control`; minimum 512 tokens for these two; 5 min TTL, 1 h optional | read 0.1x, write 1.25x (5 min) or 2x (1 h) |
| OpenAI (gpt-6-luna, gpt-5.4-mini) | automatic, 1,024-token minimum; GPT-5.6 and later also charge writes at 1.25x | read per model (0.1x on luna and 5.4-mini per the API) |
| Google (Gemini) | implicit, plus `cache_control` breakpoints for explicit; 5 min TTL on explicit writes; docs state minimums for 2.5 models (1,024 Flash) and I did not find one for 3.x | read 0.1x here per the API fields (the docs text says 0.25x, written for 2.5) |
| DeepSeek | automatic | read 0.2x per the API (0.018 on 0.09); docs text says 0.1x |
| Alibaba Qwen | explicit `cache_control` only on listed models; `qwen3.8-flash` is not in the docs' list, yet the `alibaba` endpoint lists a cache write price and `alibaba/us-east-1` reports implicit caching | read 0.1x |
| Mistral, gpt-oss-120b hosts | endpoint metadata reports implicit caching on most hosts (`supports_implicit_caching`); no OpenRouter doc section | read prices per endpoint (Mistral 0.1x; gpt-oss hosts 0.5x to 1.0x) |

Where the docs text and the API fields disagree, I list the API field (the
price actually charged) and say so. Sticky routing sends later requests to
the same provider after a cache hit, and `session_id` forces it; a manual
`provider.order` turns sticky routing off.

## Structured output (strict JSON schema)

Source: [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs.md)
and per-endpoint `supported_parameters` from `/endpoints`, read 2026-11-22.

- Request shape: `response_format: {type: "json_schema", json_schema: {name,
  strict: true, schema}}` on Chat Completions.
- OpenRouter says support is **per endpoint, not per model**. To force
  routing only to endpoints that support it, set
  `provider.require_parameters: true`. Without it, a request can reach an
  endpoint that silently ignores `response_format`
  ([provider routing](https://openrouter.ai/docs/guides/routing/provider-selection.md)).
- "Supports `structured_outputs`" is not "guarantees schema-valid output":
  the docs say enforcement varies by provider, and some translate the schema
  or treat it as a strong hint. I did not run any call, so no candidate's
  validity rate is measured here.

Endpoints that list `structured_outputs` (SO) in `supported_parameters`:

| Model | SO on | Not SO |
|---|---|---|
| haiku-5.5 / sonnet-5.5 | Anthropic, Google Vertex, Azure | Amazon Bedrock, Claude Platform on AWS (`response_format` only) |
| gpt-6-luna | all 5 (OpenAI incl. flex/fast, Bedrock, Azure) | none |
| gpt-5.4-mini | all 4 (OpenAI incl. flex/fast, Azure) | none |
| gemini-3.1-flash-lite, 3.6-flash | all 6 (AI Studio and Vertex, all tiers) | none |
| deepseek-v4-flash | 10 of 13: Baidu, StreamLake, Fireworks, DeepInfra x3, Wafer, Venice, Parasail, Mancer | Relace, SiliconFlow, Azure |
| qwen3.8-flash | both Alibaba endpoints | none |
| mistral-small-2603 | all 3 Mistral endpoints | none |
| gpt-oss-120b | most hosts | Venice, DigitalOcean, SambaNova, Bedrock (both), no `response_format` at all |

## Context window and rate limits

- Context windows are in the candidates table. At 1-6K per window x 6 plus
  the shared prompt, a call is at most about 38K tokens, so every candidate
  has room; `gpt-oss-120b` (131K) is the smallest.
- **Rate limits:** OpenRouter documents rate limits only for `:free`
  models (20 requests/minute; 50/day below $10 of all-time credits, 1,000/day
  at $10 or more), key-management calls (10,000/day), per-IP bursts on the
  key and credits endpoints, and DDoS protection
  ([limits](https://openrouter.ai/docs/api-reference/limits.md), read
  2026-11-22). Paid models have no documented per-key requests-per-minute
  cap; a 429 comes from the upstream provider, and OpenRouter retries other
  providers for the same model. Creating more keys does not raise limits,
  since capacity is governed globally. Load here is at most 50 calls a day,
  far below any of this.
- One quirk: an "in-flight spending budget" can reject a request with 402
  when the estimated cost of running and recently completed requests exceeds
  a fraction of the balance; it applies only to some prepaid accounts below a
  balance threshold the docs don't give. Whether this account would be
  subject to it is not confirmed.

## Data handling

Sources: [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection.md),
[ZDR](https://openrouter.ai/docs/guides/features/zdr.md),
[provider logging](https://openrouter.ai/docs/guides/privacy/provider-logging.md),
the live ZDR endpoint list `GET /api/v1/endpoints/zdr` (934 endpoints), all
read 2026-11-22.

The controls, from loosest to strictest:

1. `provider.data_collection: "deny"` (per request, or the account-wide
   privacy setting): use only providers that "do not collect user data".
   Default is `allow`. The docs call the data-policy tags "not a definitive
   source".
2. `provider.zdr: true` (per request), or ZDR enforced in privacy settings
   or a guardrail: route only to Zero Data Retention endpoints. In-memory
   caching does not count as retention, so implicit-caching endpoints stay
   eligible.
3. Policy tiers: **ZDR** (no routine storage), **Safety Retention** (not
   trained on, but the provider may keep any request to detect abuse), and
   **Retention and Training**. Self-serve accounts default to allowing Safety
   Retention under ZDR; enterprise accounts default to ZDR only. It is chosen
   separately for Google models and all other models.
4. OpenRouter's ZDR page announces a change planned for 2026-10-27 (its
   banner still says "planned" on 2026-11-22): every request, including ZDR
   traffic, is screened for CSAM in flight, and flagged content may be kept
   for review and legal preservation
   ([ZDR page](https://openrouter.ai/docs/guides/features/zdr.md)). That is a
   stated exception to "no retention" on OpenRouter's side.
5. BYOK with a ZDR declaration on the key, for a provider agreement you hold
   yourself. Not costed here.

`provider.zdr` filters the candidate pool, so fallbacks stay inside the ZDR
set (per the routing docs' description of `zdr` as a restriction).

**Which candidates have ZDR endpoints (from the ZDR list):**

| Model | ZDR endpoints (tag) | Safety Retention flag | SO on the ZDR ones |
|---|---|---|---|
| `claude-haiku-5.5`, `claude-sonnet-5.5` | `google-vertex/global`, `amazon-bedrock` (not first-party Anthropic) | no | Vertex yes; Bedrock no |
| `gpt-6-luna`, `gpt-5.4-mini` | `azure` only (not first-party OpenAI) | no | yes |
| `gemini-3.1-flash-lite`, `gemini-3.6-flash` | Vertex only (`global`, `flex`, `priority`; not AI Studio) | **yes, Safety Retention** | yes |
| `deepseek-v4-flash` | 10: DeepInfra x3, Fireworks, Relace, Wafer, Azure (US), Mancer, Venice, Parasail | no | all but Relace and Azure |
| `mistral-small-2603` | all 3 Mistral endpoints (`mistral/zdr`, `eu`, `us`) | no | yes |
| `gpt-oss-120b` | 23 hosts | Vertex only | most |
| `qwen3.8-flash` | **none** | n/a | n/a |

What this means, as facts:

- With `zdr: true` and **ZDR only** (Safety Retention excluded), the Gemini
  candidates have no endpoint and Qwen 3.8 Flash has none either; with
  Safety Retention allowed, the Gemini models run on Vertex.
- With ZDR, Anthropic and OpenAI models are served only from the
  hyperscalers, not first-party; the prices on those endpoints are the same
  as the table's (checked: Vertex, Bedrock, Azure rows in `/endpoints`).
  For Haiku, the ZDR set (Vertex, Bedrock) leaves only Vertex when strict
  `json_schema` is required.
- ZDR does not change price for Mistral (`mistral/zdr` is the cheapest
  Mistral endpoint), DeepSeek (DeepInfra at the headline price; Fireworks
  slightly cheaper at 0.07/0.14) or gpt-oss-120b (Near AI at 0.03/0.15 is a
  ZDR host).
- **Not confirmed:** which endpoints `data_collection: "deny"` keeps. The
  public API does not expose each endpoint's collection flag, and the
  provider-logging table is rendered client-side and did not come back in
  the markdown. The docs point to an authenticated
  `GET /api/v1/models/user` that lists models filtered by the caller's
  privacy settings and guardrails; I did not call it (needs a key).
  Whether `qwen3.8-flash` (Alibaba) passes `deny` is therefore unknown;
  it has no ZDR endpoint.
- Web search and other server tools are outside ZDR enforcement; the
  classifier uses none.

## Spend limits (for the daily cap)

Source: [limits](https://openrouter.ai/docs/api-reference/limits.md),
[guardrails](https://openrouter.ai/docs/guides/features/guardrails.md),
[create key](https://openrouter.ai/docs/api/api-reference/api-keys/create-keys.md),
read 2026-11-22.

- **Account balance:** prepaid credits; a request is rejected with 402 when
  the balance can't cover it. This is the hard backstop.
- **Per-key credit limit:** `limit` in USD with `limit_reset` of `daily`,
  `weekly` or `monthly` (or none), set at key creation or via PATCH. A daily
  reset is what a daily cap needs. Windows are UTC: daily resets at 00:00 UTC.
  Keys are created and edited through a management key; that is the
  documented route, and I did not find a dashboard-only statement either
  way.
- **Guardrail budgets** (`limit_usd` with a `reset_interval`) apply per
  member and per key. The docs describe them for organizations (workspace
  admins); I did not confirm they are available on a personal account.
- **Reading spend:** `GET /api/v1/key` returns `usage_daily`,
  `usage_weekly`, `usage_monthly`, `limit_remaining` and an
  `effective_budget`, so the app can check its own spend. Per-IP burst limits
  apply to that endpoint, and it is cheap to poll sparingly.
- A cap enforced by OpenRouter fails requests with 402 (key limit) or 403
  (guardrail budget) before reaching a provider; the app must handle both.
- The docs say OpenRouter "charges a request when it finishes", so requests
  in flight when a cap is reached may still complete; how much a cap can be
  overshot is not documented.

## Not verified

- No API call was made, so I have no measured structured-output validity,
  latency, or token usage for any candidate. Output tokens are the ticket's
  150 per window.
- Accuracy on this classification task is out of scope here (M5.5 evals).
- `data_collection: "deny"` membership per endpoint (see above).
- Hidden reasoning tokens per model and their effect on cost.
- Whether guardrail budgets exist for personal accounts.
- Batch API behaviour under ZDR.
- The shared-prompt size (1,500 tokens) is assumed; the real one comes from
  the prompt prototype.
