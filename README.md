# Project Alphecca

Çiftçiler için **NASA POWER verisi + açıklanabilir agronomi kuralları + değiştirilebilir LLM katmanı** ile çalışan, Python/FastAPI tabanlı karar destek backend'i.

> Çekirdek ürün **backend**'dir. Üzerine, tüm işlevleri tarayıcıdan denemek için hafif bir **Streamlit arayüzü** eklendi (`ui/app.py`). Arayüz iş mantığı içermez; yalnızca JSON API'sine istek atar. Üretim arayüzü yine bu API'nin üzerine kurulabilir.

Arayüzün ön yüzü **çiftçi için** tasarlandı: haritadan tarla seçimi, üç basit soru, isteğe bağlı serbest metin ve tek düğme. Ayrıntılı iklim/toprak verisi ve puan kırılımı yalnızca "Detaylı bilgi" kutusu işaretlenince görünür.

---

## 1. Ne yapıyor?

1. Çiftçiden konum (lat/lon), tarla bilgisi (toprak dokusu, pH, organik madde, tuzluluk), kaynaklar (sulama, su, bütçe) ve tercihler (hedef, ilgi/hariç ekinler, ekim ayı) alır.
2. **NASA POWER** API'sinden 25 yıllık aylık iklim klimatolojisini ve son 30 günün günlük hava/toprak nemi verisini çeker.
3. Veriyi normalize eder: sıcaklık, yağış, don/sıcak stresi, kuraklık sınıfı, toprak nemi/sıcaklığı, sezonluk su dengesi.
4. 16 ekinlik şeffaf bir kural motoruyla **0-100 uygunluk puanı** ve bileşen kırılımı üretir.
5. Seçilen AI sağlayıcısı (Gemini, OpenAI, Claude, Groq, Mistral, DeepSeek, yerel Ollama...) adayları yeniden değerlendirir; gerekçe, risk ve aksiyon üretir.
6. Nihai puan `%65 kural + %35 AI` olarak birleştirilir; AI çökerse deterministik motor devreye girer.
7. Sonuç: sıralı ekin önerileri, gerekçeler, riskler, uygulanabilir aksiyonlar, veri kaynakları, uyarılar ve yasal sorumluluk reddi.

### Çiftçi akışı (`POST /api/v1/advice`)

Bu uç, "ben ne ekeceğimi bilmiyorum" diyen bir çiftçi için tasarlandı:

1. Çiftçi haritadan tarlasını seçer (veya tarayıcı konum iznini verir) ve 3-4 basit soruyu yanıtlar.
2. İsterse kendi cümleleriyle derdini yazar (serbest metin, en fazla 2000 karakter).
3. Sunucu NASA POWER verisini çeker ve kural motoru adayları puanlar.
4. AI **yalnızca açıklama** yazar: ne ekmeli, nasıl büyütmeli, nasıl beslemeli, nasıl bakmalı, riskler ve eksik bilgiler.
5. AI anahtarı yoksa veya hata verirse aynı yapı deterministik şablonla üretilir; istek yine başarılı döner.

Bu akışta AI'nın sıralamaya etkisi **yoktur**: `final_score == rule_score`. AI yeni bir ekin adı uyduramaz; aday listesi dışındaki isimler ayıklanır.

### Önemli veri gerçeği

NASA POWER **toprak verimliliği / N-P-K / pH / organik madde sağlamaz.** Yalnızca grid tabanlı iklim, toprak nemi ve toprak sıcaklığı proxy'leri sağlar. Bu nedenle:

- pH, organik madde, tuzluluk ve doku **çiftçi girdisi** olarak alınır.
- Besin analizi eksikse API bunu `data_gaps` ve `notes` alanlarında açıkça söyler.
- NASA POWER çözünürlüğü ~0.5° × 0.625°'dir; tarla ölçeğinde değildir.

---

## 2. Hızlı başlangıç (Windows PowerShell)

