"""Exercise whole-gateway closure independently of the access-mode covers."""

import asyncio
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch

from test_position_feedback import api, load_entities, make_client, receive

binary_sensor = load_entities("binary_sensor")


class PhysicalGateClosedTests(unittest.TestCase):
    def setUp(self):
        self.client = make_client()
        self.client.device_type = "PS19001"
        self.client.state.uart_version = 1
        self.client.status_feedback_enabled = True
        self.client._connected.set()
        self.entity = binary_sensor.PowertechGateStateSensor(self.client)

    def status(self, text, value):
        receive(self.client, self.client._topic_cmd_tx, f"ACK STATUS:{text},{value}")

    def test_captured_cycles_report_not_closed_regardless_of_access_mode(self):
        cycles = json.loads((Path(__file__).parent / "legacy_status_cycles.json").read_text())
        for cycle in cycles:
            self.setUp()
            for reply in cycle["replies"]:
                self.status(reply["status"], reply["position"])
                self.assertTrue(self.entity.available)
                self.assertEqual(self.entity.is_on, not reply["status"].endswith("CLOSED"))
            self.assertFalse(self.entity.is_on)
            self.assertEqual(self.client._mqtt.published, [])

    def test_unknown_mode_and_closing_zero_are_not_confirmed_closed(self):
        self.status("PED OPENING", 0)
        self.assertEqual(self.client.state.opening_mode, "unknown")
        self.assertTrue(self.entity.is_on)
        self.status("PED CLOSING", 0)
        self.assertTrue(self.entity.is_on)
        self.status("PED CLOSED", 0)
        self.assertFalse(self.entity.is_on)

    def test_no_feedback_or_command_ack_does_not_confirm_closure(self):
        self.assertFalse(self.entity.available)
        self.assertIsNone(self.entity.is_on)
        receive(self.client, self.client._topic_cmd_tx, "ACK FULL CLOSE")
        self.assertIsNone(self.entity.is_on)

    def test_stale_closed_value_does_not_remain_confirmed(self):
        with patch.object(api.time, "monotonic", return_value=100):
            self.status("PED CLOSED", 0)
        with patch.object(api.time, "monotonic", return_value=160):
            self.assertFalse(self.entity.is_on)
        with patch.object(api.time, "monotonic", return_value=160.001):
            self.assertFalse(self.entity.available)
            self.assertIsNone(self.entity.is_on)

    def test_disconnect_does_not_retain_confirmed_closed(self):
        self.status("PED CLOSED", 0)
        self.client._connected.clear()
        self.assertFalse(self.entity.available)
        self.assertIsNone(self.entity.is_on)

    def test_bad_retained_and_shadow_updates_cannot_confirm_closure(self):
        self.status("SINGLE STOPPED", 25)
        for payload in ("ACK STATUS:PED CLOSED,101", "ACK FULL CLOSE"):
            receive(self.client, self.client._topic_cmd_tx, payload)
        self.client._on_message(None, None, types.SimpleNamespace(
            topic=self.client._topic_cmd_tx, payload=b"ACK STATUS:PED CLOSED,0", retain=True))
        receive(self.client, self.client._topic_shadow_ok,
                '{"state":{"reported":{"DEV STATUS":"00,00,10,00,00,00,00,00,00"}}}')
        self.assertTrue(self.entity.is_on)

    def test_fresh_position_event_uses_existing_physical_feedback(self):
        receive(self.client, self.client._topic_position, "40")
        self.assertTrue(self.entity.is_on)
        receive(self.client, self.client._topic_position, "0")
        self.assertFalse(self.entity.is_on)

    def test_unsupported_model_or_uart_unavailable(self):
        self.status("PED CLOSED", 0)
        self.client.state.uart_version = 2
        self.assertFalse(self.entity.available)
        self.assertIsNone(self.entity.is_on)
        self.client.state.uart_version = 1
        self.client.device_type = "PS20088D"
        self.assertFalse(self.entity.available)

    def test_discovery_waits_for_validated_metadata_and_adds_only_once(self):
        listeners, removals, entities = [], [], []
        self.client.add_listener = lambda listener: (listeners.append(listener) or (lambda: listeners.remove(listener)))
        entry = types.SimpleNamespace(entry_id="test", async_on_unload=removals.append)
        hass = types.SimpleNamespace(data={"powertech_gate": {"test": self.client}})
        self.client.state.uart_version = None
        asyncio.run(binary_sensor.async_setup_entry(hass, entry, entities.extend))
        self.assertEqual(entities, [])
        self.client.state.uart_version = 1
        listeners[0]()
        listeners[0]()
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]._attr_unique_id, "test-thing_physical_gate_closed")
        removals[0]()
        self.assertEqual(listeners, [])

    def test_opening_class_and_name_match_inverted_state(self):
        self.assertEqual(self.entity._attr_device_class, "opening")
        self.assertEqual(self.entity._attr_translation_key, "gate_state")
        self.assertEqual(self.entity._attr_unique_id, "test-thing_physical_gate_closed")

    def test_other_model_has_no_entity(self):
        self.client.device_type = "PS20088D"
        self.client.add_listener = lambda listener: lambda: None
        entry = types.SimpleNamespace(entry_id="test", async_on_unload=lambda fn: None)
        hass = types.SimpleNamespace(data={"powertech_gate": {"test": self.client}})
        entities = []
        asyncio.run(binary_sensor.async_setup_entry(hass, entry, entities.extend))
        self.assertEqual(entities, [])


if __name__ == "__main__":
    unittest.main()
