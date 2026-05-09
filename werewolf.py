from pydantic import BaseModel
from abc import ABC, abstractmethod
from typing import List
import random
import re


class Intent(BaseModel):
    want_to_speak:bool = False
    want_to_interrupt:bool = False
    vote_for:str = None


class WerewolfPlayerInterface(ABC):

    @classmethod
    def create(cls, name: str, role: str, players_names: List[str], werewolves_count: int, werewolves: List[str]) -> 'WerewolfPlayerInterface':
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

    def __init__(self, name: str, role: str, players_names: List[str], werewolves_count: int, werewolves: List[str]) -> None:
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
        print(f"WerewolfPlayer {self.name} created")        
        # TODO add your code here, if necessary


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
        # TODO implement me
        return "C'est même pas vrai!"
    

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
        print(f"{self.name} received message: {message}")
        # TODO implement me
        return Intent(want_to_speak=False, want_to_interrupt=False, vote_for="")
