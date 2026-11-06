# Repository Instructions

Read README.md, SPEC.md, USER_MANUAL.md, applicable accepted ADRs, the opaque
contract and provider.lock.json before edits. This repository owns translation
implementation, model/runtime artifacts, prompt, cache and image healthcheck.
It never owns Translator Kafka contracts, jobs, queues, checkpoints, operator
API or consumer resources. No implementation identity crosses the opaque port.

Use apply_patch for manual edits, update CHANGELOG.md, preserve Git provenance,
run narrow meaningful checks and never commit weights, secrets or runtime data.
Build does not start containers. Release only immutable digest-pinned images
with SBOM, provenance and signature. Commit only as sapogov1978 with
60944481+sapogov1978@users.noreply.github.com.
