# Exposing indi-allsky with Cloudflare Tunnels

This guide explains how to expose your **indi-allsky** web interface securely to the internet using **Cloudflare Tunnels** (`cloudflared`).

Cloudflare Tunnels create an outbound-only encrypted tunnel from your camera to Cloudflare. This provides remote access without router port forwarding, without dynamic DNS, and behind CGNAT networks (such as 4G/5G or Starlink).

---

## 1. Prerequisites

- A free [Cloudflare account](https://dash.cloudflare.com/).
- A registered domain name managed on Cloudflare DNS.
- SSH or terminal access to your `indi-allsky` host.

---

## 2. Setup via Cloudflare Dashboard (Recommended)

The web dashboard is the quickest way to configure and manage your tunnel.

### Step 1: Create the Tunnel
1. Log in to the [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/).
2. Navigate to **Networks** > **Tunnels** and click **Create a tunnel**.
3. Select **Cloudflare** as the connector type and name your tunnel (e.g., `indi-allsky`).
4. Click **Save tunnel**.

### Step 2: Install Connector on indi-allsky
The dashboard displays an installation command tailored to your hardware:
1. Select **Debian** and your architecture (`64-bit` for Raspberry Pi 4/5 64-bit OS or amd64 servers).
2. Copy and run the generated command on your camera via SSH:

```bash
# Example command:
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared.deb
sudo cloudflared service install <YOUR_TUNNEL_TOKEN>
```

3. When the dashboard indicates the connector is **Connected**, click **Next**.

### Step 3: Route Public Hostname to indi-allsky
In the **Public Hostnames** tab:
1. **Subdomain**: Enter your desired prefix (e.g. `allsky`).
2. **Domain**: Select your domain (e.g. `yourdomain.com`).
3. **Service Type**: Select `HTTPS`.
4. **URL**: Enter `localhost:443` (or your configured `HTTPS_PORT`).
5. Open **Additional application settings** > **TLS**:
   - Turn **No TLS Verify** to **ON**. *(This allows Cloudflare to trust the local SSL certificate without warning).*
6. Click **Save hostname**.

You can now open `https://allsky.yourdomain.com` from any device.

---

## 3. Alternative: CLI Setup (`/etc/cloudflared/config.yml`)

For headless or scripted environments:

```bash
# 1. Install cloudflared
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared.deb

# 2. Login and create tunnel
cloudflared tunnel login
cloudflared tunnel create indi-allsky-tunnel
cloudflared tunnel route dns indi-allsky-tunnel allsky.yourdomain.com
```

Create `/etc/cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_UUID>
credentials-file: /etc/cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: allsky.yourdomain.com
    service: https://localhost:443
    originRequest:
      noTLSVerify: true
  - service: http_status:404
```

Start the systemd service:

```bash
sudo cp ~/.cloudflared/<TUNNEL_UUID>.json /etc/cloudflared/
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

---

## 4. Architecture & Key Details

For users interested in the network flow:

```
┌───────────────────────────────┐
│          Remote User          │
│ https://allsky.yourdomain.com │
└───────────────┬───────────────┘
                │ Public HTTPS (Cloudflare Edge Certificate)
                ▼
┌───────────────────────────────┐
│     Cloudflare Edge PoP       │
└───────────────┬───────────────┘
                │ Outbound Encrypted QUIC Tunnel (No ports opened)
                ▼
┌───────────────────────────────┐
│    indi-allsky Host System    │
│  cloudflared -> localhost:443 │
└───────────────────────────────┘
```

- **Inbound Ports**: Closed. The `cloudflared` daemon creates an outbound connection to Cloudflare edge nodes.
- **WebSockets**: ActionAPI and live status indicators function out-of-the-box without extra proxy headers.
- **Access Policies**: You can optionally protect your camera with a login barrier (email OTP, Google, GitHub SSO) under **Access** > **Applications** in the Zero Trust dashboard.
