## Show all actions
```
pkaction
```

## Show action info
```
pkaction -v --action-id org.freedesktop.login1.reboot
```

## Script testing
```
pkcheck -p "$PPID" -a org.freedesktop.login1.reboot

echo $?
```