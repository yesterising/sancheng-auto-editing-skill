# 局部修改与场景缓存

本工具维护主包装内部场景，沿用原 SRT 和成片时间基准。最终仍装配为一条从 00:00 开始的全片透明 MOV，通过总规则的可用性检查后交给用户自行导入剪映；内部缓存片段不是交给用户逐场摆放的素材。

返修先读取当前 [事件与复用关系](semantic-events-and-reuse.md)及旧 build：以本次反馈定位事件和消费者，明确保留的原材料与失效派生部分，再生成 patch。事件表是制作依据，正式计划仍用下述现有合同；时序变化走完整新计划，不借局部 patch 绕过锁定范围。

## 先界定反馈范围

每轮先区分精确文案校正、局部镜头、全局样式，或重录/粗剪/倍速造成的时间变化。最新明确指令覆盖旧方案；没有实质冲突的常规选择直接执行，无法由现有优先级消解的冲突列明双方规则、影响与待决定项，继续不依赖该决定的工作。

局部镜头只改变对应场景及其依赖；全片字号反馈覆盖全部新增文字、容器和三维牌面字图。重录或改变剪辑时序后，重新锁定原片、用户SRT、工程帧率和源时间映射，再排全部窗口与镜头；可复用视觉资产，不直接复用旧秒数。仅涉及规则或skill维护时不操作剪映工程。

维护当前效果清单：以实际制作计划、渲染源码与build记录交叉核对，保留旧分镜版本标记。记录父版本、反馈范围、时间基准、正式输出及渲染/导入/上轨各状态；中断输出留在work中，不作为完成交付。生成正式新文件，不覆盖已导入旧版本。

## 输入合同

计划使用 `sancheng-scenes/v1`；时间采用整数帧，`end_frame` 为开区间。场景按顺序连续覆盖 `[0,total_frames)`。实际制作先按总规则确认 SRT；工具也先检查可读 SRT，再读取字体与素材。以下是结构示例，所有路径与参数均需按本片替换：

```json
{
  "schema": "sancheng-scenes/v1",
  "srt": "/absolute/current.srt",
  "project": {
    "editor": "jianying", "width": 1920, "height": 1080,
    "fps": "30000/1001", "total_frames": 2100,
    "font": {"family": "本片实际中文字体", "file": "/absolute/font.otf", "weight": 700},
    "accent": "#FFD34E", "foreground": "#FFFFFF", "protected_regions": []
  },
  "scenes": [{
    "id": "opening", "start_frame": 0, "end_frame": 2100,
    "recipe": "impact-title", "params": {"zone": [0.1,0.12,0.8,0.25], "title": "本片重点", "enter_frames": 6},
    "assets": {}, "depends_on": []
  }],
  "sounds": []
}
```

该示例只解释合同，不是完整分镜建议。每场 `recipe`/参数/素材键见配方目录；图片路径放 `assets`。`custom-html` 另加 `html` 路径，页面中使用的每个外部本地依赖均在 `assets` 声明；自定义页面自行保护脸部/字幕。跨场共享对象、转场或前后帧关联通过 `depends_on` 指向受依赖的场景；脚本据此连带失效，循环依赖会被拒绝。

每次都先按 [UISFX 强制选声或留白](../../koubo-cut/references/uisfx-selection.md) 完成逐场判断，用 `prepare` 取得实际选定的 `sounds`（明确留白时为空），写入本计划后运行 `bind`，生成含 `uisfx_selection` 的正式新计划供下述 validate/build 使用。上面是尚未绑定的结构示例，不能直接作为正式装配计划。`sounds` 的核心字段如 `{"path":"/absolute/sfx.wav","at_frame":45,"peak_offset_frames":3,"gain":0.25}`，实际使用 prepare 的完整记录；`at_frame` 是全片锚点，起音回推 `peak_offset_frames`，不能凭文件名猜峰值。空音轨必须有覆盖全片的明确留白记录才能生成静音包装；工具不额外加入原口播。

## 初次制作

