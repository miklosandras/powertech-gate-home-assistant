"""Powertech PW200 integration."""

from __future__ import annotations

import logging
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .api import PW200Client
from .device import format_mac
from .const import (
    CONF_CA_PATH,
    CONF_DEVICE_LABEL,
    CONF_DEVICE_TYPE,
    CONF_CERT_PATH,
    CONF_ENDPOINT,
    CONF_KEY_PATH,
    CONF_REFRESH_INTERVAL,
    CONF_SOURCE_ID,
    CONF_THING_ID,
    DEFAULT_SOURCE_ID,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
)

PLATFORMS = [
    Platform.COVER,
    Platform.SENSOR,
]

_LOGGER = logging.getLogger(__name__)


def _create_client(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> PW200Client:
    """Create Paho/TLS client outside HA's event loop."""
    return PW200Client(
        endpoint=entry.data[CONF_ENDPOINT],
        thing_id=entry.data[CONF_THING_ID],
        source_id=entry.data.get(
            CONF_SOURCE_ID,
            DEFAULT_SOURCE_ID,
        ),
        cert_path=entry.data[CONF_CERT_PATH],
        key_path=entry.data[CONF_KEY_PATH],
        ca_path=(
            entry.data.get(CONF_CA_PATH)
            or None
        ),
        event_loop=hass.loop,
        device_label=entry.data.get(CONF_DEVICE_LABEL) or entry.title,
        device_type=entry.data.get(CONF_DEVICE_TYPE),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up Powertech PW200."""
    client = await hass.async_add_executor_job(
        _create_client,
        hass,
        entry,
    )

    await hass.async_add_executor_job(
        client.start
    )

    hass.data.setdefault(
        DOMAIN,
        {},
    )[entry.entry_id] = client

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    @callback
    def _sync_device_registry() -> None:
        """Push runtime metadata learned from the AWS shadow to HA.

        This deliberately supports both the current config-entry-scoped
        device lookup API and older Home Assistant releases.
        Metadata refresh must never make the integration setup fail.
        """
        try:
            registry = dr.async_get(hass)

            get_by_identifier = getattr(
                registry,
                "async_get_device_by_identifier",
                None,
            )
            if get_by_identifier is not None:
                device = get_by_identifier(
                    (DOMAIN, client.thing_id),
                    entry.entry_id,
                )
            else:
                # Backward-compatible API. Deprecated in newer HA, but still
                # supported during the transition period.
                device = registry.async_get_device(
                    identifiers={(DOMAIN, client.thing_id)}
                )

            if device is None:
                return

            changes = {
                "manufacturer": "Powertech",
                "model": client.display_model,
                "sw_version": client.state.wbt_version,
                "serial_number": client.thing_id,
                "configuration_url": (
                    "https://powertech-automation.com/home/en-US"
                ),
            }

            mac = format_mac(client.state.wifi_mac)
            if mac:
                wanted_connection = (
                    dr.CONNECTION_NETWORK_MAC,
                    mac.lower(),
                )
                current_connections = set(device.connections)
                if wanted_connection not in current_connections:
                    current_connections.add(wanted_connection)
                    changes["new_connections"] = current_connections

            registry.async_update_device(
                device.id,
                **changes,
            )

        except Exception:
            # Device metadata is useful, but it is not allowed to break the
            # actual gate integration. Keep setup operational and log details.
            _LOGGER.exception(
                "Could not refresh Powertech device registry metadata"
            )

    remove_registry_listener = client.add_listener(_sync_device_registry)
    hass.data[DOMAIN][entry.entry_id + "_remove_registry_listener"] = (
        remove_registry_listener
    )
    _sync_device_registry()

    async def _periodic_shadow_refresh() -> None:
        """Refresh the shadow periodically so idle-state metadata stays current."""
        interval = int(
            entry.options.get(
                CONF_REFRESH_INTERVAL,
                DEFAULT_REFRESH_INTERVAL,
            )
        )
        while True:
            await asyncio.sleep(max(15, interval))
            if client.is_connected:
                await hass.async_add_executor_job(client.request_shadow)

    refresh_task = hass.async_create_task(
        _periodic_shadow_refresh(),
        f"{DOMAIN}_{entry.entry_id}_shadow_refresh",
    )
    hass.data[DOMAIN][entry.entry_id + "_refresh_task"] = refresh_task

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload Powertech PW200."""
    unload_ok = (
        await hass.config_entries.async_unload_platforms(
            entry,
            PLATFORMS,
        )
    )

    if unload_ok:
        refresh_task = hass.data[DOMAIN].pop(
            entry.entry_id + "_refresh_task",
            None,
        )
        if refresh_task:
            refresh_task.cancel()

        remove_listener = hass.data[DOMAIN].pop(
            entry.entry_id + "_remove_registry_listener",
            None,
        )
        if remove_listener:
            remove_listener()

        client = hass.data[DOMAIN].pop(
            entry.entry_id
        )
        await hass.async_add_executor_job(
            client.stop
        )

    return unload_ok
