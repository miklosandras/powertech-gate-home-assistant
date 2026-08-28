# Powertech Gate (EyeOpen) for Home Assistant

Unofficial Home Assistant custom integration for compatible Powertech / EyeOpen
AWS IoT gate controllers.

> This project is community-developed and is not affiliated with or endorsed by
> Powertech Automation.

## Features

- UI-based setup
- Automatic onboarding with a Powertech/EyeOpen account
- Six-digit gate PIN verification compatible with EyeOpen's WBT PIN check
- Powertech password and gate PIN are used only during setup/reconfigure and are not stored
- Automatic AWS IoT client certificate provisioning and policy attachment
- Read-only protocol validation before automatic gate control is enabled
- Main gate: open, close and stop
- Pedestrian/partial gate on confirmed models
- Live gate position
- Automatic unavailable/reconnect handling
- IP address and Wi-Fi MAC diagnostic entities
- Home Assistant diagnostics with sensitive fields redacted
- Hungarian and English translations
- Manual AWS certificate setup as an advanced fallback

## Compatibility

Automatic discovery is capability-based rather than tied to the literal
`WBT01` name.

A Powertech account device first becomes a candidate when it has:

- a stable UUID
- an AWS IoT endpoint

After provisioning, the integration performs a read-only AWS IoT shadow GET.
Automatic gate control is enabled only when the device returns both
`DEV INFO` and `DEV STATUS`.

No OPEN/CLOSE/STOP/PED command is sent during compatibility validation.

### Confirmed models

| Backend model | Runtime model | Main gate | Stop | Position | Pedestrian |
| --- | --- | --- | --- | --- | --- |
| PS20088 | PS20088D | ✅ | ✅ | ✅ | ✅ |

The confirmed reference device reports a `DEV INFO` value compatible with
`P190U,PS20088D,V02`.

### Experimental models

Other Powertech devices that expose the same AWS/WBT shadow schema may pass
read-only validation and be added as experimental main-gate devices.
Optional capabilities are not enabled until their behavior is verified.

## Requirements

- Home Assistant 2026.3 or newer
- A compatible Powertech/EyeOpen account/device, or existing AWS IoT
  certificate credentials for manual setup
- Internet access from Home Assistant and the gate controller for the AWS IoT
  cloud path

## Installation

### HACS custom repository

After this project is published on GitHub:

1. Open HACS.
2. Add this repository as a custom **Integration** repository.
3. Install **Powertech Gate (EyeOpen)**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration**.
6. Search for **Powertech Gate (EyeOpen)**.

### Manual installation

Copy:

```text
custom_components/powertech_gate
```

to:

```text
/config/custom_components/powertech_gate
```

and restart Home Assistant.

## Configuration

### Recommended: Powertech/EyeOpen account

1. Add **Powertech Gate (EyeOpen)**.
2. Choose automatic account setup.
3. Enter the Powertech/EyeOpen username and password.
4. Select a gate if multiple candidates are returned.
5. The integration provisions its own AWS IoT certificate.
6. A read-only shadow validation checks the Powertech gate protocol.
7. Enter the gate's six-digit PIN when requested.
8. The integration verifies the PIN against the current WBT shadow and then discards it.
9. The Home Assistant device/entities are created.

The account password, gate PIN, temporary backend access token and refresh
token are not retained by the integration after onboarding.

### Manual AWS setup

Manual setup is intended for advanced users who already have a valid AWS IoT
client certificate/private key and know the Powertech Thing ID and command
source ID.

## Entities

A confirmed PS20088-family device exposes:

- **Gate** cover
- **Pedestrian gate** cover
- **IP address** diagnostic sensor
- **Wi-Fi MAC** diagnostic sensor

The device registry also receives runtime metadata such as model and firmware
after the AWS IoT shadow is received.

## Data updates

The integration uses AWS IoT MQTT push updates for gate state and live
position. It also performs periodic shadow refreshes.

If the MQTT connection is lost, the entities become unavailable. When
connectivity returns, the integration reconnects automatically and the
entities recover without restarting Home Assistant.

For tested PS20088D hardware, pedestrian open/close state also uses the
device's explicit command ACKs so Home Assistant does not have to wait for the
next periodic shadow refresh.

## Reconfigure

Use Home Assistant's **Reconfigure** action to sign in again, verify the gate
PIN and provision a fresh AWS IoT client certificate for the configured gate.

## Diagnostics

Home Assistant diagnostics are supported. Sensitive identifiers, credential
paths and network details are redacted. The diagnostic output may retain
non-secret capability flags such as whether PIN verification succeeded.

Do not publish:

- Powertech/EyeOpen passwords
- gate PIN codes
- access or refresh tokens
- AWS IoT private keys
- AWS IoT client certificates
- Android keystores
- unredacted Home Assistant backups

## Troubleshooting

### Device is not listed during setup

Enable debug logging and look for privacy-safe lines containing:

```text
Powertech discovery
```

A candidate needs a UUID and AWS IoT endpoint.

### Candidate is rejected

Look for:

```text
Powertech candidate validation
```

Automatic control requires both `DEV INFO` and `DEV STATUS` from the AWS IoT
shadow.

### Gate becomes unavailable

Check the Home Assistant log for the MQTT disconnect reason. The integration
should automatically reconnect when AWS IoT connectivity returns.

### Reporting a new model

Use the **New model compatibility** GitHub issue template and provide only the
privacy-safe discovery/validation metadata.

## Privacy and security

See `SECURITY.md`.

## Vendor protocol note

Automatic account onboarding reproduces the behavior of the official
Powertech/EyeOpen Android client, including use of a static OAuth application
authorization value embedded in that public mobile client. It is not a
per-user password or token. Vendor-side API or authentication changes may
therefore break automatic onboarding without notice.

## Trademark notice

Powertech and EyeOpen names may be trademarks of their respective owners.
They are used here only to identify compatible products/services. This
repository intentionally does not redistribute vendor logo artwork.

## Development status

`0.9.0` is the first public release. The confirmed PS20088/PS20088D reference
hardware has been tested for account onboarding, PIN verification,
provisioning, shadow validation, open, close, stop, pedestrian open/close,
live position, unavailable state and automatic reconnect.

## License

See `LICENSE`.
