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
        self.reason: str = ""
        self.knowledge: List[str] = []

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

    def role_instructions(self) -> str:
        # Map game role to instruction flavor; avoid duplicating state here
        role = getattr(self.owner, "role", None)
        if role == "werewolf":
            mapped = "mafia"
        elif role == "detective":
            mapped = "detective"
        else:
            mapped = "villager"
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
    # Memory/history removed; previous summarization step skipped.
    # def update_memory(self) -> str:
    #     return ""

    def update_reason(self, game: "Game"):
        self.reason = str(game.events)

    # History updates removed; rely on game.events for context.
    # def Update(self, round_index: int, info: List[Any], event_type: str, semantic: Optional[str] = None) -> None:
    #     return

    def _event_log_excerpt(self, game: "Game", limit: int = 8) -> str:
        try:
            # Use most recent events as context
            lines = [e.get("text", "") for e in (game.events or [])][-limit:]
            return "\n".join(lines)
        except Exception:
            return ""

    def discuss(self, game: Optional["Game"] = None) -> str:
        """Generate a discussion statement (uses game.events as context if provided)."""
        events_text = self._event_log_excerpt(game) if game else ""
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "system", "content": self.role_instructions()},
            {"role": "system", "content": "Recent events:"},
            {"role": "system", "content": events_text},
            {"role": "user",  "content": f"Generate some discussion to the group. Do not include anything else in the output"},
        ]
        try:
            return chat_completion(messages, max_tokens=80, temperature=0.9)
        except Exception as e:
            return f"(failed to discuss: {e})"

    def vote(self, alive_players: List[str], game: Optional["Game"] = None) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "system", "content": self.role_instructions()},
            {"role": "system", "content": f"The following is the event log in JSON format: {self.reason}"},
            {"role": "user", "content": (
                f"These players are still alive: {alive_players}. "
                "Decide who you will vote to eliminate today. "
                "Respond ONLY with the player ID (integer) of your choice."
            )}
        ]
        try:
            vt = chat_completion(messages, max_tokens=10, temperature=0.7)
            return vt.strip()
        except Exception:
            return ""

    def night_action(self, game: Optional["Game"], alive_players: List[str]) -> Optional[str]:
        """Perform role-specific night action (if applicable)."""
        # Simple heuristic: avoid known allies if werewolf
        choices = [pid for pid in (alive_players or []) if pid != self.owner.id]
        try:
            if getattr(self.owner, "role", None) == "werewolf" and game is not None:
                ally_names = set(self.owner.known_allies or [])
                if ally_names:
                    name_by_id = {p.id: p.name for p in game.alive_players()}
                    choices = [pid for pid in choices if name_by_id.get(pid) not in ally_names]
        except Exception:
            pass
        return random.choice(choices) if choices else None

    def detect(self, game: Optional["Game"], alive_players: List[str]) -> Optional[str]:
        # Pick a random non-self suspect
        choices = [pid for pid in (alive_players or []) if pid != self.owner.id]
        return random.choice(choices) if choices else None

    def detect_result(self, player_num: str, role: str) -> None:
        self.knowledge.append(f"Player{player_num} is {role}")


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

    def choose_wolf_target(self, game: "Game") -> Optional[str]:
        return None

    def choose_detective_target(self, game: "Game") -> Optional[str]:
        return None
    
    def speak_in_text(self, game):
        raise NotImplementedError


class HumanPlayer(Player):
    def __init__(self, name: str, *, is_host: bool = False) -> None:
        super().__init__(name, is_host=is_host, is_ai=False)


class AIPlayer(Player):
    def __init__(self, name: str, *, is_host: bool = False) -> None:
        super().__init__(name, is_host=is_host, is_ai=True)
        # Attach agent without duplicating role/teammates
        self.agent = AIAgent(owner=self, persona=name)

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
            self.agent.update_reason(game)
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
            self.agent.update_reason(game)
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
            events_text = "\n".join(e.get("text", "") for e in (game.events or [])[-10:])
        except Exception:
            events_text = ""

        # Use agent prompts and scratch reasoning
        try:
            self.agent.update_reason(game)
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
