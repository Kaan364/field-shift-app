"""Deterministic, offline "AI fallback" advisor.

This is not a language model. It turns the rule engine's component scores into
a readable recommendation. It guarantees that the API remains useful and
testable without any API key or internet access to an LLM.
"""

from __future__ import annotations

from typing import Any

from app.ai.base import (
    AIAnalysis,
    AIContext,
    AICropAssessment,
    AdviceContext,
    AIProvider,
)
from app.schemas import AdvicePlan
from app.services.agronomy import CLIMATE_CLASS_LABELS_TR

NITROGEN_LABELS_TR = {
    "low": "az",
    "medium": "orta",
    "high": "fazla",
}
NITROGEN_LABELS_EN = {
    "low": "low",
    "medium": "medium",
    "high": "high",
}


def _tr_list(items: list[str], limit: int = 3) -> str:
    return "; ".join(items[:limit])


def _actions_tr(components: dict[str, float | None], irrigation: str) -> list[str]:
    actions: list[str] = []
    water = components.get("water")
    if water is not None and water < 70:
        if irrigation == "rainfed":
            actions.append(
                "Sulama imkânı yoksa kuraklığa dayanıklı çeşit seçin ve ekim tarihini toprak nemine göre ayarlayın."
            )
        else:
            actions.append("Sezon başı su bütçesini ve sulama programını netleştirin; kritik dönemlerde suyu ayırın.")
    temperature = components.get("temperature")
    if temperature is not None and temperature < 70:
        actions.append("Ekim tarihini yerel don takvimine göre ayarlayın; genç bitkiyi don ve sıcak dalgasından koruyun.")
    ph = components.get("ph")
    if ph is not None and ph < 70:
        actions.append("Toprak analizine göre kireç veya jips uygulamasını yerel uzmanla planlayın.")
    texture = components.get("texture")
    if texture is not None and texture < 70:
        actions.append("Toprak işlemeyi azaltın; organik madde ve malç ile bünyeyi iyileştirin.")
    salinity = components.get("salinity")
    if salinity is not None and salinity < 70:
        actions.append("Drenajı kontrol edin, tuz birikimini izleyin ve gerekiyorsa yıkama sulaması yapın.")
    climate = components.get("climate_risk")
    if climate is not None and climate < 70:
        actions.append("Don/sıcak dalgası sigortası ve risk dağıtımı (farklı tarla/çeşit) değerlendirin.")
    market = components.get("market")
    if market is not None and market < 70:
        actions.append("Ekim öncesi alıcı sözleşmesi, depolama veya kooperatif satış seçeneklerini araştırın.")
    if not actions:
        actions.append("Ekim öncesi sertifikalı tohum, toprak hazırlığı ve gübre planını yerel uzmanla doğrulayın.")
    actions.append("Sezon boyunca yağış, toprak nemi ve hastalık kayıtlarını düzenli tutun.")
    return actions[:5]


def _actions_en(components: dict[str, float | None], irrigation: str) -> list[str]:
    actions: list[str] = []
    water = components.get("water")
    if water is not None and water < 70:
        if irrigation == "rainfed":
            actions.append("If irrigation is unavailable, choose a drought-tolerant variety and align planting with soil moisture.")
        else:
            actions.append("Define the seasonal water budget and protect critical growth stages.")
    temperature = components.get("temperature")
    if temperature is not None and temperature < 70:
        actions.append("Adjust the planting date to the local frost calendar and protect young plants.")
    ph = components.get("ph")
    if ph is not None and ph < 70:
        actions.append("Plan lime or gypsum applications with a local agronomist based on a soil test.")
    texture = components.get("texture")
    if texture is not None and texture < 70:
        actions.append("Reduce tillage and build organic matter / mulch to improve soil structure.")
    salinity = components.get("salinity")
    if salinity is not None and salinity < 70:
        actions.append("Check drainage, monitor salt accumulation and leach if necessary.")
    climate = components.get("climate_risk")
    if climate is not None and climate < 70:
        actions.append("Evaluate frost/heat insurance and risk diversification across fields or varieties.")
    market = components.get("market")
    if market is not None and market < 70:
        actions.append("Explore forward contracts, storage or cooperative sales before planting.")
    if not actions:
        actions.append("Confirm certified seed, soil preparation and fertilisation with a local expert.")
    actions.append("Keep records of rainfall, soil moisture and crop health during the season.")
    return actions[:5]