```powershell
cd "$env:USERPROFILE\Desktop\Project Alphecca"

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

Copy-Item .env.example .env
# İsterseniz .env içinde AI_PROVIDER / AI_API_KEY ayarlayın.
# Hiç anahtar yoksa deterministik motor çalışır.

python run.py
```

- Swagger: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>
- Alternatif: `.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload`

---

## 2.1 Test arayüzü (Streamlit)

Backend'i ve arayüzü **tek komutla** başlatır:

```powershell
cd "$env:USERPROFILE\Desktop\Project Alphecca"
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
.\.venv\Scripts\python.exe run_ui.py
```

- Arayüz: <http://127.0.0.1:8501>
- Backend zaten açıksa: `python run_ui.py --no-backend`
- Farklı portlar: `python run_ui.py --api-port 8001 --ui-port 8502`

`run_ui.py` backend ayakta değilse kendisi başlatır, arayüz kapanınca yalnızca kendi başlattığı backend'i durdurur.

### Arayüz: çiftçi modu + uzman modu

**Çiftçi modu (varsayılan, üstte):**

1. **Harita.** OpenStreetMap üzerinde tarlaya dokunulur; nokta ve ~1,2 km'lik alan işaretlenir.
   Koordinat, OpenStreetMap Nominatim ile yer adına çevrilip gösterilir (API anahtarı gerekmez).
2. **Tarayıcı konumu.** "📍 Konumumu otomatik bul" düğmesi `/geo` sayfasını açar; izin verilirse
   `?lat=..&lon=..` ile arayüze döner ve harita oraya taşınır. (iframe'ler konum izni isteyemediği
   için ayrı bir sayfa kullanılır.)
3. **Üç basit soru.** Tarla büyüklüğü (dönüm), sulama imkânı, hedef ve ekim ayı.
   Toprak dokusu/pH/organik madde isteğe bağlı bir bölümde; bilinmiyorsa boş bırakılır.
4. **Serbest metin.** "Ne ekeceğimi bilmiyorum, nasıl bakacağımı da bilmiyorum" gibi kendi cümleleri.
   "📝 Örnek yazıyı doldur" düğmesi örnek metni yazar.
5. **Tek düğme.** "🌾 Bana ne ekeceğimi söyle" → kısa başlık, 3 ürün, ardından
   "İlk yapman gerekenler / Nasıl büyütürüm / Nasıl beslerim / Nasıl bakarım / Dikkat et" başlıkları.
6. **Detay kutusu.** "🔍 Detaylı bilgi göster (iklim, toprak, puanlar)" işaretlenirse aylık iklim
   tablosu, grafikler, toprak nemi/sıcaklığı, puan kırılımı, uyarılar ve ham JSON açılır.

**Uzman / test modu (altta, kapalı başlar):** tüm API uçlarını elle denemek için 5 sekme.

| Sekme | Test ettiği uçlar | Ne yapar |
|---|---|---|
| 🌱 Analiz | `POST /api/v1/analyze` | Konum, toprak, kaynak, tercih formu → sıralı öneriler, puan kırılımı, riskler, aksiyonlar, çevre verisi, ham JSON |
| 🌦️ Çevre Verisi | `GET /api/v1/environment` | Sadece NASA iklim/toprak özeti + aylık tablo ve grafikler |
| 🌾 Ürün Kataloğu | `GET /api/v1/crops` | 16 ürünün parametreleri, arama/filtre, detay |
| 🤖 AI Sağlayıcıları | `GET /api/v1/ai-providers` | Sağlayıcı karşılaştırması, güçlü/zayıf yönler |
| 🩺 Sistem & Konsol | `GET /`, `/health`, serbest GET/POST | Sağlık durumu, kök endpoint, elle API deneme |

Kenar çubuğunda API adresi, canlı bağlantı durumu ve Trakya/Ankara/İzmir gibi hazır konumlar bulunur.
Hazır konum seçimi yalnızca enlem/boylamı doldurur; `region_name` etikettir, hesap koordinata göre yapılır.

