"""AWS IoT client used by the Powertech PW200 integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import json
import logging
from pathlib import Path
import ssl
import threading
import time
import uuid

import paho.mqtt.client as mqtt

from .const import (
    DEFAULT_PORT,
    STATE_CLOSED,
    STATE_CLOSING,
    STATE_FACTORY,
    STATE_OPEN,
    STATE_OPENING,
    STATE_PARTIAL_OPEN,
    STATE_PARTIAL_OPENING,
    STATE_STOPPED,
    STATE_UNKNOWN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PW200State:
    """Current PW200 state."""

    gate_state: str = STATE_UNKNOWN
    position: int | None = None
    online: bool | None = None
    ip_address: str | None = None
    wifi_mac: str | None = None
    wbt_version: str | None = None
    uart_version: int | None = None
    device_info: str | None = None
    raw_status: str | None = None
    last_ack: str | None = None


class PW200Client:
    """Powertech/EyeOpen AWS IoT client."""

    def __init__(
        self,
        *,
        endpoint: str,
        thing_id: str,
        source_id: str,
        cert_path: str,
        key_path: str,
        ca_path: str | None,
        event_loop,
        device_label: str | None = None,
        device_type: str | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.thing_id = thing_id
        self.source_id = source_id
        self.cert_path = cert_path
        self.key_path = key_path
        self.ca_path = ca_path or None
        self._event_loop = event_loop
        self.device_label = device_label or "Powertech Gate"
        self.device_type = device_type

        self.state = PW200State()
        self._listeners: set[Callable[[], None]] = set()
        self._connected = threading.Event()
        self._last_disconnect_reason: str | None = None
        # Transient only; never persisted or logged.
        self._decoded_pin: str | None = None

        self._topic_shadow_get = (
            f"$aws/things/{thing_id}/shadow/get"
        )
        self._topic_shadow_ok = (
            f"$aws/things/{thing_id}/shadow/get/accepted"
        )
        self._topic_shadow_err = (
            f"$aws/things/{thing_id}/shadow/get/rejected"
        )
        self._topic_shadow_update = (
            f"$aws/things/{thing_id}/shadow/update/accepted"
        )
        self._topic_position = f"{thing_id}/position"
        self._topic_cmd_rx = f"{thing_id}/wbt01Rx"
        self._topic_cmd_tx = f"{thing_id}/wbt01Tx"

        self._mqtt = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"ha-pw200-{uuid.uuid4()}",
            protocol=mqtt.MQTTv311,
        )
        self._mqtt.on_connect = self._on_connect
        self._mqtt.on_disconnect = self._on_disconnect
        self._mqtt.on_message = self._on_message
        self._mqtt.reconnect_delay_set(min_delay=1, max_delay=60)

        self._mqtt.tls_set(
            ca_certs=self.ca_path,
            certfile=self.cert_path,
            keyfile=self.key_path,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )

    @property
    def decoded_pin(self) -> str | None:
        """Return the transient gate PIN decoded from the current shadow."""
        return self._decoded_pin

    @staticmethod
    def decode_wbt_pin(value: object) -> str | None:
        """Decode EyeOpen's reversible WBT PIN representation."""
        if not isinstance(value, str) or not value:
            return None
        try:
            parts = value.split(",")
            if len(parts) != 6:
                return None
            decoded = bytearray()
            for index, part in enumerate(parts):
                raw = int(part, 16) & 0xFF
                transformed = (~raw) & 0xFF
                transformed = ((transformed + 1) if index % 2 == 0 else (transformed - 1)) & 0xFF
                decoded.append(transformed)
            result = decoded.decode("ascii")
        except (ValueError, UnicodeDecodeError):
            return None
        return result if len(result) == 6 and result.isdigit() else None

    @property
    def is_connected(self) -> bool:
        """Return whether MQTT is currently connected."""
        return self._connected.is_set()

    @property
    def last_disconnect_reason(self) -> str | None:
        """Return the last MQTT disconnect reason."""
        return self._last_disconnect_reason

    @property
    def display_model(self) -> str:
        """Best available model/product identifier."""
        info = self.state.device_info
        if info:
            parts = [part.strip() for part in info.split(",")]
            if len(parts) >= 2 and parts[1]:
                return parts[1]
            if parts and parts[0]:
                return parts[0]
        if self.device_type:
            return self.device_type
        return "WBT01"

    @property
    def display_name(self) -> str:
        """Human-readable Home Assistant device name."""
        label = (self.device_label or "").strip()
        if label and not label.lower().startswith("powertech iot device"):
            return label
        model = self.display_model
        return f"Powertech {model}" if model else "Powertech Gate"

    @staticmethod
    def validate_files(
        cert_path: str,
        key_path: str,
        ca_path: str | None,
    ) -> None:
        """Validate certificate files without connecting."""
        for item in (cert_path, key_path):
            if not Path(item).is_file():
                raise FileNotFoundError(item)

        if ca_path and not Path(ca_path).is_file():
            raise FileNotFoundError(ca_path)

        context = (
            ssl.create_default_context(cafile=ca_path)
            if ca_path
            else ssl.create_default_context()
        )
        context.load_cert_chain(
            certfile=cert_path,
            keyfile=key_path,
        )

    def start(self) -> None:
        """Connect and start the Paho network thread."""
        _LOGGER.info(
            "Connecting Powertech Gate MQTT client"
        )
        self._mqtt.connect(
            self.endpoint,
            DEFAULT_PORT,
            keepalive=60,
        )
        self._mqtt.loop_start()

    def stop(self) -> None:
        """Disconnect MQTT."""
        try:
            self._mqtt.disconnect()
        finally:
            self._mqtt.loop_stop()

    def request_shadow(self) -> None:
        """Request the current AWS IoT shadow."""
        self._mqtt.publish(
            self._topic_shadow_get,
            "{}",
            qos=0,
        )

    def wait_for_shadow_capabilities(
        self,
        timeout: float = 12.0,
    ) -> tuple[bool, dict[str, bool]]:
        """Passively validate the Powertech AWS/WBT shadow schema.

        This sends only the AWS shadow GET request. It never sends a gate
        movement command.
        """
        deadline = time.monotonic() + timeout
        requested = False

        while time.monotonic() < deadline:
            if self.is_connected and not requested:
                self.request_shadow()
                requested = True

            state = self.state
            has_dev_info = bool(state.device_info)
            has_dev_status = bool(state.raw_status)
            if has_dev_info and has_dev_status:
                return True, {
                    "dev_info": True,
                    "dev_status": True,
                    "wbt_version": bool(state.wbt_version),
                    "uart_version": state.uart_version is not None,
                    "pin_verification": self._decoded_pin is not None,
                }

            time.sleep(0.1)

        state = self.state
        return False, {
            "dev_info": bool(state.device_info),
            "dev_status": bool(state.raw_status),
            "wbt_version": bool(state.wbt_version),
            "uart_version": state.uart_version is not None,
            "pin_verification": self._decoded_pin is not None,
        }

    def open_gate(self) -> None:
        self._publish_command("FULL OPEN")

    def close_gate(self) -> None:
        self._publish_command("FULL CLOSE")

    def stop_gate(self) -> None:
        self._publish_command("STOP")

    def pedestrian_open(self) -> None:
        self._publish_command("PED OPEN")

    def pedestrian_close(self) -> None:
        self._publish_command("PED CLOSE")

    def _publish_command(self, command: str) -> None:
        if not self._connected.is_set():
            raise RuntimeError(
                "Powertech MQTT client is not connected"
            )

        payload = (
            f"c={command};src={self.source_id}"
        )
        _LOGGER.info(
            "Powertech TX: %s",
            command,
        )

        info = self._mqtt.publish(
            self._topic_cmd_rx,
            payload=payload,
            qos=0,
        )

        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(
                f"Powertech publish failed, rc={info.rc}"
            )

        info.wait_for_publish(timeout=5)

    def add_listener(
        self,
        listener: Callable[[], None],
    ) -> Callable[[], None]:
        """Register a state listener."""
        self._listeners.add(listener)

        def remove() -> None:
            self._listeners.discard(listener)

        return remove

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            self._event_loop.call_soon_threadsafe(
                listener
            )

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties=None,
    ) -> None:
        _LOGGER.info(
            "Powertech MQTT connect result: %s",
            reason_code,
        )

        if reason_code.is_failure:
            return

        self._connected.set()
        self._last_disconnect_reason = None
        self._notify()

        client.subscribe(
            self._topic_shadow_ok,
            qos=0,
        )
        client.subscribe(
            self._topic_shadow_err,
            qos=0,
        )
        client.subscribe(
            self._topic_shadow_update,
            qos=0,
        )
        client.subscribe(
            self._topic_position,
            qos=0,
        )
        client.subscribe(
            self._topic_cmd_tx,
            qos=0,
        )

        self.request_shadow()

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties=None,
    ) -> None:
        _LOGGER.info(
            "Powertech MQTT disconnected: %s",
            reason_code,
        )
        self._connected.clear()
        self._last_disconnect_reason = str(reason_code)
        self.state = replace(self.state, online=False)
        self._notify()

    def _on_message(
        self,
        client,
        userdata,
        msg,
    ) -> None:
        payload = msg.payload.decode(
            "utf-8",
            errors="replace",
        )

        if msg.topic == self._topic_cmd_tx:
            _LOGGER.info(
                "Powertech RX: %s",
                payload,
            )
            self.state = replace(
                self.state,
                last_ack=payload,
            )
            self._notify()
            return

        if msg.topic == self._topic_position:
            try:
                position = max(
                    0,
                    min(
                        100,
                        int(
                            payload.strip().replace(
                                "%",
                                "",
                            )
                        ),
                    ),
                )
            except ValueError:
                _LOGGER.warning(
                    "Invalid Powertech position payload"
                )
                return

            self.state = replace(
                self.state,
                position=position,
            )
            self._notify()
            return

        if msg.topic == self._topic_shadow_err:
            _LOGGER.warning(
                "Powertech shadow request rejected"
            )
            return

        if msg.topic not in (
            self._topic_shadow_ok,
            self._topic_shadow_update,
        ):
            return

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            _LOGGER.warning(
                "Invalid Powertech shadow JSON"
            )
            return

        reported = (
            data.get("state", {})
            .get("reported", {})
        )

        if not isinstance(reported, dict):
            return

        raw_status = reported.get("DEV STATUS")
        decoded_pin = self.decode_wbt_pin(reported.get("WBT PIN"))
        if decoded_pin is not None:
            self._decoded_pin = decoded_pin

        gate_state = self.state.gate_state
        position = self.state.position

        if isinstance(raw_status, str):
            gate_state = self.decode_gate_state(
                raw_status
            )

            # Position topic is event based, so force
            # known physical end positions.
            if gate_state == STATE_CLOSED:
                position = 0
            elif gate_state == STATE_OPEN:
                position = 100

        self.state = PW200State(
            gate_state=gate_state,
            position=position,
            online=reported.get(
                "Connected",
                self.state.online,
            ),
            ip_address=reported.get(
                "IP",
                self.state.ip_address,
            ),
            wifi_mac=reported.get(
                "WiFi MAC",
                self.state.wifi_mac,
            ),
            wbt_version=reported.get(
                "WBT VER",
                self.state.wbt_version,
            ),
            uart_version=reported.get(
                "UART VER",
                self.state.uart_version,
            ),
            device_info=reported.get(
                "DEV INFO",
                self.state.device_info,
            ),
            raw_status=(
                raw_status
                if isinstance(raw_status, str)
                else self.state.raw_status
            ),
            last_ack=self.state.last_ack,
        )

        self._notify()

    @staticmethod
    def decode_gate_state(
        status_string: str,
    ) -> str:
        """Decode DEV STATUS using EyeOpen's status logic."""
        try:
            values = [
                int(part, 16)
                for part in status_string.split(",")
            ]
        except ValueError:
            return STATE_UNKNOWN

        if len(values) < 4:
            return STATE_UNKNOWN

        b0 = values[0]
        b2 = values[2]
        b3 = values[3]

        factory_default = bool(b0 & 0x80)
        is_operation = bool(b2 & 0x40)
        is_stopped = bool(b2 & 0x20)
        is_pedestrian = bool(b2 & 0x10)
        is_open = bool(b3 & 0x80)

        if factory_default:
            return STATE_FACTORY

        if is_stopped and is_pedestrian:
            return STATE_PARTIAL_OPEN

        if not is_operation:
            return (
                STATE_OPEN
                if is_open
                else STATE_CLOSED
            )

        if is_stopped:
            return STATE_STOPPED

        if not is_open:
            return STATE_CLOSING

        if is_pedestrian:
            return STATE_PARTIAL_OPENING

        return STATE_OPENING
