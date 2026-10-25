# Changelog

## 0.9.15
- Fix Home Assistant startup waiting on the indefinitely running periodic shadow refresh task (fixes #2).
- Register periodic shadow refresh as a config-entry-owned background task, with Home Assistant managing its lifecycle during unload.
- Add offline regression tests for task creation and successful/failed unload paths.
- No change to gate movement commands, MQTT topics, PIN verification, or safety checks.

## 0.9.14
- Add PS17066 and PS17066C to the pedestrian-capable model registry.
- This enables the Pedestrian gate entity for PS17066-family controllers after reconfiguration refreshes the stored capability flag.
- Community diagnostics confirmed backend model `PS17066`, runtime model `PS17066C`, UART version 1, successful protocol/PIN validation, and pedestrian support in the official EyeOpen app.
- No MQTT topic, parser, movement command, or safety-validation behavior is changed.

## 0.9.13
- Handle Home Assistant startup failures according to config-entry lifecycle expectations.
- Raise `ConfigEntryNotReady` for temporary AWS IoT/network connection failures so Home Assistant retries automatically.
- Raise `ConfigEntryError` when configured TLS certificate, private key, or CA material is missing, unreadable, invalid, or rejected.
- Stop the MQTT client if startup partially succeeds but platform forwarding fails.
- This release is focused on HACS review compliance and does not change gate protocol behavior.

## 0.9.12
- Make the 30-second passive EyeOpen observation resilient to MQTT disconnects.
- Preserve `wbt01Tx` and `position` message counters across reconnects.
- Re-subscribe automatically through the normal Paho `on_connect` flow after reconnection.
- Reduce reconnect backoff during setup validation and add a bounded reconnect fallback while the observation window is active.
- Add privacy-safe disconnect/reconnect counters and reason-code diagnostics.
- Keep the test fully passive: no `RS`, OPEN, CLOSE, STOP, PED or other gate command is sent.
- Keep `DEV INFO` / `DEV STATUS` and PIN-related safety validation unchanged.

## 0.9.11
- Add a 30-second passive MQTT observation window during candidate validation.
- Disable the active `RS` diagnostic request for this test.
- Observe only the already-authorized `wbt01Tx` and `position` topics plus normal shadow topics.
- Count observed messages without logging raw payloads in the new passive diagnostic lines.
- Intended test: start setup, then operate the same gate once from the official EyeOpen app during the observation window.
- Keep all existing protocol and safety validation unchanged.

## 0.9.10
- Add a single read-only `RS` system-status diagnostic after the default AWS IoT shadow has returned `404`.
- Match the official EyeOpen WBT01 command format: `c=RS;src=<source_id>` on `<thing>/wbt01Rx`, with the response expected on `<thing>/wbt01Tx`.
- Record only whether an `ACK RS:` response was received, whether its hexadecimal status format is valid, and the byte count; the raw status payload is not logged by the new diagnostic.
- Do not use an `ACK RS` response to bypass `DEV INFO` / `DEV STATUS` protocol validation or PIN verification.
- No OPEN, CLOSE, STOP, PED or other movement command is sent by this diagnostic.
- Retain the stable MQTT subscription behavior restored in 0.9.9.

## 0.9.9
- Remove the broad MQTT wildcard subscriptions introduced in 0.9.8 after community testing showed they could disrupt the AWS IoT session before normal shadow validation completed.
- Restore the known-good 0.9.7 MQTT subscription behavior.
- Add privacy-safe diagnostics comparing the user-certificate AWS IoT endpoint with the endpoint hard-coded by the official EyeOpen WBT01 client.
- Log only boolean comparison results and the AWS region label; raw endpoints, certificates and credentials are not logged.
- Keep certificate provisioning, policy attachment, Thing UUID selection and `DEV INFO` / `DEV STATUS` safety validation unchanged.
- Diagnostic release for investigating persistent default-shadow `404` responses on some PS20088 accounts.

## 0.9.8
- Add passive MQTT topic diagnostics for devices whose default AWS IoT shadow consistently returns `404`.
- Subscribe to the existing thing-scoped MQTT namespace and named-shadow update namespace without sending gate movement commands.
- Record only topic categories, counts, SUBACK results, and short non-reversible fingerprints for unknown topic suffixes.
- Never log payloads from newly observed topics; command-ack payload logging is also removed.
- Keep `DEV INFO` / `DEV STATUS` shadow validation unchanged. Passive topic activity does not enable gate control by itself.
- Diagnostic release intended to determine whether affected controllers report state outside the default AWS IoT shadow.

## 0.9.7
- Add privacy-safe discovery diagnostics for possible alternate AWS IoT Thing identifiers.
- Fingerprint only a conservative allow-list of identifier-like backend fields such as Thing/client/device IDs; raw values are never logged.
- Log whether each candidate identifier fingerprint matches the UUID currently used as the AWS Thing name.
- Include the same privacy-safe checks for nested `devies_info` records used by shared devices.
- Keep the current UUID-based Thing selection and all gate-control safety validation unchanged.
- Diagnostic release for investigating PS20088 accounts where MQTT connects successfully but the default shadow GET returns HTTP-style AWS code 404.

## 0.9.6
- Wait for AWS IoT subscription acknowledgements for both shadow GET response topics before sending the initial shadow request.
- Retry unanswered shadow GET requests within the existing 12-second passive validation window.
- Add privacy-safe logging for MQTT subscription requests, SUBACK outcomes, shadow GET attempts and validation timeouts.
- Preserve all existing gate movement commands, PIN handling and post-provisioning safety validation.
- Diagnostic/reliability release: does not guarantee compatibility for devices that never expose the required DEV INFO / DEV STATUS shadow fields.

## Previous releases
See the repository history for earlier release notes.
