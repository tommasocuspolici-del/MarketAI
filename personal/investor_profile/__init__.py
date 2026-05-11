"""Investor profile sub-package — Rule 22 enforcement."""
from __future__ import annotations

from personal.investor_profile.profile_loader import (
    ProfileLoader,
    get_profile_loader,
    reset_profile_loader,
)
from personal.investor_profile.profile_model import (
    InvestmentHorizon,
    InvestorProfile,
    RiskTolerance,
)
from personal.investor_profile.risk_profile_bridge import (
    DEFAULT_PROFILE_ID,
    DEFAULT_PROFILE_NAME,
    questionnaire_to_investor_profile,
    safe_load_investor_profile,
    save_questionnaire_to_investor_profile,
)
from personal.investor_profile.suitability_checker import (
    SuitabilityChecker,
    SuitabilityResult,
)

__version__ = "7.1.2"

__all__ = [
    "DEFAULT_PROFILE_ID",
    "DEFAULT_PROFILE_NAME",
    "InvestmentHorizon",
    "InvestorProfile",
    "ProfileLoader",
    "RiskTolerance",
    "SuitabilityChecker",
    "SuitabilityResult",
    "get_profile_loader",
    "questionnaire_to_investor_profile",
    "reset_profile_loader",
    "safe_load_investor_profile",
    "save_questionnaire_to_investor_profile",
]
