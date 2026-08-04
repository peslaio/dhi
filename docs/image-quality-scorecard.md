# DHI Image Quality Scorecard

Assessment date: 2026-07-31.

This scorecard judges whether the images provide a production-relevant improvement over regular upstream Docker Hub images. It does not compare them with Docker's paid Hardened Images service, and it does not treat a low vulnerability count as sufficient evidence of hardening.

## Verdict

**Portfolio score: 50/100 - candidate, not production-ready as a distribution.**

Seven images are configured for runtime closure. Six published closure images are credible hardened-image candidates; PHP-FPM remains a candidate under repair until its new functional contract passes in CI. This cohort removes substantial runtime content, uses an exact non-root identity, rejects package drift, and has application-level tests. It can provide value in a controlled production pilot after the current commit builds successfully and consumers pin a digest, verify signatures, and provide secure configuration.

The full-rootfs images are not at the same maturity. Several offer fewer packages than their selected upstream image, but MariaDB, PostgreSQL, MongoDB, and RabbitMQ lack the mature initialization and lifecycle behavior of their official images. RabbitMQ and .NET currently have more package records than the selected upstream comparison. The portfolio therefore should not be advertised as a drop-in production replacement.

## Scoring Model

| Area | Points | Current | Evidence |
| --- | ---: | ---: | --- |
| Runtime minimization | 20 | 11 | Seven closure images have exact allowlists and very small root filesystems; nine families retain full minbase dependency trees. |
| Least privilege and runtime hardening | 15 | 12 | Numeric non-root identity is checked; APT tools, setuid/setgid bits, and file capabilities are removed; closure images can remove shells. Full-rootfs images retain broader tooling and users can override OCI metadata. |
| Functional correctness | 20 | 10 | Every family now has an application contract, but current native CI has not completed, PHP is known broken until rebuilt, RabbitMQ has no passing functional run, and service lifecycle coverage remains shallow. |
| Supply chain and reproducibility | 20 | 7 | SBOM, Trivy, and keyless cosign exist. Inputs/actions are mutable, third-party key fingerprints are not checked, SBOMs are not OCI-attached, provenance is absent, and manifests consume mutable tags. |
| Platform and release assurance | 15 | 7 | Native amd64/arm64 jobs, tested-image archive handoff, immutable architecture digest records, and signed manifests are designed. Most families have not yet been republished under `peslaio`, and final native-platform pull verification is still missing. |
| Maintenance and usability | 10 | 3 | Per-image workflows and package docs are clear. There is no lifecycle automation, rebuild SLA, compatibility policy, or support commitment; some defaults are EOL. |
| **Total** | **100** | **50** | **Useful candidate architecture with material unresolved release and maintenance risk.** |

A score of 80 is the minimum target for a production-supported image family. A score above 80 still requires a current successful release and a documented support policy.

## Per-Image Assessment

Scores below measure repository maturity, not whether the application itself is suitable for production.

| Image | Score | Status | Main judgment |
| --- | ---: | --- | --- |
| `apache` | 68 | Candidate | Strong closure and static-app test; mutable inputs and aging release baseline limit assurance. |
| `caddy` | 67 | Candidate | Three-package closure and real HTTP test; third-party key bootstrap and broad major tag remain risks. |
| `haproxy` | 68 | Candidate | Tight closure and backend proxy roundtrip; lifecycle/version automation is missing. |
| `memcached` | 67 | Candidate | Two-package closure with protocol write/read; production network and resource policy remains consumer-owned. |
| `nginx` | 69 | Candidate | Tight closure and child-image HTTP contract; no immutable version/source policy. |
| `php-fpm` | 61 | Repair pending CI | The new contract found missing dynamic modules in the published image. Closure paths and dependencies are fixed locally but require a green release. |
| `redis` | 61 | Restricted pilot | Tight closure and RESP write/read pass; default no-auth configuration is not a secure production default. |
| `node` | 42 | Do not promote | Full rootfs and upstream Node.js 18 is EOL. A working HTTP fixture does not compensate for lifecycle risk. |
| `python` | 53 | Experimental | Real app contract and fewer packages than upstream, but still full rootfs with no exact allowlist. |
| `java-jre` | 51 | Experimental | Compiled-app contract passes; package footprint is close to upstream and no `jlink`/module-specific pruning exists. |
| `mariadb` | 43 | Do not replace upstream | SQL write/read works, but full rootfs and incomplete official-entrypoint-compatible initialization/lifecycle behavior dominate. |
| `postgresql` | 46 | Do not replace upstream | Database write/read works, but trust/bootstrap behavior and lifecycle coverage are not a production replacement for upstream. |
| `mongodb` | 40 | Do not promote | Functional CRUD baseline exists; auth, replica-set lifecycle, upgrade, and cross-platform release evidence are incomplete. |
| `rabbitmq` | 34 | Do not promote | Full rootfs is larger by package count than upstream, version 3.10 is EOL, and native CI still must validate the new queue roundtrip. |
| `dotnet-runtime-8.0` | 45 | Time-limited experimental | App contract exists, but full rootfs exceeds Microsoft upstream and .NET 8 support ends 2026-11-10. |
| `dotnet-runtime-9.0` | 41 | Do not start adoption | Full rootfs exceeds upstream and .NET 9 support ends 2026-11-10. |
| `dotnet-runtime-10.0` | 52 | Experimental | Supported LTS and app contract are positives; footprint still exceeds Microsoft runtime and Debian packages are a different distribution model. |
| `dotnet-aspnet-8.0` | 44 | Time-limited experimental | Real ASP.NET app test, but footprint and approaching end of support limit adoption. |
| `dotnet-aspnet-9.0` | 40 | Do not start adoption | Real ASP.NET app test cannot offset footprint and imminent end of support. |
| `dotnet-aspnet-10.0` | 51 | Experimental | Supported LTS and API contract; still larger by package count and behind Microsoft's update/compatibility program. |

