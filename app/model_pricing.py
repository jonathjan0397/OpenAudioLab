"""Admin-controlled model pricing: availability, credit multiplier, base cost.

One persisted source (SiteSetting key ``model_pricing``), validated centrally.
The static catalog stays the system-of-record for what a profile *is*; this
module only stores admin overrides for what it *costs* and whether it is
offered. A profile the provider never configured (``unconfigured``) can never
be enabled from here — that is a provisioning fact, not a product switch.
"""

from __future__ import annotations

import json

from .models import SiteSetting

SETTINGS_KEY = "model_pricing"
AVAILABILITY = ("available", "disabled")
MULT_RANGE = (0.1, 10.0)


class ModelPricingError(ValueError):
    pass


def _clean(payload: dict) -> dict:
    base = payload.get("base_credit_cost")
    if base is not None:
        try:
            base = int(base)
        except (TypeError, ValueError):
            raise ModelPricingError("base_credit_cost must be an integer") from None
        if not 1 <= base <= 1000:
            raise ModelPricingError("base_credit_cost must be 1-1000")
    profiles: dict[str, dict] = {}
    raw = payload.get("profiles") or {}
    if not isinstance(raw, dict):
        raise ModelPricingError("profiles must be an object")
    for pid, entry in raw.items():
        if not isinstance(entry, dict):
            raise ModelPricingError(f"profile {pid}: expected an object")
        out: dict = {}
        if entry.get("availability") is not None:
            if entry["availability"] not in AVAILABILITY:
                raise ModelPricingError(f"profile {pid}: availability must be available|disabled")
            out["availability"] = entry["availability"]
        if entry.get("multiplier") is not None:
            try:
                mult = float(entry["multiplier"])
            except (TypeError, ValueError):
                raise ModelPricingError(f"profile {pid}: multiplier must be a number") from None
            if not MULT_RANGE[0] <= mult <= MULT_RANGE[1]:
                raise ModelPricingError(f"profile {pid}: multiplier must be {MULT_RANGE[0]}-{MULT_RANGE[1]}")
            out["multiplier"] = mult
        if entry.get("display_name") is not None:
            name = str(entry["display_name"]).strip()
            if not 1 <= len(name) <= 120:
                raise ModelPricingError(f"profile {pid}: display_name must be 1-120 characters")
            out["display_name"] = name
        profiles[str(pid)] = out
    return {"base_credit_cost": base, "profiles": profiles}


def load(session) -> dict:
    row = session.get(SiteSetting, SETTINGS_KEY)
    if row is None or not row.value:
        return {"base_credit_cost": None, "profiles": {}}
    try:
        return _clean(json.loads(row.value))
    except (ValueError, TypeError):
        return {"base_credit_cost": None, "profiles": {}}


def save(session, payload: dict) -> dict:
    merged = _clean(payload)
    blob = json.dumps(merged, separators=(",", ":"))
    if len(blob) > 480:
        raise ModelPricingError("too many profile overrides")
    row = session.get(SiteSetting, SETTINGS_KEY)
    if row is None:
        row = SiteSetting(key=SETTINGS_KEY, value=blob)
        session.add(row)
    else:
        row.value = blob
    session.commit()
    return merged


def effective_availability(profile, mp: dict) -> str:
    """Admin override, except unconfigured (a provisioning fact) always wins."""
    if profile.availability == "unconfigured":
        return "unconfigured"
    entry = (mp.get("profiles") or {}).get(profile.profile_id) or {}
    return entry.get("availability", profile.availability)


def effective_display_name(profile, mp: dict, fallback: str) -> str:
    """Admin-set website display name; catalog label/release name as fallback."""
    entry = (mp.get("profiles") or {}).get(profile.profile_id) or {}
    return entry.get("display_name") or fallback


def effective_multiplier(profile, mp: dict) -> float:
    entry = (mp.get("profiles") or {}).get(profile.profile_id) or {}
    return float(entry.get("multiplier", profile.multiplier))


def base_credit_cost(mp: dict, settings) -> int:
    value = mp.get("base_credit_cost")
    return int(value) if value else int(settings.credit_cost_per_generation)
