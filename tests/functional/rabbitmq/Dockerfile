ARG RUNTIME_IMAGE=scratch
FROM ${RUNTIME_IMAGE}
ARG DHI_SOURCE_IMAGE_ID=unknown
LABEL io.pesla.dhi.functional.source-image-id="${DHI_SOURCE_IMAGE_ID}"

RUN if [ -e /var/lib/rabbitmq/.erlang.cookie ]; then \
        echo "source image must not contain a baked Erlang cookie" >&2; \
        exit 10; \
    fi

COPY --chown=0:0 --chmod=0640 rabbitmq.conf /etc/rabbitmq/rabbitmq.conf
COPY --chown=0:0 --chmod=0555 start.sh /usr/local/bin/start.sh
CMD ["/usr/local/bin/start.sh"]
