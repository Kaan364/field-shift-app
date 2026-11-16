# Project Alphecca — Technical Report

**Date:** November 15, 2026  
**Scope:** Python/FastAPI backend, NASA POWER integration, explainable agronomy engine, multi-year crop rotation, soil/water/climate modules, farmer PWA, swappable AI layer, tests, and evaluation.  
**Status:** Working backend + farmer web application (`/app/`) + automated tests + live NASA validation.

> **Version 0.2.0 note (November 15, 2026):** The first version of this report covered only the backend. This version adds the phone-friendly plain-Turkish PWA (`web/`), a 2–4 year crop rotation engine, a 9-indicator soil scorecard, monthly water balance (tons/m³), a 2001–present climate trend, and 5 new crops (21 total). For current endpoints and deployment see [README.md](README.md), for changes see [CHANGELOG.md](CHANGELOG.md).

---

## 1. Executive summary

Project Alphecca is a decision-support application that takes a farmer's location and field information, combines it with NASA POWER climate/soil data, produces an explainable score across 21 crops, and justifies the result with an LLM. The farmer interface is the PWA under `web/`; Streamlit is kept as an expert/test mode.

The most important technical decision is this: **I did not make AI the sole "crop selector."** LLMs cannot reliably perform agronomic calculations, may fabricate soil data that does not exist, and can give different results on every call. Therefore:

- The deterministic rule engine is **65% of the anchor**,
- The LLM is **35% of the explanation and reassessment**,
- If the LLM fails or there is no key, a **fully functional deterministic fallback**,
- The LLM may only use crops from the candidate list; it is constrained by a JSON schema and a `crop_key` allowlist.

In live validation for Ankara (39.93, 32.85), NASA POWER returned 418.2 mm annual precipitation, 10.31 °C mean temperature, and the `semi_arid` class; the first analysis took ~2.4 s, the cached analysis ~2 ms. Recommendation order was Winter Wheat → Barley → Grape → Chickpea → Canola (varies with inputs).

**Most critical caveat:** NASA POWER does not provide soil fertility (N-P-K), pH, or organic matter. "Pulling soil fertility from NASA APIs" was the biggest technical misconception in the plan; in this project pH/organic matter/salinity are taken as farmer input and explicitly warned about when missing. Details in Section 8.

---

## 2. What was delivered?

### 2.1. Working flow

```text
Farmer request (lat/lon + field + resources + preferences)
        │
        ▼
NASA POWER
  ├─ Climatology (2001-2025, monthly)  → climate + soil moisture/temperature
  └─ Daily (last 30 days)              → current context (optional, continue on error)
        │
        ▼
Agronomy layer
  ├─ annual precipitation/temperature, ET0 (Hargreaves), aridity class
  ├─ frost and heat stress months
  ├─ soil moisture/temperature and condition score
  └─ last 30 days: precipitation, dry spell, min/max temperature
        │
        ▼
Rule engine (21 crops)
  ├─ seasonal temperature, water balance, pH, texture, salinity
  ├─ climate risk, goal fit, market, planting calendar
  └─ 0-100 rule_score + component breakdown + constraints
        │
        ▼
AI layer (optional)
  ├─ Gemini / OpenAI / Claude / Groq / Mistral / DeepSeek / Ollama
  ├─ only candidate crop_keys; JSON schema validation
  └─ if error/no key, deterministic HeuristicProvider
        │
        ▼
Merge
  final_score = 0.65 × rule_score + 0.35 × ai_score
        │
        ▼
JSON response: ranked recommendations + rationale + risk + action + warning + source + disclaimer
```

The **free-text farmer flow (`/api/v1/advice`)** is a shortened version of the same pipeline:

```text
Farmer: map + 3 simple questions + the text "I don't know what to plant"
        │
        ▼
NASA POWER → agronomy layer → rule engine (ranking comes from here)
        │
        ▼
AI (if available) → EXPLANATION ONLY: headline, why, steps, grow, feed, care, risks, ask_farmer
        │     if AI is absent/fails, the same structure is produced with a deterministic template
        ▼
JSON: final_score == rule_score (AI cannot change the ranking)
```

