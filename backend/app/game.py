from __future__ import annotations

import hashlib
import math
import random
import shutil
import string
import struct
import time
import uuid
import wave
from pathlib import Path
import zipfile
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from backend.app.player import Player, HumanPlayer, AIPlayer

#ADD: ai speaker
from backend.app.ai_speaker import plan_and_speak, asr


def _compose_game_history(game: "Game", *, max_events: int = 40, max_chats: int = 30) -> str:
    """把最近的事件与聊天拼成历史文本，不暴露隐藏身份。用于 LLM 思考与 TTS。"""
    lines = []

    # 事件
    events = (game.events or [])[-max_events:]
    if events:
        lines.append("=== Events ===")
        for e in events:
            t = e.get("text", "")
            ph = e.get("phase", "") or ""
            if ph:
                lines.append(f"[{ph}] {t}")
            else:
                lines.append(t)

    # 聊天
    chats = (game.chat_messages or [])[-max_chats:]
    if chats:
        lines.append("\n=== Chat ===")
        for c in chats:
            nm = c.get("name", "Unknown")
            tx = c.get("text", "")
            lines.append(f"{nm}: {tx}")

    # 公共状态
    lines.append("\n=== Public State ===")
    lines.append(f"Round: {game.round_number}, Stage: {game.workflow_stage or 'unknown'}")
    alive = [p.name for p in game.alive_players()]
    lines.append(f"Alive: {', '.join(alive) if alive else '(none)'}")

    return "\n".join(lines).strip()
# END ADD

def _generate_join_code(length: int = 4) -> str:
    """Generate an uppercase join code that is easy to share."""
    return "".join(random.choices(string.ascii_uppercase, k=length))

#added
class DebugInfo(BaseModel):
    enabled: bool
    history: Optional[str] = None
    thinkRaw: Optional[str] = None

DebugInfo.model_rebuild()
#end added  

class PlayerPublic(BaseModel):
    playerId: str
    name: str
    isHost: bool
    isAI: bool
    isAlive: bool
    role: Optional[str] = None


class EventLogEntry(BaseModel):
    eventId: str
    text: str
    phase: str
    timestamp: float


class GameStateResponse(BaseModel):
    gameId: str
    joinCode: str
    status: str
    players: List[PlayerPublic]
    aiMessages: List["AISpeechLog"] = Field(default_factory=list)
    audioClips: List["AudioClipInfo"] = Field(default_factory=list)
    chatMessages: List["ChatMessage"] = Field(default_factory=list)
    events: List[EventLogEntry] = Field(default_factory=list)
    workflowStage: str
    nightStage: Optional[str] = None
    roundNumber: int
    currentTurnPlayerId: Optional[str]
    currentTurnPosition: Optional[int]
    turnOrder: List["TurnEntry"] = Field(default_factory=list)
    votes: List["VoteRecord"] = Field(default_factory=list)
    victoryTeam: Optional[str] = None
    victoryMessage: Optional[str] = None


class GameCreationResponse(GameStateResponse):
    hostPlayerId: str


class PlayerSessionResponse(BaseModel):
    playerId: str
    name: str
    role: Optional[str]
    status: str
    isAlive: bool
    isAI: Optional[bool] = None
    roleSummary: Optional[str] = None
    notes: List[str] = Field(default_factory=list)
    knownAllies: List[str] = Field(default_factory=list)


class AISpeechLog(BaseModel):
    aiPlayerId: str
    name: str
    message: str
    timestamp: float


class AudioClipInfo(BaseModel):
    clipId: str
    playerId: str
    name: str
    filename: str
    contentType: str
    size: int
    storagePath: Optional[str] = None
    transcript: Optional[str] = None


class ChatMessage(BaseModel):
    messageId: str
    playerId: str
    name: str
    text: str
    timestamp: float


class TurnEntry(BaseModel):
    playerId: str
    name: str
    isAI: bool
    order: int
    isCurrent: bool


class VoteRecord(BaseModel):
    voterId: str
    targetPlayerId: Optional[str] = None


class AISpeakResponse(BaseModel):
    message: AISpeechLog
    audioClip: Optional[AudioClipInfo] = None


class AudioUploadResponse(BaseModel):
    clipId: str
    status: str


GameStateResponse.model_rebuild()
GameCreationResponse.model_rebuild()
PlayerSessionResponse.model_rebuild()
AISpeakResponse.model_rebuild()
AudioUploadResponse.model_rebuild()
ChatMessage.model_rebuild()
TurnEntry.model_rebuild()
VoteRecord.model_rebuild()
AudioClipInfo.model_rebuild()
EventLogEntry.model_rebuild()


"""
Player types have been moved to backend/app/player.py (Player, HumanPlayer, AIPlayer).
"""


