# Translation provider v0.2.1 — component verification

Exact image: `ghcr.io/sapogov1978/aelev-translation-provider@sha256:9d1929bbf30c510f902b3ff2a80a905025ffe42ec915102d316385c02a9bcd9a`.
Source: `846381021f53421d6046d8622c2b12e61277ffd7`.

All 20 new opaque translations passed literal checks and a separate review of
every actual source/output pair. The counts regression now preserves the two
numbers without adding a subset. Prompt v2 is digest-pinned; the model and wire
contract are unchanged. [v0.2.0 remains quality-rejected](provider-release-v0.2.0-20261113.json).
This is a bounded synthetic translation corpus, not research-platform E2E.

The exact arm64 provider served HTTPS/mTLS over a published endpoint to the
actual candidate worker on a distinct network, using separate TLS volumes and
keys. A same-CA foreign client was rejected. The worker image is still an
unreleased candidate; a signed new worker pair and permanent SPIRE deployment
remain open. Ephemeral test PKI and one physical host do not admit a site.

The first preparation attempt failed during a Docker inspection before any
translation. Its original intent flag, zero actual inference, missing command
diagnostic and cleanup are preserved in the machine record. The poll now reads
initial State safely. The successful run made exactly 20 requests with no
translation retries. The source also passed 77 tests on native arm64 Python 3.13.7.

Cosign verified the exact tag workflow and GitHub OIDC issuer. For amd64 and
arm64, signed manifest links bind the per-platform SPDX SBOM and SLSA source.
Both native images passed the restricted security gate. Each raw scan retains
1 CRITICAL and 35 HIGH package findings; all individual applicability conditions
remain mandatory. No claim of generally patched OS packages is made.

Source [audit](https://github.com/sapogov1978/AELEV-translation-provider/actions/runs/43435695551)
and [release](https://github.com/sapogov1978/AELEV-translation-provider/actions/runs/43436191745) passed.
[Machine evidence](provider-release-v0.2.1-20261113.json) retains source/output hashes,
raw paths, discrepancies and remaining gates. Raw exchanges and credentials are
not committed. Existing AELEV runtimes were not switched and no RESUME was sent.
The baseline comparison retains a restart-counter change in an unrelated
pre-existing workload; it is not presented as a completely unchanged host.
