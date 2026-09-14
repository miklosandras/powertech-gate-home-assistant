# Powertech Gate (EyeOpen) for Home Assistant

Unofficial Home Assistant custom integration for compatible Powertech / EyeOpen AWS IoT gate controllers.

## What's new in 0.9.2

- Fixed pedestrian-capability detection for the `PS20040` / `PS20040D` family.
- Powertech may report `PS20040` during account setup while runtime `DEV INFO` reports `PS20040D`.
- Both identifiers are now treated as pedestrian-capable.
- Existing installs should run **Reconfigure** after updating so the stored capability flags are refreshed.

## Compatibility

### Confirmed models

| Backend model | Runtime model | Main gate | Stop | Position | Pedestrian |
| --- | --- | --- | --- | --- | --- |
| PS20088 | PS20088D | ✅ | ✅ | ✅ | ✅ |

### Additional known models

- `PS20040` / `PS20040D` are recognized as pedestrian-capable.
- Community diagnostics show the backend/runtime naming mismatch described above.
- This family has been reported as a PSA500-class controller; broader verification is ongoing.

## Shared accounts

Version 0.9.1 added support for EyeOpen shared/Manager accounts where the actual device metadata is nested under `share_devices[].devies_info`.

## Upgrade

1. Update through HACS.
2. Restart Home Assistant.
3. Run **Reconfigure** on the Powertech Gate integration if you use a PS20040/PS20040D device.

The `pedestrian_supported` flag is stored during setup/reconfigure, so this step is required after the capability registry changes.

## Project

Repository: `miklosandras/powertech-gate-home-assistant`
