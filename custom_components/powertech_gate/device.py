"""Shared device metadata helpers for Powertech Gate."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo

from .api import PW200Client
from .const import DOMAIN


def format_mac(raw: str | None) -> str | None:
    """Normalize a MAC address for Home Assistant."""
    if not raw:
        return None
    cleaned = "".join(ch for ch in raw if ch.isalnum()).upper()
    if len(cleaned) != 12:
        return raw.upper()
    return ":".join(cleaned[i:i + 2] for i in range(0, 12, 2))


def build_device_info(client: PW200Client) -> DeviceInfo:
    """Return current device information."""
    connections: set[tuple[str, str]] = set()
    mac = format_mac(client.state.wifi_mac)
    if mac:
        connections.add((CONNECTION_NETWORK_MAC, mac))

    info = DeviceInfo(
        identifiers={(DOMAIN, client.thing_id)},
        connections=connections,
        name=client.display_name,
        manufacturer="Powertech",
        model=client.display_model,
        sw_version=client.state.wbt_version,
        serial_number=client.thing_id,
        configuration_url="https://powertech-automation.com/home/en-US",
    )
    return info
