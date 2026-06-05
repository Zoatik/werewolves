import argparse
import csv
import json
import time
from pathlib import Path

import yaml

from game_leader import GameLeader, Player, VILLAGER, WEREWOLF
from game_webapp import GameLogEntry, Logger


METRIC_FIELDS = [
    "game_id",
    "status",
    "winner",
    "duration_seconds",
    "total_events",
    "total_speeches",
    "vote_results",
    "elimination_events",
    "our_players",
    "our_roles",
    "our_alive_at_end",
    "our_team_won",
    "our_speeches",
    "error",
]


class RunLogger(Logger):
    def __init__(self):
        self.entries = []
        self.msg_id = 0

    def log(self, entry: GameLogEntry) -> None:
        self.entries.append(entry)
        if entry.type in {"ERROR", "GAME_OVER", "VOTE_RESULT", "MORNING_VICTIM", "ELIMINATE_PLAYER"}:
            print(entry.to_string(self.msg_id))
        self.msg_id += 1


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--sleep", type=float, default=5)
    parser.add_argument("--config", default="players_config.yaml")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--our-names", default="Karine,Léo")
    return parser.parse_args()


def load_players(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return [
        Player(name=p["name"], api_base_url=p["api_base_url"])
        for p in config["players"]
    ]


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def append_metrics(path, metrics):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=METRIC_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({field: metrics.get(field, "") for field in METRIC_FIELDS})


def entry_to_dict(entry):
    try:
        return entry.model_dump(mode="json")
    except AttributeError:
        data = entry.dict()
        timestamp = data.get("timestamp")
        if hasattr(timestamp, "isoformat"):
            data["timestamp"] = timestamp.isoformat()
        return data


def compute_metrics(game_id, status, winner, duration_seconds, our_names, players, entries, error=""):
    our_players = [player for player in players if player.name in our_names]
    our_alive = [player.name for player in our_players if player.is_alive]
    our_roles = [f"{player.name}:{player.role}" for player in our_players]
    our_speeches = sum(1 for entry in entries if entry.type == "SPEECH" and entry.actor_name in our_names)

    if winner == WEREWOLF:
        our_team_won = any(player.role == WEREWOLF for player in our_players)
    elif winner == VILLAGER:
        our_team_won = any(player.role != WEREWOLF for player in our_players)
    else:
        our_team_won = False

    summary_players = [
        {
            "name": player.name,
            "role": player.role,
            "alive_at_end": player.is_alive,
        }
        for player in our_players
    ]

    summary = {
        "game_id": game_id,
        "status": status,
        "winner": winner or "",
        "duration_seconds": round(duration_seconds, 2),
        "our_names": our_names,
        "our_players": summary_players,
        "our_team_won": our_team_won,
        "total_events": len(entries),
        "total_speeches": sum(1 for entry in entries if entry.type == "SPEECH"),
        "error": error,
    }

    metrics = {
        "game_id": game_id,
        "status": status,
        "winner": winner or "",
        "duration_seconds": round(duration_seconds, 2),
        "total_events": len(entries),
        "total_speeches": summary["total_speeches"],
        "vote_results": sum(1 for entry in entries if entry.type == "VOTE_RESULT"),
        "elimination_events": sum(1 for entry in entries if entry.type in {"ELIMINATE_PLAYER", "MORNING_VICTIM", "VOTE_RESULT"}),
        "our_players": "|".join(player.name for player in our_players),
        "our_roles": "|".join(our_roles),
        "our_alive_at_end": "|".join(our_alive),
        "our_team_won": "true" if our_team_won else "false",
        "our_speeches": our_speeches,
        "error": error,
    }
    return summary, metrics


def run_one_game(game_id, total_games, config_path, runs_dir, our_names):
    print(f"Game {game_id}/{total_games} started")
    game_dir = runs_dir / f"game_{game_id:03d}"
    logger = RunLogger()
    players = []
    winner = ""
    status = "completed"
    error = ""
    start = time.monotonic()

    try:
        players = load_players(config_path)
        game = GameLeader(players, logger)
        can_start = game.start_game()
        if not can_start:
            status = "failed"
            error = "Failed to start game"
        else:
            while True:
                victim = game.night_time()
                if game.check_if_game_is_over() is not None:
                    break

                game.day_time(victim)
                if game.check_if_game_is_over() is not None:
                    break

            winner = game.check_if_game_is_over()
            if winner == VILLAGER:
                announcement = "La partie est terminée ! Les villageois ont gagné !"
            elif winner == WEREWOLF:
                announcement = "La partie est terminée ! Les loups-garous ont gagné !"
            else:
                announcement = f"La partie est terminée ! {winner} a gagné !"

            game.log(GameLogEntry(
                type="GAME_OVER",
                content=announcement,
                context_data={"winner": winner},
            ))
            game.announce_to_all(announcement)
    except Exception as exc:
        status = "failed"
        error = str(exc)

    duration_seconds = time.monotonic() - start
    summary, metrics = compute_metrics(
        game_id,
        status,
        winner,
        duration_seconds,
        our_names,
        players,
        logger.entries,
        error,
    )
    save_json(game_dir / "logs.json", [entry_to_dict(entry) for entry in logger.entries])
    save_json(game_dir / "summary.json", summary)
    append_metrics(runs_dir / "metrics.csv", metrics)

    if status == "completed":
        print(f"Game {game_id} completed, winner: {winner}")
    else:
        print(f"Game {game_id} failed: {error}")


def main():
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    our_names = [name.strip() for name in args.our_names.split(",") if name.strip()]

    for game_id in range(1, args.games + 1):
        run_one_game(game_id, args.games, args.config, runs_dir, our_names)
        if game_id < args.games:
            time.sleep(args.sleep)


if __name__ == "__main__":
    main()
