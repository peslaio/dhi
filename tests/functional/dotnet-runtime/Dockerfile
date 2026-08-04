ARG RUNTIME_IMAGE=scratch
ARG DOTNET_VERSION=10.0
ARG DOTNET_SDK_IMAGE=scratch

FROM --platform=$BUILDPLATFORM ${DOTNET_SDK_IMAGE} AS build
ARG DOTNET_VERSION
WORKDIR /src
COPY RuntimeProbe.csproj Program.cs ./
RUN dotnet publish RuntimeProbe.csproj \
      --configuration Release \
      --output /out \
      --no-self-contained \
      -p:DhiTargetFramework=${DOTNET_VERSION}

FROM ${RUNTIME_IMAGE}
ARG DHI_SOURCE_IMAGE_ID=unknown
LABEL io.pesla.dhi.functional.source-image-id="${DHI_SOURCE_IMAGE_ID}"
COPY --from=build --chown=10001:0 /out/ /app/
ENV DOTNET_EnableDiagnostics=0
CMD ["/usr/bin/dotnet", "/app/RuntimeProbe.dll"]
