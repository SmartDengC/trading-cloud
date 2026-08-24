# syntax=docker/dockerfile:1

FROM golang:1.24.8-alpine AS builder

ARG MINIO_VERSION=RELEASE.2025-10-15T17-29-55Z
ARG GOPROXY=https://proxy.golang.org,direct
ENV CGO_ENABLED=0 \
    GOPROXY=${GOPROXY}

RUN apk add --no-cache ca-certificates git
RUN go install -v "github.com/minio/minio@${MINIO_VERSION}"

FROM alpine:3.22

RUN apk add --no-cache ca-certificates curl tzdata \
    && addgroup -g 10001 minio \
    && adduser -D -H -u 10001 -G minio minio \
    && mkdir -p /data \
    && chown 10001:10001 /data

COPY --from=builder /go/bin/minio /usr/bin/minio

ENV MINIO_UPDATE=off
EXPOSE 9000 9001
VOLUME ["/data"]
USER 10001:10001
ENTRYPOINT ["minio"]