def _risks_tr(candidate: dict[str, Any]) -> list[str]:
    limits = candidate.get("limiting_factors") or []
    risks = list(limits[:4])
    if not risks:
        risks.append("Belirgin agronomik kısıt yok; yine de fiyat ve hava koşulları belirsizdir.")
    risks.append("NASA POWER grid verisi tarla ölçeğindeki farklılıkları göstermeyebilir.")
    return risks[:4]


def _risks_en(candidate: dict[str, Any]) -> list[str]:
    limits = candidate.get("limiting_factors") or []
    risks = list(limits[:4])
    if not risks:
        risks.append("No major agronomic constraint, but price and weather remain uncertain.")
    risks.append("NASA POWER gridded data may not capture field-scale variability.")
    return risks[:4]


class HeuristicProvider(AIProvider):
    name = "heuristic"
    model = None
    kind = "deterministic"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason

    async def analyze(self, context: AIContext) -> AIAnalysis:
        tr = context.language == "tr"
        candidates = context.candidates
        if not candidates:
            return AIAnalysis(
                summary="Değerlendirilecek aday ekin bulunamadı." if tr else "No candidate crops were available.",
                confidence="low",
            )

        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        region = context.location.get("region_name") or (
            f"{context.location.get('latitude')}, {context.location.get('longitude')}"
        )
        climate = context.environment.get("climate", {})
        climate_class = climate.get("climate_class") or "unknown"
        rainfall = climate.get("annual_precip_mm")
        mean_temp = climate.get("annual_mean_temp_c")

        assessments: list[AICropAssessment] = []
        for candidate in candidates:
            components = candidate.get("component_scores", {}) or {}
            strengths = candidate.get("strengths") or []
            limits = candidate.get("limiting_factors") or []
            irrigation = (context.farmer.get("resources") or {}).get("irrigation", "rainfed")

            if tr:
                rationale_parts = [
                    f"{candidate['crop_name_local']}, bölge koşullarında {candidate['rule_score']}/100 uygunluk aldı."
                ]
                if strengths:
                    rationale_parts.append("Güçlü yönler: " + _tr_list(strengths) + ".")
                if limits:
                    rationale_parts.append("Sınırlar: " + _tr_list(limits) + ".")
                rationale = " ".join(rationale_parts)
                actions = _actions_tr(components, irrigation)
                risks = _risks_tr(candidate)
            else:
                rationale_parts = [
                    f"{candidate['crop_name']} scored {candidate['rule_score']}/100 under the local conditions."
                ]
                if strengths:
                    rationale_parts.append("Strengths: " + "; ".join(strengths[:3]) + ".")
                if limits:
                    rationale_parts.append("Constraints: " + "; ".join(limits[:3]) + ".")
                rationale = " ".join(rationale_parts)
                actions = _actions_en(components, irrigation)
                risks = _risks_en(candidate)

            assessments.append(
                AICropAssessment(
                    crop_key=candidate["crop_key"],
                    ai_score=float(candidate["rule_score"]),
                    rationale=rationale,
                    risks=risks,
                    actions=actions,
                    planting_window=candidate.get("planting_window"),
                )
            )

        gap = top["rule_score"] - (second["rule_score"] if second else 0)
        present_components = sum(
            1 for value in (top.get("component_scores") or {}).values() if value is not None
        )
        if gap < 5 or present_components <= 5:
            confidence = "low"
        elif gap >= 10 and present_components >= 8:
            confidence = "high"
        else:
            confidence = "medium"

        if tr:
            summary = (
                f"{region} için mevcut verilerle en güçlü seçenek {top['crop_name_local']} "
                f"({top['rule_score']}/100)."
            )
            if second:
                summary += f" Ardından {second['crop_name_local']} ({second['rule_score']}/100) geliyor."
            if rainfall is not None and mean_temp is not None:
                summary += (
                    f" Bölge iklimi {CLIMATE_CLASS_LABELS_TR.get(climate_class, climate_class)} "
                    f"sınıfında; yıllık ortalama sıcaklık {mean_temp}°C, yıllık yağış {rainfall} mm."
                )
            summary += (
                " Bu bir ön karar destek çıktısıdır; ekim öncesi yerel tarım uzmanı ve toprak analizi ile doğrulanmalıdır."
            )
            general_risks = [
                "Kuraklık, don ve sıcak dalgası gibi hava olayları verimi düşürebilir.",
                "Girdi fiyatları ve satış fiyatı dalgalanması kârlılığı belirsizleştirir.",
                "NASA POWER verisi tarla ölçeğinde değildir; toprak analizi ve yerel gözlem şarttır.",
            ]
            general_actions = [
                "Ekim öncesi pH, organik madde ve besin elementleri için toprak analizi yaptırın.",
                "İl/ilçe tarım müdürlüğü veya agronomist ile çeşit ve ekim takvimini doğrulayın.",
                "Suyun debisi ve sezonluk kullanım hakkını kontrol edin; sulama planı yapın.",
                "İlk yıl tüm tarlayı riske atmayın; küçük bir pilot alanla başlayın.",
            ]
        else:
            summary = (
                f"For {region}, the strongest option with the available data is {top['crop_name']} "
                f"({top['rule_score']}/100)."
            )
            if second:
                summary += f" Next is {second['crop_name']} ({second['rule_score']}/100)."
            if rainfall is not None and mean_temp is not None:
                summary += (
                    f" The climate is classified as {climate_class}; annual mean temperature is "
                    f"{mean_temp}°C and annual rainfall is {rainfall} mm."
                )
            summary += " This is preliminary decision support; confirm with a local agronomist and a soil test."
            general_risks = [
                "Drought, frost and heat waves can reduce yield.",
                "Input and output price volatility creates financial uncertainty.",
                "NASA POWER data is gridded, not field-scale; soil testing and local observation are required.",
            ]
            general_actions = [
                "Run a soil test for pH, organic matter and nutrients before planting.",
                "Confirm variety and planting calendar with the local extension service or an agronomist.",
                "Check water rights and seasonal water availability; prepare an irrigation plan.",
                "Start with a pilot plot instead of risking the whole farm in year one.",
            ]

        return AIAnalysis(
            summary=summary,
            crops=assessments,
            general_risks=general_risks,
            general_actions=general_actions,
            confidence=confidence,
            notes=(
                "Deterministik kural motoru kullanıldı; LLM çağrısı yapılmadı."
                if tr
                else "Deterministic rule engine was used; no LLM call was made."
            ),
        )

    async def advise(self, context: AdviceContext) -> AdvicePlan:
        """Serbest metinli soruya, LLM olmadan sade dilli deterministik cevap."""

        if context.language == "tr":
            return _build_advice_tr(context)
        return _build_advice_en(context)


