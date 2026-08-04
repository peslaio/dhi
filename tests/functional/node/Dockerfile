ARG RUNTIME_IMAGE=scratch
FROM ${RUNTIME_IMAGE}
ARG DHI_SOURCE_IMAGE_ID=unknown
LABEL io.pesla.dhi.functional.source-image-id="${DHI_SOURCE_IMAGE_ID}"

COPY --chown=10001:0 --chmod=0444 app-config.json server.js /app/
CMD ["/usr/bin/node", "/app/server.js"]
