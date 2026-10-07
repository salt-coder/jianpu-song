// 简谱点歌（LLM 型技能）—— 群友发一串简谱数字，机器人在本机用 3.py 合成音乐，并以语音条发出去。
//
// 定位说明：本模块在 skills/ 下，属于 **LLM 型**（"这串数字是不是简谱、对方是不是在点歌"
// 要靠模型读懂人话），所以必须有 registerTool；只提供能力放这里是没人消费的。
//
// 生成链路：3.py（简谱 → 音符事件 → WAV）→ 本技能直接调 ffmpeg（loudnorm + MP3）→ 语音条
//
// v1.0.2 关键设计：**不让 3.py 自己调 ffmpeg**
//   3.py 内部调 ffmpeg 时它是「Node → python → ffmpeg」的孙子进程，在某些权限/沙箱环境下
//   会拿到 EACCES（返回码 4294967283 = -13），表现为只产出 WAV、MP3 静默缺失。
//   所以这里让 3.py 只产出 WAV（它失败时也会用纯 Python 兜底写 WAV），
//   再由本技能以 **Node 的直接子进程** 调 ffmpeg 完成标准化与编码。
// v1.0.3：改为**便携**——工具链（3.py / ffmpeg / node / 音源）跟着技能或 APP_ROOT 走，
//   不再写死某一台机器的路径，方便直接拷给别人的 QQ Agent 用。
//   查找顺序见 scriptCandidates()。
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// 本技能所在目录（用于就地查找工具链）
const SKILL_DIR = path.dirname(fileURLToPath(import.meta.url));

const DEFAULTS = {
  scriptPath: '',
  pythonPath: '',
  instrument: '口琴',
  bpm: 120,
  key: 'C',
  sendAsVoice: true,
  maxNotes: 160,
  maxSeconds: 120,
  timeoutMs: 180000
};

const PY_FALLBACKS = [
  'python',
  'py',
  'C:\\Program Files\\Python313\\python.exe',
  'C:\\Program Files\\Python312\\python.exe',
  'C:\\Program Files\\Python311\\python.exe',
  'C:\\Users\\Lenovo\\AppData\\Local\\Microsoft\\WindowsApps\\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\\python.exe'
];

/** 3.py 的候选位置：便携布局优先，最后才是开发机路径。 */
function scriptCandidates() {
  return [
    process.env.JIANPU_3PY || '',
    path.join(SKILL_DIR, 'tools', '3.py'),                     // 工具链塞在技能内部
    path.join(SKILL_DIR, 'jianpu-tools', '3.py'),
    path.join(SKILL_DIR, '..', '..', 'jianpu-tools', '3.py'),  // <APP_ROOT>/jianpu-tools（推荐）
    path.join(SKILL_DIR, '..', '..', '..', 'jianpu-tools', '3.py'),
    path.join(os.homedir(), 'jianpu-tools', '3.py'),
    path.join(os.homedir(), 'jianpu-portable', '3.py'),
    'D:\\jianpu-portable\\3.py',
    'D:\\deepseek\\kouqin\\3.py'                               // 开发机（向后兼容）
  ].filter(Boolean);
}

function resolveScriptPath(configured) {
  if (configured && fs.existsSync(configured)) return configured;
  const found = scriptCandidates().find((p) => fs.existsSync(p));
  return found || scriptCandidates()[0] || '3.py';
}

/** 工具目录（ffmpeg / node / engine）跟着 3.py 走 —— 便携包里它们与 3.py 同级。 */
function toolDirs(scriptPath) {
  const d = path.dirname(scriptPath || '');
  return [path.join(d, 'ffmpeg', 'bin'), path.join(d, 'node'), path.join(d, 'engine')]
    .filter((p) => fs.existsSync(p));
}

function ffmpegCandidates(scriptPath) {
  const d = path.dirname(scriptPath || '');
  return [
    path.join(d, 'ffmpeg', 'bin', 'ffmpeg.exe'),
    path.join(d, 'ffmpeg.exe'),
    'D:\\deepseek\\tools\\ffmpeg\\bin\\ffmpeg.exe',
    'C:\\Program Files\\Red Giant\\Trapcode Suite\\Tools\\ffmpeg.exe'
  ];
}

