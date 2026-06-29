# Changelog

## [0.3.0](https://github.com/jeverley/napoleon-home-ha/compare/v0.2.3...v0.3.0) (2026-06-29)


### ⚠ BREAKING CHANGES

* domain changed from napoleon_bbq to napoleon_home

### Features

* **napoleon_home:** resolve connectivity issues, overhaul entities, naming, icons, and tank calibration ([3f33d7e](https://github.com/jeverley/napoleon-home-ha/commit/3f33d7e195dbbd4fccee4e179ff4e1f7d3e540a1))
* rebrand integration from Napoleon BBQ to Napoleon Home ([ca4149e](https://github.com/jeverley/napoleon-home-ha/commit/ca4149e3a73d53486bbf22da473fe67ad904e436))
* replace backlight switch+select with light entity; rename battery saver ([7d28520](https://github.com/jeverley/napoleon-home-ha/commit/7d285202a05c82d2679332ecfc5ac37ff917f062))


### Bug Fixes

* **ble:** pair before subscribing to establish encrypted link ([12c92b3](https://github.com/jeverley/napoleon-home-ha/commit/12c92b3cdcd804c2aac26025e2fafe8623a45b31))
* **ble:** treat pair() failure as non-fatal warning ([443d782](https://github.com/jeverley/napoleon-home-ha/commit/443d78230a31b60dc719a6a1dec654635355fa23))
* **devcontainer:** make Claude persistence resilient across rebuilds ([1f85144](https://github.com/jeverley/napoleon-home-ha/commit/1f851448080b3f86872268cb3f1e6ade46706a6a))
* migrate to establish_connection, tighten BLE lifecycle ([6f3caa5](https://github.com/jeverley/napoleon-home-ha/commit/6f3caa582c3e3ac7417276102081bc2b92f81389))
* revert zip_release — HACS downloads from source tarball by default ([b14940d](https://github.com/jeverley/napoleon-home-ha/commit/b14940d979d08aab7ceb7ae16eef34b19a90a76d))
* set zip_release and filename in hacs.json for HACS 2.0 download ([d9b4e4a](https://github.com/jeverley/napoleon-home-ha/commit/d9b4e4a6b1cf582ee05be9ee8395feceb8ccc338))
* update .prettierignore for napoleon_home domain rename ([cf70972](https://github.com/jeverley/napoleon-home-ha/commit/cf7097251e7070d8335a57d0c610ea3d14a43299))
* update repo URLs to napoleon-home-ha after rename ([fca854a](https://github.com/jeverley/napoleon-home-ha/commit/fca854ad90c509daac6ab851c71aeb42b04dcd3e))

## [0.2.3](https://github.com/jeverley/napoleon-home-ha/compare/v0.2.2...v0.2.3) (2026-06-25)


### Bug Fixes

* **ble:** treat pair() failure as non-fatal warning ([443d782](https://github.com/jeverley/napoleon-home-ha/commit/443d78230a31b60dc719a6a1dec654635355fa23))

## [0.2.2](https://github.com/jeverley/napoleon-home-ha/compare/v0.2.1...v0.2.2) (2026-06-25)


### Bug Fixes

* **ble:** pair before subscribing to establish encrypted link ([12c92b3](https://github.com/jeverley/napoleon-home-ha/commit/12c92b3cdcd804c2aac26025e2fafe8623a45b31))

## [0.2.1](https://github.com/jeverley/napoleon-home-ha/compare/v0.2.0...v0.2.1) (2026-06-24)


### Bug Fixes

* update repo URLs to napoleon-home-ha after rename ([fca854a](https://github.com/jeverley/napoleon-home-ha/commit/fca854ad90c509daac6ab851c71aeb42b04dcd3e))

## [0.2.0](https://github.com/jeverley/napoleon-bbq-ha/compare/v0.1.3...v0.2.0) (2026-06-24)


### ⚠ BREAKING CHANGES

* domain changed from napoleon_bbq to napoleon_home

### Features

* rebrand integration from Napoleon BBQ to Napoleon Home ([ca4149e](https://github.com/jeverley/napoleon-bbq-ha/commit/ca4149e3a73d53486bbf22da473fe67ad904e436))


### Bug Fixes

* **devcontainer:** make Claude persistence resilient across rebuilds ([1f85144](https://github.com/jeverley/napoleon-bbq-ha/commit/1f851448080b3f86872268cb3f1e6ade46706a6a))
* update .prettierignore for napoleon_home domain rename ([cf70972](https://github.com/jeverley/napoleon-bbq-ha/commit/cf7097251e7070d8335a57d0c610ea3d14a43299))

## [0.1.3](https://github.com/jeverley/napoleon-bbq-ha/compare/v0.1.2...v0.1.3) (2026-06-24)


### Features

* replace backlight switch+select with light entity; rename battery saver ([7d28520](https://github.com/jeverley/napoleon-bbq-ha/commit/7d285202a05c82d2679332ecfc5ac37ff917f062))

## [0.1.2](https://github.com/jeverley/napoleon-bbq-ha/compare/v0.1.1...v0.1.2) (2026-06-24)


### Bug Fixes

* migrate to establish_connection, tighten BLE lifecycle ([6f3caa5](https://github.com/jeverley/napoleon-bbq-ha/commit/6f3caa582c3e3ac7417276102081bc2b92f81389))

## [0.1.1](https://github.com/jeverley/napoleon-bbq-ha/compare/v0.1.0...v0.1.1) (2026-06-23)


### Bug Fixes

* revert zip_release — HACS downloads from source tarball by default ([b14940d](https://github.com/jeverley/napoleon-bbq-ha/commit/b14940d979d08aab7ceb7ae16eef34b19a90a76d))
