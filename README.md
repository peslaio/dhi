# DHI

DHI is an open-source project for building hardened Debian-based OCI runtime images and matching Helm charts.

The project focuses on small runtime images, repeatable GitHub Actions workflows, application-level tests, multi-architecture publishing where upstream packages support it, and non-root execution. Builds are not yet bit-reproducible because Debian packages, repositories, and action references are not fully pinned.

Owner: Tobiasz Pesla <tobiasz@pesla.io>

## What Is Included

- Reusable GitHub Actions for Debian rootfs image builds.
- Per-application image workflows.
- Runtime hardening: non-root users, cleaned package caches, optional shell removal, SBOM generation, Trivy scans, and cosign signatures.
- Docker Compose application contracts for every image family.
- Multi-arch manifest publishing for supported images.
- Helm charts based on a shared `dhi-common` library chart.
- A package inventory for tracking which packages are intentionally needed per image.

## Images

Current image families:

- `apache`
- `caddy`
- `dotnet-aspnet`
- `dotnet-runtime`
- `haproxy`
- `java-jre`
- `mariadb`
- `memcached`
- `mongodb`
- `nginx`
- `node`
- `php-fpm`
- `postgresql`
- `python`
- `rabbitmq`
- `redis`

Most images target `linux/amd64` and `linux/arm64` on native GitHub-hosted runners. Some upstream package sources are architecture-limited: MongoDB 8.0 and the Microsoft Debian packages used for .NET 8 and 9 are currently published here only for `linux/amd64`; .NET 10 supports both platforms.

## Maturity

The repository is under active architecture and common-pattern development. The runtime-closure images provide measurable attack-surface reduction and are candidates for controlled evaluation, but the image portfolio is not yet a production-supported distribution.

Read the evidence before adoption:

- [Current architecture and weak points](docs/architecture.md)
- [Image test strategy](docs/testing.md)
- [Functional image contract decision](docs/adr/0001-functional-image-contracts.md)
- [Tested-image publication decision](docs/adr/0002-tested-image-publication-boundary.md)
- [Conservative quality scorecard](docs/image-quality-scorecard.md)
- [Package differences against upstream images](docs/package-diff-upstream.md)

## Package Inventory

The package inventory is maintained in [docs/package-inventory.md](docs/package-inventory.md). Package differences against regular upstream images are tracked in [docs/package-diff-upstream.md](docs/package-diff-upstream.md), and current quality scores are tracked in [docs/image-quality-scorecard.md](docs/image-quality-scorecard.md).

It separates:

- images that already use runtime closure pruning
- images that still ship the full minbase dependency tree
- required top-level package roots per image
- remaining package-count pruning targets

## Helm Charts

Charts live under `charts/`.

Each application chart depends on the local `dhi-common` library chart:

```bash
helm dependency build ./charts/nginx
helm lint ./charts/nginx
helm template dhi-nginx ./charts/nginx
```

The CI workflow renders normal mode, OpenShift mode, and NetworkPolicy mode for each chart.

## Build Workflows

Image workflows live in `.github/workflows/`.

Each application build workflow calls:

- `.github/workflows/reusable-build-debian-image.yml`
- `.github/workflows/reusable-aggregate-image-contract.yml`

Pull-request and merge-queue callers grant only read access. Per-family release wrappers first run the same read-only build and test graph with image export enabled. A separate write-scoped publisher then verifies the same-run archive, pushes and signs architecture tags, and calls `.github/workflows/reusable-publish-image-manifest.yml`.

Functional evidence and release artifacts are scoped to one workflow attempt. Retry a failed image validation or release with **Re-run all jobs**; **Re-run failed jobs** intentionally fails closed rather than mixing artifacts from different attempts. See the [release permission boundary](docs/testing.md#release-permission-boundary).

The build workflow:

1. Creates a Debian rootfs with `mmdebstrap`.
2. Installs only declared image packages.
3. Optionally copies a runtime closure into a smaller final rootfs.
4. Removes package-manager/cache/doc/log artifacts where possible.
5. Builds a `scratch`-based image.
6. Verifies package, user, shell, and package-manager policy.
7. Runs a process smoke test and a representative application contract.
8. Generates an SBOM and scans with Trivy.
9. For a trusted release only, exports the tested image and identity metadata as a one-day workflow artifact.
10. In a separate release-only job, verifies the archive, pushes and signs architecture tags, and publishes and signs the final manifest.

## Local Verification

Run workflow syntax checks:

```bash
docker run --rm \
  -v "$PWD:/repo" \
  -w /repo \
  rhysd/actionlint:1.7.7@sha256:887a259a5a534f3c4f36cb02dca341673c6089431057242cdc931e9f133147e9 \
  -color
```

Validate all image specifications, functional suites, Compose policies, fixture pins, generated matrices, and negative control-plane tests:

```bash
ruby tests/functional/contractctl.rb validate
python3 tests/functional/selftest.py
python3 tests/functional/fixturectl.py validate
```

Run a functional image contract:

```bash
tests/functional/run.sh \
  php-fpm \
  ghcr.io/peslaio/php-fpm:8.2-bookworm \
  8.2 \
  linux/amd64
```

The image reference must exist in the local Docker image store. The test builds a small PHP application, places Nginx in front of PHP-FPM, verifies dynamic PHP modules, and checks the HTTP response. It writes a canonical `result.json` plus logs, identity proof, service state, and cleanup evidence. See [docs/testing.md](docs/testing.md) for every image contract and CI behavior.

Run Helm checks for one chart:

```bash
helm dependency build ./charts/redis
helm lint ./charts/redis
helm template dhi-redis ./charts/redis
```

Inspect published platforms:

```bash
docker buildx imagetools inspect ghcr.io/peslaio/nginx:1.22-bookworm
```

Inspect packages in a published image:

```bash
container="$(docker create ghcr.io/peslaio/nginx:1.22-bookworm)"
docker export "$container" | tar -xOf - var/lib/dpkg/status | awk '/^Package: /{print $2}'
docker rm "$container"
```

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