# ---------------------------------------------------------------------------
# Deterministic advice builders (no LLM)
# ---------------------------------------------------------------------------
def _num(value: object, digits: int = 0) -> str | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if digits == 0:
        return f"{number:.0f}"
    return f"{number:.{digits}f}"


def _advice_confidence(candidates: list[dict[str, Any]], missing: int) -> str:
    if not candidates:
        return "low"
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    gap = float(top.get("rule_score") or 0) - float((second or {}).get("rule_score") or 0)
    if missing >= 2:
        return "low"
    if gap >= 10 and missing == 0:
        return "high"
    return "medium"


def _commentary(context: AdviceContext, crop_name: str | None = None) -> str:
    """Plain-English AI-style note that combines money and weather risk."""

    econ = context.economics or {}
    risk = context.risk or {}
    name = crop_name or "this crop"
    parts: list[str] = []

    margin_decare = _num(econ.get("margin_per_decare_usd"), 0)
    cost = _num(econ.get("total_cost_usd"), 0)
    low = _num(econ.get("low_profit_usd"), 0)
    high = _num(econ.get("high_profit_usd"), 0)
    if margin_decare is not None:
        parts.append(
            f"For {name}, the planning budget leaves about ${margin_decare} profit per decare "
            f"after about ${cost} of costs for your field."
        )
    if low is not None and high is not None:
        parts.append(f"Depending on price and yield, the result could range from ${low} to ${high}.")

    frost = risk.get("frost")
    heat = risk.get("heat")
    drought = risk.get("drought")
    if frost or heat or drought:
        parts.append(
            f"Weather risk is frost: {frost or 'unknown'}, heat: {heat or 'unknown'}, "
            f"drought: {drought or 'unknown'}."
        )
    if risk.get("last_frost_month"):
        parts.append(f"In a normal year the last spring frost is in {risk['last_frost_month']}.")
    if risk.get("first_frost_month"):
        parts.append(f"The first autumn frost is normally in {risk['first_frost_month']}.")

    headline = econ.get("headline")
    if headline:
        parts.append(str(headline) + ".")
    parts.append("These are planning estimates. Check the local price and the 5-day forecast before you act.")
    return " ".join(part for part in parts if part).strip()


