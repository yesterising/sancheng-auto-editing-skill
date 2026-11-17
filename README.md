# 三橙自动剪辑 Skill

面向已剪好的中文口播视频。提供同一版视频和 SRT 后，Agent 核对时间轴，梳理表达主线并提出核心词和开场方案。核心词定稿后，Agent 按语义组织字幕、手绘、解释画面、人物窗口、动效和音效。默认交付从 00:00 对齐的透明包装，由用户拖入剪映。

## 安装和使用

将本仓库 `skills/` 下的六个目录一同安装到 Agent 的本地 Skill 目录，保留彼此相邻的结构。已有同名版本时先比较内容。重新打开对话，调用 `$video-editing-playbook`，提供视频、同版 SRT 和交付要求。

本地工具需要能执行 Python 3、FFmpeg 和 ffprobe。需要口播音效脚本时，将 `skills/koubo-cut/runtime.env.example` 复制为同目录的 `runtime.env`，按本机情况配置命令，并让 `SKILLS_DIR` 指向安装这六个 Skill 的父目录。如需使用包装模块的 Remotion 实现，在对应模块下以 Node.js 20+ 执行 `npm ci`。

示例请求

> 请用 video-editing-playbook 包装这条口播视频。我提供的是最终剪切版本和同版 SRT。先给我主线、核心词和开场方案。确认核心词后，做成从 00:00 对齐的透明包装，交付能用于剪映的文件。

## 依赖和兼容范围

- 新增或重做视觉需要访问 Pinterest 及接入 Cosmos MCP，并记录实际看图和对照结果。没有新增视觉时也记录原因。交付检查使用入口 Skill 的 `scripts/finalize_delivery.py`。
- UISFX 声音和来源记录位于 `skills/koubo-cut/assets/uisfx`，本包内音频按其 CC0 文件提供。按具体动作选声或留白。
- 按需安装 [Nikola 手绘](https://github.com/hi-nikola/hand-drawn-explainer-video-nikola)、[Lemo-Opuscar](https://github.com/lemomo-ai/lemo-opuscar)、[HyperFrames](https://github.com/heygen-com/hyperframes) 或 Blender。HyperFrames 的 core、animation 和 registry 技能参考随所用工具安装。FFmpeg 技能及剪映操作 Skill 属外部依赖。
- 4B 混合可编辑及剪映原生草稿属于显式选择的路径。原生操作需要对应剪映版本、`jianying-editor` 和本机兼容性验证。公开包初次发布尚未完成干净环境从真实视频全链路渲染与剪映实机导入验证。
- 摄制者肖像、履历、背景与字体由使用者配置。请提供有权使用的素材。

包装模块源于 [aipacking](https://github.com/zhouyuechuan2025-ui/aipacking)，保留模块下的 LICENSE 和 NOTICE。随附的第三方资源按各目录原有许可和来源记录提供。
