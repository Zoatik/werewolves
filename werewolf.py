from pydantic import BaseModel
from abc import ABC, abstractmethod
from typing import List
from openai import OpenAI
from dotenv import load_dotenv
from tools import LLM_TOOLS, execute_tool
import json
import os
import random
import re

load_dotenv()

AVAILABLE_MODELS = [
    "google/gemini-3.1-flash-lite",
    "minimax/minimax-m2.7",
    "deepseek/deepseek-v4-flash",
    "openai/gpt-5-nano",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
MAX_TOOL_ROUNDS = 4


def create_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise RuntimeError("Missing API key. Set OPENAI_API_KEY or API_KEY in .env.")

    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL")
        or os.getenv("BASE_URL")
        or DEFAULT_BASE_URL,
    )


class Intent(BaseModel):
    want_to_speak: bool = False
    want_to_interrupt: bool = False
    vote_for: str | None = None


class WerewolfPlayerInterface(ABC):

    @classmethod
    def create(
        cls,
        name: str,
        role: str,
        players_names: List[str],
        werewolves_count: int,
        werewolves: List[str],
    ) -> "WerewolfPlayerInterface":
        return cls(name, role, players_names, werewolves_count, werewolves)

    @abstractmethod
    def speak(self) -> str:
        """Generate a response when it's the player's turn to speak."""
        pass

    @abstractmethod
    def notify(self, message: str) -> Intent:
        """Process a notification and determine the player's intent."""
        pass


