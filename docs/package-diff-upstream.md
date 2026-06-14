# DHI Package Diff Against Upstream Images

This document compares DHI images with regular upstream application images using package database records from `linux/amd64` images.

Generated on 2026-06-28 from available GHCR images. The collector prefers `ghcr.io/peslaio/*` and falls back to legacy `ghcr.io/tpesla/*` when an image has not yet been republished under the organization namespace.

Package names come from `/var/lib/dpkg/status` for Debian/Ubuntu images and `/lib/apk/db/installed` for Alpine images. Cross-package-manager comparisons, such as DHI Caddy `dpkg` vs upstream Caddy `apk`, are useful for size/surface comparison but package names are not one-to-one equivalent.

## Summary

| Image | DHI image | Upstream image | Package DB | DHI packages | Upstream packages | Common | DHI only | Upstream only |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `apache` | `ghcr.io/peslaio/apache:2.4-bookworm` | `httpd:2.4-bookworm` | `dpkg/dpkg` | 8 | 116 | 5 | 3 | 111 |
| `caddy` | `ghcr.io/peslaio/caddy:2-bookworm` | `caddy:2` | `dpkg/apk` | 3 | 32 | 1 | 2 | 31 |
| `haproxy` | `ghcr.io/peslaio/haproxy:2.6-bookworm` | `haproxy:2.6-bookworm` | `dpkg/dpkg` | 9 | 92 | 8 | 1 | 84 |
| `memcached` | `ghcr.io/peslaio/memcached:1.6-bookworm` | `memcached:1.6-bookworm` | `dpkg/dpkg` | 2 | 93 | 1 | 1 | 92 |
| `nginx` | `ghcr.io/peslaio/nginx:1.22-bookworm` | `nginx:1.22` | `dpkg/dpkg` | 7 | 142 | 5 | 2 | 137 |
| `php-fpm` | `ghcr.io/peslaio/php-fpm:8.2-bookworm` | `php:8.2-fpm-bookworm` | `dpkg/dpkg` | 10 | 173 | 8 | 2 | 165 |
| `redis` | `ghcr.io/peslaio/redis:7.0-bookworm` | `redis:7.0-bookworm` | `dpkg/dpkg` | 7 | 89 | 5 | 2 | 84 |
| `node` | `ghcr.io/tpesla/node:18-bookworm` | `node:18-bookworm` | `dpkg/dpkg` | 111 | 413 | 98 | 13 | 315 |
| `python` | `ghcr.io/tpesla/python:3.11-bookworm` | `python:3.11-bookworm` | `dpkg/dpkg` | 121 | 429 | 116 | 5 | 313 |
| `java-jre` | `ghcr.io/tpesla/java-jre:17-bookworm` | `eclipse-temurin:17-jre` | `dpkg/dpkg` | 130 | 140 | 90 | 40 | 50 |
| `mariadb` | `ghcr.io/tpesla/mariadb:10.11-bookworm` | `mariadb:10.11` | `dpkg/dpkg` | 142 | 151 | 132 | 10 | 19 |
| `postgresql` | `ghcr.io/tpesla/postgresql:15-bookworm` | `postgres:15-bookworm` | `dpkg/dpkg` | 128 | 144 | 122 | 6 | 22 |
| `mongodb` | `ghcr.io/tpesla/mongodb:8.0-bookworm` | `mongo:8.0` | `dpkg/dpkg` | 115 | 128 | 91 | 24 | 37 |
| `rabbitmq` | `ghcr.io/tpesla/rabbitmq:3.10-bookworm` | `rabbitmq:3.10` | `dpkg/dpkg` | 147 | 105 | 99 | 48 | 6 |
| `dotnet-runtime-8.0` | `ghcr.io/tpesla/dotnet-runtime:8.0-bookworm` | `mcr.microsoft.com/dotnet/runtime:8.0` | `dpkg/dpkg` | 109 | 92 | 91 | 18 | 1 |
| `dotnet-runtime-9.0` | `ghcr.io/tpesla/dotnet-runtime:9.0-bookworm` | `mcr.microsoft.com/dotnet/runtime:9.0` | `dpkg/dpkg` | 109 | 92 | 91 | 18 | 1 |
| `dotnet-runtime-10.0` | `ghcr.io/tpesla/dotnet-runtime:10.0-bookworm` | `mcr.microsoft.com/dotnet/runtime:10.0` | `dpkg/dpkg` | 109 | 97 | 78 | 31 | 19 |
| `dotnet-aspnet-8.0` | `ghcr.io/tpesla/dotnet-aspnet:8.0-bookworm` | `mcr.microsoft.com/dotnet/aspnet:8.0` | `dpkg/dpkg` | 110 | 92 | 91 | 19 | 1 |
| `dotnet-aspnet-9.0` | `ghcr.io/tpesla/dotnet-aspnet:9.0-bookworm` | `mcr.microsoft.com/dotnet/aspnet:9.0` | `dpkg/dpkg` | 110 | 92 | 91 | 19 | 1 |
| `dotnet-aspnet-10.0` | `ghcr.io/tpesla/dotnet-aspnet:10.0-bookworm` | `mcr.microsoft.com/dotnet/aspnet:10.0` | `dpkg/dpkg` | 110 | 97 | 78 | 32 | 19 |

## Per-Image Diffs

### `apache`

- DHI: `ghcr.io/peslaio/apache:2.4-bookworm` (8 packages)
- Upstream: `httpd:2.4-bookworm` (116 packages)
- Common packages: 5
- DHI-only packages: 3
- Upstream-only packages: 111

<details>
<summary>DHI-only packages</summary>

