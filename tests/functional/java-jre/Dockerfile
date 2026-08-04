ARG RUNTIME_IMAGE=scratch
ARG JAVA_BUILDER_IMAGE=scratch

FROM --platform=$BUILDPLATFORM ${JAVA_BUILDER_IMAGE} AS build
WORKDIR /src
COPY App.java /src/App.java
RUN mkdir -p /classes /out \
    && javac --release 17 -d /classes /src/App.java \
    && jar --create --file /out/app.jar --main-class App -C /classes .

FROM ${RUNTIME_IMAGE}
ARG DHI_SOURCE_IMAGE_ID=unknown
LABEL io.pesla.dhi.functional.source-image-id="${DHI_SOURCE_IMAGE_ID}"
COPY --from=build --chown=10001:0 --chmod=0444 /out/app.jar /app/app.jar
COPY --chown=10001:0 --chmod=0444 app.properties /app/app.properties
CMD ["/usr/bin/java", "-jar", "/app/app.jar"]
