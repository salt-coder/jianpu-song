# 简谱转音乐 · Jianpu Song

把**简谱数字**变成**音频文件**（钢琴 / 小提琴 / 长笛 / 口琴…共 287 种音色），并带一个可直接装进 **QQ Agent** 的「简谱点歌」技能。

> Turn simple numbered musical notation (jianpu) into audio — with 287 GM instrument timbres,
> plus a ready-to-install QQ Agent skill that replies with a voice message.

---

## ✨ 特性

| | 说明 |
|---|---|
| **完整简谱记号** | 高低八度（`1'` / `1,` / `（1）`）、延长线 `1-`、减时线 `1/`、附点 `1.`、连音线 `1~1`、升降号 `#4`、休止 `0`、分句停顿、换气 `\|\|`、换调 `--key 1=D` |
| **三种音源引擎** | ① 正弦波（默认，零依赖）② **GM 音源**（287 种真乐器）③ 口琴采样 |
| **响度标准化** | 用 ffmpeg 的 `loudnorm`（EBU R128 真响度）统一到 −16 LUFS |
| **音效链** | `--fx light / harmonica / wide / none`（EQ + 压缩 + chorus + 空间残响） |
| **横向工具** | `jianpu_to_midi.py`：简谱 → MIDI，交给 sfizz 等任意 SFZ 引擎渲染 |
| **QQ Agent 技能** | 群友发 `1166556`，机器人合成后**以语音条发出**（自带三级发送回退） |
| **便携包** | 一个文件夹带走全部依赖（Python 除外），换台电脑即用 |

---

## 🚀 快速开始

### 方式一：下载便携包（推荐给不想折腾的人）

到 **[Releases](../../releases)** 下载 `jianpu-portable.zip`（约 90 MB），解压后：

```bat
:: 需要 Python 3.8+（安装时勾选 Add python.exe to PATH）
python -X utf8 3.py "1 2 3 1|3 4 5-|5 6 5 4 3 1|1 5, 1-||" --engine sf2 --gm 钢琴 -o out.mp3
```

或直接双击 `run.cmd`。

### 方式二：用源码（本仓库）

```bash
# 准备：Python 3.8+ ；可选 ffmpeg（导出 MP3）、Node.js（GM 音源引擎）
python -X utf8 src/3.py "1 2 3 1|3 4 5-" --engine sf2 --gm 钢琴 -o out.mp3
```

> `src/3.py` 会自动在本目录及其子目录寻找 `engine/`、`soundfonts/`、`ffmpeg/`、`node/`，
> 找不到就去 PATH 上找，再找不到会用正弦波降级并在输出里提示。

```bash
python -X utf8 src/3.py --gm list     # 看 23 个中文音色名
python -X utf8 src/3.py --demo list   # 内置示例
python -X utf8 src/3.py --help        # 全部参数
```

---

## 🎼 简谱记号速查

| 记号 | 含义 | 记号 | 含义 |
|---|---|---|---|
| `1`~`7` | 音级（1 = 主音） | `0` | 休止符 |
| `1'` `1^` `1+` | 高八度（可叠加 `1''`） | `1,` `_1` `（1）` | 低八度（三种写法） |
| `1-` | 延长线 +1 拍（`5--` = 3 拍） | `1/` | 减时线减半（`1//` = ¼ 拍） |
| `1.` | 附点 ×1.5 | `1:0.75` | 直接指定拍数 |
| `#4` `b7` | 升 / 降号 | `1~1` 或 `1 1~` | 连音线 |
| 空格 | 分句停顿 0.25 拍 | `\|\|` | 换气，停顿 1 拍 |
| `\|` | 小节线（不停顿） | 换行 | 停顿 1 拍 |

例：`1 2 3 1 | 3 4 5- | 5 6 5 4 3 1 | 1 5, 1- ||`

---

## 🎹 音色

`--engine sf2 --gm <名字>` 或 `--program <0~127>`（GM 标准）：

```
钢琴 电钢 八音盒 管风琴 口琴 吉他 贝斯 小提琴 中提琴 大提琴 竖琴
弦乐 合唱 小号 长号 萨克斯 双簧管 长笛 排箫 正弦波
```

