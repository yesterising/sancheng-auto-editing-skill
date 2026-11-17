# 本地制作与剪映接入

全屏 B-roll 与同步人物窗口在本次完整包装范围内默认自主安排；区间外仍真实透明。正式输出由主流程统一按 [正式文件局部检查](../../package-talking-head-video/references/revision-workflow.md) 检查改动范围并最多返修两轮；返修交付通过 [文件可用性检查](../../video-editing-playbook/references/file-delivery.md) 的新版，由用户手动替换。以下不测试/不验收的旧表述只排除额外小样与整片验收，不排除正式文件局部检查。

## 路径选择

1. B-roll、解释动画及积木三维优先使用 [Lemo 本机接入](../../video-editing-playbook/references/lemo-opuscar.md) 的适用风格和实际能力；复杂骨骼、接触或机械动作更适合时走 [Blender 三维流程](blender-workflow.md)。保留真实三维效果，不降级为平面动画。
2. 已有适用的 HyperFrames 运行时：按 hyperframes-core（外部依赖，见仓库 README） 和 hyperframes-animation（外部依赖，见仓库 README） 制作可 seek 的单一时间线，优先复用其已可用渲染能力；先看实际 CLI 帮助与 Alpha 输出能力。安装了 skill 不代表 CLI 或运行依赖存在，不用 `npx` 临时下载绕过。
3. HTML/SVG/Canvas 对象动画：使用本技能 `scripts/render_alpha.mjs`。每个时间点由 `renderAt(t)` 显式计算整个可见状态，适合截图运动、关系图、文字、图形和 2.5D 物件。它不驱动任意网页上的实时 CSS/JS 动画，不负责视频逐帧解码、音轨或语音生成。
4. 原始视频截取、静态保持、图片平移缩放、声音对齐与封装：读 FFmpeg skill（外部依赖，见仓库 README），使用实际已有的 FFmpeg/FFprobe。视频画面在自绘网页中需要精确解码时，使用支持逐帧媒体的现有工具，或先生成需要的帧并由 agent 同步取用；不要截到未 seek 完成的视频画面。
5. 剪映必要状态读取与图层制作：读 jianying-editor（外部依赖，见仓库 README） 及其导入参考；画中画、人物位置变化或人后效果读 [talking-head-pip](../../talking-head-pip/SKILL.md)。这些效果需要真实素材分层，普通透明网页动画不会自动改动底片。
6. Lemo-Opuscar 风格化代码动画：读 [本机接入](../../video-editing-playbook/references/lemo-opuscar.md)，使用其 HTTP 挂载、`READY/render(t)` 专用 Alpha 桥；不直接交官方不透明 MP4，也不把 `render(t)` 仅改名后交给上面的 file:// 渲染器。全片时间与声音继续接真实 production 计划。

## 依赖定位

先根据 `command -v`、已有项目包和相关 skill 的环境定位工具，再检查对应文件可执行、包可解析。这里只存可复用的定位线索，不承诺路径永远不变。

本机曾确认可复用的路径：Node 在 `/usr/local/bin/node`；Python 环境见 `../../koubo-cut/references/local-runtime.md`。FFmpeg/FFprobe 可位于 `/Applications/ChatCut.app/Contents/Resources/app.asar.unpacked/node_modules/ffmpeg-ffprobe-static/`；这里只使用本地二进制，不启动 ChatCut 编辑器。Playwright 曾可从 `~/.npm/_npx/e41f203b7505f1fb/package.json` 解析，浏览器由该包的 `chromium.executablePath()` 定位。使用前确认仍存在；缓存失效则查已有项目依赖，不自动下载。缺失时明确缺口，完成能做的部分。

## 读取 SRT

确认用户 SRT 后，调用以下工具，`--duration` 与 `--fps` 来自当前最终工程；只有做时间底稿时才可省略 duration，此时输出明确标为估算而非全片时长：

```bash
python3 <skill-root>/scripts/srt_timeline.py /absolute/path/subtitles.srt --fps 30000/1001 --duration 70.733 --output work/srt-timeline.json
```

