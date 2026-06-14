# DHI

DHI is a repository for building and publishing hardened Debian-based OCI images and matching Helm charts.

The project focuses on small runtime images, reproducible GitHub Actions workflows, multi-architecture publishing where upstream packages support it, and Kubernetes defaults that run as non-root.

Owner: Tobiasz Pesla <tobiasz@pesla.io>

## What Is Included

- Reusable GitHub Actions for Debian rootfs image builds.
- Per-application image workflows.
- Runtime hardening: non-root users, cleaned package caches, optional shell removal, SBOM generation, Trivy scans, and cosign signatures.
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

Most images publish `linux/amd64` and `linux/arm64` manifests. Some upstream package sources are architecture-limited; for example, the current Debian bookworm MongoDB server package is `amd64` only.

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

Each application workflow calls:

- `.github/workflows/reusable-build-debian-image.yml`
- `.github/workflows/reusable-publish-image-manifest.yml`

The build workflow:

1. Creates a Debian rootfs with `mmdebstrap`.
2. Installs only declared image packages.
3. Optionally copies a runtime closure into a smaller final rootfs.
4. Removes package-manager/cache/doc/log artifacts where possible.
5. Builds a `scratch`-based image.
6. Runs smoke tests.
7. Generates an SBOM.
8. Scans with Trivy.
9. Pushes and signs the image.

## Local Verification

Run workflow syntax checks:

```bash
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest
```

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