### 2.2. Files

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI app factory, CORS, request ID, error handling, health, `/geo` location page |
| `app/config.py` | `.env`/environment variables, AI, NASA, and geocoding settings |
| `app/schemas.py` | All request/response contracts, validation |
| `app/api/routes.py` | `/analyze`, `/advice`, `/environment`, `/reverse-geocode`, `/crops`, `/ai-providers` |
| `app/clients/nasa_power.py` | NASA client, `-999` cleanup, TTL cache, retry |
| `app/clients/geocoding.py` | Nominatim reverse geocoding, TTL cache, User-Agent |
| `app/services/agronomy.py` | Climate/soil summary from NASA data, ET0, seasonal metrics |
| `app/domain/crops.py` | 21 crops, TR/EN aliases, catalog validation |
| `app/domain/scoring.py` | Explainable scoring and hard agronomic limits |
| `app/services/recommendation.py` | Shared NASA + rule pipeline (`prepare`), `/analyze` orchestration |
| `app/services/advice.py` | Free-text farmer flow: rule ranking + plain-language explanation |
| `app/ai/*` | Provider abstraction, prompt, JSON parsing, fallback |
| `ui/app.py` | Streamlit interface: map, farmer flow, detail box, expert mode |
| `tests/*` | 62 tests; NASA and LLM mocked |
| `README.md` | Setup, API, examples |
| `RAPOR.md` | This report |

### 2.3. API endpoints

- `POST /api/v1/analyze` — full analysis
- `POST /api/v1/advice` — plain-language plan for a free-text farmer question
- `GET /api/v1/environment` — NASA summary (without recommendations)
- `GET /api/v1/reverse-geocode` — coordinates → place name (Nominatim)
- `GET /api/v1/crops` — crop catalog
- `GET /api/v1/ai-providers` — AI comparison
- `GET /geo` — browser location permission page
- `GET /health` — health, AI provider, geocoding, cache
- `GET /docs` — Swagger (temporary test UI)

Error contract: `422` validation/no suitable crop, `502` NASA unreachable, `503` AI unreachable and fallback disabled.

---

## 3. NASA POWER integration

### 3.1. Services used

| Service | Purpose |
|---|---|
| `GET /api/temporal/climatology/point` | 2001-2025 monthly climate and soil moisture/temperature averages |
| `GET /api/temporal/daily/point` | Daily temperature, precipitation, soil moisture for the last 30 days |

Requests use `community=AG`, `format=JSON`, and WGS84 coordinates. `-999.0` fill values are converted to `None`; missing days are excluded from calculations.

### 3.2. Parameters used

| Parameter | Description | Use |
|---|---|---|
| `T2M` | 2 m mean temperature | Seasonal temperature, climate summary |
| `T2M_MAX` / `T2M_MIN` | Daily max/min temperature | Frost and heat stress |
| `PRECTOTCORR` | Corrected precipitation | Water balance, drought |
| `RH2M` | Relative humidity | Informational |
| `ALLSKY_SFC_SW_DWN` | Solar radiation | Informational |
| `WS2M` | Wind | Informational |
| `GWETROOT` / `GWETTOP` | Root zone / surface soil moisture | Soil condition score, drought |
| `TS` | Soil temperature | Soil condition score |
| `EVLAND` / `EVPTRNS` | Actual evaporation/evapotranspiration | Requested as raw data; **not used** in the aridity index |

### 3.3. Aridity class and ET0

NASA's `EVLAND`/`EVPTRNS` values are **actual** evaporation; an aridity index requires potential/reference ET. Therefore:

- **Hargreaves-Samani ET0** is computed from monthly `T2M`, `T2M_MAX`, `T2M_MIN`, and latitude.
- `aridity_index = annual precipitation / annual ET0`.
- Classes: `<0.05` hyper-arid, `<0.20` arid, `<0.50` semi-arid, `<0.65` dry-subhumid, `<1.0` humid, `≥1.0` very humid.

