# Contributing

Contributions and compatibility reports are welcome.

## Before opening an issue

1. Update to the latest release/RC.
2. Restart Home Assistant.
3. Download Home Assistant diagnostics for the integration.
4. If debug logging is needed, redact all secrets before posting.

## Security

Never publish:
- Powertech/EyeOpen passwords
- access or refresh tokens
- AWS IoT private keys or client certificates
- Android keystores
- unredacted Home Assistant backups

## New Powertech models

The integration intentionally separates **candidate discovery** from
**validated protocol support**.

A candidate needs a stable UUID and AWS IoT endpoint. Automatic setup then
performs a read-only shadow validation and requires `DEV INFO` and `DEV STATUS`.
Unknown models remain experimental until their command/status behavior is
confirmed.

Please use the **New model compatibility** issue template.
