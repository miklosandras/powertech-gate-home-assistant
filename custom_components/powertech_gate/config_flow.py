"""Config flow for Powertech PW200."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import slugify

from .api import PW200Client
from .backend import (
    CannotConnect,
    CertificateProvisionError,
    InvalidAuth,
    PolicyAttachError,
    PowertechDevice,
    get_devices,
    login,
    provision,
)
from .const import (
    CONF_CA_PATH,
    CONF_CERT_PATH,
    CONF_DEVICE_LABEL,
    CONF_DEVICE_TYPE,
    CONF_PED_SUPPORTED,
    CONF_EXPERIMENTAL_MODEL,
    CONF_PROTOCOL_VALIDATED,
    CONF_PIN_VERIFIED,
    CONF_ENDPOINT,
    CONF_KEY_PATH,
    CONF_REFRESH_INTERVAL,
    CONF_ENABLE_DEBUG_ATTRIBUTES,
    CONF_SETUP_METHOD,
    CONF_SOURCE_ID,
    CONF_THING_ID,
    DEFAULT_ENDPOINT,
    DEFAULT_SOURCE_ID,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    SETUP_ACCOUNT,
    SETUP_MANUAL,
)

_LOGGER = logging.getLogger(__name__)


def _device_fingerprint(value: object) -> str:
    """Return a non-reversible short identifier for logs."""
    return hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()[:10]


class PowertechPW200ConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Powertech PW200 config flow."""

    # Keep VERSION 1 so existing v0.4.x config entries
    # remain compatible without migration.
    VERSION = 1

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._devices: dict[
            str,
            PowertechDevice,
        ] = {}
        self._pending_title: str | None = None
        self._pending_data: dict[str, Any] | None = None
        self._pending_expected_pin: str | None = None
        self._pending_reconfigure_entry_id: str | None = None

    async def async_step_user(
        self,
        user_input=None,
    ) -> FlowResult:
        """Choose automatic or manual setup."""
        return self.async_show_menu(
            step_id="user",
            menu_options=[
                "account",
                "manual",
            ],
        )

    async def async_step_account(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Log in with a Powertech/EyeOpen account."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[
                "username"
            ].strip()
            password = user_input[
                "password"
            ]

            try:
                access_token = (
                    await self.hass.async_add_executor_job(
                        login,
                        username,
                        password,
                    )
                )

                devices = (
                    await self.hass.async_add_executor_job(
                        get_devices,
                        access_token,
                    )
                )

            except InvalidAuth:
                errors["base"] = "invalid_auth"

            except CannotConnect:
                errors["base"] = "cannot_connect"

            except Exception:
                _LOGGER.exception(
                    "Unexpected Powertech login error"
                )
                errors["base"] = "unknown"

            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    # Store only in-memory for the remainder
                    # of this config flow. Password is discarded.
                    self._access_token = access_token
                    self._devices = {
                        device.uuid: device
                        for device in devices
                    }

                    if len(devices) == 1:
                        return (
                            await self._async_provision_device(
                                devices[0]
                            )
                        )

                    return (
                        await self.async_step_device()
                    )

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "username"
                    ): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                        )
                    ),
                    vol.Required(
                        "password"
                    ): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_device(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Select one Powertech IoT device."""
        if (
            not self._devices
            or self._access_token is None
        ):
            return self.async_abort(
                reason="account_session_lost"
            )

        if user_input is not None:
            device = self._devices.get(
                user_input["device"]
            )

            if device is None:
                return self.async_abort(
                    reason="account_session_lost"
                )

            return (
                await self._async_provision_device(
                    device
                )
            )

        options = [
            SelectOptionDict(
                value=device.uuid,
                label=device.label,
            )
            for device in sorted(
                self._devices.values(),
                key=lambda item: (
                    item.label.lower()
                ),
            )
        ]

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "device"
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=(
                                SelectSelectorMode.DROPDOWN
                            ),
                        )
                    )
                }
            ),
        )

    async def _async_validate_candidate(
        self,
        *,
        endpoint: str,
        thing_id: str,
        cert_path: str,
        key_path: str,
        device_label: str,
        device_type: str | None,
    ) -> tuple[bool, dict[str, bool], str | None]:
        """Validate the AWS/WBT shadow without moving the gate."""
        client = await self.hass.async_add_executor_job(
            lambda: PW200Client(
                endpoint=endpoint,
                thing_id=thing_id,
                source_id=DEFAULT_SOURCE_ID,
                cert_path=cert_path,
                key_path=key_path,
                ca_path=None,
                event_loop=self.hass.loop,
                device_label=device_label,
                device_type=device_type,
            )
        )

        try:
            await self.hass.async_add_executor_job(client.start)
            valid, capabilities = await self.hass.async_add_executor_job(
                client.wait_for_shadow_capabilities,
                12.0,
            )
            _LOGGER.debug(
                "Powertech candidate validation uuid=%s valid=%s capabilities=%s",
                thing_id[:8],
                valid,
                capabilities,
            )
            return valid, capabilities, client.decoded_pin
        finally:
            await self.hass.async_add_executor_job(client.stop)

    async def _async_provision_device(
        self,
        device: PowertechDevice,
    ) -> FlowResult:
        """Create AWS cert, attach policy, store cert/key."""
        assert self._access_token is not None

        await self.async_set_unique_id(
            slugify(device.uuid)
        )
        self._abort_if_unique_id_configured()

        credentials_base = (
            self.hass.config.path(
                "powertech_gate",
                "accounts",
            )
        )

        try:
            (
                endpoint,
                cert_path,
                key_path,
            ) = (
                await self.hass.async_add_executor_job(
                    lambda: provision(
                        access_token=(
                            self._access_token
                        ),
                        device=device,
                        credentials_base_directory=(
                            credentials_base
                        ),
                    )
                )
            )

            await self.hass.async_add_executor_job(
                PW200Client.validate_files,
                cert_path,
                key_path,
                None,
            )

            protocol_validated, capabilities, expected_pin = (
                await self._async_validate_candidate(
                    endpoint=endpoint,
                    thing_id=device.uuid,
                    cert_path=cert_path,
                    key_path=key_path,
                    device_label=device.label,
                    device_type=device.device_type,
                )
            )
            if not protocol_validated:
                _LOGGER.warning(
                    "Powertech candidate rejected after passive shadow validation; "
                    "uuid=%s capabilities=%s",
                    _device_fingerprint(device.uuid),
                    capabilities,
                )
                return self.async_abort(
                    reason="unsupported_protocol"
                )

        except CertificateProvisionError:
            _LOGGER.exception(
                "Powertech certificate creation failed"
            )
            return self.async_abort(
                reason="certificate_failed"
            )

        except PolicyAttachError:
            _LOGGER.exception(
                "Powertech AWS policy attach failed"
            )
            return self.async_abort(
                reason="policy_failed"
            )

        except (CannotConnect, InvalidAuth):
            _LOGGER.exception(
                "Powertech backend provisioning failed"
            )
            return self.async_abort(
                reason="cannot_connect"
            )

        except Exception:
            _LOGGER.exception(
                "Unexpected Powertech provisioning error"
            )
            return self.async_abort(
                reason="provision_failed"
            )

        # IMPORTANT: username, password, access token, refresh token and PIN
        # are intentionally not persisted.
        pending_data = {
            CONF_SETUP_METHOD: SETUP_ACCOUNT,
            CONF_ENDPOINT: endpoint,
            CONF_THING_ID: device.uuid,
            CONF_SOURCE_ID: DEFAULT_SOURCE_ID,
            CONF_CERT_PATH: cert_path,
            CONF_KEY_PATH: key_path,
            CONF_CA_PATH: "",
            CONF_DEVICE_LABEL: device.label,
            CONF_DEVICE_TYPE: device.device_type or "",
            CONF_PED_SUPPORTED: device.pedestrian_supported,
            CONF_EXPERIMENTAL_MODEL: device.experimental_model,
            CONF_PROTOCOL_VALIDATED: True,
            CONF_PIN_VERIFIED: False,
        }

        if expected_pin is None:
            return self.async_create_entry(title=device.label, data=pending_data)

        self._pending_title = device.label
        self._pending_data = pending_data
        self._pending_expected_pin = expected_pin
        self._pending_reconfigure_entry_id = None
        return await self.async_step_pin()


    async def async_step_pin(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Verify the six-digit gate PIN against the current WBT shadow."""
        if self._pending_data is None or self._pending_expected_pin is None:
            return self.async_abort(reason="account_session_lost")

        errors: dict[str, str] = {}
        if user_input is not None:
            pin = str(user_input["pin"]).strip()
            if len(pin) != 6 or not pin.isdigit():
                errors["base"] = "invalid_pin_format"
            elif pin != self._pending_expected_pin:
                errors["base"] = "invalid_pin"
            else:
                data = {**self._pending_data, CONF_PIN_VERIFIED: True}
                self._pending_expected_pin = None
                self._pending_data = None

                if self._pending_reconfigure_entry_id is not None:
                    entry = self.hass.config_entries.async_get_entry(
                        self._pending_reconfigure_entry_id
                    )
                    self._pending_reconfigure_entry_id = None
                    if entry is None:
                        return self.async_abort(reason="account_session_lost")
                    return self.async_update_and_abort(
                        entry, data=data, reason="reconfigure_successful"
                    )

                title = self._pending_title or "Powertech Gate"
                self._pending_title = None
                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="pin",
            data_schema=vol.Schema({
                vol.Required("pin"): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                )
            }),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Re-provision credentials using a Powertech/EyeOpen account."""
        entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        if entry is None:
            return self.async_abort(reason="account_session_lost")

        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                access_token = await self.hass.async_add_executor_job(
                    login,
                    user_input["username"].strip(),
                    user_input["password"],
                )
                devices = await self.hass.async_add_executor_job(
                    get_devices,
                    access_token,
                )
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected reconfigure login error")
                errors["base"] = "unknown"
            else:
                selected = next(
                    (
                        device
                        for device in devices
                        if device.uuid == entry.data.get(CONF_THING_ID)
                    ),
                    None,
                )
                if selected is None:
                    errors["base"] = "device_not_in_account"
                else:
                    self._access_token = access_token
                    credentials_base = self.hass.config.path(
                        "powertech_gate",
                        "accounts",
                    )
                    try:
                        endpoint, cert_path, key_path = (
                            await self.hass.async_add_executor_job(
                                lambda: provision(
                                    access_token=access_token,
                                    device=selected,
                                    credentials_base_directory=(
                                        credentials_base
                                    ),
                                )
                            )
                        )
                    except CertificateProvisionError:
                        return self.async_abort(
                            reason="certificate_failed"
                        )
                    except PolicyAttachError:
                        return self.async_abort(
                            reason="policy_failed"
                        )
                    except Exception:
                        _LOGGER.exception(
                            "Unexpected reconfigure provisioning error"
                        )
                        return self.async_abort(
                            reason="provision_failed"
                        )

                    protocol_validated, capabilities, expected_pin = (
                        await self._async_validate_candidate(
                            endpoint=endpoint,
                            thing_id=selected.uuid,
                            cert_path=cert_path,
                            key_path=key_path,
                            device_label=selected.label,
                            device_type=selected.device_type,
                        )
                    )
                    if not protocol_validated:
                        _LOGGER.warning(
                            "Reconfigured Powertech candidate failed passive shadow "
                            "validation; uuid=%s capabilities=%s",
                            _device_fingerprint(selected.uuid),
                            capabilities,
                        )
                        return self.async_abort(
                            reason="unsupported_protocol"
                        )

                    new_data = {
                        **entry.data,
                        CONF_ENDPOINT: endpoint,
                        CONF_CERT_PATH: cert_path,
                        CONF_KEY_PATH: key_path,
                        CONF_DEVICE_LABEL: selected.label,
                        CONF_DEVICE_TYPE: selected.device_type or "",
                        CONF_PED_SUPPORTED: selected.pedestrian_supported,
                        CONF_EXPERIMENTAL_MODEL: selected.experimental_model,
                        CONF_PROTOCOL_VALIDATED: True,
                        CONF_PIN_VERIFIED: False,
                    }

                    if expected_pin is None:
                        return self.async_update_and_abort(
                            entry, data=new_data, reason="reconfigure_successful"
                        )

                    self._pending_title = entry.title
                    self._pending_data = new_data
                    self._pending_expected_pin = expected_pin
                    self._pending_reconfigure_entry_id = entry.entry_id
                    return await self.async_step_pin()


        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required("username"): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.TEXT,
                        )
                    ),
                    vol.Required("password"): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return PowertechGateOptionsFlow(config_entry)

    async def async_step_manual(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manual certificate fallback."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ca_path = (
                user_input.get(
                    CONF_CA_PATH,
                    "",
                ).strip()
                or None
            )

            try:
                await self.hass.async_add_executor_job(
                    PW200Client.validate_files,
                    user_input[CONF_CERT_PATH],
                    user_input[CONF_KEY_PATH],
                    ca_path,
                )

            except FileNotFoundError:
                errors["base"] = "file_not_found"

            except Exception:
                _LOGGER.exception(
                    "Manual certificate validation failed"
                )
                errors[
                    "base"
                ] = "invalid_certificate"

            else:
                thing_id = user_input[
                    CONF_THING_ID
                ].strip()

                await self.async_set_unique_id(
                    slugify(thing_id)
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=(
                        f"Powertech Gate "
                        f"({thing_id[:8]})"
                    ),
                    data={
                        CONF_SETUP_METHOD: (
                            SETUP_MANUAL
                        ),
                        CONF_ENDPOINT: user_input[
                            CONF_ENDPOINT
                        ].strip(),
                        CONF_THING_ID: thing_id,
                        CONF_SOURCE_ID: user_input[
                            CONF_SOURCE_ID
                        ].strip(),
                        CONF_CERT_PATH: user_input[
                            CONF_CERT_PATH
                        ].strip(),
                        CONF_KEY_PATH: user_input[
                            CONF_KEY_PATH
                        ].strip(),
                        CONF_CA_PATH: (
                            user_input.get(
                                CONF_CA_PATH,
                                "",
                            ).strip()
                        ),
                        CONF_PED_SUPPORTED: True,
                        CONF_EXPERIMENTAL_MODEL: False,
                        CONF_PROTOCOL_VALIDATED: True,
                        CONF_PIN_VERIFIED: False,
                    },
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENDPOINT,
                        default=DEFAULT_ENDPOINT,
                    ): str,
                    vol.Required(
                        CONF_THING_ID
                    ): str,
                    vol.Required(
                        CONF_SOURCE_ID,
                        default=DEFAULT_SOURCE_ID,
                    ): str,
                    vol.Required(
                        CONF_CERT_PATH,
                        default=(
                            "/config/powertech_gate/"
                            "client.crt.pem"
                        ),
                    ): str,
                    vol.Required(
                        CONF_KEY_PATH,
                        default=(
                            "/config/powertech_gate/"
                            "client.key.pem"
                        ),
                    ): str,
                    vol.Optional(
                        CONF_CA_PATH,
                        default=(
                            "/config/powertech_gate/"
                            "AmazonRootCA1.pem"
                        ),
                    ): str,
                }
            ),
            errors=errors,
        )


class PowertechGateOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Powertech Gate."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data=user_input,
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_REFRESH_INTERVAL,
                        default=self._entry.options.get(
                            CONF_REFRESH_INTERVAL,
                            DEFAULT_REFRESH_INTERVAL,
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=15, max=3600),
                    ),
                    vol.Optional(
                        CONF_ENABLE_DEBUG_ATTRIBUTES,
                        default=self._entry.options.get(
                            CONF_ENABLE_DEBUG_ATTRIBUTES,
                            False,
                        ),
                    ): bool,
                }
            ),
        )