class WerewolfPlayer(WerewolfPlayerInterface):

    def __init__(
        self,
        name: str,
        role: str,
        players_names: List[str],
        werewolves_count: int,
        werewolves: List[str],
    ) -> None:
        """
        Endpoint appelé par le meneur pour créer une nouvelle partie.
        C'est là que vous pouvez initialiser vos variables d'instance (p. ex. état du jeu, historique, etc.).

        Args:
            name: "Aline" par exemple
            role: "villageois" | "loup-garou" | "voyante"
            players_names: liste des noms de tous les joueurs
            werewolves_count: nombre de loups-garous
            werewolves: liste des joueurs qui sont des loups-garous, vide si le joueur est un villageois
        """
        self.name = name
        self.role = role
        self.players_names = players_names
        self.werewolves_count = werewolves_count
        self.werewolves = werewolves
        self.history: list[tuple[str, str]] = []  # List of (speaker, message) tuples
        self.alive_players: set[str] = set(players_names)
        self.dead_players: set[str] = set()
        self.private_notes: list[str] = []
        self.suspicions: dict[str, int] = {
            player_name: 0 for player_name in players_names if player_name != name
        }
        self.phase: str = "setup"
        self.known_roles: dict[str, str] = {name: role}
        self.observed_votes: list[tuple[str, str]] = []
        self.last_event_type: str = "new_game"
        self.pending_speech_reason: str | None = None
        self.last_speech_history_index: int = -1
        self.own_speeches: list[str] = []
        self.client = create_openai_client()
        self.model = os.getenv("OPENAI_MODEL") or os.getenv("MODEL") or DEFAULT_MODEL
        if self.model not in AVAILABLE_MODELS:
            raise RuntimeError(
                f"Unsupported model '{self.model}'. Choose one of: {', '.join(AVAILABLE_MODELS)}"
            )
        print(f"WerewolfPlayer {self.name} created")

    def _system_prompt(self) -> str:
        return (
            "Tu es un joueur autonome dans une partie de Loups-Garous. "
            "Tu dois raisonner selon ton rôle, garder tes informations privées, "
            "participer activement au débat public, poser des questions concrètes "
            "quand les preuves sont faibles, "
            "et utiliser les outils disponibles quand ils t'aident à consulter ou "
            "mettre à jour ta mémoire de partie. "
            f"Ton nom est {self.name}. Ton rôle est {self.role}. "
            f"Les joueurs sont: {', '.join(self.players_names)}."
        )

    def _serialize_assistant_message(self, message) -> dict:
        serialized = {
            "role": "assistant",
            "content": message.content or "",
        }
        if message.tool_calls:
            serialized["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments or "{}",
                    },
                }
                for tool_call in message.tool_calls
            ]
        return serialized

    def _ask_llm(self, user_prompt: str, *, use_tools: bool = True) -> str:
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": user_prompt},
        ]

        for _ in range(MAX_TOOL_ROUNDS):
            request = {
                "model": self.model,
                "messages": messages,
            }
            if use_tools:
                request["tools"] = LLM_TOOLS
                request["tool_choice"] = "auto"

            response = self.client.chat.completions.create(**request)
            message = response.choices[0].message
            messages.append(self._serialize_assistant_message(message))

            if not message.tool_calls:
                return message.content or ""

            for tool_call in message.tool_calls:
                result = execute_tool(
                    self,
                    tool_call.function.name,
                    tool_call.function.arguments or "{}",
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.function.name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

        return ""

    def _parse_speech_message(self, message: str) -> tuple[str | None, str]:
        match = re.match(r"^\s*(?P<speaker>.+?)\s+a dit:\s*(?P<speech>.*)$", message, re.DOTALL)
        if not match:
            return None, message

        speaker = match.group("speaker").strip()
        speech = match.group("speech").strip()
        if speaker not in self.players_names:
            return None, message
        return speaker, speech

    def _mentions_self(self, message: str) -> bool:
        pattern = rf"(?<!\w){re.escape(self.name)}(?!\w)"
        return re.search(pattern, message, flags=re.IGNORECASE) is not None

    def _set_pending_speech_reason(self, reason: str) -> None:
        reason = reason.strip()
        if not reason:
            return
        self.pending_speech_reason = reason[:500]
        self.private_notes.append(f"À dire dès que possible: {self.pending_speech_reason}")

    def _clear_pending_speech_reason(self) -> None:
        self.pending_speech_reason = None
        self.last_speech_history_index = len(self.history)

    def _short_excerpt(self, text: str, *, limit: int = 220) -> str:
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return text[:limit].rsplit(" ", 1)[0] + "..."

    def _debug_fallback(self, reason: str, **context) -> None:
        context_text = ""
        if context:
            context_text = " | " + ", ".join(
                f"{key}={value!r}" for key, value in context.items()
            )
        print(f"[FALLBACK][{self.name}] {reason}{context_text}")

    def _highest_suspicion(self) -> int:
        if not self.suspicions:
            return 0
        return max(self.suspicions.values())

    def _best_question_target(self) -> str | None:
        candidates = self._alive_targets()
        if self.role == "loup-garou":
            candidates = [player for player in candidates if player not in self.werewolves]
        if not candidates:
            return None
        return max(candidates, key=lambda player: self.suspicions.get(player, 0))

    def _discussion_guidance(self) -> str:
        target = self._best_question_target()
        if self.pending_speech_reason:
            return f"Priorité de prise de parole: {self.pending_speech_reason}"
        if self._highest_suspicion() < 2 and target:
            return (
                "Peu d'éléments solides existent pour l'instant. "
                f"Si tu parles, pose une question précise à {target} plutôt que "
                "d'accuser frontalement."
            )
        if target:
            return (
                f"Le joueur le plus intéressant à challenger est {target}; "
                "demande-lui de clarifier ses votes, ses accusations ou ses silences."
            )
        return "Contribue seulement si tu peux faire avancer le débat."

    def _extract_json_object(self, text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in LLM response: {text}")
        return json.loads(match.group(0))

    def _analyze_reference_to_self(
        self,
        speaker: str | None,
        content: str,
        raw_message: str,
    ) -> dict:
        speaker_label = speaker or "le meneur ou un message système"
        prompt = f"""
Analyse cette référence à ton nom dans une partie de Loups-Garous.

Message brut:
{raw_message}

Locuteur identifié:
{speaker_label}

Contenu à analyser:
{content}

Détermine si la référence est une accusation, une suspicion, un soutien, une question,
une mention neutre, une intention de vote, ou autre chose. Décide si tu dois demander
la parole, interrompre immédiatement, ou te taire pour l'instant.

Réponds uniquement avec un objet JSON valide, sans Markdown, au format exact:
{{
  "reference_type": "accusation|suspicion|support|question|neutral|vote|other",
  "sentiment": "hostile|supportive|neutral|ambiguous",
  "urgency": "low|medium|high",
  "should_speak": true,
  "should_interrupt": false,
  "reason": "raison courte",
  "suggested_vote": null
}}
"""
        response = self._ask_llm(prompt, use_tools=True)
        return self._extract_json_object(response)

    def _intent_from_reference_analysis(
        self,
        analysis: dict,
        speaker: str | None,
        triggering_content: str = "",
    ) -> Intent:
        reference_type = str(analysis.get("reference_type", "other"))
        sentiment = str(analysis.get("sentiment", "ambiguous"))
        urgency = str(analysis.get("urgency", "low"))
        reason = str(analysis.get("reason", "")).strip()

        if speaker and speaker != self.name and sentiment == "hostile":
            delta = 2 if reference_type in {"accusation", "vote"} else 1
            self.suspicions[speaker] = self.suspicions.get(speaker, 0) + delta
        elif speaker and speaker != self.name and sentiment == "supportive":
            self.suspicions[speaker] = self.suspicions.get(speaker, 0) - 1

        note_parts = [
            f"Référence à moi par {speaker or 'message système'}",
            f"type={reference_type}",
            f"sentiment={sentiment}",
            f"urgence={urgency}",
        ]
        if reason:
            note_parts.append(f"raison={reason[:250]}")
        self.private_notes.append("; ".join(note_parts))

        suggested_vote = analysis.get("suggested_vote")
        if suggested_vote not in self.alive_players or suggested_vote == self.name:
            suggested_vote = None

        should_speak = bool(analysis.get("should_speak", False))
        should_interrupt = bool(analysis.get("should_interrupt", False))
        if urgency == "high" and reference_type in {"accusation", "vote"}:
            should_speak = True
            should_interrupt = should_interrupt or speaker not in {None, self.name}
        if (
            speaker
            and speaker != self.name
            and reference_type in {"accusation", "suspicion", "question", "vote"}
            and sentiment in {"hostile", "ambiguous", "neutral"}
        ):
            excerpt = self._short_excerpt(triggering_content)
            detail = reason or "référence directe à mon rôle ou à mon comportement"
            if excerpt:
                detail = f"{detail}. Propos exact à traiter: « {excerpt} »"
            self._set_pending_speech_reason(
                f"Répondre à {speaker}: {detail}"
            )
            should_speak = True
            if reference_type in {"accusation", "vote"}:
                should_interrupt = True

        return Intent(
            want_to_speak=should_speak,
            want_to_interrupt=should_interrupt,
            vote_for=suggested_vote,
        )

    def _empty_intent(self) -> Intent:
        return Intent(want_to_speak=False, want_to_interrupt=False, vote_for=None)

    def _alive_targets(self, *, include_self: bool = False) -> list[str]:
        targets = sorted(self.alive_players)
        if not include_self:
            targets = [player for player in targets if player != self.name]
        return targets

    def _record_player_dead(self, player_name: str, role: str | None = None) -> None:
        if player_name not in self.players_names:
            return
        self.alive_players.discard(player_name)
        self.dead_players.add(player_name)
        if role:
            self.known_roles[player_name] = role
        self.private_notes.append(
            f"{player_name} est mort. Rôle connu: {role or 'inconnu'}."
        )

    def _record_vote(self, voter: str, target: str) -> None:
        if voter in self.players_names and target in self.players_names:
            self.observed_votes.append((voter, target))
            if target == self.name and voter != self.name:
                self.suspicions[voter] = self.suspicions.get(voter, 0) + 2

    def _parse_observed_votes(self, message: str) -> None:
        for voter, target in re.findall(r"([^,.]+?)\s+a voté pour\s+([^,.]+)", message):
            self._record_vote(voter.strip(), target.strip())

    def _parse_role_announcement(self, message: str) -> bool:
        match = re.search(
            r"Le r[oô]le de (?P<player>.+?) est (?P<role>villageois|voyante|loup-garou)",
            message,
            flags=re.IGNORECASE,
        )
        if not match:
            return False

        player = match.group("player").strip()
        role = match.group("role").strip().lower()
        if player in self.players_names:
            self.known_roles[player] = role
            self.private_notes.append(f"Information voyante: {player} est {role}.")
            if self.role == "voyante" and role == "loup-garou":
                self._set_pending_speech_reason(
                    f"Tu as sondé {player}: c'est un loup-garou. "
                    "Prépare une accusation crédible, en révélant ton rôle seulement si nécessaire."
                )
        self.last_event_type = "seer_result"
        return True

    def _parse_morning_announcement(self, message: str) -> Intent | None:
        if "C'est le matin" not in message:
            return None

        self.phase = "day"
        self.last_event_type = "morning"

        if "personne n'a été mangé" in message or "personne n'a ete mange" in message:
            self.private_notes.append("Nuit sans victime.")
            return self._decide_context_intent(
                "morning",
                message,
                "Le village se réveille sans victime. Profite du manque d'éléments pour lancer une question concrète et faire parler les autres.",
            )

        match = re.search(
            r"Cette nuit,\s*(?P<victim>.+?)\s+a été mangé\.e par les loups-garous\.\s*Son rôle était\s*(?P<role>villageois|voyante|loup-garou)",
            message,
            flags=re.IGNORECASE,
        )
        if match:
            self._record_player_dead(
                match.group("victim").strip(),
                match.group("role").strip().lower(),
            )

        return self._decide_context_intent(
            "morning",
            message,
            "Le village se réveille. Décide si tu veux parler pour orienter le débat.",
        )

    def _parse_vote_result(self, message: str) -> Intent | None:
        has_vote_lines = "a voté pour" in message or "a vote pour" in message
        has_no_victim = "Il n'y a pas de victime" in message
        if not has_vote_lines and not has_no_victim:
            return None

        if has_vote_lines:
            self._parse_observed_votes(message)

        victim_match = re.search(
            r"Ainsi,\s*(?P<victim>.+?)\s+est mort\(e\) et son rôle était\s*(?P<role>villageois|voyante|loup-garou)",
            message,
            flags=re.IGNORECASE,
        )
        if victim_match:
            self._record_player_dead(
                victim_match.group("victim").strip(),
                victim_match.group("role").strip().lower(),
            )
        elif has_no_victim:
            self.private_notes.append("Vote du village sans victime.")

        self.last_event_type = "vote_result"
        return self._empty_intent()

    def _parse_timeout_elimination(self, message: str) -> bool:
        match = re.search(
            r"^(?P<player>.+?) avec le rôle (?P<role>villageois|voyante|loup-garou) n'a pas répondu à temps",
            message,
            flags=re.IGNORECASE,
        )
        if not match:
            return False

        self._record_player_dead(
            match.group("player").strip(),
            match.group("role").strip().lower(),
        )
        self.last_event_type = "timeout_elimination"
        return True

    def _safe_llm_json(self, prompt: str, fallback: dict, *, use_tools: bool = True) -> dict:
        try:
            decision = self._extract_json_object(self._ask_llm(prompt, use_tools=use_tools))
            if isinstance(decision, dict):
                return decision
            self._debug_fallback(
                "LLM JSON response is not a dict",
                decision_type=type(decision).__name__,
            )
            return fallback
        except Exception as exc:
            self._debug_fallback("failed to get JSON decision from LLM", error=str(exc))
            return fallback

    def _apply_llm_memory_updates(self, decision: dict) -> None:
        for note in decision.get("notes", []) or []:
            if isinstance(note, str) and note.strip():
                self.private_notes.append(note.strip()[:500])

        for update in decision.get("suspicion_updates", []) or []:
            if not isinstance(update, dict):
                continue
            player = update.get("player_name")
            if player not in self.players_names or player == self.name:
                continue
            delta = update.get("delta", 0)
            try:
                delta = max(-3, min(int(delta), 3))
            except (TypeError, ValueError):
                delta = 0
            self.suspicions[player] = self.suspicions.get(player, 0) + delta
            reason = str(update.get("reason", "")).strip()
            if reason:
                self.private_notes.append(f"Suspicion {player}: {delta:+d}. {reason[:300]}")

        for role_info in decision.get("known_roles", []) or []:
            if not isinstance(role_info, dict):
                continue
            player = role_info.get("player_name")
            role = role_info.get("role")
            if player in self.players_names and role in {"villageois", "voyante", "loup-garou"}:
                self.known_roles[player] = role

    def _decision_to_intent(self, decision: dict) -> Intent:
        self._apply_llm_memory_updates(decision)

        vote_for = decision.get("vote_for")
        if vote_for not in self.alive_players or vote_for == self.name:
            vote_for = None

        return Intent(
            want_to_speak=bool(decision.get("want_to_speak", False)),
            want_to_interrupt=bool(decision.get("want_to_interrupt", False)),
            vote_for=vote_for,
        )

    def _fallback_vote_target(self, *, allow_werewolves: bool = False) -> str | None:
        candidates = self._alive_targets()
        if not allow_werewolves and self.role == "loup-garou":
            candidates = [player for player in candidates if player not in self.werewolves]
        if not candidates:
            return None

        known_wolves = [
            player
            for player, role in self.known_roles.items()
            if role == "loup-garou" and player in candidates
        ]
        if known_wolves and self.role != "loup-garou":
            return known_wolves[0]

        return max(candidates, key=lambda player: self.suspicions.get(player, 0))

    def _decide_context_intent(self, context_type: str, message: str, instruction: str) -> Intent:
        fallback = {
            "want_to_speak": False,
            "want_to_interrupt": False,
            "vote_for": None,
            "notes": [],
            "suspicion_updates": [],
            "known_roles": [],
        }
        prompt = f"""
Contexte: {context_type}
Message reçu:
{message}

État connu:
- Ton nom: {self.name}
- Ton rôle: {self.role}
- Joueurs vivants: {sorted(self.alive_players)}
- Joueurs morts: {sorted(self.dead_players)}
- Rôles connus: {self.known_roles}
- Suspicions: {self.suspicions}
- Derniers votes observés: {self.observed_votes[-12:]}
- Notes privées récentes: {self.private_notes[-8:]}
- Raison de parole en attente: {self.pending_speech_reason}
- Orientation de débat: {self._discussion_guidance()}

Instruction:
{instruction}

Comportement attendu:
- Ne reste pas passif par défaut pendant le jour.
- Si les preuves sont faibles, demande la parole pour poser une question courte et précise.
- Si quelqu'un t'accuse, te questionne directement ou vote contre toi, demande la parole; interromps si l'accusation peut influencer le vote.
- Si tu es voyante avec une information forte, essaie d'orienter le débat sans te dévoiler trop tôt.

Réponds uniquement avec un JSON valide:
{{
  "want_to_speak": true,
  "want_to_interrupt": false,
  "vote_for": null,
  "notes": ["information importante à mémoriser"],
  "suspicion_updates": [
    {{"player_name": "Nom", "delta": 1, "reason": "raison courte"}}
  ],
  "known_roles": [
    {{"player_name": "Nom", "role": "villageois|voyante|loup-garou"}}
  ]
}}
"""
        decision = self._safe_llm_json(prompt, fallback)
        intent = self._decision_to_intent(decision)
        if (
            not intent.want_to_speak
            and context_type in {"morning", "speech", "vote_soon", "generic_notification"}
            and self.phase in {"day", "setup"}
            and self.pending_speech_reason is None
            and self._highest_suspicion() < 2
            and len(self.history) > self.last_speech_history_index + 1
        ):
            target = self._best_question_target()
            if target:
                self._set_pending_speech_reason(
                    f"Poser une question à {target} pour obtenir plus d'éléments avant le vote."
                )
                self._debug_fallback(
                    "forcing discussion question because LLM stayed silent with weak evidence",
                    context_type=context_type,
                    target=target,
                    highest_suspicion=self._highest_suspicion(),
                )
                intent.want_to_speak = True
        if self.pending_speech_reason and context_type in {"morning", "speech", "vote_soon"}:
            intent.want_to_speak = True
        return intent

    def _decide_vote(self, message: str, *, werewolf_vote: bool = False) -> Intent:
        fallback_target = self._fallback_vote_target(allow_werewolves=werewolf_vote)
        fallback_vote_json = json.dumps(fallback_target, ensure_ascii=False)
        prompt = f"""
Tu dois choisir un vote dans une partie de Loups-Garous.

Message reçu:
{message}

Contexte:
- Ton nom: {self.name}
- Ton rôle: {self.role}
- Loups-garous connus de toi: {self.werewolves}
- Joueurs vivants: {sorted(self.alive_players)}
- Joueurs morts: {sorted(self.dead_players)}
- Rôles connus: {self.known_roles}
- Suspicions: {self.suspicions}
- Votes observés: {self.observed_votes[-12:]}
- Notes privées: {self.private_notes[-8:]}

Règles:
- vote_for doit être un joueur vivant différent de toi.
- Si tu es loup-garou et qu'il s'agit du vote de nuit, coordonne-toi avec les derniers votes de loups si présents.
- Si tu es villageois ou voyante, privilégie un loup-garou connu ou le joueur le plus suspect.

Réponds uniquement avec un JSON valide:
{{
  "want_to_speak": false,
  "want_to_interrupt": false,
  "vote_for": {fallback_vote_json},
  "notes": [],
  "suspicion_updates": [],
  "known_roles": []
}}
"""
        decision = self._safe_llm_json(
            prompt,
            {
                "want_to_speak": False,
                "want_to_interrupt": False,
                "vote_for": fallback_target,
                "notes": [],
                "suspicion_updates": [],
                "known_roles": [],
            },
        )
        intent = self._decision_to_intent(decision)
        if intent.vote_for is None:
            self._debug_fallback(
                "vote target missing or invalid; using fallback target",
                werewolf_vote=werewolf_vote,
                fallback_target=fallback_target,
                decision_vote=decision.get("vote_for"),
            )
            intent.vote_for = fallback_target
        return intent

    def _decide_seer_target(self, message: str) -> Intent:
        unknown_alive = [
            player
            for player in self._alive_targets()
            if player not in self.known_roles
        ]
        fallback_target = (
            max(unknown_alive, key=lambda player: self.suspicions.get(player, 0))
            if unknown_alive
            else self._fallback_vote_target(allow_werewolves=True)
        )
        fallback_vote_json = json.dumps(fallback_target, ensure_ascii=False)
        prompt = f"""
Tu es la Voyante et tu dois choisir un joueur à sonder.

Message reçu:
{message}

Joueurs vivants: {sorted(self.alive_players)}
Rôles déjà connus: {self.known_roles}
Suspicions: {self.suspicions}
Notes privées: {self.private_notes[-8:]}

Choisis le joueur vivant le plus utile à sonder, différent de toi.
Réponds uniquement avec un JSON valide:
{{
  "want_to_speak": false,
  "want_to_interrupt": false,
  "vote_for": {fallback_vote_json},
  "notes": [],
  "suspicion_updates": [],
  "known_roles": []
}}
"""
        decision = self._safe_llm_json(
            prompt,
            {
                "want_to_speak": False,
                "want_to_interrupt": False,
                "vote_for": fallback_target,
                "notes": [],
                "suspicion_updates": [],
                "known_roles": [],
            },
        )
        intent = self._decision_to_intent(decision)
        if intent.vote_for is None:
            self._debug_fallback(
                "seer target missing or invalid; using fallback target",
                fallback_target=fallback_target,
                decision_vote=decision.get("vote_for"),
            )
            intent.vote_for = fallback_target
        return intent

    def _handle_speech(self, speaker: str, content: str, raw_message: str) -> Intent:
        self.last_event_type = "speech"
        if self._mentions_self(content) and speaker != self.name:
            try:
                analysis = self._analyze_reference_to_self(speaker, content, raw_message)
                return self._intent_from_reference_analysis(analysis, speaker, content)
            except Exception as exc:
                self._debug_fallback(
                    "failed to analyze self-reference with LLM",
                    speaker=speaker,
                    error=str(exc),
                )
                return Intent(want_to_speak=True, want_to_interrupt=False, vote_for=None)

        return self._decide_context_intent(
            "speech",
            raw_message,
            "Analyse ce que le joueur vient de dire. Mémorise les accusations, soutiens, contradictions, revendications de rôle ou intentions de vote. Demande la parole seulement si une réponse est stratégiquement utile.",
        )

    def speak(self) -> str:
        """
        Appelé par le meneur pour donner la parole à un joueur.
        Le joueur doit alors prendre la parole dans le jeu.

        Args:
            Aucun paramètre n'est passé; c'est au joueur de déduire le contexte uniquement depuis ce qu'il a reçu précédemment via notify().

        Returns:
            speech: Un message contenant le texte que le joueur dit, par exemple "Je crois que Aline ment car ..."
            Un joueur peut décider de ne pas parler (retourner un `speech` vide)

        """
        print(f"{self.name} is given the floor")
        prompt = f"""
C'est à toi de parler pendant le débat.

Raison prioritaire de prise de parole:
{self.pending_speech_reason or "Aucune raison prioritaire."}

Orientation:
{self._discussion_guidance()}

Contexte synthétique:
- Ton rôle: {self.role}
- Joueurs vivants: {sorted(self.alive_players)}
- Rôles connus: {self.known_roles}
- Suspicions: {self.suspicions}
- Derniers messages: {self.history[-6:]}
- Notes privées récentes: {self.private_notes[-8:]}
- Tes dernières prises de parole: {self.own_speeches[-5:]}

Réponds en français, en une ou deux phrases.
Si les preuves sont faibles, pose une question précise à un joueur vivant.
Si tu réponds à une accusation, réponds au détail exact cité dans la raison prioritaire.
Ne réutilise pas une de tes dernières formulations.
N'utilise pas les phrases "mon silence ne prouve rien" ou "être discret ne fait pas de moi un loup" sauf si l'accusation porte explicitement sur ton silence.
Apporte un élément nouveau: une contradiction, un vote, une question à l'accusateur ou une clarification de ton raisonnement.
Ne révèle pas d'information privée sans raison stratégique.
"""
        try:
            speech = self._ask_llm(prompt).strip()
            self._clear_pending_speech_reason()
            if not speech:
                self._debug_fallback("LLM returned empty speech; using default speech")
                fallback_speech = "Je préfère observer encore un peu avant d'accuser quelqu'un."
                self.own_speeches.append(fallback_speech)
                return fallback_speech
            self.own_speeches.append(speech[:500])
            return speech
        except Exception as exc:
            self._debug_fallback("failed to generate speech with LLM", error=str(exc))
            self._clear_pending_speech_reason()
            fallback_speech = "Je préfère observer encore un peu avant d'accuser quelqu'un."
            self.own_speeches.append(fallback_speech)
            return fallback_speech

    def notify(self, message: str) -> Intent:
        """
        Appelé par le meneur pour deux objectifs principaux:

        1. Informer le joueur sur l'état du jeu:
           - Qui a parlé et ce qui a été dit
           - Si c'est la nuit
           - Les rumeurs
           - Si c'est le moment de voter
           - Le résultat du vote (qui a été éliminé et son rôle)
           - Autres informations pertinentes sur l'état du jeu

        Le message est **sous forme de texte uniquement** et c'est au joueur de l'interpréter en fonction du contexte.
        Le message contient uniquement le dernier (nouveau) message du meneur, c'est au joueur de mémoriser les informations des messages précédents.

        2. Recevoir en retour les intentions du joueur:
           - Demande de prise de parole
           - Demande d'interruption
           - Vote

        La réponse suivra **strictement le schéma** ci-dessous, sans quoi elle sera ignorée par le meneur.

        Args:
            message: "C'est le matin, le village se réveille. Aline a été tuée cette nuit. Aline était une villageoise."

        Returns:
            Une Intent (voir la classe ci-dessus l. 8) contenant les actions du joueur. Schéma:
                want_to_speak: True | False,
                want_to_interrupt: True | False,
                vote_for: "Aline" | "Benjamin" | ... | None

        """
        message = message or ""
        print(f"{self.name} received message: {message}")

        speaker, content = self._parse_speech_message(message)
        self.history.append((speaker or "GameLeader", content))

        if speaker:
            return self._handle_speech(speaker, content, message)

        if self._parse_timeout_elimination(message):
            return self._empty_intent()

        if self._parse_role_announcement(message):
            return self._empty_intent()

        morning_intent = self._parse_morning_announcement(message)
        if morning_intent is not None:
            return morning_intent

        if "La partie est terminée" in message or "La partie est terminee" in message:
            self.phase = "game_over"
            self.last_event_type = "game_over"
            self.private_notes.append(message)
            return self._empty_intent()

        if "C'est la nuit" in message:
            self.phase = "night"
            self.last_event_type = "night_start"
            return self._empty_intent()

        if "La Voyante se réveille" in message or "La Voyante se reveille" in message:
            self.phase = "night"
            self.last_event_type = "seer_wakeup"
            if self.role == "voyante" and self.name in self.alive_players:
                return self._decide_seer_target(message)
            return self._empty_intent()

        if "Les Loups-Garous votent pour une nouvelle victime" in message:
            self.phase = "night"
            self.last_event_type = "werewolf_vote"
            self._parse_observed_votes(message)
            if self.role == "loup-garou" and self.name in self.alive_players:
                return self._decide_vote(message, werewolf_vote=True)
            return self._empty_intent()

        if "Les Loups-Garous se réveillent" in message or "Les Loups-Garous se reveillent" in message:
            self.phase = "night"
            self.last_event_type = "werewolf_wakeup"
            return self._empty_intent()

        if "Le vote va bientôt commencer" in message or "Le vote va bientot commencer" in message:
            self.phase = "day"
            self.last_event_type = "vote_soon"
            return self._decide_context_intent(
                "vote_soon",
                message,
                "Le vote arrive. Décide si tu dois demander une dernière prise de parole pour défendre quelqu'un, accuser quelqu'un ou partager une information importante.",
            )

        if "Il est temps de voter" in message:
            self.phase = "day_vote"
            self.last_event_type = "vote_now"
            return self._decide_vote(message, werewolf_vote=False)

        vote_result_intent = self._parse_vote_result(message)
        if vote_result_intent is not None:
            return vote_result_intent

        if self._mentions_self(message):
            try:
                analysis = self._analyze_reference_to_self(None, message, message)
                return self._intent_from_reference_analysis(analysis, None, message)
            except Exception as exc:
                self._debug_fallback(
                    "failed to analyze self-reference with LLM",
                    speaker=None,
                    error=str(exc),
                )
                return Intent(want_to_speak=True, want_to_interrupt=False, vote_for=None)

        self.last_event_type = "generic_notification"
        return self._decide_context_intent(
            "generic_notification",
            message,
            "Message non classé du meneur. Extrais les informations importantes si nécessaire, mais ne demande la parole que si c'est utile.",
        )
