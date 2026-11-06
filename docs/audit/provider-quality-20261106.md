# Provider quality evidence — 2026-11-06

## Result

- **Status:** `PASS`
- **Exact image:**
  `ghcr.io/sapogov1978/aelev-translation-provider@sha256:4a820a13e6a03188589c09d14e52b5f2d05e9359d7df847bad768966016e9ec9`
- **Workflow:**
  [quality-smoke-provider-release run 42257002684](https://github.com/sapogov1978/AELEV-translation-provider/actions/runs/42257002684)
- **Artifact:** `provider-quality-evidence`, artifact ID `13523991236`
- **Cases:** 20 passed of 20
- **Elapsed inference:** 263.955 seconds

## Bound evidence

| Input | SHA-256 |
|---|---|
| Approved synthetic corpus | `48947913efd9236e38fd79dbfb60b48198fdd9ab0ce1483fc003485619d92b6e` |
| Historical exact baseline | `42a370463ae2109933ad389fc517056a4dae759971d6c4c23db9029e5c98f488` |
| Reviewed release alternates | `36a4d9ddc7c35550f7bde89caf45021d8fa8c93830d313fae97c2726209faaf7` |

Eighteen responses matched the historical baseline byte-for-byte. Two matched
only the exact release-specific alternatives in
[`quality/approved-alternates.json`](../../quality/approved-alternates.json):
`en-zh` used an equivalent modal verb for recoverability and `ru-en-context`
added `any` under the same explicit negation. Both preserved every stated
condition; their rationales are part of the digest-bound reviewed file.

All corpus literal checks passed. The provider ran read-only, without Linux
capabilities, with `no-new-privileges`, 2 CPU and 8 GiB memory. The workflow
pulled the immutable private image, waited for its image-owned healthcheck,
used only the opaque UDS v1 port, uploaded evidence containing case IDs, output
hashes, durations and warnings, and completed bounded container cleanup.

## Admission boundary

This closes the provider release quality gate for the exact Linux amd64 digest.
It does not admit another digest or architecture and does not replace the joint
Platform Infrastructure clean-room gate.
