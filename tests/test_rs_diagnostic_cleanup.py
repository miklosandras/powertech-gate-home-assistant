"""Offline regression guards for removing the unused RS diagnostic path."""
import ast
from pathlib import Path
import unittest

API = Path(__file__).resolve().parents[1] / "custom_components" / "powertech_gate" / "api.py"


class RSDiagnosticCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = API.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.client = next(node for node in cls.tree.body if isinstance(node, ast.ClassDef) and node.name == "PW200Client")
        cls.methods = {node.name: node for node in cls.client.body if isinstance(node, ast.FunctionDef)}

    def test_unused_rs_publisher_removed(self):
        self.assertNotIn("request_system_status_diagnostic", self.methods)
        self.assertNotIn("c=RS;src=", self.source)

    def test_no_stale_rs_state(self):
        for name in ("_system_status_requested", "_system_status_ack_received", "_system_status_ack_format_valid", "_system_status_publish_failures"):
            self.assertNotIn(name, self.source)

    def test_ack_processing_retained(self):
        handler = ast.get_source_segment(self.source, self.methods["_on_message"])
        self.assertIn("self._topic_cmd_tx", handler)
        self.assertIn("last_ack=payload", handler)
        self.assertIn("self._notify()", handler)

    def test_gate_commands_unchanged(self):
        expected = {"open_gate": "FULL OPEN", "close_gate": "FULL CLOSE", "stop_gate": "STOP", "pedestrian_open": "PED OPEN", "pedestrian_close": "FULL CLOSE"}
        for method, command in expected.items():
            self.assertIn(f'self._publish_command("{command}")', ast.get_source_segment(self.source, self.methods[method]))

    def test_shadow_safety_guards_retained(self):
        for name in ("request_shadow", "wait_for_shadow_capabilities", "_on_subscribe"):
            self.assertIn(name, self.methods)
        self.assertIn("self._shadow_subscribed.is_set()", ast.get_source_segment(self.source, self.methods["request_shadow"]))
        self.assertIn("self._shadow_subscribed.set()", ast.get_source_segment(self.source, self.methods["_on_subscribe"]))

    def test_python_compiles(self):
        compile(self.source, str(API), "exec")


if __name__ == "__main__":
    unittest.main()
