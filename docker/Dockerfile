FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
ARG APT_CHANNEL=nightly

# Install runtime and repository prerequisites
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    jq \
    tzdata \
    procps \
    sudo \
    gosu \
    mariadb-client \
    ffmpeg \
    openssl \
    && rm -rf /var/lib/apt/lists/*

# Add INDI Allsky APT repository keyring and source
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://apt.indi-allsky.org/key.gpg | gpg --dearmor -o /etc/apt/keyrings/indi-allsky.gpg \
    && chmod a+r /etc/apt/keyrings/indi-allsky.gpg \
    && printf "Types: deb\nURIs: https://apt.indi-allsky.org\nSuites: bookworm\nComponents: %s\nSigned-By: /etc/apt/keyrings/indi-allsky.gpg\n" "${APT_CHANNEL}" > /etc/apt/sources.list.d/indi-allsky.sources

# Install indi-allsky and 3rd-party camera drivers
RUN apt-get update && apt-get install -y \
    indi-allsky \
    indi-3rdparty \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Configure execution environment
ENV VIRTUAL_ENV=/var/lib/indi-allsky/venv
ENV PATH="/var/lib/indi-allsky/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENV INDIALLSKY_DOCKER=1
ENV PYTHONUNBUFFERED=1
ENV GUNICORN_ERROR_LOG_HANDLER=wsgi
ENV FLASK_APP=app.py

WORKDIR /usr/share/indi-allsky

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
