# Launches one Flask player server per local player defined in players_config.json.
# Remote players (e.g. on Vercel) are skipped; their api_base_url is used directly by the game leader.
import json
import yaml


def run_player_server(port: int) -> None:
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app = create_app()
    app.run(debug=False, port=port, host='localhost')


def local_ports_from_config(config_path: str = "players_config.yaml") -> list[int]:
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    ports: set[int] = set()
    for p in config["players"]:
        base_url = p["api_base_url"]
        if base_url.startswith("http://localhost:"):
            port = int(base_url.split(":")[2].strip("/"))
            ports.add(port)
        else:
            print(f"INFO: player {p['name']} is remote ({base_url}), not started locally")
    return sorted(ports)


if __name__ == "__main__":
    processes: list[multiprocessing.Process] = []
    for port in local_ports_from_config():
        p = multiprocessing.Process(target=run_player_server, args=(port,))
        p.start()
        processes.append(p)
        print(f"Started Werewolf player server on port {port}")

    for p in processes:
        p.join()
