#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简谱数字 → 口琴音频（真采样音源 + ffmpeg 后处理 + EBU R128 响度标准化）

============================================================================
音源（--engine）
----------------------------------------------------------------------------
  sine     正弦波合成（默认）—— 不依赖任何采样文件，稳定可靠、速度快
  sampler  真口琴采样合成（实验性，不推荐）—— 读 basic-harmonica 的 SFZ。
           已知缺陷：① 长音循环没有交叉淡化，循环点会咔一下；
                     ② 释放音相对主体偏响约 6dB（SFZ 的 -7dB 是相对原始采样的，
                        又被 RMS 归一系数放大了一次）。
           要真采样音色，建议走 sfizz 渲染（见 README）而不是这个内置采样器。

后处理（--fx）
----------------------------------------------------------------------------
  light（默认）      高通 + 轻 EQ + 压缩，细微润色
  harmonica          更重：三段 EQ + 压缩 + chorus + aecho（为采样音色调的）
  wide               harmonica 再叠立体声加宽
  none               不做后处理
  最后统一过 loudnorm 做 EBU R128 响度标准化（-16 LUFS 默认，--lufs off 可关）

记号速查（方括号表示可重复叠加）
----------------------------------------------------------------------------
  1 2 3 4 5 6 7    音级。1 = 调式主音，默认 1=C → 1 就是中央 C（261.63 Hz）
  0                休止符（时值写法同音符）
  #4   b7          升号 / 降号（♯4  ♭7 也认）
  1'               高八度（' ^ + 都行，可叠加：1'' = 高两个八度）
  1,               低八度（可叠加：1,, = 低两个八度）
  _1               低八度（另一种写法）
  （1）  (1)        低八度（沿用之前那份简谱的括号写法）
  1-               延长线：时值 +1 拍（1-- = 3 拍）
  1/               减时线：时值减半（1/  = 半拍，1// = 四分之一拍）
  1.               附点：时值 ×1.5（1.. = ×1.75）
  1:0.75           直接指定拍数（万能写法）
  1~1  1 1~        连音线（两种写法都支持）
  空格             分句停顿 0.25 拍
  |                小节线（不停顿）
  ||               段落 / 换气：停顿 1 拍
  换行             停顿 1 拍

依赖
  必需：Python 3.8+（标准库 + pydub 可选）
  可选：ffmpeg —— 用于导出 MP3 / 后处理 / 响度标准化；没有就退化成存 WAV
