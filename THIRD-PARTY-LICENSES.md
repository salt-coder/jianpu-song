# 第三方组件授权汇总

本仓库**源码本身**不含第三方二进制；但通过 Releases 发布的便携包（`jianpu-portable.zip`）
和给 QQ Agent 用的技能包（`qqagent-jianpu-skill.zip`）**内含**下列第三方组件。

**再分发前请确认你满足下表的每一条要求。**

---

## 一、汇总表

| 组件 | 版本 | 授权 | 再分发 | 关键要求 |
|---|---|---|---|---|
| **GeneralUser GS**（音源，约 31 MB） | 2.0.3 | **GeneralUser GS License v2.0** | ✅ 允许 | ① 明确允许"用于你的软件项目、修改音源或其打包方式"；② **须保留作者署名**（S. Christian Collins）；③ **不要直接盗链**作者网站上的下载文件 —— 自己带一份副本 |
| **basic-harmonica**（口琴采样，约 1 MB） | — | **CC0 1.0** | ✅ 允许 | 无（公共领域，署名非强制） |
| **ffmpeg**（约 84 MB） | 7.1 essentials build (gyan.dev) | **GPL v3** | ✅ 允许 | 构建含 `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265`，**无** `--enable-nonfree` → 可再分发；**GPL 要求提供对应源码或源码获取方式**（见下） |
| **Node.js**（约 89 MB） | v24 | **MIT** | ✅ 允许 | 附 `licenses/node-MIT.txt`（含其捆绑组件的授权列表） |
| **FluidSynth**（编译为 WebAssembly） | 2.4.6 | **LGPL-2.1** | ✅ 允许 | 附授权文本；使用者应能替换该库（本项目中它是独立文件 `engine/libfluidsynth-2.4.6.js`，可直接替换） |
| **js-synthesizer** | 1.13.0 | **MIT** | ✅ 允许 | 附授权文本 |

> ⚠️ **GeneralUser GS 作者的提醒（原文摘录）**：该音源的采样来源无法 100% 追溯，
> 因此他建议**商业软件产品**谨慎评估；本项目为非商业开源项目，正常使用不受影响。
> 若你计划商用，请自行评估或替换音源。

---

## 二、ffmpeg 的 GPL 合规（重要）

本项目分发的是 **GPL v3** 的 ffmpeg 二进制，因此需要一并提供**对应源码的获取方式**：

- 二进制来源：<https://www.gyan.dev/ffmpeg/builds/>（`ffmpeg-release-essentials.zip`）
- 该构建的构建脚本：<https://github.com/gyan-dev/ffmpeg-build-script>
- ffmpeg 官方源码：<https://ffmpeg.org/download.html>
- 完整授权文本：本目录 [`licenses/ffmpeg-GPLv3.txt`](licenses/ffmpeg-GPLv3.txt)

**替代方案**：如果你不想承担 GPL 义务，可以不打包 ffmpeg（让用户自己安装），
此时便携包从约 90 MB 降到约 35 MB，且授权只剩 MIT 系 + 音源授权。

---

## 三、各组件授权的完整文本

| 文件 | 内容 |
|---|---|
| [`licenses/GeneralUser-GS-License-v2.0.txt`](licenses/GeneralUser-GS-License-v2.0.txt) | 音源授权原文（从 SF2 内嵌 `ICMT` 标签提取） |
| [`licenses/basic-harmonica-CC0.txt`](licenses/basic-harmonica-CC0.txt) | CC0 1.0 全文 |
| [`licenses/ffmpeg-GPLv3.txt`](licenses/ffmpeg-GPLv3.txt) | GNU GPL v3 全文 |
| [`licenses/fluidsynth-LGPL-2.1.txt`](licenses/fluidsynth-LGPL-2.1.txt) | GNU LGPL 2.1 全文 |
| [`licenses/node-MIT.txt`](licenses/node-MIT.txt) | Node.js 的 LICENSE（含其捆绑组件） |
| [`licenses/js-synthesizer-MIT.txt`](licenses/js-synthesizer-MIT.txt) | js-synthesizer 授权 |

---

## 四、署名要求（请照抄到你的发布页）

> This project bundles the following third-party components:
> **GeneralUser GS v2.0.3** by S. Christian Collins (<https://schristiancollins.com/generaluser.php>),
> **basic-harmonica** samples (CC0), **FFmpeg** (GPL v3, build by gyan.dev),
> **Node.js** (MIT), **FluidSynth** (LGPL-2.1) and **js-synthesizer** (MIT).
