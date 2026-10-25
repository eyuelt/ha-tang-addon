ARG BUILD_FROM
FROM $BUILD_FROM

# The base image's s6-overlay /init otherwise runs CMD with an emptied environment, which would drop
# SUPERVISOR_TOKEN.
ENV S6_KEEP_ENV=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tang-common python3 python3-aiohttp \
    && rm -rf /var/lib/apt/lists/*

COPY app /app
WORKDIR /app
CMD ["python3", "-m", "tang_monitor"]