## Measurable Gains Over Regular Images

The clearest gain is in the closure cohort. The last amd64 package snapshot records:

| Image | DHI packages | Selected upstream packages | Reduction |
| --- | ---: | ---: | ---: |
| `apache` | 8 | 116 | 93% |
| `caddy` | 3 | 32 | 91% |
| `haproxy` | 9 | 92 | 90% |
| `memcached` | 2 | 93 | 98% |
| `nginx` | 7 | 142 | 95% |
| `php-fpm` | 18 expected after repair | 173 | 90% |
| `redis` | 7 | 89 | 92% |

These percentages show package-database reduction, not vulnerability reduction and not an exact count of exploitable paths. They are still meaningful because shells, package managers, and unrelated administration programs are absent from closure root filesystems and the main application behavior is exercised afterward.

For `node` and `python`, package counts are lower than upstream, but the full-rootfs profile retains 111 and 121 package records. Java and database gains are modest. RabbitMQ and .NET show no package-count gain in the current comparison. See [package-diff-upstream.md](package-diff-upstream.md) for the full historical snapshot.

## Strengths That Matter

- Minimal root filesystems are created deliberately from package/file closures rather than by deleting only package metadata.
- Package allowlists convert unexpected dependency growth into a build failure.
- Exact non-zero user identity is checked in both OCI config and `/etc/passwd`.
- Setuid/setgid mode bits and Linux file capabilities are stripped and verified absent.
- Functional contracts exercise HTTP, FastCGI, cache protocols, message queues, language applications, and database writes.
- Native architecture runners remove QEMU behavior from release evidence.
- Keyless signatures, SBOM generation, and vulnerability gates apply through a common workflow.

## Blocking Weaknesses

1. No pinned Debian snapshot, exact package lock, verified third-party key fingerprint, or action SHA means the build is not reproducible and has avoidable supply-chain trust gaps.
2. No attached SBOM/provenance means evidence is separated from the image digest.
3. No scheduled rebuild, release monitoring, end-of-life gate, or security response commitment exists.
4. Database and messaging images do not match mature upstream initialization, credential, backup, restore, upgrade, and failure behavior.
5. Some current defaults are EOL or near EOL. Node.js 18 ended upstream support on 2025-03-27; RabbitMQ 3.10 community support ended in 2022; .NET 8 and 9 end support on 2026-11-10.
6. Debian 12 is now in LTS. Builds need `debian-security-support` coverage checks and a migration plan to Debian 13 instead of assuming uniform Bookworm security coverage.
7. Current GHCR publication under `peslaio` is incomplete for the full-rootfs cohort until the new workflows finish successfully.
8. Static gate behavior has no deliberate violation tests yet; the checks need fail-closed fixtures to prove that package, identity, shell, and privilege regressions are detected.

## Independent Review

Kimi K3 was used through Moonshot AI's official API as an independent reviewer. It scored the pre-test baseline **38/100** and the post-change evidence **48/100**. The second review agreed that the Compose architecture is appropriate, but reduced credit because PHP and RabbitMQ do not yet have green native CI and because the static gates lack deliberate failure tests.

The maintained score is 50/100, within the normal uncertainty of the independent 48/100 review. The small difference reflects verified package reduction for Node/Python and architecture limitations in upstream package sources; it does not change the no-go decision for the full-rootfs cohort. Kimi's output is an independent opinion, not security certification.

## Promotion Requirements

Before calling any family production-supported:

1. Complete a green native amd64/arm64 release for the exact commit.
2. Pin release inputs and actions; verify every external signing key fingerprint.
3. Attach SBOM and provenance to each immutable digest.
4. Define rebuild cadence, vulnerability response SLA, supported versions, and EOL policy.
5. Require digest-based consumer examples and signature identity verification.
6. Add persistence, restart, authenticated/TLS, upgrade, and backup/restore tests where relevant.
7. Demonstrate a material footprint or operational advantage over the selected upstream image.

Until those conditions are met, use the terms `experimental`, `candidate`, or `restricted pilot`, not `production-ready DHI`.

## Lifecycle Sources

- [Debian 12 entered LTS on 2026-07-12](https://www.debian.org/News/2026/20260712)
- [Debian Bookworm LTS coverage guidance](https://wiki.debian.org/LTS/Bookworm)
- [Node.js release lifecycle](https://nodejs.org/en/about/previous-releases)
- [RabbitMQ release support timeline](https://www.rabbitmq.com/release-information)
- [.NET support policy](https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core)