def _missing_questions_tr(context: AdviceContext) -> list[str]:
    field = context.farmer.get("field") or {}
    questions: list[str] = []
    if not field.get("soil_ph"):
        questions.append("Toprağının pH değerini biliyor musun? (Toprak analizi yaptırabilirsin.)")
    if not field.get("organic_matter_pct"):
        questions.append("Toprağında organik madde (humus) ne kadar? Bilmiyorsan sorun değil.")
    if not context.location.get("region_name"):
        questions.append("Tarlan hangi il veya ilçede?")
    if not (context.farmer.get("preferences") or {}).get("planting_month"):
        questions.append("Ekim yapmayı düşündüğün ay hangisi?")
    if not context.free_text.strip():
        questions.append("Tarlanı sulayabiliyor musun? Suyun ne kadar var?")
    return questions[:3]


def _build_advice_tr(context: AdviceContext) -> AdvicePlan:
    candidates = context.candidates
    if not candidates:
        return AdvicePlan(
            headline="Şu an güvenilir bir öneri üretemedim.",
            why="Konum veya tarla bilgisi yetersiz kaldı. Veriler gelmeden tahmin yürütmek istemiyorum.",
            steps=["Konumunu haritadan seç ve tekrar dene.", "Bilmiyorsan alanı boş bırakabilirsin."],
            ask_farmer=["Tarlan nerede?", "Tarlan yaklaşık kaç dönüm?"],
            confidence="low",
        )

    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    name = top.get("crop_name_local") or top.get("crop_name") or "bu bitki"
    climate = context.environment.get("climate") or {}
    rain = _num(climate.get("annual_precip_mm"))
    temp = _num(climate.get("annual_mean_temp_c"), 1)
    climate_class = climate.get("climate_class") or "unknown"
    resources = context.farmer.get("resources") or {}
    irrigation = resources.get("irrigation", "rainfed")
    water_need = top.get("water_need_mm")
    nitrogen = NITROGEN_LABELS_TR.get(str(top.get("nitrogen_need") or ""), None)
    window = top.get("planting_window") or "bölgene uygun ekim zamanı"
    score = _num(top.get("rule_score"), 1)

    headline = f"Bu tarlada {name} ekmen en doğrusu."
    if second:
        headline += f" Alternatif: {second.get('crop_name_local')}."

    why_parts: list[str] = []
    if rain and temp:
        why_parts.append(
            f"Bölgende yıllık yağış yaklaşık {rain} mm, ortalama sıcaklık {temp}°C."
        )
    why_parts.append(
        f"{name}, bu koşullarda 100 üzerinden {score} puan aldı "
        f"({CLIMATE_CLASS_LABELS_TR.get(climate_class, climate_class)} iklim)."
    )
    if top.get("strengths"):
        why_parts.append(f"İyi yönü: {top['strengths'][0]}.")
    if top.get("limiting_factors"):
        why_parts.append(f"Dikkat etmen gereken yön: {top['limiting_factors'][0]}.")

    steps = [
        "Önce toprağını analiz ettir. Böylece ne kadar gübre gerektiğini bilirsin.",
        f"Ekim zamanı: {window}.",
        "Sertifikalı tohum al ve torbadaki ekim önerisine uy.",
        "Ekmeden önce tarlayı sür, düzle ve yabancı otları temizle.",
        "İlk yıl tarlanın tamamını değil, küçük bir bölümünü ek. Sonucu gör, sonra büyüt.",
    ]

    grow = [
        "Tohum yatağı ince ve düz olsun; büyük kesek kalmasın.",
        "Toprak çok ıslaksa ekimi birkaç gün geciktir.",
        "Ekimden sonra toprağı hafifçe bastır ki tohum toprakla temas etsin.",
        "Çıkış olduktan sonra seyrek kalan yerleri kontrol et.",
    ]

    feed = ["Gübreyi mutlaka toprak analizine göre ver. Fazla gübre bitkiyi de yakar."]
    if nitrogen:
        feed.append(f"Bu bitkinin azot ihtiyacı: {nitrogen}.")
    feed.append("Gübreyi ekimle birlikte ve büyüme döneminde ikiye bölerek ver.")
    feed.append("Hayvan gübresi kullanacaksan iyice yanmış (olgun) gübre kullan.")

    care: list[str] = []
    if water_need:
        care.append(f"Bu bitki sezon boyunca yaklaşık {int(water_need)} mm su ister.")
        if rain and water_need:
            deficit = max(0, int(water_need) - int(float(rain)))
            if deficit > 0:
                care.append(
                    f"Yağış yaklaşık {rain} mm olduğu için yaklaşık {deficit} mm ek sulama gerekebilir."
                )
            else:
                care.append("Yağış yeterli görünüyor; yine de kurak dönemlerde tarlayı kontrol et.")
    if irrigation == "rainfed":
        care.append("Sulama imkânın yoksa kurak dönemde bitkiyi strese sokmamak için erken ekim yap.")
    care.append("Yabancı otları küçükken temizle; büyüyünce bitkiyle su için yarışır.")
    care.append("Haftada bir tarlayı gez. Sararma, leke veya böcek görürsen tarım müdürlüğüne sor.")

    risks = list(top.get("limiting_factors") or [])[:3]
    risks.append("Hava koşulları her yıl aynı olmaz; don ve kuraklık riski her zaman vardır.")
    risks.append("NASA verisi tarlanın tamamını değil, bölgeyi temsil eder.")

    missing = _missing_questions_tr(context)
    return AdvicePlan(
        headline=headline,
        why=" ".join(why_parts),
        commentary=_commentary(context, name),
        steps=steps[:5],
        grow=grow[:5],
        feed=feed[:5],
        care=care[:5],
        risks=risks[:4],
        ask_farmer=missing,
        confidence=_advice_confidence(candidates, len(missing)),
    )


