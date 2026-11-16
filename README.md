# Tarla Dostu — Project Alphecca

A decision-support application for farmers powered by **NASA POWER data + explainable agronomy rules + a swappable LLM layer**.

> **Open it on your phone, answer three questions, read your planting plan.**
> The application now runs at a single address: **`/app/`** (locally <http://127.0.0.1:8000/app/>). The same FastAPI process serves both the JSON API and the farmer interface. The Streamlit interface is kept as an expert/test mode.

The interface is designed for low-literacy users with plain Turkish, large buttons, icons, and read-aloud. Technical details are inside collapsible boxes; the main screen shows only "what to plant this year, what to plant in the following years, and what condition my soil and water are in."

---

## 1. What does it do?

A single request (`POST /api/v1/farm-plan`) produces:

1. **This year's best crop** — a 0-100 score based on NASA climate data + soil + irrigation + goal.
2. **2, 3, or 4-year crop rotation** — the first year starts with the current year's recommendation; it does not plant the same family back-to-back, rewards legume/stubble/root diversity, and calculates water need.
3. **Soil health scorecard (A–D)** — nine indicators: organic matter, pH, texture, salinity, drainage, NASA soil moisture/temperature, slope, and rotation diversity; it clearly states missing data.
4. **Water scorecard** — monthly precipitation/evaporation balance, seasonal deficit; in **tons per decare** and total field m³.
5. **Climate trend** — annualized temperature/precipitation trend and drought risk from NASA POWER monthly data from 2001 to today. *Not a forecast, but the direction of historical data.*
6. **Plain-language to-dos** — first steps, growing, fertilizing, care, risks, and alternative crops.
7. **Uncertainty and limits** — data gaps, warnings, data sources, and legal disclaimer.

AI (Gemini, OpenAI, Claude, Groq, Mistral, DeepSeek, Ollama…) only writes the **explanation**. The ranking is determined by the deterministic rule engine; the application works fully without an AI key.

### Farmer web application (`/app/`)

- **3-step wizard:** location → field/water → goal. Tap the map, browser location, or 25 city shortcuts.
- **Map:** Leaflet + OpenStreetMap; field marker, reverse geocoding (Nominatim).
- **Large touch targets** and `A+` text scaling; `prefers-reduced-motion` and high-contrast support.
- **Result screen:** year-by-year planting timeline, score card, soil/water/climate cards, checkable to-do list.
- **Listen** (browser speech, `tr-TR`), **Print**, **Share** (Web Share / copy to clipboard), **Download JSON**.
- **Offline:** the app shell is cached with a service worker; the last plan is stored in `localStorage` and can be opened without internet. A connection is required for a new plan.
- **PWA:** can be added to the home screen (`manifest.webmanifest`, maskable icons).
- **Accessibility:** keyboard focus, `aria-live` status messages, color + icon + text used together.

### Important data reality

NASA POWER **does not provide soil fertility / N-P-K / pH / organic matter.** It only provides grid-based climate, soil moisture, and soil temperature proxies. Therefore:

- pH, organic matter, salinity, and texture are taken as **farmer input**; they can be left blank.
- If nutrient analysis is missing, the API clearly states this in the `data_gaps` and `notes` fields.
- NASA POWER resolution is ~0.5° × 0.625°; it is not field-scale.
- The climate trend is the linear direction of past years; it is not an official climate projection.

---

## 2. Quick start

### Linux / macOS

```bash
git clone https://github.com/Kaan364/field-shift-app.git
cd field-shift-app

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# Add an AI key if you want; it is not required.
cp .env.example .env

python run.py
# or: uvicorn app.main:app --reload
```

### Windows (PowerShell)

```powershell
git clone https://github.com/Kaan364/field-shift-app.git
cd field-shift-app

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

Copy-Item .env.example .env
python run.py
```

Addresses to open:

| Address | What it shows |
|---|---|
| <http://127.0.0.1:8000/app/> | **Farmer application** (mobile-friendly) |
| <http://127.0.0.1:8000/> | Farmer application in the browser, JSON API summary in an API client |
| <http://127.0.0.1:8000/docs> | Swagger / OpenAPI |
| <http://127.0.0.1:8000/health> | Health status |

### Docker

```bash
docker compose up --build
# http://127.0.0.1:8000/app/
```

### Verify + package with one command

```bash
./scripts/build.sh          # syntax + tests + dist/ package
make test                   # tests only
make run                    # development server
make docker                 # build the image
```

At the end, `scripts/build.sh` creates `dist/tarla-dostu-<version>-<date>.tar.gz` and a SHA-256 file. The package contains `app/` + `web/` + the dependency manifest; on the target machine it runs with `pip install -r requirements.txt` and `uvicorn app.main:app`. There is no front-end build step (vanilla HTML/CSS/JS).

---

## 3. Streamlit expert interface (optional)

Starts the backend and the legacy expert interface together:

```bash
python -m pip install -r requirements-ui.txt
python run_ui.py
# http://127.0.0.1:8501
```

- If the backend is already running: `python run_ui.py --no-backend`
- Different ports: `python run_ui.py --api-port 8001 --ui-port 8502`
- Tabs: Analysis, Environment Data, Crop Catalog (21 crops), AI Providers, System & Console.

The recommended interface for farmers is now the PWA under `/app/`; Streamlit is more for manually trying the API and seeing expert output.

---

## 4. API

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | HTML application to the browser, JSON summary to API clients |
| `GET` | `/app/` | Farmer PWA (static) |
| `GET` | `/health`, `/api/v1/health` | Health, AI provider, cache status |
| `GET` | `/api/v1/environment?latitude=..&longitude=..` | Climate/soil summary from NASA data |
| `GET` | `/api/v1/crops` | Parameters, icon, and family of 21 crops |
| `GET` | `/api/v1/ai-providers` | AI provider comparison |
| `POST` | `/api/v1/analyze` | Full analysis and ranked recommendations |
| `POST` | `/api/v1/advice` | Plain-language plan for a free-text farmer question |
| `POST` | `/api/v1/farm-plan` | **Full plan:** recommendation + rotation + soil + water + climate |
| `POST` | `/api/v1/rotation` | Crop rotation only |
| `POST` | `/api/v1/soil-health` | Soil health only |
| `POST` | `/api/v1/water-plan` | Water balance only |
| `GET` | `/api/v1/reverse-geocode?latitude=..&longitude=..` | Coordinates → place name (Nominatim) |
| `GET` | `/geo?next=/app/` | Helper page that asks the browser for location permission |

### Full plan in a single request

```bash
curl -X POST http://127.0.0.1:8000/api/v1/farm-plan \
  -H "Content-Type: application/json" \
  -d '{
    "location": {"latitude": 39.93, "longitude": 32.85, "region_name": "Ankara"},
    "area_hectares": 12.5,
    "soil_texture": "clay_loam",
    "soil_ph": 7.4,
    "organic_matter_pct": 1.8,
    "irrigation": "limited",
    "water_availability": "medium",
    "goal": "soil_health",
    "planting_month": 10,
    "rotation_years": 3,
    "top_n": 3,
    "language": "tr"
  }'
```

Main sections of the response:

```json
{
  "plan_id": "…",
  "recommendations": [{"rank": 1, "crop_key": "wheat", "crop_name_local": "Kışlık Buğday", "scores": {"final_score": 87.2}}],
  "rotation": {
    "applicable": true,
    "years_requested": 3,
    "years": [
      {"year": 1, "crop_key": "wheat", "crop_name_local": "Kışlık Buğday", "role": "Kışlık tahıl", "planting_window": "Ekim–Kasım", "water_need_mm": 450, "benefit": "…", "actions": ["…"]},
      {"year": 2, "crop_key": "chickpea", "crop_name_local": "Nohut", "role": "Baklagil", "…": "…"},
      {"year": 3, "crop_key": "barley", "crop_name_local": "Arpa", "…": "…"}
    ],
    "scores": {"overall": 78.4, "soil_health": 82, "water": 71, "resilience": 76, "profit": 65, "risk": 88},
    "benefits": ["…"],
    "cautions": ["…"],
    "alternatives": [{"crop_names": ["…"], "total_water_mm": 1080, "scores": {"overall": 74.1}}]
  },
  "soil_health": {"grade": "B", "score": 74.0, "summary": "…", "indicators": ["…"], "actions": ["…"], "data_gaps": ["…"]},
  "water": {"crop_need_mm": 1180, "season_rain_mm": 336, "deficit_mm": 844, "deficit_m3": 10550, "deficit_ton_per_decare": 844, "months": ["…"], "tips": ["…"]},
  "climate": {"available": true, "start_year": 2001, "end_year": 2025, "risk_level": "medium", "risk_label": "Orta", "trends": ["…"], "messages": ["…"]},
  "advice": {"headline": "…", "why": "…", "steps": ["…"], "grow": ["…"], "feed": ["…"], "care": ["…"], "risks": ["…"]},
  "warnings": [],
  "disclaimer": "Bu çıktı bir karar destek aracıdır; …"
}
```

> Example values vary with NASA data and inputs. Full schema: `/docs` or `/openapi.json`.

### Legacy `analyze` request

`POST /api/v1/analyze` uses the nested `field` / `resources` / `preferences` structure. `farm-plan`, `advice`, and the new endpoints accept flat fields (`area_hectares`, `soil_ph`, `irrigation`, `goal` …). Both contracts are backward compatible.

### Error codes

| Code | Meaning |
|---|---|
| `422` | Input validation error or no crop matches the filters (`no_candidates`) |
| `502` | NASA POWER unreachable (`nasa_power_unavailable`) |
| `503` | AI provider could not respond and fallback is disabled (`ai_unavailable`) |

---

## 5. Scoring and models

### Single-crop score

Nine components are calculated; if data is missing, that component is removed from the weighting:

| Component | Weight | What does it measure? |
|---|---:|---|
| Temperature | 20% | The crop's seasonal temperature range |
| Water balance | 24% | Seasonal precipitation + irrigation supply / seasonal water requirement |
| Soil pH | 10% | pH optimum and tolerance range |
| Soil texture | 10% | Texture group match |
| Salinity | 4% | EC threshold and tolerance |
| Climate risk | 10% | Frost, heat stress, aridity class |
| Goal fit | 14% | Yield, profit, low water, organic, soil health, etc. |
| Market | 5% | Market demand and access |
| Planting calendar | 3% | The month planned by the farmer |

```text
rule_score  = weighted component average (0-100)
final_score = (1 - AI_WEIGHT) * rule_score + AI_WEIGHT * ai_score
```

### Rotation score

Weights change by goal and always sum to 1.0:

| Component | What does it reward? |
|---|---|
| Soil health | Legume, stubble cover, family diversity, different root depth |
| Water | Meeting total water need with precipitation + irrigation, drought resilience |
| Climate resilience | Family diversity, breaking disease/pest pressure |
| Profit potential | Gross margin, market demand, yield potential |
| Risk safety | Penalties for high water need, high nitrogen need, poor fit |

The rotation **fixes year 1 to the current year's best crop**, so the multi-year plan does not contradict the single-year recommendation. The same crop does not repeat, the same family does not follow itself, and perennials (vineyard, olive, apple) are not included in the annual rotation.

### Water conversion

1 mm water × 1 decare (1,000 m²) = 1 m³ = **1 ton**. The API returns `deficit_mm`, `deficit_m3`, and `deficit_ton_per_decare`.

> All scores are for **preliminary screening**; they are not an official yield estimate, financial model, or guarantee.

---

## 6. AI provider configuration

The default is `heuristic` mode: it requires no internet, API key, or fee. **An AI key is not mandatory.**

```env
# Gemini (recommended starting point)
AI_PROVIDER=gemini
AI_API_KEY=...
AI_MODEL=gemini-3.5-flash-lite

# OpenAI
# AI_PROVIDER=openai
# AI_MODEL=gpt-4.1-mini

# Anthropic
# AI_PROVIDER=anthropic
# AI_MODEL=claude-sonnet-4-5

# Groq (low latency)
# AI_PROVIDER=groq
# AI_MODEL=llama-3.3-70b-versatile

# Local / privacy
# AI_PROVIDER=ollama
# AI_BASE_URL=http://localhost:11434/v1
# AI_MODEL=llama3.2

# Rule engine weight: 0 = rules only, 1 = AI only
AI_WEIGHT=0.35
# Blend the AI narrative with the rule engine's narrative, risks, and actions
AI_BLEND_WITH_HEURISTIC=true
AI_FALLBACK_TO_HEURISTIC=true
```

When `AI_BLEND_WITH_HEURISTIC=true`, the summary, rationale, risk, and action
lists written by the AI are merged with those produced by the deterministic rule engine;
one does not replace the other. The scoring formula does not change: ranking is still
based on the `final_score` weight above. `AIMetadata.blended` and
`AIMetadata.blend_weight` fields show whether blending was applied.

Geocoding and location page:

```env
GEOCODING_ENABLED=true
GEOCODING_BASE_URL=https://nominatim.openstreetmap.org
GEOCODING_LANGUAGE=en
GEOCODING_CACHE_TTL_SECONDS=86400
# Default address the /geo page will return to (can be a relative path)
UI_BASE_URL=/app/
```

Provider list: `GET /api/v1/ai-providers`. Detailed evaluation: [RAPOR.md](RAPOR.md).

---

## 7. Tests

```bash
python -m pytest -q
```

- NASA and LLM calls are mocked; **no internet or API key required**.
- Coverage: API contracts, scoring, agronomy, NASA client (including monthly→annual aggregation), rotation invariants, soil/water calculations, web interface and static assets, Streamlit smoke (if installed).
- `scripts/build.sh` does not produce a package without running tests (optional `--skip-tests`).

---

## 8. Project structure

```text
field-shift-app/
├─ app/
│  ├─ main.py                 # FastAPI factory, /app static mount, root HTML/JSON
│  ├─ config.py               # .env / environment variables
│  ├─ schemas.py              # Pydantic contracts (analyze, advice, farm-plan…)
│  ├─ api/routes.py           # /api/v1 endpoints
│  ├─ clients/
│  │  ├─ nasa_power.py        # NASA POWER client, retry, TTL cache, monthly→annual
│  │  └─ geocoding.py         # Nominatim reverse geocoding
│  ├─ domain/
│  │  ├─ crops.py             # 21 crops + TR/EN aliases
│  │  ├─ crop_meta.py         # icon, family, rotation traits
│  │  ├─ scoring.py           # explainable rule engine + rotation component
│  │  ├─ rotation.py          # multi-year crop rotation generator/scorer
│  │  ├─ soil_health.py       # 9-indicator soil scorecard
│  │  └─ water.py             # monthly water balance, ton/m³ conversion
│  ├─ services/
│  │  ├─ agronomy.py          # converts NASA data into an agronomic summary
│  │  ├─ recommendation.py    # shared NASA + rule pipeline
│  │  ├─ advice.py            # plain-language farmer plan
│  │  ├─ climate.py           # annual trend, risk level, plain-language messages
│  │  └─ farm_plan.py         # full plan orchestration in a single request
│  └─ ai/
│     ├─ base.py              # AI contract, prompts, JSON validation
│     ├─ heuristic.py         # keyless deterministic advisor
│     ├─ openai_compatible.py # OpenAI/Groq/Mistral/DeepSeek/Ollama
│     ├─ gemini.py
│     ├─ anthropic.py
│     ├─ factory.py
│     └─ provider_info.py
├─ web/                       # farmer PWA (no build step)
│  ├─ index.html
│  ├─ styles.css
│  ├─ app.js
│  ├─ sw.js                   # app-shell cache; never caches the API
│  ├─ manifest.webmanifest
│  └─ icons/
├─ ui/app.py                  # Streamlit expert/test interface
├─ tests/                     # mocks external services
├─ scripts/build.sh           # verify + test + dist package
├─ Dockerfile
├─ docker-compose.yml
├─ render.yaml                # Render blueprint
├─ Procfile
├─ Makefile
├─ .github/workflows/ci.yml   # test + Docker build + health smoke
├─ run.py
├─ requirements.txt
├─ requirements-ui.txt
├─ .env.example
├─ README.md
└─ RAPOR.md
```

---

## 9. Deployment

### Render (Blueprint)

1. In Render, choose **New → Blueprint** and connect this repository.
2. `render.yaml` defines the Docker service, the `/health` check, and environment variables.
3. The free plan may cold start; the first request can take 30-60 seconds.

### Docker / VPS

```bash
docker build -t tarla-dostu .
docker run -p 8000:8000 -e AI_PROVIDER=heuristic tarla-dostu
```

Behind a reverse proxy (nginx/Caddy), `--proxy-headers` is used. Location permission and the service worker require **HTTPS** (or `localhost`).

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Port to listen on |
| `ENVIRONMENT` | `development` | `production` recommended |
| `AI_PROVIDER` | `heuristic` | `gemini`, `openai`, `anthropic`, `groq`, `ollama`… |
| `AI_API_KEY` | — | AI key (optional) |
| `GEOCODING_ENABLED` | `true` | Nominatim reverse geocoding |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
| `NASA_POWER_*` | reasonable defaults | Timeout, cache, retry |
| `UI_BASE_URL` | `/app/` | `/geo` return address |

---

## 10. Limitations

- NASA POWER is **not a forecast**; it is retrospective climatology. The last 30 days of data may be delayed.
- The climate trend is the linear direction of the last ~25 years; it is **not** a CMIP6/NEX-GDDP scenario projection.
- Soil nutrients, pH, and organic matter do not come from NASA; farmer/laboratory data is required.
- There is no market price, local variety, disease/pest model, or irrigation schedule.
- **Free text does not change the ranking.** The rule engine uses structured fields; free text only enters the explanation.
- A map click selects a point; there is no parcel boundary (polygon) or automatic area calculation. The farmer enters the area in decares.
- Browser location and the service worker require `localhost` or HTTPS.
- Nominatim imposes a limit of 1 request per second; results are cached for 24 hours. Heavy use requires your own server.
- There is no authentication, database, rate limit, or persistent user history (the plan is stored only in the browser).
- AI output may be unverified; agronomist approval and soil analysis are essential.

Detailed risk list and roadmap: **[RAPOR.md](RAPOR.md)**.

---

## 11. License / attribution

- NASA POWER data is openly provided by NASA; for terms of use and attribution see <https://power.larc.nasa.gov/>.
- Map: © OpenStreetMap contributors; tiles are provided by the OpenStreetMap Foundation.
- Crop parameters and scoring weights are **approximate** values compiled for this project; they should be calibrated with local experts before commercial use.
- This software does not guarantee any yield, income, or profit.
