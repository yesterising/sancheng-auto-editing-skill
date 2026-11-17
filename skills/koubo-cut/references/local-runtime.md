# 本机运行环境

本用户默认由 Codex 处理已在剪映的当前视频，先按 [总规则](../../video-editing-playbook/SKILL.md) 确认用户 SRT。缺失即提醒，不自动转写补齐。

调用本机脚本时加载 "$SKILLS_DIR"/koubo-cut/runtime.env，使用其中 KOUBO_PYTHON 与已配置的 FFmpeg/FFprobe；环境失效时根据实际报错定位工具。不要为加载环境顺带运行 make_sfx.py。合成声音仅在具体事件需要时生成，按合成声音标识。

免费动作音效入口为 scripts/uisfx.py；每次自动剪辑强制执行 [UISFX 选声或留白](uisfx-selection.md)，使用已安装音频和已有 FFmpeg。catalog/inspect 用于选材，prepare 转为实际 sounds，bind 将决策绑定当前制作计划，check 在装配/交付前核对；全片装配器与新草稿入口也执行相同强制检查。它不读关键词猜音效，不联网、建服务或创建剪映工程，项目产物放项目目录。

preprocess.py 仅用于实际编码适配需要；transcribe.py 仅在用户明确要求生成/转写 SRT 时使用，不作为剪辑任务缺 SRT 的替代步骤。已有 SRT 直接使用，不重复识别、下载模型或重建时间戳。

默认使用当前工程界面和正式全片包装，字体绑定、单行布局和动作配声按总规则执行。build_draft.py 仅在用户明确要求新草稿文件时使用，先读 jianying-editor 实际所需接口；计划必须给出 SRT、实际原生字体及具体声音事件。它不会自动完成抠像或原片镜头运动，不能将 JSON 创建当成已打开或已装配工程。

历史检测的剪映路径和版本只是历史，不当作当前结论；获得 SRT 后只获取下一步制作需要的应用状态。软件维护验证与视频测试片分开，普通剪辑不额外创建工程或导出成片。
