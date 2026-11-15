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

FAMILY_LABELS_EN = {
    "cereal": "Cereal",
    "legume": "Legume",
    "oilseed": "Oilseed",
    "root": "Root crop",
    "vegetable": "Vegetable",
    "fiber": "Fibre crop",
    "forage": "Forage",
    "perennial": "Perennial",
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
        return FAMILY_LABELS_EN.get(self.family, self.family)


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
        role="Main cereal",
        benefit="Leaves straw and residue; covers the soil and brings income.",
    ),
    "barley": _t(
        _CEREAL,
        icon="🌾",
        role="Tough cereal",
        benefit="Tolerates drought and salinity; also sells as animal feed.",
    ),
    "triticale": _t(
        _CEREAL,
        icon="🌾",
        role="Winter cereal",
        benefit="Very winter-hardy; grows even on weaker soils.",
    ),
    "oats": _t(
        _CEREAL,
        icon="🌾",
        role="Feed cereal",
        benefit="Likes cool weather; used in green-manure mixes.",
    ),
    "maize": RotationTraits(
        family="cereal",
        icon="🌽",
        residue_cover=0.8,
        rooting="deep",
        break_crop=0.4,
        role="High-yield cereal",
        benefit="High yield, but needs a lot of water and nitrogen.",
    ),
    "sunflower": _t(
        _OILSEED,
        icon="🌻",
        pollinator=True,
        role="Oilseed cash crop",
        benefit="Deep roots use the soil well; attracts bees and beneficial insects.",
    ),
    "canola": _t(
        _OILSEED,
        icon="🌼",
        pollinator=True,
        break_crop=0.65,
        role="Winter oilseed",
        benefit="Breaks disease cycles; gives bees early flowers.",
    ),
    "safflower": _t(
        _OILSEED,
        icon="🌺",
        break_crop=0.6,
        role="Drought-tolerant oilseed",
        benefit="Produces oil even on a field with little water.",
    ),
    "chickpea": _t(
        _LEGUME,
        icon="🫘",
        role="Soil-building legume",
        benefit="Fixes nitrogen from the air; reduces nitrogen fertiliser need.",
    ),
    "lentil": _t(
        _LEGUME,
        icon="🫘",
        role="Dryland legume",
        benefit="Grows with little water and adds nitrogen to the soil.",
    ),
    "soybean": _t(
        _LEGUME,
        icon="🫘",
        role="Oilseed legume",
        benefit="Fixes nitrogen and is a good cash crop; likes water.",
    ),
    "alfalfa": _t(
        _FORAGE,
        icon="🌿",
        multi_year=True,
        role="Perennial forage",
        benefit="Deep roots feed the soil; can stay in the field for 2-3 years.",
    ),
    "sainfoin": _t(
        _FORAGE,
        icon="🌿",
        multi_year=True,
        role="Dryland forage",
        benefit="Drought-tolerant legume; enriches the soil with nitrogen.",
    ),
    "vetch": _t(
        _FORAGE,
        icon="🌱",
        role="Green manure",
        benefit="Fixes nitrogen; incorporated into the soil at flowering.",
    ),
    "potato": _t(
        _ROOT,
        icon="🥔",
        role="High-value root crop",
        benefit="Aerates the soil; good income but needs water.",
    ),
    "sugar_beet": _t(
        _ROOT,
        icon="🍬",
        role="Contract cash crop",
        benefit="Deep roots open the soil; needs a production contract.",
    ),
    "tomato": RotationTraits(
        family="vegetable",
        icon="🍅",
        residue_cover=0.2,
        rooting="medium",
        break_crop=0.65,
        role="High-value vegetable",
        benefit="Good income; needs a lot of water, fertiliser and labour.",
    ),
    "cotton": RotationTraits(
        family="fiber",
        icon="🧵",
        residue_cover=0.35,
        rooting="deep",
        break_crop=0.55,
        role="Warm-climate cash crop",
        benefit="Needs a long season; not economic without irrigation.",
    ),
    "olive": RotationTraits(
        family="perennial",
        icon="🫒",
        residue_cover=0.6,
        rooting="deep",
        multi_year=True,
        break_crop=0.8,
        role="Perennial orchard",
        benefit="A long-term investment; not part of a yearly rotation.",
    ),
    "grape": RotationTraits(
        family="perennial",
        icon="🍇",
        residue_cover=0.5,
        rooting="deep",
        multi_year=True,
        break_crop=0.8,
        role="Perennial vineyard",
        benefit="A long-term investment; not part of a yearly rotation.",
    ),
    "apple": RotationTraits(
        family="perennial",
        icon="🍎",
        residue_cover=0.55,
        rooting="deep",
        multi_year=True,
        break_crop=0.8,
        role="Perennial fruit orchard",
        benefit="A long-term investment; not part of a yearly rotation.",
    ),
}

DEFAULT_TRAITS = RotationTraits(family="other", icon="🌱", role="Crop", benefit="")


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
