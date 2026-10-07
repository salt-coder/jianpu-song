/* sf2_render.cjs —— 用 FluidSynth(wasm) 把音符事件离线渲染成 WAV（无需浏览器、无需音频设备）
 *
 * 为什么不用 MIDI 文件：Python 那边已经有事件列表了，直接传 JSON 更省事、还免了写 MIDI 解析器。
 *
 * 用法:
 *   node sf2_render.cjs --sf2 <音源.sf2> --events <事件.json> --wav <输出.wav>
 *                       [--program 0] [--rate 44100] [--gain 0.8] [--reverb 60] [--tail 1.5]
 *                       [--engine-dir D:/deepseek/kouqin/web-harmonica]
 *
 * 事件 JSON 格式: {"bpm":120, "events":[[起始秒, MIDI音高, 时长秒], ...]}
 */
const fs = require('fs');
const path = require('path');

function arg(name, def) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : def;
}

const SF2 = arg('sf2');
const EVENTS = arg('events');
const WAV = arg('wav');
const PROGRAM = parseInt(arg('program', '0'), 10);
const RATE = parseInt(arg('rate', '44100'), 10);
const GAIN = parseFloat(arg('gain', '0.8'));
const REVERB = parseInt(arg('reverb', '60'), 10);
const CHORUS = parseInt(arg('chorus', '0'), 10);
const TAIL = parseFloat(arg('tail', '1.5'));
const ENGINE_DIR = arg('engine-dir', path.join(__dirname, 'engine'));

if (!SF2 || !EVENTS || !WAV) {
  console.error('用法: node sf2_render.cjs --sf2 x.sf2 --events e.json --wav out.wav [--program 0]');
  process.exit(2);
}

/**
 * 加载 js-synthesizer（UMD 包）——不能用 require()。
 * QQ Agent 的 resources/app 下若有 "type":"module"，这里的 .js 会被当成 ESM，
 * UMD 包装就会崩（报 Cannot set properties of undefined (setting 'JSSynth')）。
 * 所以统一用 CJS 包装函数加载，与所在目录的 package.json 无关。
 */
function loadJSSynth(file) {
  const code = fs.readFileSync(file, 'utf8');
  const mod = { exports: {} };
  const wrapper = new Function('exports', 'module', 'require', '__filename', '__dirname', code);
  wrapper(mod.exports, mod, require, file, path.dirname(file));
  return mod.exports.JSSynth || mod.exports;
}

function writeWav(pcm, rate, file) {  const n = pcm.length;
  const buf = Buffer.alloc(44 + n * 2);
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write('WAVE', 8);
  buf.write('fmt ', 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22); buf.writeUInt32LE(rate, 24);
  buf.writeUInt32LE(rate * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34);
  buf.write('data', 36); buf.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++) {
    let v = Math.max(-1, Math.min(1, pcm[i]));
    buf.writeInt16LE(Math.round(v * 32767), 44 + i * 2);
  }
  fs.writeFileSync(file, buf);
}

(async () => {
  const t0 = Date.now();
  const spec = JSON.parse(fs.readFileSync(EVENTS, 'utf8'));
  const evs = (spec.events || []).slice().sort((a, b) => a[0] - b[0]);
  if (!evs.length) { console.error('事件为空'); process.exit(3); }
  const endSec = Math.max(...evs.map((e) => e[0] + e[2])) + TAIL;

  global.require = require;
  global.__dirname = ENGINE_DIR;
  (0, eval)(fs.readFileSync(path.join(ENGINE_DIR, 'libfluidsynth-2.4.6.js'), 'utf8'));
  const JSSynth = loadJSSynth(path.join(ENGINE_DIR, 'js-synthesizer.min.js'));
  await JSSynth.waitForReady();

  const synth = new JSSynth.Synthesizer();
  synth.init(RATE);
  const b = fs.readFileSync(SF2);
  const id = await synth.loadSFont(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
  synth.setGain(GAIN);
  synth.midiProgramSelect(0, id, 0, PROGRAM);
  if (REVERB) synth.midiControl(0, 91, REVERB);   // 混响发送
  if (CHORUS) synth.midiControl(0, 93, CHORUS);   // 合唱发送

  const N = 1024;
  const blocks = Math.ceil((endSec * RATE) / N);
  const out = new Float32Array(blocks * N);
  let idx = 0;
  const offs = [];                                 // [结束时刻, 音高]
  for (let blk = 0; blk < blocks; blk++) {
    const now = (blk * N) / RATE;
    while (idx < evs.length && evs[idx][0] <= now) {
      const [st, m, d] = evs[idx++];
      synth.midiNoteOn(0, Math.max(0, Math.min(127, m)), 100);
      offs.push([st + d, m]);
    }
    for (let i = offs.length - 1; i >= 0; i--) {
      if (offs[i][0] <= now) { synth.midiNoteOff(0, offs[i][1]); offs.splice(i, 1); }
    }
    const L = new Float32Array(N), R = new Float32Array(N);
    synth.render([L, R]);
    for (let i = 0; i < N; i++) out[blk * N + i] = (L[i] + R[i]) * 0.5;
  }

  // 防削波
  let peak = 0;
  for (let i = 0; i < out.length; i++) { const v = Math.abs(out[i]); if (v > peak) peak = v; }
  if (peak > 1) { const k = 0.99 / peak; for (let i = 0; i < out.length; i++) out[i] *= k; }

  writeWav(out, RATE, WAV);
  console.log(`  渲染完成: ${(out.length / RATE).toFixed(2)} 秒, ${(out.length / RATE).toFixed(1)}s 音频, ` +
              `峰值 ${peak.toFixed(3)}, program ${PROGRAM}, 用时 ${((Date.now() - t0) / 1000).toFixed(1)} 秒`);
})().catch((e) => { console.error('渲染失败: ' + (e && e.stack ? e.stack : e)); process.exit(1); });
