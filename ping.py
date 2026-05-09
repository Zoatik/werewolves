import json
import yaml
import time
import requests
import sys
from concurrent.futures import ThreadPoolExecutor

# Simple script to ping all players configured in players_config.yaml
# and display their status in a dynamic terminal UI.

CONFIG_FILE = "players_config.yaml"
TIMEOUT = 2  # seconds
POLL_INTERVAL = 3  # seconds

def get_player_status(player):
    name = player.get("name", "Unknown")
    url = player.get("api_base_url", "")
    try:
        # Increased timeout for cold starts as discussed
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return f"✅ {name} ({url})"
        elif response.status_code in [502, 503, 504]:
            return f"⏳ {name} ({url})"
        else:
            return f"⚠️ Error {response.status_code} {name} ({url})"
    except requests.exceptions.Timeout:
        return f"⏳ {name} ({url})"
    except requests.exceptions.RequestException:
        return f"❌ {name} ({url})"

def main():
    try:
        with open(CONFIG_FILE, "r") as f:
            config = yaml.safe_load(f)
            players = config.get("players", [])
    except FileNotFoundError:
        print(f"Error: {CONFIG_FILE} not found.")
        return
    except yaml.YAMLError:
        print(f"Error: Failed to parse {CONFIG_FILE}.")
        return

    if not players:
        print("No players configured.")
        return

    print("\033[?1049h", end="") # Use alternate screen buffer
    ping_count = 0
    try:
        while True:
            ping_count += 1
            with ThreadPoolExecutor(max_workers=len(players)) as executor:
                results = list(executor.map(get_player_status, players))

            # Move cursor to top-left
            sys.stdout.write("\033[H")
            sys.stdout.write("Werewolf Players Status (Ctrl+C to exit)\n")
            sys.stdout.write("-" * 60 + "\n")
            for line in results:
                sys.stdout.write(line + "\n")

            sys.stdout.write(f"\nPinging {ping_count} times...\n")
            sys.stdout.flush()
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?1049l", end="") # Restore main screen buffer

if __name__ == "__main__":
    main()
