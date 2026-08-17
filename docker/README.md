# indi-allsky Docker Deployment

Deploy `indi-allsky` using Docker and Docker Compose powered by official multi-arch Debian package builds.

## Quick Start

1. **Configure environment**:
   ```bash
   cd docker
   cp env_template .env
   ```
   *(Optional)*: Edit `.env` to customize observatory timezone, camera driver, initial credentials, or OIDC SSO settings.

2. **Start the stack**:
   ```bash
   docker compose up -d
   ```

3. **Access the Web Interface**:
   * **HTTPS Web UI**: `https://<server-ip>:8443`
   * **HTTP Web UI**: `http://<server-ip>:8080`
   * **Default Admin**: `admin` / `adminpassword`

## Upgrading

To update containers to the latest release:
```bash
./upgrade.sh
docker compose up -d
```
