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
    print('RUNNING CHAT COMPLETION', messages)
    # last = next((m.get("content", "") for m in reversed(messages) if isinstance(m, dict)), "")
    # words = [w for w in (last or "").split()]
    # return (" ".join(words[: min(20, len(words))]) or "thinking...").strip()
    return text_completion(messages)

role_map = {'werewolf': 'mafia'}
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

    def system_prompt(self) -> str:
        base = f"You are {self.persona}, playing the social deduction game Mafia."
        base += (
            "Rules:\n"
            "- The game alternates between Day (discussion and voting) and Night (actions).\n"
            "- Mafia know each other and can eliminate one player each night.\n"
            "- The Detective can investigate one player each night.\n"
            "- During the Day, all players discuss and vote to eliminate one suspected Mafia.\n"
            "- The game ends when all Mafia are eliminated or the Mafia equal the number of Town members."
        )
        base += (
            " You must think and speak as a human player in this game."
            " Be strategic, persuasive, and consistent with your assigned role."
            " Never reveal your role unless strategically beneficial."
        )
        return base

    def get_mapped_role(self):
        role = getattr(self.owner, "role", None)
        return role_map.get(role, role)

    def role_instructions(self) -> str:
        # Map game role to instruction flavor; avoid duplicating state here
        mapped = self.get_mapped_role()
        if mapped == "mafia":
            return (
                "You are a member of the Mafia. Your goal is to eliminate all non-mafia players without being discovered."
                " Act innocent and persuasive during the day."
            )
        elif mapped == "villager":
            return (
                "You are a Villager. You have no special powers. Your goal is to find and vote out all Mafia members."
                " During the day, discuss suspicions and vote wisely."
            )
        elif mapped == "doctor":
            return (
                "You are the Doctor. Each night, you may choose one player to save from elimination."
                " Try to deduce who the Mafia might target."
            )
        elif mapped == "detective":
            return (
                "You are the Detective. Each night, you can investigate one player to learn if they are Mafia."
                " Use your findings discreetly to influence votes."
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
            return {'past_detections': self.private_info}
        return dict()
        
    def get_generic_info(self, game):
        transcript_info = {'name', 'transcript', 'emotion'}
        ai_transcript_info = {'name', 'message', 'emotion'}
        generic = {'system_prompt': self.system_prompt(),
                'role_prompt': self.role_instructions(),
                'alive_player_list': [p.name for p in game.alive_players()],
                'events': self._event_log_excerpt(game),
                'transcript': [{k: clip[k] for k in (transcript_info & clip.keys())} for clip in game.audio_clips]}
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
            {"role": "system", "content": f"This is the global event log:"},
            {"role": "system", "content": info['events']},
            {"role": "system", "content": f"This is the list of alive players"},
            {"role": "system", "content": info['alive_player_list']},
            {"role": "system", "content": f"This is the transcript in JSON format"},
            {"role": "system", "content": json.dumps(info['transcript'])}] + role_messages

        print('INFO MESSAGES', messages)

        return messages
    
    def choice_action(self, prompt, choices, max_tokens=20, temperature=0.2):
        info_messages = self.get_info()
        messages = info_messages + [{"role": "user", "content": (
                f"{prompt}\n"
                f"Output a choice from the list: {', '.join(choices)}. ONLY output your choice."
            )}
        ]
        try:
            return chat_completion(info_messages, max_tokens=max_tokens, temperature=temperature).strip()
        except Exception as e:
            print(e)
            return ""

    def vote(self, alive_players: List[str], game: Optional["Game"] = None) -> str:
        return self.choice_action('Decide who you will vote to eliminate today.', [p.name for p in game.alive_players()])

    def night_action(self, game: Optional["Game"], alive_players: List[str]) -> Optional[str]:
        """Perform role-specific night action (if applicable)."""
        return self.choice_action('Decide who you will kill tonight.', [p.name for p in game.alive_players()])
    
    def detect(self, game: Optional["Game"], alive_players: List[str]) -> Optional[str]:
        """Perform role-specific night action (if applicable)."""
        return self.choice_action('Decide who you will detect tonight.', [p.name for p in game.alive_players()])
    
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

    def speak_in_text(self, game: "Game") -> str:
        """Generate a short line using the provided prompt template, based on game events."""
        
        # Build history context from recent events
        try:
            events_text = "\n".join(e.get("text", "") for e in (game.events or []))
        except Exception:
            events_text = ""

        # Use agent prompts and scratch reasoning
        try:
            system_prompt = self.agent.system_prompt()
            role_instructions = self.agent.role_instructions()
            reasoning = getattr(self.agent, "reason", "") or ""
        except Exception:
            system_prompt = f"You are {self.name}, playing Mafia."
            role_instructions = "Speak briefly and persuasively."
            reasoning = ""

        if self.role == "werewolf":  # mafia template
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": role_instructions},
                {"role": "system", "content": "The followings are all the historical events"},
                {"role": "system", "content": events_text},
                {"role": "system", "content": f"{self.known_allies} are your mafia team mates."},
                {"role": "user", "content": f"Now using that info, say a brief speech to deceive others. Only include the speech in the output."},
            ]
        elif self.role == "detective":
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": role_instructions},
                {"role": "system", "content": "The followings are all the historical events"},
                {"role": "system", "content": events_text},
                {"role": "system", "content": "you know the roles of the following players"},
                {"role": "system", "content": "\n".join(self.private_notes)},
                {"role": "user", "content": f"Now using that info, say a brief speech. Only include the speech in the output."},
            ]
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": role_instructions},
                {"role": "system", "content": "The followings are all the historical events"},
                {"role": "system", "content": events_text},
                {"role": "user", "content": f"Now using that info, say a brief speech. Only include the speech in the output."},
            ]

        try:
            return chat_completion(messages, max_tokens=80, temperature=0.9)
        except Exception as e:
            return f"(ai speak error: {e})"