In the Ankara example, annual ET0 is ~1724 mm and the index is 0.243 → `semi_arid`. Hargreaves can overestimate ET0, especially in continental climates with a wide daily temperature range; in production it should be calibrated with local FAO-56/station data. This is flagged in the report as a deliberate approach.

### 3.4. What NASA does not provide

- Soil nutrients (N-P-K), pH, organic matter, EC.
- Field-scale data (grid ~0.5° × 0.625°, ~50 km at mid-latitudes).
- Weather **forecast** (the daily endpoint is historical/lagged observation).
- Future climate projection (CMIP6 scenarios are a separate dataset).
- Market price, local variety, disease/pest pressure.

These gaps are explicitly stated in the response under `soil.data_gaps` and `environment.notes`. This "transparency" is a deliberate design decision: showing uncertainty is safer than giving the farmer a precise number based on incomplete data.

---

## 4. AI providers: comparison and evaluation

### 4.1. Short decision

| Scenario | My recommendation | Why |
|---|---|---|
| MVP / low cost / first release | **Google Gemini 3.5 Flash-Lite** | Free tier, low price, good Turkish, JSON mode, fast |
| Quality and JSON reliability priority | **OpenAI GPT-4.1-mini** | Consistent structured output, mature ecosystem |
| Complex agronomic reasoning | **Anthropic Claude Sonnet** | Long context, cautious language, strong reasoning |
| Very low latency | **Groq (Llama 3.3 70B)** | Near real-time response |
| EU data residency | **Mistral** | EU-based options, reasonable cost |
| Privacy / offline | **Ollama + Qwen2.5/Llama 3.3** | Data never leaves, no token fees |
| Multi-model experimentation | **OpenRouter** | One key, model comparison |
| Cost very critical, privacy flexible | **DeepSeek** | Very low token cost |

**My "best" assessment:** The most balanced starting point for this product is **Gemini 3.5 Flash-Lite + deterministic fallback**. The reason: agricultural advisory is a high-volume, multilingual, cost-sensitive business; Gemini's free tier and JSON mode allow rapid MVP validation. After product-market fit is proven, moving to GPT-4.1-mini or Claude in quality-critical flows, or A/B testing the two, makes sense. In countries with privacy regulation, Ollama/Azure OpenAI regional deployment stands out.

> **AI is not mandatory.** With `AI_PROVIDER=heuristic` (default) all endpoints work; explanations are generated with a deterministic template. Adding a key only improves explanation quality, not the ranking.

> **Gemini model note:** As of November 2026, `gemini-2.5-flash` is being redirected to `gemini-3.5-flash-lite` from December 1, 2026. The code uses `gemini-3.5-flash-lite` by default, authenticates with the `x-goog-api-key` header, and only sends the `temperature` parameter, removed in Gemini 3.x, to `gemini-2*` models.

> Model names, prices, and quotas change rapidly. This table is a qualitative assessment as of November 2026; current pricing/quota/data policy should be checked before production.

### 4.2. Detailed advantage / disadvantage table

