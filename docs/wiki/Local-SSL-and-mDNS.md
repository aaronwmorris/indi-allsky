# Local SSL Certificates and mDNS Resolution

indi-allsky operates over HTTPS by default. On Debian package (`.deb`) installations, indi-allsky automatically establishes a local Certificate Authority (CA) using **`mkcert`** and advertises **`indi-allsky.local`** over Multicast DNS (**mDNS**) via **`avahi-daemon`**.

This provides browser-trusted TLS encryption across your local network without security warnings.

> [!NOTE]
> This automated CA and mDNS integration is exclusive to the **Debian package (`.deb`)** installation workflow. Legacy source-based manual installations (`setup.sh`) generate traditional self-signed certificates.

---

## 1. Quick Start: Trusting the Certificate

To eliminate browser security warnings on your computer or phone, export the Root CA certificate from your camera and install it on your client devices once.

### Export the Root CA

Run this command on your camera to export the root certificate:

```bash
sudo indi-allsky-ctl ssl-ca-export /tmp/indi-allsky-ca.pem
```

Alternatively, download it directly from your computer via SSH:

```bash
ssh <user>@indi-allsky.local "sudo indi-allsky-ctl ssl-ca-export" > indi-allsky-ca.pem
```

---

## 2. Installing the Root CA on Client Devices

Install `indi-allsky-ca.pem` on each computer or phone accessing the camera:

### macOS
```bash
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain indi-allsky-ca.pem
```
*(Or double-click the file in Finder > select **System** keychain > set trust to **Always Trust**).*

### Windows
Open PowerShell as Administrator:
```powershell
Import-Certificate -FilePath .\indi-allsky-ca.pem -CertStoreLocation Cert:\LocalMachine\Root
```
*(Or double-click the file > Install Certificate > Local Machine > Trusted Root Certification Authorities).*

### Linux (Ubuntu / Debian)
```bash
sudo cp indi-allsky-ca.pem /usr/local/share/ca-certificates/indi-allsky-ca.crt
sudo update-ca-certificates
```

### iOS / iPadOS
1. AirDrop or email `indi-allsky-ca.pem` to your device.
2. Go to **Settings** > **Profile Downloaded** > **Install**.
3. Go to **Settings** > **General** > **About** > **Certificate Trust Settings** and enable full trust for the root certificate.

### Android
1. Transfer `indi-allsky-ca.pem` to device storage.
2. Open **Settings** > **Security** > **More Security Settings** > **Encryption & credentials**.
3. Tap **Install a certificate** > **CA certificate** and select the file.

Once installed, navigating to `https://indi-allsky.local/` will display a secure padlock icon in your browser.

---

## 3. Certificate Renewal

- **Root CA (`rootCA.pem`)**: Valid for **10 years** (does not need frequent replacement).
- **Leaf Server Certificate (`*.pem`)**: Valid for **2 years and 3 months** (enforced by modern browser standards).

### Automated Renewal
A systemd timer (`indi-allsky-ssl-renew.timer`) runs weekly on the camera. If the leaf certificate expires within 30 days, it automatically generates a new leaf certificate and reloads the web server.

> [!TIP]
> Because the Root CA does not change during renewal, your client devices will automatically trust renewed certificates without re-importing anything.

### Manual Renewal
To trigger or force a renewal manually (e.g. after moving the camera to a new IP address):

```bash
# Check validity and renew if within 30 days of expiration:
sudo indi-allsky-ctl ssl-renew

# Force immediate regeneration and web server reload:
sudo indi-allsky-ctl ssl-renew --force
```

---

## 4. Architecture & Technical Details

For users interested in the underlying implementation:

```
                      ┌────────────────────────────────────────┐
                      │            Client Device               │
                      │       (PC / Mac / iPhone / iPad)       │
                      │                                        │
                      │    Root Trust Store: rootCA.pem        │
                      └──────────────────┬─────────────────────┘
                                         │
                   HTTPS Request:        │ mDNS Resolution:
           https://indi-allsky.local/    │ "indi-allsky.local" -> 192.168.1.50
                                         │
                                         ▼
                      ┌────────────────────────────────────────┐
                      │             indi-allsky                │
                      │                                        │
                      │  Avahi mDNS:                           │
                      │   - indi-allsky.local                  │
                      │   - _indi-allsky._tcp on HTTPS_PORT    │
                      │                                        │
                      │  Web Server (Caddy / Nginx / Apache):  │
                      │   - Leaf Cert (signed by rootCA.pem)   │
                      │                                        │
                      │  Local CA Directory:                   │
                      │   - /etc/indi-allsky/ca/rootCA.pem     │
                      └────────────────────────────────────────┘
```

### mDNS & Home Assistant Discovery
- **Avahi Daemon**: Broadcasts `indi-allsky.local` via `/etc/avahi/hosts`.
- **Dedicated Service Type**: Publishes `_indi-allsky._tcp` via `/etc/avahi/services/indi-allsky.service` on the configured `HTTPS_PORT`.
- **TXT Records**: Includes `app=indi-allsky`, `path=/indi-allsky`, `ssl=true`, `version`, and `mac` to support Home Assistant Zeroconf discovery without colliding with generic HTTP devices.

### Certificate Paths & Web Server Storage
Certificates are generated with Subject Alternative Names (SAN) for `indi-allsky.local`, `localhost`, `127.0.0.1`, `::1`, and any active local network IPs. They are stored at:

| Web Server | Certificate Path | Private Key Path | Permissions |
|---|---|---|---|
| **Caddy** | `/etc/caddy/ssl/indi-allsky_caddy.pem` | `/etc/caddy/ssl/indi-allsky_caddy.key` | `root:caddy` (0640 key) |
| **Nginx** | `/etc/nginx/ssl/indi-allsky_nginx.pem` | `/etc/nginx/ssl/indi-allsky_nginx.key` | `root:root` (0600 key) |
| **Apache** | `/etc/apache2/ssl/indi-allsky_apache.pem` | `/etc/apache2/ssl/indi-allsky_apache.key` | `root:root` (0600 key) |
