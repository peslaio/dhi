# Image Test Strategy

The test goal is to prove that each locally built image can run a representative application operation, not merely print a version or keep a process alive.

The accepted design is recorded in [ADR 0001](adr/0001-functional-image-contracts.md).

## Contract Authorities

The repository currently declares 20 image specifications, 16 functional suites, and 35 native platform legs.

- `images/**/image.yaml` is authoritative for image family, version, Debian suite, and supported platforms.
- `tests/functional/<family>/contract.yaml` owns the wall-clock timeout, assertion-suite name, and exact required assertion IDs. It does not repeat versions or platforms.
- `tests/functional/<family>/compose.yaml` is the executable application topology.
- `tests/functional/fixtures.lock.json` pins external fixture images by multi-platform digest.
- `tests/functional/result.schema.json` defines the portable envelope and pass/fail conditionals. The authoritative `result.py` validator additionally cross-binds Docker, Compose, identity, fixture-lock, and cleanup evidence that JSON Schema cannot compare across files.
- `tests/functional/scan_result.py` validates that Trivy scanned the exact tested image as Debian, produced a non-empty OS-package inventory, and, for a runtime closure, found exactly the declared package allowlist.

`contractctl.rb` joins these sources, rejects missing or orphaned suites, validates Compose policy, and emits build and manifest matrices at workflow runtime. Generated matrices are not committed.

Validate the complete control plane without starting containers:

```bash
ruby tests/functional/contractctl.rb validate
python3 tests/functional/selftest.py
```

The first command renders every Compose contract and therefore requires Docker Compose v2, but it does not require a running Docker daemon. The self-test deliberately submits fabricated green application results and false-green vulnerability reports and verifies that they are rejected.

Fixture references can be checked statically or against their registries:

```bash
python3 tests/functional/fixturectl.py validate
python3 tests/functional/fixturectl.py validate --online
```

The online check confirms that each pinned index still exposes every declared fixture platform. It runs in scheduled, merge-queue, and full manual CI validation.

## Test Layers

| Layer | Gate | Purpose |
| --- | --- | --- |
| L0 | Rootfs and image assertions | Validate package policy, runtime-closure Debian OS identity, numeric user identity, forbidden tools, required files, privilege bits, capabilities, and shell removal. |
| L1 | Process smoke | Validate startup, config parsing, port readiness, or a direct command. |
| L2 | Compose application and lifecycle contract | Build or configure a representative consumer, verify useful protocol behavior, then host-control a graceful stop, same-container restart, and identical second assertion pass. |
| L3 | Registry candidate acceptance | Sign and natively pull each run-scoped architecture digest, rerun L2, assemble and sign a candidate index, prove native member selection, and rerun L2 before stable promotion. OCI-attached SBOM/provenance remain planned. |
| L4 | Kubernetes lifecycle | Validate charts, persistence, restart, upgrade, failover, backup, and policy. Planned separately. |

L0 through L2 run against the local image before an architecture artifact is pushed. The same local image then receives an SPDX SBOM and a Trivy JSON scan. The scan is not accepted merely because Trivy exits zero: a separate coverage gate binds the report to the tested image ID and requires Debian OS metadata plus a non-empty package inventory. Runtime closures must match their exact allowlist. The JSON report is retained as workflow evidence.

## Functional Contract Matrix