| Provider / model | Advantages | Disadvantages | Cost | Latency | Privacy | Turkish / JSON | Best for |
|---|---|---|---|---|---|---|---|
| **Google Gemini 3.5 Flash-Lite** | Free tier; very low price; near 1M context; strong multilingual support; built-in JSON mode; fast | Free-tier speed/data usage terms vary; regional access restrictions; model versions change frequently; sometimes overconfident | $ (free tier) | Low-medium | Google policies | Very good / very good | MVP, cost-sensitive production |
| **OpenAI GPT-4.1-mini / GPT-4.1** | Most consistent structured output; strong tool calling; mature SDK/ecosystem; good Turkish | No free tier; cost at high volume; data residency/approval; quota management | $$ | Low-medium | OpenAI policies; enterprise options | Very good / very high | Quality-critical production |
| **Anthropic Claude Sonnet / Haiku** | Strong reasoning; long documents; cautious, risk-averse language; high-quality Turkish | Expensive; no free tier; JSON requires schema/tool support plus extra validation | $$$ | Medium | Anthropic policies | Very good / high | Complex scenarios, advisory |
| **Groq (Llama 3.3 70B)** | Very low latency; affordable; OpenAI-compatible | Limited model variety; weaker Turkish nuance in open models; rate limits | $ | Very low | Groq policies | Good / medium-high | Chat, quick pre-assessment |
| **Mistral Small / Large** | EU data options; affordable; good multilingual support; fast small models | Smaller ecosystem; hardest reasoning requires the large model | $ | Low | EU options | Good / high | EU data residency |
| **DeepSeek V3 / R1** | Very low cost; strong reasoning; OpenAI-compatible | China-based data processing; privacy/compliance risk; latency under load; Turkish agricultural terminology must be verified | $ | Medium | Overseas; enterprise approval required | Good / high | Cost-critical, non-sensitive data |
| **xAI Grok** | Fast; current information; OpenAI-compatible | Not agriculture-specific; cost/quota unclear; Turkish varies by model | $$ | Low | xAI policies | Good / high | Secondary provider |
| **Together AI** | Hosts open models affordably; model variety | Turkish varies across open models; less enterprise maturity | $ | Low-medium | Provider policies | Variable / medium-high | Open model experiments |
| **OpenRouter** | Many models with one key; easy A/B; backup | Middleman fee; privacy varies by model; single point of dependency | $$ | Variable | Depends on model | Variable | Prototyping, model comparison |
| **Ollama (local)** | Fully local/offline; data never leaves; no token fees | Hardware (RAM/GPU) and operational burden; weak Turkish/reasoning in small models; security is your responsibility | Hardware | Hardware-dependent | Fully local | Medium / medium | Privacy, field/offline |
| **Hugging Face Inference** | Very broad model catalog; easy experimentation; affordable | Cold start; variable quality; quota; weak production SLA | $ | Medium-high | Depends on model | Variable | Experiments, custom models |
| **Azure OpenAI / AWS Bedrock / Vertex** | Enterprise compliance, regional data residency, SLA, private network | Setup cost; model choice depends on provider; complexity | $$-$$$ | Low-medium | Strongest enterprise options | Very good | Regulated markets, enterprise |

### 4.3. Why provider abstraction?

Thanks to the `AIProvider` interface, the same product code:

- works with any OpenAI-compatible service (`AI_PROVIDER=openai|groq|mistral|deepseek|xai|together|openrouter|ollama|custom`),
- with Gemini (`AI_PROVIDER=gemini`),
- with Claude (`AI_PROVIDER=anthropic`),
- without any of them (`AI_PROVIDER=heuristic`).

Changing the provider requires no code change; only `.env` changes. This is the most important architectural insurance against price/quota/data policy changes.

### 4.4. AI safeguards (implemented)

1. **Allowlist:** The LLM may only return `crop_key`s from the candidate list; unknown ones are filtered.
2. **JSON schema:** Validation with Pydantic; malformed JSON becomes `AIProviderError`.
3. **Deterministic anchor:** 65% of the final score comes from the rule engine.
4. **Fallback:** On LLM error the analysis does not stop entirely; the deterministic advisor takes over.
5. **Token limit:** At most 8 candidates are sent to the LLM; the response is limited to 1600 tokens.
6. **Prompt constraints:** Instructions not to fabricate data that was not provided, not to guarantee exact yield/profit, and to state missing data.
7. **Transparency:** The response returns `ai.provider`, `used`, `fallback_used`, `latency_ms`, `error` fields.
8. **Disclaimer:** Every response includes legal/liability disclaimer text.

These **reduce but do not eliminate** hallucination. Production also requires agronomist review and an evaluation set.

---

## 5. Scoring and decision logic

### 5.1. Components

