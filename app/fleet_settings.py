"""GPU fleet settings: one persisted source (SiteSetting), validated centrally.

Shared by the admin API (GET/PATCH /admin/gpu-fleet/settings) and the
autoscaler (swappiness decisions). Environment variables provide bootstrap
defaults only; the stored JSON wins.
"""

from __future__ import annotations

SETTINGS_KEY = "gpu_fleet_settings"

FLEET_DEFAULTS: dict = {
    "auto_burst_enabled": True,
    "swappiness": 50,
    "max_auto_burst_workers": 1,
    "max_dph": 0.25,
    "min_vram_gb": 24,
    "min_cuda": 12.8,
    "countries": ["US", "CA"],
    "min_reliability": 0.95,
    "preferred_download_mbps": 1000,
    "preferred_upload_mbps": 250,
    "idle_grace_seconds": 300,
    "min_worker_uptime_seconds": 180,
    "daily_burst_budget_usd": 3.0,
    "monthly_burst_budget_usd": 60.0,
}

_ALLOWED_COUNTRIES = {"US", "CA"}


class FleetSettingsError(ValueError):
    pass


def validate(payload: dict) -> dict:
    """Validate a PATCH body; returns the merged full settings dict."""
    merged = dict(FLEET_DEFAULTS)
    for key, value in payload.items():
        if key not in FLEET_DEFAULTS:
            raise FleetSettingsError(f"unknown setting: {key}")
        merged[key] = value
    try:
        sw = int(merged["swappiness"])
    except (TypeError, ValueError):
        raise FleetSettingsError("swappiness must be an integer") from None
    if not 0 <= sw <= 100:
        raise FleetSettingsError("swappiness must be 0-100")
    merged["swappiness"] = sw
    mw = int(merged["max_auto_burst_workers"])
    if not 0 <= mw <= 3:
        raise FleetSettingsError("max_auto_burst_workers must be 0-3")
    merged["max_auto_burst_workers"] = mw
    dph = float(merged["max_dph"])
    if not 0.05 <= dph <= 1.0:
        raise FleetSettingsError("max_dph must be $0.05-$1.00")
    merged["max_dph"] = dph
    vram = int(merged["min_vram_gb"])
    if not 8 <= vram <= 80:
        raise FleetSettingsError("min_vram_gb must be 8-80")
    merged["min_vram_gb"] = vram
    rel = float(merged["min_reliability"])
    if not 0.5 <= rel <= 1.0:
        raise FleetSettingsError("min_reliability must be 0.5-1.0")
    merged["min_reliability"] = rel
    countries = list(merged["countries"])
    if not countries or any(c not in _ALLOWED_COUNTRIES for c in countries):
        raise FleetSettingsError("countries must be a non-empty subset of US/CA")
    merged["countries"] = countries
    merged["auto_burst_enabled"] = bool(merged["auto_burst_enabled"])
    for key in ("daily_burst_budget_usd", "monthly_burst_budget_usd"):
        v = float(merged[key])
        if v < 0 or v > 1000:
            raise FleetSettingsError(f"{key} must be 0-1000")
        merged[key] = v
    for key in ("idle_grace_seconds", "min_worker_uptime_seconds"):
        v = int(merged[key])
        if not 0 <= v <= 3600:
            raise FleetSettingsError(f"{key} must be 0-3600")
        merged[key] = v
    for key in ("preferred_download_mbps", "preferred_upload_mbps"):
        merged[key] = int(merged[key])
    merged["min_cuda"] = float(merged["min_cuda"])
    return merged