| Image | Representative contract |
| --- | --- |
| `apache` | Serve static content and verify GET, HEAD, MIME, range, conditional, missing, traversal, and concurrent request behavior. |
| `caddy` | Verify the static contract plus a real reverse-proxy request, backend identity, and forwarding headers. |
| `haproxy` | Balance across distinguishable backends, survive one backend loss, return the declared all-unhealthy response, and recover. |
| `memcached` | Exercise version, set/get, multiget, add/replace, CAS, TTL, stats, malformed/oversized input, exact concurrent increments, delete, and empty state after process restart. |
| `nginx` | Verify the static contract plus a real reverse-proxy request, backend identity, and forwarding headers. |
| `php-fpm` | Run an Nginx-to-FastCGI application with an exact extension inventory, autoloading, query decoding, JSON echo, session cookie, upload checksum, controlled error, missing route, and concurrency checks. |
| `redis` | Require authentication and a restricted ACL, then test strings, TTL, transaction, forbidden administration, exact concurrent increments, and AOF state across restart. |
| `node` | Run a configured HTTP application and independently require JSON, filesystem, DNS, crypto, compression, encoding/timezone, worker, native-runtime/reflection, and local HTTP checks. |
| `python` | Run a configured HTTP application and independently require JSON, filesystem, DNS, crypto, compression, encoding/timezone, threads, native libc, reflection, and local HTTP checks. |
| `java-jre` | Compile a Java application in a pinned builder and independently require configuration, JSON, filesystem, DNS, crypto, compression, encoding/timezone, threads, reflection, native process, and local HTTP checks. |
| `dotnet-runtime` | Build offline from pinned SDK fixtures and require framework-dependent host, configuration, JSON, filesystem, DNS, crypto, compression, encoding/timezone, threads, reflection, native libc, and local HTTP behavior. |
| `dotnet-aspnet` | Extend the .NET runtime checks with Generic Host startup, routing/health, model validation, and streaming behavior. |
| `mariadb` | Bootstrap authenticated least-privilege access; test DDL, CRUD, upsert, commit/rollback, constraints, denied administration, and retained state after restart. |
| `postgresql` | Bootstrap password-authenticated least-privilege access; test DDL, CRUD, upsert, commit/rollback, constraints, denied role administration, and retained state after restart. |
| `mongodb` | Bootstrap authenticated users and a transaction-capable replica set; test CRUD, upsert, unique index, commit/abort, aggregation, denied user administration, and retained state after restart. |
| `rabbitmq` | Bootstrap a non-guest user/vhost, declare durable topology, publish persistent messages, test requeue/ack/unroutable and resource authorization, and retain a lifecycle marker across restart. |

The RabbitMQ runtime does not bake an Erlang cookie into the image and exposes
only the AMQP port by default. Clustered deployments must provide their cookie
as a secret with owner-only permissions. The functional fixture enables the
management plugin only for its HTTP queue roundtrip; it is not enabled in the
base runtime image.

The common verifier image uses only the Python standard library for HTTP and wire-protocol probes. Service-native clients remain in the database suites where they provide clearer semantic coverage.

## Runner Contract

Every Compose topology labels exactly one `sut` service and one terminating `test` service; other services are fixtures. Runtime services use `pull_policy: never`, an internal network, no host ports, and a unique Compose project and image alias for each run. Contracts also use read-only filesystems, declared temporary writable paths, dropped capabilities, and `no-new-privileges` where supported by the target.

The runner proves one of two image identities:

- `exact-container-image`: the SUT container uses the exact local source image ID. Redis and Memcached currently use this mode.
- `derived-rootfs-prefix`: a small child fixture records the source ID, and the source rootfs layer sequence must be an exact prefix of the SUT image. The other suites use this mode to add application files or compiled output.

This distinction prevents a derived fixture from being reported as exact-image execution while still proving that it is based on the image built in the current job.

The runner applies separate bounded operations for setup and cleanup plus the family timeout from `contract.yaml` for execution. The host-side lifecycle controller starts the topology, accepts exactly one `DHI_ASSERTION_SUMMARY` whose IDs equal the contract, requires every long-lived service to remain running with a clean state, sends `SIGTERM` directly to the SUT container, waits for an allowed clean exit, restarts the same container ID, and repeats the verifier and exact assertion-set checks. Redis additionally binds its empty-initial and restored-restart expectations to the controller phase; Memcached proves that its in-memory marker disappears. It captures rendered Compose configuration, build and execution logs, assertion contract and summaries, lifecycle timings, service state, container inspections, image inspections, identity proof, fixture lock, and cleanup evidence before removing resources.

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

Each selected build leg runs on its native GitHub runner (`ubuntu-24.04` for amd64 and `ubuntu-24.04-arm` for arm64), uploads uniquely named functional and vulnerability evidence, and then enforces both outcomes. Functional result names include the workflow attempt; family and central aggregators accept only the current attempt's exact expected `(family, version, platform)` result set. Stale-attempt results are ignored and cannot satisfy the gate, so missing current results fail alongside duplicate, unexpected, malformed, or non-passing results. Retry a failed validation with **Re-run all jobs**, because a failed-jobs-only retry intentionally cannot reuse results from an older attempt.