### Testler

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Testler NASA ve LLM çağrılarını taklit eder; internet veya API anahtarı gerektirmez.
Arayüz için ayrıca `tests/test_ui_smoke.py` çalışır: Streamlit sayfasının API kapalıyken bile çökmeden açıldığını doğrular.

---

## 3. API

| Metot | Yol | Açıklama |
|---|---|---|
| `GET` | `/` | API özeti ve örnek istek |
| `GET` | `/health` | Sağlık, AI sağlayıcısı, coğrafi kodlama, cache durumu |
| `GET` | `/api/v1/health` | Aynı sağlık kontrolü |
| `GET` | `/api/v1/environment?latitude=..&longitude=..` | NASA verisinden iklim/toprak özeti (öneri yok) |
| `GET` | `/api/v1/crops` | 16 ekinlik katalog |
| `GET` | `/api/v1/ai-providers` | AI sağlayıcı karşılaştırması |
| `POST` | `/api/v1/analyze` | Tam analiz ve sıralı öneriler |
| `POST` | `/api/v1/advice` | Serbest metinli çiftçi sorusuna sade dilli plan |
| `GET` | `/api/v1/reverse-geocode?latitude=..&longitude=..` | Koordinat → yer adı (Nominatim) |
| `GET` | `/geo?next=...` | Tarayıcıdan konum izni isteyen yardımcı sayfa (HTML) |

### Örnek istek

```python
import httpx

payload = {
    "location": {
        "latitude": 39.93,
        "longitude": 32.85,
        "region_name": "Ankara"
    },
    "field": {
        "area_hectares": 12.5,
        "soil_texture": "clay_loam",
        "soil_ph": 7.4,
        "organic_matter_pct": 1.8,
        "salinity_ds_m": 1.2
    },
    "resources": {
        "irrigation": "limited",          # rainfed | limited | full
        "water_availability": "medium",  # low | medium | high
        "budget_usd": 6000,
        "labor": "family",
        "mechanization": "medium"
    },
    "preferences": {
        "goal": "max_profit",             # max_yield | max_profit | low_water | low_input | organic | soil_health | risk_averse
        "crops_of_interest": ["wheat", "chickpea"],
        "excluded_crops": [],
        "planting_month": 10,
        "market_access": "medium",
        "max_growing_days": None
    },
    "top_n": 5,
    "language": "tr"                      # tr | en
}

response = httpx.post(
    "http://127.0.0.1:8000/api/v1/analyze",
    json=payload,
    timeout=120,
)
response.raise_for_status()
data = response.json()

for rec in data["recommendations"]:
    print(rec["rank"], rec["crop_name_local"], rec["scores"]["final_score"], rec["confidence"])
```

### Örnek yanıt (kısaltılmış)

```json
{
  "analysis_id": "…",
  "location": {"latitude": 39.93, "longitude": 32.85, "region_name": "Ankara"},
  "environment": {
    "climate": {
      "annual_mean_temp_c": 10.31,
      "annual_precip_mm": 418.2,
      "aridity_index": 0.243,
      "climate_class": "semi_arid",
      "frost_months": ["Ocak", "Şubat", "…"],
      "heat_stress_months": ["Mayıs", "…"]
    },
    "soil": {
      "root_zone_moisture_mean": 0.551,
      "soil_condition_score": 84.2,
      "soil_condition_label": "iyi",
      "data_gaps": ["NASA POWER besin elementleri (N-P-K) … sağlamaz; …"]
    },
    "recent_weather": {
      "window_days": 30,
      "available_days": 27,
      "total_precip_mm": 20.0,
      "longest_dry_spell_days": 11
    }
  },
  "recommendations": [
    {
      "rank": 1,
      "crop_key": "wheat",
      "crop_name_local": "Kışlık Buğday",
      "scores": {
        "rule_score": 93.7,
        "ai_score": 93.7,
        "final_score": 93.7,
        "components": {
          "temperature": 86.5,
          "water": 100.0,
          "ph": 100.0,
          "texture": 100.0,
          "salinity": null,
          "climate_risk": 88.0,
          "goal_fit": 71.9,
          "market": 92.0,
          "calendar": 100.0
        }
      },
      "rationale": "Kışlık Buğday, bölge koşullarında 93.7/100 uygunluk aldı. …",
      "risks": ["…"],
      "actions": ["…"],
      "planting_window": "Ekim–Kasım",
      "growing_days": 240,
      "water_need_mm": 450,
      "confidence": "medium"
    }
  ],
  "summary": "Ankara için mevcut verilerle en güçlü seçenek Kışlık Buğday …",
  "warnings": [],
  "data_sources": ["NASA POWER - Climatology", "…"],
  "ai": {
    "provider": "heuristic",
    "model": null,
    "kind": "deterministic",
    "used": true,
    "fallback_used": false,
    "latency_ms": 0
  },
  "disclaimer": "Bu çıktı bir karar destek aracıdır; verim, gelir veya kâr garantisi değildir. …"
}
```

