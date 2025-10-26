from typing import Optional

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.app.game import (
    AISpeakResponse,
    AudioUploadResponse,
    GameCreationResponse,
    GameStateResponse,
    PlayerSessionResponse,
    add_ai_player,
    advance_night,
    advance_turn,
    create_game,
    delete_game,
    detective_select,
    find_game_by_code,
    finish_round,
    get_audio_clip,
    get_game_state,
    get_player_assignment,
    get_player_audio_archive,
    trigger_ai_votes,
    join_game,
    post_chat_message,
    remove_player,
    resolve_night,
    reveal_game,
    save_audio_from_server,
    start_game,
    submit_vote,
    trigger_speech,
    wolf_vote,
    get_debug_info,
    set_debug_enabled,
    DebugInfo,
)

class ToggleDebugRequest(BaseModel):
    playerId: str
    enabled: bool


class CreateGameRequest(BaseModel):
    hostName: str


class JoinGameRequest(BaseModel):
    playerName: str


class StartGameRequest(BaseModel):
    playerId: str
    wordSetId: Optional[str] = None


class AddAIPlayerRequest(BaseModel):
    playerId: str
    aiName: Optional[str] = None


class PlayerActionRequest(BaseModel):
    playerId: str


class RemovePlayerRequest(PlayerActionRequest):
    targetPlayerId: str


class VoteRequest(BaseModel):
    playerId: str
    targetPlayerId: Optional[str] = None


class WolfKillRequest(BaseModel):
    playerId: str
    targetPlayerId: str


class DetectRequest(BaseModel):
    playerId: str
    targetPlayerId: str


class SpeechRequest(BaseModel):
    playerId: str
    speakerPlayerId: Optional[str] = None


class ChatRequest(BaseModel):
    playerId: str
    text: str


class RevealRequest(BaseModel):
    playerId: str


app = FastAPI(title="Moonlit Mafia")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/games", response_model=GameCreationResponse)
def create_game_endpoint(request: CreateGameRequest) -> GameCreationResponse:
    return create_game(request.hostName)


@app.post("/games/by-code/{join_code}", response_model=GameStateResponse)
def find_game_by_code_endpoint(join_code: str) -> GameStateResponse:
    return find_game_by_code(join_code)


@app.post("/games/{game_id}/join", response_model=PlayerSessionResponse)
def join_game_endpoint(game_id: str, request: JoinGameRequest) -> PlayerSessionResponse:
    return join_game(game_id, request.playerName)


@app.post("/games/{game_id}/ai", response_model=GameStateResponse)
def add_ai_player_endpoint(game_id: str, request: AddAIPlayerRequest) -> GameStateResponse:
    return add_ai_player(game_id, request.playerId, request.aiName)


@app.post("/games/{game_id}/players/remove", response_model=GameStateResponse)
def remove_player_endpoint(game_id: str, request: RemovePlayerRequest) -> GameStateResponse:
    return remove_player(game_id, request.playerId, request.targetPlayerId)


@app.post("/games/{game_id}/start", response_model=GameStateResponse)
def start_game_endpoint(game_id: str, request: StartGameRequest) -> GameStateResponse:
    return start_game(game_id, request.playerId, request.wordSetId)


@app.post("/games/{game_id}/turns/next", response_model=GameStateResponse)
def advance_turn_endpoint(game_id: str, request: PlayerActionRequest) -> GameStateResponse:
    return advance_turn(game_id, request.playerId)


@app.post("/games/{game_id}/night/wolf", response_model=GameStateResponse)
def wolf_vote_endpoint(game_id: str, request: WolfKillRequest) -> GameStateResponse:
    return wolf_vote(game_id, request.playerId, request.targetPlayerId)


@app.post("/games/{game_id}/night/detect", response_model=GameStateResponse)
def detective_select_endpoint(game_id: str, request: DetectRequest) -> GameStateResponse:
    return detective_select(game_id, request.playerId, request.targetPlayerId)


@app.post("/games/{game_id}/night/advance", response_model=GameStateResponse)
def advance_night_endpoint(game_id: str, request: PlayerActionRequest) -> GameStateResponse:
    return advance_night(game_id, request.playerId)


@app.post("/games/{game_id}/night/resolve", response_model=GameStateResponse)
def resolve_night_endpoint(game_id: str, request: PlayerActionRequest) -> GameStateResponse:
    return resolve_night(game_id, request.playerId)


@app.post("/games/{game_id}/turns/speech", response_model=AISpeakResponse)
def trigger_speech_endpoint(game_id: str, request: SpeechRequest) -> AISpeakResponse:
    return trigger_speech(game_id, request.playerId, request.speakerPlayerId)


@app.post("/games/{game_id}/round/finish", response_model=GameStateResponse)
def finish_round_endpoint(game_id: str, request: PlayerActionRequest) -> GameStateResponse:
    return finish_round(game_id, request.playerId)


@app.post("/games/{game_id}/vote", response_model=GameStateResponse)
def vote_player_endpoint(game_id: str, request: VoteRequest) -> GameStateResponse:
    return submit_vote(game_id, request.playerId, request.targetPlayerId)


@app.post("/games/{game_id}/vote/ai", response_model=GameStateResponse)
def trigger_ai_votes_endpoint(game_id: str, request: PlayerActionRequest) -> GameStateResponse:
    return trigger_ai_votes(game_id, request.playerId)


@app.get("/games/{game_id}/state", response_model=GameStateResponse)
def get_game_state_endpoint(game_id: str) -> GameStateResponse:
    return get_game_state(game_id)


@app.get("/games/{game_id}/players/{player_id}", response_model=PlayerSessionResponse)
def get_player_assignment_endpoint(game_id: str, player_id: str) -> PlayerSessionResponse:
    return get_player_assignment(game_id, player_id)


@app.post("/games/{game_id}/players/{player_id}/audio", response_model=AudioUploadResponse)
async def save_audio_from_server_endpoint(
    game_id: str,
    player_id: str,
    file: UploadFile = File(...),
) -> AudioUploadResponse:
    return await save_audio_from_server(game_id, player_id, file)


@app.get("/games/{game_id}/audio/{clip_id}")
def get_audio_clip_endpoint(game_id: str, clip_id: str) -> FileResponse:
    return get_audio_clip(game_id, clip_id)


@app.post("/games/{game_id}/chat", response_model=GameStateResponse)
def post_chat_message_endpoint(game_id: str, request: ChatRequest) -> GameStateResponse:
    return post_chat_message(game_id, request.playerId, request.text)


@app.post("/games/{game_id}/reveal", response_model=GameStateResponse)
def reveal_game_endpoint(game_id: str, request: RevealRequest) -> GameStateResponse:
    return reveal_game(game_id, request.playerId)


@app.delete("/games/{game_id}", response_model=dict)
def delete_game_endpoint(game_id: str, request: PlayerActionRequest) -> dict:
    return delete_game(game_id, request.playerId)


@app.get("/games/{game_id}/players/{player_id}/audio/archive")
def get_player_audio_archive_endpoint(game_id: str, player_id: str) -> FileResponse:
    return get_player_audio_archive(game_id, player_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)