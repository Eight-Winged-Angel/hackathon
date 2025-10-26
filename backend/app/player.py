from __future__ import annotations

import random
import uuid
from typing import Any, List, Optional, TYPE_CHECKING
from backend.app.utils import text_completion
# Only import Game for type checking to avoid circular imports at runtime
if TYPE_CHECKING:
    from backend.app.game import Game

# Lightweight local stub for LLM calls used by AIAgent.
def chat_completion(messages: List[dict], max_tokens: int = 80, temperature: float = 0.7, model: Optional[str] = None) -> str:
    # Deterministic short response based on last content; avoids network dependency.
    # last = next((m.get("content", "") for m in reversed(messages) if isinstance(m, dict)), "")
    # words = [w for w in (last or "").split()]
    # return (" ".join(words[: min(20, len(words))]) or "thinking...").strip()
    print('RUNNING CHAT COMPLETION', messages)
    res = text_completion(messages)
    print('RESULT OF CHAT COMPLETION', res)
    return res
role_map = {}
import json

class AIAgent:
    """Lightweight agent bound to an AIPlayer.

    - No duplicated role or teammate state; uses the owning AIPlayer's fields
      (e.g., owner.role, owner.known_allies).
    - Does not keep an internal history; uses game.events as context when provided.
    """

    def __init__(self, owner: "AIPlayer", *, persona: Optional[str] = None):
        self.owner = owner
        self.persona = persona or owner.name
        # Memory/history removed; keep a small scratchpad if needed
        self.knowledge: List[str] = []
        self.private_info = []

    def system_prompt(self, game) -> str:
        base = f"You are {self.persona}, playing the social deduction game Werewolf. \n"
        base += (
            "Rules:\n"
            "- The game alternates between Day (discussion and voting) and Night (actions).\n"
            "- Werewolves know each other and can eliminate one player each night.\n"
            "- The Detective can investigate one player each night.\n"
            "- During the Day, all players discuss and vote to eliminate one suspected werewolf.\n"
            "- The game ends when all werewolves are eliminated or the werewolves equal the number of Town members. \n"
        )
        base += (f"- In the current game, there are {len(game.players)} players and {len(game.werewolf_ids)} werewolves.\n\n")
        base += (
            "Here are some guidelines for how to think: \n"
            " You are playing a virtual game. Do not include references to physical space (e.g. who was nearest to X?), focus only on game actions and speech. \n"
            " Think and speak like a human player. \n"
            " Be strategic, persuasive, and consistent with your assigned role. \n"
            " Never reveal your role unless strategically beneficial.\n"
            " Pay attention to the logical consistency of other player's transcripts. \n"
            " Pay attention to the emotional information of other player's transcripts and use it as an argument when debating. \n"
            " Pay attention to the voting events in the past event log and ensure consistent logical reasoning. \n"
        )
        return base

    def get_mapped_role(self):
        role = getattr(self.owner, "role", None)
        return role_map.get(role, role)

    def role_instructions(self) -> str:
        # Map game role to instruction flavor; avoid duplicating state here
        mapped = self.get_mapped_role()
        if mapped == "werewolf":
            return (
                "You are a Werewolf. Your goal is to eliminate all villagers without being discovered."
                " Act innocent and persuasive during the day."
                " Contribute to discussion during the day"
                "subtly shift suspicion toward active players or those who survive many nights "
            )
        elif mapped == "villager":
            return (
                "You are a Villager. You have no special powers. Your goal is to find and vote out all Werewolves."
                " During the day, discuss suspicions and vote wisely."
                "Share reasoning, but avoid blindly following others. "
                " Defend youself if other players attacked you before, also defend other players if you think they are your teammate"
            )
        elif mapped == "doctor":
            return (
                "You are the Doctor. Each night, you may choose one player to save from elimination."
                " Try to deduce who the Werewolves might target."
            )
        elif mapped == "detective":
            return (
                "You are the Detective. Each night, you can investigate one player to learn if they are a Werewolf."
                " Use your findings discreetly to influence votes."
                " Investigate players who seem manipulative or too quiet."
                " Use your findings discreetly to influence votes."
                " Once confident, carefully reveal findings (or hint subtly) to steer the village"
            )
        else:
            return "You are a Villager. Act accordingly."
    
    def _event_log_excerpt(self, game: "Game") -> str:
        try:
            # Use most recent events as context
            lines = [e.get("text", "") for e in (game.events or [])]
            return "\n".join(lines)
        except Exception:
            return ""

    def get_role_specific_info(self, game):
        mapped = self.get_mapped_role()
        if mapped == 'mafia':
            return {'allies': [p.name for p in game.alive_werewolves()]}
        elif mapped == 'detective':
            print('DETECTIVE INFO')
            return {'past_detections': self.owner.private_notes}
        return dict()
        
    def get_generic_info(self, game):
        transcript_info = {'name', 'transcript', 'emotion', 'round_number'}
        generic = {'system_prompt': self.system_prompt(game),
                'role_prompt': self.role_instructions(),
                'alive_player_list': [p.name for p in game.alive_players()],
                'events': self._event_log_excerpt(game),
                'transcript': game.get_text_transcript(),
                'current_round_number': game.round_number}
        return generic

    def get_info(self, game):
        info = self.get_generic_info(game)
        role_info = self.get_role_specific_info(game)
        
        role_messages = []
        if role_info.keys():
            role_messages = [{
                "role": "system", "content": "This is your role specific information"
            }, {"role": "system", "content": json.dumps(role_info)}]
        
        messages = [
            {"role": "system", "content": info['system_prompt']},
            {"role": "system", "content": info['role_prompt']},
            {"role": "system", "content": f"\nThe current round number is {info['current_round_number']}"},
            {"role": "system", "content": f"\nThis is the global event log:"},
            {"role": "system", "content": info['events']},
            {"role": "system", "content": f"\nThis is the list of alive players"},
            {"role": "system", "content": ', '.join(info['alive_player_list'])},
            {"role": "system", "content": f"\nThis is the current transcript. Each line contains information about the speaker, what they said, and the emotion they said it in. It will be in the format: `SPEAKER`: `CONTENT` (Emotion: `EMOTION`). Round transitions will also be announced in the transcript. The transcript will begin with the line TRANSCRIPT START and end with the line TRANSCRIPT END."},
            {"role": "system", "content": info['transcript']}] + role_messages

        #### Merge test
        merge_messages = '\n'.join([m['content'] for m in messages])
        messages = [{'role': 'system', 'content': merge_messages}]
        
        print('GETTING INFO for', self.persona)
        print(merge_messages)

        return messages
    
    def choice_action(self, game, prompt, choices, max_tokens=20, temperature=0.2):
        try:
            print('CHOICE ACTION', prompt, choices)
            print('GAME', game)
            info_messages = self.get_info(game)
            print('INFO MESSAGES', info_messages)
            messages = info_messages + [{"role": "user", "content": (
                    f"{prompt}\n"
                    f"Output a choice from the list: {', '.join(choices)}. ONLY output your choice."
                )}
            ]
        except Exception as e:
            print(e)
        try:
            res = chat_completion(messages, max_tokens=max_tokens, temperature=temperature).strip()
            print('RES', res)
            return res
        except Exception as e:
            print(e)
            return ""

    def vote(self, alive_players: List[str], game) -> str:
        choice_dict = {p.name: p for p in game.alive_players()}
        return choice_dict[self.choice_action(game, 'Decide who you will vote to eliminate today.', list(choice_dict.keys()))].id

    def night_action(self, game: Optional["Game"], alive_players: List[str]) -> Optional[str]:
        # """Perform role-specific night action (if applicable)."""
        choice_dict = {p.name: p for p in game.alive_players()}
        return choice_dict[self.choice_action(game, 'Decide who you will kill tonight.', list(choice_dict.keys()))].id
    
    def detect(self, game: Optional["Game"], alive_players: List[str]) -> Optional[str]:
        """Perform role-specific night action (if applicable)."""
        choice_dict = {p.name: p for p in game.alive_players()}
        return choice_dict[self.choice_action(game, 'Decide who you will detect tonight.', list(choice_dict.keys()))].id
    
    def detect_result(self, player_num: str, role: str) -> None:
        self.private_info.append(f"Player{player_num} is {role}")

