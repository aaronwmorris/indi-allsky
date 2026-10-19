# External Temperature Sensors

Certain astronomical cameras (such as uncooled CMOS sensors, older USB webcams, or Raspberry Pi Camera Modules) lack internal temperature telemetry. Accurate temperature measurement is essential for:
1. **Dark Frame Library Matching**: Dark current scales exponentially with sensor temperature; master dark frames must be matched within $\pm 2^\circ\text{C}$ to $\pm 3^\circ\text{C}$ of ambient capture conditions.
2. **Dew Heater Automation**: Regulating heater duty cycle against ambient dew point calculations.

`indi-allsky` supports executing a custom script to inject ambient temperature telemetry directly into the camera image metadata.

---

## 1. Configuration

In the web interface under **Configuration** → **Camera**:
* `EXTERNAL_TEMP_SCRIPT`: Specify the absolute path to your executable script (e.g. `/etc/indi-allsky/scripts/get_ambient_temp.py`).

Ensure the script has executable permissions and is readable by the `indi-allsky` service user:
```bash
sudo chmod 755 /etc/indi-allsky/scripts/get_ambient_temp.py
sudo chown indi-allsky:indi-allsky /etc/indi-allsky/scripts/get_ambient_temp.py
```

---

## 2. Script Execution Protocol

When invoking the external script, `indi-allsky` supplies an environment variable named `TEMP_JSON` containing the temporary file path where output must be written.

The script must write valid JSON containing a key named `temp` with a floating-point temperature value in degrees Celsius:

```json
{
  "temp": 14.85
}
```

---

## 3. Implementation Examples

### Python Sensor Script Example
```python
#!/usr/bin/env python3
import os
import json

# Query your hardware sensor (e.g., I2C BME280, 1-Wire DS18B20, or weather station API)
ambient_temp_celsius = 18.25

output_path = os.environ.get("TEMP_JSON")
if output_path:
    with open(output_path, "w") as f:
        json.dump({"temp": round(ambient_temp_celsius, 2)}, f)
```

### 1-Wire DS18B20 Shell Script Example
```bash
#!/usr/bin/env bash
# Read from Linux 1-Wire subsystem
SENSOR_FILE="/sys/bus/w1/devices/28-00000xxxxxxx/w1_slave"

if [ -f "$SENSOR_FILE" ] && [ -n "$TEMP_JSON" ]; then
    RAW_TEMP=$(grep -o 't=[0-9\-]*' "$SENSOR_FILE" | cut -d= -f2)
    TEMP_C=$(awk "BEGIN {print $RAW_TEMP / 1000}")
    echo "{\"temp\": $TEMP_C}" > "$TEMP_JSON"
fi
```

### Manual Verification
Test execution directly from the command line:
```bash
TEMP_JSON=/tmp/test_temp.json /etc/indi-allsky/scripts/get_ambient_temp.py
cat /tmp/test_temp.json
```