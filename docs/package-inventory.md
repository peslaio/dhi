# DHI Package Inventory

This document records the package set we intentionally need per image.

There are two states:

- `closure`: the image uses `runtime_closure`; the listed packages are the current shipped runtime package records.
- `full-rootfs`: the image is not minimized yet; the listed packages are the required top-level package roots, and the package count shows how many dpkg package records are currently still present.

Package counts were sampled from the published `linux/amd64` images in GHCR. On `linux/arm64`, `apache`, `haproxy`, and `nginx` currently omit `libssl3`, so their CI allowlists are architecture-specific.

## Runtime-Closure Images

These images already have a small package database. Keep these package sets tight and treat any new package as suspicious unless it is needed by the main process, config validation, TLS, name resolution, or the configured smoke test.

| Image | Tag | Packages | Keep packages |
| --- | --- | ---: | --- |
| `apache` | `2.4-bookworm` | 8 | `apache2`, `apache2-bin`, `ca-certificates`, `libc6`, `libcrypt1`, `libexpat1`, `libssl3`, `media-types` |
| `caddy` | `2-bookworm` | 3 | `ca-certificates`, `caddy`, `libc6` |
| `haproxy` | `2.6-bookworm` | 9 | `ca-certificates`, `haproxy`, `libc6`, `libcap2`, `libcrypt1`, `libgcc-s1`, `libgpg-error0`, `liblzma5`, `libssl3` |
| `memcached` | `1.6-bookworm` | 2 | `libc6`, `memcached` |
| `nginx` | `1.22-bookworm` | 7 | `ca-certificates`, `libc6`, `libcrypt1`, `libssl3`, `nginx`, `nginx-common`, `zlib1g` |
| `php-fpm` | `8.2-bookworm` | 10 | `ca-certificates`, `libc6`, `libcap2`, `libgcc-s1`, `libgpg-error0`, `liblzma5`, `php8.2-common`, `php8.2-fpm`, `tzdata`, `zlib1g` |
| `redis` | `7.0-bookworm` | 7 | `libc6`, `libcap2`, `libgcc-s1`, `libgpg-error0`, `liblzma5`, `redis-server`, `redis-tools` |

## Full-Rootfs Images

These images still include the normal minbase dependency tree. The package roots below are the packages we intentionally request; the current package count shows the remaining pruning target.

| Image | Tag | Current packages | Required package roots | Notes |
| --- | --- | ---: | --- | --- |
| `node` | `18-bookworm` | 111 | `ca-certificates`, `nodejs` | Candidate for runtime closure around `/usr/bin/node` and Node shared libraries. |
| `python` | `3.11-bookworm` | 121 | `ca-certificates`, `python3`, `python-is-python3` | Candidate for runtime closure around `/usr/bin/python3`, standard library, encodings, SSL, sqlite/readline as needed. |
| `java-jre` | `17-bookworm` | 130 | `ca-certificates`, `openjdk-17-jre-headless` | Candidate for a Java-specific closure; keep JVM modules, `cacerts`, fonts only if needed. |
| `mariadb` | `10.11-bookworm` | 142 | `ca-certificates`, `mariadb-server` | Chart startup currently uses `/bin/sh` and `mariadb-install-db`; do not remove shell until chart bootstrap moves into image entrypoint or native command. |
| `postgresql` | `15-bookworm` | 128 | `ca-certificates`, `postgresql-15` | Chart startup currently uses `/bin/sh`, `initdb`, and `postgres`; shell is still required by chart defaults. |
| `mongodb` | `8.0-bookworm` | 115 | `ca-certificates`, `mongodb-org-server`, `mongodb-mongosh` | `mongosh` is required by the current HA chart replica-set bootstrap. Debian bookworm server package is amd64-only. |
| `rabbitmq` | `3.10-bookworm` | 147 | `ca-certificates`, `rabbitmq-server` | Includes Erlang runtime packages. Runtime closure needs RabbitMQ/Erlang plugin and boot-script coverage before pruning. |
| `dotnet-runtime` | `8.0-bookworm` | 109 | `ca-certificates`, `dotnet-runtime-8.0` | amd64-only tag in current workflow. |
| `dotnet-runtime` | `9.0-bookworm` | 109 | `ca-certificates`, `dotnet-runtime-9.0` | amd64-only tag in current workflow. |
| `dotnet-runtime` | `10.0-bookworm` | 109 | `ca-certificates`, `dotnet-runtime-10.0` | Multi-arch tag in current workflow. |
| `dotnet-aspnet` | `8.0-bookworm` | 110 | `ca-certificates`, `aspnetcore-runtime-8.0` | amd64-only tag in current workflow. |
| `dotnet-aspnet` | `9.0-bookworm` | 110 | `ca-certificates`, `aspnetcore-runtime-9.0` | amd64-only tag in current workflow. |
| `dotnet-aspnet` | `10.0-bookworm` | 110 | `ca-certificates`, `aspnetcore-runtime-10.0` | Multi-arch tag in current workflow. |

## Package Removal Policy

For runtime images, remove or exclude package-manager and admin tooling unless the main application needs it:

- `apt`, `apt-get`, `apt-cache`, `apt-key`
- `dpkg`
- Debian archive keyrings and `gpgv` after package installation
- interactive shells when chart defaults and image entrypoints do not require shell bootstrap
- documentation, man pages, apt caches, package list caches, logs, and temporary files

Do not remove:

- runtime dynamic libraries discovered by ELF dependency closure
- CA certificates when the application may initiate TLS connections
- NSS/resolver libraries needed for DNS and service discovery
- config files, MIME/type data, timezone data, or language/runtime module data required by the process
- tooling used by smoke tests or chart startup scripts until those scripts are replaced

## Next Pruning Targets

1. Move chart bootstrap shell logic into image-native entrypoints or direct commands where possible.
2. Enable runtime closure for `node`, `python`, and `java-jre`.
3. Design service-specific closures for `mariadb`, `postgresql`, `mongodb`, and `rabbitmq`.
4. Revisit .NET images after deciding whether to keep Microsoft package layout or copy the runtime tree directly.
