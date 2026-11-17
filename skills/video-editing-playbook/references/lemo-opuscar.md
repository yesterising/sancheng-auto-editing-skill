# Lemo-Opuscar：口播、B-roll 与动画的本机接入

本参考是 Lemo 与本用户剪辑流程的单一接入规则。实际剪辑先按 [总规则](../SKILL.md) 确认用户 SRT；独立素材和技术维护按自身范围，不为接入工具索要无关字幕。Lemo 提供风格与技法，剪映继续作为编辑宿主，本期时间、声音、文字和交付分工由总规则管理。

## 默认优先使用 Lemo

口播包装先按 [短透明手绘规则](short-transparent-handdrawn.md) 判断内容形式；已经选为真正逐笔手绘的短插入转 Nikola，不再要求先用 Lemo 做一次。以下 Lemo 优先级适用于其余适配动画；产品证据始终由真实素材承担。独立完整影片仍按该任务明确要求选择。

需要新解释动画、流程可视化、风格化 B-roll 或指定 Lemo 风格时，读取 本机技能（外部依赖，见仓库 README） 和库内 `styles/README.md`，先寻找并实际采用能满足本片要求的 Lemo 风格、导演方法和制作技法，尽量覆盖适合的视觉段落；明确能力或效果不适合、真实素材证据需要原样呈现、或复用已有成品更合理时，再选其他工具，并在计划简记理由。不设使用比例或为了调用而加无关画面。瑞士动态排版适合概念与比较，等距信息图适合流程，数据叙事适合有来源的数据，绘画风格适合故事氛围；这些是候选用法，不是关键词到模板的映射。局部返修沿已选风格处理，普通裁切、仅字幕或调音不启动 Lemo。

真实软件功能与结果用原录屏/截图；`living-screencast` 是重绘界面，`dark-keynote` 是概念界面，均不作为实际操作成功的证据。精确文字、Logo、数字和来源资产继续保留。积木与三维场景也先评估 Lemo 的风格和真实 three.js 实现；复杂骨骼、接触或机械动作更适合时转 [Blender 路径](../../sancheng-broll-animation/references/blender-workflow.md)，可继续使用适用的 Lemo 导演语法。已有素材与配方按本期语义复用，避免无意义重做。

口播 B-roll 借用 `STYLE.md` 的视觉语法和实现技法，在现有场景/事件计划写明主体、动作、结果及取舍；独立完整影片才使用官方完整导演方案。口播任务沿已核实的 SRT、原声、工程尺寸/有理数帧率与全片整数帧，不重新编主片、自动 TTS/转写、添加无关音乐或按官方 24fps/30–60秒默认重排。中文字体和横竖屏字幕规则服从本项目已锁定设计。常规制作自主完成，只在用户要求先审分镜等明确阶段停下。

## 每次使用前检查当前运行状态

库默认 `~/lemo-opuscar`；独立 FFmpeg/FFprobe 在 `~/.local/share/lemo-opuscar/bin/`，常用命令由 `~/.local/bin` 链接。以下检查从任意目录运行，使用已安装资源，不联网、不更新、不安装或调用 AI：

```bash
node "$SKILLS_DIR"/video-editing-playbook/scripts/lemo_local.mjs doctor --report /absolute/task/work/lemo-doctor.json
```

按输出核对本次所需层：核心渲染、配音/ASR、乐器采样、HDRI及风格专用依赖。`core_ready` 汇总的是通用制作环境，包含 Python 和音频能力；无声 Alpha 任务仅依赖其实际使用的浏览器、页面资源与 QTRLE 编码，音频项缺失不等于该渲染路径不可用。`--tier full` 额外核对通用配音、模型、音乐、采样与 HDRI，不代表所有专业风格的数据读取包都已安装。按具体失败项修复本次需要的部分，不切换付费生成。安装记录只是线索，doctor 与实际制作结果才是当前证据。

日常不自动更新库或重装包。缺本次依赖使用本地适配后的 `lemo-opuscar/scripts/setup.sh deps`，补样片使用 `demo <slug>`，两者均不更新库版本；只有明确要求更新时运行该脚本的 `update`，干净工作树且可快进才更新，失败不重置本地修改。完成后重跑检查；业务源码、自有风格和本地桥均放在库外。自有风格从 `~/lemo-my-styles/` 管理。第三方采样、字体和素材在本期 CREDITS 记录来源与许可。

