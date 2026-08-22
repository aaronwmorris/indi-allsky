# syntax=docker/dockerfile:1
# Universal indi-allsky Container Image
# Pulls pre-compiled .deb package from GitHub Releases or builds locally.

ARG BASE_IMAGE=debian:bookworm-slim
FROM ${BASE_IMAGE}

ARG TARGETARCH
ARG RELEASE_TAG="latest"
ARG GITHUB_REPO="aaronwmorris/indi-allsky"
ARG TZ=UTC
ARG DEBIAN_FRONTEND=noninteractive

USER root

# Install foundational runtime utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    jq \
    sudo \
    tzdata \
    locales \
    procps \
    iproute2 \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && dpkg-reconfigure -f noninteractive tzdata \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/*

# Intel VA-API video acceleration driver (if on x86_64/amd64)
RUN if [ "$TARGETARCH" = "amd64" ]; then \
        sed -i 's/Components: main/Components: main non-free non-free-firmware/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
        && apt-get update \
        && apt-get -y install --no-install-recommends intel-media-va-driver-non-free i965-va-driver 2>/dev/null || true \
        && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* ; \
    fi

# Fetch and install the pre-compiled .deb package from GitHub Release
RUN set -e; \
    ARCH_NAME="${TARGETARCH:-amd64}"; \
    echo "Fetching indi-allsky .deb package for architecture: ${ARCH_NAME} (Release: ${RELEASE_TAG})..."; \
    if [ "$RELEASE_TAG" = "latest" ]; then \
        API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/latest"; \
    else \
        API_URL="https://api.github.com/repos/${GITHUB_REPO}/releases/tags/${RELEASE_TAG}"; \
    fi; \
    DEB_URL=$(curl -s "$API_URL" | jq -r --arg arch "$ARCH_NAME" '.assets[]? | select(.name | test("indi-allsky_.*_" + $arch + "\\.deb$")) | .browser_download_url' | head -n 1); \
    if [ -z "$DEB_URL" ] || [ "$DEB_URL" = "null" ]; then \
        echo "No tagged release asset found via API, trying nightly release endpoint..."; \
        DEB_URL="https://github.com/${GITHUB_REPO}/releases/download/nightly/indi-allsky_nightly_${ARCH_NAME}.deb"; \
    fi; \
    echo "Downloading ${DEB_URL}..."; \
    curl -fsSL -o /tmp/indi-allsky.deb "$DEB_URL" || true; \
    if [ -f /tmp/indi-allsky.deb ] && [ -s /tmp/indi-allsky.deb ]; then \
        apt-get update && apt-get install -y --no-install-recommends /tmp/indi-allsky.deb \
        && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/*; \
    else \
        echo "WARNING: Pre-built deb could not be fetched. If building locally without internet, copy a built .deb into the build context."; \
    fi

# Setup system user, logging, and permissions
RUN ln -sf /dev/null /dev/log \
    && mkdir -p /var/lib/indi-allsky /etc/indi-allsky /var/www/html/allsky \
    && chown -R indi-allsky:indi-allsky /var/lib/indi-allsky /etc/indi-allsky /var/www/html/allsky 2>/dev/null || true \
    && echo "indi-allsky ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/indi-allsky \
    && chmod 0440 /etc/sudoers.d/indi-allsky

# Copy entrypoint runtime scripts
COPY docker/start_indi_allsky.sh /usr/local/bin/start_indi_allsky.sh
COPY docker/start_gunicorn.sh /usr/local/bin/start_gunicorn.sh
RUN chmod 755 /usr/local/bin/start_indi_allsky.sh /usr/local/bin/start_gunicorn.sh

USER indi-allsky
WORKDIR /usr/share/indi-allsky

# Default entrypoint (overridden by service in docker-compose.yaml)
ENTRYPOINT ["/usr/local/bin/start_indi_allsky.sh"]
