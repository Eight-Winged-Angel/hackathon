# ai_speaker.py
import json
import re
from typing import Dict, Any, Optional
from pydub import AudioSegment
import openai
from uuid import uuid4

# =============================
# API 配置
# =============================
client = openai.Client(
    api_key="bai-0tS-NIHC8A04XHOSbU7Z6qzF_tZHZyl-4l67jy5MdqBsawIj",
    base_url="https://hackathon.boson.ai/v1"
)

THINK_MODEL = "Qwen3-32B-Thinking-Hackathon"

ALLOWED_EMOTIONS = {"neutral","calm","happy","sad","angry","fearful","disgust","surprised"}



def _validate_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    out["content"] = str(plan.get("content","...")).strip()
    out["actor"] = max(1,min(24,int(plan.get("actor",1))))
    emo = str(plan.get("emotion","neutral")).lower()
    out["emotion"] = emo if emo in ALLOWED_EMOTIONS else "neutral"
    intensity = plan.get("intensity",1)
    out["intensity"] = 1 if str(intensity) not in ("1","2") else int(intensity)
    out["expression_instruction"] = str(plan.get("expression_instruction","")).strip()

    return out

def _extract_json(text: str) -> Dict[str, Any]:
    """优先提取【最后一个】```json ...``` 代码块；没有就找最后一个 {...}。"""

    # Debug：观察模型原始输出
    print("\n--- RAW MODEL OUTPUT BEGIN ---")
    print(text)
    print("--- RAW MODEL OUTPUT END ---\n")

    # ① 找最后一个 ```json ...``` 代码块
    last_json_block = None
    for m in re.finditer(r"```json\s*(\{.*?\})\s*```", text, flags=re.S):
        last_json_block = m.group(1)
    if last_json_block:
        return json.loads(last_json_block)

    # ② 兜底：抓最后一个 {...}
    m = list(re.finditer(r"\{[^{}]*?(?:\{[^{}]*\}[^{}]*?)*\}", text, flags=re.S))
    if m:
        candidate = m[-1].group(0)
        return json.loads(candidate)

    raise ValueError("Failed to parse JSON from model output")

