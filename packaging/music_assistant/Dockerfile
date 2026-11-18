# Exact multi-architecture image index, verified to contain upstream commit
# 6ab5bfa63f02d0daa237d342097a42feae5c5aae. No floating tag or dependency install.
FROM ghcr.io/music-assistant/server@sha256:7eb272e2e13da9a5d61dcbc4e1fcfc734776222b23f2825a9b5690d4427cfafb

COPY patches /opt/alarmclock-patches
RUN /app/venv/bin/python /opt/alarmclock-patches/install.py

LABEL org.opencontainers.image.title="Music Assistant — HA-AlarmClock pinned" \
      org.opencontainers.image.source="https://github.com/DaFern/HA-Alarm-Clock" \
      io.hass.name="Music Assistant — HA-AlarmClock pinned" \
      io.hass.version="2.10.12-alarmclock.1"
# Inherit upstream's mass entrypoint and private /data volume. No startup Git,
# pip, updater, source downloads, shared database mounts or credential copies.
