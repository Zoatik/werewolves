from __future__ import annotations

import json
from typing import Any, Protocol


class PlayerToolContext(Protocol):
    name: str
    role: str
    players_names: list[str]
    werewolves_count: int
    werewolves: list[str]
    alive_players: set[str]
    dead_players: set[str]
    history: list[tuple[str, str]]
    private_notes: list[str]
    suspicions: dict[str, int]
    phase: str
    known_roles: dict[str, str]
    observed_votes: list[tuple[str, str]]
    last_event_type: str


LLM_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_player_profile",
            "description": "Return the player's own role and private setup information.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_known_game_state",
            "description": "Return the currently known living players, dead players, and suspicions.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_history",
            "description": "Return the most recent messages remembered by the player.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of recent messages to return.",
                        "minimum": 1,
                        "maximum": 20,
                    }
                },
                "required": ["limit"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_note",
            "description": "Store a private note that can be reused later in the game.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {
                        "type": "string",
                        "description": "Short private note to remember.",
                    }
                },
                "required": ["note"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_player_dead",
            "description": "Record that a player has been eliminated.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "Name of the eliminated player.",
                    }
                },
                "required": ["player_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_suspicion",
            "description": "Increase or decrease suspicion for a player and remember why.",
            "parameters": {
                "type": "object",
                "properties": {
                    "player_name": {
                        "type": "string",
                        "description": "Name of the player whose suspicion score should change.",
                    },
                    "delta": {
                        "type": "integer",
                        "description": "Suspicion score change between -3 and 3.",
                        "minimum": -3,
                        "maximum": 3,
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short reason for this suspicion update.",
                    },
                },
                "required": ["player_name", "delta", "reason"],
                "additionalProperties": False,
            },
        },
    },
]


def execute_tool(player: PlayerToolContext, tool_name: str, raw_arguments: str) -> dict[str, Any]:
    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"Invalid JSON arguments for {tool_name}: {exc}"}

    handlers = {
        "get_player_profile": get_player_profile,
        "get_known_game_state": get_known_game_state,
        "get_recent_history": get_recent_history,
        "remember_note": remember_note,
        "mark_player_dead": mark_player_dead,
        "update_suspicion": update_suspicion,
    }

    if tool_name not in handlers:
        return {"ok": False, "error": f"Unknown tool: {tool_name}"}

    try:
        return handlers[tool_name](player, **arguments)
    except TypeError as exc:
        return {"ok": False, "error": f"Invalid arguments for {tool_name}: {exc}"}


def get_player_profile(player: PlayerToolContext) -> dict[str, Any]:
    return {
        "ok": True,
        "name": player.name,
        "role": player.role,
        "players_names": player.players_names,
        "werewolves_count": player.werewolves_count,
        "known_werewolves": player.werewolves,
    }


def get_known_game_state(player: PlayerToolContext) -> dict[str, Any]:
    return {
        "ok": True,
        "alive_players": sorted(player.alive_players),
        "dead_players": sorted(player.dead_players),
        "phase": player.phase,
        "last_event_type": player.last_event_type,
        "known_roles": dict(sorted(player.known_roles.items())),
        "observed_votes": player.observed_votes[-12:],
        "suspicions": dict(sorted(player.suspicions.items())),
        "private_notes": player.private_notes[-10:],
    }


def get_recent_history(player: PlayerToolContext, limit: int) -> dict[str, Any]:
    limit = max(1, min(limit, 20))
    return {
        "ok": True,
        "history": [
            {"source": source, "message": message}
            for source, message in player.history[-limit:]
        ],
    }


def remember_note(player: PlayerToolContext, note: str) -> dict[str, Any]:
    clean_note = note.strip()
    if not clean_note:
        return {"ok": False, "error": "Note cannot be empty."}

    player.private_notes.append(clean_note[:500])
    return {"ok": True, "remembered": clean_note[:500]}


def mark_player_dead(player: PlayerToolContext, player_name: str) -> dict[str, Any]:
    if player_name not in player.players_names:
        return {"ok": False, "error": f"Unknown player: {player_name}"}

    player.alive_players.discard(player_name)
    player.dead_players.add(player_name)
    return {
        "ok": True,
        "alive_players": sorted(player.alive_players),
        "dead_players": sorted(player.dead_players),
    }


def update_suspicion(
    player: PlayerToolContext,
    player_name: str,
    delta: int,
    reason: str,
) -> dict[str, Any]:
    if player_name not in player.players_names:
        return {"ok": False, "error": f"Unknown player: {player_name}"}

    bounded_delta = max(-3, min(delta, 3))
    player.suspicions[player_name] = player.suspicions.get(player_name, 0) + bounded_delta
    if reason.strip():
        player.private_notes.append(
            f"Suspicion {player_name}: {bounded_delta:+d}. {reason.strip()[:300]}"
        )

    return {
        "ok": True,
        "player_name": player_name,
        "suspicion": player.suspicions[player_name],
    }
