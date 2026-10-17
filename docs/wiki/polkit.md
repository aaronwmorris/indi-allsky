# PolicyKit (Polkit) Configuration

`indi-allsky` operates as an unprivileged service user (`indi-allsky`) for security. To perform system-level management tasks from the web interface—such as rebooting, shutting down, restarting systemd services, synchronizing time, managing network interfaces, and mounting external storage—the system relies on PolicyKit rules.

---

## Polkit Rule Specification

On standard systemd distributions (Debian, Ubuntu, Raspberry Pi OS), rules are installed to:
```
/etc/polkit-1/rules.d/90-indi-allsky.rules
```

The installed rule grants the `indi-allsky` service account explicit authorization for five functional categories:

1. **System Power Management (`org.freedesktop.login1`)**:
   * `power-off` / `power-off-multiple-sessions`
   * `reboot` / `reboot-multiple-sessions`
2. **Service Management (`org.freedesktop.systemd1`)**:
   * `manage-units`
   * `manage-unit-files`
   * `reload-daemon`
3. **Time Synchronization (`org.freedesktop.timedate1`)**:
   * `set-time`
   * `set-timezone`
   * `set-ntp`
4. **Network Configuration (`org.freedesktop.NetworkManager`)**:
   * `network-control`
   * `settings.modify.system` / `settings.modify.own`
   * `wifi.scan` / `enable-disable-wifi` / `wifi.share.protected`
5. **Storage Mounting (`org.freedesktop.udisks2`)**:
   * `filesystem-mount` / `filesystem-mount-system`
   * `power-off-drive` / `eject-media` / `filesystem-unmount-others`

---

## Verification & Diagnostic Commands

### Enumerate Installed Polkit Actions
To verify which system actions are registered with the PolicyKit daemon:
```bash
pkaction
```

### Inspect Details for a Specific Action
```bash
pkaction -v --action-id org.freedesktop.login1.reboot
```

### Test User Authorization
Simulate an authorization request for the service user without executing the command:
```bash
# Check if the current shell process is authorized to trigger a reboot
pkcheck -p "$PPID" -a org.freedesktop.login1.reboot

# Exit code 0 indicates authorization is granted; non-zero indicates denial
echo $?
```

### Restart the PolicyKit Daemon
If modifying rules manually:
```bash
sudo systemctl restart polkit
```