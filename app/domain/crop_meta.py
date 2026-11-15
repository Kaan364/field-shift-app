"""Presentation and rotation metadata for the crop catalogue.

The agronomic envelope lives in :mod:`app.domain.crops`. This module adds two
things that are useful for the farmer-facing product and the rotation engine:

* a stable emoji + plain-language family label (low-literacy UI), and
* rotation traits (nitrogen fixation, residue cover, rooting depth, ...).

Keeping this separate means the crop catalogue stays focused on the rule
engine, while rotation logic can evolve independently. All values are
approximate and deliberately transparent; they are not a substitute for a
local agronomist.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.crops import CROP_CATALOG

FAMILY_LABELS_TR = {
    "cereal": "Tahıl",
    "legume": "Baklagil",
    "oilseed": "Yağ bitkisi",
    "root": "Kök bitkisi",
    "vegetable": "Sebze",
    "fiber": "Lif bitkisi",
    "forage": "Yem bitkisi",
    "perennial": "Çok yıllık",
}


@dataclass(frozen=True)
class RotationTraits:
    """How a crop behaves inside a multi-year rotation."""

    family: str
    icon: str
    nitrogen_fixing: bool = False
    # Fraction of the soil left covered by residue after harvest (0..1).
    residue_cover: float = 0.5
    rooting: str = "medium"  # shallow | medium | deep
    soil_improver: bool = False
    pollinator: bool = False
    # How strongly the crop breaks disease cycles of the previous family (0..1).
    break_crop: float = 0.4
    # True for crops that stay in the field for more than one season.
    multi_year: bool = False
    # Short, farmer-friendly role in a rotation.
    role: str = ""
    benefit: str = ""

    @property
    def family_label(self) -> str:
        return FAMILY_LABELS_TR.get(self.family, self.family)


_CEREAL = dict(family="cereal", residue_cover=0.72, rooting="medium", break_crop=0.35)
_LEGUME = dict(
    family="legume",
    nitrogen_fixing=True,
    residue_cover=0.45,
    rooting="deep",
    soil_improver=True,
    break_crop=0.7,
)
_OILSEED = dict(family="oilseed", residue_cover=0.5, rooting="deep", break_crop=0.55)
_ROOT = dict(family="root", residue_cover=0.18, rooting="shallow", break_crop=0.6)
_FORAGE = dict(
    family="forage",
    nitrogen_fixing=True,
    residue_cover=0.8,
    rooting="deep",
    soil_improver=True,
    break_crop=0.75,
)


def _t(base: dict, **overrides) -> RotationTraits:
    """Create traits from a family template plus per-crop overrides."""

    return RotationTraits(**{**base, **overrides})


ROTATION_TRAITS: dict[str, RotationTraits] = {
    "wheat": _t(
        _CEREAL,
        icon="🌾",
        role="Ana tahıl",
        benefit="Sap ve anız bırakır; toprağı örter ve gelir getirir.",
    ),
    "barley": _t(
        _CEREAL,
        icon="🌾",
        role="Dayanıklı tahıl",
        benefit="Kurağa ve tuzluluğa dayanıklıdır; hayvan yemi olarak da satılır.",
    ),
    "triticale": _t(
        _CEREAL,
        icon="🌾",
        role="Kışlık tahıl",
        benefit="Kışa çok dayanıklıdır; zayıf topraklarda bile tutunur.",
    ),
    "oats": _t(
        _CEREAL,
        icon="🌾",
        role="Yemlik tahıl",
        benefit="Serin havayı sever; yeşil gübre karışımlarında kullanılır.",
    ),
    "maize": RotationTraits(
        family="cereal",
        icon="🌽",
        residue_cover=0.8,
        rooting="deep",
        break_crop=0.4,
        role="Yüksek verimli tahıl",
        benefit="Verimi yüksektir ama su ve azot isteği fazladır.",
    ),
    "sunflower": _t(
        _OILSEED,
        icon="🌻",
        pollinator=True,
        role="Yağlık gelir ürünü",
        benefit="Derin kökleri toprağı kullanır; arı ve böcekleri çeker.",
    ),
    "canola": _t(
        _OILSEED,
        icon="🌼",
        pollinator=True,
        break_crop=0.65,
        role="Kışlık yağ bitkisi",
        benefit="Hastalık döngüsünü kırar; arılar için erken çiçek sağlar.",
    ),
    "safflower": _t(
        _OILSEED,
        icon="🌺",
        break_crop=0.6,
        role="Kuraklığa dayanıklı yağ bitkisi",
        benefit="Suyu az olan tarlada bile yağ üretir.",
    ),
    "chickpea": _t(
        _LEGUME,
        icon="🫘",
        role="Toprağı besleyen baklagil",
        benefit="Havadan azot bağlar; azot gübresi ihtiyacını azaltır.",
    ),
    "lentil": _t(
        _LEGUME,
        icon="🫘",
        role="Kurak baklagil",
        benefit="Az suyla yetişir, toprağa azot kazandırır.",
    ),
    "soybean": _t(
        _LEGUME,
        icon="🫘",
        role="Yağlık baklagil",
        benefit="Azot bağlar ve iyi bir gelir ürünüdür; suyu sever.",
    ),
    "alfalfa": _t(
        _FORAGE,
        icon="🌿",
        multi_year=True,
        role="Çok yıllık yem bitkisi",
        benefit="Kökleri toprağı derin besler; 2-3 yıl tarlada kalabilir.",
    ),
    "sainfoin": _t(
        _FORAGE,
        icon="🌿",
        multi_year=True,
        role="Kurak yem bitkisi",
        benefit="Kurağa dayanıklı baklagil; toprağı azotla zenginleştirir.",
    ),
    "vetch": _t(
        _FORAGE,
        icon="🌱",
        role="Yeşil gübre",
        benefit="Toprağa azot bağlar; çiçekteyken toprağa karıştırılır.",
    ),
    "potato": _t(
        _ROOT,
        icon="🥔",
        role="Yüksek gelirli kök bitkisi",
        benefit="Toprağı havalandırır; iyi gelir getirir ama suyu sever.",
    ),
    "sugar_beet": _t(
        _ROOT,
        icon="🍬",
        role="Sözleşmeli gelir ürünü",
        benefit="Derin kökü toprağı açar; kontratlı üretim gerektirir.",
    ),
    "tomato": RotationTraits(
        family="vegetable",
        icon="🍅",
        residue_cover=0.2,
        rooting="medium",
        break_crop=0.65,
        role="Yüksek gelirli sebze",
        benefit="İyi gelir getirir; su, gübre ve işçilik isteği yüksektir.",
    ),
    "cotton": RotationTraits(
        family="fiber",
        icon="🧵",
        residue_cover=0.35,
        rooting="deep",
        break_crop=0.55,
        role="Sıcak iklim gelir ürünü",
        benefit="Uzun sezon ister; sulama olmadan ekonomik değildir.",
    ),
    "olive": RotationTraits(
        family="perennial",
        icon="🫒",
        residue_cover=0.6,
        rooting="deep",
        multi_year=True,
        break_crop=0.8,
        role="Çok yıllık bahçe",
        benefit="Uzun vadeli yatırımdır; yıllık ekim nöbetine girmez.",
    ),
    "grape": RotationTraits(
        family="perennial",
        icon="🍇",
        residue_cover=0.5,
        rooting="deep",
        multi_year=True,
        break_crop=0.8,
        role="Çok yıllık bağ",
        benefit="Uzun vadeli yatırımdır; yıllık ekim nöbetine girmez.",
    ),
    "apple": RotationTraits(
        family="perennial",
        icon="🍎",
        residue_cover=0.55,
        rooting="deep",
        multi_year=True,
        break_crop=0.8,
        role="Çok yıllık meyve bahçesi",
        benefit="Uzun vadeli yatırımdır; yıllık ekim nöbetine girmez.",
    ),
}

DEFAULT_TRAITS = RotationTraits(family="other", icon="🌱", role="Ürün", benefit="")


def traits_for(crop_key: str) -> RotationTraits:
    return ROTATION_TRAITS.get(crop_key, DEFAULT_TRAITS)


def icon_for(crop_key: str) -> str:
    return traits_for(crop_key).icon


def family_for(crop_key: str) -> str:
    return traits_for(crop_key).family


def validate_traits() -> list[str]:
    """Return consistency problems so new crops cannot be forgotten."""

    problems: list[str] = []
    for key in CROP_CATALOG:
        if key not in ROTATION_TRAITS:
            problems.append(f"{key}: rotation traits missing")
            continue
        traits = ROTATION_TRAITS[key]
        if not 0.0 <= traits.residue_cover <= 1.0:
            problems.append(f"{key}: residue_cover out of range")
        if not 0.0 <= traits.break_crop <= 1.0:
            problems.append(f"{key}: break_crop out of range")
        if traits.rooting not in {"shallow", "medium", "deep"}:
            problems.append(f"{key}: invalid rooting depth")
        if traits.nitrogen_fixing and traits.family not in {"legume", "forage"}:
            problems.append(f"{key}: nitrogen fixing crop is not a legume/forage")
    return problems
