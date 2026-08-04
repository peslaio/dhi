# ADR 0001: Functional image contracts

- Status: Accepted
- Date: 2026-08-03

## Context

The repository builds multiple runtime-image families and architecture variants. Process startup and version output are useful smoke checks, but they do not prove that a real application can use the produced filesystem. A previous PHP failure demonstrated this gap: the process could start while required runtime files were absent.

The test system also needs to prevent three forms of false confidence:

- testing a mutable registry tag instead of the image built in the current job;
- treating a fixture image derived from the runtime as if it had the same image ID;
- accepting a green matrix summary when an expected architecture never produced a terminal result.

## Decision

### Authorities

`images/**/image.yaml` is the only authority for image family, version, Debian suite, and supported architectures. Each family has one `tests/functional/<family>/contract.yaml` containing only versioned execution policy such as the wall-clock timeout. Versions and platforms are not repeated in contract metadata.

The common discovery tool joins these files by the image `name`. It validates the inventory and emits build and manifest matrices at workflow runtime. Generated matrices are not committed.

### Executable contract

Every family provides a Docker Compose topology with these fixed roles:

- `app` is the system under test;
- `test` is the terminating verifier whose exit code decides the behavioral result;
- any other service is a fixture.

The contract must perform representative application behavior. Examples include serving a PHP application through FastCGI, publishing and consuming a RabbitMQ message, and writing and reading database state.

The common runner owns isolation, a true wall-clock deadline, immutable local image aliases, evidence capture, teardown, result classification, and canonical JSON output. Compose shutdown grace is not used as the execution deadline.

### Image identity

The runner reports one of two identity modes:

- `exact-container-image`: the `app` container image ID equals the locally resolved source image ID;
- `derived-rootfs-prefix`: a fixture image declares the source ID, and the source image's rootfs layers are an exact prefix of the fixture image's layers.

The second mode is intentionally not described as exact-image execution. It proves that the application fixture was built on the precise local runtime produced by CI while allowing test content or compiled output to be added.

All runtime services use a no-pull policy. The source alias and Compose project name are unique per run so concurrent jobs cannot share mutable tags, containers, networks, or volumes.

### Result and failure contract

Each expected `(family, version, platform)` leg must upload one terminal `result.json`, including failures during setup, readiness, identity validation, execution, and cleanup. Results distinguish:

- application assertion failure;
- setup or readiness failure;
- image identity or platform failure;
- wall-clock timeout;
- runner or container infrastructure failure;
- evidence or cleanup failure.

Logs, rendered Compose configuration, service state, container/image identity, and cleanup status are captured before resources are removed. A passing result is accepted only when the structured identity, Docker inspect, Compose state, and fixture-lock evidence parses and agrees with the result envelope.

### GitHub Actions gate

Pull requests and merge-queue candidates use one workflow without path filters. It validates the complete contract inventory, calculates affected families from the actual diff, calls the selected image workflows, downloads all per-leg results, and exposes one stable `Image contract gate` job.

Shared runner, schema, harness, or reusable-build changes select every declared leg. Documentation-only changes select none. Scheduled runs exercise all legs. Result artifacts are attempt-scoped, and the gate compares the current attempt's exact expected and observed leg sets. Stale-attempt results are ignored and cannot satisfy that set, so missing current results fail alongside duplicate, unexpected, malformed, or non-passing results. A retry must therefore use **Re-run all jobs**.

Publishing is explicitly disabled for centrally orchestrated validation. ADR 0002 subsequently moved publication out of family workflows and into a release-only tested-artifact publisher.

## Consequences

- A declared architecture cannot silently skip its application contract.
- Pull requests test the local image produced in that job without registry credentials.
- Failures are diagnosable from durable, structured evidence.
- Image metadata no longer drifts from a second committed workflow matrix.
- Derived fixtures remain necessary for compiled applications and some configuration-heavy services; their weaker identity mode is visible in evidence.
- The system adds CI orchestration and artifact storage, and native Arm runner availability becomes a fail-closed dependency.
- Read-only contract builds and release publication are now structurally separate as specified by ADR 0002.

## Deferred work

This decision does not provide post-publication digest pulls, OCI-attached SBOM/provenance validation, stateful upgrade and restore testing, Kubernetes lifecycle tests, or production promotion policy. Those are later gates and must not be inferred from a passing image-level contract. The read-only pull-request build graph was added by ADR 0002.

## Alternatives considered

- **Version or process checks only:** rejected because they do not exercise application behavior.
- **One metadata file containing versions, platforms, and assertions:** rejected because it duplicates image specifications and makes executable fixtures harder to review.
- **Testcontainers as the common harness:** rejected for this repository because it would add a project-language dependency solely for orchestration; it remains suitable in application repositories already using such a test stack.
- **Container image-ID equality for every suite:** rejected because most current suites intentionally build a small child fixture.
- **Path-filtered per-image checks as required checks:** rejected because skipped workflows do not provide a reliable, stable required status.