class Game:
    def __init__(self, host_name: str, join_code: str) -> None:
        self.id = str(uuid.uuid4())
        self.join_code = join_code
        host = HumanPlayer(host_name, is_host=True)
        self.players: Dict[str, Player] = {host.id: host}
        self.host_id = host.id
        self.status = "waiting"
        self.ai_messages: List[Dict[str, Any]] = []
        self.audio_clips: List[Dict[str, Any]] = []
        self.audio_files: Dict[str, Path] = {}
        self.chat_messages: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        self.join_sequence: List[str] = [host.id]
        self.turn_order: List[str] = []
        self.current_turn_index: Optional[int] = None
        self.round_number: int = 0
        self.workflow_stage: str = "lobby"
        self.detective_id: Optional[str] = None
        self.werewolf_ids: List[str] = []
        self.werewolf_votes: Dict[str, str] = {}
        self.detective_target: Optional[str] = None
        self.victory_team: Optional[str] = None
        self.victory_message: Optional[str] = None
        # NEW: votes map voter_id -> target_id for current Day
        self.votes: Dict[str, str] = {}
        self.night_stage: Optional[str] = None
        self.last_night_kill_id: Optional[str] = None
        self.debug_panel_enabled: bool = True          # 是否开放调试窗口
        self.last_think_output: Optional[str] = None   # 最近一次 think model 的原始输出
        self.last_history_text: Optional[str] = None   # 最近一次合成给 think 的历史文本


    @property
    def player_list(self) -> List[PlayerPublic]:
        return [
            PlayerPublic(
                playerId=p.id,
                name=p.name,
                isHost=p.is_host,
                isAI=p.is_ai,
                isAlive=p.is_alive,
                # Do not reveal roles on death; only reveal after the game ends
                role=p.role if (self.status == "ended") else None,
            )
            for p in self.players.values()
        ]

    def alive_players(self) -> List[Player]:
        return [player for player in self.players.values() if player.is_alive]

    def alive_werewolves(self) -> List[Player]:
        return [player for player in self.alive_players() if player.role == "werewolf"]

    def alive_villagers(self) -> List[Player]:
        return [player for player in self.alive_players() if player.role != "werewolf"]

    def start_night(self, intro_text: Optional[str] = None) -> None:
        self.workflow_stage = "night"
        self.night_stage = "wolves"
        self.current_turn_index = None
        self.turn_order = []
        self.last_night_kill_id = None
        self.werewolf_votes.clear()
        self.detective_target = None
        if intro_text:
            _record_event(self, intro_text, phase="night")

    def _resolve_wolf_target(self) -> Optional[Player]:
        valid_targets = {p.id for p in self.alive_villagers()}
        tally: Dict[str, int] = {}
        for wolf in self.alive_werewolves():
            tgt = self.werewolf_votes.get(wolf.id)
            if tgt in valid_targets:
                tally[tgt] = tally.get(tgt, 0) + 1

        if not tally:
            return None

        top = max(tally.values())
        candidates = [pid for pid, count in tally.items() if count == top]
        target_id = random.choice(candidates)
        return self.players.get(target_id)

    def _execute_wolf_stage(self) -> None:
        wolves = self.alive_werewolves()
        villagers = self.alive_villagers()
        if not wolves or not villagers:
            self.last_night_kill_id = None
            _record_event(self, "The night passed quietly. No villagers were harmed.", phase="night")
            return

        for wolf in wolves:
            if wolf.is_ai and wolf.is_alive and wolf.id not in self.werewolf_votes:
                ai_choice = wolf.choose_wolf_target(self)
                if ai_choice:
                    self.werewolf_votes[wolf.id] = ai_choice

        target = self._resolve_wolf_target()
        if target:
            target.is_alive = False
            self.last_night_kill_id = target.id
            _record_event(self, f"Werewolves eliminated {target.name} under the moonlight.", phase="night")
        else:
            self.last_night_kill_id = None
            _record_event(self, "The night passed quietly. No villagers were harmed.", phase="night")

    def _execute_detective_stage(self) -> None:
        detective = self.players.get(self.detective_id) if self.detective_id else None
        if not detective or not detective.is_alive:
            self.detective_target = None
            return

        if detective.is_ai and not self.detective_target:
            ai_choice = detective.choose_detective_target(self)
            if ai_choice:
                self.detective_target = ai_choice

        observed = None
        if self.detective_target:
            candidate = self.players.get(self.detective_target)
            if candidate and candidate.is_alive:
                observed = candidate

        if not observed:
            suspects = [p for p in self.alive_players() if p.id != detective.id]
            if suspects:
                observed = random.choice(suspects)

        if observed:
            # Do not reveal alignment/role in inspection results
            note = f"You inspected {observed.name}."
            detective.private_notes.append(note)
            if len(detective.private_notes) > 5:
                detective.private_notes = detective.private_notes[-5:]

        self.detective_target = None

    def _execute_summary_stage(self) -> None:
        self.werewolf_votes.clear()
        self.detective_target = None
        self.last_night_kill_id = None
        if _evaluate_victory(self):
            self.night_stage = None
            return

        _prepare_turn_order(self)
        self.night_stage = None

    def advance_night_stage(self) -> str:
        if self.workflow_stage != "night":
            raise HTTPException(status_code=400, detail="Night actions are not active.")

        if _evaluate_victory(self):
            self.night_stage = None
            return "ended"

        stage = self.night_stage or "wolves"
        if stage == "wolves":
            self._execute_wolf_stage()
            if _evaluate_victory(self):
                self.night_stage = None
                return "ended"
            self.night_stage = "detective"
            return "detective"

        if stage == "detective":
            self._execute_detective_stage()
            self.night_stage = "summary"
            return "summary"

        if stage == "summary":
            self._execute_summary_stage()
            return "complete"

        self.night_stage = "wolves"
        return "wolves"

ROLE_SUMMARIES: Dict[str, str] = {
    "civilian": "Stay vigilant, discuss clues, and vote smart to catch the pack.",
    "detective": "Investigate quietly each night. Share just enough to sway the group.",
    "werewolf": "Blend in during the day and secretly thin the crowd at night.",
}