const ALLOWED_CHARS = /^[0-7#b♯♭'^+,_./\-~:|\s（）()]+$/;
const NOTE_CHARS = /[0-7]/g;
const VOICE_INSTRUMENTS = new Set(['口琴', '钢琴', '电钢', '八音盒', '吉他', '小提琴', '大提琴', '弦乐', '长笛', '排箫', '萨克斯']);

let getConfig = () => ({ ...DEFAULTS });

function config() {
  const raw = { ...DEFAULTS, ...(getConfig() || {}) };
  const num = (v, min, max, dflt) => {
    const n = Number(v);
    return Number.isFinite(n) ? Math.min(max, Math.max(min, Math.trunc(n))) : dflt;
  };
  return {
    scriptPath: String(raw.scriptPath || DEFAULTS.scriptPath).trim(),
    pythonPath: String(raw.pythonPath || '').trim(),
    instrument: VOICE_INSTRUMENTS.has(String(raw.instrument)) ? String(raw.instrument) : '口琴',
    bpm: num(raw.bpm, 40, 240, 120),
    key: String(raw.key || 'C').trim() || 'C',
    sendAsVoice: raw.sendAsVoice !== false,
    maxNotes: num(raw.maxNotes, 4, 600, 160),
    maxSeconds: num(raw.maxSeconds, 3, 600, 120),
    timeoutMs: num(raw.timeoutMs, 5000, 600000, 180000)
  };
}

function cleanNotation(raw) {
  let s = String(raw ?? '')
    .replace(/[\u3000\u2000-\u200b]/g, ' ')
    .replace(/[，、]/g, ' ')
    .replace(/♯/g, '#')
    .replace(/♭/g, 'b')
    .trim();
  if (!s) return null;
  if (!ALLOWED_CHARS.test(s)) return null;
  s = s.replace(/^[\s\-]+/, '').replace(/\s+/g, ' ').trim();
  if (!s) return null;
  const notes = (s.match(NOTE_CHARS) || []).length;
  if (notes < 1) return null;
  return { notation: s, notes };
}

function firstExisting(list) {
  for (const p of list) if (fs.existsSync(p)) return p;
  return null;
}

/**
 * 找可用的 Python：不只看文件是否存在，而是**真的跑一次 --version**。
 * 这样能绕开「Store 版 python.exe 只是个跳转桩」「WindowsApps 目录不可访问」这类坑。
 */
async function resolvePython(cfg, probeEnv) {
  const cands = [];
  if (cfg.pythonPath) cands.push(cfg.pythonPath);
  if (process.env.JIANPU_PYTHON) cands.push(process.env.JIANPU_PYTHON);
  const local = process.env.LOCALAPPDATA || '';
  const wa = path.join(local, 'Microsoft', 'WindowsApps');
  cands.push(path.join(wa, 'python.exe'));
  try {
    // Microsoft Store 版 Python 的真实路径形如 WindowsApps\PythonSoftwareFoundation.Python.3.11_xxxx\python.exe
    for (const d of fs.readdirSync(wa)) {
      if (/^PythonSoftwareFoundation\.Python\./i.test(d)) cands.push(path.join(wa, d, 'python.exe'));
    }
  } catch { /* WindowsApps 不可列举时忽略 */ }
  for (const v of ['313', '312', '311', '310', '39', '38']) {
    cands.push(path.join(local, 'Programs', 'Python', `Python${v}`, 'python.exe'));
    cands.push(`C:\\Python${v}\\python.exe`);
    cands.push(`C:\\Program Files\\Python${v}\\python.exe`);
    cands.push(`C:\\Program Files (x86)\\Python${v}\\python.exe`);
  }
  cands.push('C:\\Windows\\py.exe', 'python', 'py');

  for (const c of cands.filter(Boolean)) {
    if (c.includes('\\') && !fs.existsSync(c)) continue;
    const r = await runProcess(c, ['--version'], 8000, probeEnv);
    const text = `${r.stdout || ''}${r.stderr || ''}`;
    if (/Python \d/i.test(text)) return c;
  }
  return 'python';
}

function resolveFfmpeg(scriptPath) {
  return firstExisting(ffmpegCandidates(scriptPath)) || 'ffmpeg';
}

/** 工作目录：优先脚本同级的 .jianpu-tmp（用户自己的目录，最稳），再退到系统 TEMP。 */
function pickWorkDir(scriptPath) {
  const cands = [
    scriptPath ? path.join(path.dirname(scriptPath), '.jianpu-tmp') : null,
    path.join(os.tmpdir(), 'jianpu-song'),
    path.join(process.cwd(), '.jianpu-tmp')
  ].filter(Boolean);
  for (const dir of cands) {
    try {
      fs.mkdirSync(dir, { recursive: true });
      const probe = path.join(dir, '.write-probe');
      fs.writeFileSync(probe, 'ok');
      fs.unlinkSync(probe);
      return dir;
    } catch { /* 换下一个 */ }
  }
  return os.tmpdir();
}

/** 子进程环境：补 PATH（工具链自带目录优先）、强行 UTF-8、临时目录指向工作目录。 */
function childEnv(tmpDir, scriptPath) {
  const env = { ...process.env };
  const dirs = [...toolDirs(scriptPath), 'C:\\Program Files\\nodejs'].filter((d) => fs.existsSync(d));
  const current = env.PATH || env.Path || '';
  const merged = [...dirs, current].filter(Boolean).join(path.delimiter);
  env.PATH = merged;
  env.Path = merged;
  env.PYTHONIOENCODING = 'utf-8';
  env.PYTHONUTF8 = '1';
  env.TEMP = tmpDir;
  env.TMP = tmpDir;
  return env;
}

function runProcess(cmd, args, timeoutMs, env) {
  return new Promise((resolve) => {
    let stdout = '';
    let stderr = '';
    let child;
    try {
      child = spawn(cmd, args, { windowsHide: true, env });
    } catch (error) {
      resolve({ ok: false, message: `无法启动 ${cmd}：${error?.message ?? error}` });
      return;
    }
    const timer = setTimeout(() => {
      try { child.kill(); } catch { /* ignore */ }
      resolve({ ok: false, message: `执行超时（${Math.round(timeoutMs / 1000)} 秒）`, stdout, stderr });
    }, timeoutMs);
    child.stdout?.on('data', (d) => { stdout = (stdout + String(d)).slice(-16000); });
    child.stderr?.on('data', (d) => { stderr = (stderr + String(d)).slice(-16000); });
    child.on('error', (error) => {
      clearTimeout(timer);
      resolve({ ok: false, message: `启动失败：${error?.message ?? error}` });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ ok: code === 0, code, stdout, stderr });
    });
  });
}

