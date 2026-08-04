# Production Functionality Acceptance Plan

Status: planning only. This document defines proposed acceptance scenarios; it does not add test code, fixtures, workflows, registry promotion, or a production guarantee.

## Goal And Claim Boundary

A passing current contract proves that the declared CI leg performed one representative operation under its recorded identity mode: Redis and Memcached execute the unchanged exact local image, while the other suites execute a derived application whose rootfs layers have the exact local source image as their prefix. The target is a stronger, auditable claim for each exact image digest:

> For the declared family, version, platform, configuration, and capability set, every required positive, negative, lifecycle, and published-artifact scenario passed with complete evidence.

No finite suite can prove that every possible application, configuration, input, dependency, workload, or failure will work. The phrase `fully functional` must therefore not be used without a bounded capability contract. Anything not declared and tested remains unsupported or unverified.

This plan extends the L0-L2 design in [testing.md](testing.md) and the identity and evidence rules in [ADR 0001](adr/0001-functional-image-contracts.md). It does not replace them.

## Current Scope

The repository currently has 20 image specifications, 16 family suites, and 35 native platform legs.

| Family | Declared version | Native platforms | Current representative contract |
| --- | --- | --- | --- |
| `apache` | 2.4 | amd64, arm64 | Serve static content over HTTP. |
| `caddy` | 2 | amd64, arm64 | Serve configured static content over HTTP. |
| `haproxy` | 2.6 | amd64, arm64 | Proxy one HTTP request to a backend. |
| `nginx` | 1.22 | amd64, arm64 | Serve static content over HTTP. |
| `php-fpm` | 8.2 | amd64, arm64 | Execute PHP through Nginx and FastCGI and check extension presence. |
| `memcached` | 1.6 | amd64, arm64 | Execute `VERSION`, `SET`, and `GET`. |
| `redis` | 7.0 | amd64, arm64 | Execute `PING`, `SET`, and `GET`. |
| `node` | 18 | amd64, arm64 | Run a repository-owned HTTP server. |
| `python` | 3.11 | amd64, arm64 | Run a standard-library HTTP server. |
| `java-jre` | 17 | amd64, arm64 | Compile and run one HTTP class. |
| `dotnet-runtime` | 8.0, 9.0, 10.0 | 8/9 amd64; 10 amd64, arm64 | Run a framework-dependent TCP application. |
| `dotnet-aspnet` | 8.0, 9.0, 10.0 | 8/9 amd64; 10 amd64, arm64 | Run a minimal ASP.NET endpoint. |
| `mariadb` | 10.11 | amd64, arm64 | Initialize an untrusted test instance and perform SQL write/read. |
| `postgresql` | 15 | amd64, arm64 | Initialize a trust-auth test cluster and perform SQL write/read. |
| `mongodb` | 8.0 | amd64 | Run an unauthenticated standalone instance and perform insert/find. |
| `rabbitmq` | 3.10 | amd64, arm64 | Enable management in a child fixture and publish/consume through its HTTP API. |

These contracts remain valuable release smoke tests. Passing them does not retroactively satisfy the scenarios below.

## Current Runtime Lifecycle Gate

Lifecycle status is time-sensitive and independent of functional success. This snapshot is current as of 2026-08-04 and must be refreshed by a scheduled policy monitor from the linked authoritative sources rather than scraped live by release jobs.

