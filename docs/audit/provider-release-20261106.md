# Provider release evidence — 2026-11-06

## Result

- **Status:** `PASS`
- **Source commit:** `9f7074705e58187e2db99aeb77f24d765b244195`
- **Platform:** Linux x86_64 / `ubuntu-24.04`
- **Workflow:**
  [release-provider-image run 42248923795](https://github.com/sapogov1978/AELEV-translation-provider/actions/runs/42248923795)
- **Immutable image:**
  `ghcr.io/sapogov1978/aelev-translation-provider@sha256:4a820a13e6a03188589c09d14e52b5f2d05e9359d7df847bad768966016e9ec9`

## Executed evidence

The GitHub-hosted runner confirmed `x86_64`. The verified model downloader
completed size and SHA-256 validation. Buildx published the Linux amd64 image,
generated an SBOM and `mode=max` provenance, and returned the digest above.
Cosign generated an ephemeral key through GitHub OIDC and pushed the signature
for the exact digest. The same immutable reference was stored in the
`release-digest-9f7074705e58187e2db99aeb77f24d765b244195` workflow artifact.

The first hosted attempt failed closed because the stock runner exposed only
17 GiB free. The accepted workflow removes only unused preinstalled SDKs from
the disposable VM, exposing 39 GiB before the build; the second run completed
without a self-hosted runner.

## Admission boundary

This evidence closes image construction, publication, SBOM/provenance and
signature gates. It does not close bounded real-model translation quality or
the joint Platform Infrastructure clean-room gate; those remain explicit in
[TASKS.md](../../TASKS.md).