| Component | Weight | Calculation |
|---|---:|---|
| Temperature | 20% | Linear fit of the crop's seasonal mean temperature to its optimum/absolute range |
| Water balance | 24% | `(seasonal precipitation + irrigation supply) / seasonal water requirement`; drought tolerance softens the deficit |
| pH | 10% | pH optimum and tolerance range |
| Texture | 10% | Texture group (light/medium/heavy) distance |
| Salinity | 4% | EC threshold; according to crop tolerance |
| Climate risk | 10% | Number of frost months, number of heat-stress months, aridity class |
| Goal fit | 14% | Yield/profit/low water/low input/organic/soil health/risk avoidance |
| Market | 5% | Demand index; cap if market access is low |
| Planting calendar | 3% | Distance between the farmer's month and the crop's planting window |

If data is missing, the relevant component is removed from the denominator (re-weighting). For example, if pH is not entered, the pH score does not contaminate the score with a "default of 70"; it is simply excluded from the calculation. This matters to avoid false precision when data is missing.

### 5.2. Hard limits

In the following cases the score is reduced by a multiplier:

- Seasonal temperature outside the crop's absolute limit → `×0.35`
- Water balance zero and no irrigation → `×0.50`
- pH outside the absolute limit → `×0.65`
- 3+ frost months and a very frost-sensitive perennial → `×0.55`
- 3+ heat-stress months and very heat-sensitive → `×0.75`

### 5.3. AI merge

```text
final_score = 0.65 × rule_score + 0.35 × ai_score
```

`AI_WEIGHT` can be adjusted between 0 and 1 via an environment variable. `AI_WEIGHT=0` means fully deterministic, `1` means fully AI. The default of 0.35 prevents AI from completely taking over the ranking while allowing it to add interpretation.

### 5.4. Why this approach?

- **Explainability:** Every recommendation has a component breakdown; the farmer can see the answer to "why this crop?"
- **Consistency:** The same input gives the same rule score; even if the LLM version changes, the anchor stays fixed.
- **Cost:** The LLM is called with only 8 candidates and a short context.
- **Safety:** The LLM fabricating soil data that does not exist cannot determine the score on its own.

### 5.5. Why doesn't AI affect the ranking in the free-text flow?

In the `/api/v1/advice` flow, `final_score = rule_score` is fixed and `ai_score = null` is returned. The reason:

- The text the farmer writes is **unstructured**; a sentence like "no irrigation" can contradict the "full irrigation" selection in the form.
- The same sentence being interpreted differently by different models produces different rankings for the same field. This is an unacceptable volatility for an agricultural decision.
- Therefore the text only enters the **explanation** layer and the "missing information" questions. The only thing that determines the ranking is structured fields + NASA data.
- AI's suggestion of a fabricated crop name is blocked by `parse_advice` + the candidate allowlist; an unknown name falls into the `risks` field with a note that "unverifiable plant name was filtered out."

### 5.6. Does the rule engine validate data accuracy?

**No.** The rule engine is a *consistency and plausibility* check, not a *data validation* tool. Three layers must be distinguished:

| Layer | What does the rule engine do? | What can't it do? |
|---|---|---|
| NASA POWER data | Interprets values against agronomic ranges (e.g., 613 mm precipitation → semi-arid) | Cannot detect sensor/satellite error or the deviation of the grid average from field reality |
| Farmer input (pH, organic matter, texture) | Range and consistency checks (pH 3.5-10, salinity thresholds) | Cannot catch a farmer's misstatement; does not know the measurement's accuracy |
| Recommendation result | Prevents obvious errors with hard agronomic limits (does not put a frost-sensitive plant in a 3-frost-month month) | Cannot guarantee yield, price, or profit; cannot know local variety/disease information |

So the rule engine answers **"Is this recommendation absurd?"**, not **"Is this data correct?"**. What is needed for data accuracy: soil analysis (pH/OM/N-P-K), a local weather station or higher-resolution satellite data, expert verification of farmer declarations, and end-of-season yield feedback.

---

## 6. Tests and validation

### 6.1. Automated tests

```text
64 passed
```

