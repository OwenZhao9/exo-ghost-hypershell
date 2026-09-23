"""Read-only discovery of public EvoMap assets.

Only curated, device-generic event names leave this machine. The Hub's payload,
summary and executable strategy are intentionally not copied into Ghost's local
memory or fed to its control policy. Search results are references for a human.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

HUB_URL = "https://evomap.ai"
ASSET_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")

# These fixed queries contain no sensor samples, serial numbers or personal notes.
EVENT_SEARCHES = {
    "legs_offline": "robot exoskeleton leg controller offline recovery",
    "legs_online": "robot controller reconnection startup safety",
    "reconnected": "robot serial usb reconnection recovery",
    "stall": "robot serial telemetry stream stalled usb",
    "stream_slow": "robot telemetry stream slow device restart",
    "trip": "robot exoskeleton emergency stop safety recovery",
    "stalled": "robot actuator stall overcurrent torque limit",
    "port_lost": "robot usb serial port disappeared recovery",
}


def search_event(event: str, *, limit: int = 3, timeout_s: float = 7.0) -> list[dict]:
    """Return public *metadata* for a known event; never fetch asset payloads.

    Raises on transport or malformed JSON so the caller can report degraded
    availability without confusing a network failure with zero matches.
    """
    event = event.split(":", 1)[0]
    query = EVENT_SEARCHES.get(event)
    if query is None:
        return []
    params = urlencode({
        "q": query, "status": "promoted", "limit": max(1, min(limit, 5)),
        "fields": "asset_id,short_title,asset_type,status,trust_tier,validation_status",
    })
    request = Request(f"{HUB_URL}/a2a/assets/search?{params}",
                      headers={"Accept": "application/json", "User-Agent": "exo-ghost/evomap-readonly"})
    with urlopen(request, timeout=timeout_s) as response:
        data = json.load(response)
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise ValueError("EvoMap returned an invalid search response")

    references = []
    for asset in data["assets"]:
        if not isinstance(asset, dict) or asset.get("status") != "promoted":
            continue
        asset_id = asset.get("asset_id")
        if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id):
            continue
        title = asset.get("short_title") or asset.get("title") or asset_id
        title = " ".join(str(title).split())[:120]
        references.append({
            "id": asset_id,
            "title": title,
            "url": f"{HUB_URL}/a2a/assets/{quote(asset_id, safe=':')}",
            "type": str(asset.get("asset_type") or "unknown")[:24],
            "trust_tier": str(asset.get("trust_tier") or "unknown")[:24],
            "validation_status": str(asset.get("validation_status") or "unknown")[:40],
        })
        if len(references) >= limit:
            break
    return references