def think_ai_utterance(messages) -> Dict[str, Any]:
    schema_hint = (
        "At the END of your answer, output a JSON object wrapped in a fenced code block:\n"
        "```json\n"
        '{\n'
        '  "content": "{content that should be said}",\n'
        '  "actor": 1..24,\n'
        '  "emotion": "happy|sad|angry|fearful|disgust, etc.",\n'
        '  "intensity": 1 or 2,\n'
        '  "expression_instruction": "..." \n'
        '}\n'
        "```\n"
        "Do not put anything after the fenced JSON block."
    )

    system_prompt = (
        "You are a planner that generates a speaking plan for a player in a Werewolf game.\n"
        "You may include brief hidden reasoning **before** the final JSON result, outside the JSON block.\n"
        "The **final** part of your message must be exactly one JSON object, in a fenced ```json code block.\n"
        "Constraints:\n"
        "- content: concise, 10 to 18 seconds.\n"
        "- actor: integer 1..24.\n"
        "- emotion: one of ['happy','sad','angry','fearful','disgust','surprised'].\n"
        "- intensity: 1 or 2.\n"
        "- expression_instruction: short actionable refinement.\n"
    )

    user_prompt = f"{schema_hint}"

    # Retry up to 3 times if JSON parse fails
    for attempt in range(3):
        resp = client.chat.completions.create(
            model="Qwen3-Omni-30B-A3B-Thinking-Hackathon",
            messages=messages + [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            top_p=0.8,
            max_tokens=2048,
            extra_body={
                "top_k": 20,
                "repetition_penalty": 1.05,
                "presence_penalty": 0.3,
            },
        )

        raw = resp.choices[0].message.content
        try:
            plan = _extract_json(raw)
            plan["_raw_model_output"] = raw 
            return _validate_plan(plan)
        except Exception:
            print(f"⚠ JSON parse failed, retry {attempt + 1}/3...")

    # Fallback after all retries
    print("❌ JSON parse failed after 3 retries → fallback")
    plan = {"content": "Let’s not rush. Someone give us real info.", "actor": 1, "emotion": "neutral", "intensity": 1}
    plan["_raw_model_output"] = "(fallback: JSON parse failed 3x)" 
    return _validate_plan(plan)



# =============================
# ✅ 你原有的 TTS（仅支持 API 推理）
# =============================
import os, openai
import wave
import base64

# --- 新增：工具函数（放在文件顶部 imports 后 / 本函数前均可） ---
from io import BytesIO
from pydub import AudioSegment

def _extract_audio_bytes(resp) -> bytes:
    """
    尝试从 higgs response 中提取音频字节。
    兼容常见结构：choices[0].message.content 为 list，含 {"type":"output_audio","audio":{"data":...}}
    """
    try:
        parts = resp.choices[0].message.content
        if isinstance(parts, list):
            for p in parts:
                if isinstance(p, dict) and p.get("type") in ("output_audio", "audio"):
                    data = p.get("audio", {}).get("data") or p.get("data")
                    if isinstance(data, (bytes, bytearray)):
                        return bytes(data)
                    # 有些 SDK 可能是 base64；如需，按需在这里解码
        # 兜底：某些实现把二进制放在 message.audio
        maybe = getattr(resp.choices[0].message, "audio", None)
        if isinstance(maybe, (bytes, bytearray)):
            return bytes(maybe)
    except Exception:
        pass
    raise RuntimeError("Cannot extract audio bytes from response")

def _measure_dbfs(audio_bytes: bytes) -> float:
    seg = AudioSegment.from_file(BytesIO(audio_bytes), format="wav")
    return seg.dBFS
# --- 工具函数结束 ---




def b64(path):
    return base64.b64encode(open(path, "rb").read()).decode("utf-8")
def to_audio(path, vol_boost=None):
    if vol_boost is not None:
        seg = AudioSegment.from_wav(path)
        temp_name = f'{uuid4()}.wav'
        (seg + vol_boost).export(temp_name, format='wav')
        res = {'type': "input_audio", "input_audio": {'data': b64(temp_name), 'format': 'wav'}}
        Path(temp_name).unlink()
        return res
    return {'type': "input_audio", "input_audio": {'data': b64(path), 'format': 'wav'}}
import re
def process_resp(resp):
    resp = resp.choices[0].message.content
    return re.findall(r'(?:<think>.*</think>)*\n*(.+)', resp, re.DOTALL)[0]
def save_audio(resp, out_name='output.wav'):
    """
    优先按常见字段 message.audio.data(base64) 写文件；
    失败则退回通用提取器 _extract_audio_bytes(resp)。
    """
    try:
        b64data = resp.choices[0].message.audio.data  # 可能不存在
        with open(out_name, "wb") as f:
            f.write(base64.b64decode(b64data))
        return
    except Exception:
        # 走通用提取（兼容 content 列表里带 {"type":"output_audio","audio":{"data":...}} 的返回）
        audio_bytes = _extract_audio_bytes(resp)
        with open(out_name, "wb") as f:
            f.write(audio_bytes)
        return


def _fallback_save_audio_bytes(resp, out_name='output.wav'):
    """
    你在 except 分支里调用了这个函数，但原文件中并未定义，导致 NameError。
    这里做一个“最后兜底”：尽力从各种位置取音频。
    """
    try:
        audio_bytes = _extract_audio_bytes(resp)
        with open(out_name, "wb") as f:
            f.write(audio_bytes)
        return
    except Exception:
        # 真的不行再尝试 base64 → bytes 的最后一次尝试
        try:
            b64data = resp.choices[0].message.audio.data
            with open(out_name, "wb") as f:
                f.write(base64.b64decode(b64data))
            return
        except Exception as e:
            # 抛回去让上层走空音频兜底
            raise e

import requests
import time
endpoint = 'https://tmpfiles.org/api/v1/upload'
def upload_temp(f):
    resp = requests.post(endpoint, files={'file': open(f, 'rb')})
    t = 1
    while True:
        try:
            return resp.json()['data']['url'].replace('.org/', '.org/dl/')
        except:
            pass
        time.sleep(t)
        print('Sleep', t)
        t *= 2

from pathlib import Path
import pandas as pd
import kagglehub

# Download latest version
path = Path(kagglehub.dataset_download("uwrfkaggler/ravdess-emotional-speech-audio")) 
fs = path.glob('**/*.wav')
df = pd.DataFrame({'f': [str(f) for f in fs]})

df['stem'] = df.f.str.extract(r'.*\\(.*).wav')
df2 = pd.DataFrame(df.stem.str.split('-').tolist(), columns=['modality', 'vocal', 'emotion', 'intensity', 'statement', 'repetition', 'actor']).astype(int)
df_total = df.merge(df2, left_index=True, right_index=True)
emote_1 = df_total[(df_total.emotion != 1) & (df_total.actor == 1)]
neutral_1 = df_total[(df_total.emotion == 1) & (df_total.actor == 1)]
statements = ["Kids are talking by the door", "Dogs are sitting by the door"]
emotions = ['neutral', 'calm', 'happy', 'sad', 'angry', 'fearful', 'disgust', 'surprised']

def silence_filter(s, silence_limit=2000):
    from pydub import AudioSegment
    from pydub.silence import detect_silence
    seg = AudioSegment.from_wav(s)
    if (seg.dBFS > -45):
        seg = seg - seg.dBFS - 20
    else:
        return True
    return any([e - s > silence_limit for s, e in detect_silence(seg, min_silence_len=500, silence_thresh=-40)])

def generate_emotion(
    transcript,
    emotion='happy',
    actor=4,
    intensity=1,
    expression_instruction="",
    out_name='out.wav',
    max_retry=3
):
    """
    生成音频 → 用 silence_filter 质检 → 不合格则最多重试 max_retry 次。
    已接入 expression_instruction 来细化表达（语速/语调/停顿/能量/姿态）。
    """
    global df_total, emotions, statements, to_audio, save_audio

    # calm-1 fallback：不产出 calm-1
    if (emotion == 'calm' and int(intensity) == 1):
        emotion = 'neutral'
        intensity = 1

    # Few-shot 样本（可为空，零样本降级）
    samples = []
    try:
        subset = df_total[
            (df_total.emotion == emotions.index(emotion) + 1)
            & (df_total.intensity == int(intensity))
            & (df_total.actor == int(actor))
        ]
        for (_, a) in subset.iterrows():
            samples += [
                {"role": "user", "content": statements[a.statement - 1]},
                {"role": "assistant", "content": [to_audio(a.f, vol_boost=5)]},
            ]
    except Exception:
        samples = []

    # 将 expression_instruction 转成更明确的表演提示（可按需扩展）
    def _style_hint_from_expression(expr: str) -> str:
        e = (expr or "").lower().strip()
        # 轻量映射：把常见词转成更具体的演绎指令
        rules = []
        if any(k in e for k in ["assertive", "confident", "坚定", "果断", "强势"]):
            rules += ["tighter phrasing", "shorter pauses", "firm tone", "reduced upspeak"]
        if any(k in e for k in ["defensive", "防御", "被动", "解释"]):
            rules += ["slightly faster onset", "narrow pitch range", "controlled energy"]
        if any(k in e for k in ["sarcastic", "讽刺", "嘲讽", "轻蔑"]):
            rules += ["slight drawl", "downward inflection", "subtle scoff timbre"]
        if any(k in e for k in ["provocative", "挑衅"]):
            rules += ["higher projection", "sharper onsets", "brisk tempo"]
        if any(k in e for k in ["hesitant", "犹豫"]):
            rules += ["longer micro-pauses", "softer onset", "slower pace"]
        if any(k in e for k in ["urgent", "紧急", "着急"]):
            rules += ["faster pace (+10-15%)", "higher energy", "compressed pauses"]
        if any(k in e for k in ["calm", "冷静", "稳重"]):
            rules += ["steady tempo", "even tone", "longer but gentle pauses"]
        # ✅ Suspicious / doubtful
        if any(k in e for k in ["suspicious", "doubtful","怀疑", "质疑"]):
            rules += ["slight pauses before accusations", "detectable tension", "tight pitch control"]
        # ✅ Logical / analytical
        if any(k in e for k in ["logical", "reasoned", "analytical", "分析", "理性"]):
            rules += ["even tone", "moderate pace", "clear articulation", "minimal emotional variance"]
            # ✅ NEW: Joking / playful
        if any(k in e for k in ["joking", "playful", "开玩笑", "调侃"]):
            rules += ["light bounciness", "slight upward inflection", "looser rhythm"]

        # ✅ NEW: Anxious / worried
        if any(k in e for k in ["anxious", "worried", "焦虑", "担心"]):
            rules += ["slightly shaky voice", "faster breathing", "minor pitch instability"]

        # ✅ NEW: Nervous / timid
        if any(k in e for k in ["nervous", "timid", "紧张"]):
            rules += ["soft onsets", "frequent micro-pauses", "lower projection"]

        # ✅ NEW: Observant / investigative
        if any(k in e for k in ["observant", "investigative", "观察", "审视"]):
            rules += ["slow deliberate pace", "analytical pauses", "clear enunciation"]


        # 合并成一句可读的提示；为空则返回空串
        return ("Style refinement: " + ", ".join(rules) + ".\n") if rules else ""

    def _sys_prompt(extra_hint: str = ""):
        # 这里把 emotion / intensity 的硬约束、calm-1 禁用、表达强度差异、
        # 以及 expression_instruction 的“增量表演提示”都放进去。
        return (
            "<|scene_desc_start|>"
            f"Actor {actor}. Emotion {emotion}. Intensity {intensity}.\n"
            "You MUST map the requested emotion to one of EXACTLY these categories:\n"
            "['happy','sad','angry','fearful','disgust','surprised'].\n"
            "Rules:\n"
            "- We do NOT have 'calm-1'. If requested, use neutral/mild instead.\n"
            "- Intensity: 1 = mild (lower energy, softer tone, slightly slower tempo), "
            "2 = strong (higher energy, clearer projection, possibly faster tempo for happy/angry).\n"
            "- Reflect emotion+intensity via tone, pitch, speed, energy, and pause timing.\n"
            f"- expression_instruction: {expression_instruction or '(none)'}\n"
            f"{_style_hint_from_expression(expression_instruction)}"
            + extra_hint +
            "<|scene_desc_end|>\n"
        )

    def _call(extra_hint=""):
        return client.chat.completions.create(
            model="higgs-audio-generation-Hackathon",
            messages=[{"role": "system", "content": _sys_prompt(extra_hint)}]
                     + samples
                     + [{"role": "user", "content": transcript}],
            modalities=["text","audio"],
            temperature=0.9, top_p=0.95,
            max_completion_tokens=1024,
        )

    # 统一的：生成 → 保存 → 静音质检 →（必要时）重试
    for attempt in range(max_retry + 1):
        if attempt > 0:
            print(f"Retry #{attempt} due to silence detected")

        # 重试时，附加减少静音/增强能量的提示，但保持情感与强度不变
        hint = "" if attempt == 0 else (
            "Reduce silence and shorten long pauses; increase vocal projection by 4-8 dB; "
            "preserve the same emotion and intensity.\n"
        )

        resp = _call(extra_hint=hint)

        try:
            save_audio(resp, out_name=out_name)
        except Exception:
            _fallback_save_audio_bytes(resp, out_name)

        # 通过 silence_filter 进行质检；False 表示“静音不过量”，可接受
        if not silence_filter(out_name):
            break

    return out_name


def asr(audio, verbose=False, max_tokens=4096, temperature=0.2, top_p=0.95):
    messages = [
            {"role":"system","content":"You are a helpful assistant."},
            {"role":"user","content":[
                {"type":"audio_url","audio_url": {"url":upload_temp(audio)}},
                {"type":"text","text":f"Transcribe this audio."}
            ]},
        ]
    resp = client.chat.completions.create(
        model="Qwen3-Omni-30B-A3B-Thinking-Hackathon",
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stream=False,
    )   
    return process_resp(resp)


# =============================
# ✅ 串联：思考 → 发声
# =============================
def plan_and_speak(messages, out_name="out.wav"):
    plan = think_ai_utterance(messages)
    generate_emotion(
        transcript=plan["content"],
        emotion=plan["emotion"],
        actor=plan["actor"],
        intensity=plan["intensity"],
        expression_instruction=plan.get("expression_instruction",""),
        out_name=out_name
    )
    return plan