AUDIO_STORAGE_DIR = Path(__file__).resolve().parent.parent / "data" / "audio"
AUDIO_STORAGE_DIR.mkdir(parents=True, exist_ok=True)


AI_PHRASES = [
    "The moon feels restless; someone is hiding long teeth.",
    "Listen for shaky stories. Wolves always trip over the details.",
    "Detective, keep your clues subtle. The village needs you alive.",
    "If the crowd talks in circles, a wolf is steering the debate.",
    "Numbers matter. Protect the quiet civilians before it's too late.",
    "I smell fur near the well—maybe a nervous voice gave it away.",
    "When accusations fly too fast, someone is covering their tracks.",
    "Spread lanterns, not panic. Wolves thrive in confusion.",
    "Werewolves win when suspicion turns inward. Stay coordinated.",
    "Detective's hunches might sound odd, but they've seen the night.",
]

TRANSCRIPT_GLOSSARY = [
    "murmurs about silver",
    "warns the patrol",
    "eyes the town square",
    "shares coded howls",
    "cautions the detective",
    "chants an oath",
    "sketches the suspect",
    "chants under breath",
    "mentions claw marks",
    "mutters about lanterns",
]

MAX_AUDIO_HISTORY = 20


def _record_event(game: Game, text: str, *, phase: Optional[str] = None) -> None:
    entry = {
        "eventId": str(uuid.uuid4()),
        "text": text,
        "phase": phase or game.workflow_stage,
        "timestamp": time.time(),
    }
    game.events.append(entry)
    # if len(game.events) > 50:
    #     game.events = game.events[-50:]


# Player and AI agent implementations are located in backend/app/player.py


def _prepare_turn_order(game: Game) -> None:
    # New day begins; clear prior votes
    game.votes.clear()

    living_order = [
        player_id
        for player_id in game.join_sequence
        if player_id in game.players and game.players[player_id].is_alive
    ]
    game.turn_order = living_order
    if living_order:
        game.current_turn_index = 0
        game.round_number += 1
        game.workflow_stage = "discussion"
        _record_event(game, f"Day {game.round_number} discussion begins.", phase="discussion")
    else:
        game.current_turn_index = None
        game.workflow_stage = "night"


def _declare_victory(game: Game, team: str, message: str) -> None:
    game.status = "ended"
    game.workflow_stage = "ended"
    game.victory_team = team
    game.victory_message = message
    _record_event(game, message, phase="ended")


def _evaluate_victory(game: Game) -> bool:
    wolves = game.alive_werewolves()
    villagers = game.alive_villagers()
    if not wolves:
        _declare_victory(game, "village", "The town prevails! No werewolves remain.")
        return True
    if len(wolves) >= len(villagers):
        _declare_victory(game, "werewolves", "The pack overpowers the town. Wolves win.")
        return True
    return False


def _assign_roles(game: Game) -> None:
    if len(game.players) < 4:
        raise HTTPException(status_code=400, detail="Need at least 4 players for Mafia.")

    player_ids = list(game.players.keys())
    random.shuffle(player_ids)

    for player in game.players.values():
        player.role = "civilian"
        player.is_alive = True
        player.private_notes = []
        player.known_allies = []

    detective_id = player_ids.pop()
    game.players[detective_id].role = "detective"
    game.detective_id = detective_id

    remaining = player_ids
    werewolf_count = 2 if len(game.players) >= 6 else 1
    werewolf_ids = random.sample(remaining, k=min(werewolf_count, len(remaining)))

    for wolf_id in werewolf_ids:
        game.players[wolf_id].role = "werewolf"

    for wolf_id in werewolf_ids:
        wolf = game.players[wolf_id]
        wolf.known_allies = [game.players[ally_id].name for ally_id in werewolf_ids if ally_id != wolf_id]

    game.werewolf_ids = werewolf_ids
    game.status = "in_progress"
    game.round_number = 0
    game.turn_order = []
    game.current_turn_index = None
    game.victory_team = None
    game.victory_message = None
    game.events.clear()
    game.votes.clear()
    # Let AI agents sync to their assigned roles/teammates
    for p in game.players.values():
        if isinstance(p, AIPlayer):
            p.on_role_assigned(game)

    game.start_night("Roles assigned. Night falls over the village.")


def _mock_transcribe_audio(player: Player, clip_id: str, data: bytes) -> str:
    digest = hashlib.sha1(clip_id.encode("utf-8") + data[:256]).hexdigest()
    rng = random.Random(digest)
    phrase = " ".join(rng.choice(TRANSCRIPT_GLOSSARY) for _ in range(2))
    return f"{player.name} {phrase} ({digest[:6]})."


def _prune_audio(game: Game) -> None:
    while len(game.audio_clips) > MAX_AUDIO_HISTORY:
        oldest = game.audio_clips.pop(0)
        old_id = oldest.get("clipId")
        path = game.audio_files.pop(old_id, None)
        if path:
            try:
                path_obj = Path(path)
                if path_obj.exists():
                    path_obj.unlink()
            except OSError:
                pass


def _store_audio_clip(game: Game, metadata: Dict[str, Any], clip_id: str, path: Path) -> None:
    game.audio_clips.append(metadata)
    game.audio_files[clip_id] = path
    _prune_audio(game)

