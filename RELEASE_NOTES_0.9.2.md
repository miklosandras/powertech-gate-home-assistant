# Powertech Gate (EyeOpen) v0.9.2

This maintenance release fixes pedestrian-gate detection for the PS20040/PS20040D family.

## What changed

- Powertech may report the device as `PS20040` during account discovery.
- The same controller may identify itself at runtime as `PS20040D`.
- Both identifiers are now treated as pedestrian-capable.
- This fixes cases where the main gate worked but the **Pedestrian gate** entity was not created.
- No gate command/protocol behavior was changed.

## Upgrade

Update to **v0.9.2**, restart Home Assistant, then run **Reconfigure** for the integration.
