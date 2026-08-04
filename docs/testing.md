# Image Test Strategy

The test goal is to prove that each locally built image can run a representative application operation, not merely print a version or keep a process alive.

The accepted design is recorded in [ADR 0001](adr/0001-functional-image-contracts.md).

## Contract Authorities

The repository currently declares 20 image specifications, 16 functional suites, and 35 native platform legs.

- `images/**/image.yaml` is authoritative for image family, version, Debian suite, and supported platforms.
- `tests/functional/<family>/contract.yaml` owns family-level execution policy such as the wall-clock timeout. It does not repeat versions or platforms.
- `tests/functional/<family>/compose.yaml` is the executable application topology.
- `tests/functional/fixtures.lock.json` pins external fixture images by multi-platform digest.
- `tests/functional/result.schema.json` defines the portable envelope and pass/fail conditionals. The authoritative `result.py` validator additionally cross-binds Docker, Compose, identity, fixture-lock, and cleanup evidence that JSON Schema cannot compare across files.

`contractctl.rb` joins these sources, rejects missing or orphaned suites, validates Compose policy, and emits build and manifest matrices at workflow runtime. Generated matrices are not committed.

Validate the complete control plane without starting containers:

```bash
ruby tests/functional/contractctl.rb validate
python3 tests/functional/selftest.py
```

The first command renders every Compose contract and therefore requires Docker Compose v2, but it does not require a running Docker daemon. The self-test deliberately submits fabricated green results and verifies that they are rejected.

Fixture references can be checked statically or against their registries:

```bash
python3 tests/functional/fixturectl.py validate
python3 tests/functional/fixturectl.py validate --online
```

The online check confirms that each pinned index still exposes every declared fixture platform. It runs in scheduled, merge-queue, and full manual CI validation.

## Test Layers

| Layer | Gate | Purpose |
| --- | --- | --- |
| L0 | Rootfs and image assertions | Validate package policy, numeric user identity, forbidden tools, required files, privilege bits, capabilities, and shell removal. |
| L1 | Process smoke | Validate startup, config parsing, port readiness, or a direct command. |
| L2 | Compose application contract | Build or configure a representative consumer and verify useful protocol behavior. |
| L3 | Published artifact | Verify digest signature, SBOM/provenance attachment, manifest platforms, and registry pull. Some controls remain planned. |
| L4 | Kubernetes lifecycle | Validate charts, persistence, restart, upgrade, failover, backup, and policy. Planned separately. |

L0 through L2 run against the local image before an architecture artifact is pushed.

## Functional Contract Matrix

| Image | Representative contract |
| --- | --- |
| `apache` | Build a child image with static content and receive the expected HTTP body. |
| `caddy` | Load a Caddy configuration and static content, then verify HTTP response content. |
| `haproxy` | Start a real backend service and verify an HTTP request traverses HAProxy. |
| `memcached` | Execute protocol-level `SET` and `GET` and compare the value. |
| `nginx` | Build a child image with static content and receive the expected HTTP body. |
| `php-fpm` | Serve a PHP application through an Nginx FastCGI peer and verify required dynamic extensions load. |
| `redis` | Execute RESP `PING`, `SET`, and `GET`. |
| `node` | Build and run a Node HTTP application and verify its response. |
| `python` | Build and run a Python HTTP application and verify its response. |
| `java-jre` | Compile a Java application in a builder stage, run the class on DHI JRE, and verify HTTP. |
| `dotnet-runtime` | Publish a framework-dependent .NET 8, 9, or 10 service and run it on DHI runtime. |
| `dotnet-aspnet` | Publish a minimal ASP.NET 8, 9, or 10 API and verify an HTTP request. |
| `mariadb` | Initialize a data directory, start the server, create a database and table, then write and read. |
| `postgresql` | Initialize a cluster, start PostgreSQL, create a database and table, then write and read. |
| `mongodb` | Start `mongod`, insert a document with `mongosh`, and read and validate it. |
| `rabbitmq` | Enable the management plugin, declare a queue, publish a message, and consume it through the HTTP API. |

The common verifier image uses only the Python standard library for HTTP and wire-protocol probes. Service-native clients remain in the database suites where they provide clearer semantic coverage.

## Runner Contract

Every Compose topology labels exactly one `sut` service and one terminating `test` service; other services are fixtures. Runtime services use `pull_policy: never`, an internal network, no host ports, and a unique Compose project and image alias for each run. Contracts also use read-only filesystems, declared temporary writable paths, dropped capabilities, and `no-new-privileges` where supported by the target.

The runner proves one of two image identities:

- `exact-container-image`: the SUT container uses the exact local source image ID. Redis and Memcached currently use this mode.
- `derived-rootfs-prefix`: a small child fixture records the source ID, and the source rootfs layer sequence must be an exact prefix of the SUT image. The other suites use this mode to add application files or compiled output.

This distinction prevents a derived fixture from being reported as exact-image execution while still proving that it is based on the image built in the current job.

The runner applies separate bounded operations for setup and cleanup plus the family timeout from `contract.yaml` for execution. It captures rendered Compose configuration, build and execution logs, service state, container inspections, image inspections, identity proof, fixture lock, and cleanup evidence before removing resources.

