# Tarla Dostu — Project Alphecca

Çiftçiler için **NASA POWER verisi + açıklanabilir agronomi kuralları + değiştirilebilir LLM katmanı** ile çalışan karar destek uygulaması.

> **Telefonda aç, üç soruya cevap ver, ekim planını oku.**
> Uygulama artık tek bir adreste çalışır: **`/app/`** (yerelde <http://127.0.0.1:8000/app/>). Aynı FastAPI süreci hem JSON API'sini hem de çiftçi arayüzünü sunar. Streamlit arayüzü uzman/test modu olarak korunmuştur.

Arayüz sade Türkçe, büyük düğmeler, simgeler ve sesli okuma ile düşük okuryazarlıklı kullanıcılar için tasarlandı. Teknik ayrıntılar katlanır kutuların içinde; ana ekranda yalnızca "bu yıl ne ek, sonraki yıllar ne ek, toprağım ve suyum ne durumda" görünür.

---

## 1. Ne yapıyor?

Tek bir istek (`POST /api/v1/farm-plan`) şunları üretir:

1. **Bu yılın en iyi ürünü** — NASA iklim verisi + toprak + sulama + hedefe göre 0-100 puan.
2. **2, 3 veya 4 yıllık ekim nöbeti (rotasyon)** — ilk yıl mevcut yılın önerisiyle başlar; aynı familyayı üst üste koymaz, baklagil/anız/kök çeşitliliğini ödüllendirir, su ihtiyacını hesaplar.
3. **Toprak sağlığı karnesi (A–D)** — organik madde, pH, bünye, tuzluluk, drenaj, NASA toprak nemi/sıcaklığı, eğim ve rotasyon çeşitliliği olmak üzere 9 gösterge; eksik veriyi açıkça söyler.
4. **Su karnesi** — aylık yağış/buharlaşma dengesi, sezonluk açık; **dönüm başına ton** ve tarla toplamı m³ olarak.
5. **İklim eğilimi** — NASA POWER aylık verisinden 2001'den bugüne yıllıklaştırılmış sıcaklık/yağış eğilimi ve kuraklık riski. *Tahmin değil, geçmiş verinin yönü.*
6. **Sade dilli yapılacaklar** — ilk adımlar, yetiştirme, gübreleme, bakım, riskler ve alternatif ürünler.
7. **Belirsizlik ve sınırlar** — veri boşlukları, uyarılar, veri kaynakları ve yasal sorumluluk reddi.

AI (Gemini, OpenAI, Claude, Groq, Mistral, DeepSeek, Ollama…) yalnızca **açıklamayı** yazar. Sıralamayı deterministik kural motoru belirler; AI anahtarı yoksa uygulama eksiksiz çalışır.

### Çiftçi web uygulaması (`/app/`)

- **3 adımlı sihirbaz:** konum → tarla/su → hedef. Haritaya dokunma, tarayıcı konumu veya 25 il kısayolu.
- **Harita:** Leaflet + OpenStreetMap; tarla işaretçisi, ters coğrafi kodlama (Nominatim).
- **Büyük dokunma hedefleri** ve `A+` yazı büyütme; `prefers-reduced-motion` ve yüksek kontrast desteği.
- **Sonuç ekranı:** yıl yıl ekim zaman çizelgesi, puan karnesi, toprak/su/iklim kartları, işaretlenebilir yapılacaklar listesi.
- **Dinle** (tarayıcı sesi, `tr-TR`), **Yazdır**, **Paylaş** (Web Share / panoya kopyala), **JSON indir**.
- **Çevrimdışı:** uygulama kabuğu service worker ile önbelleğe alınır; son plan `localStorage`'da saklanır ve internetsiz açılabilir. Yeni plan için bağlantı gerekir.
- **PWA:** ana ekrana eklenebilir (`manifest.webmanifest`, maskelenebilir ikonlar).
- **Erişilebilirlik:** klavye odağı, `aria-live` durum mesajları, Renk + simge + metin birlikte kullanılır.

### Önemli veri gerçeği

NASA POWER **toprak verimliliği / N-P-K / pH / organik madde sağlamaz.** Yalnızca grid tabanlı iklim, toprak nemi ve toprak sıcaklığı proxy'leri sağlar. Bu nedenle:

- pH, organik madde, tuzluluk ve doku **çiftçi girdisi** olarak alınır; boş bırakılabilir.
- Besin analizi eksikse API bunu `data_gaps` ve `notes` alanlarında açıkça söyler.
- NASA POWER çözünürlüğü ~0.5° × 0.625°'dir; tarla ölçeğinde değildir.
- İklim eğilimi geçmiş yılların doğrusal yönüdür; resmî iklim projeksiyonu değildir.

---

## 2. Hızlı başlangıç

### Linux / macOS

```bash
git clone https://github.com/Kaan364/field-shift-app.git
cd field-shift-app

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# İstersen AI anahtarı ekle; gerekmiyor.
cp .env.example .env

python run.py
# veya: uvicorn app.main:app --reload
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

Açılacak adresler:

| Adres | Ne gösterir |
|---|---|
| <http://127.0.0.1:8000/app/> | **Çiftçi uygulaması** (telefon uyumlu) |
| <http://127.0.0.1:8000/> | Tarayıcıda çiftçi uygulaması, API istemcisinde JSON API özeti |
| <http://127.0.0.1:8000/docs> | Swagger / OpenAPI |
| <http://127.0.0.1:8000/health> | Sağlık durumu |

### Docker

```bash
docker compose up --build
# http://127.0.0.1:8000/app/
```

### Tek komutla doğrula + paketle

```bash
./scripts/build.sh          # sözdizimi + testler + dist/ paketi
make test                   # yalnızca testler
make run                    # geliştirme sunucusu
make docker                 # imaj derle
```

`scripts/build.sh` sonunda `dist/tarla-dostu-<sürüm>-<tarih>.tar.gz` ve SHA-256 dosyası oluşur. Paket, `app/` + `web/` + bağımlılıkların tarifini içerir; hedef makinede `pip install -r requirements.txt` ve `uvicorn app.main:app` ile çalışır. Ön yüz derleme adımı yoktur (vanilla HTML/CSS/JS).

---

## 3. Streamlit uzman arayüzü (isteğe bağlı)

Backend'i ve eski uzman arayüzünü birlikte başlatır:

```bash
python -m pip install -r requirements-ui.txt
python run_ui.py
# http://127.0.0.1:8501
```

- Backend zaten açıksa: `python run_ui.py --no-backend`
- Farklı portlar: `python run_ui.py --api-port 8001 --ui-port 8502`
- Sekmeler: Analiz, Çevre Verisi, Ürün Kataloğu (21 ürün), AI Sağlayıcıları, Sistem & Konsol.

Çiftçi için önerilen arayüz artık `/app/` altındaki PWA'dır; Streamlit daha çok API'yi elle denemek ve uzman çıktısını görmek içindir.

---

## 4. API

| Metot | Yol | Açıklama |
|---|---|---|
| `GET` | `/` | Tarayıcıya HTML uygulama, API istemcisine JSON özet |
| `GET` | `/app/` | Çiftçi PWA'sı (statik) |
| `GET` | `/health`, `/api/v1/health` | Sağlık, AI sağlayıcısı, cache durumu |
| `GET` | `/api/v1/environment?latitude=..&longitude=..` | NASA verisinden iklim/toprak özeti |
| `GET` | `/api/v1/crops` | 21 ürünün parametreleri, simgesi ve familyası |
| `GET` | `/api/v1/ai-providers` | AI sağlayıcı karşılaştırması |
| `POST` | `/api/v1/analyze` | Tam analiz ve sıralı öneriler |
| `POST` | `/api/v1/advice` | Serbest metinli çiftçi sorusuna sade dilli plan |
| `POST` | `/api/v1/farm-plan` | **Tam plan:** öneri + rotasyon + toprak + su + iklim |
| `POST` | `/api/v1/rotation` | Yalnızca ekim nöbeti |
| `POST` | `/api/v1/soil-health` | Yalnızca toprak sağlığı |
| `POST` | `/api/v1/water-plan` | Yalnızca su dengesi |
| `GET` | `/api/v1/reverse-geocode?latitude=..&longitude=..` | Koordinat → yer adı (Nominatim) |
| `GET` | `/geo?next=/app/` | Tarayıcıdan konum izni isteyen yardımcı sayfa |

### Tek istekle tam plan

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

Yanıtın ana bölümleri:

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

> Örnek değerler NASA verisine ve girdilere göre değişir. Tam şema: `/docs` veya `/openapi.json`.

### Eski `analyze` isteği

`POST /api/v1/analyze` iç içe `field` / `resources` / `preferences` yapısını kullanır. `farm-plan`, `advice` ve yeni uçlar düz alanları (`area_hectares`, `soil_ph`, `irrigation`, `goal` …) kabul eder. Her iki sözleşme de geriye dönük uyumludur.

### Hata kodları

| Kod | Anlam |
|---|---|
| `422` | Girdi doğrulama hatası veya filtrelere uyan ürün kalmadı (`no_candidates`) |
| `502` | NASA POWER'a ulaşılamadı (`nasa_power_unavailable`) |
| `503` | AI sağlayıcısı yanıt veremedi ve fallback kapalı (`ai_unavailable`) |

---

## 5. Puanlama ve modeller

### Tek ürün puanı

Dokuz bileşen hesaplanır; eksik veri varsa o bileşen ağırlıklandırmadan çıkarılır:

| Bileşen | Ağırlık | Ne ölçer? |
|---|---:|---|
| Sıcaklık | %20 | Ürünün sezonluk sıcaklık aralığı |
| Su dengesi | %24 | Sezon yağışı + sulama arzı / sezonluk su ihtiyacı |
| Toprak pH'ı | %10 | pH optimum ve tolerans aralığı |
| Toprak dokusu | %10 | Doku grubu uyumu |
| Tuzluluk | %4 | EC eşiği ve tolerans |
| İklim riski | %10 | Don, sıcak stresi, kuraklık sınıfı |
| Hedefe uygunluk | %14 | Verim, kâr, az su, organik, toprak sağlığı vb. |
| Pazar | %5 | Pazar talebi ve erişim |
| Ekim takvimi | %3 | Çiftçinin planladığı ay |

```text
rule_score  = ağırlıklı bileşen ortalaması (0-100)
final_score = (1 - AI_WEIGHT) * rule_score + AI_WEIGHT * ai_score
```

### Rotasyon puanı

Hedefe göre ağırlıklar değişir ve her zaman 1.0'a toplanır:

| Bileşen | Ne ödüllendirir? |
|---|---|
| Toprak sağlığı | Baklagil, anız örtüsü, familya çeşitliliği, farklı kök derinliği |
| Su | Toplam su ihtiyacının yağış + sulama ile karşılanması, kuraklığa dayanıklılık |
| İklim dayanıklılığı | Familya çeşitliliği, hastalık/zararlı baskısının kırılması |
| Kâr potansiyeli | Brüt marj, pazar talebi, verim potansiyeli |
| Risk güvenliği | Yüksek su ihtiyacı, yüksek azot ihtiyacı, zayıf uyum cezaları |

Rotasyon **yıl 1'i mevcut yılın en iyi ürününe sabitler**; böylece çok yıllık plan tek yıllık öneriyle çelişmez. Aynı ürün tekrar etmez, aynı familya üst üste gelmez, çok yıllık ürünler (bağ, zeytin, elma) yıllık rotasyona sokulmaz.

### Su dönüşümü

1 mm su × 1 dönüm (1.000 m²) = 1 m³ = **1 ton**. API hem `deficit_mm`, hem `deficit_m3`, hem `deficit_ton_per_decare` döndürür.

> Tüm puanlar **ön eleme** amaçlıdır; resmî verim tahmini, finansal model veya garanti değildir.

---

## 6. AI sağlayıcısı yapılandırma

Varsayılan `heuristic` moddur: internet, API anahtarı ve ücret gerektirmez. **AI anahtarı zorunlu değildir.**

```env
# Gemini (önerilen başlangıç)
AI_PROVIDER=gemini
AI_API_KEY=...
AI_MODEL=gemini-3.5-flash-lite

# OpenAI
# AI_PROVIDER=openai
# AI_MODEL=gpt-4.1-mini

# Anthropic
# AI_PROVIDER=anthropic
# AI_MODEL=claude-sonnet-4-5

# Groq (düşük gecikme)
# AI_PROVIDER=groq
# AI_MODEL=llama-3.3-70b-versatile

# Yerel / gizlilik
# AI_PROVIDER=ollama
# AI_BASE_URL=http://localhost:11434/v1
# AI_MODEL=llama3.2

# Kural motoru ağırlığı: 0 = sadece kurallar, 1 = sadece AI
AI_WEIGHT=0.35
AI_FALLBACK_TO_HEURISTIC=true
```

Coğrafi kodlama ve konum sayfası:

```env
GEOCODING_ENABLED=true
GEOCODING_BASE_URL=https://nominatim.openstreetmap.org
GEOCODING_LANGUAGE=tr
GEOCODING_CACHE_TTL_SECONDS=86400
# /geo sayfasının döneceği varsayılan adres (göreli yol olabilir)
UI_BASE_URL=/app/
```

Sağlayıcı listesi: `GET /api/v1/ai-providers`. Ayrıntılı değerlendirme: [RAPOR.md](RAPOR.md).

---

## 7. Testler

```bash
python -m pytest -q
```

- NASA ve LLM çağrıları taklit edilir; **internet veya API anahtarı gerekmez**.
- Kapsam: API sözleşmeleri, puanlama, agronomi, NASA istemcisi (aylık→yıllık toplama dahil), rotasyon değişmezleri, toprak/su hesapları, web arayüzü ve statik varlıklar, Streamlit smoke (kuruluysa).
- `scripts/build.sh` testleri çalıştırmadan paket üretmez (isteğe bağlı `--skip-tests`).

---

## 8. Proje yapısı

```text
field-shift-app/
├─ app/
│  ├─ main.py                 # FastAPI fabrikası, /app statik mount, kök HTML/JSON
│  ├─ config.py               # .env / ortam değişkenleri
│  ├─ schemas.py              # Pydantic sözleşmeleri (analyze, advice, farm-plan…)
│  ├─ api/routes.py           # /api/v1 uçları
│  ├─ clients/
│  │  ├─ nasa_power.py        # NASA POWER istemcisi, retry, TTL cache, aylık→yıllık
│  │  └─ geocoding.py         # Nominatim ters coğrafi kodlama
│  ├─ domain/
│  │  ├─ crops.py             # 21 ürün + TR/EN alias
│  │  ├─ crop_meta.py         # simge, familya, rotasyon özellikleri
│  │  ├─ scoring.py           # açıklanabilir kural motoru + rotasyon bileşeni
│  │  ├─ rotation.py          # çok yıllık ekim nöbeti üreteci/puanlayıcı
│  │  ├─ soil_health.py       # 9 göstergeli toprak karnesi
│  │  └─ water.py             # aylık su dengesi, ton/m³ dönüşümü
│  ├─ services/
│  │  ├─ agronomy.py          # NASA verisini agronomik özete çevirir
│  │  ├─ recommendation.py    # ortak NASA + kural hattı
│  │  ├─ advice.py            # sade dilli çiftçi planı
│  │  ├─ climate.py           # yıllık eğilim, risk düzeyi, sade mesajlar
│  │  └─ farm_plan.py         # tek istekte tam plan orkestrasyonu
│  └─ ai/
│     ├─ base.py              # AI sözleşmesi, prompt'lar, JSON doğrulama
│     ├─ heuristic.py         # anahtarsız deterministik danışman
│     ├─ openai_compatible.py # OpenAI/Groq/Mistral/DeepSeek/Ollama
│     ├─ gemini.py
│     ├─ anthropic.py
│     ├─ factory.py
│     └─ provider_info.py
├─ web/                       # çiftçi PWA'sı (derleme adımı yok)
│  ├─ index.html
│  ├─ styles.css
│  ├─ app.js
│  ├─ sw.js                   # uygulama kabuğu önbelleği; API'yi asla önbelleklemez
│  ├─ manifest.webmanifest
│  └─ icons/
├─ ui/app.py                  # Streamlit uzman/test arayüzü
├─ tests/                     # dış servisler mock
├─ scripts/build.sh           # doğrula + test + dist paketi
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

## 9. Dağıtım

### Render (Blueprint)

1. Render'da **New → Blueprint** seçip bu depoyu bağla.
2. `render.yaml` Docker servisini, `/health` kontrolünü ve ortam değişkenlerini tanımlar.
3. Ücretsiz plan soğuk başlangıç yapabilir; ilk istek 30-60 saniye sürebilir.

### Docker / VPS

```bash
docker build -t tarla-dostu .
docker run -p 8000:8000 -e AI_PROVIDER=heuristic tarla-dostu
```

Ters proxy (nginx/Caddy) arkasında `--proxy-headers` kullanılır. Konum izni ve service worker **HTTPS** (veya `localhost`) gerektirir.

### Ortam değişkenleri

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `PORT` | `8000` | Dinlenecek port |
| `ENVIRONMENT` | `development` | `production` önerilir |
| `AI_PROVIDER` | `heuristic` | `gemini`, `openai`, `anthropic`, `groq`, `ollama`… |
| `AI_API_KEY` | — | AI anahtarı (opsiyonel) |
| `GEOCODING_ENABLED` | `true` | Nominatim ters kodlama |
| `CORS_ORIGINS` | `*` | Virgülle ayrılmış izinli kaynaklar |
| `NASA_POWER_*` | makul varsayılanlar | Zaman aşımı, cache, retry |
| `UI_BASE_URL` | `/app/` | `/geo` dönüş adresi |

---

## 10. Sınırlamalar

- NASA POWER **tahmin değil**, geçmişe dönük klimatolojidir. Son 30 gün verisi gecikmeli olabilir.
- İklim eğilimi son ~25 yılın doğrusal yönüdür; CMIP6/NEX-GDDP senaryo projeksiyonu **değildir**.
- Toprak besinleri, pH ve organik madde NASA'dan gelmez; çiftçi/laboratuvar verisi gerekir.
- Pazar fiyatı, yerel çeşit, hastalık/zararlı modeli ve sulama programı yoktur.
- **Serbest metin sıralamayı değiştirmez.** Kural motoru yapılandırılmış alanları kullanır; serbest metin yalnızca açıklamaya girer.
- Harita tıklaması nokta seçer; parsel sınırı (polygon) ve otomatik alan hesabı yoktur. Alanı çiftçi dönüm olarak girer.
- Tarayıcı konumu ve service worker `localhost` veya HTTPS gerektirir.
- Nominatim saniyede 1 istek sınırı koyar; sonuçlar 24 saat önbelleğe alınır. Yoğun kullanımda kendi sunucunuz gerekir.
- Kimlik doğrulama, veritabanı, rate limit ve kalıcı kullanıcı geçmişi yoktur (plan yalnızca tarayıcıda saklanır).
- AI çıktısı doğrulanmamış olabilir; agronomist onayı ve toprak analizi şarttır.

Ayrıntılı risk listesi ve yol haritası: **[RAPOR.md](RAPOR.md)**.

---

## 11. Lisans / atıf

- NASA POWER verileri NASA tarafından açık olarak sunulur; kullanım ve atıf koşulları için <https://power.larc.nasa.gov/>.
- Harita: © OpenStreetMap katkıcıları; karolar OpenStreetMap Foundation tarafından sunulur.
- Ürün parametreleri ve puanlama ağırlıkları bu proje için derlenmiş **yaklaşık** değerlerdir; ticari kullanımdan önce yerel uzmanlarla kalibre edilmelidir.
- Bu yazılım hiçbir verim, gelir veya kâr garantisi vermez.
