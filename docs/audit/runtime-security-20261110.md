# Runtime security admission — 2026-11-10

Production admission remains blocked. The [machine report](runtime-security-20261110.json)
binds the released candidate, local diagnostic runtime, source-file hashes,
Trivy scan/SBOM and the networkless runtime proof. This is native arm64
evidence; it does not close final amd64 admission or attest a new signed image.

The released candidate had 2 CRITICAL and 49 HIGH package findings under
Trivy 0.76.1 with its November 10 database. The local runtime correction:

- Keeps Python 3.13.7, Debian Bookworm, application locks, prompts and API model.
- Copies only the locked application environment instead of inheriting Poetry.
- Removes global and virtualenv installers and the unused SQLite library.
- Refreshes OS security updates during release builds.
- Proves the runtime footprint with [runtime_surface_probe.py](../../tools/runtime_surface_probe.py),
  using both Python interpreters without a network or mounted credentials.

The local raw scan now has 1 CRITICAL and 35 HIGH findings, with no HIGH or
CRITICAL Python-package findings. It is still recorded as BLOCKED.

Two source-package findings have concrete non-applicability evidence:

- CVE-2023-45853 concerns MiniZip. The runtime proof finds no MiniZip library,
  pyminizip module or vulnerable MiniZip export in libz. Debian explicitly
  states that the affected contrib code is not built into the installed
  Bookworm zlib binary: [Debian assessment](https://security-tracker.debian.org/tracker/CVE-2023-45853).
- CVE-2026-16742 concerns systemd-homed. Its executable is absent; installed
  libsystemd/udev libraries do not provide that service:
  [Debian description](https://security-tracker.debian.org/tracker/CVE-2026-16742).

After those exact-runtime applicability assessments, 33 HIGH package findings
remain open. They require individual evidence or compatible fixes; there is no
blanket unfixed-package exclusion. The existing raw scanner gate is preserved.

The earlier [quality evaluation](provider-release-v0.1.0-20261110.md) applies to its exact old image.
A final hardened image still needs signed publication, both-platform security
evidence, exact-image quality verification and functional-owner integration.
No queue state, credentials, canonical storage or running production container
was changed by these diagnostic checks.

To reproduce footprint evidence after building the runtime, obtain its immutable
image ID with Docker inspect and run:

```sh
python tools/runtime_surface_probe.py --image sha256:IMAGE_ID --output /var/tmp/runtime-surface.json
```

Use a fresh output path. The tool refuses mutable image references and does not
turn footprint success into complete vulnerability admission.
