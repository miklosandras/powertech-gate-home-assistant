# Powertech Gate (EyeOpen) v0.9.1

This maintenance release fixes automatic onboarding for gates shared to another
Powertech/EyeOpen account.

## What changed

- Shared/Manager accounts are now discovered correctly.
- The integration reads device metadata nested under `share_devices[].devies_info`.
- Shared-account AWS certificate provisioning and policy attachment were tested successfully.
- MQTT connection and passive protocol validation were tested successfully from a shared account.
- `PS20040D` is included in the pedestrian-capability registry.

## Upgrade

Update through HACS, restart Home Assistant, and use **Reconfigure** if the
integration was previously set up with a shared account.
