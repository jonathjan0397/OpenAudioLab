"""Vast.ai offer discovery as a reusable backend service (GPU orchestration M2).

One filter/rank implementation shared by the admin Top-10 endpoint and (for
criteria defaults) the autoscaler. Search uses the Vast REST API so the API
container needs no CLI; lifecycle commands stay with the autoscaler's CLI.

Ranking (documented formula, weights configurable later via fleet settings):
each eligible offer gets 0..1 sub-scores, combined as

    score = 0.30*compatibility + 0.20*readiness + 0.20*cost
          + 0.15*performance + 0.05*network + 0.05*reliability + 0.05*disk

- compatibility: 1 when the offer meets the selected profile's VRAM floor and
  compute-capability minimum, else the offer is filtered out before ranking.
- readiness: 1 - min(1, est_ready_seconds / 900); est_ready = fixed startup
  (150 s) + image pull (IMAGE_GB) + checkpoint bytes for the model, converted
  at the advertised download speed. Weighted toward startup when a large
  checkpoint must be downloaded (checkpoint bytes dominate the estimate).
- cost: 1 - min(1, dph / max_dph).
- performance: min(1, compute_cap / 9.0).
- network: min(1, (inet_down/1000 + inet_up/250) / 2); missing fields score 0.5
  (unknown is neutral, not disqualifying).
- reliability: reliability2. disk: min(1, disk_space / (required_disk*2)).
"""

from __future__ import annotations

from typing import Any, Callable

DEFAULT_WEIGHTS = {
    "compatibility": 0.30,
    "readiness": 0.20,
    "cost": 0.20,
    "performance": 0.15,
    "network": 0.05,
    "reliability": 0.05,
    "disk": 0.05,
}

IMAGE_GB = 13.0
STARTUP_SECONDS = 150.0
REGISTRATION_SECONDS = 45.0
REQUIRED_DISK_GB = 90.0
# Approximate checkpoint footprints (GB) for readiness estimates; documented
# estimates, not provider facts. XL (4B DiT) ~9 GB, 2B families ~5 GB.
CHECKPOINT_GB = {"turbo": 5.0, "sft": 5.0, "xl": 9.0, "merge": 9.0}


def _country(geolocation: str | None) -> str | None:
    if not geolocation or ", " not in geolocation:
        return None
    return geolocation.rsplit(", ", 1)[-1].strip() or None


def normalize(raw: dict) -> dict:
    """Defensive normalization: missing provider fields stay None (never invented)."""

    def num(*keys):
        for k in keys:
            v = raw.get(k)
            if isinstance(v, (int, float)):
                return float(v)
        return None

    gpu_ram = num("gpu_ram", "gpu_ram_mb")
    # Unit detection: the legacy search API reported bytes, the bundles API
    # reports MB (e.g. 24576). Values below 1024 are already GB.
    vram_gb = None
    if gpu_ram is not None:
        if gpu_ram >= 1_000_000_000:
            vram_gb = gpu_ram / 1024**3
        elif gpu_ram >= 1024:
            vram_gb = gpu_ram / 1024
        else:
            vram_gb = gpu_ram
        vram_gb = round(vram_gb, 1)
    cc = num("compute_cap")
    if cc is not None and cc >= 100:  # bundles reports compute capability x100
        cc = cc / 100
    return {
        "offer_id": str(raw.get("id") or raw.get("offer_id") or ""),
        "gpu": raw.get("gpu_name") or raw.get("gpu") or None,
        "vram_gb": vram_gb,
        "cuda": num("cuda_max_good", "cuda_version"),
        "country": _country(raw.get("geolocation") or raw.get("locality")),
        "region": raw.get("geolocation") or raw.get("locality") or None,
        "reliability": num("reliability2", "reliability"),
        "download_mbps": num("inet_down", "download_speed") or None,
        "upload_mbps": num("inet_up", "upload_speed") or None,
        "disk_gb": num("disk_space", "hdd_total_gb"),
        "dph": num("dph_total", "dph"),
        "compute_cap": cc,
        "verified": bool(raw.get("verified")) if raw.get("verified") is not None else None,
        "rentable": raw.get("rentable"),
    }


def criteria_defaults() -> dict:
    return {
        "min_vram_gb": 24,
        "max_dph": 0.25,
        "countries": ["US", "CA"],
        "min_reliability": 0.95,
        "min_compute_cap": 7.5,
        "verified_only": True,
        "min_cuda": 12.8,
        "min_download_mbps": None,
        "min_upload_mbps": None,
        "model_vram_floor_gb": 0,
        "checkpoint_gb": 0.0,
    }