```text
apache2
apache2-bin
media-types
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
adduser
apt
base-files
base-passwd
bash
bsdutils
coreutils
dash
debconf
debian-archive-keyring
debianutils
diffutils
dpkg
e2fsprogs
findutils
gcc-12-base
gpgv
grep
gzip
hostname
init-system-helpers
libacl1
libapr1
libaprutil1
libaprutil1-ldap
libapt-pkg6.0
libattr1
libaudit-common
libaudit1
libblkid1
libbrotli1
libbz2-1.0
libc-bin
libcap-ng0
libcap2
libcom-err2
libcurl4
libdb5.3
libdebconfclient0
libext2fs2
libffi8
libgcc-s1
libgcrypt20
libgdbm6
libgmp10
libgnutls30
libgpg-error0
libgssapi-krb5-2
libhogweed6
libicu72
libidn2-0
libjansson4
libk5crypto3
libkeyutils1
libkrb5-3
libkrb5support0
libldap-2.5-0
libldap-common
liblua5.2-0
liblz4-1
liblzma5
libmd0
libmount1
libnettle8
libnghttp2-14
libp11-kit0
libpam-modules
libpam-modules-bin
libpam-runtime
libpam0g
libpcre2-8-0
libpcre3
libpsl5
librtmp1
libsasl2-2
libsasl2-modules-db
libseccomp2
libselinux1
libsemanage-common
libsemanage2
libsepol2
libsmartcols1
libss2
libssh2-1
libstdc++6
libsystemd0
libtasn1-6
libtinfo6
libudev1
libunistring2
libuuid1
libxml2
libxxhash0
libzstd1
login
logsave
mawk
mount
ncurses-base
ncurses-bin
openssl
passwd
perl-base
sed
sysvinit-utils
tar
tzdata
usr-is-merged
util-linux
util-linux-extra
zlib1g
```

</details>

### `caddy`

- DHI: `ghcr.io/peslaio/caddy:2-bookworm` (3 packages)
- Upstream: `caddy:2` (32 packages)
- Common packages: 1
- DHI-only packages: 2
- Upstream-only packages: 31

<details>
<summary>DHI-only packages</summary>

```text
caddy
libc6
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
alpine-baselayout
alpine-baselayout-data
alpine-keys
alpine-release
apk-tools
brotli-libs
busybox
busybox-binsh
c-ares
ca-certificates-bundle
curl
libapk
libcap
libcap-getcap
libcap-setcap
libcap-utils
libcap2
libcrypto3
libcurl
libidn2
libpsl
libssl3
libunistring
mailcap
musl
musl-utils
nghttp2-libs
scanelf
ssl_client
zlib
zstd-libs
```

</details>

### `haproxy`

- DHI: `ghcr.io/peslaio/haproxy:2.6-bookworm` (9 packages)
- Upstream: `haproxy:2.6-bookworm` (92 packages)
- Common packages: 8
- DHI-only packages: 1
- Upstream-only packages: 84

<details>
<summary>DHI-only packages</summary>

```text
haproxy
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
adduser
apt
base-files
base-passwd
bash
bsdutils
coreutils
dash
debconf
debian-archive-keyring
debianutils
diffutils
dpkg
e2fsprogs
findutils
gcc-12-base
gpgv
grep
gzip
hostname
init-system-helpers
libacl1
libapt-pkg6.0
libattr1
libaudit-common
libaudit1
libblkid1
libbz2-1.0
libc-bin
libcap-ng0
libcom-err2
libdb5.3
libdebconfclient0
libext2fs2
libffi8
libgcrypt20
libgmp10
libgnutls30
libhogweed6
libidn2-0
liblua5.3-0
liblz4-1
libmd0
libmount1
libnettle8
libp11-kit0
libpam-modules
libpam-modules-bin
libpam-runtime
libpam0g
libpcre2-8-0
libseccomp2
libselinux1
libsemanage-common
libsemanage2
libsepol2
libsmartcols1
libss2
libstdc++6
libsystemd0
libtasn1-6
libtinfo6
libudev1
libunistring2
libuuid1
libxxhash0
libzstd1
login
logsave
mawk
mount
ncurses-base
ncurses-bin
openssl
passwd
perl-base
sed
sysvinit-utils
tar
tzdata
usr-is-merged
util-linux
util-linux-extra
zlib1g
```

</details>

### `memcached`

- DHI: `ghcr.io/peslaio/memcached:1.6-bookworm` (2 packages)
- Upstream: `memcached:1.6-bookworm` (93 packages)
- Common packages: 1
- DHI-only packages: 1
- Upstream-only packages: 92

<details>
<summary>DHI-only packages</summary>

```text
memcached
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
adduser
apt
base-files
base-passwd
bash
bsdutils
coreutils
dash
debconf
debian-archive-keyring
debianutils
diffutils
dpkg
e2fsprogs
findutils
gcc-12-base
gpgv
grep
gzip
hostname
init-system-helpers
libacl1
libapt-pkg6.0
libattr1
libaudit-common
libaudit1
libblkid1
libbz2-1.0
libc-bin
libcap-ng0
libcap2
libcom-err2
libcrypt1
libdb5.3
libdebconfclient0
libevent-2.1-7
libext2fs2
libffi8
libgcc-s1
libgcrypt20
libgmp10
libgnutls30
libgpg-error0
libhogweed6
libidn2-0
liblz4-1
liblzma5
libmd0
libmount1
libnettle8
libp11-kit0
libpam-modules
libpam-modules-bin
libpam-runtime
libpam0g
libpcre2-8-0
libsasl2-2
libsasl2-modules
libsasl2-modules-db
libseccomp2
libselinux1
libsemanage-common
libsemanage2
libsepol2
libsmartcols1
libss2
libssl3
libstdc++6
libsystemd0
libtasn1-6
libtinfo6
libudev1
libunistring2
libuuid1
libxxhash0
libzstd1
login
logsave
mawk
mount
ncurses-base
ncurses-bin
passwd
perl-base
sed
sysvinit-utils
tar
tzdata
usr-is-merged
util-linux
util-linux-extra
zlib1g
```