function tailLines(text, n) {
  return String(text || '').split(/\r?\n/).map((l) => l.trim())
    .filter((l) => l && !/RuntimeWarning|warn\(/.test(l)).slice(-n);
}

function failureText(run) {
  const out = tailLines(run.stdout, 3);
  const err = tailLines(run.stderr, 3);
  const parts = [];
  if (out.length) parts.push(out.join(' / '));
  if (err.length) parts.push(err.join(' / '));
  const text = parts.join(' ｜ ') || run.message || `退出码 ${run.code}`;
  return text.length > 360 ? `${text.slice(0, 360)}…` : text;
}

export function setup(api) {
  if (api && typeof api.config === 'function') getConfig = api.config;

  api.registerTool({
    id: 'play_jianpu',
    name: '简谱点歌（发语音条）',
    description:
      '把一串简谱数字合成音乐，并以语音条发到当前会话。当群友发来简谱（如「1166556」「1 2 3 1|3 4 5-」）、' +
      '点歌、或说「用这个谱子吹一段/弹一段/唱一段」时使用。参数 notation 是简谱原文。' +
      '不要对普通数字（数量、编号、QQ 号、年份、房间号）使用；拿不准就先问一句是不是简谱。',
    category: 'media',
    icon: '🎵',
    parameters: {
      type: 'object',
      properties: {
        notation: {
          type: 'string',
          description: '简谱原文。只用 0~7 与简谱记号，例如 "1166556"、"1 2 3 1|3 4 5-|5 6 5 4 3 1"。'
        },
        instrument: {
          type: 'string',
          description: '音色，可选：口琴 / 钢琴 / 电钢 / 八音盒 / 吉他 / 小提琴 / 大提琴 / 弦乐 / 长笛 / 排箫 / 萨克斯 / 正弦波。不填用设置里的默认音色。'
        },
        bpm: { type: 'number', description: '速度，每分钟多少拍，40~240。不填用默认值。' },
        key: { type: 'string', description: '调号，如 C / D / F / G，或写成 "1=D"。不填用默认值。' }
      },
      required: ['notation']
    },

    async execute(ctx, args) {
      const cfg = config();

      const cleaned = cleanNotation(args?.notation);
      if (!cleaned) {
        return {
          content: '这串内容不像简谱（只认数字 0~7 和简谱记号，如 "1166556" 或 "1 2 3 1|3 4 5-"）。请确认后再试。',
          isError: true
        };
      }
      if (cleaned.notes > cfg.maxNotes) {
        return { content: `谱子太长（${cleaned.notes} 个音符，上限 ${cfg.maxNotes}），请截一段再点。`, isError: true };
      }
      const scriptPath = resolveScriptPath(cfg.scriptPath);
      if (!fs.existsSync(scriptPath)) {
        return {
          content: `找不到生成脚本 3.py。已尝试的位置：${scriptCandidates().slice(0, 4).join('；')}。`
            + '请把 jianpu-tools 文件夹放到 QQ Agent 的 resources/app 下，或在技能设置里填「3.py 的完整路径」。',
          isError: true
        };
      }

      const rawInstrument = String(args?.instrument || '').trim();
      const wantsSine = rawInstrument === '正弦波';
      const instrument = VOICE_INSTRUMENTS.has(rawInstrument) ? rawInstrument : cfg.instrument;
      const shownInstrument = wantsSine ? '正弦波' : instrument;
      const bpm = Number.isFinite(Number(args?.bpm)) ? Math.min(240, Math.max(40, Math.trunc(Number(args.bpm)))) : cfg.bpm;
      const key = String(args?.key || cfg.key).trim() || cfg.key;
      const engine = wantsSine ? 'sine' : 'sf2';

      const stamp = new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)
        + '-' + Math.random().toString(36).slice(2, 7);
      const workDir = pickWorkDir(scriptPath);
      const env = childEnv(workDir, scriptPath);
      const wavPath = path.join(workDir, `jianpu-${stamp}.wav`);
      const mp3Path = path.join(workDir, `jianpu-${stamp}.mp3`);

      // ① 让 3.py 只产出 WAV（避免它内部以"孙子进程"身份调 ffmpeg 被拒）
      const pyArgs = ['-X', 'utf8', scriptPath,
        '--engine', engine,
        '--bpm', String(bpm),
        '--key', key,
        '-o', wavPath,
        '--lufs', 'off'];
      if (engine === 'sf2') pyArgs.push('--gm', instrument);
      pyArgs.push(cleaned.notation);

      const python = await resolvePython(cfg, env);
      const run = await runProcess(python, pyArgs, cfg.timeoutMs, env);
      if (!fs.existsSync(wavPath)) {
        const why = run.ok ? '脚本没有产出音频文件' : failureText(run);
        return { content: `合成失败：${why}`, isError: true };
      }

      // 3.py 在 SF2 渲染失败时会**静默降级**成正弦波 —— 把这件事明确说出来，
      // 否则表现就是"音色变成了默认的电子音"，很难查。
      const runLog = `${run.stdout || ''}${run.stderr || ''}`;
      const fellBack = /改用正弦波|SF2 渲染失败/.test(runLog);
      const warn = fellBack
        ? '（⚠️ 音源降级：SF2 音源没能加载，这次实际用的是默认正弦波。请检查 jianpu-tools 里的 engine/ 与 soundfonts/ 是否完整）'
        : '';

      // ② 由本技能（Node 的直接子进程）做响度标准化 + MP3 编码
      const ffmpeg = resolveFfmpeg(scriptPath);
      const enc = await runProcess(ffmpeg, [
        '-y', '-hide_banner', '-loglevel', 'error', '-i', wavPath,
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
        '-codec:a', 'libmp3lame', '-qscale:a', '2', mp3Path
      ], cfg.timeoutMs, env);
      const hasMp3 = enc.ok && fs.existsSync(mp3Path) && fs.statSync(mp3Path).size > 1024;
      const audioPath = hasMp3 ? mp3Path : wavPath;
      const size = fs.statSync(audioPath).size;
      if (size < 1024) {
        try { fs.unlinkSync(audioPath); } catch { /* ignore */ }
        return { content: '合成结果异常（文件过小），换个谱子再试。', isError: true };
      }

      // ③ 发送：语音条 → base64 → 群文件
      const label = `[语音] 简谱小曲（${shownInstrument}${cleaned.notes}音）`;
      const errors = [];
      const note = hasMp3 ? '' : '（转码失败，已改用 WAV）';

      if (cfg.sendAsVoice) {
        for (const mode of ['path', 'base64']) {
          try {
            let seg;
            if (mode === 'path') {
              seg = [{ type: 'record', data: { file: audioPath } }];
            } else {
              const buf = await fs.promises.readFile(audioPath);
              seg = [{ type: 'record', data: { file: `base64://${buf.toString('base64')}` } }];
            }
            await ctx.sender.sendMedia(ctx.chatKey, seg, { label });
            ctx.session?.sent?.push({ type: 'voice', text: label, at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
            ctx.emit?.('session-update', ctx.session?.id);
            scheduleCleanup([audioPath, wavPath]);
            return {
              content: `已把这首简谱（${cleaned.notes} 个音符，${shownInstrument}，${bpm}BPM）合成并**以语音条发到群里**${note}${warn}。不要再复述旋律内容，按对方的话自然回应一句即可。`
            };
          } catch (error) {
            errors.push(`${mode === 'path' ? '本地路径' : 'base64'}：${error?.message ?? error}`);
          }
        }
      }

      try {
        if (ctx.kind === 'group') {
          await ctx.onebot.call('upload_group_file', {
            group_id: Number(ctx.chatId),
            file: audioPath,
            name: `简谱小曲-${instrument}${hasMp3 ? '.mp3' : '.wav'}`,
            folder: ''
          });
          ctx.session?.sent?.push({ type: 'file', text: '[简谱小曲]', at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          ctx.emit?.('session-update', ctx.session?.id);
          scheduleCleanup([audioPath, wavPath]);
          return { content: `语音条发不出去（${errors.join('；')}），已改为把音频作为群文件上传。` };
        }
        errors.push('私聊无法上传文件');
      } catch (error) {
        errors.push(`群文件：${error?.message ?? error}`);
      }

      scheduleCleanup([audioPath, wavPath]);
      return { content: `音频生成好了（${(size / 1024).toFixed(0)} KB），但发送失败：${errors.join('；')}`, isError: true };
    }
  });
}

function scheduleCleanup(files) {
  const timer = setTimeout(() => {
    for (const f of files) { try { fs.unlinkSync(f); } catch { /* ignore */ } }
  }, 5 * 60 * 1000);
  timer.unref?.();
}

/** 同步自检：脚本不在就直接在「技能」页显示原因。 */
export function available() {
  const scriptPath = resolveScriptPath(config().scriptPath);
  if (!fs.existsSync(scriptPath)) {
    return { ok: false, reason: `找不到生成脚本 3.py（请把 jianpu-tools 放到 resources/app 下，或填「3.py 的完整路径」）` };
  }
  return { ok: true };
}
