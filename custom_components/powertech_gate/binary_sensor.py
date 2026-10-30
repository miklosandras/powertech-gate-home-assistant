"""Whole-gateway opening state, independent of cover access mode."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import PW200Client
from .const import DOMAIN
from .device import build_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: PW200Client = hass.data[DOMAIN][entry.entry_id]
    added = False

    @callback
    def discover() -> None:
        """UART metadata may arrive after platform setup."""
        nonlocal added
        if not added and client.uses_access_mode_feedback:
            added = True
            async_add_entities([PowertechGateStateSensor(client)])

    entry.async_on_unload(client.add_listener(discover))
    discover()


class PowertechGateStateSensor(BinarySensorEntity):
    """Open when not closed, including motion; unavailable without fresh feedback."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "gate_state"
    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_icon = "mdi:gate"

    def __init__(self, client: PW200Client) -> None:
        self._client = client
        self._attr_unique_id = f"{client.thing_id}_physical_gate_closed"

    @property
    def device_info(self) -> DeviceInfo:
        return build_device_info(self._client)

    @property
    def available(self) -> bool:
        return (self._client.uses_access_mode_feedback
                and self._client.is_connected
                and self._client.live_feedback_available)

    @property
    def is_on(self) -> bool | None:
        closed = self._client.physical_gate_closed if self.available else None
        return None if closed is None else not closed

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._client.add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