乐器总表与用法见 [`docs/使用说明.md`](docs/使用说明.md)。

---

## 🤖 QQ Agent 技能

见 [`qqagent-skill/安装说明.md`](qqagent-skill/安装说明.md)。装好后群友发一串简谱（如 `1166556`），
机器人会合成音乐并**以语音条发出**；音源降级时会主动告警。

技能会自动在这些位置寻找工具链（`3.py` / ffmpeg / node / 音源）：

```
<技能目录>/tools/
<技能目录>/jianpu-tools/
<QQ Agent>/resources/app/jianpu-tools/     ← 安装脚本默认放这里
~/jianpu-tools/   ~/jianpu-portable/   D:\jianpu-portable\
```

---

## 📁 仓库结构

```
├── src/
│   ├── 3.py                 简谱 → 音频主程序（标准库，无第三方依赖）
│   ├── sf2_render.cjs       SF2 离线渲染器（Node + FluidSynth wasm）
│   └── jianpu_to_midi.py    简谱 → MIDI（给 sfizz 等 SFZ 引擎用）
├── qqagent-skill/
│   ├── jianpu-song/         QQ Agent 技能（skill.json + index.js）
│   ├── 一键安装.cmd
│   └── 安装说明.md
├── scripts/
│   ├── run.cmd              便携版启动器
│   └── dl_gh.py             多线程下载器（正确断点续传）
├── docs/
│   ├── 使用说明.md           完整命令行手册
│   ├── 便携版使用说明.md
│   ├── 授权说明.md
│   └── 发布说明.md           如何发布 Release（含二进制）
├── licenses/                各第三方组件的完整授权文本
├── THIRD-PARTY-LICENSES.md  第三方授权汇总（**再分发前必读**）
├── LICENSE                  本项目授权（MIT）
└── .gitignore               二进制与产物不入库
```

> **本仓库不含二进制**（ffmpeg / Node / 音源共约 205 MB），它们以 Release 附件形式发布。
> 自己打包的方法见 [`docs/发布说明.md`](docs/发布说明.md)。

---

## ⚖️ 授权

- **本项目代码**：MIT，见 [`LICENSE`](LICENSE)
- **第三方组件**：见 [`THIRD-PARTY-LICENSES.md`](THIRD-PARTY-LICENSES.md)
  - GeneralUser GS 音源：License v2.0（允许用于软件项目与再分发，**须保留作者 S. Christian Collins 署名**）
  - basic-harmonica 口琴采样：CC0（公共领域）
  - ffmpeg：**GPL v3**（再分发需附源码获取方式）
  - Node.js：MIT
  - FluidSynth / js-synthesizer：LGPL-2.1 / MIT

---

## English

**Jianpu Song** converts Chinese numbered musical notation (*jianpu*) into audio files.

- **Full notation support**: octave marks (`1'` up, `1,` down), `1-` hold, `1/` halve, `1.` dotted,
  `1~1` tie, `#4`/`b7` accidentals, `0` rests, phrase gaps, `||` breaths, and key changes (`--key 1=D`).
- **Three sound engines**: sine (default, zero-dependency) · **GM SoundFont** (287 real instruments, via
  FluidSynth compiled to WebAssembly + Node.js) · harmonica samples.
- **Loudness normalization** to −16 LUFS with ffmpeg's EBU R128 `loudnorm`, plus `--fx` effect chains.
- **QQ Agent skill**: when a group member sends a jianpu digit string, the bot renders it and replies with
  a **voice message**.

```bash
python -X utf8 src/3.py "1 2 3 1|3 4 5-" --engine sf2 --gm 钢琴 -o out.mp3
python -X utf8 src/3.py --gm list        # list instrument names
python -X utf8 src/3.py --help           # all options
```

Download the self-contained portable build (about 90 MB, Python 3.8+ required) from
**[Releases](../../releases)**. Third-party licensing details: [`THIRD-PARTY-LICENSES.md`](THIRD-PARTY-LICENSES.md).
