import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";

const STATUS_LABEL = {
  waiting: "Waiting for Players",
  in_progress: "Night Cycle",
  ended: "Game Complete",
};

const STATUS_COLOR = {
  waiting: "#38bdf8",
  in_progress: "#facc15",
  ended: "#34d399",
};

const NIGHT_STAGE_DETAILS = {
  wolves: {
    label: "Werewolves Hunt",
    hostPrompt: "Confirm the werewolf attack before advancing.",
    playerPrompt: "Werewolves are selecting a target.",
    buttonLabel: "Advance Night • Werewolves",
  },
  detective: {
    label: "Detective Investigates",
    hostPrompt: "The detective investigates.",
    playerPrompt: "Detective insight is being resolved.",
    buttonLabel: "Advance Night • Detective",
  },
  summary: {
    label: "Dawn Approaches",
    hostPrompt: "Lock in the night outcomes to begin the day.",
    playerPrompt: "Waiting for the host to usher in dawn.",
    buttonLabel: "Advance Night • Dawn",
  },
};

function StatusPill({ status }) {
  if (!status) {
    return null;
  }
  const label = STATUS_LABEL[status] || status;
  return (
    <span
      className="status-pill"
      style={{ backgroundColor: `${STATUS_COLOR[status]}22`, color: STATUS_COLOR[status] }}
    >
      {label}
    </span>
  );
}

// === CHANGED: voting helpers ===
function getAlivePlayers(gameState) {
  return (gameState?.players || []).filter((p) => p.isAlive);
}

/**
 * votes: array like [{ voterId, targetPlayerId|null }]
 * players: full players array
 * returns {
 *   byVoter: Map<voterId, targetId|null>,
 *   counts: Map<targetId|'__abstain__', number>,
 *   top: { id: string|null, count: number, isTie: boolean }
 * }
 */
function tallyVotes(votes, players) {
  const byVoter = new Map();
  const counts = new Map();
  const nameOf = (id) => players.find((p) => p.playerId === id)?.name || "Unknown";

  for (const v of votes || []) {
    if (!v?.voterId) continue;
    const tgt = v.targetPlayerId ?? "__abstain__";
    byVoter.set(v.voterId, v.targetPlayerId ?? null);
    counts.set(tgt, (counts.get(tgt) || 0) + 1);
  }

  // find top bucket (including abstain)
  let topId = null;
  let topCount = 0;
  let secondCount = 0;
  for (const [k, c] of counts.entries()) {
    if (c > topCount) {
      secondCount = topCount;
      topCount = c;
      topId = k;
    } else if (c > secondCount) {
      secondCount = c;
    }
  }
  const isTie = topCount > 0 && secondCount === topCount;

  return {
    byVoter,
    counts,
    top: { id: topId === "__abstain__" ? null : topId, count: topCount, isTie },
    nameOf,
  };
}
// === /CHANGED ===

// AI votes are triggered via backend endpoint; no client-side target selection here.

