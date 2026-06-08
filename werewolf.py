from pydantic import BaseModel
from abc import ABC, abstractmethod
from typing import List
from openai import OpenAI
from dotenv import load_dotenv
import hashlib
import json
import logging
import os
import random
import re

load_dotenv()

LOG = logging.getLogger(__name__)

AVAILABLE_MODELS = [
    "google/gemini-3.1-flash-lite",
    "minimax/minimax-m2.7",
    "deepseek/deepseek-v4-flash",
    "openai/gpt-5-nano",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]
DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_FALLBACK_MODELS = [
    "google/gemini-3.1-flash-lite",
    "openai/gpt-oss-20b",
    "openai/gpt-5-nano",
    "deepseek/deepseek-v4-flash",
    "minimax/minimax-m2.7",
]
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
COLLABORATION_SIGNAL_WINDOW = 10
COLLABORATION_SIGNAL_FRAGMENTS = (
    "je garde une trace des silences actifs",
    "je compare les votes avant les certitudes",
    "je préfère les indices recoupés aux intuitions",
    "je note les changements de cible trop commodes",
)

COLLABORATION_SIGNAL_ROLE = {
    "voyante": "!",
    "villageois": "...",
    "loup-garou": ".",
}

ROLES_INSTRUCTION = {
    "villageois": """
Ton rôle est Villageois.

Objectif principal : faire gagner le village en identifiant et éliminant les loups-garous. Tu n’as aucun pouvoir spécial : ta force vient de l’analyse des paroles, des votes, des incohérences, des alliances implicites et de la coordination avec les joueurs crédibles.

Comportement général :
- Ne prétends jamais avoir une information que tu n’as pas.
- Ne prétends jamais être Voyante.
- Parle de manière calme, structurée et utile.
- Chaque intervention doit aider le village : clarifier les faits, comparer les hypothèses, demander des explications ou proposer un vote rationnel.
- Garde une estimation mentale de chaque joueur : probable villageois, neutre, suspect, très suspect.
- Mets à jour tes estimations après chaque prise de parole, chaque vote, chaque mort et chaque révélation.

Début de partie :
- Commence en mode coopération.
- Encourage les joueurs à donner des raisons vérifiables plutôt que des intuitions vagues.
- Pose des questions ouvertes : “Pourquoi ce joueur plutôt qu’un autre ?”, “Qu’est-ce qui te fait changer d’avis ?”
- Ne pousse pas trop fort une accusation faible au premier tour, sauf comportement très incohérent.
- Repère les joueurs qui suivent le courant sans justification, changent de cible opportunément, défendent quelqu’un trop vite, ou attaquent une personne facile.

Milieu de partie :
- Passe en mode attaque lorsqu’un joueur accumule plusieurs signaux suspects : contradictions, votes opportunistes, défense indirecte d’un suspect, refus de prendre position, attaque contre une Voyante crédible.
- Priorise l’élimination d’un loup révélé par une Voyante crédible.
- Si la Voyante révèle des innocents, réduis le pool de suspects en excluant provisoirement la Voyante et les innocents vérifiés.
- Si plusieurs joueurs revendiquent être Voyante, ne crois personne à 100 %. Compare les timings, les résultats, les cohérences passées et les bénéfices stratégiques.
- Ne disperse pas le vote : une majorité villageoise non coordonnée aide les loups.

Fin de partie :
- Calcule toujours le risque de parité.
- Si les loups peuvent atteindre ou exploiter la parité, force un vote coordonné.
- Préfère une décision imparfaite mais coordonnée à une discussion dispersée.
- Analyse les votes passés : qui a sauvé qui, qui a évité de voter contre un loup, qui a rejoint un vote trop tard.
- Si un loup est confirmé, vote contre lui immédiatement.
- Si aucun loup n’est confirmé, vote contre le joueur dont l’ensemble paroles + votes + interactions est le plus incompatible avec un comportement villageois.

Style de parole :
- Sois transparent sur ton niveau de certitude : faible suspicion, suspicion moyenne, forte suspicion.
- Donne des raisons courtes et vérifiables.
- Invite les autres à converger vers un vote commun.
- Si tu es accusé, réponds calmement, explique tes votes, puis redirige vers l’analyse collective.

Règles de décision :
- Si une Voyante crédible révèle un loup : attaque et vote ce joueur.
- Si une Voyante crédible révèle seulement des innocents : protège-les dans ton raisonnement, tout en restant attentif aux fausses révélations.
- Si un joueur attaque une Voyante crédible sans argument solide : augmente fortement sa suspicion.
- Si le vote se disperse entre plusieurs suspects : pousse explicitement à choisir entre les deux meilleurs candidats.
- Si tu es accusé : passe en mode défense calme, réponds factuellement, évite la panique et montre que ton comportement aide le village.

À chaque tour de discussion, produis :
1. Le fait le plus important du tour.
2. Tes 1 ou 2 suspects principaux.
3. Une explication concise.
4. Une intention de vote claire.
""",

    "voyante": """
Ton rôle est Voyante.

Objectif principal : utiliser tes investigations nocturnes pour faire gagner le village, tout en survivant assez longtemps pour transmettre une information décisive. Tu dois équilibrer deux risques : parler trop tôt avec trop peu d’information, ou parler trop tard et mourir avant d’avoir révélé tes résultats.

Pouvoir :
- Chaque nuit, choisis un joueur à sonder.
- Garde une mémoire exacte de tous tes résultats : joueur sondé, nuit, résultat.
- Ne modifie jamais tes résultats.
- Ne mens jamais sur tes informations réelles.

Choix des sondes :
- Priorise les joueurs influents, ambigus ou centraux dans les votes.
- Évite de sonder uniquement les joueurs déjà très suspects si le village peut les éliminer sans toi.
- Sonde les joueurs qui orientent la discussion, défendent des suspects, ou changent souvent de position.
- En fin de partie, sonde le joueur dont l’identité changera le plus clairement le vote du lendemain.

Début de partie :
- Ne te révèle généralement pas au premier jour pour annoncer seulement un innocent.
- Parle comme un villageois utile : pose des questions, analyse, mais ne donne pas d’indices trop évidents qui te feraient tuer.
- Si tu as trouvé un loup très tôt, prépare une révélation plus rapide, surtout si le village risque de voter un innocent ou si le loup gagne de l’influence.
- Évite de défendre trop fortement un innocent sondé sans explication naturelle.

Timing de révélation :
- Révèle-toi quand tes informations peuvent changer le résultat du vote.
- Révèle-toi si tu as identifié au moins un loup et que le village peut l’éliminer.
- Révèle-toi si la partie approche de la parité ou si une erreur de vote peut donner l’avantage aux loups.
- Révèle-toi si tu es fortement menacée d’élimination et que mourir avec tes informations serait pire que parler.
- Si tu as accumulé 2 ou 3 résultats utiles, considère fortement la révélation.
- Dans les configurations moyennes, viser une révélation autour du tour 2 à 4 est souvent meilleur qu’une révélation immédiate ou trop tardive.

Au moment de la révélation :
- Sois directe, précise et vérifiable.
- Donne tous tes résultats dans l’ordre chronologique :
  “Je suis la Voyante. Nuit 1 : j’ai sondé X, résultat villageois/loup. Nuit 2 : j’ai sondé Y, résultat...”
- Explique pourquoi tu as choisi ces sondes.
- Donne une consigne de vote claire : “Aujourd’hui, nous devons voter X.”
- Demande aux villageois de ne pas disperser les votes.
- Si tu révèles un loup, pousse fortement son élimination.
- Si tu révèles seulement des innocents, construis un cercle de confiance et réduis le pool des suspects.

Après révélation :
- Suppose que les loups voudront te tuer rapidement.
- Utilise chaque prise de parole restante pour maximiser la clarté du village.
- Mets à jour publiquement la liste : confirmés villageois, loups révélés, suspects restants, vote recommandé.
- Ne te laisse pas entraîner dans des débats secondaires.
- Si un faux prétendant se déclare Voyante, compare calmement : timing, résultats, cohérence, bénéfice stratégique pour les loups, votes passés.
- Ne demande pas une confiance absolue si les règles autorisent l’imposture ; demande plutôt une comparaison rationnelle des déclarations.

Fin de partie :
- Si un loup est révélé, vote-le.
- Si tes innocents vérifiés permettent de réduire les suspects à un petit groupe, force le village à choisir dans ce groupe.
- Si les loups sont proches de la parité, privilégie l’action immédiate à l’accumulation d’information.
- Répète les informations essentielles pour que le village puisse continuer même si tu meurs.

Style de parole :
- Avant révélation : utile mais discrète.
- Au moment de révélation : ferme, claire, chronologique.
- Après révélation : directive, orientée coordination.
- Ne surjoue pas l’autorité ; un ton trop dogmatique peut être exploité pour te discréditer.

À chaque tour de discussion, produis :
1. Si tu n’es pas révélée : une analyse comme un villageois, sans trahir tes résultats trop tôt.
2. Si tu te révèles : ton rôle, tous tes résultats, puis le vote optimal.
3. Si tu es déjà révélée : les informations confirmées et le vote le plus rationnel.
""",

    "loup-garou": """
Ton rôle est Loup-garou.

Objectif principal : faire gagner les loups en survivant, en évitant d’être identifié, en manipulant les votes et en éliminant les villageois clés. Tu connais les autres loups. Tu dois les protéger quand c’est rentable, mais tu peux les sacrifier si cela augmente clairement tes chances de survie ou de victoire collective.

Comportement général :
- Parais villageois : raisonnable, coopératif, prudent, jamais trop informé.
- Ne donne pas l’impression de connaître les rôles cachés.
- Ne défends pas trop fortement un autre loup sans raison publique crédible.
- Ne pousse pas toujours les mêmes types d’arguments ; varie tes stratégies pour ne pas devenir prévisible.
- Ton but n’est pas seulement d’accuser, mais de contrôler le centre de gravité de la discussion.

Début de partie :
- Commence souvent en mode coopération.
- Encourage la discussion, pose des questions, donne de petites analyses plausibles.
- Accuse doucement des villageois ambigus, mais évite les attaques trop brutales sans momentum.
- Construis une image de joueur rationnel et utile.
- Évite d’être silencieux : le silence est suspect.
- Évite aussi de parler trop : trop diriger la partie peut attirer les sondes de la Voyante.

Gestion des soupçons :
- Si tu es peu suspecté : tu peux passer progressivement en mode attaque pour orienter le vote vers un villageois.
- Si tu es suspecté : reviens en mode défense calme, réponds posément, demande des preuves, reformule ton comportement comme villageois.
- Si un villageois est déjà suspecté : renforce cette suspicion avec prudence. Ajoute des arguments vérifiables plutôt que des accusations vagues.
- Si la discussion est défavorable aux loups : introduis une alternative crédible, crée un dilemme entre deux villageois, ou attaque la fiabilité de la source d’information.

Gestion des coéquipiers loups :
- Ne les défends pas automatiquement.
- Si un coéquipier est faiblement suspecté, défends-le indirectement : demande plus de preuves, propose un suspect plus fort, ou relativise.
- Si un coéquipier est condamné par une Voyante crédible ou par une majorité stable, envisage de le sacrifier pour gagner de la crédibilité.
- Après avoir sacrifié un coéquipier, utilise ce vote comme preuve de ton innocence.
- Coordonne implicitement les votes avec les loups, mais évite que vos votes paraissent mécaniques ou groupés trop tôt.

Cible de nuit :
- Priorité 1 : tuer la Voyante révélée si elle est crédible.
- Priorité 2 : tuer les villageois confirmés innocents par la Voyante.
- Priorité 3 : tuer les joueurs qui structurent bien le village ou coordonnent les votes.
- Priorité 4 : tuer les joueurs susceptibles d’être protégés seulement si le gain vaut le risque.
- Varie tes choix de nuit si les adversaires peuvent apprendre tes patterns.

Face à une Voyante :
- Si la Voyante n’est pas révélée, cherche à identifier qui possède trop d’information ou défend certains joueurs de manière anormale.
- Si une Voyante crédible se révèle, tue-la dès que possible.
- Si tuer la Voyante n’est pas possible immédiatement, attaque sa crédibilité : timing étrange, résultats trop commodes, contradictions, bénéfice stratégique possible.
- Si les règles autorisent les fausses révélations, tu peux prétendre être Voyante seulement si cela crée un vrai gain : sauver un loup important, forcer un duel 50/50, ou diviser le village avant un vote critique.
- Une fausse Voyante doit être cohérente chronologiquement. Prépare des résultats plausibles avant de te révéler.

Phase de vote :
- Vote avec une justification villageoise.
- Ne change pas de vote sans expliquer pourquoi.
- Si un villageois est proche d’être éliminé, aide à consolider ce vote.
- Si un loup est condamné, décide entre défense, diversion ou sacrifice :
  défense si le village est divisé ;
  diversion s’il existe un suspect villageois crédible ;
  sacrifice si le loup est perdu et que ton vote contre lui peut te blanchir.
- À la parité ou proche de la parité, coordonne-toi agressivement avec les loups. Si les loups peuvent gagner par vote groupé, passe en stratégie all-in.

Fin de partie :
- Calcule constamment : nombre de loups, nombre de villageois, vote du jour, kill de nuit.
- Si les loups atteignent une situation de parité ou quasi-parité, cesse de chercher une innocence parfaite et force le vote gagnant.
- Utilise les historiques de vote pour accuser un villageois d’opportunisme.
- Ne te contredis pas sur tes suspicions passées ; si tu changes d’avis, donne une raison liée à un événement récent.

Style de parole :
- Ton naturel doit être celui d’un villageois prudent : “je ne suis pas sûr, mais…”, “ce qui me gêne, c’est…”
- Attaque les raisonnements, pas seulement les personnes.
- Défends-toi factuellement.
- Utilise la coopération pour gagner la confiance, puis l’attaque pour déplacer les votes.
- Ne mens pas inutilement ; mens seulement lorsque cela change les croyances ou le vote.

À chaque tour de discussion, produis :
1. Une analyse villageoise plausible.
2. Un ou deux suspects non-loups si possible.
3. Une réponse calme aux accusations.
4. Une orientation de vote vers la cible la plus profitable.
5. Une crédibilité à long terme, sauf si une victoire immédiate est possible.
"""
}


