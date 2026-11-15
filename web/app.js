/* =============================================================================
   Tarla Dostu — farmer UI logic (vanilla JS, no build step)
   ========================================================================== */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const API = "";
  const LAST_PLAN_KEY = "tarladostu.lastPlan.v1";
  const CHECKS_KEY = "tarladostu.checks.v1";
  const TEXT_KEY = "tarladostu.bigText";

  const MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
  ];
  const MONTHS_SHORT = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];

  const CITIES = [
    ["Adana", 37.0000, 35.3213], ["Ankara", 39.9334, 32.8597], ["Antalya", 36.8969, 30.7133],
    ["Aydın", 37.8560, 27.8416], ["Balıkesir", 39.6484, 27.8826], ["Bursa", 40.1885, 29.0610],
    ["Çanakkale", 40.1553, 26.4142], ["Diyarbakır", 37.9144, 40.2306], ["Edirne", 41.6771, 26.5557],
    ["Erzurum", 39.9043, 41.2679], ["Eskişehir", 39.7767, 30.5206], ["Gaziantep", 37.0662, 37.3833],
    ["Isparta", 37.7648, 30.5566], ["İzmir", 38.4237, 27.1428], ["Kayseri", 38.7312, 35.4787],
    ["Konya", 37.8746, 32.4932], ["Kütahya", 39.4167, 29.9833], ["Malatya", 38.3552, 38.3095],
    ["Mersin", 36.8000, 34.6333], ["Samsun", 41.2928, 36.3313], ["Şanlıurfa", 37.1591, 38.7969],
    ["Tekirdağ", 40.9833, 27.5167], ["Tokat", 40.3167, 36.5500], ["Van", 38.4942, 43.3800],
    ["Yozgat", 39.8200, 34.8044],
  ];

  const CROP_OPTIONS = [
    ["wheat", "Buğday"], ["barley", "Arpa"], ["triticale", "Tritikale"], ["oats", "Yulaf"],
    ["maize", "Mısır"], ["sunflower", "Ayçiçeği"], ["canola", "Kanola"], ["safflower", "Aspir"],
    ["chickpea", "Nohut"], ["lentil", "Mercimek"], ["soybean", "Soya"], ["potato", "Patates"],
    ["sugar_beet", "Şeker pancarı"], ["alfalfa", "Yonca"], ["sainfoin", "Korunga"],
    ["vetch", "Fiğ"], ["tomato", "Domates"], ["cotton", "Pamuk"], ["olive", "Zeytin"],
    ["grape", "Üzüm"], ["apple", "Elma"],
  ];

  const ICONS = {
    wheat: "🌾", barley: "🌾", triticale: "🌾", oats: "🌾", maize: "🌽",
    sunflower: "🌻", canola: "🌼", safflower: "🌺", chickpea: "🫘", lentil: "🫘",
    soybean: "🫘", alfalfa: "🌿", sainfoin: "🌿", vetch: "🌱", potato: "🥔",
    sugar_beet: "🍬", tomato: "🍅", cotton: "🧵", olive: "🫒", grape: "🍇", apple: "🍎",
  };

  const CLIMATE_LABELS = {
    hyper_arid: "hiper-kurak", arid: "kurak", semi_arid: "yarı kurak",
    dry_sub_humid: "kuru-yarı nemli", humid: "nemli", per_humid: "çok nemli",
    unknown: "bilinmiyor",
  };

  const state = {
    step: 1,
    lat: null,
    lon: null,
    place: "",
    map: null,
    marker: null,
    plan: null,
    payload: null,
    loadingTimer: null,
    toastTimer: null,
    speaking: false,
  };

  /* ------------------------------------------------------------------ utils */
  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function num(value, digits) {
    if (value == null || value === "" || Number.isNaN(Number(value))) return "—";
    return new Intl.NumberFormat("tr-TR", {
      minimumFractionDigits: 0,
      maximumFractionDigits: digits == null ? 0 : digits,
    }).format(Number(value));
  }
  function numOrNull(value) {
    if (value == null || String(value).trim() === "") return null;
    const parsed = Number(String(value).replace(",", "."));
    return Number.isFinite(parsed) ? parsed : null;
  }
  function toast(message) {
    const node = $("toast");
    node.textContent = message;
    node.hidden = false;
    requestAnimationFrame(() => node.classList.add("show"));
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => {
      node.classList.remove("show");
      setTimeout(() => { node.hidden = true; }, 220);
    }, 3200);
  }
  function rating(score) {
    if (score == null) return { label: "Bilinmiyor", stars: "☆☆☆☆☆", tone: "mid" };
    if (score >= 85) return { label: "Çok uygun", stars: "★★★★★", tone: "good" };
    if (score >= 70) return { label: "Uygun", stars: "★★★★☆", tone: "good" };
    if (score >= 55) return { label: "Orta", stars: "★★★☆☆", tone: "mid" };
    return { label: "Zor", stars: "★★☆☆☆", tone: "low" };
  }
  function toneClass(score) {
    if (score == null) return "mid";
    if (score >= 70) return "good";
    if (score >= 50) return "mid";
    return "low";
  }
  function cssTone(score) {
    if (score == null) return "mid";
    if (score >= 70) return "good";
    if (score >= 50) return "mid";
    return "low";
  }
  function readableList(items, limit, variant) {
    return (items || []).slice(0, limit || 10)
      .map((item) => `<li${variant ? ` class="${variant}"` : ""}>${esc(item)}</li>`)
      .join("");
  }
  function climateLabel(value) { return CLIMATE_LABELS[value] || value || "bilinmiyor"; }
  function directionIcon(direction) {
    if (direction === "up") return "⬆️";
    if (direction === "down") return "⬇️";
    return "➡️";
  }

  /* ------------------------------------------------------------- boot / nav */
  function populate() {
    const citySelect = $("citySelect");
    CITIES.forEach(([name, lat, lon]) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      option.dataset.lat = lat;
      option.dataset.lon = lon;
      citySelect.appendChild(option);
    });

    const prev = $("prevCrop");
    CROP_OPTIONS.forEach(([key, label]) => {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = label;
      prev.appendChild(option);
    });

    const month = $("monthSelect");
    MONTHS.forEach((name, index) => {
      const option = document.createElement("option");
      option.value = String(index + 1);
      option.textContent = name;
      month.appendChild(option);
    });
    month.value = String(new Date().getMonth() + 1);
  }

  function showScreen(id) {
    document.querySelectorAll(".screen").forEach((screen) => {
      screen.classList.toggle("is-active", screen.id === id);
    });
    if (screenIsResult(id)) {
      $("wizardNav").hidden = true;
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function screenIsResult(id) { return id === "screen-result"; }

  function goToStep(step, { scroll = true } = {}) {
    state.step = Math.max(1, Math.min(3, step));
    document.querySelectorAll(".step").forEach((node) => {
      node.classList.toggle("is-active", Number(node.dataset.step) === state.step);
    });
    $("progressBar").style.width = `${(state.step / 3) * 100}%`;
    $("stepLabel").textContent = `${state.step} / 3`;
    $("wizardHint").textContent = `Adım ${state.step} / 3`;
    $("wizardNav").hidden = state.step === 3;
    $("backBtn").setAttribute("aria-label", state.step === 1 ? "Ana sayfaya dön" : "Geri");
    if (scroll) window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function startWizard() {
    showScreen("screen-wizard");
    goToStep(1, { scroll: false });
    setTimeout(initMap, 80);
  }

  /* -------------------------------------------------------------------- map */
  function initMap() {
    if (state.map || !window.L) return;
    const map = L.map("map", { zoomControl: false, attributionControl: true }).setView([39.0, 35.0], 5);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    map.on("click", (event) => {
      setLocation(event.latlng.lat, event.latlng.lng, { zoom: false, reverse: true });
    });
    state.map = map;
    if (state.lat != null && state.lon != null) placeMarker(state.lat, state.lon, false);
    setTimeout(() => map.invalidateSize(), 120);
  }

  function pinIcon() {
    return L.divIcon({
      className: "",
      html: '<div class="map-pin"><span>🌾</span></div>',
      iconSize: [42, 42],
      iconAnchor: [21, 40],
    });
  }

  function placeMarker(lat, lon, pan) {
    if (!state.map) return;
    if (state.marker) {
      state.marker.setLatLng([lat, lon]);
    } else {
      state.marker = L.marker([lat, lon], { icon: pinIcon(), keyboard: false }).addTo(state.map);
    }
    if (pan) state.map.setView([lat, lon], Math.max(state.map.getZoom(), 12));
  }

  function setLocation(lat, lon, options) {
    const opts = options || {};
    const latitude = Number(lat);
    const longitude = Number(lon);
    if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
      toast("Enlem -90 ile 90 arasında olmalı.");
      return;
    }
    if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
      toast("Boylam -180 ile 180 arasında olmalı.");
      return;
    }
    state.lat = latitude;
    state.lon = longitude;
    $("latInput").value = latitude.toFixed(5);
    $("lonInput").value = longitude.toFixed(5);
    $("placeName").textContent = `Seçilen nokta: ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
    $("formMsg").hidden = true;
    $("geoMsg").textContent = "";
    if (opts.zoom !== false) {
      if (state.map) {
        state.map.setView([latitude, longitude], opts.zoomLevel || Math.max(state.map.getZoom(), 12));
      }
    }
    placeMarker(latitude, longitude, false);
    if (opts.reverse !== false) reverseGeocode(latitude, longitude);
  }

  async function reverseGeocode(lat, lon) {
    try {
      const response = await fetch(`${API}/api/v1/reverse-geocode?latitude=${lat}&longitude=${lon}`);
      if (!response.ok) return;
      const data = await response.json();
      if (!data.found) return;
      const parts = [data.district, data.city || data.region, data.country].filter(Boolean);
      state.place = [...new Set(parts)].join(", ").slice(0, 120);
      if (state.place) {
        $("placeName").textContent = `📍 ${state.place}`;
      }
    } catch (error) {
      /* offline or geocoder unavailable: coordinates remain visible */
    }
  }

  function useGeolocation() {
    const button = $("geoBtn");
    const message = $("geoMsg");
    if (!navigator.geolocation) {
      message.textContent = "Tarayıcın konumu desteklemiyor. İl seçebilirsin.";
      return;
    }
    button.disabled = true;
    message.textContent = "Konum isteniyor… İzin ver.";
    navigator.geolocation.getCurrentPosition(
      (position) => {
        button.disabled = false;
        message.textContent = "";
        setLocation(position.coords.latitude, position.coords.longitude, { zoomLevel: 14, reverse: true });
        toast("Tarlan haritada işaretlendi.");
      },
      (error) => {
        button.disabled = false;
        const text = error && error.code === 1
          ? "Konum izni verilmedi. İl seçebilir veya haritaya dokunabilirsin."
          : "Konum alınamadı. Haritaya dokun veya il seç.";
        message.textContent = text;
        toast(text);
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  }

  /* ---------------------------------------------------------------- wizard */
  function validateStep(step) {
    if (step === 1) {
      if (state.lat == null || state.lon == null) {
        toast("Önce tarlanın yerini seç.");
        return false;
      }
    }
    if (step === 2) {
      const area = Number($("areaInput").value);
      if (!Number.isFinite(area) || area <= 0) {
        toast("Tarla büyüklüğünü gir. Bilmiyorsan 10 bırak.");
        $("areaInput").focus();
        return false;
      }
    }
    return true;
  }

  function collectPayload() {
    const irrigation = document.querySelector('input[name="irrigation"]:checked')?.value || "rainfed";
    const goal = document.querySelector('input[name="goal"]:checked')?.value || "max_profit";
    const areaDonum = Math.max(1, Number($("areaInput").value) || 10);
    const month = $("monthSelect").value;
    return {
      location: {
        latitude: state.lat,
        longitude: state.lon,
        region_name: state.place || null,
      },
      area_hectares: Math.max(0.01, areaDonum / 10),
      soil_texture: $("textureSelect").value || "unknown",
      soil_ph: numOrNull($("phInput").value),
      organic_matter_pct: numOrNull($("omInput").value),
      salinity_ds_m: numOrNull($("salinityInput").value),
      drainage: $("drainageSelect").value || "medium",
      slope_pct: numOrNull($("slopeInput").value),
      previous_crop: $("prevCrop").value || null,
      irrigation,
      water_availability: irrigation === "rainfed" ? "low" : irrigation === "limited" ? "medium" : "high",
      market_access: "medium",
      goal,
      planting_month: month ? Number(month) : null,
      free_text: $("freeText").value.trim(),
      top_n: 3,
      rotation_years: Number($("yearsSelect").value) || 3,
      language: "tr",
    };
  }

  async function submitPlan() {
    if (!validateStep(1) || !validateStep(2)) return;
    const payload = collectPayload();
    state.payload = payload;
    $("formMsg").hidden = true;
    $("submitBtn").disabled = true;
    showScreen("screen-loading");
    startLoadingMessages();

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 130000);
    try {
      const response = await fetch(`${API}/api/v1/farm-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(friendlyError(response.status, data));
      }
      stopLoadingMessages();
      savePlan(data, payload);
      renderPlan(data);
      showScreen("screen-result");
      toast("Planın hazır. Aşağı kaydır ve oku.");
    } catch (error) {
      stopLoadingMessages();
      showScreen("screen-wizard");
      goToStep(3, { scroll: false });
      const message = error && error.name === "AbortError"
        ? "Sunucu çok yavaş yanıt verdi. İnternetini kontrol edip tekrar dene."
        : (error && error.message) || "Plan hazırlanamadı. Tekrar dene.";
      $("formMsg").textContent = message;
      $("formMsg").hidden = false;
      $("submitBtn").disabled = false;
      toast(message);
    } finally {
      clearTimeout(timeout);
    }
  }

  function friendlyError(status, data) {
    if (status === 502) {
      return "NASA verisine şu an ulaşamadık. İnternetini kontrol et ve birkaç dakika sonra tekrar dene.";
    }
    if (status === 422) {
      const detail = data && (data.message || data.detail);
      return detail
        ? `Bazı bilgiler eksik veya geçersiz: ${String(detail).slice(0, 140)}`
        : "Bazı bilgiler eksik. Tarla bilgilerini kontrol et.";
    }
    if (status === 503) {
      return "Açıklama servisi şu an yanıt vermiyor. Kural motoruyla tekrar denemek için biraz bekle.";
    }
    if (status >= 500) {
      return "Sunucuda bir sorun var. Birkaç dakika sonra tekrar dene.";
    }
    return (data && data.message) || "İstek tamamlanamadı. Bilgileri kontrol et.";
  }

  const LOADING_MESSAGES = [
    "NASA'dan 25 yıllık hava verisi alınıyor…",
    "Tarlanın yağışı ve sıcaklığı hesaplanıyor…",
    "Toprak sağlığı ve su dengesi çıkarılıyor…",
    "3 yıllık ekim sırası kuruluyor…",
    "Sade bir plan hazırlanıyor…",
  ];
  function startLoadingMessages() {
    let index = 0;
    $("loadingMsg").textContent = LOADING_MESSAGES[0];
    clearInterval(state.loadingTimer);
    state.loadingTimer = setInterval(() => {
      index = (index + 1) % LOADING_MESSAGES.length;
      $("loadingMsg").textContent = LOADING_MESSAGES[index];
    }, 2400);
  }
  function stopLoadingMessages() {
    clearInterval(state.loadingTimer);
    state.loadingTimer = null;
  }

  /* --------------------------------------------------------------- storage */
  function savePlan(data, payload) {
    state.plan = data;
    try {
      localStorage.setItem(LAST_PLAN_KEY, JSON.stringify({ data, payload, savedAt: Date.now() }));
    } catch (error) {
      /* private mode / quota: the plan still renders */
    }
    $("lastPlanBtn").hidden = false;
  }
  function loadSavedPlan(silent) {
    try {
      const raw = localStorage.getItem(LAST_PLAN_KEY);
      if (!raw) return null;
      const saved = JSON.parse(raw);
      if (!saved || !saved.data) return null;
      if (!silent) {
        state.payload = saved.payload || null;
        renderPlan(saved.data);
        showScreen("screen-result");
        toast("Son planın açıldı.");
      }
      return saved;
    } catch (error) {
      return null;
    }
  }
  function updateLastPlanButton() {
    const saved = loadSavedPlan(true);
    $("lastPlanBtn").hidden = !saved;
    if (saved) {
      const days = Math.max(0, Math.floor((Date.now() - saved.savedAt) / 86400000));
      $("lastPlanBtn").textContent = days === 0 ? "📋 Son planımı aç" : `📋 Son planımı aç (${days} gün önce)`;
    }
  }

  /* ----------------------------------------------------------- render plan */
  function renderPlan(data) {
    state.plan = data;
    const env = data.environment || {};
    const climate = env.climate || {};
    const advice = data.advice || {};
    const recs = data.recommendations || [];
    const top = recs[0];
    const rotation = data.rotation || { applicable: false, years: [], notes: [] };
    const soil = data.soil_health || {};
    const water = data.water || {};
    const climateOutlook = data.climate || {};

    const areaHa = state.payload ? Number(state.payload.area_hectares) : null;
    const donum = areaHa ? Math.round(areaHa * 10) : null;
    const place = data.location?.region_name || state.place || "Tarlan";
    $("resultPlace").textContent = `📍 ${place}${donum ? ` • ${num(donum)} dönüm` : ""}`;
    $("resultClimate").textContent = `🌦️ ${climateLabel(climate.climate_class)} • yıllık yağış ${num(climate.annual_precip_mm)} mm`;

    /* hero */
    if (top) {
      const score = top.scores?.final_score;
      const info = rating(score);
      $("heroIcon").textContent = ICONS[top.crop_key] || "🌾";
      $("heroCrop").textContent = top.crop_name_local || top.crop_name;
      $("heroRating").textContent = `${info.stars} ${info.label}${score != null ? ` • ${num(score)}/100` : ""}`;
      $("heroWhy").textContent = advice.why || top.rationale || "";
    } else {
      $("heroCrop").textContent = "Öneri bulunamadı";
      $("heroRating").textContent = "Bilgileri kontrol edip tekrar dene.";
      $("heroWhy").textContent = "";
    }

    /* rotation */
    const years = rotation.years || [];
    $("rotationTitle").innerHTML = `🔁 ${years.length || rotation.years_requested || 3} yıllık ekim planı`;
    $("rotationSummary").textContent = rotation.summary || "";
    const rotScore = rotation.scores?.overall;
    $("rotationScorePill").textContent = rotScore != null
      ? `${rating(rotScore).label} • ${num(rotScore)}/100`
      : (rotation.applicable ? "—" : "Uygun değil");
    $("rotationScorePill").className = `pill${rotScore != null && rotScore < 55 ? " warn" : ""}`;

    renderTimeline(years, rotation);
    renderBenefits(rotation);
    renderRotationDetails(rotation);

    /* scores */
    renderScores(rotation);

    /* soil */
    renderSoil(soil);

    /* water */
    renderWater(water);

    /* climate */
    renderClimate(climateOutlook, climate);

    /* advice sections */
    renderList("firstSteps", advice.steps || [], "check");
    renderList("growList", advice.grow || []);
    renderList("feedList", advice.feed || []);
    renderList("careList", advice.care || []);
    renderList("riskList", advice.risks || []);

    /* alternatives */
    renderAlternatives(recs.slice(1, 4));

    /* tech */
    renderTech(data, env, climate, climateOutlook);
    $("disclaimer").textContent = data.disclaimer || "";

    restoreChecks(data.plan_id);
  }

  function renderTimeline(years, rotation) {
    const container = $("rotationTimeline");
    if (!rotation.applicable || !years.length) {
      container.innerHTML = `
        <div class="timeline-card">
          <p class="timeline-crop"><span class="emoji">ℹ️</span><strong>Yıllık ekim nöbeti uygulanmıyor</strong></p>
          <p class="timeline-benefit">${esc(rotation.summary || "")}</p>
        </div>`;
      return;
    }
    container.innerHTML = years.map((year) => {
      const icon = year.icon || ICONS[year.crop_key] || "🌾";
      const rain = year.season_rain_mm != null ? ` • yağış ${num(year.season_rain_mm)} mm` : "";
      const actions = (year.actions || []).map((item) => `<li>${esc(item)}</li>`).join("");
      return `
        <div class="timeline-item" data-year="${year.year}">
          <div class="year-badge">${year.year}.<br>YIL</div>
          <div class="timeline-card">
            <div class="timeline-crop">
              <span class="emoji" aria-hidden="true">${esc(icon)}</span>
              <strong>${esc(year.crop_name_local)}</strong>
            </div>
            <p class="timeline-role">${esc(year.role || year.family_label || "")}</p>
            <div class="timeline-tags">
              <span>🗓️ ${esc(year.planting_window)}</span>
              <span>💧 ${num(year.water_need_mm)} mm${esc(rain)}</span>
            </div>
            <p class="timeline-benefit">${esc(year.benefit || "")}</p>
            ${year.cover_crop ? `<p class="cover-line">🌱 ${esc(year.cover_crop)}</p>` : ""}
            ${actions ? `<details><summary>Bu yıl ne yapmalı?</summary><ul>${actions}</ul></details>` : ""}
          </div>
        </div>`;
    }).join("");
  }

  function renderBenefits(rotation) {
    const box = $("rotationBenefits");
    const benefits = (rotation.benefits || []).slice(0, 3);
    if (!benefits.length) { box.innerHTML = ""; return; }
    box.innerHTML = benefits.map((item) => `<p>✅ ${esc(item)}</p>`).join("");
  }

  function renderRotationDetails(rotation) {
    $("rotationWhy").innerHTML =
      readableList(rotation.benefits, 8, "good") + readableList(rotation.cautions, 6, "warn");
    const notes = (rotation.notes || []).join(" ");
    $("rotationNotes").textContent = notes;
    const alternatives = rotation.alternatives || [];
    const container = $("rotationAlternatives");
    if (!alternatives.length) { container.innerHTML = ""; return; }
    container.innerHTML = `
      <h3 class="subhead">Başka sıralar</h3>
      <div class="alt-grid">
        ${alternatives.map((alt) => `
          <div class="alt">
            <span class="emoji" aria-hidden="true">🔁</span>
            <div class="alt-body">
              <strong>${esc((alt.crop_names || []).join(" → "))}</strong>
              <span>Toplam su ihtiyacı ${num(alt.total_water_mm)} mm</span>
            </div>
            <span class="alt-score">${num(alt.scores?.overall)}</span>
          </div>`).join("")}
      </div>`;
  }

  function renderScores(rotation) {
    const grid = $("scoreGrid");
    if (!rotation.scores) {
      grid.innerHTML = `<p class="hint">${esc(rotation.summary || "Bu tarla için rotasyon puanı hesaplanamadı.")}</p>`;
      return;
    }
    const scores = rotation.scores;
    const rows = [
      ["Toprak sağlığı", scores.soil_health, "🪨"],
      ["Su tasarrufu", scores.water, "💧"],
      ["İklim dayanıklılığı", scores.resilience, "🌦️"],
      ["Kazanç potansiyeli", scores.profit, "💰"],
      ["Risk güvenliği", scores.risk, "🛡️"],
    ];
    grid.innerHTML = rows.map(([label, value, icon]) => {
      const tone = toneClass(value);
      return `
        <div class="score-row">
          <span class="score-label">${icon} ${esc(label)}</span>
          <span class="score-value ${tone}">${num(value)}/100</span>
          <div class="bar"><span class="${cssTone(value)}" style="width:${Math.max(2, Math.min(100, Number(value) || 0))}%"></span></div>
        </div>`;
    }).join("");
  }

  function renderSoil(soil) {
    const grade = soil.grade || "—";
    const gradeNode = $("soilGrade");
    gradeNode.textContent = grade;
    gradeNode.className = `grade ${String(grade).toLowerCase()}`;
    gradeNode.setAttribute("aria-label", `Toprak notu ${grade}`);
    $("soilSummary").textContent = soil.summary || "";
    const score = soil.score;
    const bar = $("soilBar");
    bar.style.width = `${score == null ? 0 : Math.max(2, Math.min(100, score))}%`;
    bar.className = cssTone(score);
    $("soilScoreText").textContent = score == null ? "—" : num(score);
    $("soilActions").innerHTML = readableList(soil.actions, 5);
    $("soilOutlook").textContent = soil.outlook || "";
    $("soilOutlook").hidden = !soil.outlook;
    $("soilIndicators").innerHTML = (soil.indicators || []).map((item) => {
      const value = item.value != null ? `${num(item.value, 1)} ${esc(item.unit || "")}` : "—";
      const status = item.status || "bilinmiyor";
      return `
        <div class="indicator">
          <strong>${esc(item.label)}</strong>
          <span class="value">${value} <span class="status ${esc(status)}">${esc(status)}</span></span>
          <span class="advice">${esc(item.advice || "")}</span>
        </div>`;
    }).join("");
    $("soilGaps").textContent = (soil.data_gaps || []).join(" ");
  }

  function renderWater(water) {
    $("waterSummary").textContent = water.summary || "";
    const stats = [
      ["Bitki ihtiyacı", `${num(water.crop_need_mm)} mm`],
      ["Yağış", `${num(water.season_rain_mm)} mm`],
      ["Ek sulama", `${num(water.deficit_mm)} mm`],
      ["Tarlan için", `${num(water.deficit_m3)} ton`],
    ];
    $("waterStats").innerHTML = stats.map(([label, value], index) => `
      <div class="water-stat${index === 2 || index === 3 ? " highlight" : ""}">
        <strong>${esc(value)}</strong>
        <span>${esc(label)}</span>
      </div>`).join("");

    const months = water.months || [];
    const max = Math.max(1, ...months.map((m) => Math.max(Number(m.rain_mm) || 0, Number(m.et0_mm) || 0)));
    $("waterMonths").innerHTML = months.map((m, index) => {
      const rain = Math.max(0, Number(m.rain_mm) || 0);
      const et0 = Math.max(0, Number(m.et0_mm) || 0);
      const short = MONTHS_SHORT[index] || m.month;
      return `
        <div class="month-row" title="${esc(m.month)}: yağış ${num(rain)} mm, buharlaşma ${num(et0)} mm">
          <span class="m">${esc(short)}</span>
          <div class="month-bars-inner">
            <div class="mini-bar"><span style="width:${(rain / max) * 100}%"></span></div>
            <div class="mini-bar et"><span style="width:${(et0 / max) * 100}%"></span></div>
          </div>
        </div>`;
    }).join("");
    const tips = water.tips || [];
    $("waterTips").innerHTML = readableList(tips, 6);
    $("waterTips").hidden = !tips.length;
  }

  function renderClimate(outlook, climate) {
    const risk = $("climateRisk");
    const riskKey = outlook.risk_level || "unknown";
    const riskText = outlook.risk_label || "Bilinmiyor";
    risk.textContent = `Risk: ${riskText}`;
    risk.className = `pill${riskKey === "high" ? " bad" : riskKey === "medium" ? " warn" : ""}`;

    const trends = outlook.trends || [];
    $("climateTrends").innerHTML = trends.map((trend) => {
      const sign = trend.change > 0 ? "+" : "";
      return `
        <div class="trend">
          <span class="trend-icon" aria-hidden="true">${directionIcon(trend.direction)}</span>
          <div class="trend-body">
            <strong>${esc(trend.label)}</strong>
            <span>${esc(trend.message)}</span>
          </div>
          <span class="trend-change ${esc(trend.direction)}">${sign}${num(trend.change, 1)} ${esc(trend.unit)}</span>
        </div>`;
    }).join("");
    $("climateTrends").hidden = !trends.length;

    const messages = outlook.messages || [];
    $("climateMessages").innerHTML = readableList(messages, 4);
    $("climateMessages").hidden = !messages.length;

    const dry = outlook.dry_months || [];
    $("climateDry").innerHTML = dry.length
      ? `☀️ <strong>Kurak aylar:</strong> ${dry.map((month) => esc(month)).join(", ")}. Sulama planını buna göre yap.`
      : "";
    $("climateDry").hidden = !dry.length;

    if (outlook.available) {
      $("climateSource").textContent = `NASA POWER ${outlook.start_year}–${outlook.end_year} (${outlook.available_years} yıl). Eğilim geçmiş verinin yönüdür; tahmin değildir.`;
    } else {
      $("climateSource").textContent = `Uzun yıllık eğilim verisi alınamadı. Bölge iklimi: ${climateLabel(climate.climate_class)}, yıllık yağış ${num(climate.annual_precip_mm)} mm.`;
    }
  }

  function renderList(id, items, mode) {
    const container = $(id);
    if (!container) return;
    if (!items || !items.length) {
      container.innerHTML = `<li class="hint">Bu bölüm için ek bilgi yok.</li>`;
      return;
    }
    if (mode === "check") {
      container.innerHTML = items.map((item, index) => `
        <li class="check-item">
          <input type="checkbox" id="step-${index}" data-check-index="${index}">
          <label for="step-${index}"><span>${esc(item)}</span></label>
        </li>`).join("");
      return;
    }
    container.innerHTML = items.map((item) => `<li>${esc(item)}</li>`).join("");
  }

  function renderAlternatives(recs) {
    const container = $("alternatives");
    if (!recs.length) {
      container.innerHTML = `<p class="hint">Başka alternatif yok.</p>`;
      return;
    }
    container.innerHTML = recs.map((rec) => {
      const score = rec.scores?.final_score;
      return `
        <div class="alt">
          <span class="emoji" aria-hidden="true">${ICONS[rec.crop_key] || "🌾"}</span>
          <div class="alt-body">
            <strong>${esc(rec.crop_name_local)}</strong>
            <span>${esc(rec.planting_window)} • ${num(rec.water_need_mm)} mm su</span>
          </div>
          <span class="alt-score">${rating(score).label}</span>
        </div>`;
    }).join("");
  }

  function renderTech(data, env, climate, outlook) {
    const soil = env.soil || {};
    const tech = [
      ["Ortalama sıcaklık", `${num(climate.annual_mean_temp_c, 1)} °C`],
      ["Yıllık yağış", `${num(climate.annual_precip_mm)} mm`],
      ["İklim sınıfı", climateLabel(climate.climate_class)],
      ["Toprak nemi (NASA)", num(soil.root_zone_moisture_mean, 2)],
      ["Toprak sıcaklığı", `${num(soil.mean_soil_temp_c, 1)} °C`],
      ["Eğilim dönemi", outlook.available ? `${outlook.start_year}–${outlook.end_year}` : "yok"],
      ["AI açıklama", data.ai?.kind === "llm" ? "dil modeli" : "kural motoru"],
      ["Plan no", String(data.plan_id || "").slice(0, 10)],
    ];
    $("techDetails").innerHTML = `
      <div class="tech-grid">
        ${tech.map(([label, value]) => `<div class="tech-item"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("")}
      </div>
      <h3 class="subhead">Veri kaynakları</h3>
      <ul class="ticks">
        ${(data.data_sources || []).map((source) => `<li><strong>${esc(source.name)}</strong> — ${esc(source.description)}</li>`).join("")}
      </ul>`;
    const warnings = data.warnings || [];
    $("techWarnings").innerHTML = warnings.length
      ? `<strong>Uyarılar:</strong><br>${warnings.map((warning) => `• ${esc(warning)}`).join("<br>")}`
      : "";
  }

  /* ------------------------------------------------------------- checklists */
  function restoreChecks(planId) {
    if (!planId) return;
    let store = {};
    try { store = JSON.parse(localStorage.getItem(CHECKS_KEY) || "{}"); } catch (error) { store = {}; }
    const checked = store[planId] || [];
    document.querySelectorAll('#firstSteps input[type="checkbox"]').forEach((input) => {
      input.checked = checked.includes(Number(input.dataset.checkIndex));
    });
  }
  function persistChecks(planId) {
    if (!planId) return;
    let store = {};
    try { store = JSON.parse(localStorage.getItem(CHECKS_KEY) || "{}"); } catch (error) { store = {}; }
    store[planId] = Array.from(document.querySelectorAll('#firstSteps input[type="checkbox"]'))
      .filter((input) => input.checked)
      .map((input) => Number(input.dataset.checkIndex));
    try { localStorage.setItem(CHECKS_KEY, JSON.stringify(store)); } catch (error) { /* ignore */ }
  }

  /* --------------------------------------------------------------- speaking */
  function spokenSummary() {
    const data = state.plan;
    if (!data) return "";
    const advice = data.advice || {};
    const rotation = data.rotation || {};
    const soil = data.soil_health || {};
    const water = data.water || {};
    const parts = [
      advice.headline || "",
      advice.why || "",
      rotation.summary || "",
      soil.summary || "",
      water.summary || "",
      (advice.steps || []).slice(0, 3).join(" "),
      "Bu bir karar destek aracıdır. Ekimden önce toprak analizi yaptır ve yerel tarım uzmanına danış.",
    ];
    return parts.filter(Boolean).join(" ");
  }
  function toggleSpeech() {
    if (!("speechSynthesis" in window)) {
      toast("Tarayıcın sesli okumayı desteklemiyor.");
      return;
    }
    if (state.speaking) {
      window.speechSynthesis.cancel();
      state.speaking = false;
      $("listenBtn").textContent = "🔊 Dinle";
      return;
    }
    const text = spokenSummary();
    if (!text) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "tr-TR";
    utterance.rate = 0.92;
    utterance.pitch = 1;
    utterance.onend = () => {
      state.speaking = false;
      $("listenBtn").textContent = "🔊 Dinle";
    };
    utterance.onerror = () => {
      state.speaking = false;
      $("listenBtn").textContent = "🔊 Dinle";
    };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
    state.speaking = true;
    $("listenBtn").textContent = "⏹ Durdur";
  }

  /* ------------------------------------------------------------- share/print */
  async function sharePlan() {
    const data = state.plan;
    if (!data) return;
    const text = spokenSummary();
    const shareData = {
      title: "Tarla Dostu — ekim planım",
      text: text.slice(0, 800),
      url: window.location.href,
    };
    if (navigator.share) {
      try { await navigator.share(shareData); return; } catch (error) { /* cancelled */ }
    }
    try {
      await navigator.clipboard.writeText(text);
      toast("Plan metni kopyalandı.");
    } catch (error) {
      toast("Paylaşım bu tarayıcıda çalışmadı.");
    }
  }
  function downloadJson() {
    if (!state.plan && !state.payload) return;
    const payload = JSON.stringify(state.plan || state.payload, null, 2);
    const blob = new Blob([payload], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `tarla-plani-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  /* ------------------------------------------------------------------- init */
  function bind() {
    $("startBtn").addEventListener("click", startWizard);
    $("lastPlanBtn").addEventListener("click", () => loadSavedPlan(false));
    $("nextBtn").addEventListener("click", () => {
      if (!validateStep(state.step)) return;
      if (state.step < 3) goToStep(state.step + 1);
    });
    $("backBtn").addEventListener("click", () => {
      if (state.step === 1) {
        showScreen("screen-home");
      } else {
        goToStep(state.step - 1);
      }
    });
    $("submitBtn").addEventListener("click", submitPlan);
    $("geoBtn").addEventListener("click", useGeolocation);
    $("citySelect").addEventListener("change", (event) => {
      const option = event.target.selectedOptions[0];
      if (!option || !option.dataset.lat) return;
      state.place = `${option.textContent}, Türkiye`;
      setLocation(Number(option.dataset.lat), Number(option.dataset.lon), { zoomLevel: 11, reverse: false });
      $("placeName").textContent = `📍 ${state.place}`;
    });
    $("applyCoords").addEventListener("click", () => {
      const lat = numOrNull($("latInput").value);
      const lon = numOrNull($("lonInput").value);
      if (lat == null || lon == null) { toast("Enlem ve boylamı gir."); return; }
      setLocation(lat, lon, { zoomLevel: 13, reverse: true });
    });

    document.querySelectorAll("[data-delta]").forEach((button) => {
      button.addEventListener("click", () => {
        const input = $("areaInput");
        const current = Number(input.value) || 0;
        const next = Math.max(1, Math.min(100000, current + Number(button.dataset.delta)));
        input.value = String(next);
      });
    });

    document.querySelectorAll("[data-example]").forEach((button) => {
      button.addEventListener("click", () => {
        $("freeText").value = button.dataset.example;
        $("freeText").focus();
      });
    });

    document.querySelectorAll('.goal input, .choice input').forEach((input) => {
      input.addEventListener("change", () => {
        document.querySelectorAll(`input[name="${input.name}"]`).forEach((peer) => {
          peer.closest("label").classList.toggle("is-selected", peer.checked);
        });
      });
    });

    $("firstSteps").addEventListener("change", () => {
      if (state.plan) persistChecks(state.plan.plan_id);
    });

    $("listenBtn").addEventListener("click", toggleSpeech);
    $("printBtn").addEventListener("click", () => window.print());
    $("printBtn2").addEventListener("click", () => window.print());
    $("shareBtn").addEventListener("click", sharePlan);
    $("downloadBtn").addEventListener("click", downloadJson);
    $("newPlanBtn").addEventListener("click", () => {
      showScreen("screen-wizard");
      goToStep(1, { scroll: false });
      setTimeout(initMap, 60);
    });

    $("helpBtn").addEventListener("click", () => {
      const dialog = $("helpDialog");
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    });

    $("textToggle").addEventListener("click", () => {
      const big = document.documentElement.classList.toggle("big-text");
      localStorage.setItem(TEXT_KEY, big ? "1" : "0");
      $("textToggle").textContent = big ? "A−" : "A+";
      $("textToggle").setAttribute("aria-label", big ? "Yazıyı küçült" : "Yazıyı büyüt");
      setTimeout(() => { if (state.map) state.map.invalidateSize(); }, 200);
    });

    const savedText = localStorage.getItem(TEXT_KEY);
    if (savedText === "1") {
      document.documentElement.classList.add("big-text");
      $("textToggle").textContent = "A−";
    }

    window.addEventListener("scroll", () => {
      document.querySelector(".topbar").classList.toggle("scrolled", window.scrollY > 6);
    }, { passive: true });

    window.addEventListener("online", updateConnection);
    window.addEventListener("offline", updateConnection);
    updateConnection();

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/app/sw.js", { scope: "/app/" }).catch(() => { /* non-fatal */ });
    }
  }

  function updateConnection() {
    const offline = !navigator.onLine;
    $("offlineBanner").hidden = !offline;
  }

  function readUrlLocation() {
    let params;
    try { params = new URLSearchParams(window.location.search); } catch (error) { return false; }
    const lat = numOrNull(params.get("lat"));
    const lon = numOrNull(params.get("lon"));
    if (lat == null || lon == null) return false;
    state.lat = lat;
    state.lon = lon;
    $("latInput").value = lat.toFixed(5);
    $("lonInput").value = lon.toFixed(5);
    $("placeName").textContent = `Seçilen nokta: ${lat.toFixed(4)}, ${lon.toFixed(4)}`;
    startWizard();
    setTimeout(() => setLocation(lat, lon, { zoomLevel: 13, reverse: true }), 220);
    return true;
  }

  populate();
  bind();
  goToStep(1, { scroll: false });
  updateLastPlanButton();
  readUrlLocation();
})();
