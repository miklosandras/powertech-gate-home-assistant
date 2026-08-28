"""Diagnostic sensors for Powertech PW200."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.config_entries import (
    ConfigEntry,
)
from homeassistant.const import (
    EntityCategory,
)
from homeassistant.core import (
    HomeAssistant,
    callback,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
)

from .api import PW200Client
from .device import build_device_info, format_mac
from .const import DOMAIN



async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: PW200Client = (
        hass.data[
            DOMAIN
        ][entry.entry_id]
    )

    async_add_entities(
        [
            PowertechPW200IPAddressSensor(
                client
            ),
            PowertechPW200MacAddressSensor(
                client
            ),
        ],
        True,
    )


class _PW200DiagnosticSensor(
    SensorEntity
):
    _attr_has_entity_name = True
    _attr_entity_category = (
        EntityCategory.DIAGNOSTIC
    )
    _attr_should_poll = False

    def __init__(
        self,
        client: PW200Client,
    ) -> None:
        self._client = client

    @property
    def device_info(self) -> DeviceInfo:
        return build_device_info(self._client)

    @property
    def available(self) -> bool:
        """Diagnostic sensors follow the live MQTT connection."""
        return self._client.is_connected

    async def async_added_to_hass(
        self,
    ) -> None:
        await super().async_added_to_hass()

        self.async_on_remove(
            self._client.add_listener(
                self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class PowertechPW200IPAddressSensor(
    _PW200DiagnosticSensor
):
    _attr_translation_key = "ip_address"
    _attr_icon = "mdi:ip-network"

    def __init__(
        self,
        client: PW200Client,
    ) -> None:
        super().__init__(client)
        self._attr_unique_id = (
            f"{client.thing_id}"
            "_ip_address"
        )

    @property
    def native_value(
        self,
    ) -> str | None:
        return (
            self._client.state.ip_address
        )


class PowertechPW200MacAddressSensor(
    _PW200DiagnosticSensor
):
    _attr_translation_key = "wifi_mac"
    _attr_icon = "mdi:network-outline"

    def __init__(
        self,
        client: PW200Client,
    ) -> None:
        super().__init__(client)
        self._attr_unique_id = (
            f"{client.thing_id}_wifi_mac"
        )

    @property
    def native_value(
        self,
    ) -> str | None:
        return format_mac(
            self._client.state.wifi_mac
        )