```bash
python3 <skill-root>/scripts/scene_pack.py validate --plan /task/work/plan-v1-reviewed.json
python3 <skill-root>/scripts/scene_pack.py build --plan /task/work/plan-v1-reviewed.json --cache /task/work/scene-cache --output /task/outputs/全片包装_v1.mov --ffmpeg /existing/ffmpeg --playwright-from /existing/project/package.json
```

复用现有 Node、Playwright 或 Playwright-core/匹配 Chromium、FFmpeg 和 `sancheng-broll-animation/scripts/render_alpha.mjs`，可传 `--browser /existing/chromium`，运行时不安装依赖、不联网。页面含视频/音频时由渲染器明确拒绝，需改用原有媒体/三维制作路径。这里输出的是动画素材，不是口播成片导出。

## 定点修改

先读取原计划和已有 build 记录，依据用户反馈生成 patch：

```json
{"reason":"用户要求重点文字更大、落稳更快","scenes":[{"id":"opening","params":{"font_size":112,"enter_frames":4}}]}
```

```bash
python3 <skill-root>/scripts/scene_pack.py revise --plan /task/work/plan-v1-reviewed.json --patch /task/work/patch.json --out /task/work/plan-v2.json
python3 <skill-root>/scripts/scene_pack.py diff --before /task/work/plan-v1-reviewed.json --after /task/work/plan-v2.json
# 先重判本次改动相关声音，prepare/bind 得到 plan-v2-reviewed.json，再正式装配。
python3 <skill-root>/scripts/scene_pack.py build --plan /task/work/plan-v2-reviewed.json --cache /task/work/scene-cache --output /task/outputs/全片包装_v2.mov --ffmpeg /existing/ffmpeg --playwright-from /existing/project/package.json
```

patch 可更新已存在场景的参数、素材、配方、自定义 HTML、显式依赖及场内 `events/needs/coverage_note`；事件须给当前依据与仍处于本场的全片帧，详见 [配方生产](recipe-production.md)。也可整体更新 `sounds`。它锁住场景编号、起止帧、项目规格、SRT 与字体，避免一次局部反馈重排全片。用户明确要求改时序、字体或工程规格时，另制完整新计划并同步时间映射，不能把它伪装成局部 patch。

revise/diff 允许读取旧计划，便于复用视觉缓存；变更后原 UISFX 绑定会失效。只重判本次变动及其相关声音，沿用未变事件并输出完整决策记录，再 prepare/bind 新计划后运行 build。声音维持原样也要重新确认和绑定，不跳过该步骤。

缓存键包括场景参数、实际素材内容、SRT 整体哈希、字体、渲染实现和已声明的依赖。改一场会重做该场及其依赖方；未变场景复用；SRT、字体/全局规格变化会使所有相关缓存失效。缓存文件哈希不符时重渲染，输出文件与原计划拒绝覆盖。声音变化重装音轨，画面缓存可复用。文件名相同不证明材料适用；原材料可保留而时间证据需重算时，分别记录，不宣称已实现按词自动局部重渲染。

`<输出>.build.json` 报告每场 `rendered/reused`、完整帧数、文件哈希、音效数量，以及 `imported_to_jianying=false`、`acceptance=not_assessed`。`history` 记录反馈、父计划哈希和修改范围，不把自动修复分数当作审美结论。

## 交付与验证范围

正式制作中的字体/布局计算、时序与编码反馈照常完成；正式文件的可用性检查、最多返修轮数及用户手动导入分工以当前总规则为准，不由本参考另设一套限制。正式输出按 [正式文件局部检查](revision-workflow.md) 比较两版 build 的真实场景键和声音指纹，最多两轮定点返修；首次制作只按新增场景关键动作抽样。检查与用户认可分开记录。返修或重做均生成新的正式文件，检查素材与全片合成关系后给出新文件链接，保留旧版，由用户自己替换；本流程不进入原生替换入口，用户导入后不再自动检查。渲染器不操作剪映，也不自动将素材放进时间线。默认仍为 4A，明确混合可编辑时进入 [4B](hybrid-editable.md)。
