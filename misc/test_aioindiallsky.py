#!/usr/bin/env python3
"""
Simple test script for aioindiallsky SDK without installing/building.
Usage:
    ./misc/test_aioindiallsky.py --host 192.168.86.232 --port 8080 --ssl --api-key YOUR_SECRET_KEY
"""
import sys
import argparse
import asyncio
from pathlib import Path

# Add aioindiallsky source directory to sys.path (no pip install required)
AIO_DIR = Path(__file__).resolve().parent.parent.parent / "aioindiallsky"
if AIO_DIR.exists():
    sys.path.insert(0, str(AIO_DIR))
elif Path("/home/hamish/git/aioindiallsky").exists():
    sys.path.insert(0, "/home/hamish/git/aioindiallsky")

try:
    from aioindiallsky import IndiAllSkyClient
except ImportError:
    print(f"Error: Could not find aioindiallsky package at {AIO_DIR}")
    sys.exit(1)


async def main():
    parser = argparse.ArgumentParser(description="Test aioindiallsky SDK directly from source")
    parser.add_argument("--host", default="192.168.86.232", help="indi-allsky host IP")
    parser.add_argument("--port", type=int, default=8080, help="Port (8080 or 80/443)")
    parser.add_argument("--ssl", action="store_true", help="Use WSS / HTTPS")
    parser.add_argument("--api-key", default="", help="API Key / Secret Key")
    parser.add_argument("--action", default="", help="Send a command (e.g. pause, unpause, get_sensors, ping)")
    args = parser.parse_args()

    client = IndiAllSkyClient(
        host=args.host,
        port=args.port,
        ssl=args.ssl,
        api_key=args.api_key
    )

    def on_exposure(exp):
        print(f"\n📸 [EVENT] New Exposure: {exp.filename}")
        print(f"   Exposure: {exp.exposure}s | Temp: {exp.temp}°C | SQM: {exp.sqm} | Stars: {exp.stars}")

    def on_sensor(sens):
        print(f"\n📊 [EVENT] Sensor Update (Last Update: {sens.last_update}):")
        print(f"   Active Named Sensors: {list(sens.sensors.keys())}")

    def on_generic(event_name, data):
        print(f"🔔 [EVENT] Raw Event '{event_name}': {data}")

    client.register_callback("exposure_complete", on_exposure)
    client.register_callback("sensor_update", on_sensor)
    client.register_callback("all", on_generic)

    if args.action:
        print(f"Sending command '{args.action}' over /ws/control...")
        success = await client.send_command(args.action)
        print(f"Command '{args.action}' sent: {success}")
        await asyncio.sleep(2)
        await client.disconnect()
        return

    print(f"Connecting to indi-allsky SDK at {client.events_url}...")
    try:
        await client.connect()
        print("Connected! Listening for live SDK events (Press Ctrl+C to stop)...\n")
        await client.listen()
    except KeyboardInterrupt:
        print("\nDisconnecting SDK...")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