| Runtime | Current authority/status | Promotion consequence |
| --- | --- | --- |
| Node 18 | [Node.js release table](https://nodejs.org/en/about/previous-releases): EOL since 2025-03-27. | Hard block production promotion; move the specification and application matrix to an Active or Maintenance LTS line. |
| Python 3.11 | [Python version table](https://devguide.python.org/versions/): security-fixes-only through 2027-10. | Eligible only while the Debian package revision and Debian security coverage pass and a migration date is recorded. |
| Java 17 | [Debian OpenJDK 17 tracker](https://security-tracker.debian.org/tracker/source-package/openjdk-17): eligibility follows the exact Bookworm package and tracked security status, not a generic Java LTS label. | Fail closed when the version-controlled Debian coverage snapshot is stale, unsupported, or violates the approved vulnerability policy. |
| .NET / ASP.NET 8 | [Microsoft support policy](https://dotnet.microsoft.com/en-us/platform/support/policy): Maintenance, end of support 2026-11-10. | Require the latest approved patch and an explicit near-EOL adoption/migration decision; block after end of support. |
| .NET / ASP.NET 9 | [Microsoft support policy](https://dotnet.microsoft.com/en-us/platform/support/policy): Maintenance, end of support 2026-11-10. | Require the latest approved patch and an explicit near-EOL adoption/migration decision; block after end of support. |
| .NET / ASP.NET 10 | [Microsoft support policy](https://dotnet.microsoft.com/en-us/platform/support/policy): Active LTS, end of support 2028-11-14. | Eligible when the latest approved patch, platform, security, and functionality gates pass. |

The same snapshot mechanism must cover application servers, databases, proxies, and Debian Bookworm/LTS package coverage. A stale snapshot blocks release; a release workflow must not silently accept the last known status.

## Capability Contract Required Before More Tests

Each version must first declare the product surface that its tests are expected to cover. The eventual machine-readable representation is an implementation decision, but it must contain at least:

| Area | Required declaration |
| --- | --- |
| Runtime surface | Executables, modules, extensions, shared frameworks, protocol features, and expected version/ABI. |
| OCI interface | Entrypoint, command, user, home, workdir, ports, environment contract, and supported overrides. |
| Configuration | Supported file paths, environment precedence, reload behavior, and invalid-config behavior. |
| Filesystem | Immutable content, writable paths, tmpfs/volume requirements, ownership, and arbitrary-UID behavior. |
| Network and security | Listeners, authentication, TLS ownership, trusted peers, and intentionally unavailable features. |
| Lifecycle | Readiness meaning, PID 1 behavior, supported signals, graceful deadline, restart expectations, and log destinations. |
| State | Persistence format, initialization, backup/restore, crash recovery, and upgrade compatibility, or an explicit stateless declaration. |
| Compatibility target | Runtime primitive, repository chart/launcher, or declared drop-in compatibility with another image interface. |
| Exclusions | Features deliberately removed, not packaged, insecure by default, architecture-limited, or outside support. |

Every declared capability must map to at least one scenario. Every scenario must map back to a declared capability. An untested required capability, an undocumented exclusion, or an ambiguous compatibility target blocks production promotion.

For MariaDB, PostgreSQL, and MongoDB this decision is especially important. Their raw images currently default to version commands, while their functional child images and Helm charts supply startup logic. They must be described either as runtime primitives with a versioned, tested launcher or as service images with a supported entrypoint contract. They are not currently drop-in replacements for the official image entrypoints.

## Acceptance Tiers

| Tier | Execution point | Blocking purpose |
| --- | --- | --- |
| PR baseline | Every affected pull request on every declared native platform | Retain current L0 static, L1 smoke, and focused L2 application contracts. |
| Release acceptance | Before registry write, against the exact locally built image | Exercise the declared capability set, negative behavior, configuration, lifecycle, and a bounded concurrency burst. |
| Candidate-digest acceptance | After pushing run-scoped candidate references and resolving their immutable digests, before changing stable tags | Pull by digest on native runners, verify publication evidence, and rerun a short application contract against the registry object. |
| Version-promotion qualification | Before initially granting production support to a version or materially expanding its capability contract | Exercise upgrade sources, backup/restore, distributed behavior, Kubernetes integration, and approved controlled-runner SLOs. |
| Scheduled assurance | Recurring against an exact currently supported digest | Exercise longer soak, failure injection, certificate rotation, dependency matrices, lifecycle/security-policy refresh, and stateful recovery. |
| Diagnostic/performance | On demand until an explicit threshold and owner are approved | Characterize capacity and regressions without silently turning hardware-sensitive observations into release gates. |

Every production release graph must repeat the baseline assertions and pass the release and candidate-digest tiers; it does not depend on a separate prior PR event. Every changed stateful candidate digest must also pass a candidate-specific previous-accepted-state compatibility sentinel before a stable-tag move, even when its declared major/minor version is unchanged. The only absence exception is the first promotion of a new channel, when no previous accepted digest exists: record the approved `notApplicableReason`, pass initial version-promotion qualification, and qualify every declared supported source format. A missing predecessor fails closed for every subsequent changed digest. Version-promotion qualification is also required for a version transition, a material capability expansion, or a change to the declared state/upgrade contract, not for every byte-identical policy rebuild. Scheduled scenarios have family-specific freshness policies; a missing, stale, or failed required scheduled result marks the channel unhealthy and blocks subsequent stable-tag moves until triaged. It does not silently rewrite or roll back an already published tag.

Application failures must never be retried into a pass. Bounded retries are allowed only for classified infrastructure operations such as registry transfer. Each result identifies one candidate SUT plus every previous-image, builder, client, and fixture digest it used. Evidence from another candidate, attempt, or undeclared input cannot satisfy the current exact set.

## Common Required Scenarios

Every family inherits these scenarios. A family section may strengthen or explicitly mark a scenario as not applicable.

1. **Identity and inventory:** bind the result to repository commit, build/run attempt, platform, OCI metadata, runtime version, Debian package revision, and declared module/ABI inventory. Pre-publication results use the local image ID and exported archive SHA-256; architecture-candidate results add `platformManifestDigest`; assembled multi-platform results add `indexDigest`.
2. **Static policy:** verify the exact passwd identity and home, package policy, forbidden tools, privilege bits, capabilities, required files, ownership, and shell-removal policy. Deliberate violating fixtures must prove each gate fails closed.
3. **Real consumer:** build a repository-owned, dependency-locked application or client with digest-pinned builders. Runtime execution performs no package download and proves useful application behavior rather than a version command.
4. **Configuration:** prove defaults and documented file/environment precedence. Missing, malformed, contradictory, or unreadable required configuration must fail nonzero without becoming ready.
5. **Filesystem and identity:** run as `10001:0` and, where OpenShift compatibility is declared, as an arbitrary non-root UID with GID 0. Keep the root filesystem read-only and prove that only declared tmpfs or volume paths change.
6. **Positive and negative security behavior:** trusted credentials, certificates, peers, and permissions succeed; wrong credentials, wrong CA/hostname, plaintext where TLS is required, excessive privileges, and forbidden operations fail. Every declared HTTP, TLS/ALPN, stream, or binary-protocol mode requires explicit negotiation and negative-path evidence.
7. **Lifecycle:** drive PID 1 from the host-side controller through start, semantic readiness, an in-flight operation, the documented graceful signal, readiness withdrawal, bounded clean exit, restart, and a second semantic probe. The Docker socket must not be mounted into a verifier container.
8. **Failure paths:** exercise at least an invalid config, unwritable runtime path, missing dependency or secret, dependency timeout, and family-specific memory/PID/file-descriptor/storage exhaustion behavior. OOM or forced termination can be the correct declared result; it must be classified and must not report false readiness, hang indefinitely, corrupt committed state beyond the declared guarantee, or leave residual resources.
9. **Bounded concurrency:** run a correctness-oriented burst large enough to cross worker/thread/pool boundaries. Require zero unexpected application errors or crashes and record latency and resource data. Hardware-sensitive capacity thresholds belong only on controlled promotion runners.
10. **Cleanup and evidence:** capture logs, state, assertions, container/image inspection, filesystem changes, metrics, and cleanup before removal. OOM, signal, exit, secondary failure, and residual-resource states must remain distinguishable.
11. **Lifecycle eligibility:** consume a version-controlled policy snapshot refreshed by a scheduled monitor from authoritative upstream and Debian sources. Fail release when the snapshot is stale. An EOL or unsupported version cannot be promoted through additional positive tests.
12. **Applicability:** every common scenario is either required or carries a capability-contract-approved `notApplicableReason`. Omission is not equivalent to not applicable.
13. **Stateful digest compatibility:** before moving a stable tag to any changed stateful digest, create committed representative state with the previous accepted digest, stop it cleanly, and prove that the candidate can open or upgrade a copy of that state and continue reads and writes within the declared rollback boundary. When backup/restore is supported, also produce a backup with the previous digest and restore it into fresh candidate state. Record the observed package revisions, launcher/state-contract revisions, `sourceDigest`, backup producer digest and format/version, `targetDigest`, checksums, migration steps, and last safe rollback point. Only a first-ever channel with no previous accepted digest may record the approved `notApplicableReason`; it must instead pass initial version-promotion qualification and every declared supported-source scenario. Any later missing predecessor fails closed. Distributed, destructive, and long-running upgrade matrices may remain version-promotion or scheduled scenarios, but this candidate-specific sentinel may not.

## Candidate-Digest Promotion Flow

The current publisher verifies the tested archive and signs the resulting architecture and manifest digests, but it does not pull and execute the registry object. The target flow is:

1. Complete local release acceptance and export the exact tested architecture image.
2. Push run-scoped candidate architecture tags, resolve each immutable `platformManifestDigest`, attach the required per-platform SBOM/provenance, sign the digest, and verify signature identity, issuer, and attachment subjects without moving public stable tags.
3. On each native platform, pull the platform manifest by digest and prove that its platform, OCI revision, runtime identity, and digest match the publisher record. Pulling this single-platform object does not exercise index selection.
4. Rerun a short real-consumer contract from the pulled platform digest. Derived application fixtures must retain explicit source-layer identity; service primitives should run the pulled image directly with mounted configuration or launcher.
5. Assemble a candidate index only from the accepted platform digests, resolve its `indexDigest`, apply the declared index-level SBOM/provenance or attestation policy, sign it, and verify identity, issuer, and subjects.
6. Pull the candidate index by digest on every declared native platform and prove that registry selection resolves to the already accepted `platformManifestDigest` for that platform.
7. Move all supported mutable public tags only after acceptance: `version-suite` and, while the product exposes them, `version-suite-{arch}`. Re-resolve every moved tag and require the accepted index or platform digest. Alternatively retire stable architecture tags explicitly.
8. Leave a failed candidate unpromoted.

## Evidence And Pass Rules

Each scenario emits one attempt-scoped structured result with a common envelope and a scenario-specific evidence block. Fields such as lifecycle timings, request metrics, state checksums, or backup records are required only when the declared scenario schema makes them applicable; they are not fabricated for unrelated scenarios. The staged identity records are:

| Stage | Required SUT binding |
| --- | --- |
| Local acceptance | `localImageId` and exported `archiveSha256`. |
| Architecture publication | Role-tagged candidate `platformManifestDigest` bound to the local record. |
| Index assembly | Candidate `indexDigest` and its exact accepted platform-manifest members. |
| Native post-pull | Pulled image ID/digest and selected platform digest bound back to the candidate records. |
| Upgrade/rolling scenario | Explicit `sourceDigest` and `targetDigest`, with the target remaining the candidate SUT. |

The common envelope and applicable evidence contain:

- family, declared and observed version, scenario ID, tier, applicability, optional approved `notApplicableReason`, platform, commit, run ID, and run attempt;
- tier-appropriate SUT identity: pre-publication local image ID and archive SHA-256, architecture-candidate `platformManifestDigest`, assembled `indexDigest`, identity mode, and source-layer proof where applicable;
- candidate SUT identity plus role-tagged `sourceDigest`/`targetDigest`, previous-image, capability, fixture, client, and builder digests and dependency-lock hashes;
- assertion-level expected and actual outcomes, including expected negative failures;
- redacted configuration provenance, secret-file owner/mode without secret content, and public certificate fingerprints;
- PID 1 signal timestamp, readiness transition, drained operation, exit code, shutdown duration, restart duration, and post-restart probe;
- request/operation totals, concurrency, error count, latency summary, OOM state, and resource measurements;
- state checksum or record count before and after restart, restore, upgrade, or failover where applicable;
- container/image inspection, logs, filesystem changes, cleanup status, warnings, and secondary failures;
- cosign verification, SBOM/provenance subjects, public-tag re-resolution, and index-to-platform selection evidence for candidate-digest scenarios.

Aggregation must compare the exact expected and observed `(family, version, platform, tier, scenario)` sets. Missing, duplicate, stale, unexpected, malformed, wrong-digest, non-passing, evidence-incomplete, secret-leaking, or cleanup-failed results block the gate.

## Web And Proxy Images

### Apache 2.4

Current scope is deliberately a static-server closure retaining prefork, authorization, directory, and MIME modules. It does not currently retain SSL or proxy modules.

Required release acceptance:

- validate configuration and require the retained module inventory to equal the capability contract;
- serve GET and HEAD, correct MIME type, conditional and range requests, and the declared missing-file response;
- test `DirectoryIndex` resolution separately from `Options Indexes`: a directory containing `index.html` must resolve it, while a directory without an index must return the declared listing or denial; the production profile requires listing disabled unless it is an explicit supported capability;
- reject traversal and unsafe symlink access and explicitly decide whether `FollowSymLinks` remains a supported default;
- prove immutable config/content, stdout/stderr logging, declared runtime-path writes only, graceful stop, clean PID-file restart, and a keep-alive concurrency burst.

Version-promotion qualification:

- verify the last supported production configuration and install the chart in kind with probes, read-only policy, NetworkPolicy, rolling update, and disruption behavior if the chart is promoted with the image.

Scheduled assurance:

- reload a valid configuration during traffic and reject an invalid reload without replacing the serving workers;
- exercise slow clients and file-descriptor limits.

Claim boundary: TLS, reverse proxy, rewrite, embedded PHP, and any module absent from the retained inventory remain unsupported until both packaging and scenarios are added.

### Caddy 2

Required release acceptance:

- validate and adapt a declared Caddyfile and record the effective binary/version capability inventory;
- serve static content and reverse proxy method, path, body, and declared forwarding headers to a real backend;
- prove bounded backend-down behavior and automatic recovery after backend restart;
- use a deterministic private CA on an unprivileged TLS port: correct CA/hostname succeeds and incorrect trust or hostname fails;
- classify `/srv` explicitly as immutable content or writable application data, then prove that classification alongside `/config` and `/data` ownership, certificate/config immutability, graceful stop/restart, and bounded HTTPS/proxy concurrency;
- apply a valid route reload and prove an invalid reload leaves the previous configuration serving.

Version-promotion qualification:

- retain declared internal-PKI state across restart, verify prior-release Caddyfile and `/data` compatibility, and qualify the chart if it is supported.

Scheduled assurance:

- reload and rotate a private certificate under sustained traffic;
- test public ACME only in an explicitly isolated external-integration profile; do not make deterministic release CI depend on the public service.

Claim boundary: patch-level version, external DNS plugins, public ACME behavior, and any persisted state not named in the capability contract remain unclaimed.

### HAProxy 2.6

Required release acceptance:

- validate config and record `haproxy -vv` capabilities;
- proxy method, path, body, and declared headers across two distinguishable health-checked backends;
- remove one backend, require convergence to the survivor, restore it, then remove all backends and require the configured bounded failure response;
- verify admin-socket owner/mode, declared runtime writes, timeouts, graceful stop/restart, and a multi-connection burst;
- test TCP mode and mounted TLS termination only when they are declared supported capabilities.

Version-promotion qualification:

- verify compatibility with the last supported production configuration and qualify the chart if it is supported.

Scheduled assurance:

- drain or reload under traffic without losing accepted connections;
- exercise slow, flapping, and failing backends, `maxconn` saturation, and TLS handshake load.

Claim boundary: the current `-db` process model does not by itself define seamless reload. A supported master-worker or external replacement strategy must be declared before zero-downtime reload can be promised.

### Nginx 1.22

Required release acceptance:

- run config validation and record the exact `nginx -V` module/build inventory;
- exercise static GET/HEAD, MIME, conditional/range requests, missing files, and traversal rejection;
- proxy to a real backend, require bounded 502/504 behavior while it is down, and verify recovery;
- exercise private-CA TLS on an unprivileged port and positive/negative trust paths;
- send a large body through declared temporary storage and prove no undeclared filesystem writes;
- perform graceful QUIT with an in-flight response, restart, valid HUP reload, invalid-config rejection, and a keep-alive burst.

Version-promotion qualification:

- verify previous-config compatibility and run the real derived site through the chart if chart support is in scope.

Scheduled assurance:

- reload and interrupt backends under sustained traffic;
- exercise slow clients, temporary-file pressure, and file-descriptor limits.

Claim boundary: only modules in the recorded package/build inventory are supported. Static-serving success does not imply TLS, proxy, mail, stream, or third-party-module compatibility.

### PHP-FPM 8.2

Required release acceptance:

- build a dependency-locked representative application with Composer outside the runtime and copy only runtime files into the derived image;
- through Nginx/FastCGI exercise routing, GET and POST JSON, cookies/session state, file upload checksum, autoloaded dependency, controlled exception, and error logging;
- assign an operation-level assertion to every declared PHP extension or explicitly exclude it; `extension_loaded()` alone is not sufficient;
- record FPM SAPI, PHP/package revision, INI inputs, available PDO drivers, and OPcache behavior;
- prove immutable application/config, only declared session/upload/run/log writes, non-execution of non-PHP paths, controlled 5xx behavior, and no secret disclosure;
- use a production pool fixture with `clear_env=yes`, an explicit pool-level `env[...]` allowlist, `security.limit_extensions=.php`, and a declared trusted-peer boundary such as a protected Unix socket or isolated internal TCP listener; a declared variable must reach the app while an undeclared variable and a secret sentinel remain absent from responses and logs;
- declare the session backend and restart semantics: tmpfs-backed file sessions must disappear after restart, a mounted persistent session path must retain the expected session, and an external session backend must be tested as that separate capability;
- gracefully stop with an in-flight slow request, restart, and burst beyond `pm.max_children` without crash, OOM, or lost accepted requests.

Version-promotion qualification:

- verify a pinned framework/dependency lock across patch rebuilds and integrate with declared external services such as a database or Redis only after the required drivers/extensions are added to the capability contract;
- qualify the real application through the chart if chart support is in scope.

Scheduled assurance:

- sustain mixed fast/slow requests and uploads while measuring worker, memory, and OPcache growth;
- reload workers under traffic.

Claim boundary: FastCGI owns no public TLS/authentication boundary and must not be exposed directly. The current all-interface listener with `clear_env=no` is not a production-secure pool contract.

## Cache Images

### Memcached 1.6

Required release acceptance:

- cover SET/GET, ADD, REPLACE, GETS/CAS including stale-CAS rejection, DELETE, atomic counters, multi-get, TTL expiry, and version/stats;
- send malformed and oversized input and prove other clients remain usable;
- prove UDP remains disabled; when declared, test TLS negotiation and exercise SASL success/failure through the appropriate binary-protocol authentication path rather than treating capability output as behavioral proof;
- use concurrent clients to reach an exact counter result;
- stop and restart cleanly and explicitly require cached data to be absent after restart, because persistence is not a supported property;
- prove exact-image identity, read-only rootfs, no unexpected writes, and correct behavior at the configured memory limit.

Version-promotion qualification:

- verify previous-release command-line/config compatibility and chart NetworkPolicy/disruption behavior if the chart is a supported deployment path.

Scheduled assurance:

- run high-churn eviction, connection churn, maximum-connection behavior, and resource-leak soak.

Claim boundary: the default all-interface plaintext service has no authentication and is acceptable only behind enforced network isolation. Persistence, replication, and failover are explicitly unsupported.

### Redis 7.0

Required release acceptance:

- mount a secure ACL configuration; correct credentials and allowed commands succeed, while missing/wrong credentials and administrative commands from the application user fail;
- cover SET/GET, TTL, atomic concurrent INCR, transaction or pipeline behavior, selected data types, and pub/sub only if declared;
- use a persistent volume, write a committed value, wait for the declared Redis-7.0-compatible AOF durability condition derived from `appendfsync` and observable persistence state, record the accepted crash-loss window, stop gracefully, restart the exact candidate, and verify the value;
- test `maxmemory` with the declared eviction policy: rejected writes must not make PING or existing reads unhealthy;
- reject invalid or unwritable persistence configuration without reporting readiness;
- exercise TLS positive/negative paths if the Debian build's TLS capability is declared;
- complete a bounded concurrent client burst under non-root/read-only-rootfs constraints.

Version-promotion qualification:

- qualify the complete supported AOF/RDB source-format and backup/restore matrix beyond the candidate-specific previous-digest sentinel;
- qualify primary/replica resynchronization and controlled promotion if replication is in product scope, plus kind persistence/restart if the chart is supported.

Scheduled assurance:

- exercise SIGKILL/AOF recovery and AOF rewrite under traffic;
- run high-write soak with memory/latency trends and certificate rotation.

Claim boundary: the currently shipped `protected-mode no`, no-auth, all-interface configuration is a production blocker. A separately labelled no-auth restricted profile may require enforced network isolation, but it cannot satisfy the production ACL/TLS security scenario or receive the same security claim. AOF alone is not HA or a zero-loss guarantee.

## Language Runtime Images

### Node 18

Required release acceptance for any supported Node line:

- build a dependency-locked framework application in a digest-pinned builder and copy production dependencies into the runtime; no install occurs at runtime;
- exercise CommonJS/ESM loading, JSON and streaming HTTP, async filesystem access, DNS, outbound TLS with a private CA, crypto, compression, timers, and `worker_threads`;
- load a small repository-owned addon to prove its declared N-API level, architecture, dynamic loader, and relevant libc compatibility;
- prove environment/file configuration precedence, `NODE_EXTRA_CA_CERTS`, logging, invalid configuration, graceful keep-alive drain, restart, and bounded concurrency;
- require a clear failure for an incompatible native addon or unsupported runtime requirement.

Version-promotion qualification:

- pass the selected framework/native-addon compatibility matrix and kind rolling update.

Scheduled assurance:

- run memory/GC/file-descriptor soak, dependency timeouts, certificate rotation, and lifecycle/Debian security-coverage refresh.

Claim boundary: npm need not be present in the runtime if the declared pattern builds dependencies elsewhere. One N-API sentinel does not prove V8/NAN or arbitrary `NODE_MODULE_VERSION` addon compatibility. The [current scorecard](image-quality-scorecard.md) marks Node 18 EOL, so it remains blocked regardless of positive functional results until the specification moves to a supported line.

### Python 3.11

Required release acceptance:

- build a hash-locked WSGI or ASGI application and wheelhouse with an identical Debian interpreter ABI/path, then prefer installation into a copied `--target` tree without runtime downloads; a copied venv is allowed only when interpreter paths match and its shebangs, symlinks, and `pyvenv.cfg` are validated against the runtime;
- exercise TLS/CA, DNS, JSON, encodings, timezone data, filesystem/tmp behavior, threads, multiprocessing, `ctypes`, and every declared standard-library/native capability;
- load one repository-owned CPython extension and record SOABI to prove platform compatibility;
- prove configuration precedence, unbuffered logs, no unintended bytecode writes on a read-only rootfs, graceful worker drain, restart, and an incompatible-wheel failure;
- run bounded concurrent requests through the selected production server rather than only `http.server`.

Version-promotion qualification:

- pass the selected binary-wheel and WSGI/ASGI server matrix and kind rolling update.

Scheduled assurance:

- exercise worker crash/restart, memory and file-descriptor soak, certificate rotation, and Debian package/security-policy refresh rather than comparing only the interpreter's base version string.

Claim boundary: pip, build tools, venv creation, database drivers, and arbitrary PyPI wheels are supported only when explicitly declared. One native extension is an ABI sentinel, not universal wheel compatibility.

### Java JRE 17

Required release acceptance:

- build an offline/checksum-locked representative fat JAR with a digest-pinned Java 17 builder and run it with `java -jar`;
- exercise JSON, profiles/configuration, logging, reflection/service loading, DNS, outbound HTTPS/private truststore, crypto, timezone, charset, NIO/tmp, and every declared JRE module;
- load a small JNI library built for each native platform;
- record vendor/package revision, module list, `JAVA_HOME`, detected CPU/memory, and bounded heap behavior under a known cgroup limit;
- prove an application shutdown hook, graceful HTTP drain, restart, untrusted-CA failure, missing-JNI failure, and `UnsupportedClassVersionError` for deliberately newer bytecode.

Version-promotion qualification:

- pass the selected framework, JDBC, and native Netty/JNI matrix plus kind rolling update.

Scheduled assurance:

- exercise GC, memory, thread, and certificate-rotation behavior and refresh Debian OpenJDK security coverage.

Claim boundary: this is a Debian headless JRE, not a JDK. One fat-JAR fixture does not claim JPMS module-path applications, Java agents, CDS, JMX/JFR, thin-JAR layouts, vendor equivalence, or availability of compiler/diagnostic tools absent from the inventory unless each capability is separately declared and tested.

### .NET Runtime 8.0, 9.0, And 10.0

Required release acceptance for every declared version/platform leg:

- publish a locked, framework-dependent Generic Host/Worker application with the matching digest-pinned SDK and locked NuGet graph;
- exercise DI, options/configuration, logging, JSON, `HttpClient`, TLS, DNS, sockets, filesystem/tmp, globalization/ICU, time zones, reflection, ThreadPool, and container GC/memory behavior;
- load a small native P/Invoke sentinel on every native architecture;
- prove file/environment precedence, `DOTNET_RUNNING_IN_CONTAINER`, diagnostics policy, graceful host shutdown with an in-flight operation, restart, and bounded concurrency;
- prove framework mismatch and newer-target-framework failures with roll-forward policy fixed;
- prove that ASP.NET-only applications fail with the expected missing shared-framework result in the runtime image.

Version-promotion qualification:

- pass the selected NuGet/RID-native package matrix and kind rolling update.

Scheduled assurance:

- exercise memory/GC/PID constraints, dependency failure, and certificate rotation;
- refresh Microsoft servicing status and require the current approved package patch.

Claim boundary: the proposed fixture proves framework-dependent Generic Host deployment. Self-contained, single-file, trimmed, ReadyToRun, NativeAOT, and undeclared RID-native packaging remain unsupported until separately declared and tested. Versions 8.0 and 9.0 are currently amd64-only; 10.0 is declared for amd64 and arm64. Functional depth cannot override platform or lifecycle exclusions.

### ASP.NET 8.0, 9.0, And 10.0

Required release acceptance for every declared version/platform leg:

- publish a locked Web API with JSON model binding/validation, DI, options, environment-specific settings, structured logs, and semantic health/readiness endpoints;
- exercise Kestrel HTTP/1.1, HTTP/2 over private-CA TLS, streaming request/response, outbound HTTPS, and declared binding/config precedence;
- securely mount a test certificate and prove correct and incorrect password, path, CA, and hostname cases;
- withdraw readiness and drain keep-alive/in-flight work on SIGTERM, exit cleanly, restart, and pass bounded concurrency;
- fail clearly for invalid binding, missing certificate, unsupported shared-framework version, and unwritable runtime paths.

Version-promotion qualification:

- pass the selected middleware/NuGet graph, WebSocket or gRPC only when declared, and kind rolling update.

Scheduled assurance:

- exercise slow-client and memory/GC soak and certificate rotation;
- refresh the same version/platform and support-policy gates as the matching .NET runtime.

Claim boundary: a minimal endpoint does not prove arbitrary ASP.NET packages, server modes, authentication stacks, or RID-native dependencies.

## Data And Messaging Images

The required release scenarios below assume that the runtime-primitive versus service-image decision has been made. Until then, the launcher itself is an unresolved product boundary.

### MariaDB 10.11

Required release acceptance:

- initialize a fresh volume without `--skip-grant-tables`, using mounted secret files for root and least-privileged application credentials, and execute initialization exactly once;
- fail safely on a missing/misowned secret, nonempty partial data directory, or interrupted bootstrap without overwriting data;
- require TLS and correct credentials; reject plaintext, wrong CA/hostname, wrong password, and administrative operations from the application user;
- execute DDL, insert/update/select, constraints, prepared statements, commit, and rollback through an external client;
- perform graceful restart and SIGKILL recovery on the same volume: committed state survives, uncommitted state does not, and recovery logs contain no unexplained storage error;
- create a logical dump with the candidate, restore it into a fresh candidate volume, and compare schema, grants, row count, and canonical data checksum;
- for every changed candidate digest, create the same declared logical backup with the previous accepted digest, restore it into fresh candidate state, compare the same invariants, and record producer digest, format/version, target digest, and rollback boundary.

Version-promotion qualification:

- qualify the complete supported source-digest and on-disk-format matrix, upgrade procedure, and rollback boundaries beyond the candidate-specific previous-digest sentinel;
- qualify GTID replication, catch-up, controlled failover, and kind StatefulSet/PVC/Secret lifecycle when they are in the supported product contract.

Scheduled assurance:

- repeat the declared replication/failover sentinel and exercise backup/restore, ENOSPC, permission, corruption-marker, and multi-hour constrained-resource behavior.

Current blocker: the raw image defaults to a version command and the present functional launcher disables grants. The chart does not provide a complete credential/init-once contract.

### PostgreSQL 15

Required release acceptance:

- initialize with a secret file, SCRAM host authentication, explicit local policy, least-privileged application role, database, and one-time initialization;
- fail on an empty/missing secret instead of silently selecting host `trust`;
- require TLS `verify-full`; reject plaintext, wrong CA/hostname, and wrong credentials;
- exercise commit/rollback, prepared queries, foreign-key and unique constraints, and declared extensions through an external libpq-compatible client;
- perform graceful restart and SIGKILL recovery, require semantic readiness, validate WAL recovery, and compare committed state;
- run a custom-format logical dump with the candidate and restore it to a fresh candidate cluster with schema/data checksums;
- for every changed candidate digest, produce the declared backup with the previous accepted digest, restore it into a fresh candidate cluster, compare the same invariants, and record producer digest, format/version, target digest, and rollback boundary.

Version-promotion qualification:

- qualify the complete supported source-digest and cluster-format matrix, update procedure, integrity checks, and rollback boundaries beyond the candidate-specific previous-digest sentinel;
- qualify streaming replication, slots, promotion, timelines/LSN, base backup/PITR, and kind StatefulSet/PVC/Secret lifecycle when they are in the supported product contract.

Scheduled assurance:

- repeat the declared replication/recovery sentinel and exercise ENOSPC, permission failures, and constrained-resource soak.

Current blocker: the functional fixture uses trust authentication. The chart can default to host trust when the password is empty, consumes `POSTGRES_PASSWORD` through the environment instead of exposing a launcher-supported file-based secret contract, and does not include its optional PostgreSQL config mount in the startup command.

### MongoDB 8.0

Required release acceptance:

- keep the release explicitly amd64-only and reject any manifest or scheduling claim for arm64;
- form a single-member authenticated replica set for required release acceptance, perform localhost-only bootstrap of root and least-privileged application users, then restart with authorization, mounted key material, and TLS enabled;
- fail on missing secrets, wrong keyfile ownership/mode, interrupted init, or partial data without overwriting it;
- exercise insert/find/update/delete, unique-index rejection, aggregation, and a replica-set transaction commit/abort through an external client;
- perform graceful restart and SIGKILL/journal recovery with a canonical collection checksum;
- run candidate-to-candidate dump/restore using a separately digest-pinned tools fixture, not by expanding the runtime image;
- for every changed candidate digest, use the same declared tools fixture to back up data served by the previous accepted digest and restore it into fresh candidate state, compare canonical collection/index/auth metadata, and record producer digest, tools and format versions, target digest, and rollback boundary.

Version-promotion qualification:

- retain FCV across same-major patch-digest updates; for a separately supported cross-major upgrade, advance FCV only after the documented rollback boundary and compatibility checks;
- qualify a three-member TLS/keyfile replica set, majority writes, election after primary loss, transaction behavior during failover, rolling update, and kind StatefulSet/PVC/Secret/node-architecture lifecycle if the chart is supported.

Scheduled assurance:

- repeat the declared election/transaction sentinel and exercise ENOSPC and constrained-resource soak.

Current blocker: the raw image defaults to a version command and current functional coverage is unauthenticated standalone CRUD. The chart's replica-set launcher lacks auth/keyfile and can leave the process running after initialization retries are exhausted.

### RabbitMQ 3.10

Required release acceptance for a supported RabbitMQ line:

- mount a shared Erlang cookie with exact ownership/mode and continue proving that no cookie is baked into the image;
- initialize a non-guest user, vhost, permissions, and policies from controlled definitions; remote guest and wrong credentials must fail;
- use AMQPS with an external AMQP 0-9-1 client, not only management HTTP;
- declare exchange and durable/quorum queue, bind, publish persistent messages with confirms, consume/ack, nack/requeue, and verify mandatory unroutable behavior;
- perform graceful restart and SIGKILL recovery and prove that confirmed persistent messages satisfy the declared survival/delivery semantics;
- for every changed candidate digest, create a user, vhost, policy, durable/quorum queue, and confirmed persistent message with the previous accepted digest, stop it cleanly, then start the candidate against a copy of that state and prove the declared configuration, read/write, acknowledgement, and rollback-boundary behavior;
- treat definitions export/import as configuration recovery, not as a message backup, and define a separate Mnesia recovery procedure if supported.

Version-promotion qualification:

- qualify a three-node shared-cookie cluster, quorum-queue leader loss, confirmed-message accounting, rolling upgrade, feature flags, and kind StatefulSet/PVC/Secret/PDB/NetworkPolicy lifecycle if the chart is supported.

Scheduled assurance:

- repeat the declared quorum failover sentinel and exercise network partition, resource alarms, and constrained-resource soak.

Current blocker: the [current scorecard](image-quality-scorecard.md) marks RabbitMQ 3.10 EOL. The base image does not enable management, while the functional child does and the chart currently exposes its port. The chart also lacks a non-guest credential/definitions bootstrap, TLS contract, and mounted shared-cookie contract, so it is not yet a usable production launcher. Positive tests cannot override the lifecycle block.

## Kubernetes And Chart Acceptance

Chart success must not be inferred from image success. If a chart is part of the supported product, run these scenarios with the exact candidate digest in kind or another declared conformance cluster:

- require the default chart repository to equal the canonical publisher-owned repository; require candidate rendering to equal the exact canonical `<repository>@<indexDigest>`, prove native selection equals the expected `platformManifestDigest`, and require the running Pod status image ID to resolve to that selected platform digest;
- render and install normal, OpenShift arbitrary-UID, read-only-rootfs, NetworkPolicy, persistence, and secret-mount profiles;
- require semantic startup, readiness, liveness, and shutdown probes rather than TCP-only availability where corruption or partial initialization can still accept a socket;
- verify Service routing, denied and allowed network paths, no service-account token by default, seccomp, dropped capabilities, and declared writable mounts;
- delete and reschedule a pod, preserve or intentionally discard state according to the capability contract, and rerun the application assertion;
- perform rolling update from the previous accepted digest, PDB/disruption, rollback, and failure of a deliberately broken config or secret;
- for distributed stateful scenarios, verify quorum/failover semantics instead of only pod count.

Application-runtime charts whose defaults only sleep or omit probes remain scaffolding until a real derived application is supplied. Stateful chart launcher behavior is release-blocking when the raw image is marketed as a runtime primitive plus chart.

Current blocker: every chart defaults to `ghcr.io/tpesla/<family>`, while this repository currently publishes under `ghcr.io/peslaio/<family>`. A digest override does not repair a wrong repository name, so default and candidate rendering must both be corrected and tested before chart promotion.

## Planned Delivery Sequence

1. Define versioned capability contracts and explicit exclusions for all 20 specifications.
2. Define scenario IDs, structured result fields, exact-set aggregation, secret redaction, and host-controlled lifecycle phases.
3. Spike three orchestration shapes before multiplying fixtures: PHP-FPM for a derived application and trusted FastCGI boundary; Redis for exact-image persistence/auth/lifecycle; HAProxy for host-controlled dependency failure and TLS.
4. Extend the pattern to the remaining stateless web, cache, and language-runtime families.
5. Resolve the database runtime-primitive versus service-image boundary, then add secure initialization, restart/recovery, and backup/restore.
6. Add run-scoped candidate publication, native digest pull/run, attached evidence verification, and stable-tag promotion.
7. Add controlled-runner soak/performance baselines, upgrade matrices, distributed failure tests, and Kubernetes promotion.
8. Add deliberate negative fixtures for every common and family-specific gate before relying on it for promotion.

## Open Decisions Before Implementation

- Exact capability and exclusion list for every version, especially retained web-server modules and language native-extension support.
- Whether each database is a runtime primitive plus supported launcher/chart or a drop-in service image.
- Reference applications, clients, dependency locks, and fixture ownership for each ecosystem.
- Graceful deadlines, correctness burst sizes, controlled-runner resource profiles, soak duration, and versioned performance SLOs.
- Supported upgrade source versions, backup formats, and data-loss semantics.
- Candidate registry/tag namespace and atomic stable-tag promotion procedure.
- OCI attachment format and verification policy for SBOM and provenance.
- Lifecycle/EOL policy, rebuild cadence, evidence freshness, exception ownership, and support response SLA.
- Which Helm charts are part of the production-supported product rather than examples.

Until these decisions are recorded and every required scenario passes for the same exact digest, the existing labels `experimental`, `candidate`, and `restricted pilot` remain accurate.