</details>

### `nginx`

- DHI: `ghcr.io/peslaio/nginx:1.22-bookworm` (7 packages)
- Upstream: `nginx:1.22` (142 packages)
- Common packages: 5
- DHI-only packages: 2
- Upstream-only packages: 137

<details>
<summary>DHI-only packages</summary>

```text
libssl3
nginx-common
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
adduser
apt
base-files
base-passwd
bash
bsdutils
coreutils
curl
dash
debconf
debian-archive-keyring
debianutils
diffutils
dpkg
e2fsprogs
findutils
fontconfig-config
fonts-dejavu-core
gcc-10-base
gcc-9-base
gettext-base
gpgv
grep
gzip
hostname
init-system-helpers
libacl1
libapt-pkg6.0
libattr1
libaudit-common
libaudit1
libblkid1
libbrotli1
libbsd0
libbz2-1.0
libc-bin
libcap-ng0
libcom-err2
libcurl4
libdb5.3
libdebconfclient0
libdeflate0
libexpat1
libext2fs2
libffi7
libfontconfig1
libfreetype6
libgcc-s1
libgcrypt20
libgd3
libgeoip1
libgmp10
libgnutls30
libgpg-error0
libgssapi-krb5-2
libhogweed6
libicu67
libidn2-0
libjbig0
libjpeg62-turbo
libk5crypto3
libkeyutils1
libkrb5-3
libkrb5support0
libldap-2.4-2
liblz4-1
liblzma5
libmd0
libmount1
libnettle8
libnghttp2-14
libnsl2
libp11-kit0
libpam-modules
libpam-modules-bin
libpam-runtime
libpam0g
libpcre2-8-0
libpcre3
libpng16-16
libpsl5
libreadline8
librtmp1
libsasl2-2
libsasl2-modules-db
libseccomp2
libselinux1
libsemanage-common
libsemanage1
libsepol1
libsmartcols1
libss2
libssh2-1
libssl1.1
libstdc++6
libsystemd0
libtasn1-6
libtiff5
libtinfo6
libtirpc-common
libtirpc3
libudev1
libunistring2
libuuid1
libwebp6
libx11-6
libx11-data
libxau6
libxcb1
libxdmcp6
libxml2
libxpm4
libxslt1.1
libxxhash0
libzstd1
login
logsave
lsb-base
mawk
mount
ncurses-base
ncurses-bin
nginx-module-geoip
nginx-module-image-filter
nginx-module-njs
nginx-module-xslt
openssl
passwd
perl-base
readline-common
sed
sensible-utils
sysvinit-utils
tar
tzdata
ucf
util-linux
```

</details>

### `php-fpm`

- DHI: `ghcr.io/peslaio/php-fpm:8.2-bookworm` (10 packages)
- Upstream: `php:8.2-fpm-bookworm` (173 packages)
- Common packages: 8
- DHI-only packages: 2
- Upstream-only packages: 165

<details>
<summary>DHI-only packages</summary>

```text
php8.2-common
php8.2-fpm
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
adduser
apt
autoconf
base-files
base-passwd
bash
binutils
binutils-common
binutils-x86-64-linux-gnu
bsdutils
bzip2
coreutils
cpp
cpp-12
curl
dash
debconf
debian-archive-keyring
debianutils
diffutils
dpkg
dpkg-dev
e2fsprogs
file
findutils
g++
g++-12
gcc
gcc-12
gcc-12-base
gpgv
grep
gzip
hostname
init-system-helpers
libacl1
libapt-pkg6.0
libargon2-1
libasan8
libatomic1
libattr1
libaudit-common
libaudit1
libbinutils
libblkid1
libbrotli1
libbz2-1.0
libc-bin
libc-dev-bin
libc6-dev
libcap-ng0
libcc1-0
libcom-err2
libcrypt-dev
libcrypt1
libctf-nobfd0
libctf0
libcurl4
libdb5.3
libdebconfclient0
libdpkg-perl
libext2fs2
libffi8
libgcc-12-dev
libgcrypt20
libgdbm-compat4
libgdbm6
libgmp10
libgnutls30
libgomp1
libgprofng0
libgssapi-krb5-2
libhogweed6
libicu72
libidn2-0
libisl23
libitm1
libjansson4
libk5crypto3
libkeyutils1
libkrb5-3
libkrb5support0
libldap-2.5-0
liblsan0
liblz4-1
libmagic-mgc
libmagic1
libmd0
libmount1
libmpc3
libmpfr6
libnettle8
libnghttp2-14
libnsl-dev
libnsl2
libonig5
libp11-kit0
libpam-modules
libpam-modules-bin
libpam-runtime
libpam0g
libpcre2-8-0
libperl5.36
libpkgconf3
libpsl5
libquadmath0
libreadline8
librtmp1
libsasl2-2
libsasl2-modules-db
libseccomp2
libselinux1
libsemanage-common
libsemanage2
libsepol2
libsmartcols1
libsodium23
libsqlite3-0
libss2
libssh2-1
libssl3
libstdc++-12-dev
libstdc++6
libsystemd0
libtasn1-6
libtinfo6
libtirpc-common
libtirpc-dev
libtirpc3
libtsan2
libubsan1
libudev1
libunistring2
libuuid1
libxml2
libxxhash0
libzstd1
linux-libc-dev
login
logsave
m4
make
mawk
mount
ncurses-base
ncurses-bin
openssl
passwd
patch
perl
perl-base
perl-modules-5.36
pkg-config
pkgconf
pkgconf-bin
re2c
readline-common
rpcsvc-proto
sed
sysvinit-utils
tar
usr-is-merged
util-linux
util-linux-extra
xz-utils
```

</details>

### `redis`