export default function App() {
  const [phase, setPhase] = useState("landing");
  const [gameState, setGameState] = useState(null);
  const [playerSession, setPlayerSession] = useState(null);
  const [hostPlayerId, setHostPlayerId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [aiNameInput, setAiNameInput] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [recordStatus, setRecordStatus] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [audioBusy, setAudioBusy] = useState(false);
  const [chatText, setChatText] = useState("");
  const [turnBusy, setTurnBusy] = useState(false);
  const [finishBusy, setFinishBusy] = useState(false);
  const [nightBusy, setNightBusy] = useState(false);
  const [kickBusy, setKickBusy] = useState(null);
  const [wolfTarget, setWolfTarget] = useState("");
  const [detectiveTarget, setDetectiveTarget] = useState("");
  const [wolfActionBusy, setWolfActionBusy] = useState(false);
  const [detectActionBusy, setDetectActionBusy] = useState(false);
  const [wolfActionDone, setWolfActionDone] = useState(false);
  const [detectActionDone, setDetectActionDone] = useState(false);

  // === CHANGED: simple AI audio playback state (no transcript plumbing) ===
  const [aiCuedThisTurn, setAiCuedThisTurn] = useState(false);
  const [aiAudioPlaying, setAiAudioPlaying] = useState(false);
  const aiAudioRef = useRef(null);
  // === /CHANGED ===

  // AI voting is triggered via backend; no local per-day auto logic kept.

  const [hostForm, setHostForm] = useState({ hostName: "" });
  const [joinForm, setJoinForm] = useState({ code: "", name: "" });

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  const gameId = gameState?.gameId || null;
  const playerId = playerSession?.playerId || null;
  const nightStage = gameState?.nightStage || null;
  const nightStageInfo = nightStage ? NIGHT_STAGE_DETAILS[nightStage] || null : null;

  useEffect(() => {
    return () => {
      const recorder = mediaRecorderRef.current;
      if (recorder) {
        try {
          if (recorder.state !== "inactive") {
            recorder.stop();
          }
        } catch {}
        const tracks = recorder.stream?.getTracks?.() || [];
        tracks.forEach((track) => track.stop());
        mediaRecorderRef.current = null;
        audioChunksRef.current = [];
      }
      if (aiAudioRef.current) {
        try {
          aiAudioRef.current.pause();
        } catch {}
        aiAudioRef.current = null;
      }
    };
  }, []);

  // (Removed) Previously auto-triggered AI votes on the client; now handled via backend endpoint.

  const refreshGameState = useCallback(async () => {
    if (!gameId) return;
    try {
      const latest = await api.getGameState(gameId);
      setGameState((previous) => (!previous ? latest : { ...previous, ...latest }));
    } catch (err) {
      console.error("Failed to refresh game state", err);
    }
  }, [gameId]);

  const refreshPlayer = useCallback(async () => {
    if (!gameId || !playerId) return;
    try {
      const session = await api.getPlayerAssignment(gameId, playerId);
      setPlayerSession(session);
    } catch (err) {
      console.error("Failed to refresh player state", err);
    }
  }, [gameId, playerId]);

  useEffect(() => {
    if (!gameId || !playerId) return;
    const interval = setInterval(() => {
      refreshGameState();
      refreshPlayer();
    }, 3000);
    return () => clearInterval(interval);
  }, [gameId, playerId, refreshGameState, refreshPlayer]);

  useEffect(() => {
    if (!gameId) return;
    refreshGameState();
    if (playerId) refreshPlayer();
  }, [gameId, playerId, refreshGameState, refreshPlayer]);

  const isHost = useMemo(() => {
    if (!playerId || !gameState?.players) return false;
    return Boolean(gameState.players.find((p) => p.playerId === playerId && p.isHost));
  }, [playerId, gameState]);

  const currentTurn = useMemo(() => {
    if (!gameState?.currentTurnPlayerId) return null;
    return gameState.players?.find((p) => p.playerId === gameState.currentTurnPlayerId) || null;
  }, [gameState]);

  // === CHANGED: whenever the turn changes, reset cue + audio-playing flags ===
  useEffect(() => {
    setAiCuedThisTurn(false);
    setAiAudioPlaying(false);
    if (aiAudioRef.current) {
      try {
        aiAudioRef.current.pause();
      } catch {}
      aiAudioRef.current = null;
    }
  }, [gameState?.currentTurnPlayerId, gameState?.workflowStage]);
  // === /CHANGED ===

  useEffect(() => {
    if (nightStage !== "wolves") {
      setWolfTarget("");
      setWolfActionBusy(false);
    }
    if (nightStage !== "detective") {
      setDetectiveTarget("");
      setDetectActionBusy(false);
    }
  }, [nightStage]);

  const roleBanner = useMemo(() => {
    if (!playerSession || !gameState) return null;
    if (gameState.status === "waiting") return "Roles will appear once the host begins the night.";
    if (!playerSession.role) return null;
    const title =
      playerSession.role === "werewolf"
        ? "You are a werewolf. Blend in during the day."
        : playerSession.role === "detective"
        ? "You are the detective. Investigate quietly."
        : "You are a villager. Trust your instincts.";
    return `${title} ${playerSession.roleSummary || ""}`.trim();
  }, [playerSession, gameState]);

  const handleCreateGame = async (event) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const trimmed = hostForm.hostName.trim();
      if (!trimmed) throw new Error("Please enter a host name.");
      const created = await api.createGame(trimmed);
      setGameState(created);
      setHostPlayerId(created.hostPlayerId);
      const session = await api.getPlayerAssignment(created.gameId, created.hostPlayerId);
      setPlayerSession(session);
      setPhase("host");
    } catch (err) {
      setError(err.message || "Could not create game right now.");
    } finally {
      setLoading(false);
    }
  };

  const handleJoinGame = async (event) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const trimmedName = joinForm.name.trim();
      const code = joinForm.code.trim().toUpperCase();
      if (!code) throw new Error("Enter a join code.");
      if (!trimmedName) throw new Error("Enter a player name.");

      const game = await api.findGameByCode(code);
      setHostPlayerId(game.players.find((p) => p.isHost)?.playerId || null);

      const session = await api.joinGame(game.gameId, trimmedName);
      const updated = await api.getGameState(game.gameId);
      setGameState(updated);
      setPlayerSession(session);
      setPhase("player");
    } catch (err) {
      setError(err.message || "Could not join the game.");
    } finally {
      setLoading(false);
    }
  };

  const handleStartGame = async () => {
    if (!gameId || !playerId) return;
    setError("");
    setLoading(true);
    try {
      const response = await api.startGame(gameId, playerId);
      setGameState((previous) => ({ ...(previous || {}), ...response }));
      await refreshPlayer();
    } catch (err) {
      setError(err.message || "Unable to start the game.");
    } finally {
      setLoading(false);
    }
  };

  const handleAddAiPlayer = async () => {
    if (!gameId || !playerId) return;
    setError("");
    setAiBusy(true);
    try {
      const name = aiNameInput.trim();
      const response = await api.addAiPlayer(gameId, playerId, name);
      setGameState((previous) => ({ ...(previous || {}), ...response }));
    } catch (err) {
      setError(err?.message || "Unable to add an AI player right now.");
    } finally {
      setAiBusy(false);
    }
  };

  const handleRemovePlayer = async (targetPlayerId) => {
    if (!isHost || !gameId || !playerId) return;
    setError("");
    setKickBusy(targetPlayerId);
    try {
      const resp = await api.removePlayer(gameId, playerId, targetPlayerId);
      setGameState((prev) => ({ ...(prev || {}), ...resp }));
      await refreshGameState();
    } catch (err) {
      setError(err?.message || "Unable to remove player.");
    } finally {
      setKickBusy(null);
    }
  };

  // === CHANGED: play the WAV that AI just generated; block Next until finished ===
  const playAiClip = (clip) => {
    if (!clip?.clipId || !gameId) return;
    const url = api.audioUrl(gameId, clip.clipId);
    try {
      if (aiAudioRef.current) {
        try {
          aiAudioRef.current.pause();
        } catch {}
        aiAudioRef.current = null;
      }
      const audio = new Audio(url);
      aiAudioRef.current = audio;
      setAiAudioPlaying(true);
      audio.onended = () => {
        setAiAudioPlaying(false);
      };
      audio.onerror = () => {
        setAiAudioPlaying(false);
      };
      audio.play().catch(() => {
        setAiAudioPlaying(false);
      });
    } catch {
      setAiAudioPlaying(false);
    }
  };

  const handleStartSpeak = async () => {
    if (!isHost || !gameId || !playerId) return;
    if (!gameState || gameState.workflowStage !== "discussion") return;
    const speaker =
      gameState.players?.find((p) => p.playerId === gameState.currentTurnPlayerId) || null;
    if (!speaker || !speaker.isAI || !speaker.isAlive) return;

    setAiBusy(true);
    setError("");
    try {
      const response = await api.cueSpeech(gameId, playerId, speaker.playerId);
      if (response?.audioClip) {
        setAiCuedThisTurn(true);
        playAiClip(response.audioClip); // audio playing blocks Next
      } else {
        setAiCuedThisTurn(true);
      }
      await refreshGameState();
    } catch (err) {
      setError(err?.message || "Failed to cue AI speech.");
    } finally {
      setAiBusy(false);
    }
  };
  // === /CHANGED ===

  // === CHANGED: vote handler (UI consistent with turn entries) ===
  const [voteBusy, setVoteBusy] = useState(false);
  const [aiVoteBusy, setAiVoteBusy] = useState(false);
  const handleVote = async (targetPlayerId /* string | null for abstain */) => {
    if (!gameId || !playerId) return;
    setError("");
    setVoteBusy(true);
    try {
      const resp = await api.vote(gameId, playerId, targetPlayerId || null);
      setGameState((prev) => ({ ...(prev || {}), ...resp }));
      await refreshGameState();
    } catch (err) {
      setError(err?.message || "Unable to submit vote.");
    } finally {
      setVoteBusy(false);
    }
  };
  // === /CHANGED ===

  // Host: trigger backend AI votes
  const handleTriggerAiVotes = async () => {
    if (!isHost || !gameId || !playerId) return;
    setError("");
    setAiVoteBusy(true);
    try {
      const resp = await api.triggerAiVotes(gameId, playerId);
      setGameState((prev) => ({ ...(prev || {}), ...resp }));
      await refreshGameState();
    } catch (err) {
      setError(err?.message || "Unable to trigger AI votes.");
    } finally {
      setAiVoteBusy(false);
    }
  };

  const handleSubmitWolfTarget = async () => {
    if (!gameId || !playerId || !wolfTarget) return;
    if (gameState?.workflowStage !== "night" || gameState?.nightStage !== "wolves") return;
    setError("");
    setWolfActionBusy(true);
    try {
      const resp = await api.submitWerewolfTarget(gameId, playerId, wolfTarget);
      setGameState((prev) => ({ ...(prev || {}), ...resp }));
      await refreshGameState();
      setWolfActionDone(true);
    } catch (err) {
      setError(err?.message || "Unable to set a night target.");
    } finally {
      setWolfActionBusy(false);
    }
  };

  const handleSubmitDetectiveTarget = async () => {
    if (!gameId || !playerId || !detectiveTarget) return;
    if (gameState?.workflowStage !== "night" || gameState?.nightStage !== "detective") return;
    setError("");
    setDetectActionBusy(true);
    try {
      const resp = await api.submitDetectiveTarget(gameId, playerId, detectiveTarget);
      setGameState((prev) => ({ ...(prev || {}), ...resp }));
      await refreshGameState();
      setDetectActionDone(true);
    } catch (err) {
      setError(err?.message || "Unable to submit inspection.");
    } finally {
      setDetectActionBusy(false);
    }
  };

  // Reset action-done flags when night stage/day changes
  useEffect(() => {
    if (!gameState) return;
    // Any time the night stage or workflow stage flips, clear per-stage done flags
    if (gameState.workflowStage !== "night") {
      setWolfActionDone(false);
      setDetectActionDone(false);
    } else {
      // On each stage entry, reset the corresponding flag
      if (gameState.nightStage === "wolves") {
        setWolfActionDone(false);
      }
      if (gameState.nightStage === "detective") {
        setDetectActionDone(false);
      }
    }
  }, [gameState?.workflowStage, gameState?.nightStage, gameState?.roundNumber]);

  const handleToggleRecording = async () => {
    if (!gameId || !playerId) {
      setRecordStatus("Join a game before recording.");
      return;
    }

    const activeRecorder = mediaRecorderRef.current;
    if (isRecording && activeRecorder) {
      setRecordStatus("Wrapping up recording...");
      setIsRecording(false);
      setAudioBusy(true);
      try {
        activeRecorder.stop();
      } catch (err) {
        console.error("stop recorder", err);
        setAudioBusy(false);
      }
      return;
    }

    if (audioBusy) return;

    if (!navigator.mediaDevices?.getUserMedia) {
      setRecordStatus("Audio recording is not supported in this browser.");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];
      setRecordStatus("Recording... tap again to upload.");

      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size) {
          audioChunksRef.current.push(event.data);
        }
      };

      // Helper: transcode recorded Blob to 16-bit PCM WAV using WebAudio
      const blobToArrayBuffer = (b) => new Promise((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => res(fr.result);
        fr.onerror = rej;
        fr.readAsArrayBuffer(b);
      });

      const audioBufferToWav = (audioBuffer) => {
        const numOfChan = audioBuffer.numberOfChannels || 1;
        const sampleRate = audioBuffer.sampleRate || 48000;
        const samples = audioBuffer.length;
        const bytesPerSample = 2; // 16-bit PCM
        const blockAlign = numOfChan * bytesPerSample;
        const dataSize = samples * blockAlign;
        const buffer = new ArrayBuffer(44 + dataSize);
        const view = new DataView(buffer);

        const writeString = (offset, str) => {
          for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
        };
        let offset = 0;
        // RIFF header
        writeString(offset, 'RIFF'); offset += 4;
        view.setUint32(offset, 36 + dataSize, true); offset += 4; // file size - 8
        writeString(offset, 'WAVE'); offset += 4;
        // fmt chunk
        writeString(offset, 'fmt '); offset += 4;
        view.setUint32(offset, 16, true); offset += 4; // PCM chunk size
        view.setUint16(offset, 1, true); offset += 2; // format = PCM
        view.setUint16(offset, numOfChan, true); offset += 2;
        view.setUint32(offset, sampleRate, true); offset += 4;
        view.setUint32(offset, sampleRate * blockAlign, true); offset += 4; // byte rate
        view.setUint16(offset, blockAlign, true); offset += 2;
        view.setUint16(offset, bytesPerSample * 8, true); offset += 2; // bits per sample
        // data chunk
        writeString(offset, 'data'); offset += 4;
        view.setUint32(offset, dataSize, true); offset += 4;

        // write interleaved samples
        const channels = [];
        for (let ch = 0; ch < numOfChan; ch++) channels.push(audioBuffer.getChannelData(ch));
        let idx = 0;
        for (let i = 0; i < samples; i++) {
          for (let ch = 0; ch < numOfChan; ch++) {
            let s = Math.max(-1, Math.min(1, channels[ch][i] || 0));
            view.setInt16(offset + idx, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
            idx += 2;
          }
        }
        return new Blob([buffer], { type: 'audio/wav' });
      };

      const transcodeToWav = async (blob) => {
        try {
          const arrayBuffer = await blobToArrayBuffer(blob);
          const ctx = new (window.OfflineAudioContext || window.webkitOfflineAudioContext)(1, 1, 48000);
          // Use a regular AudioContext for decoding to be widely supported
          const ac = new (window.AudioContext || window.webkitAudioContext)();
          const decoded = await ac.decodeAudioData(arrayBuffer.slice(0));
          const wavBlob = audioBufferToWav(decoded);
          try { ac.close(); } catch {}
          return wavBlob;
        } catch (e) {
          // Fallback: if decode fails, return original (may still be wav)
          return blob;
        }
      };

      mediaRecorder.onstop = async () => {
        try {
          const tracks = mediaRecorder.stream?.getTracks?.() || [];
          tracks.forEach((track) => track.stop());
          setIsRecording(false);

          if (!audioChunksRef.current.length) {
            setRecordStatus("No audio captured.");
            setAudioBusy(false);
            return;
          }

          const mimeType = mediaRecorder.mimeType || "audio/webm";
          const rawBlob = new Blob(audioChunksRef.current, { type: mimeType });
          setRecordStatus("Transcoding to WAV...");
          const wavBlob = await transcodeToWav(rawBlob);
          setRecordStatus("Uploading WAV...");
          await api.uploadAudio(gameId, playerId, wavBlob);
          setRecordStatus("Clip shared with the group.");
          await refreshGameState();
        } catch (err) {
          setRecordStatus(err?.message || "Failed to upload audio.");
        } finally {
          audioChunksRef.current = [];
          mediaRecorderRef.current = null;
          setAudioBusy(false);
        }
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      setRecordStatus(err?.message || "Unable to access microphone.");
    }
  };

  const handleAdvanceTurn = async () => {
    if (!isHost || !gameId || !playerId) return;
    setError("");
    setTurnBusy(true);
    try {
      const response = await api.advanceTurn(gameId, playerId);
      setGameState((previous) => ({ ...(previous || {}), ...response }));
    } catch (err) {
      setError(err?.message || "Unable to advance to the next player.");
    } finally {
      setTurnBusy(false);
    }
  };

  const handleFinishRound = async () => {
    if (!isHost || !gameId || !playerId) return;
    setError("");
    setFinishBusy(true);
    try {
      const response = await api.finishRound(gameId, playerId);
      setGameState((previous) => ({ ...(previous || {}), ...response }));
    } catch (err) {
      setError(err?.message || "Unable to finish the round.");
    } finally {
      setFinishBusy(false);
    }
  };

  const handleAdvanceNightStage = async () => {
    if (!isHost || !gameId || !playerId) return;
    setError("");
    setNightBusy(true);
    try {
      const response = await api.advanceNight(gameId, playerId);
      setGameState((previous) => ({ ...(previous || {}), ...response }));
    } catch (err) {
      setError(err?.message || "Unable to advance the night.");
    } finally {
      setNightBusy(false);
    }
  };

  const handleSendChat = async (event) => {
    event.preventDefault();
    if (!gameId || !playerId) return;
    const text = chatText.trim();
    if (!text) return;
    try {
      await api.postChat(gameId, playerId, text);
      setChatText("");
      await refreshGameState();
    } catch (err) {
      setError(err?.message || "Failed to send message.");
    }
  };

  const handleReveal = async () => {
    if (!gameId || !playerId) return;
    setError("");
    setLoading(true);
    try {
      const response = await api.endGame(gameId, playerId);
      setGameState((previous) => ({ ...(previous || {}), ...response }));
      await refreshPlayer();
      await refreshGameState();
    } catch (err) {
      setError(err.message || "Unable to end the game right now.");
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setPhase("landing");
    setGameState(null);
    setPlayerSession(null);
    setHostPlayerId(null);
    setError("");
    setHostForm({ hostName: "" });
    setJoinForm({ code: "", name: "" });
    setAiNameInput("");
    setAiBusy(false);
    setRecordStatus("");
    setIsRecording(false);
    setAudioBusy(false);
    setTurnBusy(false);
    setFinishBusy(false);
    setNightBusy(false);
    setAiCuedThisTurn(false);
    setAiAudioPlaying(false);
    setWolfTarget("");
    setDetectiveTarget("");
    setWolfActionBusy(false);
    setDetectActionBusy(false);
    if (aiAudioRef.current) {
      try {
        aiAudioRef.current.pause();
      } catch {}
      aiAudioRef.current = null;
    }
    const recorder = mediaRecorderRef.current;
    if (recorder) {
      try {
        if (recorder.state !== "inactive") {
          recorder.stop();
        }
      } catch {}
      const tracks = recorder.stream?.getTracks?.() || [];
      tracks.forEach((track) => track.stop());
    }
    mediaRecorderRef.current = null;
    audioChunksRef.current = [];
  };

  // === CHANGED: apply votes & end day ===
  const [applyBusy, setApplyBusy] = useState(false);

  const handleApplyVotes = async () => {
    if (!isHost || !gameId || !playerId) return;
    setError("");
    setApplyBusy(true);
    try {
      if (typeof api.applyVotes === "function") {
        const resp = await api.applyVotes(gameId, playerId);
        setGameState((prev) => ({ ...(prev || {}), ...resp }));
      } else {
        const resp = await api.finishRound(gameId, playerId);
        setGameState((prev) => ({ ...(prev || {}), ...resp }));
      }
      await refreshGameState();
    } catch (err) {
      setError(err?.message || "Unable to apply votes.");
    } finally {
      setApplyBusy(false);
    }
  };
  // === /CHANGED ===

  const renderLanding = () => (
    <div className="actions">
      <div className="card">
        <h2>Host a New Game</h2>
        <p>Spin up a Moonlit Mafia lobby, share the join code, and guide each night/day cycle.</p>
        <form onSubmit={handleCreateGame}>
          <label htmlFor="hostName">Host Name</label>
          <input
            id="hostName"
            autoComplete="off"
            value={hostForm.hostName}
            onChange={(event) => setHostForm({ hostName: event.target.value })}
            placeholder="Enter your name"
          />
          <button type="submit" style={{ marginTop: "1rem" }} disabled={loading}>
            {loading ? "Creating..." : "Create Game"}
          </button>
        </form>
      </div>
      <div className="card">
        <h2>Join a Game</h2>
        <p>Enter the join code shared by the host to help the town survive.</p>
        <form onSubmit={handleJoinGame}>
          <label htmlFor="joinCode">Join Code</label>
          <input
            id="joinCode"
            value={joinForm.code}
            onChange={(event) => setJoinForm((prev) => ({ ...prev, code: event.target.value.toUpperCase() }))}
            placeholder="e.g. XJ7Q"
            autoComplete="off"
            maxLength={6}
          />
          <label htmlFor="playerName" style={{ marginTop: "0.75rem" }}>
            Your Name
          </label>
          <input
            id="playerName"
            value={joinForm.name}
            onChange={(event) => setJoinForm((prev) => ({ ...prev, name: event.target.value }))}
            placeholder="Enter your name"
            autoComplete="off"
          />
          <button type="submit" style={{ marginTop: "1rem" }} disabled={loading}>
            {loading ? "Joining..." : "Join Game"}
          </button>
        </form>
      </div>
    </div>
  );

  const renderPlayers = () => {
    if (!gameState?.players?.length) {
      return <p>No players yet. Share the join code!</p>;
    }
    const playerCount = gameState.players?.length || 0;

    return (
      <>
        <div className="player-list">
          {gameState.players.map((player) => {
            const isCurrentTurn =
              gameState.workflowStage === "discussion" &&
              gameState.currentTurnPlayerId === player.playerId;
            const roleLabel = player.role
              ? player.role.charAt(0).toUpperCase() + player.role.slice(1)
              : null;

            return (
              <div
                className={`player-chip${isCurrentTurn ? " current" : ""}`}
                key={player.playerId}
                style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}
              >
                <span>{player.name}</span>
                {/* === CHANGED: tag yourself explicitly === */}
                {player.playerId === playerId && (
                  <span className="you-pill" style={{ fontSize: 12, padding: "0 6px", borderRadius: 8, background: "rgba(59,130,246,0.2)", color: "#93c5fd" }}>
                    You
                  </span>
                )}
                {/* === /CHANGED === */}
                <span style={{ opacity: 0.8 }}>
                  {(() => {
                    if (player.isHost) return "Host";
                    if (!player.isAlive) return roleLabel ? `${roleLabel} (revealed)` : "Eliminated";
                    if (player.isAI) return roleLabel && gameState.status === "ended" ? `AI ${roleLabel}` : "AI";
                    if (isCurrentTurn) return "Speaking";
                    if (gameState.status === "ended" && roleLabel) return roleLabel;
                    return player.isAlive ? "Player" : "Eliminated";
                  })()}
                </span>

                {/* Remove (kick) button: host-only, waiting phase, not for host */}
                {isHost && gameState.status === "waiting" && !player.isHost && (
                  <button
                    type="button"
                    onClick={() => handleRemovePlayer(player.playerId)}
                    disabled={kickBusy === player.playerId}
                    title="Remove player"
                    style={{
                      marginLeft: "auto",
                      padding: "0.15rem 0.5rem",
                      lineHeight: 1,
                      background: "rgba(248, 113, 113, 0.25)",
                      color: "#fecaca",
                    }}
                  >
                    {kickBusy === player.playerId ? "…" : "✕"}
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {isHost && gameState.status === "waiting" && (
          <div
            style={{
              marginTop: "0.75rem",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
              justifyContent: "space-between",
              flexWrap: "wrap",
            }}
          >
            <button type="button" onClick={handleAddAiPlayer} disabled={aiBusy}>
              {aiBusy ? "Adding..." : "+ Add AI"}
            </button>

            <button
              type="button"
              onClick={handleStartGame}
              disabled={loading || playerCount < 4}
              title={playerCount < 4 ? "Need at least 4 players" : "Deal roles and begin Night 1"}
              style={{ marginLeft: "auto" }}
            >
              {loading ? "Dealing..." : "Start First Night"}
            </button>
          </div>
        )}
      </>
    );
  };

  const renderTurnTracker = () => {
    if (!gameState) return null;

    const turnOrder = gameState.turnOrder || [];
    const stage = gameState.workflowStage;
    const isDiscussion = stage === "discussion";
    const isNight = stage === "night";
    const isEnded = gameState.status === "ended";

    const safeRoundNumber =
      typeof gameState.roundNumber === "number" && Number.isFinite(gameState.roundNumber)
        ? gameState.roundNumber
        : 0;
    const dayNumber = Math.max(safeRoundNumber || 1, 1);
    const nightNumber = Math.max(safeRoundNumber + 1, 1);

    const allSpoken =
      isDiscussion &&
      turnOrder.length > 0 &&
      gameState.currentTurnPosition === turnOrder.length &&
      aiCuedThisTurn &&
      !(turnBusy || aiAudioPlaying);

    const stageDescription = (() => {
      if (isNight) {
        const nightLabel = nightStageInfo?.label || "Night actions underway";
        return `Night ${nightNumber}: ${nightLabel}.`;
      }
      if (isDiscussion) {
        return `Day ${dayNumber} discussion in progress${
          currentTurn?.name ? ` - ${currentTurn.name} is speaking.` : "."
        }`;
      }
      if (isEnded) {
        return gameState.victoryMessage || "Game complete.";
      }
      return "Waiting for the host to begin the first night.";
    })();

    const isHostHere = isHost && !!turnOrder.length && isDiscussion;
    const isCurrentAI = Boolean(currentTurn?.isAI && currentTurn?.isAlive);
    const isCurrentPlayerSpeaking =
      isDiscussion && currentTurn && currentTurn.playerId === playerId && currentTurn.isAlive;

    const recordingLocked = audioBusy || isRecording;
    const canAdvance =
      isHostHere &&
      !allSpoken &&
      !turnBusy &&
      !aiAudioPlaying &&
      !recordingLocked &&
      (!isCurrentAI || aiCuedThisTurn);
    const canCloseDay = isHostHere && !finishBusy && !recordingLocked;

    const headerActions = [];

    if (isCurrentPlayerSpeaking) {
      headerActions.push(
        <button
          key="record"
          type="button"
          onClick={handleToggleRecording}
          disabled={audioBusy}
          aria-label={isRecording ? "Stop recording and upload" : "Record your turn"}
          title={isRecording ? "Stop recording and upload" : "Record your turn"}
          style={{
            width: 38,
            height: 38,
            borderRadius: "50%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: isRecording ? "rgba(248,113,113,0.3)" : "rgba(59,130,246,0.18)",
            color: isRecording ? "#fecaca" : "#bfdbfe",
            border: "1px solid rgba(59,130,246,0.35)",
            fontSize: "1.1rem",
          }}
        >
          {isRecording ? "..." : "🎙️"}
        </button>
      );
    }

    if (isHostHere && isCurrentAI) {
      headerActions.push(
        <button
          key="ai-speak"
          type="button"
          onClick={handleStartSpeak}
          disabled={aiBusy || aiAudioPlaying || aiCuedThisTurn || recordingLocked}
          aria-label="Cue AI speaker"
          title={
            aiCuedThisTurn
              ? "AI speaker already cued"
              : aiBusy || aiAudioPlaying
              ? "Wait for audio to finish"
              : "Cue the current AI speaker"
          }
          style={{
            width: 38,
            height: 38,
            borderRadius: "50%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(59,130,246,0.18)",
            color: "#bfdbfe",
            border: "1px solid rgba(59,130,246,0.35)",
            fontSize: "1.1rem",
          }}
        >
          {aiBusy || aiAudioPlaying ? "..." : "Cue"}
        </button>
      );
    }

    let speakingControls = null;
    if (isDiscussion && !allSpoken && isHost && turnOrder.length > 0) {
      speakingControls = (
        <div className="turn-controls" style={{ display: "flex", gap: "0.5rem" }}>
          <button
            type="button"
            onClick={handleAdvanceTurn}
            disabled={!canAdvance}
            title={
              recordingLocked
                ? "Finish recording before advancing"
                : aiAudioPlaying
                ? "Wait for audio to finish"
                : isCurrentAI && !aiCuedThisTurn
                ? "Cue the AI speaker before advancing"
                : "Advance to the next speaker"
            }
            style={{ marginRight: "auto" }}
          >
            {turnBusy || aiAudioPlaying ? "Working..." : "Next Speaker"}
          </button>

          <button
            type="button"
            onClick={handleFinishRound}
            disabled={!canCloseDay}
            style={{ background: "rgba(248,113,113,0.35)", color: "#fee2e2" }}
          >
            {finishBusy ? "Closing..." : "Close Day"}
          </button>
        </div>
      );
    }

    let votingControls = null;
    if (isDiscussion && allSpoken) {
      const alive = (gameState.players || []).filter((p) => p.isAlive);
      const aliveIds = new Set(alive.map((p) => p.playerId));
      const votes = gameState?.votes || [];
      const aliveVotes = votes.filter((v) => aliveIds.has(v.voterId));
      const voterIdsWhoVoted = new Set(aliveVotes.map((v) => v.voterId));
      const allVoted = voterIdsWhoVoted.size === alive.length;

      if (!allVoted) {
        const myVote = (gameState.votes || []).find((v) => v.voterId === playerId) || null;
        const myVotedTarget = myVote ? (myVote.targetPlayerId ?? "__abstain__") : null;
        votingControls = (
          <div
            className="turn-controls"
            style={{
              marginTop: "0.75rem",
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              gap: "0.5rem",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <h4 style={{ margin: 0 }}>Cast Your Vote</h4>
              {isHost && (
                <button
                  type="button"
                  onClick={handleTriggerAiVotes}
                  disabled={aiVoteBusy}
                  className="btn"
                  title="Ask AI players to cast their votes now"
                  style={{ padding: "0.25rem 0.6rem" }}
                >
                  {aiVoteBusy ? "Triggering..." : "Trigger AI Votes"}
                </button>
              )}
            </div>
            <p className="turn-stage" style={{ margin: 0 }}>
              Choose a player to eliminate, or abstain.
            </p>
            <div className="turn-list" style={{ width: "100%" }}>
              {gameState.players
                .filter((p) => p.isAlive)
                .map((p) => (
                  <div key={p.playerId} className="turn-entry" style={{ alignItems: "center" }}>
                    <div className="turn-entry-position" />
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1 }}>
                      <div className="turn-entry-name">
                        {p.name}
                        {p.playerId === playerId && (
                          <span style={{ marginLeft: 6, fontSize: 12, color: "#93c5fd" }}>(You)</span>
                        )}
                      </div>
                      <div className="turn-entry-role">
                        {p.isAI ? "AI" : p.isHost ? "Host" : "Player"}
                      </div>
                    </div>
                    <div style={{ marginLeft: "auto" }}>
                      {myVotedTarget !== null ? (
                        (myVotedTarget === "__abstain__" && p.playerId === playerId) ||
                        (myVotedTarget !== "__abstain__" && myVotedTarget === p.playerId) ? (
                          <button
                            type="button"
                            disabled
                            className="btn"
                            title="You have voted"
                            style={{ padding: "0.25rem 0.6rem", background: "rgba(148, 163, 184, 0.25)", color: "#cbd5e1", cursor: "not-allowed" }}
                          >
                            Voted
                          </button>
                        ) : null
                      ) : (
                        p.playerId === playerId ? (
                          <button
                            type="button"
                            onClick={() => handleVote(null)}
                            disabled={voteBusy}
                            title="Abstain from voting"
                            className="btn"
                            style={{ padding: "0.25rem 0.6rem" }}
                          >
                            {voteBusy ? "?" : "Do Not Vote"}
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => handleVote(p.playerId)}
                            disabled={voteBusy}
                            title={`Vote to eliminate ${p.name}`}
                            className="btn"
                            style={{ padding: "0.25rem 0.6rem" }}
                          >
                            {voteBusy ? "?" : "Vote"}
                          </button>
                        )
                      )}
                    </div>
                  </div>
                ))}
            </div>
            <p className="turn-stage" style={{ marginTop: "0.25rem" }}>
              Waiting for everyone to vote... ({voterIdsWhoVoted.size} / {alive.length})
            </p>
          </div>
        );
      } else {
        const { byVoter, counts, top, nameOf } = tallyVotes(aliveVotes, gameState.players);
        const entries = Array.from(counts.entries())
          .map(([key, cnt]) => ({
            key,
            label: key === "__abstain__" ? "Abstain" : nameOf(key),
            count: cnt,
          }))
          .sort((a, b) => b.count - a.count);

        const voterLines = alive
          .map((p) => {
            const tgt = byVoter.get(p.playerId);
            return { voter: p.name, target: tgt ? nameOf(tgt) : "Abstain" };
          })
          .sort((a, b) => a.voter.localeCompare(b.voter));

        const killName = top.isTie || !top.id ? null : nameOf(top.id);

        votingControls = (
          <div
            className="turn-controls"
            style={{
              marginTop: "0.75rem",
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-start",
              gap: "0.75rem",
            }}
          >
            <h4 style={{ margin: 0 }}>Voting Summary</h4>
            <div className="turn-list" style={{ width: "100%" }}>
              {entries.map((e) => (
                <div key={e.key} className="turn-entry" style={{ alignItems: "center" }}>
                  <div className="turn-entry-position" />
                  <div className="turn-entry-name">{e.label}</div>
                  <div className="turn-entry-role" style={{ marginLeft: "auto" }}>
                    {e.count} vote{e.count === 1 ? "" : "s"}
                  </div>
                </div>
              ))}
            </div>
            <div className="ai-log" style={{ width: "100%" }}>
              {voterLines.map((ln) => (
                <div key={ln.voter} className="ai-entry">
                  <div className="ai-entry-header">
                    <strong>{ln.voter}</strong>
                    <span>voted</span>
                  </div>
                  <p>{ln.target}</p>
                </div>
              ))}
            </div>
            {isHost ? (
              <div style={{ display: "flex", gap: "0.5rem" }}>
                {killName ? (
                  <button
                    type="button"
                    onClick={handleApplyVotes}
                    disabled={applyBusy}
                    title={`Eliminate ${killName} and end the day`}
                    style={{ background: "rgba(248,113,113,0.35)", color: "#fee2e2" }}
                  >
                    {applyBusy ? "Applying..." : "End Voting"}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleFinishRound}
                    disabled={finishBusy}
                    title="No clear target — end day without elimination"
                  >
                    {finishBusy ? "Closing..." : "End Voting"}
                  </button>
                )}
              </div>
            ) : (
              <p className="turn-stage" style={{ marginTop: "0.25rem" }}>
                Waiting for the host to apply the result...
              </p>
            )}
          </div>
        );
      }
    }

    return (
      <div className="card" style={{ marginTop: "1.5rem" }}>
        <div className="turn-header">
          <div>
            <h3>Turn Flow</h3>
            <p className="turn-stage">{stageDescription}</p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            {recordStatus && isCurrentPlayerSpeaking && (
              <span style={{ fontSize: 12, color: "#a5b4fc" }}>{recordStatus}</span>
            )}
            {headerActions}
            {currentTurn?.name && <div className="turn-current-pill">Now: {currentTurn.name}</div>}
          </div>
        </div>

        {isDiscussion ? (
          <>
            <div className="turn-list">
              {turnOrder.length ? (
                turnOrder.map((entry) => (
                  <div key={entry.playerId} className={`turn-entry${entry.isCurrent ? " current" : ""}`}>
                    <div className="turn-entry-position">#{entry.order}</div>
                    <div>
                      <div className="turn-entry-name">
                        {entry.name}
                        {entry.playerId === playerId && (
                          <span style={{ marginLeft: 8, fontSize: 12, color: "#93c5fd" }}>(You)</span>
                        )}
                      </div>
                      <div className="turn-entry-role">{entry.isAI ? "AI" : "Player"}</div>
                    </div>
                  </div>
                ))
              ) : (
                <p style={{ color: "#94a3b8" }}>Turn order will appear once the night resolves.</p>
              )}
            </div>

            {speakingControls}
            {votingControls}
          </>
        ) : (
          isNight && (
            <div style={{ marginTop: "1rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              <p style={{ color: "#94a3b8" }}>
                {isHost
                  ? nightStageInfo?.hostPrompt || "Host: queue night actions or resolve when ready."
                  : nightStageInfo?.playerPrompt || "Waiting for the host to resolve the night."}
              </p>
            </div>
          )
        )}
      </div>
    );
  };

  const renderNightRoleActions = () => {
    if (!playerSession || !gameState) return null;
    if (!playerSession.isAlive) return null;
    if (gameState.workflowStage !== "night") return null;

    const stage = gameState.nightStage;
    const sections = [];

    if (playerSession.role === "werewolf" && stage === "wolves") {
      const allyNames = new Set((playerSession.knownAllies || []).map((name) => name.toLowerCase()));
      const targets = (gameState.players || [])
        .filter(
          (p) =>
            p.isAlive &&
            p.playerId !== playerId &&
            !allyNames.has((p.name || "").toLowerCase())
        )
        .sort((a, b) => a.name.localeCompare(b.name));

      sections.push(
        <div key="wolf" style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <h4 style={{ margin: 0 }}>Choose someone to hunt</h4>
          <select
            value={wolfTarget}
            onChange={(event) => setWolfTarget(event.target.value)}
            disabled={wolfActionBusy || nightBusy || wolfActionDone}
            style={{ minWidth: 220 }}
          >
            <option value="">Select a target</option>
            {targets.map((p) => (
              <option value={p.playerId} key={p.playerId}>
                {p.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleSubmitWolfTarget}
            disabled={wolfActionBusy || nightBusy || !wolfTarget || wolfActionDone}
            style={{ padding: "0.35rem 0.75rem" }}
          >
            {wolfActionBusy ? "Submitting..." : wolfActionDone ? "Submitted" : "Submit Hunt"}
          </button>
        </div>
      );
    }

    if (playerSession.role === "detective" && stage === "detective") {
      const suspects = (gameState.players || [])
        .filter((p) => p.isAlive && p.playerId !== playerId)
        .sort((a, b) => a.name.localeCompare(b.name));

      sections.push(
        <div key="detective" style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <h4 style={{ margin: 0 }}>Inspect a player</h4>
          <select
            value={detectiveTarget}
            onChange={(event) => setDetectiveTarget(event.target.value)}
            disabled={detectActionBusy || nightBusy || detectActionDone}
            style={{ minWidth: 220 }}
          >
            <option value="">Select a suspect</option>
            {suspects.map((p) => (
              <option value={p.playerId} key={p.playerId}>
                {p.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleSubmitDetectiveTarget}
            disabled={detectActionBusy || nightBusy || !detectiveTarget || detectActionDone}
            style={{ padding: "0.35rem 0.75rem" }}
          >
            {detectActionBusy ? "Submitting..." : detectActionDone ? "Submitted" : "Submit Inspection"}
          </button>
        </div>
      );
    }

    if (!sections.length) {
      return null;
    }

    return (
      <div className="card" style={{ marginTop: "1.5rem" }}>
        <h3>Your Night Actions</h3>
        <p style={{ color: "#94a3b8", marginTop: 0 }}>
          Only you can see these controls. Make your move before the host advances the night.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>{sections}</div>
      </div>
    );
  };

  const renderRoleCard = () => {
    if (!playerSession || !gameState || (gameState.status === "waiting" && !playerSession.role)) return null;
    const roleLabel = playerSession.role ? playerSession.role.charAt(0).toUpperCase() + playerSession.role.slice(1) : "Unknown";
    const allies = playerSession.knownAllies || [];
    const notes = playerSession.notes || [];
    return (
      <div className="word-card">
        <div className="label">Your role</div>
        <div className="word">{roleLabel}</div>
        {roleBanner && <p style={{ marginTop: "1rem", color: "#fbcfe8" }}>{roleBanner}</p>}
        {!playerSession.isAlive && (
          <div className="hint-box" style={{ marginTop: "1.25rem" }}>
            You have been eliminated. Continue watching the timeline as roles reveal.
          </div>
        )}
        {allies.length > 0 && (
          <div className="hint-box" style={{ marginTop: "1.25rem" }}>
            Packmates: {allies.join(", ")}
          </div>
        )}
        {notes.length > 0 && (
          <div className="ai-log" style={{ marginTop: "1rem" }}>
            {notes
              .slice()
              .reverse()
              .map((note, idx) => (
                <div className="ai-entry" key={`${note}-${idx}`}>
                  <p>{note}</p>
                </div>
              ))}
          </div>
        )}
      </div>
    );
  };

  const renderAudioLog = () => {
    if (!gameState?.audioClips?.length) return null;
    return (
      <div className="card" style={{ marginTop: "1.5rem" }}>
        <h3>Audio Uploads & Transcripts</h3>
        <div className="audio-list">
          {gameState.audioClips
            .slice()
            .reverse()
            .map((clip) => (
              <div className="audio-item" key={clip.clipId} title={clip.storagePath || ""}>
                <div>
                  <strong>{clip.name}</strong> shared {clip.filename}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                  <audio controls src={api.audioUrl(gameId, clip.clipId)} style={{ height: 30 }} />
                  <div className="audio-item-meta">{(clip.size / 1024).toFixed(1)} KB</div>
                </div>
                {clip.transcript && (
                  <div className="audio-item-meta" style={{ marginTop: "0.35rem", fontStyle: "italic" }}>
                    Transcript: {clip.transcript}
                  </div>
                )}
              </div>
            ))}
        </div>
        {/* <p style={{ marginTop: "0.5rem", color: "#64748b" }}>
          Audio clips live under <code>backend/data/audio</code>; swap in your own speech-to-text engine later.
        </p> */}  
      </div>
    );
  };

  const renderChat = () => {
    if (!gameState) return null;
    return (
      <div className="card" style={{ marginTop: "1.5rem" }}>
        <h3>Town Chat</h3>
        <div className="ai-log">
          {(gameState.chatMessages || [])
            .slice()
            .reverse()
            .map((m) => (
              <div className="ai-entry" key={m.messageId}>
                <div className="ai-entry-header">
                  <strong>{m.name}</strong>
                  <span>{new Date(m.timestamp * 1000).toLocaleTimeString()}</span>
                </div>
                <p>{m.text}</p>
              </div>
            ))}
        </div>
        <form onSubmit={handleSendChat} style={{ marginTop: "0.75rem", display: "flex", gap: "0.5rem" }}>
          <input value={chatText} onChange={(e) => setChatText(e.target.value)} placeholder="Share a quick thought" />
          <button type="submit" disabled={!chatText.trim()}>
            Send
          </button>
        </form>
      </div>
    );
  };

  const renderEvents = () => {
    if (!gameState?.events?.length) return null;
    return (
      <div className="card" style={{ marginTop: "1.5rem" }}>
        <h3>Night & Day Timeline</h3>
        <div className="ai-log">
          {gameState.events
            .slice()
            .reverse()
            .map((event) => (
              <div className="ai-entry" key={event.eventId}>
                <div className="ai-entry-header">
                  <strong>{event.phase ? event.phase.toUpperCase() : "EVENT"}</strong>
                  <span>{new Date(event.timestamp * 1000).toLocaleTimeString()}</span>
                </div>
                <p>{event.text}</p>
              </div>
            ))}
        </div>
      </div>
    );
  };

  const renderHostControls = () => {
    if (!isHost || !gameState) return null;
    if (gameState.status === "waiting") return null;
    const isActive = gameState.status === "in_progress";
    const isNightStageActive = isActive && gameState.workflowStage === "night";
    const advanceLabel = nightStageInfo?.buttonLabel || "Advance Night";
    return (
      <div className="card" style={{ marginTop: "1.5rem" }}>
        <h3>Host Controls</h3>
        {isNightStageActive && (
          <>
            <button
              type="button"
              onClick={handleAdvanceNightStage}
              disabled={nightBusy || !nightStage}
            >
              {nightBusy ? "Advancing..." : advanceLabel}
            </button>
            {nightStageInfo && (
              <p style={{ marginTop: "0.5rem", color: "#94a3b8" }}>{nightStageInfo.hostPrompt}</p>
            )}
          </>
        )}
        {isActive && (
          <button
            type="button"
            onClick={handleReveal}
            disabled={loading}
            style={{ marginTop: "0.75rem", background: "rgba(248, 113, 113, 0.35)", color: "#fee2e2" }}
          >
            {loading ? "Ending..." : "End Game & Reveal Roles"}
          </button>
        )}
        {!isActive && (
          <p style={{ marginTop: "0.5rem", color: "#94a3b8" }}>
            Game complete. Use "Back to Start" to host another round.
          </p>
        )}
      </div>
    );
  };

  const renderGameView = () => {
    if (!gameState) return null;
    return (
      <>
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <h2>Game Lobby</h2>
              <StatusPill status={gameState.status} />
            </div>
            <div>
              <div style={{ fontSize: "0.85rem", color: "#cbd5f5" }}>Join Code</div>
              <div className="join-code">{gameState.joinCode}</div>
            </div>
          </div>
          <div className="section-title">Players</div>
          {renderPlayers()}
          {gameState.victoryMessage && (
            <div className="hint-box" style={{ marginTop: "1.5rem" }}>
              {gameState.victoryMessage}
            </div>
          )}
        </div>
        {renderRoleCard()}
        {renderEvents()}
        {renderTurnTracker()}
        {renderNightRoleActions()}
        {renderAudioLog()}
        {renderChat()}
        {renderHostControls()}
        <button
          type="button"
          style={{ marginTop: "1.5rem", background: "rgba(148, 163, 184, 0.25)", color: "#e2e8f0" }}
          onClick={handleReset}
        >
          Back to Start
        </button>
      </>
    );
  };

  return (
    <div className="app-container">
      <h1>Moonlit Mafia</h1>
      <p style={{ color: "#cbd5f5" }}>
        Social deduction under a full moon: villagers talk by day, werewolves hunt by night, and the detective searches
        for the truth.
      </p>

      {error && <div className="error-banner">{error}</div>}

      {phase === "landing" ? renderLanding() : renderGameView()}
    </div>
  );
}
