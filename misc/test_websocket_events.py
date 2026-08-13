#!/usr/bin/env python3
"""
Interactive Test WebSocket client for indi-allsky event stream.
Usage:
    # Interactive mode (listen + type commands in terminal):
    ./misc/test_websocket_events.py --url wss://192.168.86.232/indi-allsky/ws/events --no-ssl-verify

    # Single command mode:
    ./misc/test_websocket_events.py --url wss://192.168.86.232/indi-allsky/ws/events --no-ssl-verify --action pause
"""
import sys
import argparse
import json
import time
import ssl
import threading

try:
    import simple_websocket
except ImportError:
    print("Error: simple-websocket library is required. Install via pip or run in venv.")
    sys.exit(1)


SUPPORTED_SHORTCUT_COMMANDS = {
    "pause": {"action": "pause"},
    "unpause": {"action": "unpause"},
    "ping": {"action": "ping"},
    "status": {"action": "get_status"},
    "get_status": {"action": "get_status"},
    "reboot": {"action": "reboot"},
    "shutdown": {"action": "shutdown"},
    "keogram": {"action": "generate_keogram"},
    "timelapse": {"action": "generate_timelapse"},
    "startrail": {"action": "generate_startrail"},
    "darks": {"action": "trigger_darks"},
}


def stdin_reader_thread(ws, running_flag):
    """Background thread to read interactive commands from stdin."""
    print("\n💡 Interactive Terminal Mode Active!")
    print("Type a command name (pause, unpause, ping, status, keogram, timelapse, reboot) or raw JSON, then hit Enter:\n")
    while running_flag[0]:
        try:
            line = input().strip()
            if not line:
                continue
            if line.lower() in ("exit", "quit"):
                running_flag[0] = False
                ws.close()
                break

            if line.lower() in SUPPORTED_SHORTCUT_COMMANDS:
                payload = SUPPORTED_SHORTCUT_COMMANDS[line.lower()]
            elif line.startswith("{"):
                payload = json.loads(line)
            else:
                payload = {"action": line}

            ws.send(json.dumps(payload))
            print(f"--> SENT: {json.dumps(payload)}")
        except Exception as e:
            if running_flag[0]:
                print(f"Error sending command: {e}")


def main():
    parser = argparse.ArgumentParser(description="indi-allsky WebSocket Event Test Listener & Command Sender")
    parser.add_argument("--url", default="ws://127.0.0.1:8080/indi-allsky/ws/events", help="WebSocket URL (ws:// or wss://)")
    parser.add_argument("--api-key", default="", help="API Key / Token if required")
    parser.add_argument("--no-ssl-verify", action="store_true", help="Disable SSL certificate verification for wss://")
    parser.add_argument("--action", default="", help="Send a single action command (e.g. pause, unpause, ping, get_status) and exit")
    args = parser.parse_args()

    url = args.url
    if args.api_key:
        separator = "&" if "?" in url else "?"
        url += f"{separator}api_key={args.api_key}"

    ssl_context = None
    if url.startswith("wss://") or args.no_ssl_verify:
        ssl_context = ssl._create_unverified_context()

    print(f"Connecting to indi-allsky WebSocket stream at {url}...")
    try:
        ws = simple_websocket.Client(url, ssl_context=ssl_context)
        print("Connected successfully! Listening for live events...")
        print("-" * 60)

        # Single action command mode
        if args.action:
            action_name = args.action.lower()
            payload = SUPPORTED_SHORTCUT_COMMANDS.get(action_name, {"action": args.action})
            ws.send(json.dumps(payload))
            print(f"--> SENT: {json.dumps(payload)}")
            # Read handshake and command response
            for _ in range(2):
                msg = ws.receive()
                if msg:
                    event = json.loads(msg)
                    print(f"[{time.strftime('%H:%M:%S')}] EVENT: {event.get('event')}")
                    print(json.dumps(event.get('data', {}), indent=2))
            ws.close()
            return

        # Default: Send status request
        ws.send(json.dumps({"action": "get_status"}))

        # Start interactive stdin reader thread
        running_flag = [True]
        t = threading.Thread(target=stdin_reader_thread, args=(ws, running_flag), daemon=True)
        t.start()

        while running_flag[0]:
            data = ws.receive()
            if data is None:
                print("Connection closed by server.")
                break

            try:
                event = json.loads(data)
                event_name = event.get('event', 'unknown')
                timestamp = event.get('timestamp', time.time())
                payload = event.get('data', {})

                print(f"\n[{time.strftime('%H:%M:%S', time.localtime(timestamp))}] EVENT: {event_name}")
                print(json.dumps(payload, indent=2))
                print("-" * 60)
            except json.JSONDecodeError:
                print(f"RAW MESSAGE: {data}")

    except KeyboardInterrupt:
        print("\nDisconnecting...")
    except Exception as e:
        err_msg = str(e)
        print(f"Error: {err_msg}")


if __name__ == "__main__":
    main()
