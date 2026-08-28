"""Cover entities for Powertech PW200."""

from __future__ import annotations

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
)

from .api import PW200Client
from .device import build_device_info
from .const import (
    CONF_PED_SUPPORTED,
    DOMAIN,
    STATE_CLOSED,
    STATE_CLOSING,
    STATE_OPEN,
    STATE_OPENING,
    STATE_PARTIAL_OPEN,
    STATE_PARTIAL_OPENING,
    STATE_STOPPED,
)



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

    entities = [PowertechPW200Cover(client)]
    if entry.data.get(CONF_PED_SUPPORTED, True):
        entities.append(PowertechPW200PedestrianCover(client))

    async_add_entities(
        entities,
        True,
    )


class _PW200BaseCover(CoverEntity):
    _attr_has_entity_name = True
    _attr_device_class = (
        CoverDeviceClass.GATE
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
        """Covers follow the live MQTT connection, just like diagnostics."""
        return self._client.is_connected

    async def async_stop_cover(
        self,
        **kwargs,
    ) -> None:
        await self.hass.async_add_executor_job(
            self._client.stop_gate
        )

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


class PowertechPW200Cover(
    _PW200BaseCover
):
    """Full gate cover."""

    _attr_translation_key = "gate"
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        client: PW200Client,
    ) -> None:
        super().__init__(client)
        self._attr_unique_id = (
            f"{client.thing_id}_gate"
        )

    @property
    def is_closed(
        self,
    ) -> bool | None:
        state = (
            self._client.state.gate_state
        )

        if state == STATE_CLOSED:
            return True

        if state in (
            STATE_OPEN,
            STATE_OPENING,
            STATE_CLOSING,
            STATE_PARTIAL_OPEN,
            STATE_PARTIAL_OPENING,
            STATE_STOPPED,
        ):
            return False

        if (
            self._client.state.position
            is not None
        ):
            return (
                self._client.state.position
                == 0
            )

        return None

    @property
    def is_opening(self) -> bool:
        return (
            self._client.state.gate_state
            in (
                STATE_OPENING,
                STATE_PARTIAL_OPENING,
            )
        )

    @property
    def is_closing(self) -> bool:
        return (
            self._client.state.gate_state
            == STATE_CLOSING
        )

    @property
    def extra_state_attributes(self):
        return {
            "pw200_state": (
                self._client.state.gate_state
            ),
            "last_ack": (
                self._client.state.last_ack
            ),
        }

    async def async_open_cover(
        self,
        **kwargs,
    ) -> None:
        await self.hass.async_add_executor_job(
            self._client.open_gate
        )

    async def async_close_cover(
        self,
        **kwargs,
    ) -> None:
        await self.hass.async_add_executor_job(
            self._client.close_gate
        )


class PowertechPW200PedestrianCover(
    _PW200BaseCover
):
    """Pedestrian / partial gate cover."""

    _attr_translation_key = (
        "pedestrian_gate"
    )
    _attr_icon = "mdi:walk"
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        client: PW200Client,
    ) -> None:
        super().__init__(client)
        self._attr_unique_id = (
            f"{client.thing_id}"
            "_pedestrian_gate"
        )

    @property
    def is_closed(
        self,
    ) -> bool | None:
        """Return pedestrian gate state.

        PS20088D may acknowledge PED OPEN / PED CLOSE without immediately
        publishing a fresh RS/shadow state. Prefer those explicit ACKs before
        falling back to the shared gate state/position.
        """
        last_ack = self._client.state.last_ack or ""

        if last_ack.startswith("ACK PED OPEN"):
            return False

        if (
            last_ack.startswith("ACK PED CLOSE")
            or last_ack.startswith("ACK FULL CLOSE")
        ):
            return True

        state = self._client.state.gate_state

        if state == STATE_CLOSED:
            return True

        if state in (
            STATE_PARTIAL_OPEN,
            STATE_PARTIAL_OPENING,
            STATE_OPEN,
            STATE_OPENING,
            STATE_CLOSING,
            STATE_STOPPED,
        ):
            return False

        if self._client.state.position is not None:
            return self._client.state.position == 0

        return None

    @property
    def is_opening(self) -> bool:
        return (
            self._client.state.gate_state
            == STATE_PARTIAL_OPENING
        )

    @property
    def is_closing(self) -> bool:
        return (
            self._client.state.gate_state
            == STATE_CLOSING
        )

    @property
    def extra_state_attributes(self):
        return {
            "mode": "pedestrian",
            "pw200_state": (
                self._client.state.gate_state
            ),
            "last_ack": (
                self._client.state.last_ack
            ),
        }

    async def async_open_cover(
        self,
        **kwargs,
    ) -> None:
        await self.hass.async_add_executor_job(
            self._client.pedestrian_open
        )

    async def async_close_cover(
        self,
        **kwargs,
    ) -> None:
        await self.hass.async_add_executor_job(
            self._client.pedestrian_close
        )
