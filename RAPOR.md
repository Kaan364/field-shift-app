# Project Alphecca — Teknik Rapor

**Tarih:** 14 Kasım 2026  
**Kapsam:** Python/FastAPI backend, NASA POWER entegrasyonu, açıklanabilir agronomi motoru, değiştirilebilir AI katmanı, testler ve değerlendirme.  
**Durum:** Çalışır backend + 44 otomatik test + canlı NASA doğrulaması. UI kapsam dışı (sonra eklenecek).

---

## 1. Yönetici özeti

Project Alphecca, bir çiftçinin konum ve tarla bilgilerini alıp NASA POWER iklim/toprak verisiyle birleştiren, 16 ekin arasından açıklanabilir bir puanlama yapan ve sonucu bir LLM ile gerekçelendiren bir karar destek backend'idir.

Teknik olarak en önemli karar şudur: **AI'ı tek başına "ekin seçici" yapmadım.** LLM'ler agronomik hesabı güvenilir biçimde yapamaz, olmayan toprak verisini uydurabilir ve her çağrıda farklı sonuç verebilir. Bu nedenle:

- Deterministik kural motoru **çıpanın %65'i**,
- LLM **açıklama ve yeniden değerlendirmenin %35'i**,
- LLM çökerse veya anahtar yoksa **tamamen çalışan deterministik yedek**,
- LLM yalnızca aday listesindeki ekinleri kullanabilir; JSON şeması ve `crop_key` allowlist'i ile sınırlandırılır.

Canlı doğrulamada Ankara (39.93, 32.85) için NASA POWER'dan 418.2 mm yıllık yağış, 10.31 °C ortalama sıcaklık ve `semi_arid` sınıfı alındı; ilk analiz ~2.4 s, cache'li analiz ~2 ms sürdü. Öneri sıralaması Kışlık Buğday → Arpa → Üzüm → Nohut → Kanola oldu (girdilere göre değişir).

**En kritik uyarı:** NASA POWER toprak verimliliği (N-P-K), pH veya organik madde sağlamaz. "NASA API'leriyle toprak verimliliğini çekmek" planın en büyük teknik yanılgısıydı; bu projede pH/organik madde/tuzluluk çiftçi girdisi olarak alınır ve eksikse açıkça uyarılır. Ayrıntılar Bölüm 8'de.

---

## 2. Ne teslim edildi?

### 2.1. Çalışan akış

```text
Çiftçi isteği (lat/lon + tarla + kaynaklar + tercihler)
        │
        ▼
NASA POWER
  ├─ Climatology (2001-2025, aylık)  → iklim + toprak nemi/sıcaklığı
  └─ Daily (son 30 gün)              → güncel bağlam (opsiyonel, hata olursa devam)
        │
        ▼
Agronomi katmanı
  ├─ yıllık yağış/sıcaklık, ET0 (Hargreaves), kuraklık sınıfı
  ├─ don ve sıcak stresi ayları
  ├─ toprak nemi/sıcaklığı ve koşul puanı
  └─ son 30 gün: yağış, kuraklık aralığı, min/max sıcaklık
        │
        ▼
Kural motoru (16 ekin)
  ├─ sezonluk sıcaklık, su dengesi, pH, doku, tuzluluk
  ├─ iklim riski, hedef uyumu, pazar, ekim takvimi
  └─ 0-100 rule_score + bileşen kırılımı + kısıtlar
        │
        ▼
AI katmanı (opsiyonel)
  ├─ Gemini / OpenAI / Claude / Groq / Mistral / DeepSeek / Ollama
  ├─ yalnızca aday crop_key'leri; JSON şema doğrulaması
  └─ hata/anahtar yoksa deterministik HeuristicProvider
        │
        ▼
Birleştirme
  final_score = 0.65 × rule_score + 0.35 × ai_score
        │
        ▼
JSON yanıt: sıralı öneriler + gerekçe + risk + aksiyon + uyarı + kaynak + disclaimer
```

**Serbest metinli çiftçi akışı (`/api/v1/advice`)** aynı hattın kısaltılmış halidir:

```text
Çiftçi: harita + 3 basit soru + "ne ekeceğimi bilmiyorum" yazısı
        │
        ▼
NASA POWER → agronomi katmanı → kural motoru (sıralama buradan gelir)
        │
        ▼
AI (varsa) → yalnızca AÇIKLAMA: headline, why, steps, grow, feed, care, risks, ask_farmer
        │     AI yoksa/hata verirse aynı yapı deterministik şablonla üretilir
        ▼
JSON: final_score == rule_score (AI sıralamayı değiştiremez)
```

### 2.2. Dosyalar

