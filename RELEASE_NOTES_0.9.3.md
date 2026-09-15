# Powertech Gate (EyeOpen) 0.9.3

## Fixed

Pedestrian gate closing now matches the behavior of the official EyeOpen Android app.

- **Pedestrian Open** sends `PED OPEN`.
- **Pedestrian Close** now sends `FULL CLOSE`.
- `PED CLOSE` is no longer sent by the Home Assistant pedestrian close action.

A community PS20040/PS20040D controller explicitly returned `NAK PED CLOSE` for the previous command while accepting `FULL CLOSE` with `ACK FULL CLOSE`. Review of the official EyeOpen APK confirmed that pedestrian mode has a dedicated open command, while closing uses the normal gate close command.

No changes were made to discovery, AWS IoT provisioning, PIN verification, main-gate open/close/stop, or capability detection.

## Updating

Update through HACS and restart Home Assistant.

No Reconfigure step is required specifically for this 0.9.3 fix.
