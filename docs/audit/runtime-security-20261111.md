# Scoped provider security review — 2026-11-11

The [machine report](runtime-security-20261111.json) records a pre-release native
arm64 evaluation of the reviewed provider source. All 36 HIGH/CRITICAL package
findings have individual applicability decisions under the profile below.
The raw Trivy report retains 1 CRITICAL and 35 HIGH findings; no upstream
package is relabelled as fixed. Final signed-image verification remains open.

The admitted scope is the default opaque Python provider entrypoint, using
UID 10001, read-only root, no effective capabilities, no-new-privileges and
an empty fstab. It excludes general-purpose interactive OS utility execution.
The functional owner must preserve and verify those conditions at deployment.

| Finding | Verified applicability condition |
|---|---|
| [MiniZip CVE-2023-45853](https://security-tracker.debian.org/tracker/CVE-2023-45853) | Affected library, Python binding and libz MiniZip export are absent |
| [systemd-homed CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | Affected service executable is absent |
| [Archive::Tar CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | Affected Perl module is absent |
| [mount CVE-2026-53613](https://security-tracker.debian.org/tracker/CVE-2026-53613), [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | No fstab authorization or privileged mount execution path in the verified profile |
| [libblkid CVE-2026-53615](https://security-tracker.debian.org/tracker/CVE-2026-53615) | No block-metadata parser path, loaded libblkid, native blkid imports or application native/process invocation APIs |
| [GNU gzip CVE-2026-41992](https://security-tracker.debian.org/tracker/CVE-2026-41992) | Affected LZW/LZH CLI is not executed; Python HTTP gzip decoding is a different path |
| [infocmp CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | Affected command-line program is not executed by the provider |
| [libacl CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | No privileged ACL caller, loaded libacl or affected native imports |
| [zlib CVE-2026-76844](https://security-tracker.debian.org/tracker/CVE-2026-76844), [CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091) | No gz* file-write API execution path; native imports and reviewed application APIs are checked independently of the disputed version range |

[runtime-profile.json](../../security/runtime-profile.json) binds the manually
reviewed application, locked dependency set, provider configuration and gate
code by SHA-256. The probe checks actual installed versions, imports engine
definitions without reading a key or invoking inference, inspects native ELF
imports and records native binary hashes. Source checks support this concrete
review; they are not a general proof for arbitrary future Python programs.

Unknown HIGH/CRITICAL findings, a different package/type, missing inventory,
wrong image ID, changed reviewed files/dependencies or missing controls fail
admission. Raw findings and individual decisions remain in the output.
Eleven tests cover those failure boundaries. A passing source CI is required
for the exact release commit. Release CI scans the published native amd64
image and runs this gate before signing it; raw scan and decisions are retained.

Run against a fresh complete scan and immutable image reference:

```sh
python tools/runtime_surface_probe.py --image ghcr.io/OWNER/IMAGE@sha256:DIGEST --scan /var/tmp/vulnerabilities.json --output /var/tmp/security.json
```

Use fresh evidence paths. This component review does not establish live API
quality, permanent identities, functional-owner admission or platform E2E.
