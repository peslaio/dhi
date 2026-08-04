ARG RUNTIME_IMAGE=scratch
ARG JAVA_BUILDER_IMAGE=scratch

FROM --platform=$BUILDPLATFORM ${JAVA_BUILDER_IMAGE} AS build
WORKDIR /src
COPY App.java /src/App.java
RUN mkdir -p /out && javac --release 17 -d /out /src/App.java

FROM ${RUNTIME_IMAGE}
ARG DHI_SOURCE_IMAGE_ID=unknown
LABEL io.pesla.dhi.functional.source-image-id="${DHI_SOURCE_IMAGE_ID}"
COPY --from=build --chown=10001:0 --chmod=0444 /out/App.class /app/App.class
CMD ["/usr/bin/java", "-cp", "/app", "App"]