- DHI: `ghcr.io/peslaio/redis:7.0-bookworm` (7 packages)
- Upstream: `redis:7.0-bookworm` (89 packages)
- Common packages: 5
- DHI-only packages: 2
- Upstream-only packages: 84

<details>
<summary>DHI-only packages</summary>

```text
redis-server
redis-tools
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
adduser
apt
base-files
base-passwd
bash
bsdutils
coreutils
dash
debconf
debian-archive-keyring
debianutils
diffutils
dpkg
e2fsprogs
findutils
gcc-12-base
gpgv
grep
gzip
hostname
init-system-helpers
libacl1
libapt-pkg6.0
libattr1
libaudit-common
libaudit1
libblkid1
libbz2-1.0
libc-bin
libcap-ng0
libcom-err2
libcrypt1
libdb5.3
libdebconfclient0
libext2fs2
libffi8
libgcrypt20
libgmp10
libgnutls30
libhogweed6
libidn2-0
liblz4-1
libmd0
libmount1
libnettle8
libp11-kit0
libpam-modules
libpam-modules-bin
libpam-runtime
libpam0g
libpcre2-8-0
libseccomp2
libselinux1
libsemanage-common
libsemanage2
libsepol2
libsmartcols1
libss2
libssl3
libstdc++6
libsystemd0
libtasn1-6
libtinfo6
libudev1
libunistring2
libuuid1
libxxhash0
libzstd1
login
logsave
mawk
mount
ncurses-base
ncurses-bin
passwd
perl-base
sed
sysvinit-utils
tar
tzdata
usr-is-merged
util-linux
util-linux-extra
zlib1g
```

</details>

### `node`

- DHI: `ghcr.io/tpesla/node:18-bookworm` (111 packages)
- Upstream: `node:18-bookworm` (413 packages)
- Common packages: 98
- DHI-only packages: 13
- Upstream-only packages: 315

<details>
<summary>DHI-only packages</summary>

```text
libc-ares2
libfile-find-rule-perl
libnode108
libnumber-compare-perl
libtext-glob-perl
libuv1
node-acorn
node-busboy
node-cjs-module-lexer
node-undici
node-xtend
nodejs
usrmerge
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
autoconf
automake
autotools-dev
binutils
binutils-common
binutils-x86-64-linux-gnu
bzip2
comerr-dev
cpp
cpp-12
curl
default-libmysqlclient-dev
dirmngr
dpkg-dev
file
fontconfig
fontconfig-config
fonts-dejavu-core
g++
g++-12
gcc
gcc-12
gir1.2-freedesktop
gir1.2-gdkpixbuf-2.0
gir1.2-glib-2.0
gir1.2-rsvg-2.0
git
git-man
gnupg
gnupg-l10n
gnupg-utils
gpg
gpg-agent
gpg-wks-client
gpg-wks-server
gpgconf
gpgsm
hicolor-icon-theme
icu-devtools
imagemagick
imagemagick-6-common
imagemagick-6.q16
krb5-multidev
libaom3
libapr1
libaprutil1
libasan8
libassuan0
libatomic1
libbinutils
libblkid-dev
libbrotli-dev
libbsd0
libbz2-dev
libc-dev-bin
libc6-dev
libcairo-gobject2
libcairo-script-interpreter2
libcairo2
libcairo2-dev
libcbor0.8
libcc1-0
libcrypt-dev
libctf-nobfd0
libctf0
libcurl3-gnutls
libcurl4
libcurl4-openssl-dev
libdatrie1
libdav1d6
libdb-dev
libdb5.3-dev
libde265-0
libdeflate-dev
libdeflate0
libdjvulibre-dev
libdjvulibre-text
libdjvulibre21
libdpkg-perl
libedit2
libelf1
liberror-perl
libevent-2.1-7
libevent-core-2.1-7
libevent-dev
libevent-extra-2.1-7
libevent-openssl-2.1-7
libevent-pthreads-2.1-7
libexif-dev
libexif12
libexpat1
libexpat1-dev
libffi-dev
libfftw3-double3
libfido2-1
libfontconfig-dev
libfontconfig1
libfreetype-dev
libfreetype6
libfreetype6-dev
libfribidi0
libgcc-12-dev
libgdbm-dev
libgdk-pixbuf-2.0-0
libgdk-pixbuf-2.0-dev
libgdk-pixbuf2.0-bin
libgdk-pixbuf2.0-common
libgirepository-1.0-1
libglib2.0-0
libglib2.0-bin
libglib2.0-data
libglib2.0-dev
libglib2.0-dev-bin
libgmp-dev
libgmpxx4ldbl
libgomp1
libgprofng0
libgraphite2-3
libgssapi-krb5-2
libgssrpc4
libharfbuzz0b
libheif1
libice-dev
libice6
libicu-dev
libimath-3-1-29
libimath-dev
libisl23
libitm1
libjansson4
libjbig-dev
libjbig0
libjpeg-dev
libjpeg62-turbo
libjpeg62-turbo-dev
libk5crypto3
libkadm5clnt-mit12
libkadm5srv-mit12
libkdb5-10
libkeyutils1
libkrb5-3
libkrb5-dev
libkrb5support0
libksba8
liblcms2-2
liblcms2-dev
libldap-2.5-0
liblerc-dev
liblerc4
liblqr-1-0
liblqr-1-0-dev
liblsan0
libltdl-dev
libltdl7
liblzma-dev
liblzo2-2
libmagic-mgc
libmagic1
libmagickcore-6-arch-config
libmagickcore-6-headers
libmagickcore-6.q16-6
libmagickcore-6.q16-6-extra
libmagickcore-6.q16-dev
libmagickcore-dev
libmagickwand-6-headers
libmagickwand-6.q16-6
libmagickwand-6.q16-dev
libmagickwand-dev
libmariadb-dev
libmariadb-dev-compat
libmariadb3
libmaxminddb-dev
libmaxminddb0
libmount-dev
libmpc3
libmpfr6
libncurses-dev
libncurses5-dev
libncurses6
libncursesw5-dev
libncursesw6
libnpth0
libnsl-dev
libnsl2
libnuma1
libopenexr-3-1-30
libopenexr-dev
libopenjp2-7
libopenjp2-7-dev
libpango-1.0-0
libpangocairo-1.0-0
libpangoft2-1.0-0
libpcre2-16-0
libpcre2-32-0
libpcre2-dev
libpcre2-posix3
libpixman-1-0
libpixman-1-dev
libpkgconf3
libpng-dev
libpng16-16
libpq-dev
libpq5
libproc2-0
libpsl5
libpthread-stubs0-dev
libpython3-stdlib
libpython3.11-minimal
libpython3.11-stdlib
libquadmath0
libreadline-dev
libreadline8
librsvg2-2
librsvg2-common
librsvg2-dev
librtmp1
libsasl2-2
libsasl2-modules-db
libselinux1-dev
libsepol-dev
libserf-1-1
libsm-dev
libsm6
libsqlite3-0
libsqlite3-dev
libssh2-1
libssl-dev
libstdc++-12-dev
libsvn1
libthai-data
libthai0
libtiff-dev
libtiff6
libtiffxx6
libtirpc-common
libtirpc-dev
libtirpc3
libtool
libtsan2
libubsan1
libutf8proc2
libwebp-dev
libwebp7
libwebpdemux2
libwebpmux3
libwmf-0.2-7
libwmf-dev
libwmflite-0.2-7
libx11-6
libx11-data
libx11-dev
libx265-199
libxau-dev
libxau6
libxcb-render0
libxcb-render0-dev
libxcb-shm0
libxcb-shm0-dev
libxcb1
libxcb1-dev
libxdmcp-dev
libxdmcp6
libxext-dev
libxext6
libxml2
libxml2-dev
libxrender-dev
libxrender1
libxslt1-dev
libxslt1.1
libxt-dev
libxt6
libyaml-0-2
libyaml-dev
libzstd-dev
linux-libc-dev
m4
make
mariadb-common
media-types
mercurial
mercurial-common
mysql-common
netbase
openssh-client
patch
pinentry-curses
pkg-config
pkgconf
pkgconf-bin
procps
python3
python3-distutils
python3-lib2to3
python3-minimal
python3.11
python3.11-minimal
readline-common
rpcsvc-proto
sensible-utils
shared-mime-info
sq
subversion
ucf
unzip
usr-is-merged
uuid-dev
wget
x11-common
x11proto-core-dev
x11proto-dev
xorg-sgml-doctools
xtrans-dev
xz-utils
zlib1g-dev
```

