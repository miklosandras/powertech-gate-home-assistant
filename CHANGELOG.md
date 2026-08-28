# Changelog

## 0.9.0
- First public release.
- Confirmed on Powertech PS20088 / PS20088D reference hardware.
- Automatic Powertech/EyeOpen account onboarding.
- EyeOpen-compatible six-digit gate PIN verification without persisting the PIN.
- AWS IoT provisioning and read-only protocol validation.
- Main gate open/close/stop and pedestrian open/close.
- Live position, availability handling and automatic reconnect.
- Security/privacy hardened logging and diagnostics.
- Hungarian and English translations.


## 0.9.0 RC9
- Final public-release documentation cleanup.
- Removed vendor logo artwork from the repository to avoid redistributing third-party brand assets.
- README now reflects the tested RC8/RC9 behavior, including PIN verification and pedestrian ACK state handling.
- Documented the static OAuth application authorization as public mobile-client metadata, not a per-user credential.
- Added an explicit trademark/non-affiliation notice.
- No runtime protocol changes from RC8.


## 0.9.0 RC8
- Security/privacy hardening audit before public release.
- Replaced raw/partial device UUIDs in debug logs with one-way SHA-256 fingerprints.
- Removed AWS IoT endpoint from normal connection logs.
- Movement TX logs now show only the command, not the MQTT source identifier.
- Backend HTTP response bodies are no longer propagated into exceptions/logs.
- Shadow rejection and invalid-position logs no longer include arbitrary device payloads.
- Credential directories are chmod 0700; certificate/private-key files remain chmod 0600.
- Expanded diagnostics redaction defensively for conventional credential field names.
- No user password, gate PIN, access/refresh token, certificate PEM, or private key is intentionally logged or included in diagnostics.


## 0.9.0 RC7
- Added EyeOpen-compatible six-digit gate PIN verification to automatic setup.
- PIN is decoded transiently from the `WBT PIN` shadow field and compared only in memory.
- The entered PIN is never stored, logged or included in diagnostics.
- Reconfigure also requires PIN verification when the device exposes `WBT PIN`.
- Experimental models without a decodable WBT PIN can still be configured; diagnostics record `pin_verified: false`.
- Added only the non-sensitive boolean `pin_verified` diagnostic flag.
- Fixed a legacy manual-setup schema regression and genericized its fallback title.


## 0.9.0 RC6
- Fixed Pedestrian gate close action staying disabled after a successful `PED OPEN`.
- Pedestrian cover state now prefers explicit `ACK PED OPEN` / `ACK PED CLOSE` responses.
- `ACK FULL CLOSE` also marks the pedestrian cover closed.
- No protocol or movement command changes; `PED CLOSE` remains the verified close command.
- This handles PS20088D hardware that may not publish an immediate follow-up `ACK RS` after pedestrian movement.


## 0.9.0 RC5
- GitHub/HACS release cleanup.
- Added HACS and Hassfest GitHub Actions validation workflows.
- Added Python 3.14 syntax validation workflow.
- Added dedicated bug-report and new-model compatibility issue templates.
- Added CONTRIBUTING.md and a first-release checklist.
- Reworked README into a public-facing installation, compatibility, diagnostics, troubleshooting and security guide.
- Raised declared HACS minimum Home Assistant version to 2026.3 because local custom-integration brand assets are used.
- Added `codeowners` manifest key; maintainer username still needs to be filled before public release.
- Removed legacy `strings.json`; custom integration translations are shipped directly in `translations/en.json` and `translations/hu.json`.
- Existing RC4 discovery, provisioning, passive shadow validation and gate behavior are unchanged.


## 0.9.0 RC4
- Renamed discovery logging from `compatible_devices` to `candidate_devices`.
- Added passive post-provisioning protocol validation.
- A candidate must return both `DEV INFO` and `DEV STATUS` in its AWS IoT shadow before automatic gate control is enabled.
- Validation performs only a shadow GET; it never sends OPEN/CLOSE/STOP/PED commands.
- Unknown models can pass validation if they use the confirmed Powertech AWS/WBT shadow schema.
- Added `protocol_validated` to privacy-safe diagnostics.
- Reconfigure now uses Home Assistant's non-reloading update-and-abort flow to avoid the 2026 config-entry reload/listener race.


