# Security

Please do not publish or attach any of the following in GitHub issues:

- Powertech/EyeOpen passwords
- gate PIN codes
- access tokens
- refresh tokens
- AWS IoT private keys
- AWS IoT client certificates
- exported Android keystores
- unredacted Home Assistant backups

Use Home Assistant's generated diagnostics file whenever possible. The
integration redacts the primary identifiers, credentials, certificate paths,
network identifiers and raw device status used during troubleshooting.

If you discover a vulnerability that could expose credentials or allow
unauthorized gate control, do not open a public issue. Contact the repository
maintainer privately. The private reporting address/process should be filled
in before the first public release.


## Logging and diagnostics hardening

Public-release builds avoid placing account/device secrets or raw primary
identifiers in normal logs. Device identifiers used for troubleshooting are
represented by short one-way SHA-256 fingerprints. Backend HTTP response
bodies are not propagated into Home Assistant exceptions because their
contents are outside the integration's control.

AWS IoT private-key and certificate files are stored under a 0700 credential
directory; both files are set to 0600 where the host platform permits it.


## Public mobile-client authorization

The automatic onboarding implementation contains the static OAuth application
authorization value used by the official Android public client. It is not a
user credential and does not grant access to a Powertech account by itself.
User passwords, access tokens, refresh tokens and gate PINs must never be
committed to the repository.

Because this relies on an undocumented vendor API, the vendor may change or
revoke the client authorization or protocol at any time.
