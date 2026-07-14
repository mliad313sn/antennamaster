"""Subscription tiers and feature entitlements.

Enforcement model: when the request carries a bearer token, the user's tier
is enforced. Anonymous requests follow the deployment mode:

* open mode (default, ``AM_SAAS_MODE`` unset/0) — self-hosted installs keep
  every capability without accounts; tiers only apply to logged-in users'
  saved-project quotas.
* SaaS mode (``AM_SAAS_MODE=1``) — anonymous requests are treated as
  ``basic``, so gated features require login + entitlement.
"""
from __future__ import annotations

import os

from fastapi import HTTPException

TIER_ORDER = {"basic": 0, "pro": 1, "enterprise": 2}

# feature key -> minimum tier
FEATURES: dict[str, str] = {
    "srtm_terrain": "basic",
    "wifi_presets": "basic",
    "dxf_fusion": "pro",           # DXF terrain fusion / georeferencing
    "ptp_backhaul": "pro",         # PtP/PtMP presets + rain/gas nuances
    "pdf_export": "pro",
    "indoor_studio": "pro",
    "private_networks": "enterprise",  # private LTE/5G presets
    "multi_site": "enterprise",
    "api_access": "enterprise",    # long-lived API tokens
    "white_label": "enterprise",
}

# Preset key -> gating feature (presets not listed are basic).
PRESET_FEATURES: dict[str, str] = {
    "ptp18000": "ptp_backhaul",
    "private_lte_b48": "private_networks",
    "private_nr_n77": "private_networks",
    "private_lte_iot": "private_networks",
}

# Saved-project quota per tier (None = unlimited).
PROJECT_QUOTA: dict[str, int | None] = {"basic": 3, "pro": 25, "enterprise": None}

TIER_INFO = [
    {"key": "basic", "label": "Basic", "price_month_usd": 0,
     "highlights": ["Global SRTM terrain", "Wi-Fi / PMR / broadcast presets",
                    "3 saved projects"]},
    {"key": "pro", "label": "Pro", "price_month_usd": 79,
     "highlights": ["DXF terrain fusion", "PtP/PtMP backhaul with rain & gas",
                    "Indoor/underground studio", "Branded PDF reports",
                    "25 saved projects"]},
    {"key": "enterprise", "label": "Enterprise", "price_month_usd": 299,
     "highlights": ["Private LTE/5G models", "Multi-site best-server",
                    "API access", "White-label reports",
                    "Unlimited projects & sites"]},
]


def saas_mode() -> bool:
    return os.environ.get("AM_SAAS_MODE", "0") == "1"


def tier_of(user: dict | None) -> str | None:
    """Effective tier: user's tier, 'basic' for anonymous in SaaS mode,
    None (= unrestricted) for anonymous in open mode."""
    if user is not None:
        return user["tier"]
    return "basic" if saas_mode() else None


def has_feature(user: dict | None, feature: str) -> bool:
    tier = tier_of(user)
    if tier is None:
        return True
    need = FEATURES.get(feature, "basic")
    return TIER_ORDER[tier] >= TIER_ORDER[need]


def require_feature(user: dict | None, feature: str) -> None:
    if not has_feature(user, feature):
        need = FEATURES.get(feature, "basic")
        raise HTTPException(
            402,
            f"The '{feature}' capability requires the {need} plan "
            f"(current: {tier_of(user) or 'anonymous'}). Upgrade to continue.")


def check_preset_allowed(user: dict | None, preset_key: str) -> None:
    feature = PRESET_FEATURES.get(preset_key)
    if feature:
        require_feature(user, feature)
