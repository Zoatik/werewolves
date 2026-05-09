import sys
import random
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel
from collections import Counter
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import json
import yaml

from game_webapp import Logger, WebLogger, GameLogEntry



import logging
from logging.handlers import RotatingFileHandler

LOG = logging.getLogger(__name__)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
# Rotating file handler
rotating_handler = RotatingFileHandler('game_leader.log', maxBytes=5*1024*1024, backupCount=50)
#formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
formatter = logging.Formatter('%(levelname)s: %(message)s')
rotating_handler.setFormatter(formatter)
logger.addHandler(rotating_handler)
# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
# Suppress unnecessary logs from other libs
for lib in ['tornado', 'asyncio', 'httpx', 'httpcore', 'openai', 'urllib3', 'requests']:
    logging.getLogger(lib).setLevel(logging.WARNING)
LOG.info("Logging setup completed")




SEER: str = "voyante"
WEREWOLF: str = "loup-garou"
VILLAGER: str = "villageois"

# hard limits
MAX_INTERRUPTIONS: int = 2
MAX_ROUNDS: int = 20
API_TIMEOUT: int = 4 # seconds





class Player(BaseModel):
    name: str
    role: str = "unassigned"
    api_base_url: str
    api_endpoint: str = None
    is_alive: bool = True
    number_interruptions: int = 0
    spoke_at_rounds: List[int] = []

    def last_spoke_at_round(self) -> int:
        # if a player has not spoken yet, return a very old round to exagerate the time since last speech
        return self.spoke_at_rounds[-1] if self.spoke_at_rounds else -4

def name(player_or_list) -> str:
    if player_or_list is None:
        return "None"
    elif isinstance(player_or_list, Player):
        return player_or_list.name
    elif isinstance(player_or_list, list):
        return [name(p) for p in player_or_list]
    else:
        return str(player_or_list)


class Intent(BaseModel):
    player_name: str
    want_to_speak: bool
    want_to_interrupt: bool
    vote_for: Optional[str] = None


class ConsoleLogger(Logger):

    def __init__(self):
        self.msg_id = 0

    def log(self, entry: GameLogEntry) -> None:
        print('-' * 80)
        print(entry.to_string(self.msg_id))
        print('-' * 80)
        self.msg_id += 1


class ApiCalls:
    """Handles all API communications with players."""
    
    @staticmethod
    def post_new_game(player: Player, players_names: List[str], werewolves_cnt:int, werewolves: List[Optional[str]]) -> int:
        """
        Send a POST request to /new_game endpoint.
        
        Args:
            player: The player
            
        Returns:
            bool: True if the player is connected, False otherwise
        """
        try:
            LOG.debug(f"--> new_game for {player.name} ({player.role})")
            response = requests.post(
                f"{player.api_base_url}/new_game", 
                json={
                    "role": player.role, 
                    "player_name": player.name, 
                    "players_names": players_names,
                    "werewolves_count" : werewolves_cnt,
                    "werewolves": werewolves
                }, 
                timeout=API_TIMEOUT
            )
            LOG.debug(f"<-- new_game response from {player.name}: {str(response.text).strip()}")
            response.raise_for_status()
            # get the player_id
            player_id = response.json()["player_id"]
            return player_id
        except Exception as e:
            LOG.warning(f"Error in post_new_game for {player.name}: {str(e)}")
            return -1
    
    @staticmethod
    def post_speech(player: Player) -> Optional[str]:
        """
        Send a POST request to /speech endpoint.
        
        Args:
            player: The player
        """
        try:
            LOG.debug(f"--> speech for player {player.name}")
            response = requests.post(f"{player.api_endpoint}/speak", timeout=API_TIMEOUT)
            LOG.debug(f"<-- speech response from {player.name}: {str(response.text).strip()}")
            response.raise_for_status()
            j = response.json()
            # check if the response is valid
            assert type(j) == dict, f"Response is not a dictionary: {j}"
            assert "speech" in j, f"speech is not in the response: {j}"
            speech = j["speech"]
            assert type(speech) == str, f"Speech is not a string: {speech}"
            if len(speech) == 0:
                LOG.warning(f"Speech is empty for {player.name}")
            return speech
        except Exception as e:
            LOG.warning(f"Error in post_speech for {player.name}: {str(e)}")
            return None
    
    @staticmethod
    def post_notify(player: Player, message: str) -> Optional[Intent]:
        """
        Send a POST request to /notify endpoint.
        
        Args:
            player: The player to notify
            message: The message to send
            
        Returns:
            Dict: The intent response from the player
        """
        try:
            LOG.debug(f"--> notify for {player.name}: {message}")
            response = requests.post(f"{player.api_endpoint}/notify", json={"message": message}, timeout=API_TIMEOUT)
            LOG.debug(f"<-- notify response from {player.name}: {str(response.text).strip()}")
            response.raise_for_status()
            j = response.json()
            # check if the response is valid
            assert type(j) == dict, f"Response is not a dictionary: {j}"
            assert "want_to_speak" in j, f"want_to_speak is not in the response: {j}"
            assert "want_to_interrupt" in j, f"want_to_interrupt is not in the response: {j}"
            assert "vote_for" in j, f"vote_for is not in the response: {j}"
            return Intent(player_name=player.name, want_to_speak=j["want_to_speak"], want_to_interrupt=j["want_to_interrupt"], vote_for=j["vote_for"])
        except requests.exceptions.Timeout:
            LOG.warning(f"Timeout in post_notify for player {player.name} after {API_TIMEOUT}s")
            return None
        except Exception as e:
            LOG.warning(f"Error in post_notify for player {player.name}: {e}")
            return None


