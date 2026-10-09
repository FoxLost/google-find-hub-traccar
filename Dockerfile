FROM python:3.11.11-slim-bookworm
ARG VERSION=dev


LABEL org.opencontainers.image.title="Google Find Hub Traccar Relay" \
      org.opencontainers.image.description="Persistent Google Find Hub to Traccar OsmAnd relay" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/FoxLost/google-find-hub-traccar" \
      org.opencontainers.image.documentation="https://github.com/FoxLost/google-find-hub-traccar#readme" \
      org.opencontainers.image.licenses="GPL-3.0-only"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    TMPDIR=/tmp

RUN groupadd --gid 10001 relay \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/relay --shell /usr/sbin/nologin relay \
    && install --directory --owner=10001 --group=10001 /app /data

WORKDIR /app

# Keep dependency installation cacheable while requiring the small runtime set.
COPY requirements-runtime.txt /tmp/requirements-runtime.txt
RUN python -m pip install --no-cache-dir --requirement /tmp/requirements-runtime.txt \
    && rm -f /tmp/requirements-runtime.txt

COPY --chown=10001:10001 LICENSE /app/LICENSE
COPY --chown=10001:10001 Auth /app/Auth
COPY --chown=10001:10001 FMDNCrypto /app/FMDNCrypto
COPY --chown=10001:10001 KeyBackup /app/KeyBackup
COPY --chown=10001:10001 NovaApi /app/NovaApi
COPY --chown=10001:10001 ProtoDecoders /app/ProtoDecoders
COPY --chown=10001:10001 SpotApi /app/SpotApi
COPY --chown=10001:10001 findhub_relay /app/findhub_relay
COPY --chmod=0755 bin/findhub-relay /usr/local/bin/findhub-relay

VOLUME ["/data"]
USER 10001:10001

ENTRYPOINT ["findhub-relay"]
CMD ["daemon"]
HEALTHCHECK --interval=30s --timeout=10s --start-period=2m --retries=3 \
    CMD ["findhub-relay", "healthcheck"]
