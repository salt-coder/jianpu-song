#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简谱 → 标准 MIDI 文件（供 sfizz / 任何音源引擎渲染）。

这样就能把「简谱记号」和「音色」解耦：
    简谱 ──jianpu_to_midi.py──> MIDI ──sfizz_render + 任意 SFZ──> 钢琴/口琴/弦乐/...

音高约定与 3.py 一致：中音 1 = C4（MIDI 60），1=C 时可 --key D / '1=D' 换调。

用法:
  python jianpu_to_midi.py "1 2 3 1|3 4 5-" out.mid --bpm 120 --key C [--program 0] [--chan 0]
"""
import argparse
import importlib.util
import os
import struct
import sys

TPQ = 480                     # ticks per quarter note
JIANPU_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'kouqin', '3.py')


def load_jianpu_module():
    """复用 3.py 里的简谱解析器，保证记号规则完全一致。"""
    path = os.path.normpath(JIANPU_PY)
    if not os.path.isfile(path):
        raise SystemExit(f'找不到 3.py: {path}')
    spec = importlib.util.spec_from_file_location('jianpu3', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def varint(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def write_midi(events, out_path, bpm=120.0, program=None, chan=0, sounding=0.95):
    """events = [[midi|None, beats, gap_beats], ...] → 标准 MIDI（格式 0）。"""
    raw = []                                  # (绝对 tick, 排序键, 字节)
    t = 0.0
    for midi, beats, gap in events:
        if midi is not None:
            on = int(round(t * TPQ))
            off = max(on + 1, int(round((t + beats * sounding) * TPQ)))
            raw.append((on, 1, bytes([0x90 | chan, max(0, min(127, midi)), 100])))
            raw.append((off, 0, bytes([0x80 | chan, max(0, min(127, midi)), 0])))
        t += beats + gap
    raw.sort(key=lambda x: (x[0], x[1]))

    track = bytearray()
    us = int(round(60000000.0 / bpm))         # 每拍微秒
    track += b'\x00\xff\x51\x03' + struct.pack('>I', us)[1:]
    track += b'\x00\xff\x58\x04\x04\x02\x18\x08'          # 4/4 拍
    if program is not None:
        track += b'\x00' + bytes([0xC0 | chan, program & 0x7F])

    last = 0
    for tick, _k, data in raw:
        track += varint(tick - last) + data
        last = tick
    track += b'\x00\xff\x2f\x00'              # End of Track

    with open(out_path, 'wb') as f:
        f.write(b'MThd' + struct.pack('>IHHH', 6, 0, 1, TPQ))
        f.write(b'MTrk' + struct.pack('>I', len(track)) + bytes(track))
    return len(raw) // 2, t


def main(argv=None):
    ap = argparse.ArgumentParser(description='简谱 → MIDI（记号规则与 3.py 一致）')
    ap.add_argument('tune', help='简谱字符串')
    ap.add_argument('out', help='输出 .mid')
    ap.add_argument('--bpm', type=float, default=120.0)
    ap.add_argument('--key', default='C', help="调号，如 C / D / F# / '1=D'")
    ap.add_argument('--program', type=int, default=None, help='GM 音色号（0=大钢琴），写进 MIDI')
    ap.add_argument('--chan', type=int, default=0, help='MIDI 通道，默认 0')
    args = ap.parse_args(argv)

    jp = load_jianpu_module()
    events = jp.parse_tune(args.tune, key=args.key)
    n, beats = write_midi(events, args.out, bpm=args.bpm, program=args.program, chan=args.chan)
    print(f'  写出 {args.out}: {n} 个音符, {beats:.2f} 拍, {beats*60/args.bpm:.2f} 秒 @ {args.bpm:g}BPM')
    return 0


if __name__ == '__main__':
    sys.exit(main())
