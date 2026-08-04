# DHI Image Architecture

This document describes the architecture implemented in this repository as of 2026-08-03. It separates current behavior from the target design so that experimental work is not presented as a production guarantee.

## Scope

DHI builds Debian-based OCI runtime images. The intended value is broader than vulnerability scanning:

- reduce executable and package attack surface
- omit package managers and interactive shells from runtime images where possible
- run the application as a fixed non-root numeric identity
- test application behavior instead of accepting a successful process start as proof
- publish SBOMs, vulnerability scan results, signatures, and multi-architecture manifests

The Helm charts in `charts/` are a separate deployment layer. Their presence does not make an image production-ready, and chart quality is not included in the image score unless a chart is required to start the image.

## Current System

```text
unfiltered PR / merge-group workflow
        |
        +-- validate 20 specs, 16 suites, and 35 declared legs
        +-- calculate affected image families from the actual diff
        +-- call selected family workflows without publishing
        +-- require one valid result artifact per expected leg
        |
        v
stable Image contract gate

per-image push or manual workflow
        |
        v
reusable-build-debian-image.yml
        |
        +-- mmdebstrap minbase + declared packages
        +-- optional third-party APT repository
        +-- hardening and runtime-rootfs construction
        +-- OCI image built FROM scratch
        +-- static image contract
        +-- process smoke test
        +-- Docker Compose application contract
        +-- SPDX SBOM + Trivy gate
        +-- architecture tag push + keyless cosign signature
        |
        v
reusable-publish-image-manifest.yml
        |
        +-- combine native amd64 and arm64 artifacts
        +-- publish version-suite manifest
        +-- keyless cosign signature on manifest digest
```

Each image family has its own workflow. The workflows pass image-specific package roots, files, command, user, ports, and test settings to the reusable builder. This keeps CI ownership visible while sharing the build implementation.

The files under `images/**/image.yaml` are the authority for family, version, Debian suite, and supported architectures. `tests/functional/contractctl.rb` joins them to one family-level `contract.yaml`, validates the complete inventory, and generates uncommitted build and manifest matrices. Family workflows still own package and rootfs-construction inputs; those details have not yet moved into executable image metadata.

Test fixture base images are recorded by tag and multi-platform digest in `tests/functional/fixtures.lock.json`. The runner passes those immutable references into Docker builds, and scheduled control-plane validation checks their declared amd64 and arm64 index coverage online.

## Runtime Construction Profiles

### Runtime closure

Used by `apache`, `caddy`, `haproxy`, `memcached`, `nginx`, `php-fpm`, and `redis`.

The builder copies declared application files, expands declared glob patterns, walks ELF dependencies with `ldd`, and records an exact package allowlist. It then removes shell and package-manager executables when requested. An unmatched required file pattern now fails the build.

This is the strongest profile in the repository because it materially reduces runtime contents. Package counts in the last published amd64 snapshot range from 2 to 16, compared with 32 to 173 records in the selected upstream images. Package count is only a proxy; functional coverage and reachable binaries matter more than the number alone.

### Full rootfs

Used by `node`, `python`, `java-jre`, `mariadb`, `postgresql`, `mongodb`, `rabbitmq`, `dotnet-runtime`, and `dotnet-aspnet`.

The builder starts from Debian `minbase`, installs declared package roots, removes caches and selected administration files, and ships the remaining dependency tree. These images run as non-root and omit APT executables, but they retain substantially more operating-system content and usually retain a shell.

This profile is a hardened Debian image construction method, not a distroless-equivalent result. It should not receive the same readiness label as the runtime-closure profile.

## Build And Release Contract

1. Validated image specifications select the application version, Debian suite, and architectures; a per-image workflow supplies package roots and runtime construction settings.
2. Native `ubuntu-24.04` amd64 and `ubuntu-24.04-arm` arm64 runners build matching Debian root filesystems. Cross-architecture QEMU execution is not used for release tests.
3. `mmdebstrap` verifies Debian repository metadata with the Debian archive keyring and installs the requested packages.
4. The builder creates either a closure rootfs or a cleaned full rootfs and writes a single runtime identity to `/etc/passwd`.
5. The image is built from `scratch` with exact `USER uid:gid` metadata.
6. Static checks reject UID 0, identity mismatch, forbidden package records, unexpected allowlist changes, APT executables, setuid/setgid files, file capabilities, and common shell executables when shell removal is enabled.
7. A smoke test validates process startup, command output, TCP, or HTTP behavior.
8. A Compose application contract builds or configures a representative consumer and exercises an application-level operation. The common runner proves the local source-image identity, applies a wall-clock deadline, captures evidence before teardown, and emits a canonical result.
9. Syft emits an SPDX JSON SBOM and Trivy gates fixable HIGH and CRITICAL package vulnerabilities.
10. Architecture-specific tags are pushed and signed. A separate workflow assembles and signs the multi-architecture manifest.

## Security Boundaries

The build trusts:

- GitHub-hosted runner images and the GitHub Actions control plane
- referenced GitHub Actions
- Debian mirrors, archive keys, and package metadata
- configured third-party APT endpoints and signing keys
- GHCR for storage and distribution
- Syft, Trivy, and cosign tooling installed by actions
- digest-pinned external images used to build functional-test fixtures

Consumers must still enforce their own controls:

- pin production deployments to an image digest
- verify the expected keyless signature identity and workflow issuer
- scan against the consumer's policy and current vulnerability database
- provide secure application configuration, credentials, TLS, and network policy
- test the actual application layered on the runtime image

Non-root metadata does not prevent a Kubernetes workload from overriding the user. Shell removal does not provide a sandbox. Minimal images still require seccomp, capability restrictions, read-only filesystems, network policy, and normal workload isolation.