| Test file | Coverage | Count |
|---|---|---:|
| `test_nasa_power.py` | JSON parsing, `-999` cleanup, cache, retry, HTTP/network/error | 7 |
| `test_agronomy.py` | Climate summary, ET0, soil, last 30 days, season window | 5 |
| `test_scoring.py` | Catalog, ranking, irrigation, exclude/interest, pH, texture, calendar, duration | 10 |
| `test_ai.py` | Heuristic, JSON cleanup, allowlist, OpenAI/Gemini/Claude, 400 fallback, Gemini 3.x request shape | 12 |
| `test_api.py` | Health, `/geo`, root, catalog, analysis, validation, 502/422/503, AI fallback, weight | 14 |
| `test_advice.py` | `/advice` flow, free-text passthrough, fallback on AI error, `/reverse-geocode`, Nominatim cache/error | 8 |
| `test_ui_smoke.py` | UI files, rendering with backend off, farmer flow, detail box, button regressions, payload contract | 8 |

Tests **do not make real NASA or LLM calls**; they use `httpx.MockTransport` and fake clients. This lets them run in CI without keys and free of charge.

### 6.2. Live validation

- Real NASA POWER call: Ankara, 39.93/32.85.
- Result: 418.2 mm annual precipitation, 10.31 °C mean, ET0 ~1723.7 mm, aridity 0.243, `semi_arid`.
- First analysis ~2.4 s (NASA network); cached analysis ~2 ms.
- Recommendation in heuristic mode: Winter Wheat 93.7, Barley 88.6, Grape 84.5.
- `GET /docs` and `POST /api/v1/analyze` worked end to end.
- `POST /api/v1/advice` (Edirne 41.6771/26.5557, free text): 2.7 s, 613 mm / 13.65 °C,
  "Winter Wheat is the best choice for this field. Alternative: Barley." — 5 steps, 4 growth, 4 feeding, 4 care items.
- `GET /api/v1/reverse-geocode` real Nominatim call: "Sabuni Mahallesi, Edirne Merkez, Edirne" (~400 ms, cached afterwards).
- The Streamlit interface was connected to the live backend and tested: recommendation button → result screen, detail box → climate/soil/score table; no exceptions.

### 6.3. Untested

- Live quality testing with real LLM keys (no key).
- Local crop varieties and agronomic accuracy in different countries.
- Load/performance testing (locust/k6).
- Security penetration testing.
- Long-term NASA quota behavior.

These should be done before production.

---

## 7. Where can it be improved? (prioritized)

### P0 — Required before production

1. **Soil data:** SoilGrids / OpenLandMap integration + mandatory/incentivized soil analysis. NASA alone is not enough.
2. **Weather forecast:** NASA daily is historical data; a 7-14 day forecast and irrigation warning with Open-Meteo/NOAA GFS/ECMWF.
3. **Geocoding:** Address/city/district search (Nominatim, Google Geocoding); currently lat/lon is manual.
4. **Authentication + rate limit:** API key/JWT, per-user quota, abuse protection.
5. **Persistence:** PostgreSQL + PostGIS; analysis history, farm/field records, feedback.
6. **Observability:** Structured logging, Prometheus/OpenTelemetry, error tracking, cost/latency dashboard.
7. **Deployment:** Docker, CI (lint + test), staging/prod, HTTPS, secret manager.
8. **Data validation:** Agronomist-labeled evaluation set; hit rate of recommendations; backtesting in different regions.

### P1 — Strengthens the product

9. **Crop simulation:** Yield and irrigation simulation with DSSAT/APSIM/CROPWAT; instead of/alongside the rule engine.
10. **Climate projection:** SSP2-4.5/SSP5-8.5 scenarios with NASA NEX-GDDP-CMIP6; the question "will this crop still be suitable in 2030-2050?"
11. **Satellite data:** Sentinel-2 NDVI, SMAP soil moisture, Landsat for field-level validation.
12. **Market prices:** Local exchange/cooperative prices, input costs, gross margin calculation.
13. **Variety database:** Region-specific certified varieties, hardiness, yield potential.
14. **Pest/disease models:** GDD-based risk alerts, early warning.
15. **Irrigation scheduling:** FAO-56 ETc, soil water holding capacity, irrigation efficiency.
16. **i18n:** All texts translatable; currently the heuristic is Turkish/English, crop notes mostly Turkish.
17. **Offline/mobile:** Ollama local server or an on-device small model; low-connectivity fields.