> Not: Örnekteki bileşen değerleri tam olarak yukarıdaki istekle birebir aynı olmayabilir; NASA verisi ve ayarlarla değişir.

### Örnek: çiftçi sorusu (`POST /api/v1/advice`)

```json
{
  "location": {"latitude": 41.6771, "longitude": 26.5557, "region_name": "Edirne"},
  "area_hectares": 2.0,
  "irrigation": "limited",
  "goal": "max_profit",
  "planting_month": 10,
  "free_text": "Tarlam Edirne'de. Ne ekeceğimi bilmiyorum. Nasıl bakacağımı da bilmiyorum.",
  "top_n": 3,
  "language": "tr"
}
```

Yanıtın önemli kısmı (canlı NASA verisiyle üretilmiş gerçek çıktı):

```json
{
  "advice": {
    "headline": "Bu tarlada Kışlık Buğday ekmen en doğrusu. Alternatif: Arpa.",
    "why": "Bölgende yıllık yağış yaklaşık 613 mm, ortalama sıcaklık 13.7°C. Kışlık Buğday bu koşullarda 91.1/100 aldı (yarı kurak iklim).",
    "steps": ["Önce toprağını analiz ettir…", "Ekim zamanı: Ekim–Kasım…"],
    "grow": ["Tohum yatağı ince ve düz olsun…"],
    "feed": ["Gübreyi mutlaka toprak analizine göre ver…"],
    "care": ["Bu bitki sezon boyunca yaklaşık 450 mm su ister…"],
    "risks": ["…", "NASA verisi tarlanın tamamını değil, bölgeyi temsil eder."],
    "ask_farmer": ["Toprağının pH değerini biliyor musun?"],
    "confidence": "medium"
  },
  "recommendations": [
    {"rank": 1, "crop_key": "wheat", "scores": {"rule_score": 91.1, "ai_score": null, "final_score": 91.1}}
  ],
  "ai": {"provider": "heuristic", "kind": "deterministic", "used": true, "fallback_used": false},
  "environment": {"climate": {"annual_precip_mm": 613.0, "annual_mean_temp_c": 13.65}}
}
```

`ai.kind` değeri `deterministic` ise açıklamayı kural motoru yazmıştır; `llm` ise bir dil modeli yazmıştır
(sıralama yine kural motorundan gelir).

### Hata kodları

| Kod | Anlam |
|---|---|
| `422` | Girdi doğrulama hatası veya filtrelere uyan ekin kalmadı (`no_candidates`) |
| `502` | NASA POWER'a ulaşılamadı (`nasa_power_unavailable`) |
| `503` | AI sağlayıcısı yanıt veremedi ve fallback kapalı (`ai_unavailable`) |

---

## 4. AI sağlayıcısı yapılandırma

Varsayılan `heuristic` moddur: internet, API anahtarı ve ücret gerektirmez. **AI anahtarı zorunlu değildir**;
anahtar olmadan da tüm uçlar (analiz ve serbest metinli öneri) çalışır, yalnızca açıklamalar deterministik
şablonla üretilir.

