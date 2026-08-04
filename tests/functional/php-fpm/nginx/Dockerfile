ARG NGINX_FIXTURE_IMAGE=scratch
FROM ${NGINX_FIXTURE_IMAGE}

COPY --chmod=0444 nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --chmod=0444 index.php /var/www/html/index.php
