# Translation provider v0.1.0 quality admission — 2026-11-10

The tagged release image
`ghcr.io/sapogov1978/aelev-translation-provider@sha256:e1c7ea57dadaa322bd91104a0908f7edcd371552aab776e9469714b4b670641c`
passed the bounded 20-case opaque UDS evaluation. Its source is tag `v0.1.0`,
commit `2e90c2f62de4bcc5be78f37413b5a8c9cc097285`.

All 20 actual response texts were separately reviewed against the original
segments and expected meanings. Negation, uncertainty, conditions, numbers,
units, identifiers, placeholders, list order and line breaks were preserved.
The lock/castle and factory/power-plant examples retained their supplied
context; the central-bank examples added no country. This is a bounded Codex
review of the supplied corpus, not an independent linguistic benchmark or
admission of every language supported by the implementation.

The automation passed 20/20 contract, warning and literal checks in 55.652
seconds. Every raw output SHA-256 was reconciled with the machine report.
The exact native arm64 image, healthy provider and isolated UDS client were
recorded by Docker inspection. The client had no network or provider secret.

Source audit [42839546330](https://github.com/sapogov1978/AELEV-translation-provider/actions/runs/42839546330)
and release [42840698695](https://github.com/sapogov1978/AELEV-translation-provider/actions/runs/42840698695)
passed. Cosign verified the exact image against issuer
`https://token.actions.githubusercontent.com` and identity
`https://github.com/sapogov1978/AELEV-translation-provider/.github/workflows/release.yml@refs/tags/v0.1.0`.
Both `linux/amd64` and `linux/arm64` have SLSA provenance and SPDX SBOM;
the attested source revision matches the release tag.

[Machine evidence](provider-release-v0.1.0-20261110.json) binds the image,
source, corpus, raw exchanges, runtime inspection and supply-chain receipts.
Raw exchanges remain outside Git at
`/var/tmp/aelev-production-admission.wDuzQd/translation-v010/raw.json`.
The earlier [evaluation](provider-quality-20261110.md) remains evidence for
its separately identified image; its results were not relabelled as this run.

Result: `PROVIDER_QUALITY_PASS / PLATFORM_CLEAN_ROOM_PENDING`. Exact Translator
worker pairing, joint infrastructure clean-room and recovery remain gates for
the infrastructure stage. This provider evaluation issued no queue command or
`RESUME`, and test resources were removed after the run.
