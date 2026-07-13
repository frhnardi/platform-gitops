# syntax=docker/dockerfile:1
#
# Multi-stage build for the DeepSeek alert-RCA webhook (Python/FastAPI).
#   build stage   — installs pinned deps into a copyable tree
#   runtime stage — distroless python3 + nonroot (UID 65532): no shell, no pip
#
# This replaces the original "python:3.12-slim + pip install at container start +
# inline python -c heredoc" pattern, which ran as root on a writable rootfs and
# would violate the platform's own baseline policies. Now it ships like any other
# service: through the golden path, Trivy-scanned and keyless-signed. 3.11-slim
# is matched to the distroless python3-debian12 runtime (also 3.11).

FROM python:3.11-slim-bookworm AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt

FROM gcr.io/distroless/python3-debian12:nonroot AS runtime
WORKDIR /app
ENV PYTHONPATH=/deps PYTHONUNBUFFERED=1
COPY --from=build /deps /deps
COPY rca.py app.py ./
EXPOSE 8080
USER 65532:65532
ENTRYPOINT ["python", "app.py"]