### P2 — Creates long-term differentiation

18. **Feedback loop:** Model calibration with the farmer's "did I plant/did I not, what was the result?" data.
19. **A/B testing:** Gemini vs GPT vs Claude; cost/quality/latency measurement.
20. **Yield prediction:** ML model with satellite + weather + soil + farmer record; does not replace the rule engine, supports it.
21. **Carbon/regenerative agriculture:** Organic matter, carbon credit, water footprint modules.
22. **Insurance/finance:** Insurance premium or credit profile tied to the risk score (careful with regulation).

---

## 8. Missing or wrong points in the plan (open report)

The following is critical but constructive; most were partially mitigated in this project, but they remain open for productization.

### 8.1. "Soil fertility with NASA APIs" — technically wrong

NASA POWER provides soil **moisture** and **temperature**; it **does not provide** the N-P-K, pH, organic matter, cation exchange capacity, and salinity needed for fertility. In this project pH/OM/EC are farmer input; if missing, there is a `data_gaps` warning. The real solution: SoilGrids/OpenLandMap + laboratory analysis + local soil maps.

### 8.2. "Let AI pick the best crop type" — over-trusting the LLM

LLMs are not an agricultural calculation engine; they can give different answers to the same input, fabricate data that does not exist, and cannot know local variety/market information. In this project I constrained AI to **35% weight** and **allowlist + JSON schema + deterministic fallback**. Even so, it is not enough on its own: process-based models such as DSSAT/APSIM and agronomist validation are required.

### 8.3. "NASA climate change data" — confusing historical baseline with future projection

The climatology we use is the 2001-2025 average; it is not a "climate change scenario." The future requires NASA NEX-GDDP-CMIP6, SSP scenarios, and downscaling. Today's output answers "is this crop suitable in the current/past climate?", not "will it be suitable in 2050?"

### 8.4. "Weather" — confusing forecast with observation

The POWER daily endpoint is retrospective/lagged data; it is not a 7-day forecast. A separate forecast provider (Open-Meteo, NOAA GFS, ECMWF) is required for irrigation and frost alerts.

### 8.5. "All farmers in the world" — a single global model is not realistic

21 crops and a single weight set are not enough worldwide. At the country/region level:

- local crops and varieties,
- soil types and analysis methods,
- market prices and logistics,
- climate zones,
- language, units, regulation

differ. The product strategy should be "global engine + regional data packs"; entering every country with the same coefficients would be misleading.

### 8.6. Grid resolution — the field-scale illusion

POWER uses a ~50 km grid. Two fields in the same cell can have different soil, slope, and water. The phrase "selected region" is suitable for marketing, not for agronomic precision. It should be supported by field boundaries (polygon), soil sampling, and satellite data.

### 8.7. Giving precise recommendations without soil analysis

If pH/OM/EC are not entered, the model runs with defaults and the response says so. However, unless the UI makes these gaps **mandatory/incentivized**, the farmer may perceive false precision. The UI should have a "no soil analysis" badge and a confidence-reduction mechanism.

### 8.8. Legal liability and the "yield guarantee" risk

Agricultural advice can cause serious economic damage if applied incorrectly. Instead of saying "this crop is the most profitable," probability/risk language should be used; there should be a disclaimer, terms of use, insurance, and human approval. This project has a disclaimer but no legal text or liability insurance.

### 8.9. Privacy and KVKK/GDPR

Location, field size, and production information are personal/commercial data. Currently:

- no authentication,
- no rate limit,
- no data retention policy,
- no PII masking in logs,
- no explicit consent flow for sending data to the AI provider.

In production, KVKK/GDPR notices, retention periods, the right to erasure, cross-border transfer, and provider data policies must be clarified.

