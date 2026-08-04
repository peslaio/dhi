ARG RUNTIME_IMAGE=scratch
FROM ${RUNTIME_IMAGE}
ARG DHI_SOURCE_IMAGE_ID=unknown
LABEL io.pesla.dhi.functional.source-image-id="${DHI_SOURCE_IMAGE_ID}"

COPY --chown=0:0 --chmod=0555 start.sh verify.sh /usr/local/bin/
CMD ["/usr/local/bin/start.sh"]
