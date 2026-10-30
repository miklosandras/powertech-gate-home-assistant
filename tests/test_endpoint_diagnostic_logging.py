"""Offline regression tests for privacy-safe AWS endpoint diagnostics.

Extract only the relevant backend functions; no network, Home Assistant,
credentials, MQTT connection or physical controller is required.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "custom_components" / "powertech_gate" / "backend.py"
EXPECTED_ENDPOINT = "expected.iot.eu-central-1.amazonaws.com"


def _load_certificate_functions(response):
    """Load certificate handling with an in-memory fake backend response."""
    source = BACKEND.read_text(encoding="utf-8")
    tree = ast.parse(source)
    required = {"_pick", "_endpoint_region", "create_user_certificate"}
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in required
    ]
    if {node.name for node in functions} != required:
        raise AssertionError("Certificate helper functions not found")

    calls = []

    def fake_request(method, path, *, body, authorization):
        calls.append((method, path, body, authorization))
        return response

    namespace = {
        "_request": fake_request,
        "_LOGGER": logging.getLogger("powertech_endpoint_diagnostic_test"),
        "OFFICIAL_WBT_AWS_ENDPOINT": EXPECTED_ENDPOINT,
        "CertificateProvisionError": RuntimeError,
    }
    module = ast.Module(body=functions, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(BACKEND), "exec"), namespace)
    return namespace["create_user_certificate"], calls


class EndpointDiagnosticTests(unittest.TestCase):
    def _check(self, endpoint, expected_level, expected_match):
        response = {
            "endpoint": endpoint,
            "user_certificateArn": "SECRET_ARN_DO_NOT_LOG",
            "certificatePem": "SECRET_CERTIFICATE_DO_NOT_LOG",
            "PrivateKey": "SECRET_PRIVATE_KEY_DO_NOT_LOG",
        }
        create_certificate, calls = _load_certificate_functions(response)
        with self.assertLogs("powertech_endpoint_diagnostic_test", level="DEBUG") as captured:
            values = create_certificate("test-access-token")
        self.assertEqual(values, (
            endpoint, response["user_certificateArn"],
            response["certificatePem"], response["PrivateKey"],
        ))
        self.assertEqual(calls, [(
            "PUT", "/v4.0/devices/iot/user/certificate/",
            {"app": 0}, "Bearer test-access-token",
        )])
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].levelname, expected_level)
        output = captured.output[0]
        self.assertIn(f"certificate_endpoint_matches_official={expected_match}", output)
        self.assertIn("certificate_region=", output)
        for secret in (
            "SECRET_ARN_DO_NOT_LOG", "SECRET_CERTIFICATE_DO_NOT_LOG",
            "SECRET_PRIVATE_KEY_DO_NOT_LOG", "test-access-token",
        ):
            self.assertNotIn(secret, output)

    def test_expected_endpoint_is_debug_only(self):
        self._check(EXPECTED_ENDPOINT, "DEBUG", "True")

    def test_unexpected_endpoint_remains_warning(self):
        self._check("alternate.iot.us-east-1.amazonaws.com", "WARNING", "False")


if __name__ == "__main__":
    unittest.main()
