import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", default="runs")
    return parser.parse_args()


def read_metrics(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_summaries(runs_dir):
    summaries = []
    for path in sorted(runs_dir.glob("game_*/summary.json")):
        with open(path, "r", encoding="utf-8") as f:
            summaries.append(json.load(f))
    return summaries


def pct(part, total):
    if total == 0:
        return "0.0%"
    return f"{(part / total) * 100:.1f}%"


def write_report(runs_dir, metrics, summaries):
    total_games = len(summaries) or len(metrics)
    completed = [row for row in metrics if row.get("status") == "completed"]
    failed = [row for row in metrics if row.get("status") == "failed"]
    winners = Counter(row.get("winner", "") for row in completed)
    our_wins = sum(1 for row in metrics if row.get("our_team_won") == "true")
    total_speeches = sum(int(row.get("total_speeches") or 0) for row in metrics)
    avg_speeches = total_speeches / len(metrics) if metrics else 0

    roles = defaultdict(Counter)
    survival = defaultdict(lambda: {"alive": 0, "games": 0})
    for summary in summaries:
        for player in summary.get("our_players", []):
            name = player.get("name", "")
            role = player.get("role", "")
            if name and role:
                roles[name][role] += 1
            if name:
                survival[name]["games"] += 1
                if player.get("alive_at_end"):
                    survival[name]["alive"] += 1

    errors = [row.get("error", "") for row in metrics if row.get("error")]
    lines = [
        "# Rapport des parties",
        "",
        f"Généré le {datetime.now().isoformat(timespec='seconds')}",
        "",
        f"- Nombre total de parties: {total_games}",
        f"- Parties complétées: {len(completed)}",
        f"- Parties échouées: {len(failed)}",
        f"- Victoires villageois: {winners.get('villageois', 0)}",
        f"- Victoires loups-garous: {winners.get('loup-garou', 0)}",
        f"- Taux de victoire villageois: {pct(winners.get('villageois', 0), len(completed))}",
        f"- Taux de victoire loups-garous: {pct(winners.get('loup-garou', 0), len(completed))}",
        f"- Parties où nos bots gagnent: {our_wins}",
        f"- Nombre moyen de speeches par partie: {avg_speeches:.1f}",
        "",
        "## Rôles joués par Karine/Léo",
    ]

    if roles:
        for name in sorted(roles):
            role_counts = ", ".join(f"{role}: {count}" for role, count in sorted(roles[name].items()))
            lines.append(f"- {name}: {role_counts}")
    else:
        lines.append("- Aucun rôle enregistré.")

    lines.extend(["", "## Taux de survie de Karine/Léo"])
    if survival:
        for name in sorted(survival):
            data = survival[name]
            lines.append(f"- {name}: {pct(data['alive'], data['games'])} ({data['alive']}/{data['games']})")
    else:
        lines.append("- Aucune survie enregistrée.")

    lines.extend(["", "## Erreurs rencontrées"])
    if errors:
        for error, count in Counter(errors).items():
            lines.append(f"- {count}x {error}")
    else:
        lines.append("- Aucune erreur enregistrée.")

    lines.extend([
        "",
        "## Pistes simples d'amélioration",
        "- Réduire les votes invalides.",
        "- Surveiller les timeouts.",
        "- Comparer les performances selon le rôle.",
        "- Regarder les parties où nos bots meurent tôt.",
    ])

    report_path = runs_dir / "report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    metrics = read_metrics(runs_dir / "metrics.csv")
    summaries = read_summaries(runs_dir)
    write_report(runs_dir, metrics, summaries)


if __name__ == "__main__":
    main()