============================================================================
"""
import argparse
import array
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave

try:
    from pydub import AudioSegment
except ImportError:  # 允许没有 pydub，走纯标准库写 WAV
    AudioSegment = None

SAMPLE_RATE = 44100
DEGREE_SEMITONES = [0, 2, 4, 5, 7, 9, 11]
KEY_SEMITONES = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

# ── 便携支持 ──────────────────────────────────────────────────────────────
# 脚本会**优先在同目录下**寻找资源（便携包结构），找不到才退回开发机的绝对路径。
# 便携包目录结构：
#   <包根>/3.py、sf2_render.cjs、使用说明.md
#   <包根>/engine/      libfluidsynth-2.4.6.js、js-synthesizer.min.js
#   <包根>/soundfonts/  GeneralUser-GS.sf2
#   <包根>/ffmpeg/bin/  ffmpeg.exe
#   <包根>/node/        node.exe
#   <包根>/harmonica/   harmonica solo.sfz、wav/*.wav
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _here(*parts):
    return os.path.join(BASE_DIR, *parts)


def _first_existing(*paths):
    """返回第一个存在的路径；都不存在时返回最后一个（用于给出可读的报错）。"""
    for p in paths:
        if p and os.path.exists(p):
            return p
    return paths[-1] if paths else ''


DEFAULT_SFZ = _first_existing(
    _here('harmonica', 'harmonica solo.sfz'),
    r'D:\deepseek\basic-harmonica\harmonica solo.sfz')
DEFAULT_WAV_DIR = _first_existing(
    _here('harmonica', 'wav'),
    r'D:\deepseek\basic-harmonica\tools\wav')
FFMPEG_CANDIDATES = [
    _here('ffmpeg', 'bin', 'ffmpeg.exe'),
    _here('ffmpeg.exe'),
    r'D:\deepseek\tools\ffmpeg\bin\ffmpeg.exe',
    r'C:\Program Files\Red Giant\Trapcode Suite\Tools\ffmpeg.exe',
]

FX_PRESETS = {
    'none': '',
    'light': ('highpass=f=110,'
              'equalizer=f=240:width_type=q:w=1:g=-2,'
              'equalizer=f=2600:width_type=q:w=1.2:g=2.5,'
              'acompressor=threshold=-18dB:ratio=3:attack=10:release=200'),
    'harmonica': ('highpass=f=110,'
                  'equalizer=f=240:width_type=q:w=1:g=-3,'
                  'equalizer=f=2600:width_type=q:w=1.2:g=3,'
                  'equalizer=f=7000:width_type=q:w=1.5:g=2,'
                  'acompressor=threshold=-18dB:ratio=3:attack=10:release=200:makeup=2,'
                  'chorus=0.6:0.9:50|60:0.4|0.32:0.25|0.4:2|1.3,'
                  'aecho=0.85:0.7:55|190:0.28|0.16'),
}
FX_PRESETS['wide'] = FX_PRESETS['harmonica'] + ',extrastereo=m=1.6'

# ── SF2（GM 音源）离线渲染：Node + js-synthesizer(FluidSynth wasm) ──
DEFAULT_SF2 = _first_existing(
    _here('soundfonts', 'GeneralUser-GS.sf2'),
    r'D:\deepseek\tools\soundfonts\GeneralUser-GS.sf2')
SF2_RENDERER = _first_existing(
    _here('sf2_render.cjs'),
    r'D:\deepseek\tools\sf2_render.cjs')
SF2_ENGINE_DIR = _first_existing(
    _here('engine'),
    r'D:\deepseek\kouqin\web-harmonica')
NODE_CANDIDATES = [
    _here('node', 'node.exe'),
    _here('node.exe'),
    r'C:\Program Files\nodejs\node.exe',
    r'C:\Users\Lenovo\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe',
]
# GM 音色名 → program 号（中文名和英文名都认）
GM_PROGRAMS = {
    '钢琴': 0, 'piano': 0, '大钢琴': 0, 'grand': 0,
    '亮钢琴': 1, 'bright': 1, '电钢': 4, 'epiano': 4,
    '八音盒': 10, 'musicbox': 10, '管风琴': 19, 'organ': 19,
    '吉他': 24, 'guitar': 24, '尼龙吉他': 24, '钢弦吉他': 25,
    '贝斯': 33, 'bass': 33, '小提琴': 40, 'violin': 40,
    '中提琴': 41, 'viola': 41, '大提琴': 42, 'cello': 42,
    '竖琴': 46, 'harp': 46, '弦乐': 48, 'strings': 48,
    '合唱': 52, 'choir': 52, '小号': 56, 'trumpet': 56,
    '长号': 57, 'trombone': 57, '萨克斯': 65, 'sax': 65,
    '双簧管': 68, 'oboe': 68, '长笛': 73, 'flute': 73,
    '排箫': 75, 'panflute': 75, '口琴': 22, 'harmonica': 22,
}

_ffmpeg_cache = {'path': None, 'filters': None}


# ────────────────────────────── ffmpeg ──────────────────────────────
def find_ffmpeg():
    if _ffmpeg_cache['path'] is not None:
        return _ffmpeg_cache['path'] or None
    found = shutil.which('ffmpeg')
    if not found:
        for p in FFMPEG_CANDIDATES:
            if os.path.isfile(p):
                found = p
                break
    _ffmpeg_cache['path'] = found or ''
    return found


def has_filter(ffmpeg, name):
    if _ffmpeg_cache['filters'] is None:
        try:
            r = subprocess.run([ffmpeg, '-hide_banner', '-filters'],
                               capture_output=True, text=True, errors='replace')
            _ffmpeg_cache['filters'] = r.stdout or ''
        except Exception:
            _ffmpeg_cache['filters'] = ''
    return re.search(r'^\s*\S*\s+' + re.escape(name) + r'\s', _ffmpeg_cache['filters'], re.M) is not None


def find_node():
    """找 Node 解释器（SF2 离线渲染要用）。"""
    n = shutil.which('node') or shutil.which('node.exe')
    if n:
        return n
    for p in NODE_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def render_via_sf2(events, bpm, out_wav, soundfont, program, reverb=70, gain=0.8,
                   rate=SAMPLE_RATE, verbose=True):
    """用 Node + FluidSynth(wasm) 把事件渲染成 WAV。返回 (成功?, 说明)。"""
    node = find_node()
    if not node:
        return False, '没找到 Node（SF2 渲染需要它）'
    if not os.path.isfile(SF2_RENDERER):
        return False, f'缺少渲染器脚本: {SF2_RENDERER}'
    if not os.path.isfile(soundfont):
        return False, f'找不到音源: {soundfont}'

    beat = 60.0 / bpm
    evs, t = [], 0.0
    for midi, beats, gap in events:
        dur = beats * beat
        if midi is not None:
            evs.append([round(t, 4), int(midi), round(dur * 0.95, 4)])
        t += dur + gap * beat
    ev_json = os.path.splitext(out_wav)[0] + '.events.json'
    with open(ev_json, 'w', encoding='utf-8') as f:
        json.dump({'bpm': bpm, 'events': evs}, f)

    cmd = [node, SF2_RENDERER, '--sf2', soundfont, '--events', ev_json, '--wav', out_wav,
           '--engine-dir', SF2_ENGINE_DIR,
           '--program', str(int(program)), '--gain', str(gain), '--reverb', str(int(reverb)),
           '--rate', str(int(rate))]
    r = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    ok = (r.returncode == 0 and os.path.isfile(out_wav))
    msg = (r.stdout or '').strip() or (r.stderr or '').strip()
    if verbose and ok and msg:
        print('  ' + msg.splitlines()[-1].strip())
    return ok, msg


def encode_with_fx(wav_path, out_path, fx='harmonica', lufs=-16.0, tp=-1.5, lra=11.0, bitrate='192k'):
    """一次 ffmpeg 走完：效果链 + 响度标准化 + 编码。返回 (成功?, 说明)。"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, '没找到 ffmpeg'
    ext = os.path.splitext(out_path)[1].lower()
    codec = ['-codec:a', 'libmp3lame', '-b:a', bitrate] if ext == '.mp3' else ['-codec:a', 'pcm_s16le']

    chain = []
    if fx and fx != 'none':
        chain.append(FX_PRESETS.get(fx, FX_PRESETS['harmonica']))
    if lufs is not None and has_filter(ffmpeg, 'loudnorm'):
        chain.append(f'loudnorm=I={lufs}:TP={tp}:LRA={lra}:print_format=json')
    af = ','.join(x for x in chain if x)

    cmd = [ffmpeg, '-y', '-hide_banner', '-i', wav_path, '-ar', str(SAMPLE_RATE)]
    if af:
        cmd += ['-af', af]
    cmd += codec + [out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
    if r.returncode != 0 or not os.path.isfile(out_path):
        tail = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''
        return False, f'ffmpeg 失败（返回码 {r.returncode}）：{tail}'

    info = ''
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            info = (f"响度标准化 {d.get('input_i')} → {d.get('output_i')} LUFS，"
                    f"峰值 {d.get('input_tp')} → {d.get('output_tp')} dBTP")
        except Exception:
            pass
    return True, info


# ────────────────────────────── 简谱解析 ──────────────────────────────
def key_to_midi_base(key):
    """'1=C' / 'C' / 'D' / 'F#' / 'Bb' → 中音 1 对应的 MIDI 音高（C4=60 起算）。"""
    k = str(key).strip().upper()
    if k.startswith('1='):
        k = k[2:]
    acc = 0
    while k and k[0] in '#♯B♭':
        acc += 1 if k[0] in '#♯' else -1
        k = k[1:]
    if k and k[0] not in KEY_SEMITONES:
        raise ValueError(f'不认识的调号: {key}')
    return 60 + KEY_SEMITONES.get(k[0], 0) + acc


def _apply_marks(text, octave_shift, i, beats, dotted, halves, extends, tie):
    n = len(text)
    while i < n:
        c = text[i]
        if c in "'^+":
            octave_shift += 1
            i += 1
        elif c == ',':
            octave_shift -= 1
            i += 1
        elif c == '.':
            dotted += 1
            i += 1
        elif c == '/':
            halves += 1
            i += 1
        elif c == '-':
            extends += 1
            i += 1
        elif c == '~':
            tie = True
            i += 1
        elif c == ':':
            m = re.match(r':(\d+(?:\.\d+)?)', text[i:])
            if m:
                beats = float(m.group(1))
                i += m.end()
            break
        else:
            break
    return i, octave_shift, beats, dotted, halves, extends, tie


def parse_event(text, i, base, force_low=0):
    n = len(text)
    acc = 0
    octave_shift = -force_low
    while i < n and text[i] in '#♯b♭_':
        if text[i] in '#♯':
            acc += 1
        elif text[i] in 'b♭':
            acc -= 1
        else:
            octave_shift -= 1
        i += 1
    if i >= n or not text[i].isdigit():
        return None, i
    deg = int(text[i])
    i += 1
    beats, dotted, halves, extends, tie = 1.0, 0, 0, 0, False
    i, octave_shift, beats, dotted, halves, extends, tie = _apply_marks(
        text, octave_shift, i, beats, dotted, halves, extends, tie)
    beats = beats / (2 ** halves)
    beats *= (2 - 0.5 ** dotted)
    beats += extends
    midi = None if deg == 0 else (base + DEGREE_SEMITONES[deg - 1] + acc + 12 * octave_shift)
    return {'midi': midi, 'beats': beats, 'tie': tie}, i


def parse_tune(text, key='C'):
    """简谱文本 → 事件列表 [[midi|None, beats, gap_beats], ...]"""
    base = key_to_midi_base(key)
    events, pending_gap, pending_tie = [], 0.0, False
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            pending_gap += 1.0 if c == '\n' else 0.25
            i += 1
            continue
        if c == '|':
            k = 0
            while i < n and text[i] == '|':
                k += 1
                i += 1
            if k >= 2:
                pending_gap += 1.0
            continue
        if c in '（(':
            j = i + 1
            inner = ''
            while j < n and text[j] not in '）)':
                inner += text[j]
                j += 1
            ev = None
            if inner.strip():
                ev, _ = parse_event(inner.strip(), 0, base, force_low=1)
            i = j + 1 if j < n else j
            if ev is None:
                print(f'  警告：括号里没解析出音符: （{inner}）')
                continue
        else:
            ev, i = parse_event(text, i, base)
            if ev is None:
                print(f'  跳过无效字符: {c!r}')
                i += 1
                continue

        if pending_gap:
            if events:
                events[-1][2] += pending_gap
            pending_gap = 0.0

        merged = False
        if ev['tie'] and events and events[-1][0] == ev['midi']:
            events[-1][1] += ev['beats']
            merged = True
        elif pending_tie and events and events[-1][0] == ev['midi']:
            events[-1][1] += ev['beats']
            merged = True
            pending_tie = False
        if not merged:
            events.append([ev['midi'], ev['beats'], 0.0])
            pending_tie = bool(ev['tie']) and ev['midi'] is not None

    if pending_gap and events:
        events[-1][2] += pending_gap
    return events


# ────────────────────────────── 采样音源 ──────────────────────────────
def read_wav(path):
    """读 16bit 单/多声道 WAV，返回 (array('h') 单声道, 采样率)。"""
    with wave.open(path, 'rb') as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
        sw = w.getsampwidth()
    if sw != 2:
        raise ValueError(f'{path}: 只支持 16bit WAV（当前 {sw*8}bit）')
    a = array.array('h')
    a.frombytes(raw)
    if ch > 1:
        mono = array.array('h', [0]) * (len(a) // ch)
        for i in range(len(mono)):
            mono[i] = int(sum(a[i * ch:(i + 1) * ch]) / ch)
        a = mono
    return a, sr


class Sampler:
    """按 SFZ 定义演奏 basic-harmonica 采样（含循环与释放音）。"""

    def __init__(self, sfz_path=DEFAULT_SFZ, wav_dir=DEFAULT_WAV_DIR, verbose=True):
        self.regions, self.releases = [], []
        self.cache = {}
        self.load_sfz(sfz_path, wav_dir, verbose)

    def load_sfz(self, sfz_path, wav_dir, verbose):
        txt = open(sfz_path, encoding='utf-8', errors='replace').read()
        group = {}          # 当前 <group> 的公共参数
        is_release_group = False
        for line in txt.splitlines():
            line = re.sub(r'//.*$', '', line).strip()
            if not line:
                continue
            if line.startswith('<group>'):
                group = {}
                # group 参数在后续行里，这里先重置
                self._pending_group = group
                is_release_group = False
                continue
            kv = dict(re.findall(r'(\w+)=("[^"]*"|\S+)', line))
            if 'trigger' in kv and kv['trigger'] == 'release':
                is_release_group = True
                group['trigger'] = 'release'
            if 'volume' in kv:          # 注意：SFZ 里 volume 写在 trigger 之前，必须无条件读
                group['volume'] = float(kv['volume'])
            if 'ampeg_attack' in kv and 'sample' not in kv:
                group.update({k: float(v) for k, v in kv.items() if k.startswith('ampeg')})
                continue
            if 'sample' not in kv:
                continue

            sample = kv['sample'].strip('"')
            base = os.path.splitext(os.path.basename(sample))[0]
            wav = os.path.join(wav_dir, base + '.wav')
            if not os.path.isfile(wav):
                if verbose:
                    print(f'  ⚠️ 缺采样文件: {wav}')
                continue
            data, sr = read_wav(wav)
            reg = {
                'data': data, 'sr': sr,
                'lokey': int(kv.get('lokey', 0)), 'hikey': int(kv.get('hikey', 127)),
                'key': int(kv.get('key', 60)), 'tune': float(kv.get('tune', 0)),
                'volume': float(group.get('volume', 0.0)),
                'attack': float(group.get('ampeg_attack', 0.02)),
                'release': float(group.get('ampeg_release', 0.07)),
                'name': base,
            }
            if group.get('trigger') == 'release':
                self.releases.append(reg)
            else:
                # 统一响度：按 RMS 归一，避免各采样音量不齐
                n = max(1, len(data))
                rms = math.sqrt(sum(float(v) * v for v in data[::max(1, n // 20000)]) /
                                max(1, len(data[::max(1, n // 20000)]))) / 32768
                reg['rms'] = max(1e-6, rms)
                self.regions.append(reg)

    def _pick(self, midi, pool):
        hit = [r for r in pool if r['lokey'] <= midi <= r['hikey']]
        if not hit:
            hit = sorted(pool, key=lambda r: abs(r['key'] - midi))[:1]
        return hit[0]

    @staticmethod
    def _resample(data, ratio, out_len):
        """线性插值重采样；升调时先做盒式平均预滤波，抑制混叠。"""
        if ratio > 1.0:
            w = int(math.ceil(ratio))
            if w > 1:
                acc, run = 0, 0
                filt = array.array('h', [0]) * (len(data) // w)
                for i in range(len(filt)):
                    s = sum(data[i * w:(i + 1) * w]) / w
                    filt[i] = int(s)
                data = filt
        n = len(data)
        out = array.array('h', [0]) * out_len
        for i in range(out_len):
            x = i * ratio
            i0 = int(x)
            if i0 >= n - 1:
                break
            frac = x - i0
            out[i] = int(data[i0] * (1 - frac) + data[i0 + 1] * frac)
        return out

    def note(self, midi, seconds, amp=0.5, level_match=True):
        """合成一个音（源索引映射实现循环 + 释放音尾巴），返回 array('h')。"""
        reg = self._pick(midi, self.regions)
        rel = self._pick(midi, self.releases) if self.releases else None
        ck = (midi, round(seconds, 3), round(amp, 3), level_match)
        if ck in self.cache:
            return self.cache[ck]

        ratio = (2.0 ** ((midi - reg['key']) / 12.0)) * (2.0 ** (reg['tune'] / 1200.0))
        src = reg['data']
        base_gain = amp * (0.7 / reg['rms'] if level_match else 1.0)
        if reg['volume']:
            base_gain *= 10 ** (reg['volume'] / 20.0)

        # 升调时先做盒式平均（抗混叠），再线性插值
        work = src
        if ratio > 1.0:
            w = int(math.ceil(ratio))
            if w > 1:
                work = array.array('h', [0]) * (len(src) // w)
                for i in range(len(work)):
                    work[i] = int(sum(src[i * w:(i + 1) * w]) / w)
        n = len(work)
        loop_s = int(n * 0.30)                 # 循环区取中段，避开起音
        loop_e = max(loop_s + 1, int(n * 0.95))
        out_len = int(SAMPLE_RATE * max(0.0, seconds))
        atk = max(1, int(SAMPLE_RATE * reg['attack']))
        rel_n = max(1, int(SAMPLE_RATE * reg['release']))
        out = array.array('h', [0]) * out_len
        for i in range(out_len):
            x = i * ratio
            if x >= loop_e:                    # 超出采样尾部 → 折回循环区
                x = loop_s + (x - loop_s) % (loop_e - loop_s)
            i0 = int(x)
            if i0 >= n - 1:
                break
            fr = x - i0
            v = work[i0] * (1.0 - fr) + work[i0 + 1] * fr
            g = base_gain
            if i < atk:
                g *= i / atk
            if i > out_len - rel_n:
                g *= (out_len - i) / rel_n
            out[i] = int(max(-1.0, min(1.0, v / 32768.0 * g)) * 32767)

        # 释放音：接在音符末尾（模拟松口/离键的收尾）
        if rel is not None:
            r_ratio = (2.0 ** ((midi - rel['key']) / 12.0)) * (2.0 ** (rel['tune'] / 1200.0))
            r_src = rel['data']
            r_len = int(len(r_src) / max(1e-6, r_ratio))
            r_gain = base_gain * (10 ** (rel['volume'] / 20.0)) * 0.9
            r_atk = max(1, int(SAMPLE_RATE * rel.get('attack', 0.04)))
            r = array.array('h', [0]) * r_len
            for i in range(r_len):
                x = i * r_ratio
                i0 = int(x)
                if i0 >= len(r_src) - 1:
                    break
                fr = x - i0
                v = r_src[i0] * (1.0 - fr) + r_src[i0 + 1] * fr
                g = r_gain * (i / r_atk if i < r_atk else 1.0)
                r[i] = int(max(-1.0, min(1.0, v / 32768.0 * g)) * 32767)
            out = out + r

        self.cache[ck] = out
        return out


# ────────────────────────────── 正弦波退路 ──────────────────────────────
def tone_pcm(midi, seconds, amp=0.5, vibrato=0.0):
    total = int(SAMPLE_RATE * max(0.0, seconds))
    out = array.array('h', [0]) * total
    if total <= 0:
        return out
    freq = 440.0 * (2.0 ** ((midi - 69) / 12.0))
    atk = max(1, int(SAMPLE_RATE * 0.008))
    dec = max(1, int(SAMPLE_RATE * 0.06))
    rel = max(1, min(int(SAMPLE_RATE * 0.04), total // 4))
    w = 2.0 * math.pi * freq / SAMPLE_RATE
    vib_w = 2.0 * math.pi * 5.0 / SAMPLE_RATE
    depth = vibrato * 0.012
    for k in range(total):
        if k < atk:
            env = k / atk
        elif k < atk + dec:
            env = 1.0 - 0.25 * (k - atk) / dec
        else:
            env = 0.75
        if k > total - rel:
            env *= (total - k) / rel
        phase = w * k
        if depth:
            phase += depth * math.sin(vib_w * k)
        out[k] = int(max(-1.0, min(1.0, math.sin(phase) * env * amp)) * 32767)
    return out


# ────────────────────────────── 混音渲染 ──────────────────────────────
def render(events, bpm=120.0, amp=0.5, vibrato=0.0, engine='sampler',
           sampler=None, sounding_ratio=0.98, verbose=True):
    """把事件列表渲染成 16bit 单声道 PCM（重叠自动混音）。"""
    beat = 60.0 / bpm
    # 先排时间轴
    timeline, t = [], 0.0
    for midi, beats, gap in events:
        dur = beats * beat
        timeline.append((t, midi, dur))
        t += dur + gap * beat
    total = int(SAMPLE_RATE * (t + 1.0))

    acc = array.array('l', [0]) * total
    for start, midi, dur in timeline:
        if midi is None:
            continue
        snd = dur * sounding_ratio
        if engine == 'sampler' and sampler is not None:
            pcm = sampler.note(midi, snd, amp=amp)
        else:
            pcm = tone_pcm(midi, snd, amp=amp, vibrato=vibrato)
        off = int(start * SAMPLE_RATE)
        for i, v in enumerate(pcm):
            j = off + i
            if j >= total:
                break
            acc[j] += v

    # 归一化防削波
    peak = max((abs(v) for v in acc), default=0)
    if peak > 32767:
        k = 32700.0 / peak
        acc = array.array('l', [int(v * k) for v in acc])
    return array.array('h', [max(-32768, min(32767, v)) for v in acc])


def pcm_to_wav(pcm, path):
    with wave.open(path, 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(pcm.tobytes())


def pcm_to_segment(pcm):
    if AudioSegment is None:
        return None
    return AudioSegment(pcm.tobytes(), sample_width=2, frame_rate=SAMPLE_RATE, channels=1)


# ────────────────────────────── 主流程 ──────────────────────────────
def number_to_mp3(tune_str, output_file='melody.mp3', bpm=120.0, key='C',
                  lufs=-16.0, tp=-1.5, lra=11.0, amp=0.5, vibrato=0.0,
                  engine='sine', sfz=DEFAULT_SFZ, wav_dir=DEFAULT_WAV_DIR,
                  fx='light', soundfont=DEFAULT_SF2, program=0, reverb=70,
                  verbose=True):
    """简谱字符串 → 音频文件（MP3 需 ffmpeg；没有 ffmpeg 时自动改存 WAV）。

    engine : 'sine' 正弦波（默认，快） / 'sf2' GM 音源（287 种音色）
             / 'sampler' 实验性 Python 采样器（有循环与释放音缺陷，不推荐）
    program: GM 音色号（engine='sf2' 时生效）：0=大钢琴 40=小提琴 73=长笛 24=吉他 48=弦乐…
    """
    events = parse_tune(tune_str, key=key)
    if not events:
        raise ValueError('简谱里没解析出任何音符')
    total_beats = sum(b + g for _, b, g in events)
    if verbose:
        print(f'  解析出 {len(events)} 个事件，共 {total_beats:.2f} 拍 '
              f'（{total_beats * 60 / bpm:.2f} 秒 @ {bpm:g}BPM, 1={str(key).upper().replace("1=", "")}）')

    tmpdir = tempfile.mkdtemp(prefix='jianpu_')
    wav_tmp = os.path.join(tmpdir, 'raw.wav')
    pcm = None
    try:
        if engine == 'sf2':
            if verbose:
                print(f'  音源: GM program {program} + {os.path.basename(soundfont)}')
            ok, msg = render_via_sf2(events, bpm, wav_tmp, soundfont, program,
                                     reverb=reverb, verbose=verbose)
            if not ok:
                last = msg.splitlines()[-1].strip() if msg else '未知原因'
                print(f'  ⚠️ SF2 渲染失败（{last}），改用正弦波')
                engine = 'sine'

        if engine != 'sf2':
            sampler = None
            if engine == 'sampler':
                if os.path.isfile(sfz):
                    try:
                        sampler = Sampler(sfz, wav_dir, verbose=verbose)
                        if verbose:
                            print(f'  音源: {len(sampler.regions)} 个音高区域 + '
                                  f'{len(sampler.releases)} 个释放音（{os.path.basename(sfz)}）')
                    except Exception as e:
                        print(f'  ⚠️ 采样音源加载失败（{e}），改用正弦波')
                        engine = 'sine'
                else:
                    if verbose:
                        print(f'  ⚠️ 找不到 SFZ: {sfz}，改用正弦波')
                    engine = 'sine'
            pcm = render(events, bpm=bpm, amp=amp, vibrato=vibrato, engine=engine,
                         sampler=sampler, verbose=verbose)
            pcm_to_wav(pcm, wav_tmp)

        seconds = seconds_est = total_beats * 60 / bpm
        try:
            with wave.open(wav_tmp, 'rb') as w:
                seconds = w.getnframes() / float(w.getframerate())
        except Exception:
            pass

        want = None if lufs in (None, 0, 0.0) else lufs
        ok, info = encode_with_fx(wav_tmp, output_file, fx=fx, lufs=want, tp=tp, lra=lra)
        if not ok:
            out_wav = os.path.splitext(output_file)[0] + '.wav'
            seg = pcm_to_segment(pcm) if pcm is not None else None
            if seg is not None:
                seg.export(out_wav, format='wav')
            else:
                shutil.copyfile(wav_tmp, out_wav)
            output_file = out_wav
            if verbose:
                print(f'  ⚠️ {info}')
                print(f'  已改存 WAV: {output_file}')
        elif verbose:
            if info:
                print('  ' + info)
            print(f'  已生成: {output_file}  （{seconds:.2f} 秒）')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return output_file


# ────────────────────────────── 内置示例 ──────────────────────────────
DEMOS = {
    '两只老虎': dict(tune='1 2 3 1 | 1 2 3 1 | 3 4 5- | 3 4 5- | '
                          '5 6 5 4 3 1 | 5 6 5 4 3 1 | 1 5, 1- | 1 5, 1- ||',
                     bpm=120, key='C'),
    '小星星': dict(tune='1 1 5 5 | 6 6 5- | 4 4 3 3 | 2 2 1- | '
                         '5 5 4 4 | 3 3 2- | 5 5 4 4 | 3 3 2- | '
                         '1 1 5 5 | 6 6 5- | 4 4 3 3 | 2 2 1-',
                   bpm=112, key='C'),
    '音阶与记号演示': dict(tune="1 2 3 4 5 6 7 1' | 1' 7 6 5 4 3 2 1 || "
                               "1, 2, 3, 4, 5, 6, 7, 1 | （1）2 3 4 5 6 7 1 || "
                               "1/ 2/ 3/ 4/ 5/ 6/ 7/ 1'/ | 1. 2. 3. 4. | #4 b7 0 5",
                          bpm=100, key='C'),
    '音色对比': dict(tune='1 2 3 4 5 6 7 1\' 1\' 7 6 5 4 3 2 1 | '
                          '1 3 5 1\' 5 3 1 | 6, 1 3 6 3 1 6,', bpm=96, key='C'),
}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='简谱数字 → 音乐音频（正弦波 / 287 种 GM 音色 / 口琴采样 + ffmpeg 后处理 + loudnorm）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='记号说明见本文件开头注释；--demo list 看内置示例；--gm list 看可用音色名。')
    ap.add_argument('tune', nargs='?', help='简谱字符串，如 "1 2 3 1|3 4 5-"。省略则跑内置《两只老虎》')
    ap.add_argument('-o', '--out', default=None, help='输出文件名')
    ap.add_argument('--bpm', type=float, default=120.0, help='速度，默认 120')
    ap.add_argument('--key', default='C', help="调号，如 C / D / F# / '1=D'，默认 C")
    ap.add_argument('--engine', choices=['sine', 'sf2', 'sampler'], default='sine',
                    help='音源：sine=正弦波（默认，快）；sf2=GM 音源（287 种音色，推荐）；sampler=实验性采样器')
    ap.add_argument('--gm', default=None,
                    help='GM 音色名：钢琴/电钢/吉他/小提琴/大提琴/弦乐/长笛/小号/萨克斯/竖琴/管风琴…（写 list 看全部）')
    ap.add_argument('--program', type=int, default=0,
                    help='GM 音色号（--gm 的等价写法）：0=大钢琴 24=吉他 40=小提琴 48=弦乐 73=长笛')
    ap.add_argument('--soundfont', default=DEFAULT_SF2, help='SF2 音源路径（默认 GeneralUser GS）')
    ap.add_argument('--reverb', type=int, default=70, help='SF2 引擎混响量 0~127，默认 70')
    ap.add_argument('--fx', choices=list(FX_PRESETS), default='light',
                    help='后处理效果链，默认 light（轻微 EQ+压缩）；harmonica 更重，none 为干声')
    ap.add_argument('--lufs', default='-16', help='响度标准化目标（LUFS），默认 -16；off 表示不做')
    ap.add_argument('--sfz', default=DEFAULT_SFZ, help='SFZ 音源路径（sampler 引擎用）')
    ap.add_argument('--wav-dir', default=DEFAULT_WAV_DIR, help='采样 WAV 目录')
    ap.add_argument('--vibrato', type=float, default=0.0, help='颤音深度（仅 sine 引擎）')
    ap.add_argument('--amp', type=float, default=0.5, help='合成振幅 0~1，默认 0.5')
    ap.add_argument('--demo', nargs='?', const='list', help='跑内置示例：--demo 两只老虎 / --demo list')
    args = ap.parse_args(argv)

    lufs = None if str(args.lufs).lower() in ('off', 'none', 'no', '0') else float(args.lufs)

    program = args.program
    if args.gm:
        g = str(args.gm).strip().lower()
        if g in ('list', 'all'):
            cn = sorted({k for k in GM_PROGRAMS if not k.isascii()}, key=lambda k: GM_PROGRAMS[k])
            print('可用 GM 音色名（中文）：')
            print('  ' + ' / '.join(cn))
            print('也可以用 --program <0~127> 直接指定音色号')
            return 0
        if g in GM_PROGRAMS:
            program = GM_PROGRAMS[g]
        elif g.isdigit():
            program = int(g)
        else:
            print(f'⚠️ 不认识的音色名: {args.gm}（用 --gm list 看可用列表）')
            return 2

    common = dict(lufs=lufs, engine=args.engine, sfz=args.sfz, wav_dir=args.wav_dir,
                  fx=args.fx, amp=args.amp, vibrato=args.vibrato,
                  soundfont=args.soundfont, program=program, reverb=args.reverb)

    if args.demo:
        if args.demo == 'list' or args.demo not in DEMOS:
            print('内置示例：' + ' / '.join(DEMOS))
            if args.demo == 'list':
                return 0
        name = args.demo if args.demo in DEMOS else '两只老虎'
        d = DEMOS[name]
        number_to_mp3(d['tune'], args.out or f'{name}.mp3',
                      bpm=args.bpm if args.bpm != 120 else d['bpm'],
                      key=args.key if args.key != 'C' else d['key'], **common)
        return 0

    if args.tune:
        number_to_mp3(args.tune, args.out or 'melody.mp3', bpm=args.bpm, key=args.key, **common)
        return 0

    print('▶ 默认《两只老虎》（传简谱字符串或 --demo 可以换）')
    number_to_mp3(DEMOS['两只老虎']['tune'], 'two_tigers.mp3', bpm=120, key='C', **common)
    return 0


if __name__ == '__main__':
    sys.exit(main())