它保留毫秒时间与原文，报告重叠和空档，输出字幕的帧包络。起帧向下、止帧向上取整只是覆盖该字幕的范围，不能用包络替换精确时间，或把重叠误判成切镜。底稿 `design_status` 为待设计；agent 需将其转成真实语义分镜。若 SRT 超出明确工程时长，工具报错，由 agent 定位时序差异，不裁掉尾句。

## 本地网页动画接口

HTML 由 agent 按本片内容编写，项目文件放本次任务 `work/`。页面、画布清屏与编码全程保留透明，画幅从工程读取。所有字体、图片、脚本来自已授权的本地文件；渲染器阻止联网。`window.ready` 可用于资源准备，渲染器也会等待字体和图片解码。真实中文字体需由页面显式加载并检查字重和字形，不能仅依赖系统回退。

```javascript
// renderAt 可以是 async，必须在返回前完成本帧绘制。
window.ready = Promise.all([document.fonts.load('700 76px "ProjectCJK"'), document.fonts.ready]);
window.renderAt = function (t) {
  // 使用时间 t 设置全部对象的状态；Canvas 每帧 clearRect 后重画。
  // 同一 t 总是同一结果；场景隐藏和恢复也必须由 t 决定。
};
```

不用真实时钟、未固定随机数、计时器累积或依赖前一帧的增量更新；关键图像的加载失败应在页面中抛错。SVG/HTML 元素的移动、旋转、遮罩和透明度都从绝对时间求值。处理本片素材时，先阅读已有代码，再按 coding-discipline 最小改动。

```bash
node <skill-root>/scripts/render_alpha.mjs --html work/animation/index.html --output outputs/全片同步透明包装.mov --width 1920 --height 1080 --fps 30 --duration 70.733 --ffmpeg /absolute/path/ffmpeg --playwright-from /absolute/path/existing-project/package.json
```

所有值按本次工程替换。输出固定为 QTRLE/ARGB MOV、无音轨；画幅与帧率由参数显式指定，帧数按 duration×fps 向上取整。实际时长因此最多比目标多不到一帧；使用同一目标帧数装配全片其他图层与声音。工具拒绝覆盖已有文件；修改后选择新正式文件名，不破坏已导入素材的关联。文件中的“透明”来自真实渲染内容，编码格式不能修复页面画了不透明背景的问题。

每帧截图会处理图片与自绘图形；原始视频、音频请走媒体工具，渲染器遇到 HTML video/audio 元素会明确拒绝。页面显式报错、图片失败或 FFmpeg 错误会停止任务并报告，不把不完整文件当成正式素材；错误时残留输出可供定位，修复后另选输出名。

## 声音与交付

声音按总规则选择实际素材和动作峰值；本地 renderer 不自动配声。需要音效时用 FFmpeg 将实际声音按最终时间线对齐：主视频流 `-c:v copy` 保留 Alpha，音轨用当前 MOV 支持的格式（例如 PCM）；精确指定同一目标时长，不能用 `-shortest` 把没有尾部音效的全片截短。单独音轨也从 00:00 开始、覆盖全片，尾部补静音。不得把口播原声再次混进包装层。

整帧 B-roll 在本次完整包装或指定范围内按自动导演规则自主安排；在统一全片透明素材中，这些范围可不透明，其他区域按设计透出原片。完整主包装从首帧到末帧连续承接，辅助层的透明空档不代表主包装可无内容。仅独立动画任务才按用户要求交付短片或不透明 MP4。

素材装配后按总规则完成正式文件可用性检查，展示并链接文件，由用户自己导入和拖入剪映。没有 AI 批量导入入口不影响文件交付，不把它列为制作阻塞。本流程不放入时间线或操作当前工程；明确要求草稿或成片文件时仅按所需产物制作并完成适用检查，不自动保存/安装/导出剪映工程。烘焙 MOV 与保留源码分别说明，不承诺导入后可原生编辑动画内部元素。