| Dosya | Görev |
|---|---|
| `app/main.py` | FastAPI app factory, CORS, request ID, hata yönetimi, health, `/geo` konum sayfası |
| `app/config.py` | `.env`/ortam değişkenleri, AI, NASA ve geocoding ayarları |
| `app/schemas.py` | Tüm istek/yanıt sözleşmeleri, doğrulama |
| `app/api/routes.py` | `/analyze`, `/advice`, `/environment`, `/reverse-geocode`, `/crops`, `/ai-providers` |
| `app/clients/nasa_power.py` | NASA istemcisi, `-999` temizliği, TTL cache, retry |
| `app/clients/geocoding.py` | Nominatim ters coğrafi kodlama, TTL cache, User-Agent |
| `app/services/agronomy.py` | NASA verisinden iklim/toprak özeti, ET0, sezon metrikleri |
| `app/domain/crops.py` | 16 ekin, TR/EN alias, katalog doğrulaması |
| `app/domain/scoring.py` | Açıklanabilir puanlama ve sert agronomik limitler |
| `app/services/recommendation.py` | Ortak NASA + kural hattı (`prepare`), `/analyze` orkestrasyonu |
| `app/services/advice.py` | Serbest metinli çiftçi akışı: kural sıralaması + sade dilli açıklama |
| `app/ai/*` | Sağlayıcı soyutlaması, prompt, JSON ayrıştırma, fallback |
| `ui/app.py` | Streamlit arayüzü: harita, çiftçi akışı, detay kutusu, uzman modu |
| `tests/*` | 62 test; NASA ve LLM mock'lu |
| `README.md` | Kurulum, API, örnekler |
| `RAPOR.md` | Bu rapor |

### 2.3. API uç noktaları

