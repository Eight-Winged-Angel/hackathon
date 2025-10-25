const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://100.67.145.80:8000";

async function request(path, options = {}) {
  const isFormData = options?.body instanceof FormData;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = body.detail || response.statusText || "Request failed";
    throw new Error(message);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export const api = {
  createGame(hostName) {
    return request("/games", {
      method: "POST",
      body: JSON.stringify({ hostName }),
    });
  },

  // Trigger backend AI votes for all alive AI players who haven't voted
  triggerAiVotes(gameId, hostPlayerId) {
    return request(`/games/${gameId}/vote/ai`, {
      method: "POST",
      body: JSON.stringify({ playerId: hostPlayerId }),
    });
  },

  findGameByCode(joinCode) {
    return request(`/games/by-code/${encodeURIComponent(joinCode)}`, {
      method: "POST",
    });
  },

  joinGame(gameId, playerName) {
    return request(`/games/${gameId}/join`, {
      method: "POST",
      body: JSON.stringify({ playerName }),
    });
  },

  startGame(gameId, playerId) {
    return request(`/games/${gameId}/start`, {
      method: "POST",
      body: JSON.stringify({ playerId }),
    });
  },

  getGameState(gameId) {
    return request(`/games/${gameId}/state`, {
      method: "GET",
    });
  },

  getPlayerAssignment(gameId, playerId) {
    return request(`/games/${gameId}/players/${playerId}`, {
      method: "GET",
    });
  },

  endGame(gameId, playerId) {
    return request(`/games/${gameId}/reveal`, {
      method: "POST",
      body: JSON.stringify({ playerId }),
    });
  },

  advanceNight(gameId, playerId) {
    return request(`/games/${gameId}/night/advance`, {
      method: "POST",
      body: JSON.stringify({ playerId }),
    });
  },

  addAiPlayer(gameId, playerId, aiName) {
    return request(`/games/${gameId}/ai`, {
      method: "POST",
      body: JSON.stringify({
        playerId,
        aiName: aiName || undefined,
      }),
    });
  },

  // ---------- NEW: Remove player (host-only, lobby) ----------
  removePlayer(gameId, hostPlayerId, targetPlayerId) {
    return request(`/games/${gameId}/players/remove`, {
      method: "POST",
      body: JSON.stringify({
        playerId: hostPlayerId,
        targetPlayerId,
      }),
    });
  },

  // ---------- NEW: Voting APIs ----------
  // Cast a vote to remove targetPlayerId
  vote(gameId, voterPlayerId, targetPlayerId) {
    return request(`/games/${gameId}/vote`, {
      method: "POST",
      body: JSON.stringify({
        playerId: voterPlayerId,
        targetPlayerId: targetPlayerId ?? null,
      }),
    });
  },

  advanceTurn(gameId, playerId) {
    return request(`/games/${gameId}/turns/next`, {
      method: "POST",
      body: JSON.stringify({ playerId }),
    });
  },

  finishRound(gameId, playerId) {
    return request(`/games/${gameId}/round/finish`, {
      method: "POST",
      body: JSON.stringify({ playerId }),
    });
  },

  cueSpeech(gameId, playerId, speakerPlayerId) {
    return request(`/games/${gameId}/turns/speech`, {
      method: "POST",
      body: JSON.stringify({
        playerId,
        speakerPlayerId: speakerPlayerId || undefined,
      }),
    });
  },

  submitWerewolfTarget(gameId, playerId, targetPlayerId) {
    return request(`/games/${gameId}/night/wolf`, {
      method: "POST",
      body: JSON.stringify({
        playerId,
        targetPlayerId,
      }),
    });
  },

  submitDetectiveTarget(gameId, playerId, targetPlayerId) {
    return request(`/games/${gameId}/night/detect`, {
      method: "POST",
      body: JSON.stringify({
        playerId,
        targetPlayerId,
      }),
    });
  },

  uploadAudio(gameId, playerId, blob) {
    const formData = new FormData();
    formData.append("file", blob, "speech.wav");
    return request(`/games/${gameId}/players/${playerId}/audio`, {
      method: "POST",
      body: formData,
    });
  },

  audioUrl(gameId, clipId) {
    return `${API_BASE_URL}/games/${gameId}/audio/${clipId}`;
  },

  postChat(gameId, playerId, text) {
    return request(`/games/${gameId}/chat`, {
      method: "POST",
      body: JSON.stringify({ playerId, text }),
    });
  },
};
