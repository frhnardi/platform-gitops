# syntax=docker/dockerfile:1
#
# Multi-stage build for the DORA exporter (Python).
#   build stage   — installs the pinned deps into a copyable tree
#   runtime stage — distroless python3 + nonroot (UID 65532): no shell, no pip,
#                   nothing to exec into
#
# Like every workload on this platform, this image is meant to ship THROUGH the
# golden path: Trivy scans it, cosign signs it keyless, Kyverno admits it only by
# that signature. Base images are re-pinned to a digest by the golden-path build.
# 3.11-slim is matched to the distroless python3-debian12 runtime (also 3.11) so
# the copied dependency tree is ABI-compatible.

FROM python:3.11-slim-bookworm AS build
WORKDIR /app
COPY requirements.txt .
# --target keeps everything in one directory we can copy onto distroless, where
# there is no pip and no writable site-packages.
RUN pip install --no-cache-dir --target=/deps -r requirements.txt

FROM gcr.io/distroless/python3-debian12:nonroot AS runtime
WORKDIR /app
ENV PYTHONPATH=/deps PYTHONUNBUFFERED=1
COPY --from=build /deps /deps
COPY leadtime.py exporter.py ./
EXPOSE 8080
USER 65532:65532
ENTRYPOINT ["python", "exporter.py"]
