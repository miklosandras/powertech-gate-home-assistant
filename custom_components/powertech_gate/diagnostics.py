"""Diagnostics for Powertech Gate."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import PW200Client
from .const import DOMAIN

TO_REDACT = {
    "cert_path",
    "key_path",
    "ca_path",
    "endpoint",
    "source_id",
    "thing_id",
    "username",
    "password",
    "access_token",
    "refresh_token",
    "pin",
    "private_key",
    "certificate",
}

DEVICE_TO_REDACT = {
    "thing_id",
    "ip_address",
    "wifi_mac",
    "raw_status",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict:
    """Return privacy-conscious diagnostics for a config entry."""
    client: PW200Client = hass.data[DOMAIN][entry.entry_id]
    state = client.state

    config_entry = async_redact_data(dict(entry.data), TO_REDACT)

    device = async_redact_data(
        {
            "name": client.display_name,
            "model": client.display_model,
            "pedestrian_supported": entry.data.get("pedestrian_supported"),
            "experimental_model": entry.data.get("experimental_model"),
            "protocol_validated": entry.data.get("protocol_validated"),
            "pin_verified": entry.data.get("pin_verified"),
            "thing_id": client.thing_id,
            "firmware": state.wbt_version,
            "uart_version": state.uart_version,
            "device_info": state.device_info,
            "online": state.online,
            "ip_address": state.ip_address,
            "wifi_mac": state.wifi_mac,
            "position": state.position,
            "raw_status": state.raw_status,
            "mqtt_connected": client.is_connected,
            "last_disconnect_reason": client.last_disconnect_reason,
        },
        DEVICE_TO_REDACT,
    )

    return {
        "config_entry": config_entry,
        "device": device,
    }
