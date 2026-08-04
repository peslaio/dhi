# DHI Image Quality Scorecard

Assessment date: 2026-08-04.

This scorecard judges whether the images provide a production-relevant improvement over regular upstream Docker Hub images. It does not compare them with Docker's paid Hardened Images service, and it does not treat a low vulnerability count as sufficient evidence of hardening.

## Verdict

**Portfolio score: 59/100 - candidate, not production-ready as a distribution.**

All seven runtime-closure images are credible hardened-image candidates. For commit [`0e62730`](https://github.com/peslaio/dhi/commit/0e627306a2f9c7ee018ad5b31fb4fd1079e5421d), every configured release workflow completed successfully: 35 native build legs produced bound Trivy reports, exercised the declared application contracts, exported the tested images, and published signed architecture images; the resulting 20 version/suite manifests were also published and signed. The closure cohort removes substantial runtime content, uses an exact non-root identity, rejects package drift, and has application-level tests. It can provide value in a controlled production pilot when consumers pin a digest, verify signatures, and provide secure configuration.

The full-rootfs images are not at the same maturity. Several offer fewer packages than their selected upstream image, but MariaDB, PostgreSQL, MongoDB, and RabbitMQ lack the mature initialization and lifecycle behavior of their official images. RabbitMQ and .NET currently have more package records than the selected upstream comparison. The portfolio therefore should not be advertised as a drop-in production replacement.

## Scoring Model

| Area | Points | Current | Evidence |
| --- | ---: | ---: | --- |
| Runtime minimization | 20 | 11 | Seven closure images have exact allowlists and very small root filesystems; nine families retain full minbase dependency trees. |
| Least privilege and runtime hardening | 15 | 12 | Numeric non-root identity is checked; APT tools, setuid/setgid bits, and file capabilities are removed; closure images can remove shells. Full-rootfs images retain broader tooling and users can override OCI metadata. |
| Functional correctness | 20 | 14 | Every declared native leg passed its application contract at `0e62730`, including the PHP FastCGI path and RabbitMQ queue roundtrip. Service lifecycle, persistence, authentication, TLS, upgrade, and failure coverage remain shallow. |
| Supply chain and reproducibility | 20 | 9 | SBOM, keyless cosign, immutable-digest manifest sources, and bound fail-closed Trivy JSON coverage are proven. Inputs and action tags remain mutable, third-party key fingerprints are not checked, SBOMs and scan reports are not OCI-attached, and provenance is absent. |
| Platform and release assurance | 15 | 10 | All 16 release workflows proved native builds, tested-image archive handoff, immutable architecture digest records, architecture signing, and signed manifests. Final native-platform pulls of the published registry objects are still missing. |
| Maintenance and usability | 10 | 3 | Per-image workflows and package docs are clear. There is no lifecycle automation, rebuild SLA, compatibility policy, or support commitment; some defaults are EOL. |
| **Total** | **100** | **59** | **Useful candidate architecture with material unresolved supply-chain, lifecycle, and maintenance risk.** |

A score of 80 is the minimum target for a production-supported image family. A score above 80 still requires a current successful release and a documented support policy.

## Per-Image Assessment

Scores below measure repository maturity, not whether the application itself is suitable for production.

| Image | Score | Status | Main judgment |
| --- | ---: | --- | --- |
| `apache` | 68 | Candidate | Strong closure and static-app test; mutable inputs and aging release baseline limit assurance. |
| `caddy` | 67 | Candidate | Four-package closure and real HTTP test; third-party key bootstrap and broad major tag remain risks. |
| `haproxy` | 68 | Candidate | Tight closure and backend proxy roundtrip; lifecycle/version automation is missing. |
| `memcached` | 67 | Candidate | Six-package closure with protocol write/read; production network and resource policy remains consumer-owned. |
| `nginx` | 69 | Candidate | Tight closure and child-image HTTP contract; no immutable version/source policy. |
| `php-fpm` | 66 | Candidate | Native Nginx-to-FastCGI contracts execute real PHP with required dynamic modules; lifecycle/version automation remains missing. |
| `redis` | 61 | Restricted pilot | Tight closure and RESP write/read pass; default no-auth configuration is not a secure production default. |
| `node` | 42 | Do not promote | Full rootfs and upstream Node.js 18 is EOL. A working HTTP fixture does not compensate for lifecycle risk. |
| `python` | 53 | Experimental | Real app contract and fewer packages than upstream, but still full rootfs with no exact allowlist. |
| `java-jre` | 51 | Experimental | Compiled-app contract passes; package footprint is close to upstream and no `jlink`/module-specific pruning exists. |
| `mariadb` | 43 | Do not replace upstream | SQL write/read works, but full rootfs and incomplete official-entrypoint-compatible initialization/lifecycle behavior dominate. |
| `postgresql` | 46 | Do not replace upstream | Database write/read works, but trust/bootstrap behavior and lifecycle coverage are not a production replacement for upstream. |
| `mongodb` | 40 | Do not promote | Functional CRUD baseline exists; auth, replica-set lifecycle, upgrade, and cross-platform release evidence are incomplete. |
| `rabbitmq` | 36 | Do not promote | Native queue declare/publish/consume passes, but the full rootfs is larger by package count than upstream, version 3.10 is EOL, and lifecycle/auth/TLS coverage is incomplete. |
| `dotnet-runtime-8.0` | 45 | Time-limited experimental | App contract exists, but full rootfs exceeds Microsoft upstream and .NET 8 support ends 2026-11-10. |
| `dotnet-runtime-9.0` | 41 | Do not start adoption | Full rootfs exceeds upstream and .NET 9 support ends 2026-11-10. |
| `dotnet-runtime-10.0` | 52 | Experimental | Supported LTS and app contract are positives; footprint still exceeds Microsoft runtime and Debian packages are a different distribution model. |
| `dotnet-aspnet-8.0` | 44 | Time-limited experimental | Real ASP.NET app test, but footprint and approaching end of support limit adoption. |
| `dotnet-aspnet-9.0` | 40 | Do not start adoption | Real ASP.NET app test cannot offset footprint and imminent end of support. |
| `dotnet-aspnet-10.0` | 51 | Experimental | Supported LTS and API contract; still larger by package count and behind Microsoft's update/compatibility program. |

## Measurable Gains Over Regular Images

The clearest gain is in the closure cohort. The current workflow closure sets, compared with the last upstream amd64 package snapshot, record:

| Image | DHI packages | Selected upstream packages | Reduction |
| --- | ---: | ---: | ---: |
| `apache` | 13 | 116 | 89% |
| `caddy` | 4 | 32 | 88% |
| `haproxy` | 19 | 92 | 79% |
| `memcached` | 6 | 93 | 94% |
| `nginx` | 9 | 142 | 94% |
| `php-fpm` | 33 | 173 | 81% |
| `redis` | 17 | 89 | 81% |

These percentages show package-database reduction, not vulnerability reduction and not an exact count of exploitable paths. They are still meaningful because shells, package managers, and unrelated administration programs are absent from closure root filesystems and the main application behavior is exercised afterward.

For `node` and `python`, package counts are lower than upstream, but the full-rootfs profile retains 111 and 121 package records. Java and database gains are modest. RabbitMQ and .NET show no package-count gain in the current comparison. See [package-diff-upstream.md](package-diff-upstream.md) for the full historical snapshot.

## Strengths That Matter

- Minimal root filesystems are created deliberately from package/file closures rather than by deleting only package metadata.
- Package allowlists convert unexpected dependency growth into a build failure.
- Exact non-zero user identity is checked in both OCI config and `/etc/passwd`.
- Setuid/setgid mode bits and Linux file capabilities are stripped and verified absent.
- Functional contracts exercise HTTP, FastCGI, cache protocols, message queues, language applications, and database writes.
- Native architecture runners remove QEMU behavior from release evidence.
- Keyless signatures, SBOM generation, retained bound vulnerability reports, and fail-closed vulnerability gates apply through a common workflow.

## Blocking Weaknesses

1. No pinned Debian snapshot, exact package lock, verified third-party key fingerprint, or action SHA means the build is not reproducible and has avoidable supply-chain trust gaps.
2. No attached SBOM/provenance means evidence is separated from the image digest.
3. No scheduled rebuild, release monitoring, end-of-life gate, or security response commitment exists.
4. Database and messaging images do not match mature upstream initialization, credential, backup, restore, upgrade, and failure behavior.
5. Some current defaults are EOL or near EOL. Node.js 18 ended upstream support on 2025-03-27; RabbitMQ 3.10 community support ended in 2022; .NET 8 and 9 end support on 2026-11-10.
6. Debian 12 is now in LTS. Builds need `debian-security-support` coverage checks and a migration plan to Debian 13 instead of assuming uniform Bookworm security coverage.
7. There is no final native-platform pull and identity check that validates each published registry object independently of the uploaded build archive.
8. Trivy coverage has deliberate false-green tests, but the rootfs package, identity, shell, and privilege gates still need a complete set of violation fixtures.

## Independent Review

Kimi K3 was used through Moonshot AI's official API as an independent reviewer. It scored the pre-test baseline **38/100** and the then-current post-change evidence **48/100**. At the time of that review, it agreed that the Compose architecture was appropriate but reduced credit because PHP and RabbitMQ did not yet have green native CI and because the static gates lacked deliberate failure tests.

The later `0e62730` release closed those specific PHP and RabbitMQ evidence gaps and proved bound, fail-closed Trivy coverage. The maintained score of 59/100 incorporates that later evidence; Kimi was not rerun, so its 48/100 remains a historical independent opinion rather than a current comparison or security certification. The no-go decision for the full-rootfs cohort is unchanged.

## Promotion Requirements

Before calling any family production-supported:

1. Complete a green release for every declared native platform for the exact commit.
2. Pin release inputs and actions; verify every external signing key fingerprint.
3. Attach SBOM and provenance to each immutable digest.
4. Define rebuild cadence, vulnerability response SLA, supported versions, and EOL policy.
5. Require digest-based consumer examples and signature identity verification.
6. Add persistence, restart, authenticated/TLS, upgrade, and backup/restore tests where relevant.
7. Demonstrate a material footprint or operational advantage over the selected upstream image.

Release `0e62730` satisfies requirement 1 for the current image changes. Every later promoted rebuild must satisfy it again.

Until those conditions are met, use the terms `experimental`, `candidate`, or `restricted pilot`, not `production-ready DHI`.

## Lifecycle Sources

- [Debian 12 entered LTS on 2026-07-12](https://www.debian.org/News/2026/20260712)
- [Debian Bookworm LTS coverage guidance](https://wiki.debian.org/LTS/Bookworm)
- [Node.js release lifecycle](https://nodejs.org/en/about/previous-releases)
- [RabbitMQ release support timeline](https://www.rabbitmq.com/release-information)
- [.NET support policy](https://dotnet.microsoft.com/en-us/platform/support/policy/dotnet-core)
