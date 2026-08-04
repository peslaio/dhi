ARG RUNTIME_IMAGE=scratch
FROM ${RUNTIME_IMAGE}
ARG DHI_SOURCE_IMAGE_ID=unknown
LABEL io.pesla.dhi.functional.source-image-id="${DHI_SOURCE_IMAGE_ID}"

COPY --chown=0:0 --chmod=0640 nginx.conf /etc/nginx/nginx.conf
COPY --chown=10001:0 --chmod=0444 index.html /var/www/html/index.html
