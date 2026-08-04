ARG PYTHON_IMAGE=scratch
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /harness
COPY --chmod=0555 probe.py /harness/probe.py

USER 65532:65532
ENTRYPOINT ["python", "/harness/probe.py"]
