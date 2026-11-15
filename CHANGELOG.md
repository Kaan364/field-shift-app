# Değişiklik Günlüğü

Tüm önemli değişiklikler bu dosyada tutulur. Sürümleme: [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-11-15

### Eklendi

- **Çiftçi PWA'sı (`/app/`)**: mobil öncelikli, sade Türkçe, büyük düğmeler, simgeler ve 3 adımlı sihirbaz.
  - Leaflet + OpenStreetMap haritası, tarayıcı konumu, 25 il kısayolu, elle koordinat girişi.
  - Sonuç ekranında yıl yıl ekim zaman çizelgesi, puan karnesi, toprak/su/iklim kartları.
  - Sesli okuma (`tr-TR`), yazdırma, Web Share/pano paylaşımı, JSON indirme.
  - `localStorage` ile son plan ve işaretlenmiş yapılacaklar; çevrimdışı uyarısı.
  - Service worker ile uygulama kabuğu önbelleği (API yanıtları asla önbelleğe alınmaz).
  - `manifest.webmanifest`, SVG favicon ve 192/512/maskelenebilir PNG ikonlar.
  - `A+` yazı büyütme, `prefers-reduced-motion`, yüksek kontrast ve klavye erişilebilirliği.
- **Yeni API uçları**:
  - `POST /api/v1/farm-plan` — tek istekte öneri + rotasyon + toprak + su + iklim.
  - `POST /api/v1/rotation`, `POST /api/v1/soil-health`, `POST /api/v1/water-plan`.
- **Çok yıllık ekim nöbeti motoru** (`app/domain/rotation.py`): 2–4 yıl, yıl 1 mevcut öneriye sabit, familya tekrarı yok, alternatif sıralar ve sade gerekçeler.
- **Toprak sağlığı karnesi** (`app/domain/soil_health.py`): 9 gösterge, A–D notu, eksik veri boşlukları ve öncelikli aksiyonlar.
- **Su dengesi** (`app/domain/water.py`): aylık yağış/buharlaşma, sezonluk açık, dönüm başına ton ve tarla toplamı m³.
- **İklim eğilimi** (`app/services/climate.py`): NASA POWER aylık verisinden 2001–bugün yıllıklaştırılmış sıcaklık/yağış eğilimi, risk düzeyi ve sade mesajlar.
- **5 yeni ürün**: tritikale, yulaf, aspir, korunga, fiğ (toplam 21).
- **Ürün meta verisi** (`app/domain/crop_meta.py`): simge, familya etiketi, rotasyon özellikleri ve doğrulama.
- **Dağıtım ve derleme**: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `render.yaml`, `Procfile`, `runtime.txt`, `Makefile`, `scripts/build.sh`, GitHub Actions CI (test + Docker + health smoke).
- **Testler**: rotasyon değişmezleri, toprak/su hesapları, tam plan sözleşmesi, web arayüzü/statik varlıklar ve aylık→yıllık NASA toplama testleri.

### Değişti

- `GET /` artık tarayıcılara çiftçi uygulamasını, API istemcilerine JSON özetini döndürür (içerik anlaşması).
- `UI_BASE_URL` varsayılanı `/app/`; `/geo` göreli dönüş adreslerini kabul eder.
- Ürün kataloğu ve README 21 ürüne güncellendi.
- `FakeNASA` test yardımcısı boş yıllık veri senaryosunu destekler.

### Düzeltildi

- NASA POWER'ın `annual` ürünü bulunmadığı için iklim eğilimi **aylık** uçtan yıllıklaştırılarak hesaplanıyor; eksik yıllar eğilime sokulmuyor.
- 4 yıllık rotasyon özeti dördüncü yılı da listeliyor.
- Su kartında ipuçları yokken açıklama göstergesinin yanlış gizlenmesi giderildi.
- `.gitignore` başındaki hatalı kod bloğu işareti temizlendi.

### Güvenlik / gizlilik

- Konum yalnızca istek içinde kullanılır; sunucuda saklanmaz.
- Planlar tarayıcıda `localStorage`'da tutulur; hesaplar arası paylaşılmaz.
- Service worker API yanıtlarını önbelleğe almaz.

## [0.1.0] — 2026-10-01

- İlk sürüm: FastAPI backend, NASA POWER klimatolojisi, açıklanabilir kural motoru, LLM katmanı, Streamlit uzman arayüzü.