class Player:
    def __init__(self, name: str, is_host: bool, *, is_ai: bool = False) -> None:
        self.id = str(uuid.uuid4())
        self.name = name
        self.is_host = is_host
        self.is_ai = is_ai
        self.role: Optional[str] = None
        self.is_alive: bool = True
        self.private_notes: List[str] = []
        self.known_allies: List[str] = []

class HumanPlayer(Player):
    def __init__(self, name: str, *, is_host: bool = False) -> None:
        super().__init__(name, is_host=is_host, is_ai=False)

class AIPlayer(Player):
    def __init__(self, name: str, *, is_host: bool = False, actor=None) -> None:
        super().__init__(name, is_host=is_host, is_ai=True)
        # Attach agent without duplicating role/teammates
        self.agent = AIAgent(owner=self, persona=name)
        self.actor = actor
        print('ACTOR IS', self.actor)

    def on_role_assigned(self, game: "Game") -> None:
        # Keep known_allies already set by game; agent reads from owner fields.
        return

    def choose_wolf_target(self, game: "Game") -> Optional[str]:
        if self.role != "werewolf" or not self.is_alive:
            return None
        candidates = [p.id for p in game.alive_villagers() if p.id != self.id]
        if not candidates:
            return None
        try:
            pick = self.agent.night_action(game, candidates)
            if pick in candidates:
                return pick
        except Exception:
            pass
        return random.choice(candidates) if candidates else None

    def choose_detective_target(self, game: "Game") -> Optional[str]:
        if getattr(game, "detective_id", None) != self.id or not self.is_alive:
            return None
        suspects = [p.id for p in game.alive_players() if p.id != self.id]
    
        if not suspects:
            return None
        try:
            pick = self.agent.detect(game, suspects)
            if pick in suspects:
                return pick
        except Exception:
            pass
        return random.choice(suspects) if suspects else None
