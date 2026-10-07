#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多线程分段下载器（支持正确的断点续传）。

关键点：每段下载**追加**写入自己的分段文件（open(..., 'ab')），
而不是像 curl -o 那样截断重写 —— 否则续传时偏移量和文件长度会对不上。

用法:
  python dl_gh.py <url> <输出文件> [--threads 4] [--size N] [--timeout 60]
完成后校验：文件大小一致 + 头部字节（若给了 --magic 则校验）
"""
import argparse
import os
import sys
import threading
import time
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) dsh-downloader'}
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 直连


def head_size(url, timeout=30):
    try:
        req = urllib.request.Request(url, headers=UA, method='HEAD')
        r = OPENER.open(req, timeout=timeout)
        n = r.headers.get('Content-Length')
        return int(n) if n else 0
    except Exception:
        return 0


def fetch_part(url, start, end, path, results, idx, timeout=60, retries=60):
    want = end - start + 1
    for attempt in range(retries):
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have == want:
            results[idx] = ('ok', want); return
        if have > want:
            os.remove(path); have = 0
        try:
            req = urllib.request.Request(
                url, headers={**UA, 'Range': f'bytes={start + have}-{end}'})
            r = OPENER.open(req, timeout=timeout)
            with open(path, 'ab') as f:            # ← 追加，不是覆盖
                while True:
                    b = r.read(65536)
                    if not b:
                        break
                    f.write(b)
        except Exception:
            time.sleep(1.5)
        have = os.path.getsize(path) if os.path.exists(path) else 0
        results[idx] = ('...', have)
    have = os.path.getsize(path) if os.path.exists(path) else 0
    results[idx] = ('ok' if have == want else 'fail', have)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('url')
    ap.add_argument('out')
    ap.add_argument('--threads', type=int, default=4)
    ap.add_argument('--size', type=int, default=0, help='已知文件总大小（0=自己探测）')
    ap.add_argument('--magic', default='', help='期望的文件头（如 RIFF）')
    args = ap.parse_args(argv)

    size = args.size or head_size(args.url)
    if size <= 0:
        print('❌ 探测不到文件大小'); return 1
    print(f'目标 {size/1024/1024:.2f} MB，{args.threads} 线程', flush=True)

    parts_dir = args.out + '.parts'
    os.makedirs(parts_dir, exist_ok=True)
    n = args.threads
    chunk = (size + n - 1) // n
    ranges = [(i * chunk, min((i + 1) * chunk - 1, size - 1)) for i in range(n)]
    results = {i: ('...', 0) for i in range(n)}

    ths = []
    for i, (s, e) in enumerate(ranges):
        p = os.path.join(parts_dir, f'p{i}')
        t = threading.Thread(target=fetch_part, args=(args.url, s, e, p, results, i),
                             daemon=True)
        t.start(); ths.append(t)

    t0 = time.time()
    while any(t.is_alive() for t in ths):
        time.sleep(10)
        got = sum(v[1] for v in results.values())
        spd = got / max(0.1, time.time() - t0)
        print(f'  {got/1024/1024:6.2f}/{size/1024/1024:.2f} MB  '
              f'({100*got/size:5.1f}%)  {spd/1024:6.0f} KB/s  {time.time()-t0:5.0f}s', flush=True)
    for t in ths:
        t.join()

    missing = [(i, results[i]) for i in range(n) if results[i][0] != 'ok']
    if missing:
        print(f'❌ 有 {len(missing)} 段没下完: {missing}', flush=True)
        return 1

    with open(args.out, 'wb') as out:
        for i in range(n):
            with open(os.path.join(parts_dir, f'p{i}'), 'rb') as f:
                while True:
                    b = f.read(1 << 20)
                    if not b:
                        break
                    out.write(b)
    got = os.path.getsize(args.out)
    dt = time.time() - t0
    print(f'✅ 合并完成 {got/1024/1024:.2f} MB，用时 {dt:.0f} 秒，平均 {got/1024/dt:.0f} KB/s', flush=True)
    if got != size:
        print(f'❌ 大小不符（{got} != {size}）'); return 1
    if args.magic:
        head = open(args.out, 'rb').read(len(args.magic))
        if head != args.magic.encode():
            print(f'❌ 文件头不符: {head!r} != {args.magic!r}'); return 1
        print(f'✅ 文件头校验通过: {head!r}', flush=True)
    for i in range(n):
        os.remove(os.path.join(parts_dir, f'p{i}'))
    os.rmdir(parts_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
