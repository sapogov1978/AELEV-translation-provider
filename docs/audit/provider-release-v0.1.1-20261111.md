# Translation provider v0.1.1 — exact-release component verification

Image: `ghcr.io/sapogov1978/aelev-translation-provider@sha256:97d7604113008b93781061a0bbba2404bcd7769b864e3ade268b71a483e4f70a`.
Source: `185c5a7b5ad7bdce24a6f5dc5dba18f1eeaa62d1`.

The exact native arm64 image passed 20 bounded live API cases. Codex
separately reviewed every actual output against the supplied material and
expected meaning. Twenty repository-owned synthetic translation segments; all actual source/output pairs reviewed separately against expected meanings. Not an independent linguistic benchmark or all-language admission.

The [machine report](provider-release-v0.1.1-20261111.json) binds the frozen corpus, complete opaque
request/response hashes, native image, security scans and supply-chain receipts.
Raw exchanges remain outside Git at `/var/tmp/aelev-production-admission.wDuzQd/translation-v011/raw.json`.

Cosign verified the exact tag workflow identity and GitHub OIDC issuer. Both
amd64 and arm64 have SPDX SBOMs and SLSA provenance matching the source above.
Source audit [42924973947](https://github.com/sapogov1978/AELEV-translation-provider/actions/runs/42924973947)
and release [42925405066](https://github.com/sapogov1978/AELEV-translation-provider/actions/runs/42925405066) passed.

Both native architectures passed the [scoped security review](runtime-security-20261111.md).
Each raw scan retains **1 CRITICAL and 35 HIGH** package findings. Individual
applicability decisions admit only the reviewed default opaque entrypoint with
UID 10001, read-only root, no effective capabilities, no-new-privileges and an
empty fstab. This is not a claim that those OS packages are patched. The owner
must verify the same profile at deployment; an unknown HIGH/CRITICAL blocks.

All 20 source/output pairs preserve their reviewed meanings, including
negation, conditions, uncertainty, context, numbers, identifiers, placeholders,
list order and line breaks. The worker pairing also passed a separate
networkless UDS probe with exact worker digest
`ghcr.io/sapogov1978/aelev-platform-infrastructure-translator-worker@sha256:d68d70243a6746cbe9dbdd537b2d773f701c9cd44daabbeac78d88a0e6fa98a5`.
That probe issued no inference; the 20 translations were a separate live run.
The original runner encountered an asynchronous auto-removal race during test
volume cleanup after all calls passed. The container was confirmed absent,
the labelled unreferenced volume was removed, and a cleanup receipt was saved.
No API request was repeated for this correction.

Full Infrastructure clean-room, deployed Translator recovery and deployment-site
admission remain separate gates. No working queue or RESUME was touched.
