# ai_speaker.py
import json
import re
from typing import Dict, Any, Optional
from pydub import AudioSegment
import openai
from uuid import uuid4
import os


# =============================
# API 配置
# =============================
# print(os.getenv('BOSON_API_KEY'))
# API_KEY = os.getenv('BOSON_API_KEY')
client = openai.Client(
    api_key=API_KEY,
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
        '  "emotion": "happy|sad|angry|fearful|disgust, etc.",\n'
        '  "intensity": 1 or 2\n'
        '  "expression_instruction": "{short sentence describing emotion}"\n'
        '}\n'
        "```\n"
        "Do not put anything after the fenced JSON block."
    )

    system_prompt = (
        "You are a planner that generates a speaking plan for a player in a Werewolf game.\n"
        "This game is played virtually; do not include any info about the physical space\n"
        "You may include brief hidden reasoning **before** the final JSON result, outside the JSON block.\n"
        "The **final** part of your message must be exactly one JSON object, in a fenced ```json code block.\n"
        "Constraints:\n"
        "- content: concise, 10 to 18 seconds.\n"
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

def to_audio(path, min_vol=None, boost=0):
    # if min_vol is not None:
    min_vol = -100 if min_vol is None else min_vol
    
    seg = AudioSegment.from_wav(path)
    temp_name = f'{uuid4()}.wav'
    (seg + max(0, min_vol - seg.dBFS) + boost).export(temp_name, format='wav')
    res = {'type': "input_audio", "input_audio": {'data': b64(temp_name), 'format': 'wav'}}
    Path(temp_name).unlink()

    return res

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

import kagglehub
from pathlib import Path
from pydub import AudioSegment
import numpy as np
path = kagglehub.dataset_download("uwrfkaggler/ravdess-emotional-speech-audio")
import pandas as pd

fs = Path(path).glob('**/*.wav')
df = pd.DataFrame({'f': [str(f) for f in fs]})
df['stem'] = df.f.str.extract(r'.*\\(.*).wav')
df2 = pd.DataFrame(df.stem.str.split('-').tolist(), columns=['modality', 'vocal', 'emotion', 'intensity', 'statement', 'repetition', 'actor']).astype(int)
df_total = df.merge(df2, left_index=True, right_index=True)
statements = ["Kids are talking by the door", "Dogs are sitting by the door"]
emotions = ['neutral', 'calm', 'happy', 'sad', 'angry', 'fearful', 'disgust', 'surprised']

df_total['emotion'] = df_total.emotion.apply(lambda x: emotions[x - 1])
df_total['statement'] = df_total.statement.apply(lambda x: statements[x - 1])

def generate_audio(transcript, system_prompt=None, additional_messages=None, temperature=0.9, 
                   top_p=0.95, top_k=50, max_tokens=512, out_name='out.wav', **kwargs):
    additional_messages = [] if additional_messages is None else additional_messages
    system_prompt = system_prompt or 'Generate speech based on the provided sample and transcript. <|scene_desc_start|>The audio is recorded in a quiet room with no noise. The speech is clearly audible and loud.<|scene_desc_end|>'
    resp = client.chat.completions.create(
        model="higgs-audio-generation-Hackathon",
        messages=[  
            {"role": "system", "content": system_prompt},
        ] + additional_messages + [{'role': 'user', 'content': transcript}],
        modalities=["text", "audio"],
        max_completion_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stream=False,
        stop=["<|eot_id|>", "<|end_of_text|>", "<|audio_eos|>"],
        extra_body={"top_k": top_k},
        **kwargs
    )  
    save_audio(resp, out_name)

def extract_samples(n_samples=None, **kwargs):
    mask = df_total.f.notna()
    for k, v in kwargs.items():
        mask &= (df_total[k] == v)
    samples = []
    masked = df_total[mask]
    n_samples = min(len(masked), n_samples) if n_samples is not None else len(masked)
    for _, sample in df_total[mask].sample(n_samples).iterrows():
        samples += [{'role': 'user', 'content': sample.statement}, 
            {'role': 'assistant', 'content': [to_audio(sample.f, min_vol=-30)]}]
    return samples

def silence_filter(s, silence_limit=2000):
    from pydub import AudioSegment
    from pydub.silence import detect_silence
    seg = AudioSegment.from_wav(s)
    if (seg.dBFS > -45):
        seg = seg - seg.dBFS - 20
    else:
        return True
    return any([e - s > silence_limit for s, e in detect_silence(seg, min_silence_len=500, silence_thresh=-40)])

def asr(audio, verbose=False, max_tokens=4096, temperature=0.2, top_p=0.95):
    messages = [
            {"role":"system","content":"You are a helpful assistant."},
            {"role":"user","content":[
                {"type":"audio_url","audio_url": {"url":upload_temp(audio)}},
                {"type":"text","text":f"Transcribe this audio. Only output the transcript, do not output anything else."}
            ]},
        ]
    resp = client.chat.completions.create(
        model="higgs-audio-understanding-Hackathon",
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
def plan_and_speak(player, game, out_name="out.wav"):
    plan = think_ai_utterance(player.get_info(game))
    prompt = f'''Generate speech based on the provided sample and transcript. 
    
    <|scene_desc_start|>The audio is recorded in a quiet room with no noise. The speech is clearly audible and loud. {plan.get("expression_instruction", "")} <|scene_desc_end|>'''
    for i in range(3):
        generate_audio(transcript = plan['content'], 
                       system_prompt=prompt,
                    additional_messages=extract_samples(n_samples=3, 
                                                        actor=player.owner.actor, 
                                                        intensity=plan['intensity'], 
                                                        emotion=plan['emotion'],
                                                        ),
                    out_name=out_name)
        print(f'GENERATION {i}')
        if not silence_filter(out_name):
            break
    
    # generate_emotion(
    #     transcript=plan["content"],
    #     emotion=plan["emotion"],
    #     actor=plan["actor"],
    #     intensity=plan["intensity"],
    #     expression_instruction=plan.get("expression_instruction",""),
    #     out_name=out_name
    # )
    return plan

def semantic_info(audio, verbose=False, max_tokens=4096, temperature=0.2, top_p=0.95):
    print('SEMANTIC AUDIO', audio)
    messages = [
            {"role":"system","content":"You are a helpful assistant."},
            {"role":"user","content":[
                {"type":"audio_url","audio_url": {"url":upload_temp(audio)}},
                {"type":"text","text":f"Write a short description about the prosody, tone, and emotional information in the audio."}
            ]},
        ]
    resp = client.chat.completions.create(
        model="higgs-audio-understanding-Hackathon",
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stream=False,
    )   
    return process_resp(resp)
