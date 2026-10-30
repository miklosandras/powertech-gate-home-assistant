"""Offline MQTT shadow diagnostics tests; no Home Assistant or gate required."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]

pkg = types.ModuleType('powertech_gate')
pkg.__path__ = [str(ROOT / 'custom_components' / 'powertech_gate')]
sys.modules['powertech_gate'] = pkg
const = types.ModuleType('powertech_gate.const')
const.DEFAULT_PORT = 8883
for name in ('CLOSED', 'CLOSING', 'FACTORY', 'OPEN', 'OPENING', 'PARTIAL_OPEN',
             'PARTIAL_OPENING', 'STOPPED', 'UNKNOWN'):
    setattr(const, 'STATE_' + name, name.lower())
sys.modules['powertech_gate.const'] = const

class FakePublishInfo:
    def __init__(self, rc=0):
        self.rc = rc
    def wait_for_publish(self, timeout=None):
        return True

class FakeMQTTClient:
    def __init__(self, *args, **kwargs):
        self.subscriptions = []
        self.published = []
        self.mid = 0
        self.publish_rc = 0
        self.subscribe_rc_by_topic = {}
    def reconnect_delay_set(self, **kwargs): pass
    def tls_set(self, **kwargs): pass
    def subscribe(self, topic, qos=0):
        self.mid += 1
        self.subscriptions.append((self.mid, topic))
        return self.subscribe_rc_by_topic.get(topic, 0), self.mid
    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return FakePublishInfo(self.publish_rc)
    def connect(self, *args, **kwargs): return 0
    def loop_start(self): pass
    def disconnect(self): pass
    def loop_stop(self): pass

mqtt_mod = types.ModuleType('paho.mqtt.client')
mqtt_mod.Client = FakeMQTTClient
mqtt_mod.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
mqtt_mod.MQTTv311 = 4
mqtt_mod.MQTT_ERR_SUCCESS = 0
sys.modules['paho'] = types.ModuleType('paho')
sys.modules['paho.mqtt'] = types.ModuleType('paho.mqtt')
sys.modules['paho.mqtt.client'] = mqtt_mod
sys.modules['paho.mqtt'].client = mqtt_mod

spec = importlib.util.spec_from_file_location(
    'powertech_gate.api',
    ROOT / 'custom_components' / 'powertech_gate' / 'api.py',
)
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)

class FakeLoop:
    def call_soon_threadsafe(self, fn): fn()

class ShadowDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.client = api.PW200Client(
            endpoint='test.invalid', thing_id='test-thing', source_id='test-source',
            cert_path='/not/used', key_path='/not/used', ca_path=None,
            event_loop=FakeLoop(),
        )
        self.mqtt = self.client._mqtt
        self.client.SHADOW_RETRY_INTERVAL_SECONDS = 0.025

    def connect(self):
        self.client._on_connect(
            self.mqtt, None, None, types.SimpleNamespace(is_failure=False), None
        )

    def ack(self, kind, accepted=True):
        for mid, topic in reversed(self.mqtt.subscriptions):
            if kind in topic and mid in self.client._pending_subscriptions:
                self.client._on_subscribe(
                    self.mqtt, None, mid,
                    [types.SimpleNamespace(is_failure=not accepted)], None
                )
                return
        self.fail(f'No subscription for {kind}')

    def shadow_requests(self):
        return [x for x in self.mqtt.published if x[0].endswith('/shadow/get')]

    def test_initial_get_waits_for_both_response_subacks(self):
        self.connect()
        self.assertEqual(self.shadow_requests(), [])
        self.assertFalse(self.client.request_shadow())
        self.ack('get/accepted')
        self.assertEqual(self.shadow_requests(), [])
        self.ack('get/rejected')
        self.assertEqual(len(self.shadow_requests()), 1)
        self.assertTrue(self.client._shadow_subscribed.is_set())
        self.assertTrue(all(topic.endswith('/shadow/get') for topic, _, _ in self.mqtt.published))

    def test_rejected_suback_does_not_request_shadow(self):
        self.connect()
        self.ack('get/accepted')
        self.ack('get/rejected', accepted=False)
        self.assertFalse(self.client._shadow_subscribed.is_set())
        self.assertEqual(self.shadow_requests(), [])

    def test_subscribe_request_failure_is_logged_and_blocks_get(self):
        self.mqtt.subscribe_rc_by_topic[self.client._topic_shadow_err] = 4
        self.connect()
        self.ack('get/accepted')
        self.assertFalse(self.client._shadow_subscribed.is_set())
        self.assertEqual(self.shadow_requests(), [])

    def test_retries_after_subacks_and_timeout_summary(self):
        self.connect()
        self.ack('get/accepted')
        self.ack('get/rejected')
        with self.assertLogs(api.__name__, level='WARNING') as captured:
            valid, capabilities = self.client.wait_for_shadow_capabilities(0.14)
        self.assertFalse(valid)
        self.assertFalse(capabilities['dev_status'])
        self.assertGreaterEqual(len(self.shadow_requests()), 2)
        self.assertTrue(any('shadow validation timed out' in line for line in captured.output))
        self.assertTrue(any('get_accepted=0' in line for line in captured.output))
        self.assertEqual(len(self.mqtt.published), len(self.shadow_requests()))

    def test_get_accepted_enables_validation(self):
        self.connect()
        self.ack('get/accepted')
        self.ack('get/rejected')
        msg = types.SimpleNamespace(
            topic=self.client._topic_shadow_ok,
            payload=json.dumps({'state': {'reported': {
                'DEV INFO': 'P190U,PS20088D,V02',
                'DEV STATUS': '60,64,AA,00,40,00,00,40,00',
            }}}).encode(),
        )
        self.client._on_message(self.mqtt, None, msg)
        valid, capabilities = self.client.wait_for_shadow_capabilities(0.05)
        self.assertTrue(valid)
        self.assertTrue(capabilities['dev_info'])
        self.assertTrue(capabilities['dev_status'])
        self.assertEqual(self.client._shadow_get_accepted, 1)

    def test_get_rejected_logs_only_numeric_code(self):
        msg = types.SimpleNamespace(
            topic=self.client._topic_shadow_err,
            payload=b'{"code":403,"message":"SECRET_RESPONSE_DO_NOT_LOG"}',
        )
        with self.assertLogs(api.__name__, level='WARNING') as captured:
            self.client._on_message(self.mqtt, None, msg)
        self.assertIn('code=403', captured.output[0])
        self.assertNotIn('SECRET_RESPONSE_DO_NOT_LOG', captured.output[0])
        self.assertEqual(self.client._shadow_get_rejected, 1)

    def test_reconnect_requires_new_subacks(self):
        self.connect()
        self.ack('get/accepted')
        self.ack('get/rejected')
        self.client._on_disconnect(self.mqtt, None, None, 'normal', None)
        self.assertFalse(self.client.request_shadow())
        self.connect()
        self.assertFalse(self.client.request_shadow())
        self.ack('get/accepted')
        self.assertFalse(self.client._shadow_subscribed.is_set())
        self.ack('get/rejected')
        self.assertTrue(self.client._shadow_subscribed.is_set())
        self.assertEqual(len(self.shadow_requests()), 2)

    def test_failed_shadow_publish_reports_failure_without_gate_commands(self):
        self.connect()
        self.ack('get/accepted')
        self.mqtt.publish_rc = 4
        with self.assertLogs(api.__name__, level='WARNING'):
            self.ack('get/rejected')
        self.assertEqual(self.client._shadow_publish_failures, 1)
        self.assertEqual(len(self.shadow_requests()), 1)
        self.assertNotIn('/wbt01Rx', self.mqtt.published[0][0])

    def test_routine_ack_and_position_activity_is_debug_only(self):
        ack = types.SimpleNamespace(
            topic=self.client._topic_cmd_tx,
            payload=b'ACK FULL OPEN',
        )
        position = types.SimpleNamespace(
            topic=self.client._topic_position,
            payload=b'45%',
        )
        with self.assertLogs(api.__name__, level='DEBUG') as captured:
            self.client._on_message(self.mqtt, None, ack)
            self.client._on_message(self.mqtt, None, position)
        self.assertEqual(self.client.state.last_ack, 'ACK FULL OPEN')
        self.assertEqual(self.client.state.position, 45)
        self.assertEqual(self.client._passive_command_ack_messages, 1)
        self.assertEqual(self.client._passive_position_messages, 1)
        self.assertTrue(all(record.levelname == 'DEBUG' for record in captured.records))
        self.assertTrue(any('topic_kind=command_ack' in line for line in captured.output))
        self.assertTrue(any('topic_kind=position' in line for line in captured.output))
        self.assertEqual(self.mqtt.published, [])

    def test_invalid_position_still_warns_without_state_update(self):
        msg = types.SimpleNamespace(
            topic=self.client._topic_position,
            payload=b'not-a-position',
        )
        with self.assertLogs(api.__name__, level='DEBUG') as captured:
            self.client._on_message(self.mqtt, None, msg)
        self.assertEqual(self.client._passive_position_messages, 1)
        self.assertIsNone(self.client.state.position)
        self.assertTrue(any(
            record.levelname == 'WARNING'
            and 'Invalid Powertech position payload' in record.getMessage()
            for record in captured.records
        ))
        self.assertEqual(self.mqtt.published, [])

    def test_successful_reconnect_is_info_not_warning(self):
        with self.assertLogs(api.__name__, level='INFO') as captured:
            self.connect()
            self.connect()
        self.assertTrue(any(
            record.levelname == 'INFO'
            and 'Powertech MQTT reconnected' in record.getMessage()
            for record in captured.records
        ))
        self.assertFalse(any(record.levelname == 'WARNING' for record in captured.records))
        self.assertEqual(self.mqtt.published, [])

    def test_passive_validation_start_and_reconnect_attempt_are_debug(self):
        from unittest import mock

        self.mqtt.reconnect = lambda: 0
        with mock.patch.object(api.time, 'monotonic', side_effect=[100.0, 101.0, 102.0, 131.0]):
            with mock.patch.object(api.time, 'sleep', return_value=None):
                with self.assertLogs(api.__name__, level='DEBUG') as captured:
                    valid, _ = self.client.wait_for_shadow_capabilities(0.01)
        self.assertFalse(valid)
        self.assertTrue(any(
            record.levelname == 'DEBUG'
            and 'observation window started' in record.getMessage()
            for record in captured.records
        ))
        self.assertTrue(any(
            record.levelname == 'DEBUG'
            and 'reconnect attempt; attempt=' in record.getMessage()
            for record in captured.records
        ))
        self.assertTrue(any(
            record.levelname == 'WARNING'
            and 'shadow validation timed out' in record.getMessage()
            for record in captured.records
        ))
        self.assertEqual(self.client._manual_reconnect_attempts, 1)
        self.assertEqual(self.mqtt.published, [])

    def test_disconnect_remains_warning(self):
        with self.assertLogs(api.__name__, level='WARNING') as captured:
            self.client._on_disconnect(self.mqtt, None, None, 'normal', None)
        self.assertTrue(any(
            'Powertech MQTT disconnected' in record.getMessage()
            for record in captured.records
        ))
        self.assertEqual(self.mqtt.published, [])

    def test_non_response_subacks_do_not_trigger_get(self):
        self.connect()
        self.ack('/position')
        self.ack('/wbt01Tx')
        self.ack('update/accepted')
        self.assertEqual(self.shadow_requests(), [])

if __name__ == '__main__':
    unittest.main(verbosity=2)