Direct per-image push and manual release wrappers remain available. Their path filters intentionally cover production build inputs, while functional-test-only pull-request coverage is owned by the central unfiltered workflow. Manual publication is accepted only when the selected ref is `main`.

### Release permission boundary

The central workflow and all family build workflows are read-only. They set `export_image: false` for pull requests and merge-queue candidates, never log in to the registry, and contain no push or signing operation.

A trusted main-branch release has the following stages:

1. `release_build` calls the same read-only family workflow with `export_image: true`. Only after static checks, smoke, the functional contract, SBOM generation, Trivy policy, and independent Trivy coverage validation succeed does the builder save the architecture-tagged image as a run-scoped artifact.
2. `release_publish` receives `packages: write` and `id-token: write`, downloads only the named artifact from the current workflow run, and verifies its repository, commit SHA, run ID, run attempt, version, platform, local image ID, byte size, and SHA-256 digest.
3. Each native publisher pushes a run-scoped candidate architecture tag, records and signs its immutable digest, verifies the keyless certificate identity and issuer, pulls the digest on the matching native runner, and reruns the complete functional and lifecycle contract.
4. Manifest publication accepts only the exact set of successful immutable architecture records, creates and signs a run-scoped candidate index from `image@sha256:…` members, and on every declared native platform proves that index selection equals the accepted platform digest before rerunning the contract from the index digest.
5. Only after all candidate acceptance jobs pass does promotion move the convenience architecture tags and finally the version-suite index tag. Every moved tag is re-resolved and compared with its accepted digest.

The release wrapper serializes runs per family and ref without cancelling an active publisher. This prevents two main-branch runs from concurrently overwriting the same architecture tags. Architecture and manifest publishers also require their commit to remain an ancestor of current `main` and compare intervening paths immediately before writing. A newer documentation-only or unrelated-family commit is allowed; a force-pushed lineage or a newer change to the same family or a shared release input fails closed. Self-tests require this path classifier to equal every wrapper's push trigger paths. The accepted design is recorded in [ADR 0002](adr/0002-tested-image-publication-boundary.md).

Release archive names include the workflow run attempt. To retry a failed release, use **Re-run all jobs**. Re-running only failed jobs cannot combine successful architecture archives from an older attempt with newly built archives and therefore fails closed.

GHCR does not provide an atomic transaction across several mutable tags. Promotion therefore updates stable architecture tags sequentially and writes the version-suite index last as the release commit marker. A registry failure during promotion can leave some architecture convenience tags advanced while the primary version-suite tag remains on the previous accepted index. Operators must treat the primary index tag or an immutable digest as authoritative and retry or reconcile a partial promotion.

After the workflow has run once, configure branch protection or the repository ruleset to require `Image contract gate`.

## Remaining Production Gates

The complete target acceptance matrix is documented in [Production Functionality Acceptance Plan](production-functionality-test-plan.md). The repository now implements its common assertion contract, host-controlled graceful restart, candidate architecture/index acceptance, and chart-rendering baseline, but the broader matrix is not complete and does not provide a universal production guarantee.

The current contracts establish baseline runtime compatibility. Production promotion should also require:

1. Attach the SBOM and provenance to the OCI digest and verify their subjects after registry pull.
2. Add post-promotion native pulls of the public stable tags; current native acceptance uses the same immutable candidate digests before those tags move.
3. Add readiness withdrawal and in-flight drain assertions around graceful shutdown, plus crash/SIGKILL recovery where applicable.
4. Test backup and restore for MariaDB, PostgreSQL, and MongoDB.
5. Test previous-accepted-digest and supported-version upgrades with retained data.
6. Add TLS-enabled service profiles and negative CA/hostname/plaintext checks; current stateful fixtures cover password authentication and authorization but not TLS.
7. Test Helm charts in kind, including probes, arbitrary UID, persistence, disruption, NetworkPolicy, rolling update, and failover. Current chart gates are render-time only.
8. Add deliberate rootfs workflow-policy violations beyond the covered Trivy no-OS/no-package cases to prove every L0 gate fails closed.
9. Enforce supported-version and Debian lifecycle policy; functional success cannot make EOL Node 18 or RabbitMQ 3.10 production-eligible.
