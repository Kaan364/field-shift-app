"""Serialisation helpers for the economics and risk domain reports."""

from __future__ import annotations

from dataclasses import asdict

from app.domain.economics import EconomicsSection as EconomicsReport
from app.domain.frost import RiskSection as RiskReport
from app.schemas import EconomicsSection, RiskSection


def economics_payload(report: EconomicsReport) -> EconomicsSection:
    return EconomicsSection.model_validate(asdict(report))


def risk_payload(report: RiskReport) -> RiskSection:
    return RiskSection.model_validate(asdict(report))
