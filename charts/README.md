# Debian Image Forge Helm Charts

This directory contains one Helm chart per Debian Image Forge image, plus a shared library chart.

## Architecture

The chart layout follows a Bitnami-style model:

- `dhi-common` is a Helm library chart with shared Kubernetes resources.
- Every application chart depends on `dhi-common` through `file://../dhi-common`.
- Application charts keep their own `values.yaml`, image defaults, ports, probes, persistence, config, and workload type.
- Stateless images use `Deployment`.
- Stateful images use `StatefulSet` with `volumeClaimTemplates` enabled by default.
- Security defaults run as non-root UID `10001`, group `0`, drop Linux capabilities, disable service account token automounting, and use `RuntimeDefault` seccomp.
- `openshift.enabled=true` removes fixed UID/GID settings so OpenShift restricted SCC can assign the runtime UID.
- `networkPolicy.enabled=true` renders a default ingress NetworkPolicy for the chart service.
- `metrics.enabled` is reserved and off by default. These images do not bundle Prometheus exporters; add exporters through `sidecars`, `extraEnvVars`, and additional service ports when needed.

## Charts

| Chart | Default image | Workload | Default service |
| --- | --- | --- | --- |
| `apache` | `ghcr.io/tpesla/apache:2.4-bookworm` | Deployment | HTTP 80 -> 8080 |
| `caddy` | `ghcr.io/tpesla/caddy:2-bookworm` | Deployment | HTTP 80 -> 8080 |
| `dotnet-aspnet` | `ghcr.io/tpesla/dotnet-aspnet:8.0-bookworm` | Deployment | Disabled |
| `dotnet-runtime` | `ghcr.io/tpesla/dotnet-runtime:8.0-bookworm` | Deployment | Disabled |
| `haproxy` | `ghcr.io/tpesla/haproxy:2.6-bookworm` | Deployment | HTTP 80 -> 8080 |
| `java-jre` | `ghcr.io/tpesla/java-jre:17-bookworm` | Deployment | Disabled |
| `mariadb` | `ghcr.io/tpesla/mariadb:10.11-bookworm` | StatefulSet | MySQL 3306 |
| `memcached` | `ghcr.io/tpesla/memcached:1.6-bookworm` | Deployment | Memcached 11211 |
| `mongodb` | `ghcr.io/tpesla/mongodb:8.0-bookworm` | StatefulSet | MongoDB 27017, replica set HA |
| `nginx` | `ghcr.io/tpesla/nginx:1.22-bookworm` | Deployment | HTTP 80 -> 8080 |
| `node` | `ghcr.io/tpesla/node:18-bookworm` | Deployment | Disabled |
| `php-fpm` | `ghcr.io/tpesla/php-fpm:8.2-bookworm` | Deployment | FastCGI 9000 |
| `postgresql` | `ghcr.io/tpesla/postgresql:15-bookworm` | StatefulSet | PostgreSQL 5432 |
| `python` | `ghcr.io/tpesla/python:3.11-bookworm` | Deployment | Disabled |
| `rabbitmq` | `ghcr.io/tpesla/rabbitmq:3.10-bookworm` | StatefulSet | AMQP 5672, management 15672 |
| `redis` | `ghcr.io/tpesla/redis:7.0-bookworm` | StatefulSet | Redis 6379 |

## Standard Values

Every application chart supports the same top-level deployment controls:

- `image.registry`, `image.repository`, `image.tag`, `image.digest`, `image.pullPolicy`, `image.pullSecrets`
- `replicaCount`, `workload.type`, `updateStrategy`
- `serviceAccount`, `podSecurityContext`, `containerSecurityContext`, `openshift`
- `command`, `args`, `env`, `extraEnvVars`, `extraEnvVarsCM`, `extraEnvVarsSecret`, `extraEnvFrom`
- `containerPorts`, `service`, `ingress`, `networkPolicy`
- `config`, `persistence`, `emptyDirs`, `extraVolumes`, `extraVolumeMounts`
- `resources`, `lifecycle`, `initContainers`, `sidecars`
- `livenessProbe`, `readinessProbe`, `startupProbe`
- `autoscaling`, `pdb`, `nodeSelector`, `tolerations`, `affinity`, `topologySpreadConstraints`, `priorityClassName`

Digest pinning is supported for every chart:

```sh
helm install redis ./charts/redis \
  --set image.digest=sha256:...
```

When `image.digest` is set, the chart renders `registry/repository@digest` and ignores `image.tag`.

## Examples

Install Redis with the default GHCR image:

```sh
helm dependency build ./charts/redis
helm install redis ./charts/redis
```

Install MongoDB as a 3-pod replica set:

```sh
helm dependency build ./charts/mongodb
helm install mongodb ./charts/mongodb
```

Scale MongoDB down to a single replica set member for local testing:

```sh
helm install mongodb ./charts/mongodb \
  --set replicaCount=1
```

Install ASP.NET runtime 10 instead of the default 8:

```sh
helm dependency build ./charts/dotnet-aspnet
helm install app ./charts/dotnet-aspnet \
  --set image.tag=10.0-bookworm \
  --set service.enabled=true
```

Render for OpenShift restricted SCC:

```sh
helm template redis ./charts/redis \
  --set openshift.enabled=true
```

Enable a default NetworkPolicy:

```sh
helm template redis ./charts/redis \
  --set networkPolicy.enabled=true
```

Validate all charts locally:

```sh
for chart in charts/*; do
  [ -f "$chart/templates/common.yaml" ] || continue
  helm dependency build "$chart"
  helm lint "$chart"
  helm template "dhi-$(basename "$chart")" "$chart" >/dev/null
done
```