## Strong Points

- The closure profile removes real attack surface, including APT and common shell executables, rather than only hiding package database records.
- Runtime users are numeric, non-zero, and checked against both image metadata and `/etc/passwd`.
- Setuid/setgid mode bits and Linux file capabilities are stripped from the final runtime rootfs and verified absent.
- Exact package allowlists make dependency drift visible for closure images.
- Every image family has an application-level contract, including data write/read operations for stateful services.
- Native amd64 and arm64 runners test the platform that will be published.
- SBOM generation, vulnerability gating, and keyless signing are part of the common workflow.
- Separate image workflows provide clear ownership and failure isolation while retaining a common implementation.

## Real Weak Points

### Release inputs are not reproducible

Debian mirrors, package versions, third-party repositories, and most action references are mutable. Builds are repeatable in structure but not bit-reproducible. The same commit can produce different package versions and bytes on another date.

Third-party APT keys are downloaded during the build without a declared fingerprint or checksum. A valid repository signature protects package metadata after a key is trusted, but the current key bootstrap is still an unauthenticated trust decision from the workflow's perspective.

### Artifact evidence is incomplete

The SPDX SBOM is uploaded as a workflow artifact but is not attached to the OCI digest. There is no SLSA provenance or in-toto build attestation. Consumers therefore cannot retrieve all evidence from the image reference alone.

Trivy scans OS packages for HIGH and CRITICAL vulnerabilities and ignores unfixed findings. It does not currently gate secrets, configuration findings, licenses, or a policy-defined age for ignored vulnerabilities.

### Version lifecycle is weak

The repository has no automated upstream release discovery, end-of-life gate, rebuild schedule, or documented security response SLA. Examples visible in the current defaults include upstream-EOL Node.js 18 and RabbitMQ 3.10. Debian 12 entered LTS on 2026-07-12, so package coverage must be checked rather than assuming all Bookworm packages receive normal Debian Security Team support.

### Full-rootfs images provide inconsistent value

`rabbitmq` and the .NET images currently contain more package records than their selected upstream comparisons. Database images are only modestly smaller and replace mature official entrypoint behavior with repository-specific startup assumptions. For these families, non-root execution and common supply-chain controls are useful, but package minimization is not yet a convincing reason to migrate.

### Runtime defaults are not secure deployment defaults

Redis and MongoDB development configurations allow unauthenticated network access. Database images do not yet implement the complete initialization, credential, upgrade, backup, and migration behavior users expect from mature official images. The image tests intentionally use isolated test networks; that does not make those settings suitable for production.

### Build configuration is only partly data-driven

Version, suite, architecture, and contract timeout now have validated authorities. Package roots, runtime closure paths, commands, and several version-specific filenames still live in family workflows. Changing a single-version specification without updating those construction inputs can therefore produce a semantically inconsistent build even though the generated matrix is correct.

### Publishing still uses mutable architecture tags

Manifest assembly waits for both build jobs, but it resolves mutable `-amd64` and `-arm64` tags instead of consuming immutable digest outputs. A release should pass and verify exact digests, including their declared platform, before creating the final manifest.

### Pull-request contracts still traverse a write-capable release graph

The central pull-request workflow disables pushing, does not inherit secrets, and guards architecture and manifest publication. The nested family and reusable build workflows nevertheless declare `packages: write` and `id-token: write`, so the current caller must also request those capabilities. A called workflow cannot elevate its token above the caller, which prevents simply downgrading the outer job while the same nested graph handles publication.

The intended boundary is a separate read-only contract-build graph followed by a write-capable publication graph. Until that split is implemented, same-repository pull-request workflow changes must be treated as write-capable code, and the workflow must never be changed to `pull_request_target`.

### Some gates still lack deliberate failure tests

The contract control plane has daemon-free negative tests for malformed results, failed test exits, OOM termination, identity mismatch, evidence aliasing, and missing evidence. The rootfs package, user, shell, and privilege gates do not yet inject every known violation and prove each check fails closed. The PHP incident shows why positive startup checks are insufficient: the old image passed CI while required runtime files were absent.

## Target Common Pattern

The functional-contract portion now has a validated specification join, generated matrices, native platform execution, typed results, exact artifact aggregation, and a stable PR gate. The next architecture work should extend that pattern:

1. Move package roots, runtime profile, identity, ports, writable paths, and trusted-key fingerprints into an executable versioned image schema.
2. Pin remaining third-party actions by commit and verify third-party APT key fingerprints before trust.
3. Separate read-only contract execution from the write-capable publishing call graph so pull-request jobs never request package or OIDC write capability.
4. Produce immutable per-architecture digests, OCI-attached SBOMs, and SLSA provenance.
5. Publish only after native platform tests pass and manifest entries match expected platforms and digests.
6. Add lifecycle automation for upstream releases, Debian support coverage, scheduled rebuilds, and deprecation.
7. Promote an image through explicit maturity states: experimental, candidate, and production-supported.

## Production Decision

These images are DHI-like in intent and, for the closure cohort, in technical construction. The repository is not yet a production-ready image distribution as a whole.

An experienced team can gain measurable value from a closure image after a current green build by pinning its digest, verifying its signature, supplying secure configuration, and running its own application tests. The full-rootfs database, RabbitMQ, and .NET images do not yet offer enough consistent advantage over mature upstream images to justify a blanket migration.

The open-source value is real: the build logic is inspectable, there is no paid-image dependency, and the strongest images substantially reduce runtime contents. The tradeoff is that update cadence, compatibility validation, incident response, and support remain the operator's responsibility until this project defines and demonstrates those services.