The canonical exit classifications are:

| Exit | Classification |
| --- | --- |
| `0` | Contract passed. |
| `2` | Invalid invocation or contract selection. |
| `10` | Application assertion failed. |
| `11` | Fixture build, setup, or readiness failed. |
| `12` | Image identity or platform proof failed. |
| `13` | A bounded operation or the wall-clock contract timed out. |
| `14` | Docker, Compose, verifier, or runner infrastructure failed. |
| `15` | Evidence capture or cleanup invalidated an otherwise passing run. |
| `130` / `143` | The runner was interrupted by `SIGINT` or `SIGTERM`. |

Cleanup or evidence failures discovered after another failure are retained as secondary failures rather than hiding the primary cause.

## Running Locally

The image reference must already exist in the local Docker image store. Run a contract with image family, image reference, application version, and platform:

```bash
tests/functional/run.sh \
  php-fpm \
  ghcr.io/peslaio/php-fpm:8.2-bookworm \
  8.2 \
  linux/amd64
```

Other examples:

```bash
tests/functional/run.sh redis ghcr.io/peslaio/redis:7.0-bookworm 7.0 linux/amd64
tests/functional/run.sh mongodb ghcr.io/peslaio/mongodb:8.0-bookworm 8.0 linux/amd64
tests/functional/run.sh dotnet-aspnet ghcr.io/peslaio/dotnet-aspnet:10.0-bookworm 10.0 linux/arm64
```

By default, the runner writes a unique evidence directory under `$RUNNER_TEMP`, `$TMPDIR`, or `/tmp/dhi-functional/`, in that order. Set `DHI_FUNCTIONAL_ARTIFACT_DIR` to choose an evidence root; every invocation creates a unique child directory so stale evidence cannot contaminate a later run:

```bash
evidence_root="$(mktemp -d)"
DHI_FUNCTIONAL_ARTIFACT_DIR="$evidence_root" \
  tests/functional/run.sh redis local/redis:test 7.0 linux/amd64
result_path="$(find "$evidence_root" -name result.json -type f -print -quit)"
python3 tests/functional/result.py validate "$result_path"
```

For a declared contract leg, `result.json` is emitted for setup and infrastructure failures as well as application failures, provided Python and the artifact directory are available. A malformed CLI invocation can exit before the terminal-result trap is installed.

## GitHub Actions Integration

`.github/workflows/image-contracts.yml` is the unfiltered pull-request, merge-queue, scheduled, and manual entry point. It performs control-plane preflight checks, computes affected families from the actual diff, invokes selected per-image workflows with publishing disabled, and exposes the stable required-check name `Image contract gate`.

Impact selection is fail-closed:

- a family image, workflow, or suite change selects that family;
- a shared runner, schema, fixture, reusable workflow, or image-specification control-plane change selects every family;
- documentation-only changes select no image legs but still run preflight and the stable gate;
- scheduled and merge-queue runs select all declared legs.

Each selected build leg runs on its native GitHub runner (`ubuntu-24.04` for amd64 and `ubuntu-24.04-arm` for arm64), uploads a uniquely named evidence artifact even when the contract fails, and then enforces the runner outcome. Family and central aggregators require the exact expected `(family, version, platform)` result set. Missing, duplicate, unexpected, malformed, or non-passing results fail the gate.

Direct per-image push and manual release workflows remain available. Their path filters intentionally cover production build inputs, while functional-test-only pull-request coverage is owned by the central unfiltered workflow. Manual publication is accepted only when the selected ref is `main`.

### Current permission limitation

The centrally orchestrated jobs set `push: false`, do not inherit secrets, and guard both architecture publication and manifest publication. However, the current nested reusable release graph still declares `packages: write` and `id-token: write`, so the caller must request those token capabilities even on pull requests. GitHub prevents a called workflow from elevating permissions above its caller, which makes this a structural constraint of the combined build-and-publish graph rather than a publishing switch alone.

Splitting read-only contract building from the write-capable publishing graph is required follow-up work. Until that split is complete, the central workflow must use `pull_request`, never `pull_request_target`, and repository owners should treat same-repository pull requests as write-capable workflow code.

After the workflow has run once, configure branch protection or the repository ruleset to require `Image contract gate`.

## Required Follow-Up Tests

The current contracts establish baseline runtime compatibility. Production promotion should also require:

1. Split the read-only pull-request build graph from registry publication and OIDC signing permissions.
2. Pull each final digest on native amd64 and arm64 after manifest publication.
3. Verify cosign certificate identity and issuer, not only signature presence.
4. Retrieve an OCI-attached SBOM and provenance statement for the same digest.
5. Test clean shutdown and restart with persisted data for all stateful services.
6. Test backup and restore for MariaDB, PostgreSQL, and MongoDB.
7. Test supported-version upgrades with retained data.
8. Test authenticated and TLS-enabled service configuration.
9. Test Helm charts in kind, including readiness, disruption, NetworkPolicy, and failover.
10. Add deliberate rootfs workflow-policy violations that prove every L0 gate fails closed.