def ineligible_reason(offer: dict, crit: dict) -> str | None:
    """Hard filters first; returns a machine-readable reason or None."""
    if offer["dph"] is None or offer["dph"] <= 0:
        return "NO_PRICE"
    if offer["dph"] > crit["max_dph"]:
        return "PRICE_ABOVE_CEILING"
    if offer["vram_gb"] is None or offer["vram_gb"] < max(crit["min_vram_gb"], crit["model_vram_floor_gb"]):
        return "VRAM_BELOW_MINIMUM"
    if offer["cuda"] is not None and offer["cuda"] < crit["min_cuda"]:
        return "CUDA_UNSUPPORTED"
    if offer["compute_cap"] is not None and offer["compute_cap"] < crit["min_compute_cap"]:
        return "INCOMPATIBLE_GPU"
    if crit["countries"] and offer["country"] not in crit["countries"]:
        return "OUTSIDE_REGION"
    if crit["verified_only"] and offer["verified"] is False:
        return "UNVERIFIED_HOST"  # bundles returns null; the server-side filter enforces it
    if offer["reliability"] is not None and offer["reliability"] < crit["min_reliability"]:
        return "LOW_RELIABILITY"
    if crit["min_download_mbps"] and (offer["download_mbps"] or 0) < crit["min_download_mbps"]:
        return "DOWNLOAD_BELOW_MINIMUM"
    if crit["min_upload_mbps"] and (offer["upload_mbps"] or 0) < crit["min_upload_mbps"]:
        return "UPLOAD_BELOW_MINIMUM"
    if offer["disk_gb"] is not None and offer["disk_gb"] < REQUIRED_DISK_GB:
        return "DISK_INSUFFICIENT"
    return None


def est_ready_seconds(offer: dict, checkpoint_gb: float) -> float | None:
    mbps = offer["download_mbps"]
    if not mbps:
        return None  # not reported -> not estimated
    transfer_gb = IMAGE_GB + checkpoint_gb
    return STARTUP_SECONDS + REGISTRATION_SECONDS + transfer_gb * 8 * 1000 / mbps


def score(offer: dict, crit: dict, weights: dict | None = None) -> float:
    w = weights or DEFAULT_WEIGHTS
    max_dph = crit["max_dph"] or 0.25
    compat = 1.0  # eligible offers passed the profile floor by construction
    ready = est_ready_seconds(offer, crit.get("checkpoint_gb", 0.0))
    readiness = 1.0 - min(1.0, ready / 900.0) if ready is not None else 0.5
    cost = 1.0 - min(1.0, (offer["dph"] or max_dph) / max_dph)
    perf = min(1.0, (offer["compute_cap"] or 0.0) / 9.0)
    if offer["download_mbps"] or offer["upload_mbps"]:
        network = min(1.0, ((offer["download_mbps"] or 0) / 1000.0 + (offer["upload_mbps"] or 0) / 250.0) / 2.0)
    else:
        network = 0.5
    rel = min(1.0, max(0.0, offer["reliability"] or 0.0))
    disk = min(1.0, (offer["disk_gb"] or 0.0) / (REQUIRED_DISK_GB * 2))
    return round(
        w["compatibility"] * compat + w["readiness"] * readiness + w["cost"] * cost
        + w["performance"] * perf + w["network"] * network + w["reliability"] * rel + w["disk"] * disk,
        4,
    )


def rank(raw_offers: list[dict], crit: dict | None = None, weights: dict | None = None,
         limit: int = 10) -> dict:
    """Filter hard-ineligible offers, then rank; returns Top-N + exclusions."""
    merged = {**criteria_defaults(), **(crit or {})}
    eligible: list[dict] = []
    excluded: dict[str, int] = {}
    for raw in raw_offers:
        offer = normalize(raw)
        reason = ineligible_reason(offer, merged)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        offer["est_ready_seconds"] = est_ready_seconds(offer, merged.get("checkpoint_gb", 0.0))
        offer["score"] = score(offer, merged, weights)
        eligible.append(offer)
    eligible.sort(key=lambda o: -o["score"])
    top = eligible[:limit]
    for i, offer in enumerate(top, 1):
        offer["rank"] = i
    return {"offers": top, "eligible_count": len(eligible), "excluded": excluded}


def search_offers(fetch: Callable[[dict], list[dict]], crit: dict | None = None,
                  limit: int = 200) -> list[dict]:
    merged = {**criteria_defaults(), **(crit or {})}
    return fetch(merged)[:limit]
