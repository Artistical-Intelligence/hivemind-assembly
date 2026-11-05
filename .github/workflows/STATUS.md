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
CHECKS PENDING: chatmode-native-events.yml — bounded no-model-API workflow runs five focused native event, watchdog, ingress and browser-message contract suites with retained JUnit artifact. Latest Actions run 42095932643 passed (13 tests), but independent workflow security/pinning review, actual authenticated browser/service acceptance and full HA contracts remain pending.
CHECKS PENDING: chatmode-native-events.yml — focused no-model-API workflow at run 42099862699 passed 20 tests, including seven GitHub MCP inline-resource contracts. Full HA contracts, independent workflow/source review and external hosted permission UI remain unverified.
CHECKS PENDING: ha-core-effects.yml — isolated no-model-API core durable-effect test workflow; Actions run 42102912620 passed four tests. Independent CI source/pinning review, global HA acceptance and release gate remain pending.