## 0.9.0 RC3
- Capability-based discovery now uses stable UUID + AWS IoT endpoint instead of a literal WBT01 name.
- Added a model capability registry.
- PS20088 / PS20088D remain the confirmed reference family.
- Pedestrian gate is enabled automatically only for confirmed models.
- Other Powertech AWS/WBT models are treated as experimental main-gate devices.
- Diagnostics report experimental-model and pedestrian-support flags.


## 0.9.0 RC2
- Added privacy-safe debug logging for Powertech account device discovery.
- Logs `admin_devices`, `user_devices`, and `share_devices` metadata.
- Logs field names plus non-secret compatibility hints such as UUID type, device type, product type, endpoint presence and Bluetooth-MAC presence.
- Does not log passwords, access/refresh tokens, PIN codes, certificates or private keys.
- Intended to collect real model metadata before enabling broader automatic model support.


## 0.9.0 RC1
- Started broader Powertech gate support beyond a literal `WBT01` device-type check.
- Device discovery is prepared to accept Powertech gates that expose the AWS/WBT transport metadata required by this integration.
- Existing WBT01/PW200 behavior is preserved.
- Availability/reconnect behavior from 0.8.4 RC is preserved.
- This is the first multi-model compatibility RC; unknown models should be validated before being advertised as supported.


## 0.8.4 RC
- Fixed Gate and Pedestrian gate being permanently unavailable after setup/reconnect.
- Cover availability now follows the live MQTT connection exactly, matching the IP and Wi-Fi MAC diagnostic sensors.
- Removed the extra dependency on the shadow's `Connected` field, which can remain stale after a reconnect.


## 0.8.3 RC
- Fixed cover availability handling.
- Main Gate and Pedestrian gate now become unavailable when the live MQTT connection is lost.
- Cover availability also respects the device's reported online state.
- Covers automatically return when MQTT/device connectivity is restored.
- IP address and Wi-Fi MAC availability behavior is unchanged.


## 0.8.2 RC
- Hardened Home Assistant diagnostics privacy.
- Redacts endpoint, source ID, Thing UUID, IP address, Wi-Fi MAC, raw status, and certificate/key paths.
- Keeps model, firmware, UART version, position, online status, and MQTT health.
- Added documentation and issue-tracker manifest placeholders for the future GitHub repository.


## 0.8.1
- Fixed a v0.8.0 setup crash caused by an accidental third argument passed to `dict.get()` while reading the command source ID.
- Enlarged/tightened the Powertech brand icon using the official high-resolution artwork.
- Reduced excess whitespace around the integration logo.


## 0.8.0
- Breaking change: integration domain renamed from `powertech_pw200` to `powertech_gate`.
- Clean install required from pre-0.8.0 versions.
- Added reconfigure flow for regenerating account/AWS IoT credentials.
- Added options flow for shadow refresh interval and future debug behavior.
- Added periodic shadow refresh while MQTT is connected.
- Improved unavailable/reconnect handling.
- Extended safe diagnostics with MQTT connection health.
- Kept automatic Powertech/EyeOpen account onboarding.
- Kept branding, dynamic device names, firmware, MAC, IP and pedestrian cover.


## 0.7.1
- Fixed startup failure caused by device-registry metadata refresh.
- Added compatibility with both older and 2026.8+ Home Assistant device lookup APIs.
- Device-registry metadata failures no longer abort integration setup.
- Fixed Wi-Fi MAC diagnostic sensor after the shared helper refactor.
- Prevented the failed setup/retry cycle that caused "platform has already been setup" errors.

## 0.7.0
- Added runtime device-registry metadata updates.
- Firmware version and Wi-Fi MAC now populate after the first AWS shadow update.
- Added device serial/Thing UUID and official Powertech configuration URL.
- Added safe Home Assistant diagnostics.
- Added public GitHub/HACS repository files.
- Kept the existing `powertech_gate` domain for upgrade compatibility.

## 0.6.0
- Generic Powertech Gate (EyeOpen) naming.
- Automatic account onboarding and AWS IoT provisioning.
- Dynamic EyeOpen device name and model detection.
- HACS repository skeleton.

## 0.5.2
- Fixed Powertech `PrivateKey` certificate response parsing.

## 0.5.1
- Fixed EyeOpen `app_type_index` to 2.

