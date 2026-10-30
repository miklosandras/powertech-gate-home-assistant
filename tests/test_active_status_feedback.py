"""Replay physical captures through production state/cover code; no network."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import types
import unittest
from unittest.mock import patch

from test_position_feedback import api, cover, sensor, make_client, receive
class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    async def sleep(self, duration):
        self.now += duration
        await asyncio.sleep(0)



class ActiveFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.client = make_client()
        self.client.device_type = "PS19001"
        self.client.state.uart_version = 1
        self.client.status_feedback_enabled = True
        self.client._connected.set()
        self.full = cover.PowertechPW200Cover(self.client)
        self.ped = cover.PowertechPW200PedestrianCover(self.client)
        self.position = sensor.PowertechPositionSensor(self.client)

    def status(self, text, value):
        receive(self.client, self.client._topic_cmd_tx, f"ACK STATUS:{text},{value};src=PRIVATE")

    def test_captured_full_and_pedestrian_cycles_and_stale_shadows(self):
        cycles = json.loads((Path(__file__).parent / "legacy_status_cycles.json").read_text())
        for cycle in cycles:
            self.setUp()
            identified = False
            for reply in cycle["replies"]:
                self.status(reply["status"], reply["position"])
                state = self.client.state
                before = (state.gate_state, state.position, state.opening_mode)
                receive(self.client, self.client._topic_shadow_ok,
                        '{"state":{"reported":{"DEV STATUS":"00,00,10,00,00,00,00,00,00"}}}')
                state = self.client.state
                self.assertEqual(before, (state.gate_state, state.position, state.opening_mode))
                self.assertTrue(self.full.available)
                self.assertEqual(self.position.native_value, reply["position"])
                if reply["status"].endswith("CLOSED"):
                    self.assertTrue(self.full.is_closed)
                    self.assertTrue(self.ped.is_closed)
                    self.assertTrue(self.client.physical_gate_closed)
                    identified = False
                elif reply["status"] == "SINGLE STOPPED" or reply["status"].endswith("OPENED"):
                    identified = True
                    self.assertEqual(state.opening_mode, cycle["mode"])
                    self.assertFalse(self.client.physical_gate_closed)
                    self.assertEqual(self.full.is_closed, cycle["mode"] != "full")
                    self.assertEqual(self.ped.is_closed, cycle["mode"] != "pedestrian")
                elif not identified:
                    self.assertIsNone(self.full.is_closed)
                    self.assertIsNone(self.ped.is_closed)
                elif reply["status"].endswith("CLOSING"):
                    self.assertEqual(self.full.is_closing, cycle["mode"] == "full")
                    self.assertEqual(self.ped.is_closing, cycle["mode"] == "pedestrian")
            self.assertEqual(self.client._mqtt.published, [])

    def test_near_endpoint_closed_reply_and_raw_diagnostic(self):
        self.status("PED CLOSED", 1)
        self.assertTrue(self.full.is_closed)
        self.assertEqual(self.position.native_value, 1)
        self.status("PED OPENING", 0)
        self.assertFalse(self.client.physical_gate_closed)
        self.assertIsNone(self.full.is_closed)
        self.status("PED CLOSED", 50)
        self.assertFalse(self.client.physical_gate_closed)

    def test_stale_feedback_unavailable_without_claiming_closed(self):
        with patch.object(api.time, "monotonic", return_value=100):
            self.status("SINGLE STOPPED", 26)
        with patch.object(api.time, "monotonic", return_value=161):
            self.assertFalse(self.full.available)
            self.assertFalse(self.position.available)
            self.assertIsNone(self.full.is_closed)
            self.assertIsNone(self.ped.is_closed)
            self.assertIsNone(self.full.extra_state_attributes["physical_gate_closed"])

    def test_invalid_retained_and_command_acks_are_not_physical_feedback(self):
        self.assertFalse(self.full.available)
        for payload in ("ACK FULL OPEN", "ACK PED CLOSE", "ACK STATUS:PED CLOSED,101"):
            receive(self.client, self.client._topic_cmd_tx, payload)
        self.client._on_message(None, None, types.SimpleNamespace(
            topic=self.client._topic_cmd_tx, payload=b"ACK STATUS:PED CLOSED,0", retain=True))
        self.assertFalse(self.full.available)
        self.assertEqual(self.client.system_status_generation, 0)

    def test_position_events_clear_old_direction_and_close_both_modes(self):
        self.status("PED OPENED", 98)
        self.status("PED CLOSING", 82)
        receive(self.client, self.client._topic_position, "40")
        self.assertFalse(self.full.is_closed)
        self.assertTrue(self.ped.is_closed)
        self.assertFalse(self.full.is_closing)
        receive(self.client, self.client._topic_position, "0")
        self.assertTrue(self.full.is_closed)
        self.assertTrue(self.ped.is_closed)

    def test_other_models_and_uart_versions_do_not_apply_legacy_state(self):
        for model, uart in (("PS20088D", 1), ("PS19001", 2)):
            self.setUp()
            self.client.device_type = model
            self.client.state.uart_version = uart
            self.status("SINGLE STOPPED", 26)
            self.assertFalse(self.client.state.status_received)


class PollerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = make_client()
        self.client.device_type = "PS19001"
        self.client.status_feedback_enabled = True
        self.client.state.uart_version = 1
        self.client._connected.set()
        self.client._shadow_subscription_status["command_ack"] = True
        self.clock = Clock()
        self.poller = self.client.status_poller
        self.poller.clock, self.poller.sleep = self.clock, self.clock.sleep

    async def executor(self, method):
        return method()

    async def test_polling_sends_only_legacy_read(self):
        original = self.client._mqtt.publish
        def publish(topic, payload, qos=0):
            result = original(topic, payload, qos)
            receive(self.client, self.client._topic_cmd_tx, "ACK STATUS:PED CLOSED,0")
            return result
        self.client._mqtt.publish = publish
        await self.poller.sample(self.executor)
        self.assertEqual(self.poller.responses, 1)
        self.assertEqual(self.client._mqtt.published,
                         [(self.client._topic_cmd_rx, "c=READ STATUS;src=test-source", 0)])
        self.assertEqual(self.poller.interval(), 10)

    async def test_single_request_timeout_and_backoff(self):
        async def sleep(duration):
            self.assertTrue(self.poller.waiting)
            await self.clock.sleep(duration)
        self.poller.sleep = sleep
        await self.poller.sample(self.executor)
        self.assertEqual(len(self.client._mqtt.published), 1)
        self.assertGreaterEqual(self.clock(), 8)
        self.assertEqual(self.poller.failures, 1)
        self.assertEqual(self.poller.interval(), 20)
        self.assertFalse(self.poller.waiting)

    async def test_fast_window_is_bounded_and_resets_after_closed(self):
        self.client.state = replace(self.client.state, status_received=True,
                                    feedback_updated_at=api.time.monotonic(), gate_state=api.STATE_OPEN)
        self.assertEqual(self.poller.interval(), 2)
        self.clock.now = 91
        self.assertEqual(self.poller.interval(), 10)
        self.client.state = replace(self.client.state, gate_state=api.STATE_CLOSED)
        self.assertEqual(self.poller.interval(), 10)
        self.assertIsNone(self.poller.active_since)

    async def test_cancel_clears_waiting_flag(self):
        self.poller.sleep = asyncio.sleep
        task = asyncio.create_task(self.poller.sample(self.executor))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.poller.waiting)

    async def test_background_loop_skips_other_models_and_disconnection(self):
        for reason in ("other_model", "uart2", "disconnected"):
            await self.asyncSetUp()
            if reason == "other_model":
                self.client.device_type = "PS20088D"
            elif reason == "uart2":
                self.client.state.uart_version = 2
            elif reason == "disconnected":
                self.client._connected.clear()
            async def stop(_duration):
                raise asyncio.CancelledError
            self.poller.sleep = stop
            with self.assertRaises(asyncio.CancelledError):
                await self.poller.run(self.executor)
            self.assertEqual(self.client._mqtt.published, [])

    async def test_closing_after_long_hold_starts_another_fast_window(self):
        self.client.state = replace(self.client.state, status_received=True,
                                    feedback_updated_at=api.time.monotonic(), gate_state=api.STATE_OPEN)
        self.assertEqual(self.poller.interval(), 2)
        self.clock.now = 91
        self.assertEqual(self.poller.interval(), 10)
        self.client.state = replace(self.client.state, gate_state=api.STATE_CLOSING)
        self.assertEqual(self.poller.interval(), 2)


class StatusParserTests(unittest.TestCase):
    def test_only_bounded_known_legacy_replies_are_accepted(self):
        for payload in (None, "ACK FULL OPEN", "ACK STATUS:PED CLOSED,-1",
                        "ACK STATUS:PED CLOSED,101", "ACK STATUS:OTHER,20",
                        "ACK STATUS:SINGLE STOPPED,2.5", "ACK STATUS:PED CLOSED,٠"):
            self.assertEqual(api.parse_status_reply(payload), {})
        self.assertEqual(api.parse_status_reply("ACK STATUS:SINGLE STOPPED,25;src=private"),
                         {"ack": "ACK STATUS", "status": "SINGLE STOPPED", "status_position": 25})

    def test_read_requires_supported_model_connection_and_command_subscription(self):
        client = make_client()
        client.device_type = "PS19001"
        client.state.uart_version = 1
        client.status_feedback_enabled = True
        self.assertFalse(client.request_fresh_system_status())
        client._connected.set()
        self.assertFalse(client.request_fresh_system_status())
        client._shadow_subscription_status["command_ack"] = True
        client.device_type = "PS20088D"
        self.assertFalse(client.request_fresh_system_status())
        client.device_type = "PS19001"
        client.state.uart_version = 2
        self.assertFalse(client.request_fresh_system_status())
        self.assertEqual(client._mqtt.published, [])
        client.state.uart_version = 1
        client._mqtt.publish_rc = 4
        self.assertFalse(client.request_fresh_system_status())
        self.assertEqual(client._mqtt.published[-1][1], "c=READ STATUS;src=test-source")
