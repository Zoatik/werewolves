"""
Small local smoke test for the Werewolf player.
Automatically starts the Flask app, runs a few checks, and shuts it down.
"""

import subprocess
import time
import requests
import sys
import os
import socket
import threading

# Configuration
PYTHON_PATH = "/Users/ren/miniconda3/bin/python"
PLAYERS_NAMES = ["Aline", "Benjamin", "Chloe", "David", "Elise", "Frédéric", "Gabrielle"]
# Generous timeout for the smoke test; the real game leader uses API_TIMEOUT=4s,
# so a slow player will pass this test but still get eliminated in real games.
LLM_TIMEOUT = 30

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def run_local_test():
    port = get_free_port()
    url = f"http://localhost:{port}/"
    
    print(f"--- Starting local smoke test on {url} ---")
    
    # 1. Start the Flask app
    env = os.environ.copy()
    env["FLASK_APP"] = "app.py"
    # Ensure we are in the right directory for imports to work
    cwd = os.path.dirname(os.path.abspath(__file__))
    
    process = subprocess.Popen(
        [PYTHON_PATH, "-m", "flask", "run", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=cwd,
        text=True,
        bufsize=1,
    )

    def _tee_server_output():
        for line in process.stdout:
            print(f"[server] {line}", end="", flush=True)
    tee = threading.Thread(target=_tee_server_output, daemon=True)
    tee.start()

    try:
        # 2. Wait for server to be up
        print("Waiting for server to start...", end="", flush=True)
        up = False
        for _ in range(10):
            try:
                resp = requests.get(url, timeout=1)
                if resp.status_code == 200:
                    up = True
                    break
            except:
                pass
            print(".", end="", flush=True)
            time.sleep(1)
            if process.poll() is not None:
                print("\nError: Flask process exited unexpectedly.")
                return
        
        if not up:
            print("\nError: Server timed out.")
            return
        print(" OK!")

        # 3. Create a player
        print("\n[1/4] Creating player...")
        payload = {
            "role": "villageois",
            "player_name": "Aline",
            "players_names": PLAYERS_NAMES,
            "werewolves_count": 2,
            "werewolves": []
        }
        resp = requests.post(f"{url}new_game", json=payload, timeout=2)
        resp.raise_for_status()
        data = resp.json()
        player_id = data["player_id"]
        print(f"Success! player_id: {player_id}")

        # 4. Dummy moves
        print("\n[2/4] Running dummy moves...")
        
        def timed_post(label, path, payload=None):
            t0 = time.time()
            r = requests.post(f"{url}{path}", json=payload, timeout=LLM_TIMEOUT)
            r.raise_for_status()
            elapsed = time.time() - t0
            warn = "  [SLOW: would time out in real game]" if elapsed > 4 else ""
            print(f"-> OK ({elapsed:.1f}s){warn}")
            return r

        msg = "C'est le matin, le village se réveille."
        print(f"  notify: '{msg}'", end=" ", flush=True)
        timed_post("notify", f"{player_id}/notify", {"message": msg})

        print(f"  speak", end=" ", flush=True)
        resp = timed_post("speak", f"{player_id}/speak")
        speech = resp.json().get("speech")
        print(f"    speech: '{speech}'")

        msg_vote = "Il est temps de voter. Donnez maintenant votre intention de vote."
        print(f"[3/4]  notify (vote): '{msg_vote}'", end=" ", flush=True)
        resp = timed_post("notify-vote", f"{player_id}/notify", {"message": msg_vote})
        intent = resp.json()
        print(f"    vote_for: '{intent.get('vote_for')}'")

        print("\n[4/4] Summary")
        print("Local smoke test PASSED!")

    except Exception as e:
        print(f"\nTest failed: {e}")
    finally:
        print("\nShutting down local player...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        tee.join(timeout=2)

if __name__ == "__main__":
    run_local_test()
