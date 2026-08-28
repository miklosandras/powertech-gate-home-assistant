"""Powertech backend provisioning client.

This module is used only during the Home Assistant config flow.

The Powertech password is never written to the Home Assistant config entry.
After setup, the integration talks directly to AWS IoT with the generated
client certificate/private key.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from .const import BACKEND_BASE_URL, BACKEND_REST_TOKEN, KNOWN_PEDESTRIAN_MODELS

_LOGGER = logging.getLogger(__name__)


class PowertechBackendError(Exception):
    """Base Powertech backend exception."""


class InvalidAuth(PowertechBackendError):
    """Invalid Powertech username/password."""


class CannotConnect(PowertechBackendError):
    """Powertech backend cannot be reached."""


class CertificateProvisionError(PowertechBackendError):
    """Powertech returned an incomplete certificate response."""


class PolicyAttachError(PowertechBackendError):
    """AWS IoT policy attach failed."""


@dataclass(slots=True)
class PowertechDevice:
    """Powertech backend device entry."""

    uuid: str
    endpoint: str
    label: str
    device_type: str | None = None
    product_type: str | None = None
    uuid_type: str | None = None
    pedestrian_supported: bool = False
    experimental_model: bool = False


def _request(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    authorization: str | None = None,
) -> dict:
    """Perform a small JSON request using only the Python standard library."""
    url = BACKEND_BASE_URL.rstrip("/") + path
    data = None
    headers = {
        "Accept": "application/json",
        "User-Agent": "HomeAssistant-Powertech-PW200/0.5.0",
    }

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    if authorization:
        headers["Authorization"] = authorization

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")

            if not raw.strip():
                return {}

            try:
                result = json.loads(raw)
            except json.JSONDecodeError as err:
                raise CannotConnect(
                    f"Invalid JSON returned by {path}"
                ) from err

            if not isinstance(result, dict):
                raise CannotConnect(
                    f"Unexpected JSON type returned by {path}"
                )

            return result

    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")

        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}

        # Do not propagate backend response bodies into Home Assistant
        # exceptions/logs. Error bodies are outside our control and may contain
        # account/device metadata or echoed request data.
        if err.code in (401, 403):
            raise InvalidAuth("Powertech authentication failed") from err

        raise CannotConnect(
            f"Powertech backend HTTP error {err.code}"
        ) from err

    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise CannotConnect(str(err)) from err


def login(username: str, password: str) -> str:
    """Log in with the password grant used by the Android app."""
    response = _request(
        "POST",
        "/v4.0/user/outh2/token/",
        body={
            "username": username,
            "password": password,
            "grant_type": "password",
            "scope": "user",
            "app_type_index": 2,
        },
        authorization=BACKEND_REST_TOKEN,
    )

    access_token = response.get("access_token")
    if not access_token:
        raise InvalidAuth("No access_token in login response")

    return str(access_token)



def _fingerprint(value: object) -> str | None:
    """Return a non-reversible short fingerprint for debug logs."""
    if value in (None, ""):
        return None
    return hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()[:10]


def _redact_device_for_debug(item: dict) -> dict:
    """Return only non-secret device discovery metadata for logs."""
    if not isinstance(item, dict):
        return {}

    return {
        "keys": sorted(item.keys()),
        "uuid_fingerprint": _fingerprint(
            item.get("uuid")
            or item.get("UID")
            or item.get("uid")
            or item.get("device_uuid")
        ),
        "uuid_type": (
            item.get("uuid_type")
            or item.get("uuidType")
            or item.get("UUIDType")
        ),
        "device_type": (
            item.get("devies_type")
            or item.get("devices_type")
            or item.get("device_type")
            or item.get("deviceType")
        ),
        "product_type": (
            item.get("product_type")
            or item.get("productType")
        ),
        "has_iot_endpoint": bool(
            item.get("iot_endpoint")
            or item.get("awsEndpoint")
            or item.get("aws_endpoint")
            or item.get("endpoint")
        ),
        "has_bt_mac": bool(
            item.get("bt_mac_address")
            or item.get("btMacAddress")
        ),
        "has_pin_code": bool(
            item.get("pin_code")
            or item.get("pinCode")
        ),
        "admin_user_present": bool(
            item.get("admin_user")
            or item.get("adminUser")
        ),
        "organization_present": bool(
            item.get("organization")
        ),
    }


def _log_device_bucket(bucket: str, value) -> None:
    """Log Powertech device-list schema without leaking credentials."""
    entries = list(_iter_device_items(value) or [])
    _LOGGER.debug(
        "Powertech discovery bucket=%s entries=%d",
        bucket,
        len(entries),
    )
    for index, item in enumerate(entries):
        _LOGGER.debug(
            "Powertech discovery item bucket=%s index=%d metadata=%s",
            bucket,
            index,
            _redact_device_for_debug(item),
        )


def _iter_device_items(value):
    """Yield objects from a device bucket that can be object/list/null."""
    if value is None:
        return

    if isinstance(value, dict):
        yield value
        return

    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item



def _extract_custom_names(value) -> dict[str, str]:
    """Best-effort extraction of UUID -> display name from backend custom_info."""
    result: dict[str, str] = {}

    def walk(item):
        if isinstance(item, dict):
            uuid = str(item.get("uuid") or item.get("uid") or "").strip()
            name = (
                item.get("display_name")
                or item.get("displayName")
                or item.get("device_name")
                or item.get("deviceName")
                or item.get("name")
            )
            if uuid and isinstance(name, str) and name.strip():
                result[uuid] = name.strip()
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return result


def get_devices(access_token: str) -> list[PowertechDevice]:
    """Read candidate Powertech AWS IoT gate devices from the account."""
    response = _request(
        "GET",
        "/v4.0/user/devices/",
        authorization=f"Bearer {access_token}",
    )

    custom_names = _extract_custom_names(response.get("custom_info"))

    for _bucket_name in (
        "admin_devices",
        "user_devices",
        "share_devices",
    ):
        _log_device_bucket(
            _bucket_name,
            response.get(_bucket_name),
        )

    custom_info = response.get("custom_info")
    if custom_info is not None:
        if isinstance(custom_info, dict):
            _LOGGER.debug(
                "Powertech discovery custom_info keys=%s",
                sorted(custom_info.keys()),
            )
        elif isinstance(custom_info, list):
            _LOGGER.debug(
                "Powertech discovery custom_info list_items=%d",
                len(custom_info),
            )
        else:
            _LOGGER.debug(
                "Powertech discovery custom_info type=%s",
                type(custom_info).__name__,
            )

    devices: list[PowertechDevice] = []
    seen: set[str] = set()

    for bucket in ("admin_devices", "user_devices", "share_devices"):
        for item in _iter_device_items(response.get(bucket)):
            uuid = str(item.get("uuid") or "").strip()
            endpoint = str(item.get("iot_endpoint") or "").strip()

            # Capability-based discovery: UUID + AWS IoT endpoint are required.
            if not uuid or not endpoint or uuid in seen:
                continue

            device_type = (
                item.get("devies_type")
                or item.get("devices_type")
                or item.get("device_type")
            )
            product_type = item.get("product_type")
            uuid_type = item.get("uuid_type")

            friendly_name = custom_names.get(uuid)
            if friendly_name:
                label = friendly_name
            else:
                model_text = str(device_type or "Powertech Gate")
                label = f"{model_text} · {uuid[:8]}"

            normalized_device_type = str(device_type or "").upper()
            pedestrian_supported = normalized_device_type in KNOWN_PEDESTRIAN_MODELS
            experimental_model = not pedestrian_supported

            devices.append(
                PowertechDevice(
                    uuid=uuid,
                    endpoint=endpoint,
                    label=label,
                    device_type=(
                        str(device_type)
                        if device_type is not None
                        else None
                    ),
                    product_type=(
                        str(product_type)
                        if product_type is not None
                        else None
                    ),
                    uuid_type=(
                        str(uuid_type)
                        if uuid_type is not None
                        else None
                    ),
                    pedestrian_supported=pedestrian_supported,
                    experimental_model=experimental_model,
                )
            )
            seen.add(uuid)

    _LOGGER.debug("Powertech device list parsed; candidate_devices=%d", len(devices))
    return devices


def _pick(response: dict, *keys: str):
    """Pick the first populated response key."""
    for key in keys:
        value = response.get(key)
        if value not in (None, ""):
            return value
    return None


def create_user_certificate(
    access_token: str,
) -> tuple[str, str, str, str]:
    """Create an AWS IoT user certificate.

    RequestAwsUserCertificateCreate extends RequestAwsAppType, whose Android
    body is exactly {"app": 0}.
    """
    response = _request(
        "PUT",
        "/v4.0/devices/iot/user/certificate/",
        body={"app": 0},
        authorization=f"Bearer {access_token}",
    )

    endpoint = _pick(response, "endpoint")
    certificate_arn = _pick(
        response,
        "user_certificateArn",
        "user_certificate_arn",
        "certificateArn",
        "certificate_arn",
        "certificateARN",
    )
    certificate_pem = _pick(
        response,
        "certificatePem",
        "certificate_pem",
        "certificatePEM",
        "certificate",
    )
    private_key = _pick(
        response,
        "PrivateKey",
        "privateKey",
        "private_key",
        "privateKeyPem",
        "private_key_pem",
    )

    if not all(
        (
            endpoint,
            certificate_arn,
            certificate_pem,
            private_key,
        )
    ):
        safe_keys = ", ".join(sorted(response.keys()))
        raise CertificateProvisionError(
            "Incomplete certificate response. "
            f"Received fields: {safe_keys}"
        )

    return (
        str(endpoint),
        str(certificate_arn),
        str(certificate_pem),
        str(private_key),
    )


def attach_policy(
    access_token: str,
    *,
    endpoint: str,
    certificate_arn: str,
    uuid: str,
) -> None:
    """Attach the AWS IoT certificate policy to one device."""
    try:
        _request(
            "PUT",
            "/v4.0/devices/iot/device/policy/",
            body={
                "endpoint": endpoint,
                "user_certificateArn": certificate_arn,
                "uuid": uuid,
            },
            authorization=f"Bearer {access_token}",
        )
    except (InvalidAuth, CannotConnect) as err:
        raise PolicyAttachError(str(err)) from err


def save_credentials(
    base_directory: str,
    *,
    uuid: str,
    certificate_pem: str,
    private_key: str,
) -> tuple[str, str]:
    """Save certificate/key under the HA config directory."""
    target = Path(base_directory) / uuid
    target.mkdir(parents=True, exist_ok=True)

    try:
        os.chmod(target, 0o700)
    except OSError:
        pass

    cert_path = target / "client.crt.pem"
    key_path = target / "client.key.pem"

    cert_path.write_text(
        certificate_pem.strip() + "\n",
        encoding="utf-8",
    )
    key_path.write_text(
        private_key.strip() + "\n",
        encoding="utf-8",
    )

    try:
        os.chmod(cert_path, 0o600)
        os.chmod(key_path, 0o600)
    except OSError:
        pass

    return str(cert_path), str(key_path)


def provision(
    *,
    access_token: str,
    device: PowertechDevice,
    credentials_base_directory: str,
) -> tuple[str, str, str]:
    """Provision AWS credentials for one selected Powertech device."""
    (
        certificate_endpoint,
        certificate_arn,
        certificate_pem,
        private_key,
    ) = create_user_certificate(access_token)

    # The endpoint returned with the new certificate is authoritative.
    endpoint = certificate_endpoint or device.endpoint

    attach_policy(
        access_token,
        endpoint=endpoint,
        certificate_arn=certificate_arn,
        uuid=device.uuid,
    )

    _LOGGER.debug("AWS IoT policy attach completed for device=%s", _fingerprint(device.uuid))

    cert_path, key_path = save_credentials(
        credentials_base_directory,
        uuid=device.uuid,
        certificate_pem=certificate_pem,
        private_key=private_key,
    )

    _LOGGER.debug("Automatic Powertech provisioning completed for device=%s", _fingerprint(device.uuid))
    return endpoint, cert_path, key_path
