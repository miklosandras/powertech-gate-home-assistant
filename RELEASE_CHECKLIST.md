# Release checklist

## Already validated on reference hardware

- [x] Automatic account setup
- [x] Six-digit PIN verification: wrong PIN rejected
- [x] Six-digit PIN verification: correct PIN accepted
- [x] Reconfigure
- [x] Main gate open / close / stop
- [x] Pedestrian open / close
- [x] Live position
- [x] Offline -> unavailable -> automatic reconnect
- [x] Sensitive-value audit of packaged source
- [x] Python syntax compilation

## Required before first public GitHub release

- [ ] Create the public GitHub repository.
- [x] Repository URLs set to `miklosandras/powertech-gate-home-assistant`.
- [x] `@miklosandras` added to `manifest.json` `codeowners`.
- [ ] Enable GitHub Issues.
- [ ] Add repository description.
- [ ] Add topics such as `home-assistant`, `hacs`, `powertech`, `eyeopen`, `gate`.
- [ ] Push the repository and verify the Hassfest workflow passes.
- [ ] Verify the HACS validation workflow passes.
- [ ] Download Home Assistant diagnostics once more and manually verify redaction.
- [ ] Test installation from the GitHub/HACS repository on a clean Home Assistant instance.
- [ ] Create a GitHub **Release** (not only a tag).
- [ ] Use a SemVer-compatible release tag matching `manifest.json`.
- [ ] Optionally apply for inclusion in the HACS default repository after the project is stable.

## Recommended

- [x] Promoted the tested release candidate to `0.9.0`.
- [ ] Add screenshots with all account/device identifiers redacted.
- [ ] Do not add vendor-owned logo artwork unless permission is available.