## 渲染接口和真实 Alpha

Lemo 页面必须同时实现 `window.READY = true`、确定性的 `window.render(t)` 和正数 `window.DUR`（场内秒数），资源通过本地 HTTP 的 `/core/`、`/node_modules/` 和 `/@film/` 加载。通用 `render_alpha.mjs` 是 file:// 与 `renderAt(t)` 契约，不能靠函数改名直接兼容。官方 `video.mjs` 用 JPEG 与 H.264 输出，不保留透明，后续转 MOV 无法恢复。

本机桥使用匹配浏览器和本地挂载，等待字体/图片与 READY，逐帧调用 render，通过 PNG 输出 QTRLE/ARGB MOV；仅本地资源，输出无音轨。页面须支持同一时刻独立 seek，无实时钟或累积状态。真实 video/audio 解码另走媒体工具，不在网页里截取未完成 seek 的画面。

```bash
node "$SKILLS_DIR"/video-editing-playbook/scripts/lemo_local.mjs render-alpha \
  --project /absolute/task/work/lemo-scene \
  --output /absolute/task/work/lemo-scene-v1.mov \
  --width 1080 --height 1920 --fps 30000/1001 \
  --frames 1800 --start-frame 300 --end-frame 480
```

参数来自工程与事件计划；示例仅说明接口。`frames` 为输出总帧数，场景范围为 `[start-frame,end-frame)`，区间外透明，场内 t 从零开始，公式为 `(全片帧−场景起帧)/fps`。页面 DUR 对应场内整数帧，差异先重排本期动画，不静默拉伸口播/SRT。可先内部生成局部短场，再进入全片装配；用户最终收到已同步好的完整素材。

Alpha 取决于页面：HTML/body/CSS 无不透明底，2D Canvas clearRect，WebGL renderer 开启 alpha 且 clearAlpha 为零。适合不透明舞台的风格作为全屏 B-roll，覆盖原大人物后再叠同步静音人物窗口；区间外恢复透明。去掉背景改变风格核心时选择全屏版本或说明是局部改编。QTRLE/ARGB 只证明有 Alpha 通道，正式文件仍检查透明区/主体区实际像素及合成关系。

## 原有声音、装配与交付链

关键动作消费本期 [语义事件](../../package-talking-head-video/references/semantic-events-and-reuse.md)，登记全片事件帧与场内时间。Lemo 的 `EV` 可表达事件，不自动证明与本期 SRT 或声音同步。场景起止、阅读停留和切点按真实内容安排。

每次剪辑仍进入 [UISFX 选声或留白](../../koubo-cut/references/uisfx-selection.md)，Lemo 自带合成音及独立电影的配声建议不替代判断；已有口播保留一份，不混进包装层。明确无声时记录留白。采用的其他免费声音在计划登记来源、锚点和增益，按既有混音与核听规则处理。

接入使用既有真实 Blender/FFmpeg `production` 计划：登记 source/SRT、project.fps/total_frames、覆盖全片的 scenes、实际 renderer/布局/源映射，以及所有源码、JS、字体、贴图等 `assets` 依赖。UISFX `prepare` 后 `bind/check --mode production`，通过再装配；依赖或事件变化使旧绑定/相关缓存失效。不把 HTTP 页面假装成 scene_pack 的 file:// custom-html。与现有场景合成时沿实际装配代码记录依赖，不另造虚假场景满足核对器。

所有层统一为 00:00、工程尺寸、精确帧率和全片帧数；必要音轨补静音到全片，复制视频流保留 Alpha。按 [制作检查](production-checks.md) 和 [文件交付](file-delivery.md) 检查正式改动区间、字体、合成、声音、完整解码与兼容依据，再用 `finalize_delivery.py`（`uisfx_mode=production`）生成本轮链接。桥自检不替代本期可用性检查或剪映原生验收；用户自行导入/拖到 00:00/替换，AI 不操作当前工程。
