ARG RUNTIME_IMAGE=scratch
FROM ${RUNTIME_IMAGE}
ARG DHI_SOURCE_IMAGE_ID=unknown
LABEL io.pesla.dhi.functional.source-image-id="${DHI_SOURCE_IMAGE_ID}"

COPY --chown=0:0 --chmod=0555 verify.sh /usr/local/bin/verify.sh
CMD ["/usr/bin/mongod", "--config", "/etc/mongodb/mongodb.conf"]
