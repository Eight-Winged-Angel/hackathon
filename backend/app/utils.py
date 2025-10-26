import base64
from pathlib import Path
import os, openai
import wave
import base64

from uuid import uuid4

from pydub import AudioSegment
from pathlib import Path
import numpy as np

API_KEY = os.getenv('BOSON_API_KEY')
print(os.getenv('BOSON_API_KEY'))
# print(API_KEY)
client = openai.Client(
    api_key=API_KEY,
    base_url="https://hackathon.boson.ai/v1"
)

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

    return {'type': "input_audio", "input_audio": {'data': b64(path), 'format': 'wav'}}

import re
def process_resp(resp, verbose=False):
    resp = resp.choices[0].message.content
    # if verbose:
    #     thinking = re.findall(r'<think>(.*)</think>', resp, re.DOTALL)[0]
    #     print('THINKING', thinking)
    return re.findall(r'(?:<think>.*</think>)*\n*(.+)', resp, re.DOTALL)[0]
def save_audio(resp, out_name='output.wav'):
    (f := open(out_name, "wb")).write(base64.b64decode(resp.choices[0].message.audio.data))
def as_type(url, _type='audio'):
    return {'type': f'{_type}_url', f'{_type}_url': {'url': url}}
def as_text(t):
    return {'type': 'text', 'text': t}

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
        
def text_completion(messages, model='Qwen3-32B-thinking-Hackathon', temperature=1, max_tokens=2048, top_p=0.95, **kwargs):
    resp = client.chat.completions.create(model=model,
                                    messages=messages,
                                    max_completion_tokens=max_tokens,
                                    temperature=temperature,
                                    top_p=top_p,
                                   **kwargs)
    return process_resp(resp)