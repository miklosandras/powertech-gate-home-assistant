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

        # AWS shadow GET is safe only after both response subscriptions are
        # acknowledged. These flags/counters contain no sensitive payloads.
        self._shadow_subscribed = threading.Event()
        self._shadow_subscription_status: dict[str, bool] = {}
        self._pending_subscriptions: dict[int, str] = {}
        self._shadow_lock = threading.Lock()
        self._shadow_get_requests = 0
        self._shadow_get_accepted = 0
        self._shadow_get_rejected = 0
        self._last_shadow_get_at = 0.0
        self._shadow_publish_failures = 0

        # Passive activity counters used only for privacy-safe diagnostics.
        self._passive_command_ack_messages = 0
        self._passive_position_messages = 0

        # Validation-session MQTT lifecycle diagnostics. These counters are
        # deliberately preserved across reconnects.
        self._successful_connects = 0
        self._disconnect_events = 0
        self._manual_reconnect_attempts = 0
        self._manual_reconnect_failures = 0
        self._last_manual_reconnect_at = 0.0

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
        self._mqtt.on_subscribe = self._on_subscribe
        self._mqtt.on_message = self._on_message
        self._mqtt.reconnect_delay_set(min_delay=1, max_delay=3)

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

    # Keep retries inside the existing 12-second validation window; no gate
    # movement commands are sent during this process.
    SHADOW_RETRY_INTERVAL_SECONDS = 3.0

    def request_shadow(self) -> bool:
        """Request shadow only after MQTT confirms response subscriptions.

        Returns whether MQTT accepted the publish request (not whether AWS
        delivered a shadow). The payload is fixed and contains no identifiers.
        """
        if not self.is_connected or not self._shadow_subscribed.is_set():
            _LOGGER.debug(
                "Powertech shadow GET deferred; mqtt_connected=%s "
                "subscriptions_ready=%s",
                self.is_connected,
                self._shadow_subscribed.is_set(),
            )
            return False

        with self._shadow_lock:
            # Set before publish: the callback could receive the response
            # immediately on a different thread.
            self._last_shadow_get_at = time.monotonic()
            self._shadow_get_requests += 1
            request_number = self._shadow_get_requests

        info = self._mqtt.publish(self._topic_shadow_get, "{}", qos=0)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            with self._shadow_lock:
                self._shadow_publish_failures += 1
            _LOGGER.warning(
                "Powertech shadow GET publish failed; rc=%s",
                info.rc,
            )
            return False

        _LOGGER.debug(
            "Powertech shadow GET queued; attempt=%d", request_number
        )
        return True

    def wait_for_shadow_capabilities(
        self,
        timeout: float = 12.0,
    ) -> tuple[bool, dict[str, bool]]:
        """Passively validate AWS/WBT shadow and retry missed GETs safely.

        No OPEN, CLOSE, STOP or pedestrian commands are sent here.
        """
        timeout = max(timeout, 30.0)
        deadline = time.monotonic() + timeout
        _LOGGER.warning(
            "Powertech passive MQTT observation window started; "
            "duration_seconds=%d",
            int(timeout),
        )

        while time.monotonic() < deadline:
            now = time.monotonic()
            state = self.state
            if state.device_info and state.raw_status:
                return True, self._shadow_capabilities()

            if not self.is_connected:
                with self._shadow_lock:
                    last_manual_reconnect = self._last_manual_reconnect_at

                if (
                    not last_manual_reconnect
                    or now - last_manual_reconnect >= 5.0
                ):
                    with self._shadow_lock:
                        self._last_manual_reconnect_at = now
                        self._manual_reconnect_attempts += 1
                        reconnect_attempt = self._manual_reconnect_attempts

                    _LOGGER.warning(
                        "Powertech MQTT reconnect attempt; attempt=%d",
                        reconnect_attempt,
                    )
                    try:
                        reconnect_rc = self._mqtt.reconnect()
                    except Exception as err:
                        with self._shadow_lock:
                            self._manual_reconnect_failures += 1
                        _LOGGER.warning(
                            "Powertech MQTT reconnect attempt failed; "
                            "error_type=%s",
                            type(err).__name__,
                        )
                    else:
                        _LOGGER.debug(
                            "Powertech MQTT reconnect call returned; rc=%s",
                            reconnect_rc,
                        )

            if self._shadow_subscribed.is_set():
                with self._shadow_lock:
                    last_request = self._last_shadow_get_at
                    rejected_count = self._shadow_get_rejected

                if (
                    not last_request
                    or time.monotonic() - last_request
                    >= self.SHADOW_RETRY_INTERVAL_SECONDS
                ):
                    self.request_shadow()

                # 0.9.11 is intentionally passive after a shadow 404.
                _ = rejected_count

            time.sleep(0.1)

        with self._shadow_lock:
            attempts = self._shadow_get_requests
            accepted = self._shadow_get_accepted
            rejected = self._shadow_get_rejected
            publish_failures = self._shadow_publish_failures
            passive_command_ack_messages = (
                self._passive_command_ack_messages
            )
            passive_position_messages = (
                self._passive_position_messages
            )
            successful_connects = self._successful_connects
            disconnect_events = self._disconnect_events
            manual_reconnect_attempts = self._manual_reconnect_attempts
            manual_reconnect_failures = self._manual_reconnect_failures
            confirmed = sorted(
                topic
                for topic, ok in self._shadow_subscription_status.items()
                if ok
            )
            failed = sorted(
                topic
                for topic, ok in self._shadow_subscription_status.items()
                if not ok
            )

        _LOGGER.warning(
            "Powertech shadow validation timed out; mqtt_connected=%s "
            "subscriptions_ready=%s confirmed=%s failed=%s "
            "get_attempts=%d get_accepted=%d get_rejected=%d "
            "publish_failures=%d "
            "passive_command_ack_messages=%d "
            "passive_position_messages=%d successful_connects=%d "
            "disconnect_events=%d reconnect_attempts=%d "
            "reconnect_failures=%d",
            self.is_connected,
            self._shadow_subscribed.is_set(),
            confirmed,
            failed,
            attempts,
            accepted,
            rejected,
            publish_failures,
            passive_command_ack_messages,
            passive_position_messages,
            successful_connects,
            disconnect_events,
            manual_reconnect_attempts,
            manual_reconnect_failures,
        )
        return False, self._shadow_capabilities()

    def _shadow_capabilities(self) -> dict[str, bool]:
        """Return only boolean capability indicators for diagnostics."""
        return {
            "dev_info": bool(self.state.device_info),
            "dev_status": bool(self.state.raw_status),
            "wbt_version": bool(self.state.wbt_version),
            "uart_version": self.state.uart_version is not None,
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
        # Match the official EyeOpen Android app: pedestrian mode is opened
        # with PED OPEN, but closing uses the normal FULL CLOSE command.
        self._publish_command("FULL CLOSE")

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

        with self._shadow_lock:
            self._successful_connects += 1
            successful_connects = self._successful_connects

        if successful_connects > 1:
            _LOGGER.warning(
                "Powertech MQTT reconnected; reconnect_count=%d",
                successful_connects - 1,
            )

        # Reconnects start with a new set of SUBACKs. Avoid accepting an
        # earlier connection's subscription readiness.
        self._shadow_subscribed.clear()
        with self._shadow_lock:
            self._pending_subscriptions.clear()
            self._shadow_subscription_status.clear()
            self._last_shadow_get_at = 0.0

        self._connected.set()
        self._last_disconnect_reason = None
        self._notify()

        topics = (
            ("shadow_accepted", self._topic_shadow_ok),
            ("shadow_rejected", self._topic_shadow_err),
            ("shadow_updated", self._topic_shadow_update),
            ("position", self._topic_position),
            ("command_ack", self._topic_cmd_tx),
        )
        for name, topic in topics:
            rc, mid = client.subscribe(topic, qos=0)
            if rc != mqtt.MQTT_ERR_SUCCESS:
                with self._shadow_lock:
                    self._shadow_subscription_status[name] = False
                _LOGGER.warning(
                    "Powertech MQTT subscribe request failed; "
                    "topic_kind=%s rc=%s", name, rc,
                )
            else:
                with self._shadow_lock:
                    self._pending_subscriptions[mid] = name
                _LOGGER.debug(
                    "Powertech MQTT subscription requested; topic_kind=%s",
                    name,
                )
        # Do not request the shadow yet: wait for both GET response SUBACKs.

    def _on_subscribe(
        self,
        client,
        userdata,
        mid,
        reason_code_list,
        properties=None,
    ) -> None:
        """Confirm AWS subscription readiness before the first shadow GET."""
        with self._shadow_lock:
            name = self._pending_subscriptions.pop(mid, None)
        if name is None:
            _LOGGER.debug("Powertech MQTT received untracked SUBACK")
            return

        accepted = bool(reason_code_list) and all(
            not (
                reason.is_failure
                if hasattr(reason, "is_failure")
                else int(reason) >= 128
            )
            for reason in reason_code_list
        )
        with self._shadow_lock:
            self._shadow_subscription_status[name] = accepted
            ready = (
                self._shadow_subscription_status.get("shadow_accepted") is True
                and self._shadow_subscription_status.get("shadow_rejected") is True
            )

        _LOGGER.debug(
            "Powertech MQTT subscription acknowledged; "
            "topic_kind=%s accepted=%s", name, accepted,
        )
        if not accepted:
            _LOGGER.warning(
                "Powertech MQTT subscription rejected; topic_kind=%s",
                name,
            )

        if ready and not self._shadow_subscribed.is_set():
            self._shadow_subscribed.set()
            _LOGGER.debug("Powertech MQTT shadow response subscriptions ready")
            self.request_shadow()

    def _on_disconnect(
        self,
        client,
        userdata,
        disconnect_flags,
        reason_code,
        properties=None,
    ) -> None:
        raw_reason_code = getattr(reason_code, "value", None)
        if type(raw_reason_code) is not int:
            try:
                raw_reason_code = int(reason_code)
            except (TypeError, ValueError):
                raw_reason_code = None

        with self._shadow_lock:
            self._disconnect_events += 1
            disconnect_count = self._disconnect_events

        _LOGGER.warning(
            "Powertech MQTT disconnected during validation; "
            "code=%s reason=%s disconnect_count=%d",
            raw_reason_code,
            reason_code,
            disconnect_count,
        )
        self._connected.clear()
        self._shadow_subscribed.clear()
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
            with self._shadow_lock:
                self._passive_command_ack_messages += 1
                command_ack_count = self._passive_command_ack_messages
            _LOGGER.warning(
                "Powertech passive MQTT activity observed; "
                "topic_kind=command_ack count=%d",
                command_ack_count,
            )

            _LOGGER.debug("Powertech MQTT command-ack message received")

            self.state = replace(
                self.state,
                last_ack=payload,
            )
            self._notify()
            return

        if msg.topic == self._topic_position:
            with self._shadow_lock:
                self._passive_position_messages += 1
                position_count = self._passive_position_messages
            _LOGGER.warning(
                "Powertech passive MQTT activity observed; "
                "topic_kind=position count=%d",
                position_count,
            )

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
            with self._shadow_lock:
                self._shadow_get_rejected += 1
            # AWS IoT shadow/get/rejected normally includes a numeric error
            # code. Record only that code: the full error response may contain
            # request metadata and must not be copied into public logs.
            try:
                error = json.loads(payload)
            except json.JSONDecodeError:
                error = None

            code = error.get("code") if isinstance(error, dict) else None
            if type(code) is not int:
                code = None

            _LOGGER.warning(
                "Powertech shadow request rejected; code=%s",
                code,
            )
            return

        if msg.topic not in (
            self._topic_shadow_ok,
            self._topic_shadow_update,
        ):
            return

        if msg.topic == self._topic_shadow_ok:
            with self._shadow_lock:
                self._shadow_get_accepted += 1
            _LOGGER.debug("Powertech shadow GET accepted")

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