### 8.10. Cost and latency control

Calling an LLM on every request can be expensive. This project has an 8-candidate/1600-token limit and a cache; however:

- a daily quota per user,
- response caching (same grid + same profile),
- small-model routing,
- a cost alarm

are missing. Especially on the free tier, bulk usage can exhaust the quota.

### 8.11. Lack of evaluation

The answer to "is the AI good?" cannot be given with anecdotes. A test set labeled by agronomists, region-based backtesting, recommendation hit rate, user satisfaction, and real harvest data are required. Without this, even the 35% AI weight remains arbitrary.

### 8.12. No disease/pest, irrigation, or post-harvest processes

Crop selection is not the only decision; planting time, fertilization, irrigation, disease, harvest, storage, and sales are also required. The product roadmap should cover this chain; otherwise the farmer gets an answer to "what should we plant?" but is left alone for the rest of the season.

### 8.13. Localization and literacy

Turkish/English support exists; however:

- crop notes are mostly Turkish,
- units are metric,
- a high literacy level is assumed,
- there is no visual/audio support.

Real coverage requires multilingual support, plain language, voice narration, and mobile-first design.

### 8.14. Data license and attribution

Although NASA data is open, attribution/terms should be checked. Crop parameters and score weights are approximate values compiled for this project; local sources and expert calibration are essential for commercial use.

### 8.15. Infrastructure and resilience

Single process, in-memory cache, no database. Multi-instance deployment would cause cache inconsistency, data loss on restart, and horizontal scaling problems. It should be matured with Redis, PostgreSQL, and a job queue.

---

## 9. Roadmap

### 0-1 month (MVP hardening)

- Docker + CI, environment separation, secret manager
- Auth/rate limit, PII masking, KVKK/GDPR texts
- SoilGrids + soil analysis fields, geocoding
- Forecast API (Open-Meteo) and frost/heat alerts
- Agronomist review screen (recommendation approval/rejection)
- Quality testing with a real LLM key and cost measurement

### 1-3 months (agronomic depth)

- DSSAT/APSIM/CROPWAT integration (at least a pilot region)
- NEX-GDDP-CMIP6 scenarios
- Local variety and market price database
- Irrigation scheduling (FAO-56 ETc)
- Pest/disease GDD alerts
- PostgreSQL + PostGIS, analysis history, farm records

### 3-6 months (scale and evidence)

- Multi-region field pilot, agronomist-labeled evaluation set
- Satellite (Sentinel-2/SMAP) validation
- A/B testing: Gemini vs GPT vs Claude; cost/quality
- Feedback loop and model calibration
- Mobile/offline scenario, i18n
- Risk score API for insurance/finance partnerships

---

## 10. Production checklist

- [ ] Real soil analysis and local expert verification
- [ ] Forecast provider and frost alert
- [ ] Authentication, rate limit, quota
- [ ] KVKK/GDPR notice and data retention policy
- [ ] AI provider agreement/data processing addenda
- [ ] Cost alarm and token budget
- [ ] Agronomist approval flow
- [ ] Evaluation set and accuracy metrics
- [ ] Docker/CI/CD, staging, HTTPS
- [ ] Log/metric/trace and error monitoring
- [ ] Backup and disaster recovery
- [ ] Legal disclaimer and terms of use

---

## 11. Conclusion

This delivery goes beyond "a working backend" and builds an **honest architecture**:

- it clearly separates what NASA data is and is not,
- it does not make AI the sole decision-maker, but ties it to an explainable rule engine,
- it is provider-independent and testable without keys,
- it does not hide missing data, but shows it with `data_gaps` and `warnings`,
- it proves it works with 44 tests and live NASA validation.

The biggest gaps are **field-scale soil data**, **weather forecasting**, **climate projection**, **local calibration**, **user verification/security**, and an **agronomist evaluation set**. These are prioritized in Sections 7-8.

In short: this backend is a solid first version of the "crop recommendation with NASA + AI" idea; however, it should not go to production for real farmer value without adding data depth and human validation.