def _build_advice_en(context: AdviceContext) -> AdvicePlan:
    candidates = context.candidates
    if not candidates:
        return AdvicePlan(
            headline="I cannot give a reliable recommendation yet.",
            why="The location or field information is insufficient.",
            steps=["Pick your location on the map and try again."],
            ask_farmer=["Where is your field?", "How large is it?"],
            confidence="low",
        )

    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    name = top.get("crop_name") or "this crop"
    climate = context.environment.get("climate") or {}
    rain = _num(climate.get("annual_precip_mm"))
    temp = _num(climate.get("annual_mean_temp_c"), 1)
    irrigation = (context.farmer.get("resources") or {}).get("irrigation", "rainfed")
    water_need = top.get("water_need_mm")

    headline = f"Plant {name} on this field."
    if second:
        headline += f" Alternative: {second.get('crop_name')}."

    why = (
        f"Annual rainfall is about {rain} mm and mean temperature {temp}°C. "
        f"{name} scored {_num(top.get('rule_score'), 1)}/100 for these conditions."
        if rain and temp
        else f"{name} scored {_num(top.get('rule_score'), 1)}/100 for these conditions."
    )

    care = []
    if water_need:
        care.append(f"This crop needs about {int(water_need)} mm of water per season.")
        if rain:
            deficit = max(0, int(water_need) - int(float(rain)))
            if deficit > 0:
                care.append(f"With about {rain} mm of rain, you may need roughly {deficit} mm of irrigation.")
    if irrigation == "rainfed":
        care.append("Without irrigation, plant early and protect the crop during dry spells.")
    care.append("Control weeds early and inspect the field weekly for pests or disease.")

    return AdvicePlan(
        headline=headline,
        why=why,
        commentary=_commentary(context, name),
        steps=[
            "Get a soil test first so you know what fertiliser you need.",
            f"Planting window: {top.get('planting_window') or 'your local window'}.",
            "Use certified seed and follow the sowing guidance on the bag.",
            "Prepare and level the seedbed before sowing.",
            "In the first year, plant a small plot before risking the whole field.",
        ],
        grow=[
            "Keep the seedbed fine and level.",
            "Delay sowing a few days if the soil is waterlogged.",
            "Press the soil lightly after sowing so seed contacts soil.",
            "Check emergence and fill any gaps.",
        ],
        feed=[
            "Fertilise according to the soil test, not by guess.",
            f"Nitrogen need for this crop: {NITROGEN_LABELS_EN.get(str(top.get('nitrogen_need') or ''), 'unknown')}.",
            "Split nitrogen applications across the season.",
        ],
        care=care[:5],
        risks=[
            *(top.get("limiting_factors") or [])[:3],
            "Weather varies each year; frost and drought risk remain.",
            "NASA data represents the region, not your exact field.",
        ],
        ask_farmer=["Can you irrigate?", "Which month do you plan to plant?", "What is your soil pH?"][:3],
        confidence=_advice_confidence(candidates, 1),
    )