# ADD: generate AI audio clip, substitute duck for TTS service
def _generate_ai_audio_clip(game: "Game", ai_player: "Player") -> Dict[str, Any]:
    """使用 ai_speaker.plan_and_speak 基于游戏历史生成 AI 人声 WAV，并存储为音频片段。
       同时记录最近一次 history 与 think 原始输出到 Game。"""
    clip_id = str(uuid.uuid4())

    # 独立目录
    audio_dir = AUDIO_STORAGE_DIR / game.id
    audio_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{clip_id}.wav"
    file_path = audio_dir / filename

    transcript_text = "..."
    try:
        history_text = _compose_game_history(game, max_events=40, max_chats=30)
<<<<<<< HEAD
        game.last_history_text = history_text  # <<< 记录历史

        plan = plan_and_speak(history_text, out_name=str(file_path))
=======
        # 这里会把音频直接写入 file_path
        print(ai_player)
        plan = plan_and_speak(*ai_player.agent.get_relevant_info(game), out_name=str(file_path))
>>>>>>> 7f86eedf75fe3798b4c897f45eca6446a7074065
        transcript_text = str(plan.get("content", "")).strip() or "..."
        game.last_think_output = str(plan.get("_raw_model_output", "")) or "(empty)"  # <<< 记录 think 原始输出
    except Exception as e:
<<<<<<< HEAD
        game.last_think_output = f"(TTS/plan failed: {e})"
        # 兜底：100ms 静音，避免前端报错
=======
        # 兜底：失败时写一个极短的空WAV（不理想，但不会让前端炸掉）
        print(e)
        transcript_text = "(TTS failed; empty audio fallback)"