</details>

### `python`

- DHI: `ghcr.io/tpesla/python:3.11-bookworm` (121 packages)
- Upstream: `python:3.11-bookworm` (429 packages)
- Common packages: 116
- DHI-only packages: 5
- Upstream-only packages: 313

<details>
<summary>DHI-only packages</summary>

```text
libfile-find-rule-perl
libnumber-compare-perl
libtext-glob-perl
python-is-python3
usrmerge
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
autoconf
automake
autotools-dev
binutils
binutils-common
binutils-x86-64-linux-gnu
bzip2
comerr-dev
cpp
cpp-12
curl
default-libmysqlclient-dev
dirmngr
dpkg-dev
file
fontconfig
fontconfig-config
fonts-dejavu-core
g++
g++-12
gcc
gcc-12
gir1.2-freedesktop
gir1.2-gdkpixbuf-2.0
gir1.2-glib-2.0
gir1.2-rsvg-2.0
git
git-man
gnupg
gnupg-l10n
gnupg-utils
gpg
gpg-agent
gpg-wks-client
gpg-wks-server
gpgconf
gpgsm
hicolor-icon-theme
icu-devtools
imagemagick
imagemagick-6-common
imagemagick-6.q16
krb5-multidev
libaom3
libapr1
libaprutil1
libasan8
libassuan0
libatomic1
libbinutils
libblkid-dev
libbluetooth-dev
libbluetooth3
libbrotli-dev
libbrotli1
libbsd0
libbz2-dev
libc-dev-bin
libc6-dev
libcairo-gobject2
libcairo-script-interpreter2
libcairo2
libcairo2-dev
libcbor0.8
libcc1-0
libcrypt-dev
libctf-nobfd0
libctf0
libcurl3-gnutls
libcurl4
libcurl4-openssl-dev
libdatrie1
libdav1d6
libdb-dev
libdb5.3-dev
libde265-0
libdeflate-dev
libdeflate0
libdjvulibre-dev
libdjvulibre-text
libdjvulibre21
libdpkg-perl
libedit2
libelf1
liberror-perl
libevent-2.1-7
libevent-core-2.1-7
libevent-dev
libevent-extra-2.1-7
libevent-openssl-2.1-7
libevent-pthreads-2.1-7
libexif-dev
libexif12
libexpat1-dev
libffi-dev
libfftw3-double3
libfido2-1
libfontconfig-dev
libfontconfig1
libfreetype-dev
libfreetype6
libfreetype6-dev
libfribidi0
libgcc-12-dev
libgdbm-dev
libgdk-pixbuf-2.0-0
libgdk-pixbuf-2.0-dev
libgdk-pixbuf2.0-bin
libgdk-pixbuf2.0-common
libgirepository-1.0-1
libglib2.0-0
libglib2.0-bin
libglib2.0-data
libglib2.0-dev
libglib2.0-dev-bin
libgmp-dev
libgmpxx4ldbl
libgomp1
libgprofng0
libgraphite2-3
libgssrpc4
libharfbuzz0b
libheif1
libice-dev
libice6
libicu-dev
libicu72
libimath-3-1-29
libimath-dev
libisl23
libitm1
libjansson4
libjbig-dev
libjbig0
libjpeg-dev
libjpeg62-turbo
libjpeg62-turbo-dev
libkadm5clnt-mit12
libkadm5srv-mit12
libkdb5-10
libkrb5-dev
libksba8
liblcms2-2
liblcms2-dev
libldap-2.5-0
liblerc-dev
liblerc4
liblqr-1-0
liblqr-1-0-dev
liblsan0
libltdl-dev
libltdl7
liblzma-dev
liblzo2-2
libmagic-mgc
libmagic1
libmagickcore-6-arch-config
libmagickcore-6-headers
libmagickcore-6.q16-6
libmagickcore-6.q16-6-extra
libmagickcore-6.q16-dev
libmagickcore-dev
libmagickwand-6-headers
libmagickwand-6.q16-6
libmagickwand-6.q16-dev
libmagickwand-dev
libmariadb-dev
libmariadb-dev-compat
libmariadb3
libmaxminddb-dev
libmaxminddb0
libmount-dev
libmpc3
libmpfr6
libncurses-dev
libncurses5-dev
libncurses6
libncursesw5-dev
libnghttp2-14
libnpth0
libnsl-dev
libnuma1
libopenexr-3-1-30
libopenexr-dev
libopenjp2-7
libopenjp2-7-dev
libpango-1.0-0
libpangocairo-1.0-0
libpangoft2-1.0-0
libpcre2-16-0
libpcre2-32-0
libpcre2-dev
libpcre2-posix3
libpixman-1-0
libpixman-1-dev
libpkgconf3
libpng-dev
libpng16-16
libpq-dev
libpq5
libproc2-0
libpsl5
libpthread-stubs0-dev
libquadmath0
libreadline-dev
librsvg2-2
librsvg2-common
librsvg2-dev
librtmp1
libsasl2-2
libsasl2-modules-db
libselinux1-dev
libsepol-dev
libserf-1-1
libsm-dev
libsm6
libsqlite3-dev
libssh2-1
libssl-dev
libstdc++-12-dev
libsvn1
libtcl8.6
libthai-data
libthai0
libtiff-dev
libtiff6
libtiffxx6
libtirpc-dev
libtk8.6
libtool
libtsan2
libubsan1
libutf8proc2
libwebp-dev
libwebp7
libwebpdemux2
libwebpmux3
libwmf-0.2-7
libwmf-dev
libwmflite-0.2-7
libx11-6
libx11-data
libx11-dev
libx265-199
libxau-dev
libxau6
libxcb-render0
libxcb-render0-dev
libxcb-shm0
libxcb-shm0-dev
libxcb1
libxcb1-dev
libxdmcp-dev
libxdmcp6
libxext-dev
libxext6
libxft-dev
libxft2
libxml2
libxml2-dev
libxrender-dev
libxrender1
libxslt1-dev
libxslt1.1
libxss-dev
libxss1
libxt-dev
libxt6
libyaml-0-2
libyaml-dev
libzstd-dev
linux-libc-dev
m4
make
mariadb-common
mercurial
mercurial-common
mysql-common
netbase
openssh-client
patch
pinentry-curses
pkg-config
pkgconf
pkgconf-bin
procps
python3-distutils
python3-lib2to3
rpcsvc-proto
sensible-utils
shared-mime-info
sq
subversion
tcl
tcl-dev
tcl8.6
tcl8.6-dev
tk
tk-dev
tk8.6
tk8.6-dev
ucf
unzip
usr-is-merged
uuid-dev
wget
x11-common
x11proto-core-dev
x11proto-dev
xorg-sgml-doctools
xtrans-dev
xz-utils
zlib1g-dev
```