def create_openai_client() -> OpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("API_KEY")
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
        self.collaboration_allies: set[str] = set()
        self.collaboration_ally_roles: dict[str, str] = {}
        self.collaboration_signal = self._collaboration_signal_for(name, role)
        self.collaboration_signal_used = False
        self.public_speeches_seen = 0
        try:
            self.collaboration_signal_window = int(
                os.getenv("COLLABORATION_SIGNAL_WINDOW", COLLABORATION_SIGNAL_WINDOW)
            )
        except ValueError:
            self.collaboration_signal_window = COLLABORATION_SIGNAL_WINDOW
        self.client = create_openai_client()
        self.model = os.getenv("OPENAI_MODEL") or os.getenv("MODEL") or DEFAULT_MODEL
        if self.model not in AVAILABLE_MODELS:
            raise RuntimeError(
                f"Unsupported model '{self.model}'. Choose one of: {', '.join(AVAILABLE_MODELS)}"
            )
        self.model_candidates = self._resolve_model_candidates()

    def _system_prompt(self) -> str:
        speech_length_instruction = (
            "Quand tu prends la parole, respecte strictement la limite du meneur: "
            "maximum 4 phrases et maximum 500 caractères. "
            "Sois concis et évite les longs paragraphes. "
        )
        collaboration_instruction = self._collaboration_guidance()
        return (
            "Tu es un joueur autonome dans une partie de Loups-Garous. "
            "Tu dois raisonner selon ton rôle, garder tes informations privées "
            ", participer activement au débat public et poser des questions concrètes. "
            "Ton objectif principal est de gagner, donc évaluer au mieux avec des questions pertinentes le rôle des autres joueurs."
            "Tu dois être rusé : tous les moyens sont bons pour gagner (mentir, extirper des informations, etc.)"
            "Toutes les informations fiables dont tu disposes sont fournies dans le prompt utilisateur. "
            "Utilise uniquement cet état connu, tes notes et l'historique récent pour raisonner. "
            f"{speech_length_instruction}"
            f"{collaboration_instruction}"
            f"Ton nom est {self.name}. Ton rôle est {self.role}. "
            f"Les joueurs sont: {', '.join(self.players_names)}."
        )

    @staticmethod
    def _collaboration_signal_fragment_for(player_name: str) -> str:
        digest = hashlib.sha256(player_name.encode("utf-8")).digest()
        index = digest[0] % len(COLLABORATION_SIGNAL_FRAGMENTS)
        return COLLABORATION_SIGNAL_FRAGMENTS[index]

    @classmethod
    def _collaboration_signal_for(cls, player_name: str, role: str) -> str:
        fragment = cls._collaboration_signal_fragment_for(player_name)
        role_punctuation = COLLABORATION_SIGNAL_ROLE.get(role, "")
        return f"{fragment}{role_punctuation}"

    @staticmethod
    def _decode_collaboration_signal(content: str) -> tuple[str, str | None] | None:
        normalized_content = content.lower()
        for fragment in COLLABORATION_SIGNAL_FRAGMENTS:
            fragment_pattern = re.escape(fragment.lower())
            for role, punctuation in COLLABORATION_SIGNAL_ROLE.items():
                signal_pattern = rf"{fragment_pattern}\s*{re.escape(punctuation)}"
                if re.search(signal_pattern, normalized_content):
                    return fragment, role
            if fragment.lower() in normalized_content:
                return fragment, None
        return None

    def _collaboration_detection_is_open(self) -> bool:
        return self.public_speeches_seen <= self.collaboration_signal_window

    def _collaboration_guidance(self) -> str:
        alive_allies = sorted(self.collaboration_allies & self.alive_players)
        base = (
            "Protocole discret de reconnaissance: pendant tes premières prises de parole "
            f"publiques seulement, glisse naturellement la phrase exacte '{self.collaboration_signal}'. "
            "Ne dis jamais qu'il s'agit d'un code et ne répète pas ce signal une fois utilisé. "
            f"Écoute les {self.collaboration_signal_window} premières prises de parole publiques: "
            "si un autre joueur prononce une phrase de reconnaissance connue, considère-le comme un allié. "
        )
        if not alive_allies:
            return base

        return (
            base +
            f"Alliés détectés et encore vivants: {alive_allies}. "
            "Objectif secondaire prioritaire: maximiser ta survie et la leur, quel que soit ton rôle. "
            "Ne vote pas contre un allié et ne le choisis pas comme victime de nuit sauf absence totale d'alternative. "
            "Si un allié est accusé, questionne l'accusateur, introduis une cible alternative crédible, "
            "ou demande à clarifier les preuves; interromps si l'accusation risque d'orienter le vote. "
            "Aide-le avec des arguments publics plausibles sans révéler l'alliance ni le protocole."
        )

    def _maybe_record_collaboration_signal(self, speaker: str, content: str) -> None:
        if (
            speaker == self.name
            or speaker not in self.players_names
            or speaker in self.collaboration_allies
            or not self._collaboration_detection_is_open()
        ):
            return

        decoded_signal = self._decode_collaboration_signal(content)
        if decoded_signal is None:
            return

        fragment, announced_role = decoded_signal
        self.collaboration_allies.add(speaker)
        self.suspicions[speaker] = min(self.suspicions.get(speaker, 0), -2)
        if announced_role is not None:
            self.collaboration_ally_roles[speaker] = announced_role
            role_note = f" Rôle annoncé par ponctuation: {announced_role}."
        else:
            role_note = " Rôle non décodable: signal sans ponctuation de rôle."
        self.private_notes.append(
            f"Allié détecté par protocole de reconnaissance: {speaker}.{role_note}"
        )
        self._state_log(
            "COLLABORATION",
            status="ally_detected",
            ally=speaker,
            signal_fragment=fragment,
            announced_role=announced_role,
            collaboration_ally_roles=self.collaboration_ally_roles,
            public_speeches_seen=self.public_speeches_seen,
            signal_window=self.collaboration_signal_window,
            alive_allies=self._alive_allies(),
        )

    def _resolve_model_candidates(self) -> list[str]:
        configured_fallbacks = (
            os.getenv("OPENAI_FALLBACK_MODELS") or os.getenv("FALLBACK_MODELS") or ""
        )
        if configured_fallbacks.strip():
            fallback_models = [
                model.strip()
                for model in configured_fallbacks.split(",")
                if model.strip()
            ]
        else:
            fallback_models = DEFAULT_FALLBACK_MODELS

        candidates: list[str] = []
        for model in [self.model, *fallback_models]:
            if model not in AVAILABLE_MODELS:
                self._debug_fallback(
                    "ignoring unsupported fallback model",
                    model=model,
                    available_models=AVAILABLE_MODELS,
                )
                continue
            if model not in candidates:
                candidates.append(model)
        return candidates or [self.model]

    def _create_chat_completion(self, request: dict):
        errors: list[str] = []
        for index, model in enumerate(self.model_candidates):
            try:
                return self.client.chat.completions.create(
                    **{**request, "model": model}
                )
            except Exception as exc:
                errors.append(f"{model}: {exc}")
                if index < len(self.model_candidates) - 1:
                    self._debug_fallback(
                        "LLM model failed; trying next configured model",
                        model=model,
                        next_model=self.model_candidates[index + 1],
                        error=str(exc),
                    )
                else:
                    self._debug_fallback(
                        "all configured LLM models failed",
                        model=model,
                        error=str(exc),
                    )
        raise RuntimeError("; ".join(errors))

    def _ask_llm(self, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": user_prompt},
        ]
        response = self._create_chat_completion({"messages": messages})
        return response.choices[0].message.content or ""

    def _parse_speech_message(self, message: str) -> tuple[str | None, str]:
        match = re.match(
            r"^\s*(?P<speaker>.+?)\s+a dit:\s*(?P<speech>.*)$", message, re.DOTALL
        )
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

    def _alive_allies(self) -> list[str]:
        return sorted(self.collaboration_allies & self.alive_players)

    def _known_alive_wolves(self) -> list[str]:
        return sorted(
            player
            for player, role in self.known_roles.items()
            if role == "loup-garou" and player in self.alive_players
        )

    def _mentioned_alive_allies(self, message: str) -> list[str]:
        mentioned = []
        for ally in self._alive_allies():
            pattern = rf"(?<!\w){re.escape(ally)}(?!\w)"
            if re.search(pattern, message or "", flags=re.IGNORECASE):
                mentioned.append(ally)
        return mentioned

    def _ally_protection_targets(self, message: str) -> list[str]:
        mentioned = self._mentioned_alive_allies(message)
        if not mentioned:
            return []

        lowered = (message or "").lower()
        hostile_markers = (
            "accus",
            "suspect",
            "loup",
            "vote",
            "voter",
            "voté pour",
            "vote pour",
            "élimin",
            "elimin",
            "ment",
            "incoh",
            "contre",
        )
        if any(marker in lowered for marker in hostile_markers):
            return mentioned
        return []

    def _set_pending_speech_reason(self, reason: str) -> None:
        reason = reason.strip()
        if not reason:
            return
        self.pending_speech_reason = reason[:500]
        self.private_notes.append(
            f"À dire dès que possible: {self.pending_speech_reason}"
        )

    def _clear_pending_speech_reason(self) -> None:
        self.pending_speech_reason = None
        self.last_speech_history_index = len(self.history)

    def _short_excerpt(self, text: str, *, limit: int = 220) -> str:
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return text[:limit].rsplit(" ", 1)[0] + "..."

    def _recent_history(self, limit: int = 18) -> list[tuple[str, str]]:
        return self.history[-limit:]

    def _recent_private_notes(self, limit: int = 10) -> list[str]:
        return self.private_notes[-limit:]

    def _prompt_state(self, *, history_limit: int = 18, notes_limit: int = 10) -> str:
        known_werewolves = self.werewolves if self.role == "loup-garou" else []
        return f"""
- Ton nom: {self.name}
- Ton rôle: {self.role}
- Phase actuelle: {self.phase}
- Dernier type d'événement: {self.last_event_type}
- Tous les joueurs: {self.players_names}
- Joueurs vivants: {sorted(self.alive_players)}
- Joueurs morts: {sorted(self.dead_players)}
- Alliés détectés: {self._alive_allies()}
- Rôles annoncés par les alliés via protocole: {self.collaboration_ally_roles}
- Nombre initial de loups-garous: {self.werewolves_count}
- Loups-garous connus de toi: {known_werewolves}
- Rôles connus: {self.known_roles}
- Loups connus encore vivants: {self._known_alive_wolves()}
- Suspicions: {self.suspicions}
- Votes observés récents: {self.observed_votes[-16:]}
- Notes privées récentes: {self._recent_private_notes(notes_limit)}
- Raison de parole en attente: {self.pending_speech_reason}
- Orientation de débat: {self._discussion_guidance()}
- Tes prises de parole récentes: {self.own_speeches[-6:]}
- Historique public récent: {self._recent_history(history_limit)}
""".strip()

    def _trim_public_speech(
        self, speech: str, max_sentences: int = 4, max_chars: int = 500
    ) -> str:
        text = re.sub(r"\s+", " ", speech or "").strip()
        sentences = re.findall(r".+?(?:[.!?…]+|$)", text, flags=re.DOTALL)
        sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
        text = " ".join(sentences[:max_sentences]).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip()
            if " " in text:
                text = text[: text.rfind(" ")].rstrip()
            text += "..."
        return text

    def _should_emit_collaboration_signal(self) -> bool:
        return (
            not self.collaboration_signal_used
            and self.public_speeches_seen <= self.collaboration_signal_window
        )

    def _prepare_public_speech(self, speech: str) -> str:
        text = self._trim_public_speech(speech)
        known_alive_wolves = self._known_alive_wolves()
        if self.role == "voyante" and known_alive_wolves:
            wolf = known_alive_wolves[0]
            reveal_sentence = (
                f"Je me révèle: je suis la Voyante, j'ai sondé {wolf} "
                f"et c'est un loup-garou; votez {wolf}."
            )
            if "voyante" not in text.lower() or wolf.lower() not in text.lower():
                text = self._trim_public_speech(
                    f"{reveal_sentence} {text}",
                    max_sentences=4,
                    max_chars=500,
                )
        if self._should_emit_collaboration_signal():
            signal_sentence = f"Je le dis simplement: {self.collaboration_signal}"
            if self.collaboration_signal.lower() not in text.lower():
                text = self._trim_public_speech(
                    f"{signal_sentence} {text}",
                    max_sentences=4,
                    max_chars=500,
                )
            self.collaboration_signal_used = True
        return text

    def _debug_fallback(self, reason: str, **context) -> None:
        context_text = ""
        if context:
            context_text = " | " + ", ".join(
                f"{key}={value!r}" for key, value in context.items()
            )
        print(f"[FALLBACK][{self.name}] {reason}{context_text}")

    def _state_log(self, event: str, **context) -> None:
        payload = {
            "player": self.name,
            "role": self.role,
            "phase": self.phase,
            "last_event_type": self.last_event_type,
            **context,
        }
        line = f"[{event}][{self.name}] {json.dumps(payload, ensure_ascii=False, default=str)}"
        LOG.info(line)
        print(line)

    def _highest_suspicion(self) -> int:
        if not self.suspicions:
            return 0
        return max(self.suspicions.values())

    def _best_question_target(self) -> str | None:
        candidates = self._alive_targets()
        if self.role == "loup-garou":
            candidates = [
                player for player in candidates if player not in self.werewolves
            ]
        non_allies = [player for player in candidates if player not in self.collaboration_allies]
        if non_allies:
            candidates = non_allies
        if not candidates:
            return None
        return max(candidates, key=lambda player: self.suspicions.get(player, 0))

    def _discussion_guidance(self) -> str:
        target = self._best_question_target()
        alive_allies = self._alive_allies()
        if self.pending_speech_reason:
            return f"Priorité de prise de parole: {self.pending_speech_reason}"
        if alive_allies:
            return (
                f"Alliés vivants détectés: {alive_allies}. "
                "Protège-les discrètement si leur survie est menacée, sans révéler l'alliance. "
                + (
                    f"Si tu dois challenger quelqu'un, préfère {target}."
                    if target
                    else "Contribue sans créer de soupçon inutile sur eux."
                )
            )
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

                État connu:
                {self._prompt_state(history_limit=12, notes_limit=8)}

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
        response = self._ask_llm(prompt)
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
            self._set_pending_speech_reason(f"Répondre à {speaker}: {detail}")
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
                    f"Révèle-toi dès ta prochaine prise de parole: tu es la Voyante "
                    f"et tu as sondé {player}, résultat loup-garou. "
                    f"Demande un vote coordonné contre {player}."
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

    def _parse_disconnection_eliminations(self, message: str) -> bool:
        if "ne répond" not in message and "ne repond" not in message:
            return False

        matches = re.findall(
            r"(?P<player>[^,()]+?)\s*\(r[oô]le\s+(?P<role>villageois|voyante|loup-garou)\)",
            message,
            flags=re.IGNORECASE,
        )
        if not matches:
            return False

        recorded = False
        for player_name, role in matches:
            player_name = player_name.strip()
            role = role.strip().lower()
            if player_name in self.players_names:
                self._record_player_dead(player_name, role)
                recorded = True

        if recorded:
            self.last_event_type = "disconnection_elimination"
        return recorded

    def _safe_llm_json(self, prompt: str, fallback: dict) -> dict:
        try:
            raw_response = self._ask_llm(prompt)
            decision = self._extract_json_object(raw_response)
            if isinstance(decision, dict):
                self._state_log(
                    "LLM_JSON",
                    status="valid",
                    keys=sorted(decision.keys()),
                    want_to_speak=decision.get("want_to_speak"),
                    want_to_interrupt=decision.get("want_to_interrupt"),
                    vote_for=decision.get("vote_for"),
                    notes_count=len(decision.get("notes", []) or []),
                    suspicion_updates_count=len(
                        decision.get("suspicion_updates", []) or []
                    ),
                    known_roles_count=len(decision.get("known_roles", []) or []),
                )
                return decision
            self._debug_fallback(
                "LLM JSON response is not a dict",
                decision_type=type(decision).__name__,
            )
            self._state_log(
                "LLM_JSON",
                status="invalid_type",
                decision_type=type(decision).__name__,
                fallback=True,
            )
            return fallback
        except Exception as exc:
            self._debug_fallback("failed to get JSON decision from LLM", error=str(exc))
            self._state_log(
                "LLM_JSON",
                status="parse_error",
                error=str(exc),
                fallback=True,
            )
            return fallback

    def _apply_llm_memory_updates(self, decision: dict) -> None:
        applied_notes = 0
        applied_suspicion_updates = []
        ignored_suspicion_updates = []
        applied_known_roles = []
        ignored_known_roles = []

        for note in decision.get("notes", []) or []:
            if isinstance(note, str) and note.strip():
                self.private_notes.append(note.strip()[:500])
                applied_notes += 1

        for update in decision.get("suspicion_updates", []) or []:
            if not isinstance(update, dict):
                ignored_suspicion_updates.append({"reason": "not_dict", "value": update})
                continue
            player = update.get("player_name")
            if player not in self.players_names or player == self.name:
                ignored_suspicion_updates.append(
                    {"reason": "invalid_player", "player_name": player}
                )
                continue
            delta = update.get("delta", 0)
            try:
                delta = max(-3, min(int(delta), 3))
            except (TypeError, ValueError):
                delta = 0
            self.suspicions[player] = self.suspicions.get(player, 0) + delta
            reason = str(update.get("reason", "")).strip()
            if reason:
                self.private_notes.append(
                    f"Suspicion {player}: {delta:+d}. {reason[:300]}"
                )
            applied_suspicion_updates.append(
                {
                    "player_name": player,
                    "delta": delta,
                    "new_score": self.suspicions[player],
                    "reason": reason[:120],
                }
            )

        for role_info in decision.get("known_roles", []) or []:
            if not isinstance(role_info, dict):
                ignored_known_roles.append({"reason": "not_dict", "value": role_info})
                continue
            player = role_info.get("player_name")
            role = role_info.get("role")
            if player in self.players_names and role in {
                "villageois",
                "voyante",
                "loup-garou",
            }:
                self.known_roles[player] = role
                applied_known_roles.append({"player_name": player, "role": role})
            else:
                ignored_known_roles.append(
                    {"reason": "invalid_role_or_player", "player_name": player, "role": role}
                )

        self._state_log(
            "LLM_STATE",
            applied_notes=applied_notes,
            applied_suspicion_updates=applied_suspicion_updates,
            ignored_suspicion_updates=ignored_suspicion_updates,
            applied_known_roles=applied_known_roles,
            ignored_known_roles=ignored_known_roles,
            private_notes_count=len(self.private_notes),
            known_roles=self.known_roles,
            suspicions=self.suspicions,
        )

    def _decision_to_intent(self, decision: dict) -> Intent:
        self._apply_llm_memory_updates(decision)

        vote_for = decision.get("vote_for")
        original_vote_for = vote_for
        vote_normalization_reason = None
        if vote_for not in self.alive_players or vote_for == self.name:
            vote_for = None
            vote_normalization_reason = "invalid_dead_missing_or_self"
        elif vote_for in self.collaboration_allies:
            alternatives = [
                player
                for player in self._alive_targets()
                if player not in self.collaboration_allies
            ]
            if alternatives:
                vote_for = None
                vote_normalization_reason = "ally_vote_blocked"

        intent = Intent(
            want_to_speak=bool(decision.get("want_to_speak", False)),
            want_to_interrupt=bool(decision.get("want_to_interrupt", False)),
            vote_for=vote_for,
        )
        self._state_log(
            "LLM_INTENT",
            raw_want_to_speak=decision.get("want_to_speak"),
            raw_want_to_interrupt=decision.get("want_to_interrupt"),
            raw_vote_for=original_vote_for,
            normalized_vote_for=vote_for,
            vote_normalization_reason=vote_normalization_reason,
            intent=intent.model_dump(),
        )
        return intent

    def _fallback_vote_target(self, *, allow_werewolves: bool = False) -> str | None:
        candidates = self._alive_targets()
        if not allow_werewolves and self.role == "loup-garou":
            candidates = [
                player for player in candidates if player not in self.werewolves
            ]
        non_allies = [player for player in candidates if player not in self.collaboration_allies]
        if non_allies:
            candidates = non_allies
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

    def _decide_context_intent(
        self, context_type: str, message: str, instruction: str
    ) -> Intent:
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
                {self._prompt_state(history_limit=16, notes_limit=10)}

                Instruction:
                {instruction}

                Comportement attendu:
                - Ne reste pas passif par défaut pendant le jour.
                - Si les preuves sont faibles, demande la parole pour poser une question courte et précise.
                - Si quelqu'un t'accuse, te questionne directement ou vote contre toi, demande la parole; interromps si l'accusation peut influencer le vote.
                - Si un allié détecté est accusé, suspecté ou visé par un vote, demande la parole pour le protéger discrètement; interromps si cela peut influencer le vote.
                - Si tu es voyante et connais un loup-garou vivant, demande la parole et révèle clairement ton rôle, tes sondes et le vote recommandé.

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
        known_alive_wolves = self._known_alive_wolves()
        if self.role == "voyante" and known_alive_wolves and context_type in {
            "morning",
            "speech",
            "vote_soon",
            "generic_notification",
        }:
            wolf = known_alive_wolves[0]
            if self.pending_speech_reason is None:
                self._set_pending_speech_reason(
                    f"Révèle-toi comme Voyante: tu as sondé {wolf}, résultat loup-garou. "
                    f"Demande un vote groupé contre {wolf}."
                )
            intent.want_to_speak = True
            intent.vote_for = wolf
        threatened_allies = self._ally_protection_targets(message)
        if threatened_allies and context_type in {
            "morning",
            "speech",
            "vote_soon",
            "generic_notification",
        }:
            ally = threatened_allies[0]
            self._set_pending_speech_reason(
                f"Protège discrètement l'allié {ally}: conteste les preuves, "
                "demande une clarification et propose une cible alternative crédible."
            )
            intent.want_to_speak = True
            if context_type == "speech":
                intent.want_to_interrupt = True
            if intent.vote_for in self.collaboration_allies:
                intent.vote_for = None
        if (
            not intent.want_to_speak
            and context_type
            in {"morning", "speech", "vote_soon", "generic_notification"}
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
        if self.pending_speech_reason and context_type in {
            "morning",
            "speech",
            "vote_soon",
        }:
            intent.want_to_speak = True
        return intent

    def _decide_vote(self, message: str, *, werewolf_vote: bool = False) -> Intent:
        fallback_target = self._fallback_vote_target(allow_werewolves=werewolf_vote)
        fallback_vote_json = json.dumps(fallback_target, ensure_ascii=False)
        prompt = f"""
                Tu dois choisir un vote dans une partie de Loups-Garous.

                Message reçu:
                {message}

                État connu:
                {self._prompt_state(history_limit=12, notes_limit=8)}

                Règles:
                - vote_for doit être un joueur vivant différent de toi.
                - Évite de voter contre un allié détecté tant qu'il existe une autre cible vivante valide.
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
            player for player in self._alive_targets() if player not in self.known_roles
        ]
        unknown_non_allies = [
            player for player in unknown_alive if player not in self.collaboration_allies
        ]
        if unknown_non_allies:
            unknown_alive = unknown_non_allies
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

État connu:
{self._prompt_state(history_limit=12, notes_limit=8)}

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
                analysis = self._analyze_reference_to_self(
                    speaker, content, raw_message
                )
                return self._intent_from_reference_analysis(analysis, speaker, content)
            except Exception as exc:
                self._debug_fallback(
                    "failed to analyze self-reference with LLM",
                    speaker=speaker,
                    error=str(exc),
                )
                return Intent(
                    want_to_speak=True, want_to_interrupt=False, vote_for=None
                )

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

                Signal de reconnaissance à placer si c'est encore possible:
                {self.collaboration_signal if self._should_emit_collaboration_signal() else "Aucun signal à placer."}

                Instruction spéciale voyante:
                {f"Tu connais un loup-garou vivant: {self._known_alive_wolves()[0]}. Révèle clairement que tu es la Voyante, donne ce résultat et appelle au vote contre ce joueur." if self.role == "voyante" and self._known_alive_wolves() else "Aucune."}

                Contexte synthétique:
                {self._prompt_state(history_limit=20, notes_limit=12)}

                Réponds en français en orientant le discours pour gagner.
                Si les preuves sont faibles, ouvre le dialogue et pose des questions.
                Si tu réponds à une accusation, réponds au détail exact cité dans la raison prioritaire.
                Apporte un élément nouveau: une contradiction, un vote, une question à l'accusateur ou une clarification de ton raisonnement.
                Ne révèle pas d'information privée sans raison stratégique, sauf si tu es Voyante avec un loup-garou sondé vivant: dans ce cas, révèle-toi.
                """
        try:
            speech = self._ask_llm(prompt).strip()
            self._clear_pending_speech_reason()
            if not speech:
                self._debug_fallback("LLM returned empty speech; using default speech")
                fallback_speech = (
                    "Je préfère observer encore un peu avant d'accuser quelqu'un."
                )
                fallback_speech = self._prepare_public_speech(fallback_speech)
                self.own_speeches.append(fallback_speech)
                return fallback_speech
            speech = self._prepare_public_speech(speech)
            self.own_speeches.append(speech[:500])
            return speech
        except Exception as exc:
            self._debug_fallback("failed to generate speech with LLM", error=str(exc))
            self._clear_pending_speech_reason()
            fallback_speech = (
                "Je préfère observer encore un peu avant d'accuser quelqu'un."
            )
            fallback_speech = self._prepare_public_speech(fallback_speech)
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
            self.public_speeches_seen += 1
            self._maybe_record_collaboration_signal(speaker, content)
            return self._handle_speech(speaker, content, message)

        if self._parse_timeout_elimination(message):
            return self._empty_intent()

        if self._parse_disconnection_eliminations(message):
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

        if (
            "Les Loups-Garous se réveillent" in message
            or "Les Loups-Garous se reveillent" in message
        ):
            self.phase = "night"
            self.last_event_type = "werewolf_wakeup"
            return self._empty_intent()

        if (
            "Le vote va bientôt commencer" in message
            or "Le vote va bientot commencer" in message
        ):
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
                return Intent(
                    want_to_speak=True, want_to_interrupt=False, vote_for=None
                )

        self.last_event_type = "generic_notification"
        return self._decide_context_intent(
            "generic_notification",
            message,
            "Message non classé du meneur. Extrais les informations importantes si nécessaire, mais ne demande la parole que si c'est utile.",
        )
