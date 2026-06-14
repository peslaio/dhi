# DHI Image Quality Scorecard

This scorecard rates image quality from `0` to `100`. A score of `85+` is the current production-quality target for DHI images.

Scores are conservative. They use repository evidence, package inventory, package diffs against upstream images, and the latest successful workflow runs for the minimized images.

## Scoring Model

| Area | Points | What Good Looks Like |
| --- | ---: | --- |
| Package minimization | 25 | Runtime closure or equivalent pruning, exact package allowlist, no unexplained package records. |
| Runtime hardening | 15 | Non-root user, writable paths scoped, package-manager tooling removed, shell removed where startup does not need it. |
| CI verification | 20 | Build, smoke test, shell check, package allowlist, architecture matrix, and manifest publish all pass. |
| Supply-chain controls | 15 | SBOM generated, Trivy scan passes or has narrow documented ignores, pushed digest is signed. |
| Multi-architecture quality | 10 | `linux/amd64` and `linux/arm64` are published where upstream packages support both; unsupported arches are explicit. |
| Operational readiness | 15 | Entrypoint/config/chart behavior is service-appropriate, repeatable, and does not rely on avoidable shell bootstrap. |

## Current Scores

| Image | Score | Grade | Reason |
| --- | ---: | --- | --- |
| `apache` | 88 | Production target met | Runtime closure, exact package allowlist, shell removed, non-root, smoke test and publish passed on both architectures. |
| `caddy` | 85 | Production target met | Minimal package set and green CI; score is capped by narrow upstream Go stdlib Trivy ignores. |
| `haproxy` | 88 | Production target met | Runtime closure and package allowlist are strong; both architectures published successfully. |
| `memcached` | 86 | Production target met | Very small runtime package set; service smoke is basic but adequate for current image scope. |
| `nginx` | 88 | Production target met | Runtime closure, package allowlist, shell removal, HTTP smoke, and multi-arch publish are green. |
| `php-fpm` | 86 | Production target met | Runtime closure and package allowlist are green; FPM runtime remains larger than simpler daemon images. |
| `redis` | 84 | Near target | Runtime closure is good, but arm64 currently uses a weaker oneshot smoke path than amd64. |
| `node` | 68 | Needs pruning | Smaller than upstream, but still full-rootfs, no final package allowlist, and no runtime closure. |
| `python` | 70 | Needs pruning | Smaller than upstream, but still full-rootfs and needs Python-specific runtime closure. |
| `java-jre` | 64 | Needs pruning | Package count is close to upstream and Java runtime closure/module pruning is not implemented yet. |
| `mariadb` | 63 | Needs service hardening | Full-rootfs image; chart startup still depends on shell/bootstrap behavior. |
| `postgresql` | 66 | Needs service hardening | Full-rootfs image; chart startup still depends on shell/init behavior. |
| `mongodb` | 58 | Not production target | Full-rootfs, `amd64` only, and HA behavior depends on extra bootstrap tooling. |
| `rabbitmq` | 55 | Not production target | Full-rootfs and currently has more package records than the compared upstream image. |
| `dotnet-runtime-8.0` | 58 | Not production target | Full-rootfs, `amd64` only, and package count is higher than Microsoft upstream. |
| `dotnet-runtime-9.0` | 58 | Not production target | Full-rootfs, `amd64` only, and package count is higher than Microsoft upstream. |
| `dotnet-runtime-10.0` | 62 | Needs pruning | Multi-arch is better, but the image still carries a full Debian package set. |
| `dotnet-aspnet-8.0` | 57 | Not production target | Full-rootfs, `amd64` only, and package count is higher than Microsoft upstream. |
| `dotnet-aspnet-9.0` | 57 | Not production target | Full-rootfs, `amd64` only, and package count is higher than Microsoft upstream. |
| `dotnet-aspnet-10.0` | 61 | Needs pruning | Multi-arch is better, but package count remains higher than Microsoft upstream. |

## Interpretation

The strongest images today are the runtime-closure images:

- `apache`
- `caddy`
- `haproxy`
- `memcached`
- `nginx`
- `php-fpm`
- `redis`

The rest should not be described as production-quality hardened DHI images yet. They can run, but they still need package pruning, final package allowlists, stronger smoke tests, and in some cases chart/startup changes before they meet the same bar.

## Next Quality Gates

1. Republish all images under `ghcr.io/peslaio/*`.
2. Add runtime closure or equivalent pruning for `node`, `python`, and `java-jre`.
3. Design safe service-specific pruning for `mariadb`, `postgresql`, `mongodb`, and `rabbitmq`.
4. Rework .NET images so they do not exceed Microsoft upstream package count without a documented reason.
5. Add exact package allowlists to every image once the final package set is intentional.
6. Strengthen smoke tests so every architecture validates the main service behavior, not only version output.
