#!/usr/bin/env python3
"""
Test WebSocket client for indi-allsky event stream.
Usage:
    python3 misc/test_websocket_events.py --url ws://localhost:8080/indi-allsky/ws/events
"""
import sys
import argparse
import json
import time

try:
    import simple_websocket
except ImportError:
    print("Error: simple-websocket library is required. Install via pip or run in venv.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="indi-allsky WebSocket Event Test Listener")
    parser.add_argument("--url", default="ws://127.0.0.1:8080/indi-allsky/ws/events", help="WebSocket URL")
    parser.add_argument("--api-key", default="", help="API Key / Token if required")
    args = parser.parse_args()

    url = args.url
    if args.api_key:
        url += f"?api_key={args.api_key}"

    print(f"Connecting to indi-allsky WebSocket stream at {url}...")
    try:
        ws = simple_websocket.Client(url)
        print("Connected successfully! Listening for live events (Press Ctrl+C to stop)...")
        print("-" * 60)

        # Send a status request to verify bi-directional communication
        ws.send(json.dumps({"type": "get_status"}))

        while True:
            data = ws.receive()
            if data is None:
                print("Connection closed by server.")
                break
            
            try:
                event = json.loads(data)
                event_name = event.get('event', 'unknown')
                timestamp = event.get('timestamp', time.time())
                payload = event.get('data', {})

                print(f"[{time.strftime('%H:%M:%S', time.localtime(timestamp))}] EVENT: {event_name}")
                print(json.dumps(payload, indent=2))
                print("-" * 60)
            except json.JSONDecodeError:
                print(f"RAW MESSAGE: {data}")

    except KeyboardInterrupt:
        print("\nDisconnecting...")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