- `POST /api/v1/analyze` — tam analiz
- `POST /api/v1/advice` — serbest metinli çiftçi sorusuna sade dilli plan
- `GET /api/v1/environment` — NASA özeti (öneri olmadan)
- `GET /api/v1/reverse-geocode` — koordinat → yer adı (Nominatim)
- `GET /api/v1/crops` — ekin kataloğu
- `GET /api/v1/ai-providers` — AI karşılaştırması
- `GET /geo` — tarayıcı konum izni sayfası
- `GET /health` — sağlık, AI sağlayıcısı, geocoding, cache
- `GET /docs` — Swagger (geçici test UI'ı)

Hata sözleşmesi: `422` doğrulama/uygun ekin yok, `502` NASA erişilemez, `503` AI erişilemez ve fallback kapalı.

---

## 3. NASA POWER entegrasyonu

### 3.1. Kullanılan servisler

| Servis | Amaç |
|---|---|
| `GET /api/temporal/climatology/point` | 2001-2025 aylık iklim ve toprak nemi/sıcaklığı ortalamaları |
| `GET /api/temporal/daily/point` | Son 30 günün günlük sıcaklık, yağış, toprak nemi |

İstekler `community=AG`, `format=JSON` ve WGS84 koordinatlarla yapılır. `-999.0` dolgu değerleri `None`'a çevrilir; eksik günler hesaplamalara sokulmaz.

### 3.2. Kullanılan parametreler

| Parametre | Açıklama | Kullanım |
|---|---|---|
| `T2M` | 2 m ortalama sıcaklık | Sezon sıcaklığı, iklim özeti |
| `T2M_MAX` / `T2M_MIN` | Günlük max/min sıcaklık | Don ve sıcak stresi |
| `PRECTOTCORR` | Düzeltilmiş yağış | Su dengesi, kuraklık |
| `RH2M` | Bağıl nem | Bilgi amaçlı |
| `ALLSKY_SFC_SW_DWN` | Güneş radyasyonu | Bilgi amaçlı |
| `WS2M` | Rüzgar | Bilgi amaçlı |
| `GWETROOT` / `GWETTOP` | Kök bölgesi / üst toprak nemi | Toprak koşul puanı, kuraklık |
| `TS` | Toprak sıcaklığı | Toprak koşul puanı |
| `EVLAND` / `EVPTRNS` | Gerçek buharlaşma/evapotranspirasyon | Ham veri olarak istenir; kuraklık endeksinde **kullanılmaz** |

### 3.3. Kuraklık sınıfı ve ET0

NASA'nın `EVLAND`/`EVPTRNS` değerleri **gerçek** buharlaşmadır; aridity index için potansiyel/referans ET gerekir. Bu nedenle:

- Aylık `T2M`, `T2M_MAX`, `T2M_MIN` ve enlemden **Hargreaves-Samani ET0** hesaplanır.
- `aridity_index = yıllık yağış / yıllık ET0`.
- Sınıflar: `<0.05` hiper-kurak, `<0.20` kurak, `<0.50` yarı kurak, `<0.65` kuru-yarı nemli, `<1.0` nemli, `≥1.0` çok nemli.

Ankara örneğinde yıllık ET0 ~1724 mm ve indeks 0.243 → `semi_arid`. Hargreaves, özellikle geniş günlük sıcaklık aralığı olan karasal iklimlerde ET0'ı abartabilir; üretimde yerel FAO-56/istasyon verisiyle kalibre edilmelidir. Bu, raporda bilinçli bir yaklaşım olarak işaretlenmiştir.

### 3.4. NASA'nın sağlamadıkları

- Toprak besin elementleri (N-P-K), pH, organik madde, EC.
- Tarla ölçeğinde veri (grid ~0.5° × 0.625°, orta enlemde ~50 km).
- Hava **tahmini** (daily endpoint geçmiş/gecikmeli gözlemdir).
- Gelecek iklim projeksiyonu (CMIP6 senaryoları ayrı veri setidir).
- Pazar fiyatı, yerel çeşit, hastalık/zararlı baskısı.

Bu eksikler yanıtta `soil.data_gaps` ve `environment.notes` içinde açıkça belirtilir. Bu "şeffaflık" bilinçli bir tasarım kararıdır: çiftçiye eksik veriyle kesinlik numarası vermektense belirsizliği göstermek daha güvenlidir.

---

## 4. AI sağlayıcıları: karşılaştırma ve değerlendirme

### 4.1. Kısa karar

| Senaryo | Önerim | Neden |
|---|---|---|
| MVP / düşük maliyet / ilk sürüm | **Google Gemini 3.5 Flash-Lite** | Ücretsiz katman, düşük fiyat, iyi Türkçe, JSON modu, hızlı |
| Kalite ve JSON güvenilirliği öncelikli | **OpenAI GPT-4.1-mini** | Tutarlı yapılandırılmış çıktı, olgun ekosistem |
| Karmaşık agronomik akıl yürütme | **Anthropic Claude Sonnet** | Uzun bağlam, temkinli dil, güçlü akıl yürütme |
| Çok düşük gecikme | **Groq (Llama 3.3 70B)** | Gerçek zamana yakın yanıt |
| AB veri ikametgahı | **Mistral** | AB merkezli seçenekler, uygun maliyet |
| Gizlilik / çevrimdışı | **Ollama + Qwen2.5/Llama 3.3** | Veri dışarı çıkmaz, token ücreti yok |
| Çoklu model denemesi | **OpenRouter** | Tek anahtar, model karşılaştırma |
| Maliyet çok kritik, gizlilik esnek | **DeepSeek** | Çok düşük token maliyeti |

**Benim "en iyisi" değerlendirmem:** Bu ürün için en dengeli başlangıç **Gemini 3.5 Flash-Lite + deterministik fallback**'tir. Nedeni: tarımsal danışmanlık yüksek hacimli, çok dilli ve maliyet duyarlı bir iş; Gemini'nin ücretsiz katmanı ve JSON modu MVP'yi hızlı doğrulamaya izin verir. Ürün-pazar uyumu kanıtlandıktan sonra kalite kritik akışlarda GPT-4.1-mini veya Claude'a geçmek, ya da ikisini A/B test etmek mantıklıdır. Gizlilik regülasyonu olan ülkelerde Ollama/Azure OpenAI bölgesel dağıtım öne çıkar.

> **AI zorunlu değildir.** `AI_PROVIDER=heuristic` (varsayılan) ile tüm uç noktalar çalışır; açıklamalar deterministik şablonla üretilir. Anahtar eklenirse yalnızca açıklama kalitesi artar, sıralama değişmez.

> **Gemini model notu:** Kasım 2026 itibarıyla `gemini-2.5-flash` 1 Aralık 2026'dan itibaren `gemini-3.5-flash-lite`'a yönlendirilmektedir. Kod varsayılan olarak `gemini-3.5-flash-lite` kullanır, kimlik doğrulamayı `x-goog-api-key` başlığıyla yapar ve Gemini 3.x'te kaldırılan `temperature` parametresini yalnızca `gemini-2*` modellerine gönderir.

> Model adları, fiyatlar ve kotalar hızla değişir. Bu tablo Kasım 2026 itibarıyla niteliksel bir değerlendirmedir; üretim öncesi güncel fiyat/kota/veri politikası kontrol edilmelidir.

### 4.2. Ayrıntılı avantaj / dezavantaj tablosu

| Sağlayıcı / model | Avantajlar | Dezavantajlar | Maliyet | Gecikme | Gizlilik | Türkçe / JSON | En uygun |
|---|---|---|---|---|---|---|---|
| **Google Gemini 3.5 Flash-Lite** | Ücretsiz katman; çok düşük fiyat; 1M'a yakın bağlam; güçlü çok dillilik; yerleşik JSON modu; hızlı | Ücretsiz katmanda hız/veri kullanım koşulları değişken; bölgesel erişim kısıtları; model sürümleri sık değişir; bazen aşırı özgüvenli | $ (ücretsiz katman) | Düşük-orta | Google politikaları | Çok iyi / çok iyi | MVP, maliyet duyarlı üretim |
| **OpenAI GPT-4.1-mini / GPT-4.1** | En tutarlı structured output; güçlü araç çağırma; olgun SDK/ekosistem; iyi Türkçe | Ücretsiz katman yok; yüksek hacimde maliyet; veri ikametgahı/onay; kota yönetimi | $$ | Düşük-orta | OpenAI politikaları; kurumsal seçenekler | Çok iyi / çok yüksek | Kalite kritik üretim |
| **Anthropic Claude Sonnet / Haiku** | Güçlü akıl yürütme; uzun doküman; temkinli, riskten kaçınan dil; yüksek kaliteli Türkçe | Pahalı; ücretsiz katman yok; JSON için şema/tool desteği ek doğrulama ister | $$$ | Orta | Anthropic politikaları | Çok iyi / yüksek | Karmaşık senaryo, danışmanlık |
| **Groq (Llama 3.3 70B)** | Çok düşük gecikme; uygun fiyat; OpenAI uyumlu | Model çeşidi sınırlı; açık modelde Türkçe nüansı daha zayıf; hız sınırı | $ | Çok düşük | Groq politikaları | İyi / orta-yüksek | Sohbet, hızlı ön değerlendirme |
| **Mistral Small / Large** | AB veri seçenekleri; uygun fiyat; iyi çok dillilik; hızlı küçük modeller | Ekosistem daha küçük; en zor akıl yürütmede büyük model gerekir | $ | Düşük | AB seçenekleri | İyi / yüksek | AB veri ikametgahı |
| **DeepSeek V3 / R1** | Çok düşük maliyet; güçlü akıl yürütme; OpenAI uyumlu | Çin merkezli veri işleme; gizlilik/uyum riski; yoğunlukta gecikme; Türkçe tarım terminolojisi doğrulanmalı | $ | Orta | Yurt dışı; kurumsal onay şart | İyi / yüksek | Maliyet kritik, hassas olmayan veri |
| **xAI Grok** | Hızlı; güncel bilgi; OpenAI uyumlu | Tarıma özel değil; maliyet/kota belirsiz; Türkçe modelden modele değişir | $$ | Düşük | xAI politikaları | İyi / yüksek | İkincil sağlayıcı |
| **Together AI** | Açık modelleri uygun fiyatla barındırır; model çeşitliliği | Açık modellerde Türkçe değişken; kurumsal olgunluk daha az | $ | Düşük-orta | Sağlayıcı politikaları | Değişken / orta-yüksek | Açık model denemeleri |
| **OpenRouter** | Tek anahtarla çoklu model; kolay A/B; yedekleme | Aracı ücreti; gizlilik modele göre değişir; tek nokta bağımlılığı | $$ | Değişken | Modele göre | Değişken | Prototip, model karşılaştırma |
| **Ollama (yerel)** | Tamamen yerel/çevrimdışı; veri dışarı çıkmaz; token ücreti yok | Donanım (RAM/GPU) ve operasyon yükü; küçük modellerde Türkçe/akıl yürütme zayıf; güvenlik sizin sorumluluğunuz | Donanım | Donanıma bağlı | Tamamen yerel | Orta / orta | Gizlilik, saha/offline |
| **Hugging Face Inference** | Çok geniş model kataloğu; deneme kolaylığı; uygun fiyat | Cold start; kalite değişken; kota; üretim SLA'sı zayıf | $ | Orta-yüksek | Modele göre | Değişken | Deney, özel model |
| **Azure OpenAI / AWS Bedrock / Vertex** | Kurumsal uyum, bölgesel veri ikametgahı, SLA, özel ağ | Kurulum maliyeti; model seçimi sağlayıcıya bağlı; karmaşıklık | $$-$$$ | Düşük-orta | En güçlü kurumsal seçenekler | Çok iyi | Regüle pazarlar, kurumsal |

### 4.3. Neden sağlayıcı soyutlaması?

`AIProvider` arayüzü sayesinde aynı ürün kodu:

- OpenAI uyumlu herhangi bir servisle (`AI_PROVIDER=openai|groq|mistral|deepseek|xai|together|openrouter|ollama|custom`),
- Gemini ile (`AI_PROVIDER=gemini`),
- Claude ile (`AI_PROVIDER=anthropic`),
- hiçbiri olmadan (`AI_PROVIDER=heuristic`)

çalışır. Sağlayıcı değiştirmek kod değişikliği gerektirmez; yalnızca `.env` değişir. Bu, fiyat/kota/veri politikası değişimlerine karşı en önemli mimari sigortadır.

### 4.4. AI güvenlik önlemleri (uygulanan)

1. **Allowlist:** LLM yalnızca aday listesindeki `crop_key`'leri döndürebilir; bilinmeyenler filtrelenir.
2. **JSON şeması:** Pydantic ile doğrulama; bozuk JSON `AIProviderError`'a dönüşür.
3. **Deterministik çıpa:** Nihai puanın %65'i kural motorundan gelir.
4. **Fallback:** LLM hatasında analiz tamamen durmaz; deterministik danışman devreye girer.
5. **Token sınırı:** LLM'e en fazla 8 aday gönderilir; yanıt 1600 token ile sınırlıdır.
6. **Prompt sınırları:** Verilmeyen veriyi uydurmama, kesin verim/kâr garantisi vermeme, eksik veriyi belirtme talimatı.
7. **Şeffaflık:** Yanıtta `ai.provider`, `used`, `fallback_used`, `latency_ms`, `error` alanları döner.
8. **Disclaimer:** Her yanıtta yasal/sorumluluk reddi metni bulunur.

Bunlar hallucination'ı **azaltır, sıfırlamaz**. Üretimde ayrıca agronomist incelemesi ve değerlendirme seti gerekir.

---

## 5. Puanlama ve karar mantığı

### 5.1. Bileşenler

| Bileşen | Ağırlık | Hesap |
|---|---:|---|
| Sıcaklık | %20 | Ekinin sezonluk ortalama sıcaklık optimum/absolut aralığına lineer uyum |
| Su dengesi | %24 | `(sezon yağışı + sulama arzı) / sezonluk su ihtiyacı`; kuraklık toleransı açığı yumuşatır |
| pH | %10 | pH optimum ve tolerans aralığı |
| Doku | %10 | Doku grubu (hafif/orta/ağır) mesafesi |
| Tuzluluk | %4 | EC eşiği; ekin toleransına göre |
| İklim riski | %10 | Donlu ay sayısı, sıcak stresi ay sayısı, kuraklık sınıfı |
| Hedefe uygunluk | %14 | Verim/kâr/az su/az girdi/organik/toprak sağlığı/riskten kaçınma |
| Pazar | %5 | Talep endeksi; pazar erişimi düşükse tavan |
| Ekim takvimi | %3 | Çiftçinin ayı ile ekinin ekim penceresi mesafesi |

Eksik veri varsa ilgili bileşen paydadan çıkarılır (yeniden ağırlıklandırma). Örneğin pH girilmediyse pH puanı "70 varsayılanı" ile skoru kirletmez; sadece hesaplama dışı kalır. Bu, veri eksikliğinde yanlış kesinlik üretmemek için önemlidir.

### 5.2. Sert limitler

Aşağıdaki durumlarda puan çarpanla düşürülür:

- Sezon sıcaklığı ekinin absolut sınırının dışında → `×0.35`
- Su dengesi sıfır ve sulama yok → `×0.50`
- pH absolut sınır dışında → `×0.65`
- 3+ donlu ay ve dona çok hassas çok yıllık → `×0.55`
- 3+ sıcak stresi ayı ve sıcağa çok hassas → `×0.75`

### 5.3. AI birleştirme

```text
final_score = 0.65 × rule_score + 0.35 × ai_score
```

`AI_WEIGHT` ortam değişkeniyle 0-1 arasında ayarlanabilir. `AI_WEIGHT=0` tamamen deterministik, `1` tamamen AI demektir. Varsayılan 0.35, AI'ın sıralamayı tamamen ele geçirmesini engellerken yorum katmasına izin verir.

### 5.4. Neden bu yaklaşım?

- **Açıklanabilirlik:** Her önerinin bileşen kırılımı var; çiftçi "neden bu ekin?" sorusunun cevabını görebilir.
- **Tutarlılık:** Aynı girdi aynı kural puanını verir; LLM sürüm değişse bile çıpa sabit kalır.
- **Maliyet:** LLM yalnızca 8 aday ve kısa bağlamla çağrılır.
- **Güvenlik:** LLM'in olmayan toprak verisini uydurması skoru tek başına belirleyemez.

### 5.5. Serbest metinli akışta AI neden sıralamaya karışmıyor?

`/api/v1/advice` akışında `final_score = rule_score` olarak sabitlenir ve `ai_score = null` döner. Nedeni:

- Çiftçinin yazdığı metin **yapılandırılmamıştır**; "sulama yok" gibi bir cümle ile formdaki "tam sulama" seçimi çelişebilir.
- Aynı cümlenin farklı modellerde farklı yorumlanması, aynı tarla için farklı sıralama üretir. Bu, tarımsal karar için kabul edilemez bir oynaklıktır.
- Bu yüzden metin yalnızca **açıklama** katmanına ve "eksik bilgi" sorularına girer. Sıralamayı belirleyen tek şey yapılandırılmış alanlar + NASA verisidir.
- AI'ın uydurma ekin adı önermesi `parse_advice` + aday allowlist ile engellenir; bilinmeyen isim `risks` alanına "doğrulanamayan bitki adı ayıklandı" notuyla düşer.

### 5.6. Kural motoru veri doğruluğunu doğrular mı?

**Hayır.** Kural motoru bir *tutarlılık ve makullük* denetimidir, bir *veri doğrulama* aracı değildir. Ayırt edilmesi gereken üç katman:

| Katman | Kural motoru ne yapar? | Ne yapamaz? |
|---|---|---|
| NASA POWER verisi | Değerleri agronomik aralıklara göre yorumlar (ör. 613 mm yağış → yarı kurak) | Sensör/uydu hatasını, grid ortalamasının tarla gerçeğinden sapmasını tespit edemez |
| Çiftçi girdisi (pH, organik madde, doku) | Aralık ve tutarlılık kontrolü (pH 3.5-10, tuzluluk eşikleri) | Çiftçinin yanlış beyanını yakalayamaz; ölçümün doğruluğunu bilemez |
| Öneri sonucu | Sert agronomik limitlerle bariz hataları engeller (dona hassas bitkiyi 3 donlu aya koymaz) | Verim, fiyat veya kâr garantisi veremez; yerel çeşit/hastalık bilgisini bilemez |

Yani kural motoru **"bu öneri saçma mı?"** sorusunu yanıtlar, **"bu veri doğru mu?"** sorusunu değil. Veri doğruluğu için gerekenler: toprak analizi (pH/OM/N-P-K), yerel meteoroloji istasyonu veya daha yüksek çözünürlüklü uydu verisi, çiftçi beyanının uzman tarafından doğrulanması ve sezon sonunda verim geri bildirimi.

---

## 6. Testler ve doğrulama

### 6.1. Otomatik testler

```text
64 passed
```

| Test dosyası | Kapsam | Adet |
|---|---|---:|
| `test_nasa_power.py` | JSON ayrıştırma, `-999` temizliği, cache, retry, HTTP/ağ/hata | 7 |
| `test_agronomy.py` | İklim özeti, ET0, toprak, son 30 gün, sezon penceresi | 5 |
| `test_scoring.py` | Katalog, sıralama, sulama, hariç/ilgi, pH, doku, takvim, süre | 10 |
| `test_ai.py` | Heuristic, JSON temizleme, allowlist, OpenAI/Gemini/Claude, 400 fallback, Gemini 3.x istek şekli | 12 |
| `test_api.py` | Health, `/geo`, root, katalog, analiz, validasyon, 502/422/503, AI fallback, ağırlık | 14 |
| `test_advice.py` | `/advice` akışı, serbest metin aktarımı, AI hatasında fallback, `/reverse-geocode`, Nominatim cache/hata | 8 |
| `test_ui_smoke.py` | Arayüz dosyaları, backend kapalıyken render, çiftçi akışı, detay kutusu, düğme regresyonları, payload sözleşmesi | 8 |

Testler **gerçek NASA veya LLM çağrısı yapmaz**; `httpx.MockTransport` ve fake istemciler kullanır. Bu sayede CI'da anahtarsız ve ücretsiz çalışır.

### 6.2. Canlı doğrulama

- Gerçek NASA POWER çağrısı: Ankara, 39.93/32.85.
- Sonuç: 418.2 mm yıllık yağış, 10.31 °C ortalama, ET0 ~1723.7 mm, aridity 0.243, `semi_arid`.
- İlk analiz ~2.4 s (NASA ağı); cache'li analiz ~2 ms.
- Heuristic modda öneri: Kışlık Buğday 93.7, Arpa 88.6, Üzüm 84.5.
- `GET /docs` ve `POST /api/v1/analyze` uçtan uca çalıştı.
- `POST /api/v1/advice` (Edirne 41.6771/26.5557, serbest metinle): 2.7 s, 613 mm / 13.65 °C,
  "Bu tarlada Kışlık Buğday ekmen en doğrusu. Alternatif: Arpa." — 5 adım, 4 büyütme, 4 besleme, 4 bakım maddesi.
- `GET /api/v1/reverse-geocode` gerçek Nominatim çağrısı: "Sabuni Mahallesi, Edirne Merkez, Edirne" (~400 ms, sonrası cache).
- Streamlit arayüzü canlı backend'e bağlanıp test edildi: öneri düğmesi → sonuç ekranı, detay kutusu → iklim/toprak/puan tablosu; istisna yok.

### 6.3. Test edilmeyenler

- Gerçek LLM anahtarlarıyla canlı kalite testi (anahtar yok).
- Farklı ülkelerdeki yerel ekin çeşitleri ve agronomik doğruluk.
- Yük/performans testi (locust/k6).
- Güvenlik sızma testi.
- Uzun süreli NASA kota davranışı.

Bunlar üretim öncesi yapılmalıdır.

---

## 7. Nereler daha iyi hale getirilebilir? (öncelikli)

### P0 — Üretimden önce şart

1. **Toprak verisi:** SoilGrids / OpenLandMap entegrasyonu + zorunlu/teşvikli toprak analizi. NASA tek başına yeterli değil.
2. **Hava tahmini:** NASA daily geçmiş veridir; Open-Meteo/NOAA GFS/ECMWF ile 7-14 günlük tahmin ve sulama uyarısı.
3. **Geocoding:** Adres/il/ilçe araması (Nominatim, Google Geocoding); şu an lat/lon manuel.
4. **Kimlik doğrulama + rate limit:** API anahtarı/JWT, kullanıcı başına kota, kötüye kullanım koruması.
5. **Kalıcılık:** PostgreSQL + PostGIS; analiz geçmişi, çiftlik/tarla kaydı, geri bildirim.
6. **Gözlemlenebilirlik:** Structured logging, Prometheus/OpenTelemetry, hata izleme, maliyet/gecikme panosu.
7. **Dağıtım:** Docker, CI (lint + test), staging/prod, HTTPS, secret manager.
8. **Veri doğrulama:** Agronomist etiketli değerlendirme seti; önerilerin isabet oranı; farklı bölgelerde backtest.

### P1 — Ürünü güçlendirir

9. **Ekin simülasyonu:** DSSAT/APSIM/CROPWAT ile verim ve sulama simülasyonu; kural motoru yerine/yanına.
10. **İklim projeksiyonu:** NASA NEX-GDDP-CMIP6 ile SSP2-4.5/SSP5-8.5 senaryoları; "2030-2050'de bu ekin hâlâ uygun mu?" sorusu.
11. **Uydu verisi:** Sentinel-2 NDVI, SMAP toprak nemi, Landsat ile tarla düzeyi doğrulama.
12. **Pazar fiyatları:** Yerel borsa/kooperatif fiyatları, girdi maliyetleri, brüt marj hesabı.
13. **Çeşit veritabanı:** Bölgeye özel sertifikalı çeşitler, dayanıklılık, verim potansiyeli.
14. **Zararlı/hastalık modelleri:** GDD tabanlı risk uyarıları, erken uyarı.
15. **Sulama programı:** FAO-56 ETc, toprak su tutma kapasitesi, sulama verimliliği.
16. **i18n:** Tüm metinlerin çevrilebilir olması; şu an heuristic Türkçe/İngilizce, ekin notları ağırlıklı Türkçe.
17. **Offline/mobil:** Ollama yerel sunucu veya cihaz üstü küçük model; düşük bağlantılı sahalar.

### P2 — Uzun vadeli fark yaratır

18. **Geri bildirim döngüsü:** Çiftçinin "ekdim/ekmedim, sonuç ne oldu?" verisiyle model kalibrasyonu.
19. **A/B testi:** Gemini vs GPT vs Claude; maliyet/kalite/gecikme ölçümü.
20. **Verim tahmini:** Uydu + hava + toprak + çiftçi kaydı ile ML modeli; kural motorunun yerini almaz, destekler.
21. **Karbon/rejeneratif tarım:** Organik madde, karbon kredisi, su ayak izi modülleri.
22. **Sigorta/finans:** Risk skoruna bağlı sigorta primi veya kredi profilı (regülasyon dikkatli).

---

## 8. Planındaki eksik veya yanlış noktalar (açık rapor)

Aşağıdakiler eleştirel ama yapıcıdır; çoğu bu projede kısmen hafifletildi, ancak ürünleşme için hâlâ açıktır.

### 8.1. "NASA API'leriyle toprak verimliliği" — teknik olarak yanlış

NASA POWER toprak **nemini** ve **sıcaklığını** verir; verimlilik için gerekli N-P-K, pH, organik madde, katyon değişim kapasitesi ve tuzluluğu **vermez**. Bu projede pH/OM/EC çiftçi girdisi; eksikse `data_gaps` uyarısı var. Gerçek çözüm: SoilGrids/OpenLandMap + laboratuvar analizi + yerel toprak haritaları.

### 8.2. "AI en iyi ekin türünü seçsin" — LLM'e fazla güvenmek

LLM'ler tarımsal bir hesap motoru değildir; aynı girdiye farklı cevap verebilir, olmayan veriyi uydurabilir, yerel çeşit/pazar bilgisini bilemez. Bu projede AI'ı **%35 ağırlıkla** ve **allowlist + JSON şeması + deterministik fallback** ile sınırladım. Yine de tek başına yeterli değil: DSSAT/APSIM gibi süreç tabanlı modeller ve agronomist doğrulaması gerekir.

### 8.3. "NASA iklim değişikliği verisi" — tarihsel baseline ile gelecek projeksiyonu karıştırmak

Kullandığımız klimatoloji 2001-2025 ortalamasıdır; "iklim değişikliği senaryosu" değildir. Gelecek için NASA NEX-GDDP-CMIP6, SSP senaryoları ve downscaling gerekir. Bugünkü çıktı "mevcut/geçmiş iklimde bu ekin uygun mu?" sorusuna cevap verir; "2050'de uygun mu?" sorusuna değil.

### 8.4. "Hava durumu" — tahmin ile gözlemi karıştırmak

POWER daily endpoint'i geçmişe dönük/gecikmeli veridir; 7 günlük tahmin değildir. Sulama ve don uyarısı için ayrı bir forecast sağlayıcısı (Open-Meteo, NOAA GFS, ECMWF) gerekir.

### 8.5. "Dünyadaki tüm çiftçiler" — tek global model gerçekçi değil

16 ekin ve tek ağırlık seti dünya çapında yeterli değil. Ülke/bölge bazında:

- yerel ekinler ve çeşitler,
- toprak tipleri ve analiz yöntemleri,
- pazar fiyatları ve lojistik,
- iklim kuşakları,
- dil, birim, regülasyon

farklıdır. Ürün stratejisi "global motor + bölgesel veri paketleri" olmalı; her ülkeye aynı katsayılarla girmek yanıltıcı olur.

### 8.6. Grid çözünürlüğü — tarla ölçeği yanılsaması

POWER ~50 km grid kullanır. Aynı hücredeki iki tarlanın toprağı, eğimi ve suyu farklı olabilir. "Seçilen bölge" ifadesi pazarlama için uygun, agronomik kesinlik için değil. Tarla sınırı (polygon), toprak örneklemesi ve uydu verisi ile desteklenmeli.

### 8.7. Toprak analizi olmadan kesin öneri vermek

pH/OM/EC girilmezse model varsayılanlarla çalışır ve yanıt bunu söyler. Ancak UI bu eksikleri **zorunlu/teşvikli** hale getirmezse çiftçi yanlış kesinlik algılayabilir. UI'da "toprak analizi yok" rozeti ve güven düşürme mekanizması olmalı.

### 8.8. Yasal sorumluluk ve "verim garantisi" riski

Tarımsal öneri, yanlış uygulanırsa ciddi ekonomik zarar doğurabilir. "Şu ekin en kârlı" demek yerine olasılık/risk dili kullanılmalı; disclaimer, kullanım koşulları, sigorta ve insan onayı olmalı. Bu projede disclaimer var ama hukuki metin ve sorumluluk sigortası yok.

### 8.9. Gizlilik ve KVKK/GDPR

Konum, tarla büyüklüğü ve üretim bilgisi kişisel/ticari veridir. Şu an:

- kimlik doğrulama yok,
- rate limit yok,
- veri saklama politikası yok,
- loglarda PII maskesi yok,
- AI sağlayıcısına veri gönderimi için açık rıza akışı yok.

Üretimde KVKK/GDPR aydınlatma, saklama süresi, silme hakkı, yurt dışı aktarım ve sağlayıcı veri politikaları netleştirilmelidir.

### 8.10. Maliyet ve gecikme kontrolü

Her istekte LLM çağrısı pahalı olabilir. Bu projede 8 aday/1600 token sınırı ve cache var; ancak:

- kullanıcı başına günlük kota,
- yanıt cache'i (aynı grid + aynı profil),
- küçük model yönlendirmesi,
- maliyet alarmı

yok. Özellikle ücretsiz katmanda toplu kullanım kotayı tüketebilir.

### 8.11. Değerlendirme (evaluation) eksikliği

"AI iyi mi?" sorusunun cevabı anekdotla verilemez. Agronomistlerin etiketlediği bir test seti, bölge bazlı backtest, öneri isabet oranı, kullanıcı memnuniyeti ve gerçek hasat verisi gerekir. Bu olmadan %35 AI ağırlığı bile keyfi kalır.

### 8.12. Hastalık/zararlı, sulama ve hasat sonrası süreçler yok

Ekin seçimi tek karar değil; ekim zamanı, gübreleme, sulama, hastalık, hasat, depolama ve satış gerekir. Ürün yol haritası bu zinciri kapsamalı; yoksa çiftçi "ne ekelim?" sorusunun cevabını alır ama sezon boyunca yalnız kalır.

### 8.13. Yerelleştirme ve okuryazarlık

Türkçe/İngilizce destek var; ancak:

- ekin notları ağırlıklı Türkçe,
- birimler metrik,
- okuma yazma düzeyi yüksek varsayımı,
- görsel/işitsel destek yok.

Gerçek kapsama için çok dilli, basit dil, sesli anlatım ve mobil-öncelikli tasarım gerekir.

### 8.14. Veri lisansı ve atıf

NASA verisi açık olsa da atıf/koşullar kontrol edilmeli. Ekin parametreleri ve puan ağırlıkları bu projede derlenmiş yaklaşık değerlerdir; ticari kullanımda yerel kaynak ve uzman kalibrasyonu şarttır.

### 8.15. Altyapı ve dayanıklılık

Tek süreç, in-memory cache, veritabanı yok. Çok örnekli (multi-instance) dağıtımda cache tutarsızlığı, yeniden başlatmada veri kaybı ve yatay ölçekleme sorunları olur. Redis, PostgreSQL ve job queue ile olgunlaştırılmalı.

---

## 9. Yol haritası

### 0-1 ay (MVP sertleştirme)

- Docker + CI, ortam ayrımı, secret manager
- Auth/rate limit, PII maskeleme, KVKK/GDPR metinleri
- SoilGrids + toprak analizi alanları, geocoding
- Forecast API (Open-Meteo) ve don/sıcak uyarısı
- Agronomist review ekranı (öneri onayı/reddi)
- Gerçek LLM anahtarıyla kalite testi ve maliyet ölçümü

### 1-3 ay (agronomik derinlik)

- DSSAT/APSIM/CROPWAT entegrasyonu (en az pilot bölge)
- NEX-GDDP-CMIP6 senaryoları
- Yerel çeşit ve pazar fiyatı veritabanı
- Sulama programı (FAO-56 ETc)
- Zararlı/hastalık GDD uyarıları
- PostgreSQL + PostGIS, analiz geçmişi, çiftlik kaydı

### 3-6 ay (ölçek ve kanıt)

- Çok bölgeli saha pilotu, agronomist etiketli değerlendirme seti
- Uydu (Sentinel-2/SMAP) doğrulama
- A/B testi: Gemini vs GPT vs Claude; maliyet/kalite
- Geri bildirim döngüsü ve model kalibrasyonu
- Mobil/offline senaryo, i18n
- Sigorta/finans ortaklıkları için risk skoru API'si

---

## 10. Üretim kontrol listesi

- [ ] Gerçek toprak analizi ve yerel uzman doğrulaması
- [ ] Forecast sağlayıcısı ve don uyarısı
- [ ] Kimlik doğrulama, rate limit, kota
- [ ] KVKK/GDPR aydınlatma ve veri saklama politikası
- [ ] AI sağlayıcı sözleşmesi/veri işleme ekleri
- [ ] Maliyet alarmı ve token bütçesi
- [ ] Agronomist onay akışı
- [ ] Değerlendirme seti ve doğruluk metrikleri
- [ ] Docker/CI/CD, staging, HTTPS
- [ ] Log/metric/trace ve hata izleme
- [ ] Yedekleme ve felaket kurtarma
- [ ] Yasal disclaimer ve kullanım koşulları

---

## 11. Sonuç

Bu teslim, "çalışan bir backend"in ötesinde **dürüst bir mimari** kuruyor:

- NASA verisinin ne olduğunu ve ne olmadığını açıkça ayırıyor,
- AI'ı tek karar mercii yapmıyor, açıklanabilir kural motoruna bağlıyor,
- sağlayıcı bağımsız ve anahtarsız test edilebilir,
- eksik veriyi gizlemiyor, `data_gaps` ve `warnings` ile gösteriyor,
- 44 test ve canlı NASA doğrulamasıyla çalıştığını kanıtlıyor.

En büyük eksikler; **tarla ölçeğinde toprak verisi**, **hava tahmini**, **iklim projeksiyonu**, **yerel kalibrasyon**, **kullanıcı doğrulama/güvenlik** ve **agronomist değerlendirme seti**dir. Bunlar Bölüm 7-8'de önceliklendirildi.

Kısaca: Bu backend, "NASA + AI ile ekin önerisi" fikrinin sağlam bir ilk sürümüdür; ancak gerçek çiftçi değeri için veri derinliği ve insan doğrulaması eklenmeden üretime alınmamalıdır.
