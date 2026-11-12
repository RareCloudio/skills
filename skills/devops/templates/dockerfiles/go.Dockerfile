# Go service built into one static binary and run on a distroless base (no shell, no package
# manager, a non-root user built in). Copy to the project root as `Dockerfile`, next to the
# `.dockerignore` template.
#
# Placeholders (sample values in brackets, used when this file is checked):
#   <GO_VERSION>  Go line of the build image, at least the go line of go.mod; a tag the
#                 publisher keeps rebuilding (references/first-deploy.md, "Image tags") [1.26]
#   <MAIN_PKG>    package to build, relative to the module root [.]
#   <PORT>        port the service listens on inside the container [8080]
#
# The base has no shell and no curl, so the health check runs the binary itself: the service
# needs a flag that probes its own health endpoint and exits 0 or 1 (here `-healthcheck`).
# Without one, drop the HEALTHCHECK and check health from Compose or the proxy instead.

FROM golang:<GO_VERSION>-trixie AS build
WORKDIR /src
# go.sum* matches nothing in a module without dependencies; the build still goes on.
COPY go.mod go.sum* ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
# CGO_ENABLED=0: with cgo on (the default when a C compiler is present, as in this image) a
# program that uses net links against glibc, and the static base below cannot start it.
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/server <MAIN_PKG>

FROM gcr.io/distroless/static-debian13:nonroot
COPY --from=build /out/server /server
USER nonroot:nonroot
ENV PORT=<PORT>
EXPOSE <PORT>
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["/server", "-healthcheck"]
ENTRYPOINT ["/server"]