</details>

### `java-jre`

- DHI: `ghcr.io/tpesla/java-jre:17-bookworm` (130 packages)
- Upstream: `eclipse-temurin:17-jre` (140 packages)
- Common packages: 90
- DHI-only packages: 40
- Upstream-only packages: 50

<details>
<summary>DHI-only packages</summary>

```text
ca-certificates-java
debian-archive-keyring
gcc-12-base
java-common
libapt-pkg6.0
libasound2
libasound2-data
libavahi-client3
libavahi-common-data
libavahi-common3
libcap2
libcups2
libdb5.3
libdbus-1-3
libext2fs2
libfile-find-rule-perl
libgdbm-compat4
libgdbm6
libglib2.0-0
libgnutls30
libgraphite2-3
libharfbuzz0b
libhogweed6
libjpeg62-turbo
liblcms2-2
libnettle8
libnspr4
libnss3
libnumber-compare-perl
libpcsclite1
libperl5.36
libpng16-16
libssl3
libtext-glob-perl
libunistring2
openjdk-17-jre-headless
perl
perl-modules-5.36
usrmerge
util-linux-extra
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
coreutils-from-uutils
curl
dirmngr
fontconfig
fonts-dejavu-mono
gcc-16-base
gnu-coreutils
gnupg
gpg
gpg-agent
gpgconf
gpgsm
libapt-pkg7.0
libassuan9
libbsd0
libc-gconv-modules-extra
libcurl4t64
libdb5.3t64
libext2fs2t64
libgnutls30t64
libhogweed6t64
libksba8
libldap-common
libldap2
libncursesw6
libnettle8t64
libnghttp2-14
libnpth0t64
libpng16-16t64
libproc2-0
libpsl5t64
libreadline8t64
librtmp1
libsasl2-2
libsasl2-modules-db
libssh2-1t64
libssl3t64
libunistring5
locales
login.defs
openssl-provider-legacy
p11-kit
p11-kit-modules
pinentry-curses
procps
readline-common
rust-coreutils
sensible-utils
ubuntu-keyring
wget
```