class GameLeader:
    
    def __init__(self, players: List[Player], logger: Logger = ConsoleLogger()):
        """
        Initialize a new game.
        
        Args:
            player_ids: List of player identifiers
        """
        # list of players. players are not removed from this list, but set to is_alive = False
        self.players: List[Player] = players
        self.__game_log: List[GameLogEntry] = []  # don't call this directly, use log() instead
        self.api: ApiCalls = ApiCalls()
        self.logger: Logger = logger
        self.round: int = 0  # increased everytime a player speaks (not the leader)


    def log(self, entry: GameLogEntry) -> None:
        self.logger.log(entry)
        self.__game_log.append(entry)


    def get_player_by_name(self, name: str) -> Optional[Player]:
        return next((player for player in self.players if player.name == name), None)


    def players_actives(self, exclude_player: Optional[str] = None) -> List[Player]:
        """
        Get a list of all active players.
        """
        return [p for p in self.players if p.is_alive and p.name != exclude_player]


    def last_player_to_speak(self) -> Optional[str]:
        if len(self.__game_log) > 0:
            return self.__game_log[-1].actor_name
        else:
            return None


    def start_game(self) -> bool:
        """
        Start a new game by assigning roles and notifying players.
        
        Returns:
            bool: True if game started successfully, False otherwise
        """
        # Create role distribution
        werewolves = self._assign_roles()

        players_names = [player.name for player in self.players]
        
        # Initialize player states
        success = True
        for player in self.players:
            if player.role == WEREWOLF:  # only show werewolves to each other
                player_id = self.api.post_new_game(player, players_names, len(werewolves), werewolves)
            else:
                player_id = self.api.post_new_game(player, players_names, len(werewolves), [])
            if player_id < 0:
                success = False
                self.log(GameLogEntry(
                    type="ERROR",
                    content=f"Failed to start game for player {player.name}",
                    context_data={"werewolves": werewolves, "players_names": players_names}
                ))
                break
            else:
                # update player's api
                player.api_endpoint = f"{player.api_base_url}{player_id}/"
        
        return success


    def _assign_roles(self) -> List[str]:
        """
        Assign roles to players randomly.

        Returns:
            A list of werewolves' names
        """
        num_players = len(self.players)
        num_werewolves = 2 if num_players < 12 else 3  # according to rules
        has_seer = num_players >= 5  # Only add seer if enough players
        
        # Create list of roles
        all_roles = [WEREWOLF] * num_werewolves
        if has_seer:
            all_roles.append(SEER)
        
        # Fill remaining slots with villagers
        num_villagers = num_players - len(all_roles)
        all_roles.extend([VILLAGER] * num_villagers)

        werewolves = []
        
        # Shuffle roles and assign to players
        random.shuffle(all_roles)
        for player, role in zip(self.players, all_roles):
            player.role = role
            if role == WEREWOLF:
                werewolves.append(player.name)
            self.log(GameLogEntry(
                type="ROLE_ASSIGNMENT",
                target_name=player.name,
                content=f"Le/a joueur.euse {player.name} a été assigné le rôle de {role}",
                context_data={"role": role}
            ))
        return werewolves


    def check_if_game_is_over(self) -> Optional[str]:
        """
        Check if the game is over by checking win conditions.
        
        Returns:
            Optional[str]: "werewolves" if werewolves win, "villagers" if villagers win, 
                          None if game continues
        """
        
        alive_werewolves = 0
        alive_villagers = 0
        
        # count alive players by role
        for player in self.players:
            if player.is_alive:
                if player.role == WEREWOLF:
                    alive_werewolves += 1
                else:
                    alive_villagers += 1
        
        # check win conditions
        if alive_werewolves == 0:
            return VILLAGER
        elif alive_villagers == 0:
            return WEREWOLF
        else:  # game continues
            return None


    def eliminate_player(self, player: Player, phase:str) -> None:
        """
        Remove a player from the game.
        
        Args:
            player: The player to eliminate
            phase: Whether night or day
        """
        assert player in self.players and player.is_alive, f"{player.name} is not in the game or is not alive"
        player.is_alive = False
        

    def announce_to_one(self, player: Player, msg: str) -> Optional[Intent]:
        """ 
        Announce a message to a single player.
        """
        return self.api.post_notify(player, msg)


    def print_game_summary(self, verbose: bool = False) -> None:
        # print a summary of the game so far
        LOG.info("*" * 80)
        LOG.info(f"Game summary:")
        LOG.info(f"Initial werewolves: {[player.name for player in self.players if player.role == WEREWOLF]}")
        LOG.info(f"Initial seer: {name(next((player for player in self.players if player.role == SEER), None))}")
        
        
        if verbose:
            # litst all messages
            for log_entry in self.__game_log:
                actor_name = f"[{log_entry.actor_name}]" if log_entry.actor_name != "GameLeader" else ""
                LOG.info(f"{log_entry.type}: {actor_name} {log_entry.content}")
        else:
            # list who has been eliminated since last night
            for log_entry in self.__game_log:
                if log_entry.type == "VOTE_RESULT":
                    LOG.info(f"Villageois ont éliminé   {log_entry.context_data.get('victim', "personne")} (rôle {log_entry.context_data.get('victim_role', "aucun")}).")
                if log_entry.type == "MORNING_VICTIM":
                    LOG.info(f"Loups-garous ont éliminé {log_entry.context_data.get('victim', "personne")} (rôle {log_entry.context_data.get('victim_role', "aucun")}).")
        
        LOG.info(f"Active players: {name(self.players_actives())}")
        LOG.info(f"Active werewolves: {[player.name for player in self.players_actives() if player.role == WEREWOLF]}")

        LOG.info("*" * 80)


    def announce_to_all(self, msg: str, exclude_player: Optional[str] = None) -> List[Optional[Intent]]:
        """
        Announce a message to all active players asynchronously using ThreadPoolExecutor.
        """
        active_players = [player for player in self.players_actives() if player.name != exclude_player]
        results = []
        
        if not active_players:
            return results
        
        with ThreadPoolExecutor(max_workers=len(active_players)) as executor:
            # Submit all tasks
            future_to_player = {
                executor.submit(self.api.post_notify, player, msg): player 
                for player in active_players
            }
            
            # Wait for completion - each individual API call has its own timeout (API_TIMEOUT)
            try:
                for future in as_completed(future_to_player, timeout=API_TIMEOUT):
                    player = future_to_player[future]
                    try:
                        result = future.result()  # This won't block since future is already done
                        if result is not None:
                            results.append(result)
                    except Exception as e:
                        LOG.info(f"Error getting result from {player.name}: {e}")
                        
            except TimeoutError:
                # This should rarely happen since individual calls have their own timeouts
                LOG.warning(f"Overall timeout waiting for responses in announce_to_all after {API_TIMEOUT}s")
                
            # Handle any remaining futures that didn't complete
            for future, player in future_to_player.items():
                if not future.done():
                    LOG.warning(f"Request to {player.name} did not complete, cancelling")
                    future.cancel()
        
        return results


    def discussion_segment(self, speaker:Player) -> List[Intent]:
        """
        Conduct a discussion segment by choosing the next speaker, letting them speak and announcing their speech.

        Args:
            intents: The intents of the players
            
        Returns:
            a tuple with the intents of the players after the discussion segment and a boolean indicating if the discussion should continue
        """
        assert speaker in self.players_actives(), f"{speaker.name} is not in the game or is not alive"

        # update round and speaker's spoke_at_rounds
        self.round += 1
        speaker.spoke_at_rounds.append(self.round)

        # let the player speak
        speech = self.api.post_speech(speaker)
        if speech is None:
            msg = f"{speaker.name} avec le rôle {speaker.role} n'a pas répondu à temps. Il/elle a été éliminé de la partie."    
            self.log(GameLogEntry(
                type="ELIMINATE_PLAYER",
                actor_name=speaker.name,
                content=msg,
                context_data={"reason": "no_speech_response"}
            ))
            return self.announce_to_all(msg, exclude_player=speaker.name)
        else:
            # log the speech
            self.log(GameLogEntry(
                type="SPEECH",
                actor_name=speaker.name,
                content=speech
            ))            
            return self.announce_to_all(f"{speaker.name} a dit: {speech}", exclude_player=speaker.name)


    def choose_next_speaker(self, intents: List[Intent], discussion_round: int) -> Optional[Player]:
        """
        LLM chooses the next speaker from the list of intents, based on game history, player statistics, and current intents.
        Returns None if we should stop debating for now.
        """

        valid_interrupts: List[str] = [intent.player_name 
                                       for intent in intents 
                                       if intent.want_to_interrupt 
                                       and intent.player_name != self.last_player_to_speak()
                                       and self.get_player_by_name(intent.player_name) in self.players_actives()
                                       and self.get_player_by_name(intent.player_name).number_interruptions < MAX_INTERRUPTIONS]
        LOG.debug(f"valid_interrupts: {valid_interrupts}")
        valid_want_to_speak: List[str] = [intent.player_name 
                                     for intent in intents 
                                     if intent.want_to_speak 
                                     and intent.player_name != self.last_player_to_speak()
                                     and self.get_player_by_name(intent.player_name) in self.players_actives()
                                     and self.get_player_by_name(intent.player_name).is_alive]
        LOG.debug(f"valid_want_to_speak: {valid_want_to_speak}")
        # strict priority to interrupters. choose at random
        if len(valid_interrupts) > 0:
            interruptor: Player = self.get_player_by_name(random.choice(valid_interrupts))
            interruptor.number_interruptions += 1
            LOG.debug(f"INTERRUPTOR: {name(interruptor)}")
            return interruptor
        
        # hard limits if too many rounds
        if discussion_round > MAX_ROUNDS:
            LOG.debug(f"discussion_round > MAX_ROUNDS: {discussion_round}")
            return None
        
        # first, add 5 * players if  want_to_speak
        candidates: List[Player] = [self.get_player_by_name(player_name) for player_name in valid_want_to_speak] * 5
        LOG.debug(f"want_to_speak candidates: {name(candidates)}")
        
        # then add silent players. DISABLED for now
        # for player in self.players_actives(self.last_player_to_speak()):
        #     haven_t_spoken_since = self.round - player.last_spoke_at_round()
        #     # add multiple times if haven't spoken for a long time
        #     factor = min(30, math.floor(math.exp(0.15 * haven_t_spoken_since)) - 1)
        #     LOG.debug(f"silent player: {player.name} hasn't spoken for {haven_t_spoken_since} rounds, factor: {factor}")
        #     candidates.extend([player] * factor)

        # then remove players that have spoken too much
        total_speeches = sum(len(player.spoke_at_rounds) for player in self.players_actives()) + 1
        for player in self.players_actives():
            speech_ratio = len(player.spoke_at_rounds) / total_speeches
            factor = int(speech_ratio * 3)
            LOG.debug(f"chatty player: {player.name} has spoken {len(player.spoke_at_rounds)} times out of {total_speeches}, speech_ratio: {speech_ratio}, factor: {factor}")
            for _ in range(factor):
                if player in candidates:
                    candidates.remove(player)

        # add multiple None to candidate list. pick a None --> stop this discussion
        # smoothly increases from near 0 to 50 between x = 10 and x = 20 using a scaled sigmoid curve.
        factor = int(50 / (1 + math.exp(-1.5 * (discussion_round - 15))))
        candidates.extend([None] *  factor)
        LOG.debug(f"number of None added: {factor}")
        LOG.debug(f"candidates: {name(candidates)}")

        if len(candidates) == 0:
            LOG.debug(f"no candidates, returning None")
            return None
        
        # choose at random. 
        chosen = random.choice(candidates)
        LOG.debug(f"chosen: {name(chosen)}")
        if chosen is not None:
            if chosen.name in valid_interrupts:
                chosen.number_interruptions += 1
        return chosen


    def day_time(self, victim: Optional[Player]) -> None:
    
        rumors = self.generate_rumors()
        
        # annonce de la victime de la nuit passée
        if victim is None:
            announcement = f"""C'est le matin, le village se réveille, tout le monde se réveille et ouvre les yeux... Cette nuit, personne n'a été mangé.e par les loups-garous. {rumors}"""
            self.log(GameLogEntry(
                type="MORNING_VICTIM",
                content=announcement,
                context_data={"victim": None, "victim_role": None, "rumors": rumors}
            ))
        else:
            announcement = f"""C'est le matin, le village se réveille, tout le monde se réveille et ouvre les yeux... Cette nuit, {victim.name} a été mangé.e par les loups-garous. Son rôle était {victim.role}. {rumors}"""
            self.log(GameLogEntry(
                type="MORNING_VICTIM",
                content=announcement,
                context_data={"victim": victim.name, "victim_role": victim.role, "rumors": rumors}
            ))
        intents = self.announce_to_all(announcement)

        self.print_game_summary()

        # débat
        discussion_round: int = 0
        keep_debating: bool = True
        while keep_debating:
            LOG.debug(f"discussion_round: {discussion_round}")
            speaker = self.choose_next_speaker(intents, discussion_round)
            LOG.debug(f"speaker: {name(speaker)}")
            if speaker is None:
                keep_debating=False
            else:
                intents = self.discussion_segment(speaker)
                discussion_round += 1

        # bientôt vote
        announcement = "Le vote va bientôt commencer. Chaque joueur peut encore prendre la parole s'il le souhaite."
        self.log(GameLogEntry(
            type="VOTE_SOON",
            content=announcement
        ))
        intents = self.announce_to_all(announcement)

        # all players that want_to_speak can speak at max once
        valid_want_to_speak: List[str] = [intent.player_name 
            for intent in intents 
            if intent.want_to_speak 
            and intent.player_name != self.last_player_to_speak()
            and intent.player_name in [p.name for p in self.players_actives()]]
        LOG.debug(f"valid_want_to_speak: {valid_want_to_speak}")

        while len(valid_want_to_speak) > 0:
            speaker: Player = self.get_player_by_name(random.choice(valid_want_to_speak))
            LOG.debug(f"speaker: {name(speaker)}")
            valid_want_to_speak.remove(speaker.name)
            intents = self.discussion_segment(speaker)

        # vote, calcul victime, annonce, élimination
        announcement = "Il est temps de voter. Donnez maintenant votre intention de vote."
        self.log(GameLogEntry(
            type="VOTE_NOW",
            content=announcement
        ))
        intents = self.announce_to_all(announcement)
        valid_votes = self.validate_votes(intents)
        LOG.debug(f"valid_votes: {valid_votes}")
        victim = self.compute_victim(valid_votes)
        LOG.debug(f"victim: {name(victim)}")
        msg_voted_for: str = ", ".join([f"{vote[0]} a voté pour {vote[1]}" for vote in valid_votes])
        if victim is None:
            announcement = f"{msg_voted_for}. Il n'y a pas de victime."
            self.log(GameLogEntry(
                type="VOTE_RESULT",
                content=announcement,
                context_data={"victim": None, "victim_role": None, "votes": valid_votes}
            ))
        else:
            announcement = f"{msg_voted_for}. Ainsi, {victim.name} est mort(e) et son rôle était {victim.role}."   
            self.log(GameLogEntry(
                type="VOTE_RESULT",
                content=announcement,
                context_data={"victim": victim.name, "victim_role": victim.role, "votes": valid_votes}
            ))
            self.eliminate_player(victim, "day")
        self.announce_to_all(announcement)

        
    def validate_votes(self, votes: List[Intent]) -> List[Tuple[str, str]]:
        """
        Check if the vote is for a valid player.

        Args:
            votes: The list of intents to validate

        Returns:
            The list of validated votes, each tuple is (player_name, vote_for)
        """
        valid_votes: List[Tuple[str, str]] = []
        for intent in votes:
            player_to_vote_for = self.get_player_by_name(intent.vote_for)
            if player_to_vote_for is None:
                LOG.info(f"Le joueur {intent.vote_for} n'est pas dans la partie. {intent.player_name} ne peut pas voter pour lui.")
            player_to_vote_for_is_alive = intent.vote_for in [p.name for p in self.players_actives()]
            if not player_to_vote_for_is_alive:
                LOG.info(f"Le joueur {intent.vote_for} n'est plus dans la partie. {intent.player_name} ne peut pas voter pour lui.")
            else:
                valid_votes.append((intent.player_name, intent.vote_for))
        return valid_votes


    def compute_victim(self, valid_votes: List[Tuple[str, str]]) -> Optional[Player]:
        """
        Compute the victim from the list of valid votes. Choose the player with the most votes.
        If there is a tie, choose a random player from those with the highest number of votes.
        """
        votes_for = Counter([vote[1] for vote in valid_votes])
        
        if len(votes_for) == 0:
            return None  # no votes, no victim
        # If there is only one player voted for, return it
        elif len(votes_for) == 1:  # pick the only one
            return self.get_player_by_name(votes_for.most_common(1)[0][0])
        
        # Get the highest vote count
        most_common = votes_for.most_common()
        highest_count = most_common[0][1]
        
        # Find all players with the highest count (could be one or more in case of tie)
        top_voted = [player for player, count in most_common if count == highest_count]
        
        # If there's a tie, return a random player from those with the highest votes
        if len(top_voted) > 1:
            return self.get_player_by_name(random.choice(top_voted))
        else:
            return self.get_player_by_name(top_voted[0])


    def generate_rumors(self) -> str:
        """
        Generate rumors about the night.
        """
        return "" # LATER generate rumors


    def night_time(self) -> Optional[Player]:

        msg = "C'est la nuit, tout le village s’endort, les joueurs ferment les yeux."
        self.log(GameLogEntry(
            type="NIGHT_START",
            content=msg
        ))
        self.announce_to_all(msg)

        # voyante; on lui demande de sonder un joueur; on lui annonce le rôle de ce joueur.
        seer: Optional[Player] = next((player for player in self.players_actives() if player.role == SEER), None)
        LOG.debug(f"seer: {name(seer)}")
        if seer is not None:
            announcement = "La Voyante se réveille, et désigne un joueur dont elle veut sonder la véritable personnalité !"
            self.log(GameLogEntry(
                type="VOYANTE_WAKEUP",
                content=announcement
            ))
            intents = self.announce_to_all(announcement)
            player_to_check:str = [intent.vote_for for intent in intents if intent.player_name == seer.name][0]
            LOG.debug(f"Seer asked to check player: {player_to_check}")
            if player_to_check in [p.name for p in self.players_actives()]:
                player_to_check_role = self.get_player_by_name(player_to_check).role
                announcement_to_voyante = f"Le rôle de {player_to_check} est {player_to_check_role}"
                # special case where we just notify a single player
                self.announce_to_one(seer, announcement_to_voyante)
                self.log(GameLogEntry(
                    type="VOYANTE_ANNOUNCEMENT",
                    content=announcement_to_voyante,
                    target_name=seer.name,
                    public=False,
                    context_data={"player_to_check": player_to_check, "player_to_check_role": player_to_check_role}
                ))
            else:
                LOG.info(f"Le joueur {player_to_check} n'est pas dans la partie. La Voyante ne peut pas sonder.")

        # loup garous votent
        loup_garous = [player for player in self.players_actives() if player.role == WEREWOLF]
        LOG.debug(f"loup_garous: {name(loup_garous)}")
        msg = f"Les Loups-Garous se réveillent, se reconnaissent et désignent une nouvelle victime !!!"
        self.log(GameLogEntry(
            type="WEREWOLF_VOTE_ANNOUNCEMENT",
            content=msg,
            context_data={"loup_garous": [name(loupgarou) for loupgarou in loup_garous]}
        ))
        last_vote = ""
        victim = None
        rounds = 0
        while victim is None and rounds < 4:  # LATER always use 4?
            msg = f"Les Loups-Garous votent pour une nouvelle victime !!! {last_vote}"
            votes = []
            for loupgaroup in loup_garous: 
                intents = self.announce_to_one(loupgaroup, msg)
                if intents is not None:  # don't consider invalid responses
                    votes.append(intents)
            # validate_votes returns a list of tuples (player_name, vote_for). we only care for the vote_for
            valid_votes = [vote[1] for vote in self.validate_votes(votes)]
            LOG.debug(f"valid_votes: {valid_votes}, rounds: {rounds}")
            # if all votes validated and all loup garous voted for the same player, we have a victim
            LOG.debug(f"valid_votes from loup garous: {valid_votes}")
            if len(valid_votes) == len(loup_garous) and len(set(valid_votes)) == 1:
                victim = self.get_player_by_name(valid_votes[0])
                LOG.debug(f"victim: {name(victim)}")
                # LATER: should we log the vote? i think it's logged when village awakes...
                self.eliminate_player(victim, "night")
                LOG.debug(f"victim eliminated: {name(victim)}")
            else:
                last_vote = f"Dernier vote: " + ", ".join([f"{i.player_name} a voté pour {i.vote_for}" for i in votes])
                LOG.debug(f"no consensus found, rounds: {rounds}")
            rounds += 1
                
        return victim
    

if __name__ == "__main__":

    # Load player configuration from YAML file
    with open("players_config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    players = [
        Player(name=p["name"], api_base_url=p["api_base_url"]) for p in config["players"]
    ]
    
    # weblogger if w flag
    web_mode = '-w' in sys.argv or 'w' in sys.argv
    if web_mode:
        logger = WebLogger()
    else:
        logger = ConsoleLogger()

    # Create game and start it
    game = GameLeader(players, logger)
    can_start = game.start_game()
    if not can_start:
        LOG.error("ERROR: Failed to start game")
        exit(1)
    else:
        game.print_game_summary()
        while True:
            # NIGHT TIME
            victim = game.night_time()
            if game.check_if_game_is_over() is not None:
                break
            
            # DAY TIME
            game.day_time(victim)
            if game.check_if_game_is_over() is not None:
                break
        game.print_game_summary(verbose=True)
        game.log(GameLogEntry(
            type="GAME_OVER",
            content=f"Game over! {game.check_if_game_is_over()} win!"
        ))

        # save the game logs to a file
        #with open("game_logs2.json", "w", encoding="utf-8") as f:
        #    json.dump([msg.model_dump_json() for msg in game.logger.msgs], f, indent=4)
