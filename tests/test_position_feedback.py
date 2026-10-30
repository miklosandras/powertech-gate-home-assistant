"""Replay sanitised PS19001 observations through real message and cover code."""

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from test_shadow_diagnostics_096 import api, FakeLoop

ROOT = Path(__file__).resolve().parents[1]


def make_client():
    return api.PW200Client(
        endpoint="test.invalid", thing_id="test-thing", source_id="test-source",
        cert_path="unused", key_path="unused", ca_path=None, event_loop=FakeLoop(),
    )


def receive(client, topic, payload):
    client._on_message(None, None, types.SimpleNamespace(
        topic=topic, payload=payload.encode(), retain=False, dup=False,
    ))


def load_entities(filename):
    """Stub HA's entity scaffolding only; exercise the actual entity properties."""
    modules = {}
    for name in ("homeassistant", "homeassistant.components", "homeassistant.components.cover",
                 "homeassistant.components.binary_sensor",
                 "homeassistant.components.sensor", "homeassistant.config_entries",
                 "homeassistant.const", "homeassistant.core", "homeassistant.helpers",
                 "homeassistant.helpers.device_registry", "homeassistant.helpers.entity_platform",
                 "powertech_gate.const", "powertech_gate.device"):
        modules[name] = types.ModuleType(name)
    cover = modules["homeassistant.components.cover"]
    cover.CoverEntity = object
    cover.CoverDeviceClass = types.SimpleNamespace(GATE="gate")
    cover.CoverEntityFeature = types.SimpleNamespace(OPEN=1, CLOSE=2, STOP=4)
    modules["homeassistant.components.sensor"].SensorEntity = object
    modules["homeassistant.components.binary_sensor"].BinarySensorEntity = object
    modules["homeassistant.components.binary_sensor"].BinarySensorDeviceClass = types.SimpleNamespace(OPENING="opening")
    modules["homeassistant.config_entries"].ConfigEntry = object
    modules["homeassistant.core"].HomeAssistant = object
    modules["homeassistant.core"].callback = lambda func: func
    modules["homeassistant.const"].EntityCategory = types.SimpleNamespace(DIAGNOSTIC="diagnostic")
    modules["homeassistant.helpers.device_registry"].DeviceInfo = dict
    modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object
    modules["powertech_gate.device"].build_device_info = lambda client: {}
    modules["powertech_gate.device"].format_mac = lambda value: value
    const = modules["powertech_gate.const"]
    const.DOMAIN = "powertech_gate"
    const.CONF_PED_SUPPORTED = "pedestrian_supported"
    for name in dir(api):
        if name.startswith("STATE_"):
            setattr(const, name, getattr(api, name))
    modules["powertech_gate.api"] = api
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(
            f"powertech_gate.{filename}", ROOT / "custom_components/powertech_gate" / f"{filename}.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


cover = load_entities("cover")
sensor = load_entities("sensor")


class PositionFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.client = make_client()
        self.client.device_type = "PS19001"
        self.full = cover.PowertechPW200Cover(self.client)
        self.pedestrian = cover.PowertechPW200PedestrianCover(self.client)
        self.position = sensor.PowertechPositionSensor(self.client)

    def shadow(self, status="00,00,10,00,00,00,00,00,00", topic=None):
        receive(self.client, topic or self.client._topic_shadow_ok,
                json.dumps({"state": {"reported": {"DEV STATUS": status}}}))

    def test_captured_cycles_close_and_never_hide_nonzero_positions(self):
        fixtures = json.loads((ROOT / "tests/ps19001_cycles.json").read_text())
        for cycle in fixtures:
            with self.subTest(cycle=cycle["name"]):
                self.setUp()
                positions = []
                for message in cycle["messages"]:
                    kind = message["kind"]
                    if kind == "position":
                        value = message["position_payload"]
                        receive(self.client, self.client._topic_position, str(value))
                        positions.append(value)
                        self.assertEqual(self.full.is_closed, value == 0)
                        self.assertEqual(self.pedestrian.is_closed, value == 0)
                        self.assertEqual(self.position.native_value, value)
                    elif kind == "command_ack":
                        receive(self.client, self.client._topic_cmd_tx, message["ack"])
                        if message["ack"] == "ACK PED OPEN":
                            self.assertFalse(self.pedestrian.is_closed)
                    else:
                        before = self.client.state.position
                        self.shadow(",".join(f"{value:02X}" for value in message["status_bytes"]))
                        if positions:
                            self.assertEqual(self.client.state.position, before)
                            self.assertEqual(self.full.is_closed, before == 0)
                            self.assertEqual(self.pedestrian.is_closed, before == 0)
                self.assertGreater(max(positions), 0)
                self.assertEqual(positions[-1], 0)
                self.assertTrue(self.full.is_closed)
                self.assertTrue(self.pedestrian.is_closed)
                self.assertEqual(self.client._mqtt.published, [])

    def test_stale_close_ack_cannot_hide_later_physical_opening(self):
        receive(self.client, self.client._topic_cmd_tx, "ACK FULL CLOSE")
        receive(self.client, self.client._topic_position, "40")
        self.assertFalse(self.full.is_closed)
        self.assertFalse(self.pedestrian.is_closed)

    def test_command_close_does_not_claim_closed_before_zero_feedback(self):
        receive(self.client, self.client._topic_position, "40")
        receive(self.client, self.client._topic_cmd_tx, "ACK FULL CLOSE")
        self.assertFalse(self.full.is_closed)
        self.assertFalse(self.pedestrian.is_closed)
        receive(self.client, self.client._topic_position, "0")
        self.assertTrue(self.full.is_closed)
        self.assertTrue(self.pedestrian.is_closed)

    def test_new_open_ack_is_superseded_by_next_position(self):
        receive(self.client, self.client._topic_position, "0")
        receive(self.client, self.client._topic_cmd_tx, "ACK PED OPEN;src=PRIVATE")
        self.assertFalse(self.pedestrian.is_closed)
        self.shadow()
        self.assertFalse(self.pedestrian.is_closed)
        receive(self.client, self.client._topic_position, "0")
        self.assertTrue(self.pedestrian.is_closed)
        self.assertEqual(self.client.state.last_ack, "ACK PED OPEN;src=PRIVATE")

    def test_malformed_out_of_range_and_retained_positions_cannot_close_gate(self):
        receive(self.client, self.client._topic_position, "40")
        for value in ("-1", "101", "invalid", "", "2.5", "40%%"):
            receive(self.client, self.client._topic_position, value)
            self.assertEqual(self.position.native_value, 40)
        self.client._on_message(None, None, types.SimpleNamespace(
            topic=self.client._topic_position, payload=b"0", retain=True))
        self.assertFalse(self.full.is_closed)

    def test_position_sensor_unknown_until_event_not_shadow_estimate(self):
        self.shadow()
        self.assertIsNone(self.position.native_value)
        receive(self.client, self.client._topic_position, "20%")
        self.assertEqual(self.position.native_value, 20)
        self.shadow()
        self.assertEqual(self.position.native_value, 20)

    def test_does_not_invent_direction_from_partial_travel_value(self):
        receive(self.client, self.client._topic_position, "40")
        self.client.state = replace(self.client.state, gate_state=api.STATE_CLOSING)
        for entity in (self.full, self.pedestrian):
            self.assertFalse(entity.is_closed)
            self.assertFalse(entity.is_opening)
            self.assertFalse(entity.is_closing)

    def test_other_models_keep_existing_shadow_and_ack_behavior(self):
        self.client.device_type = "PS20088D"
        self.shadow()
        receive(self.client, self.client._topic_position, "40")
        self.assertTrue(self.full.is_closed)
        receive(self.client, self.client._topic_cmd_tx, "ACK PED OPEN")
        self.assertFalse(self.pedestrian.is_closed)
        receive(self.client, self.client._topic_position, "0")
        self.assertFalse(self.pedestrian.is_closed)
        self.shadow("00,00,00,80")
        self.assertEqual(self.client.state.position, 100)

    def test_runtime_model_identification_selects_fix(self):
        self.client.device_type = None
        self.client.state = replace(self.client.state, device_info="P190,PS19001,V0.1")
        self.assertTrue(self.client.uses_position_feedback)

    def test_network_diagnostics_default_disabled_without_disabling_position(self):
        for cls in (sensor.PowertechPW200IPAddressSensor, sensor.PowertechPW200MacAddressSensor):
            self.assertFalse(cls(self.client)._attr_entity_registry_enabled_default)
        self.assertTrue(getattr(self.position, "_attr_entity_registry_enabled_default", True))

    def test_disconnect_makes_both_covers_and_sensor_unavailable(self):
        self.client._connected.set()
        receive(self.client, self.client._topic_position, "40")
        self.assertTrue(self.full.available)
        self.client._on_disconnect(None, None, None, "test", None)
        self.assertFalse(self.full.available)
        self.assertFalse(self.pedestrian.available)
        self.assertFalse(self.position.available)


if __name__ == "__main__":
    unittest.main()