</details>

### `mariadb`

- DHI: `ghcr.io/tpesla/mariadb:10.11-bookworm` (142 packages)
- Upstream: `mariadb:10.11` (151 packages)
- Common packages: 132
- DHI-only packages: 10
- Upstream-only packages: 19

<details>
<summary>DHI-only packages</summary>

```text
debian-archive-keyring
libbpf1
libfile-find-rule-perl
libnuma1
libnumber-compare-perl
libperl5.36
libproc2-0
libtext-glob-perl
perl-modules-5.36
util-linux-extra
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
gpg
gpgconf
libaio1
libassuan0
libbpf0
libjemalloc2
libpcre3
libperl5.34
libprocps8
libsqlite3-0
libtcmalloc-minimal4
lsb-base
mariadb-backup
perl-modules-5.34
pwgen
sensible-utils
ubuntu-keyring
xz-utils
zstd
```

</details>

### `postgresql`

- DHI: `ghcr.io/tpesla/postgresql:15-bookworm` (128 packages)
- Upstream: `postgres:15-bookworm` (144 packages)
- Common packages: 122
- DHI-only packages: 6
- Upstream-only packages: 22

<details>
<summary>DHI-only packages</summary>

```text
ca-certificates
libfile-find-rule-perl
libllvm14
libnumber-compare-perl
libtext-glob-perl
usrmerge
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
dirmngr
gnupg
gnupg-l10n
gnupg-utils
gpg
gpg-agent
gpg-wks-client
gpg-wks-server
gpgconf
gpgsm
less
libassuan0
libksba8
libllvm19
libncursesw6
libnpth0
libnss-wrapper
libsqlite3-0
pinentry-curses
usr-is-merged
xz-utils
zstd
```

</details>

### `mongodb`

- DHI: `ghcr.io/tpesla/mongodb:8.0-bookworm` (115 packages)
- Upstream: `mongo:8.0` (128 packages)
- Common packages: 91
- DHI-only packages: 24
- Upstream-only packages: 37

<details>
<summary>DHI-only packages</summary>

```text
debian-archive-keyring
gcc-12-base
libapt-pkg6.0
libcurl4
libdb5.3
libext2fs2
libfile-find-rule-perl
libgdbm-compat4
libgdbm6
libgnutls30
libhogweed6
libldap-2.5-0
libnettle8
libnumber-compare-perl
libperl5.36
libpsl5
libssh2-1
libssl3
libtext-glob-perl
libunistring2
perl
perl-modules-5.36
usrmerge
util-linux-extra
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
gcc-14-base
jq
krb5-locales
libapt-pkg6.0t64
libassuan0
libcurl4t64
libdb5.3t64
libext2fs2t64
libgnutls30t64
libhogweed6t64
libjq1
libldap-common
libldap2
libncursesw6
libnettle8t64
libnpth0t64
libnuma1
libonig5
libproc2-0
libpsl5t64
libsasl2-modules
libssh-4
libssl3t64
libunistring5
mongodb-database-tools
mongodb-org
mongodb-org-database
mongodb-org-database-tools-extra
mongodb-org-mongos
mongodb-org-shell
mongodb-org-tools
numactl
procps
publicsuffix
sensible-utils
ubuntu-keyring
unminimize
```

</details>

### `rabbitmq`

- DHI: `ghcr.io/tpesla/rabbitmq:3.10-bookworm` (147 packages)
- Upstream: `rabbitmq:3.10` (105 packages)
- Common packages: 99
- DHI-only packages: 48
- Upstream-only packages: 6

<details>
<summary>DHI-only packages</summary>

```text
cron
cron-daemon-common
debian-archive-keyring
erlang-asn1
erlang-base
erlang-crypto
erlang-eldap
erlang-ftp
erlang-inets
erlang-mnesia
erlang-os-mon
erlang-parsetools
erlang-public-key
erlang-runtime-tools
erlang-snmp
erlang-ssl
erlang-syntax-tools
erlang-tftp
erlang-tools
erlang-xmerl
libexpat1
libfile-find-rule-perl
libgdbm-compat4
libgdbm6
libmd0
libnumber-compare-perl
libperl5.36
libpopt0
libproc2-0
libpython3-stdlib
libpython3.11-minimal
libpython3.11-stdlib
libreadline8
libsqlite3-0
libtext-glob-perl
libwrap0
logrotate
media-types
perl
perl-modules-5.36
python3
python3-minimal
python3.11
python3.11-minimal
rabbitmq-server
readline-common
socat
util-linux-extra
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
gosu
libncurses6
libpcre3
libprocps8
lsb-base
ubuntu-keyring
```

</details>

### `dotnet-runtime-8.0`

- DHI: `ghcr.io/tpesla/dotnet-runtime:8.0-bookworm` (109 packages)
- Upstream: `mcr.microsoft.com/dotnet/runtime:8.0` (92 packages)
- Common packages: 91
- DHI-only packages: 18
- Upstream-only packages: 1

<details>
<summary>DHI-only packages</summary>

```text
dotnet-host
dotnet-hostfxr-8.0
dotnet-runtime-8.0
dotnet-runtime-deps-8.0
libfile-find-rule-perl
libgdbm-compat4
libgdbm6
libgssapi-krb5-2
libk5crypto3
libkeyutils1
libkrb5-3
libkrb5support0
libnumber-compare-perl
libperl5.36
libtext-glob-perl
perl
perl-modules-5.36
usrmerge
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
usr-is-merged
```

</details>

### `dotnet-runtime-9.0`

- DHI: `ghcr.io/tpesla/dotnet-runtime:9.0-bookworm` (109 packages)
- Upstream: `mcr.microsoft.com/dotnet/runtime:9.0` (92 packages)
- Common packages: 91
- DHI-only packages: 18
- Upstream-only packages: 1

