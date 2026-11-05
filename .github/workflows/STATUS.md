CHECKS PENDING: online-installer.yml — independent workflow review; owner-authorized beta packaging addition only. Requires compiled failure/recovery tests and real installation, preserves all offline assets, and cannot publish stable or move the beta tag.
CHECKS PENDING: source-snapshot.yml — source-archive workflow review.
CHECKS PENDING: integration-inputs.yml — pinned donor preservation review.
CHECKS PENDING: owned-components.yml — source build and offline artifact retention review.
CHECKS PENDING: platform-components.yml — offline native runtime package review.
CHECKS PENDING: internal-execution.yml — compiled-helper build, process lifecycle tests and recovery-archive review.
CHECKS PENDING: integration-acceptance.yml — cross-target linker prerequisites and Windows/Linux regression evidence review.
CHECKS PENDING: offline-acceptance.yml — complete local payload, isolated CI firewall lifecycle, real setup checks and evidence retention; independent source review.
CHECKS PENDING: offline-recheck.yml — reuse exact preserved component artifacts, network-blocked fresh installation and separate lightweight diagnostics; independent source review.
CHECKS PENDING: owned-runtime-recheck.yml — current HA clients against exact native helper artifacts on Windows and Linux; independent source review.
CHECKS PENDING: beta-release.yml — independent workflow review; this is the owner's expressly authorized testing-prerelease path, not stable approval. Requires preserved-source identity, passing packaging tests, actual offline installation and user-data survival before publication. Existing releases are not overwritten.
CHECKS PENDING: chatmode-native-events.yml — new bounded GitHub Actions no-model-API workflow runs four focused native event/watchdog/ingress suites, retaining JUnit artifact. Actions run 42095047614 passed (12 tests), but workflow security, pinning, source-review and full existing HA contracts still pending.