>>>>>>> 7f86eedf75fe3798b4c897f45eca6446a7074065
        try:
            with wave.open(str(file_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00" * 3200)
        except Exception:
            pass

    try:
        size = (file_path.stat().st_size if file_path.exists() else 0)
    except Exception:
        size = 0

    metadata = {
        "clipId": clip_id,
        "playerId": ai_player.id,
        "name": ai_player.name,
        "filename": filename,
        "contentType": "audio/wav",
        "size": size,
        "storagePath": str(file_path),
        "transcript": transcript_text,
    }
    _store_audio_clip(game, metadata, clip_id, file_path)
    return metadata

games_by_id: Dict[str, Game] = {}
games_by_code: Dict[str, Game] = {}


def _get_game_or_404(game_id: str) -> Game:
    game = games_by_id.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found.")
    return game


def _get_player(game: Game, player_id: str) -> Player:
    player = game.players.get(player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found in this game.")
    return player


def _build_game_state_response(game: Game) -> GameStateResponse:
    ai_messages = [AISpeechLog(**entry) for entry in game.ai_messages]
    audio_clips = [AudioClipInfo(**entry) for entry in game.audio_clips]
    chat_messages = [ChatMessage(**entry) for entry in game.chat_messages]
    events = [EventLogEntry(**entry) for entry in game.events]
    game.turn_order = [
        pid
        for pid in game.turn_order
        if pid in game.players and game.players[pid].is_alive
    ]

    current_player_id: Optional[str] = None
    current_position: Optional[int] = None
    if game.workflow_stage == "discussion" and game.turn_order:
        if game.current_turn_index is None or game.current_turn_index >= len(game.turn_order):
            game.current_turn_index = 0
        current_player_id = game.turn_order[game.current_turn_index]
        current_position = game.current_turn_index + 1
    else:
        game.current_turn_index = None

    turn_entries: List[TurnEntry] = []
    for idx, player_id in enumerate(game.turn_order):
        player = game.players.get(player_id)
        if not player or not player.is_alive:
            continue
        turn_entries.append(
            TurnEntry(
                playerId=player_id,
                name=player.name,
                isAI=player.is_ai,
                order=idx + 1,
                isCurrent=current_player_id == player_id and game.workflow_stage == "discussion",
            )
        )

    vote_records = [
        VoteRecord(voterId=voter_id, targetPlayerId=target_id)
        for voter_id, target_id in game.votes.items()
        if voter_id in game.players
    ]

    return GameStateResponse(
        gameId=game.id,
        joinCode=game.join_code,
        status=game.status,
        players=game.player_list,
        aiMessages=ai_messages,
        audioClips=audio_clips,
        chatMessages=chat_messages,
        events=events,
        workflowStage=game.workflow_stage,
        nightStage=game.night_stage,
        roundNumber=game.round_number,
        currentTurnPlayerId=current_player_id,
        currentTurnPosition=current_position,
        turnOrder=turn_entries,
        votes=vote_records,
        victoryTeam=game.victory_team,
        victoryMessage=game.victory_message,
    )


def create_game(host_name: str) -> GameCreationResponse:
    trimmed = host_name.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Host name cannot be empty.")

    join_code = _generate_join_code()
    while join_code in games_by_code:
        join_code = _generate_join_code()

    game = Game(host_name=trimmed, join_code=join_code)
    games_by_id[game.id] = game
    games_by_code[game.join_code] = game

    state = _build_game_state_response(game)
    return GameCreationResponse(
        **state.dict(),
        hostPlayerId=game.host_id,
    )


def find_game_by_code(join_code: str) -> GameStateResponse:
    game = games_by_code.get(join_code.upper())
    if not game:
        raise HTTPException(status_code=404, detail="Game not found.")
    return _build_game_state_response(game)


def join_game(game_id: str, player_name: str) -> PlayerSessionResponse:
    game = _get_game_or_404(game_id)
    if game.status != "waiting":
        raise HTTPException(status_code=400, detail="Game already started.")

    trimmed_name = player_name.strip()
    if not trimmed_name:
        raise HTTPException(status_code=400, detail="Player name cannot be empty.")

    player = HumanPlayer(trimmed_name, is_host=False)
    game.players[player.id] = player
    if player.id not in game.join_sequence:
        game.join_sequence.append(player.id)

    return PlayerSessionResponse(
        playerId=player.id,
        name=player.name,
        status=game.status,
        role=None,
        isAlive=player.is_alive,
        isAI=False,
        roleSummary=None,
        notes=[],
        knownAllies=[],
    )


def add_ai_player(game_id: str, host_player_id: str, ai_name: Optional[str]) -> GameStateResponse:
    game = _get_game_or_404(game_id)
    host = _get_player(game, host_player_id)

    if not host.is_host:
        raise HTTPException(status_code=403, detail="Only the host can add AI players.")

    if game.status != "waiting":
        raise HTTPException(status_code=400, detail="Cannot add AI players after the game starts.")

    base_name = (ai_name or "").strip()
    if not base_name:
        ai_count = sum(1 for p in game.players.values() if p.is_ai)
        base_name = f"AI Agent {ai_count + 1}"

    existing_names = {p.name for p in game.players.values()}
    candidate = base_name
    suffix = 2
    while candidate in existing_names:
        candidate = f"{base_name} {suffix}"
        suffix += 1

    ai_player = AIPlayer(candidate, is_host=False)
    game.players[ai_player.id] = ai_player
    if ai_player.id not in game.join_sequence:
        game.join_sequence.append(ai_player.id)

    _record_event(game, f"{ai_player.name} joined the lobby.", phase="lobby")
    return _build_game_state_response(game)


# NEW: Remove player from lobby (host only, cannot remove host)
def remove_player(game_id: str, host_player_id: str, target_player_id: str) -> GameStateResponse:
    game = _get_game_or_404(game_id)
    host = _get_player(game, host_player_id)

    if not host.is_host:
        raise HTTPException(status_code=403, detail="Only the host can remove players.")

    if game.status != "waiting":
        raise HTTPException(status_code=400, detail="Players can only be removed in the lobby before the game starts.")

    if target_player_id == game.host_id:
        raise HTTPException(status_code=400, detail="Cannot remove the host.")

    target = game.players.get(target_player_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target player not found.")

    name = target.name
    # Remove player and clean up sequences
    game.players.pop(target_player_id, None)
    if target_player_id in game.join_sequence:
        game.join_sequence = [pid for pid in game.join_sequence if pid != target_player_id]
    if target_player_id in game.turn_order:
        game.turn_order = [pid for pid in game.turn_order if pid != target_player_id]

    # Remove any votes they cast or received (in case voting UI is surfaced early)
    game.votes = {voter: tgt for voter, tgt in game.votes.items() if voter != target_player_id and tgt != target_player_id}

    _record_event(game, f"{name} was removed from the lobby by the host.", phase="lobby")
    return _build_game_state_response(game)


def start_game(game_id: str, player_id: str, word_set_id: Optional[str] = None) -> GameStateResponse:
    game = _get_game_or_404(game_id)
    host = _get_player(game, player_id)

    if not host.is_host:
        raise HTTPException(status_code=403, detail="Only the host can start the game.")

    if len(game.players) < 4:
        raise HTTPException(status_code=400, detail="Need at least 4 players to start.")

    if game.status != "waiting":
        raise HTTPException(status_code=400, detail="Game already started.")

    _assign_roles(game)

    return _build_game_state_response(game)


def advance_turn(game_id: str, player_id: str) -> GameStateResponse:
    game = _get_game_or_404(game_id)
    host = _get_player(game, player_id)

    if not host.is_host:
        raise HTTPException(status_code=403, detail="Only the host can advance turns.")

    if game.status != "in_progress":
        raise HTTPException(status_code=400, detail="Cannot advance turns unless the game is active.")

    if game.workflow_stage != "discussion":
        raise HTTPException(status_code=400, detail="Discussion is not active. Resolve the night first.")

    if not game.turn_order:
        raise HTTPException(status_code=400, detail="No speakers available. Resolve the night again.")

    if game.current_turn_index is None:
        game.current_turn_index = 0
    elif game.current_turn_index < len(game.turn_order) - 1:
        game.current_turn_index += 1
    else:
        raise HTTPException(status_code=400, detail="All players have spoken. Close the day to continue.")

    return _build_game_state_response(game)


def wolf_vote(game_id: str, player_id: str, target_player_id: str) -> GameStateResponse:
    game = _get_game_or_404(game_id)

    if game.status != "in_progress" or game.workflow_stage != "night":
        raise HTTPException(status_code=400, detail="Werewolves act only at night.")

    wolf = _get_player(game, player_id)
    if not wolf.is_alive or wolf.role != "werewolf":
        raise HTTPException(status_code=403, detail="Only alive werewolves can choose a target.")

    current_stage = game.night_stage or "wolves"
    if current_stage != "wolves":
        raise HTTPException(status_code=400, detail="Werewolf actions have already been processed.")

    target = game.players.get(target_player_id)
    if not target or not target.is_alive:
        raise HTTPException(status_code=404, detail="Target not found or not alive.")

    if target.role == "werewolf":
        raise HTTPException(status_code=400, detail="Werewolves cannot attack a packmate.")

    game.werewolf_votes[wolf.id] = target.id
    return _build_game_state_response(game)


def detective_select(game_id: str, player_id: str, target_player_id: str) -> GameStateResponse:
    game = _get_game_or_404(game_id)

    if game.status != "in_progress" or game.workflow_stage != "night":
        raise HTTPException(status_code=400, detail="Detective acts only at night.")

    if not game.detective_id:
        raise HTTPException(status_code=400, detail="This game has no detective.")

    detective = _get_player(game, player_id)
    if detective.id != game.detective_id:
        raise HTTPException(status_code=403, detail="Only the detective can inspect.")
    if not detective.is_alive:
        raise HTTPException(status_code=400, detail="Eliminated detective cannot inspect.")

    current_stage = game.night_stage or "wolves"
    if current_stage != "detective":
        raise HTTPException(status_code=400, detail="Detective actions are not available right now.")

    target = game.players.get(target_player_id)
    if not target or not target.is_alive:
        raise HTTPException(status_code=404, detail="Target not found or not alive.")
    if target.id == detective.id:
        raise HTTPException(status_code=400, detail="Detective cannot inspect themselves.")

    game.detective_target = target.id
    return _build_game_state_response(game)


def advance_night(game_id: str, player_id: str) -> GameStateResponse:
    game = _get_game_or_404(game_id)
    host = _get_player(game, player_id)

    if not host.is_host:
        raise HTTPException(status_code=403, detail="Only the host can advance the night.")

    if game.status != "in_progress":
        raise HTTPException(status_code=400, detail="Game is not running.")

    if game.workflow_stage != "night":
        raise HTTPException(status_code=400, detail="Night actions are already complete.")

    game.advance_night_stage()
    return _build_game_state_response(game)


def resolve_night(game_id: str, player_id: str) -> GameStateResponse:
    """Maintained for backward compatibility; delegates to advance_night."""
    return advance_night(game_id, player_id)

# modify
def trigger_speech(
    game_id: str,
    requester_player_id: str,
    speaker_player_id: Optional[str] = None,
) -> AISpeakResponse:
    game = _get_game_or_404(game_id)
    requester = _get_player(game, requester_player_id)

    if game.status == "waiting":
        raise HTTPException(status_code=400, detail="Start the game before cueing speech.")

    current_speaker_id = speaker_player_id or (
        game.current_turn_player_id if game.workflow_stage == "discussion" else None
    )
    if not current_speaker_id:
        raise HTTPException(status_code=400, detail="No speaker is currently active.")

    speaker: Player = game.players.get(current_speaker_id)
    if not speaker or not speaker.is_alive:
        raise HTTPException(status_code=404, detail="Speaker not found or not alive.")

    if requester.id != speaker.id and not requester.is_host:
        raise HTTPException(
            status_code=403, detail="Only the host or the speaker may trigger speech."
        )

    if not speaker.is_ai:
        raise HTTPException(status_code=400, detail="AI speech can only be triggered for AI players.")

    # 直接合成语音（内部会记录 last_history_text / last_think_output）
    try:
        audio_meta = _generate_ai_audio_clip(game, speaker)
        message_text = audio_meta.get("transcript") or ""
    except Exception as e:
        message_text = f"(ai speech error: {e})"
        audio_meta = {
            "clipId": str(uuid.uuid4()),
            "playerId": speaker.id,
            "name": speaker.name,
            "filename": "",
            "contentType": "audio/wav",
            "size": 0,
            "storagePath": None,
            "transcript": message_text,
        }

    entry = {
        "aiPlayerId": speaker.id,
        "name": speaker.name,
        "message": message_text,
        "timestamp": time.time(),
    }
    game.ai_messages.append(entry)
    if len(game.ai_messages) > 20:
        game.ai_messages = game.ai_messages[-20:]

    return AISpeakResponse(
        message=AISpeechLog(**entry),
        audioClip=AudioClipInfo(**audio_meta),
    )



def get_debug_info(game_id: str) -> DebugInfo:
    """读取调试窗口数据：开启则返回 history + thinkRaw；关闭只返回 enabled=false。"""
    game = _get_game_or_404(game_id)
    if not game.debug_panel_enabled:
        return DebugInfo(enabled=False, history=None, thinkRaw=None)
    return DebugInfo(
        enabled=True,
        history=game.last_history_text or "",
        thinkRaw=game.last_think_output or "",
    )


def set_debug_enabled(game_id: str, player_id: str, enabled: bool) -> DebugInfo:
    """仅 Host 可切换调试面板开关。"""
    game = _get_game_or_404(game_id)
    host = _get_player(game, player_id)
    if not host.is_host:
        raise HTTPException(status_code=403, detail="Only the host can toggle debug window.")
    game.debug_panel_enabled = bool(enabled)
    # 如需关闭时清空缓存，可放开下面两行
    # if not game.debug_panel_enabled:
    #     game.last_history_text = None
    #     game.last_think_output = None
    return get_debug_info(game_id)

# modify end

def finish_round(game_id: str, player_id: str) -> GameStateResponse:
    game = _get_game_or_404(game_id)
    host = _get_player(game, player_id)

    if not host.is_host:
        raise HTTPException(status_code=403, detail="Only the host can finish the round.")

    if game.status != "in_progress":
        raise HTTPException(status_code=400, detail="Cannot finish the round right now.")

    if game.workflow_stage != "discussion":
        raise HTTPException(status_code=400, detail="Only discussions can be closed.")

    # Close the day: go to night; clear votes
    game.start_night(f"Day {game.round_number} closes. Night {game.round_number + 1} begins.")

    return _build_game_state_response(game)


def submit_vote(game_id: str, voter_player_id: str, target_player_id: Optional[str]) -> GameStateResponse:
    game = _get_game_or_404(game_id)

    if game.status != "in_progress":
        raise HTTPException(status_code=400, detail="Voting is only available during the game.")

    if game.workflow_stage != "discussion":
        raise HTTPException(status_code=400, detail="Voting is only allowed during the day discussion.")

    voter = _get_player(game, voter_player_id)
    if not voter.is_alive:
        raise HTTPException(status_code=400, detail="Eliminated players cannot vote.")

    if target_player_id is not None and target_player_id == voter.id:
        raise HTTPException(status_code=400, detail="You cannot vote for yourself.")

    target: Optional[Player] = None
    if target_player_id is not None:
        target = game.players.get(target_player_id)
        if not target or not target.is_alive:
            raise HTTPException(status_code=404, detail="Target player not found or not alive.")

    # Record (or change) vote
    previous_target = game.votes.get(voter.id)
    game.votes[voter.id] = target.id if target else None

    # Tally votes among alive voters only
    alive_ids = {p.id for p in game.alive_players()}
    tally: Dict[str, int] = {}
    for voter_id, tgt in game.votes.items():
        if voter_id in alive_ids and tgt in alive_ids:
            tally[tgt] = tally.get(tgt, 0) + 1

    majority = (len(alive_ids) // 2) + 1
    top_target_id = max(tally, key=tally.get) if tally else None
    top_votes = tally.get(top_target_id, 0) if top_target_id else 0

    # Log vote change (lightweight)
    new_target_id = target.id if target else None
    if previous_target != new_target_id:
        if target:
            verb = f"voted to remove {target.name}"
        else:
            verb = "chose to abstain"
        _record_event(game, f"{voter.name} {verb}.", phase="discussion")

    # If majority reached, kick immediately and go to night
    if top_target_id and top_votes >= majority:
        kicked = game.players.get(top_target_id)
        if kicked and kicked.is_alive:
            kicked.is_alive = False
            _record_event(game, f"The town has voted. {kicked.name} is removed from the game.", phase="discussion")

            if _evaluate_victory(game):
                return _build_game_state_response(game)

            # Day ends after a kick; proceed to night
            game.start_night(
                f"Day {game.round_number} closes after a vote. Night {game.round_number + 1} begins."
            )

    return _build_game_state_response(game)


def trigger_ai_votes(game_id: str, player_id: str) -> GameStateResponse:
    """Host-triggered: cast random votes for all alive AI players who haven't voted.

    - Only allowed during in-progress day discussion.
    - Skips AI who already voted.
    - 20% chance to abstain; otherwise random alive non-self target.
    - Stops early if a majority ends the day.
    """
    game = _get_game_or_404(game_id)
    host = _get_player(game, player_id)

    if not host.is_host:
        raise HTTPException(status_code=403, detail="Only the host can trigger AI votes.")

    if game.status != "in_progress":
        raise HTTPException(status_code=400, detail="Voting is only available during the game.")

    if game.workflow_stage != "discussion":
        raise HTTPException(status_code=400, detail="AI votes can only be triggered during the day discussion.")

    alive_ids = {p.id for p in game.alive_players()}
    # Consider only alive voters as 'already voted'
    voted_alive_ids = {voter_id for voter_id, _ in game.votes.items() if voter_id in alive_ids}

    # AI players who are alive and have not yet voted
    ai_voters = [
        p for p in game.players.values() if p.is_ai and p.is_alive and p.id not in voted_alive_ids
    ]

    for ai in ai_voters:
        # If majority was reached while processing earlier votes, stop
        if game.workflow_stage != "discussion":
            break

        # Randomly abstain ~20% of the time; otherwise pick a random alive non-self target
        target_id: Optional[str] = None
        candidates = [pid for pid in alive_ids if pid != ai.id]
        if candidates:
            if random.random() < 0.2:
                target_id = None
            else:
                # Prefer agent choice; fallback to random
                try:
                    if isinstance(ai, AIPlayer) and hasattr(ai, "agent"):
                        # Pass the full game for event/context-aware voting
                        pick = ai.agent.vote(list(candidates), game)
                        if pick in candidates:
                            target_id = pick
                        else:
                            target_id = random.choice(candidates)  # TODO, pick the top suspect
                    else:
                        target_id = random.choice(candidates)
                except Exception:
                    target_id = random.choice(candidates)

        # Reuse regular vote pathway for validation, logging, and majority handling
        try:
            submit_vote(game_id, ai.id, target_id)
        except HTTPException:
            # Ignore transient errors (e.g., state changed mid-loop)
            if game.workflow_stage != "discussion":
                break
            continue

    return _build_game_state_response(game)


def get_game_state(game_id: str) -> GameStateResponse:
    game = _get_game_or_404(game_id)
    return _build_game_state_response(game)


def get_player_assignment(game_id: str, player_id: str) -> PlayerSessionResponse:
    game = _get_game_or_404(game_id)
    player = _get_player(game, player_id)

    role = player.role if game.status != "waiting" else None
    role_summary = ROLE_SUMMARIES.get(role) if role else None
    allies = player.known_allies if role == "werewolf" and role is not None else []
    notes = list(player.private_notes)

    return PlayerSessionResponse(
        playerId=player.id,
        name=player.name,
        status=game.status,
        role=role,
        isAlive=player.is_alive,
        isAI=player.is_ai,
        roleSummary=role_summary,
        notes=notes,
        knownAllies=allies,
    )


async def save_audio_from_server(game_id: str, player_id: str, file: UploadFile) -> AudioUploadResponse:
    game = _get_game_or_404(game_id)
    player = _get_player(game, player_id)
    print('SAVING AUDIO FOR PLAYER', player)
    data = await file.read()

    if not data:
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")

    size_limit = 5 * 1024 * 1024  # 5 MB
    if len(data) > size_limit:
        raise HTTPException(status_code=400, detail="Audio file is too large (limit 5 MB).")

    clip_id = str(uuid.uuid4())
    original_name = file.filename or "speech.wav"
    original_name = Path(original_name).name
    content_type = file.content_type or "application/octet-stream"
    # Only accept/save WAV; front-end sends WAV now.
    # Minimal signature check for RIFF/WAVE header; otherwise reject.
    data_start = data[:12]
    is_wav = (len(data_start) >= 12 and data_start[:4] == b"RIFF" and data_start[8:12] == b"WAVE") or (
        original_name.lower().endswith(".wav")
    ) or (content_type in {"audio/wav", "audio/x-wav"})
    if not is_wav:
        raise HTTPException(status_code=415, detail="Only WAV audio is supported.")
    filename = f"{clip_id}.wav"

    audio_dir = AUDIO_STORAGE_DIR / game.id
    audio_dir.mkdir(parents=True, exist_ok=True)
    file_path = audio_dir / filename
    file_path.write_bytes(data)

    transcript = asr(file_path)
    metadata = {
        "clipId": clip_id,
        "playerId": player.id,
        "name": player.name,
        "filename": original_name if original_name.lower().endswith('.wav') else filename,
        "contentType": "audio/wav",
        "size": len(data),
        "storagePath": str(file_path),
        "transcript": transcript,
    }

    _store_audio_clip(game, metadata, clip_id, file_path)

    return AudioUploadResponse(clipId=clip_id, status="stored")


def get_audio_clip(game_id: str, clip_id: str) -> FileResponse:
    game = _get_game_or_404(game_id)
    meta = next((m for m in game.audio_clips if m.get("clipId") == clip_id), None)
    if not meta:
        raise HTTPException(status_code=404, detail="Audio metadata not found.")

    file_path = game.audio_files.get(clip_id)
    if not file_path:
        raise HTTPException(status_code=404, detail="Audio clip not found.")

    file_path = Path(file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio clip not found.")

    return FileResponse(
        path=file_path,
        media_type=meta.get("contentType", "application/octet-stream"),
        filename=meta.get("filename", file_path.name),
    )


def get_player_audio_archive(game_id: str, target_player_id: str) -> FileResponse:
    game = _get_game_or_404(game_id)
    target = game.players.get(target_player_id)
    if not target:
        raise HTTPException(status_code=404, detail="Player not found.")

    clip_ids = [m.get("clipId") for m in game.audio_clips if m.get("playerId") == target_player_id]
    files: List[Path] = []
    for cid in clip_ids:
        p = game.audio_files.get(cid)
        if p:
            path_obj = Path(p)
            if path_obj.exists():
                files.append(path_obj)

    if not files:
        raise HTTPException(status_code=404, detail="No audio clips for this player.")

    audio_dir = AUDIO_STORAGE_DIR / game.id
    audio_dir.mkdir(parents=True, exist_ok=True)
    safe_name = target.name.replace(' ', '_') or 'player'
    zip_path = audio_dir / f"{safe_name}-clips.zip"

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.name)

    return FileResponse(path=zip_path, media_type="application/zip", filename=zip_path.name)


def post_chat_message(game_id: str, player_id: str, text: str) -> GameStateResponse:
    game = _get_game_or_404(game_id)
    player = _get_player(game, player_id)
    trimmed = (text or "").strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    entry = {
        "messageId": str(uuid.uuid4()),
        "playerId": player.id,
        "name": player.name,
        "text": trimmed,
        "timestamp": time.time(),
    }
    game.chat_messages.append(entry)
    if len(game.chat_messages) > 100:
        game.chat_messages = game.chat_messages[-100:]

    return _build_game_state_response(game)


def reveal_game(game_id: str, player_id: str) -> GameStateResponse:
    game = _get_game_or_404(game_id)
    host = _get_player(game, player_id)

    if not host.is_host:
        raise HTTPException(status_code=403, detail="Only the host can reveal players.")

    if game.status == "waiting":
        raise HTTPException(status_code=400, detail="Game has not started.")

    if game.status != "ended":
        _declare_victory(game, "host", "The host ended the night early. Roles are now visible.")

    return _build_game_state_response(game)


def delete_game(game_id: str, player_id: str) -> Dict[str, str]:
    game = _get_game_or_404(game_id)
    host = _get_player(game, player_id)

    if not host.is_host:
        raise HTTPException(status_code=403, detail="Only the host can delete the game.")

    games_by_id.pop(game_id, None)
    games_by_code.pop(game.join_code, None)
    audio_dir = AUDIO_STORAGE_DIR / game.id
    if audio_dir.exists():
        shutil.rmtree(audio_dir, ignore_errors=True)
    return {"status": "deleted"}