<details>
<summary>DHI-only packages</summary>

```text
dotnet-host
dotnet-hostfxr-9.0
dotnet-runtime-9.0
dotnet-runtime-deps-9.0
libfile-find-rule-perl
libgdbm-compat4
libgdbm6
libgssapi-krb5-2
libk5crypto3
libkeyutils1
libkrb5-3
libkrb5support0
libnumber-compare-perl
libperl5.36
libtext-glob-perl
perl
perl-modules-5.36
usrmerge
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
usr-is-merged
```

</details>

### `dotnet-runtime-10.0`

- DHI: `ghcr.io/tpesla/dotnet-runtime:10.0-bookworm` (109 packages)
- Upstream: `mcr.microsoft.com/dotnet/runtime:10.0` (97 packages)
- Common packages: 78
- DHI-only packages: 31
- Upstream-only packages: 19

<details>
<summary>DHI-only packages</summary>

```text
adduser
debian-archive-keyring
dotnet-host
dotnet-hostfxr-10.0
dotnet-runtime-10.0
dotnet-runtime-deps-10.0
gcc-12-base
libapt-pkg6.0
libdb5.3
libext2fs2
libfile-find-rule-perl
libgdbm-compat4
libgdbm6
libgnutls30
libgssapi-krb5-2
libhogweed6
libicu72
libk5crypto3
libkeyutils1
libkrb5-3
libkrb5support0
libnettle8
libnumber-compare-perl
libperl5.36
libssl3
libtext-glob-perl
libunistring2
perl
perl-modules-5.36
usrmerge
util-linux-extra
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
gcc-14-base
libapt-pkg6.0t64
libassuan0
libdb5.3t64
libext2fs2t64
libgnutls30t64
libhogweed6t64
libicu74
libncursesw6
libnettle8t64
libnpth0t64
libproc2-0
libssl3t64
libunistring5
procps
sensible-utils
tzdata-legacy
ubuntu-keyring
unminimize
```

</details>

### `dotnet-aspnet-8.0`

- DHI: `ghcr.io/tpesla/dotnet-aspnet:8.0-bookworm` (110 packages)
- Upstream: `mcr.microsoft.com/dotnet/aspnet:8.0` (92 packages)
- Common packages: 91
- DHI-only packages: 19
- Upstream-only packages: 1

<details>
<summary>DHI-only packages</summary>

```text
aspnetcore-runtime-8.0
dotnet-host
dotnet-hostfxr-8.0
dotnet-runtime-8.0
dotnet-runtime-deps-8.0
libfile-find-rule-perl
libgdbm-compat4
libgdbm6
libgssapi-krb5-2
libk5crypto3
libkeyutils1
libkrb5-3
libkrb5support0
libnumber-compare-perl
libperl5.36
libtext-glob-perl
perl
perl-modules-5.36
usrmerge
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
usr-is-merged
```

</details>

### `dotnet-aspnet-9.0`

- DHI: `ghcr.io/tpesla/dotnet-aspnet:9.0-bookworm` (110 packages)
- Upstream: `mcr.microsoft.com/dotnet/aspnet:9.0` (92 packages)
- Common packages: 91
- DHI-only packages: 19
- Upstream-only packages: 1

<details>
<summary>DHI-only packages</summary>

```text
aspnetcore-runtime-9.0
dotnet-host
dotnet-hostfxr-9.0
dotnet-runtime-9.0
dotnet-runtime-deps-9.0
libfile-find-rule-perl
libgdbm-compat4
libgdbm6
libgssapi-krb5-2
libk5crypto3
libkeyutils1
libkrb5-3
libkrb5support0
libnumber-compare-perl
libperl5.36
libtext-glob-perl
perl
perl-modules-5.36
usrmerge
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
usr-is-merged
```

</details>

### `dotnet-aspnet-10.0`

- DHI: `ghcr.io/tpesla/dotnet-aspnet:10.0-bookworm` (110 packages)
- Upstream: `mcr.microsoft.com/dotnet/aspnet:10.0` (97 packages)
- Common packages: 78
- DHI-only packages: 32
- Upstream-only packages: 19

<details>
<summary>DHI-only packages</summary>

```text
adduser
aspnetcore-runtime-10.0
debian-archive-keyring
dotnet-host
dotnet-hostfxr-10.0
dotnet-runtime-10.0
dotnet-runtime-deps-10.0
gcc-12-base
libapt-pkg6.0
libdb5.3
libext2fs2
libfile-find-rule-perl
libgdbm-compat4
libgdbm6
libgnutls30
libgssapi-krb5-2
libhogweed6
libicu72
libk5crypto3
libkeyutils1
libkrb5-3
libkrb5support0
libnettle8
libnumber-compare-perl
libperl5.36
libssl3
libtext-glob-perl
libunistring2
perl
perl-modules-5.36
usrmerge
util-linux-extra
```

</details>

<details>
<summary>Upstream-only packages</summary>

```text
gcc-14-base
libapt-pkg6.0t64
libassuan0
libdb5.3t64
libext2fs2t64
libgnutls30t64
libhogweed6t64
libicu74
libncursesw6
libnettle8t64
libnpth0t64
libproc2-0
libssl3t64
libunistring5
procps
sensible-utils
tzdata-legacy
ubuntu-keyring
unminimize
```

</details>

## Interpretation

- Runtime-closure images (`apache`, `caddy`, `haproxy`, `memcached`, `nginx`, `php-fpm`, `redis`) have a much smaller package surface than regular upstream images.
- Full-rootfs images still carry Debian minbase/runtime dependency trees. They need runtime-closure work before they should receive the same quality score as the minimized images.
- Images still sourced from `ghcr.io/tpesla/*` need to be republished under `ghcr.io/peslaio/*` if the organization namespace is now canonical.