```env
# Gemini (önerilen başlangıç)
# Kasım 2026 itibarıyla güncel stabil model: gemini-3.5-flash-lite
# gemini-2.5-flash 1 Aralık 2026'dan itibaren otomatik olarak 3.5-flash-lite'a yönlendiriliyor.
AI_PROVIDER=gemini
AI_API_KEY=...
AI_MODEL=gemini-3.5-flash-lite

# İsteğe bağlı: Gemini uç noktası / anahtar başlığı
# Kimlik doğrulama x-goog-api-key başlığıyla yapılır; kod bunu otomatik ekler.
# AI_BASE_URL=https://generativelanguage.googleapis.com/v1beta

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

> Gemini 3.x ailesinde bazı örnekleme parametreleri kaldırıldığı için kod, `temperature` değerini yalnızca
> `gemini-2*` modellerine gönderir. Model adını değiştirirseniz `GET /health` ile sağlayıcıyı doğrulayın.

Harita ve yer adı için ayrı anahtar gerekmez; OpenStreetMap Nominatim kullanılır:

```env
GEOCODING_ENABLED=true
GEOCODING_BASE_URL=https://nominatim.openstreetmap.org
GEOCODING_LANGUAGE=tr
GEOCODING_CACHE_TTL_SECONDS=86400
# Tarayıcı konum sayfasının geri döneceği varsayılan adres
UI_BASE_URL=http://127.0.0.1:8501
```

Sağlayıcı listesi ve karşılaştırma: `GET /api/v1/ai-providers`. Ayrıntılı değerlendirme için [RAPOR.md](RAPOR.md).

---

## 5. Puanlama mantığı

Her ekin için 9 bileşen hesaplanır; eksik veri varsa o bileşen ağırlıklandırmadan çıkarılır:

| Bileşen | Ağırlık | Ne ölçer? |
|---|---:|---|
| Sıcaklık | %20 | Ekinin sezonluk sıcaklık aralığı |
| Su dengesi | %24 | Sezon yağışı + sulama arzı / sezonluk su ihtiyacı |
| Toprak pH'ı | %10 | pH optimum ve tolerans aralığı |
| Toprak dokusu | %10 | Doku grubu uyumu |
| Tuzluluk | %4 | EC eşiği ve tolerans |
| İklim riski | %10 | Don, sıcak stresi, kuraklık sınıfı |
| Hedefe uygunluk | %14 | Verim, kâr, az su, organik, toprak sağlığı vb. |
| Pazar | %5 | Pazar talebi ve erişim |
| Ekim takvimi | %3 | Çiftçinin planladığı ay |

Nihai puan:

```text
rule_score  = ağırlıklı bileşen ortalaması (0-100)
final_score = (1 - AI_WEIGHT) * rule_score + AI_WEIGHT * ai_score
```

Sert agronomik sınırlar (aşırı sıcaklık, ciddi su açığı, pH dışı, dona hassas çok yıllık) puanı ayrıca çarpanla düşürür. AI yalnızca sıralamayı ve açıklamayı etkiler; kural motorunun temel agronomik mantığını silemez.

> Bu puanlama bir **ön eleme** aracıdır; resmî verim tahmini veya finansal model değildir.

---

## 6. Proje yapısı

```text
Project Alphecca/
├─ app/
│  ├─ main.py                 # FastAPI app factory, /geo konum sayfası, health, hata yönetimi
│  ├─ config.py               # .env / ortam değişkenleri (AI, NASA, geocoding, UI)
│  ├─ schemas.py              # Pydantic istek/yanıt sözleşmesi (analyze + advice)
│  ├─ api/routes.py           # /api/v1 uç noktaları
│  ├─ clients/
│  │  ├─ nasa_power.py        # NASA POWER istemcisi, cache, retry
│  │  └─ geocoding.py         # Nominatim ters coğrafi kodlama (TTL cache)
│  ├─ domain/
│  │  ├─ crops.py             # 16 ekinlik bilgi tabanı + TR/EN alias
│  │  └─ scoring.py           # açıklanabilir kural motoru
│  ├─ services/
│  │  ├─ agronomy.py          # NASA verisini agronomik özete çevirir
│  │  ├─ recommendation.py    # ortak NASA + kural hattı (prepare) ve /analyze
│  │  └─ advice.py            # serbest metinli çiftçi akışı (/advice)
│  └─ ai/
│     ├─ base.py              # AI sözleşmesi, prompt'lar, JSON doğrulama
│     ├─ heuristic.py         # anahtarsız deterministik danışman (analiz + öneri)
│     ├─ openai_compatible.py # OpenAI/Groq/Mistral/DeepSeek/Ollama...
│     ├─ gemini.py            # Google Gemini (gemini-3.5-flash-lite)
│     ├─ anthropic.py         # Anthropic Claude
│     ├─ factory.py           # sağlayıcı seçimi + fallback
│     └─ provider_info.py     # /ai-providers karşılaştırması
├─ ui/
│  └─ app.py                   # Streamlit arayüzü: harita + çiftçi akışı + uzman modu
├─ tests/                      # 64 test, dış servisler mock
├─ run.py                      # sadece backend
├─ run_ui.py                   # backend + arayüz (tek komut)
├─ requirements.txt            # backend bağımlılıkları
├─ requirements-ui.txt         # arayüz bağımlılıkları (streamlit, folium, streamlit-folium)
├─ .env.example
├─ README.md
└─ RAPOR.md                    # ayrıntılı değerlendirme ve eksikler
```

---

## 7. Sınırlamalar

- NASA POWER **tahmin değil**, geçmişe dönük klimatolojidir. Son 30 gün verisi de gecikmeli olabilir.
- Toprak besinleri, pH ve organik madde NASA'dan gelmez; çiftçi/laboratuvar verisi gerekir.
- İklim değişikliği projeksiyonu (CMIP6/NEX-GDDP) henüz yok; mevcut sürüm tarihsel baseline kullanır.
- Pazar fiyatı, yerel çeşit, hastalık/zararlı modeli ve sulama programı yoktur.
- **Serbest metin sıralamayı değiştirmez.** Kural motoru yalnızca yapılandırılmış alanları (konum, sulama, toprak, hedef, ay) kullanır. Serbest metin yalnızca AI açıklamasına ve eksik bilgi sorularına girer; bu yüzden çiftçi "sulama yok" yazıp formda "tam sulama" seçerse form kazanır.
- Harita tıklaması ~1,2 km yarıçaplı bir nokta seçer; parsel sınırı (polygon) çizimi ve alan hesabı yoktur. Alanı çiftçi dönüm olarak girer.
- Tarayıcı konumu `localhost` veya HTTPS gerektirir; bazı mobil tarayıcılar izin vermez. Bu durumda harita elle kullanılır.
- Nominatim saniyede 1 istek sınırı koyar; sonuçlar 24 saat önbelleğe alınır. Yoğun kullanımda kendi Nominatim sunucunuz veya ücretli bir harita servisi gerekir.
- Kimlik doğrulama, veritabanı, rate limit ve kalıcı geçmiş yoktur (üretim öncesi eklenmeli).
- AI çıktısı doğrulanmamış olabilir; agronomist onayı ve toprak analizi şarttır.

Ayrıntılı risk listesi, AI sağlayıcı karşılaştırması ve yol haritası: **[RAPOR.md](RAPOR.md)**.

---

## 8. Lisans / atıf

- NASA POWER verileri NASA tarafından açık olarak sunulur; kullanım ve atıf koşulları için <https://power.larc.nasa.gov/> kontrol edilmelidir.
- Ekin parametreleri ve puanlama ağırlıkları bu proje için derlenmiş **yaklaşık** değerlerdir; ticari kullanımdan önce yerel uzmanlarla kalibre edilmelidir.
- Bu yazılım hiçbir verim, gelir veya kâr garantisi vermez.
