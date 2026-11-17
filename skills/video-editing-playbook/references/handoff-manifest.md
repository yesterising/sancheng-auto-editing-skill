# 单一交付核对入口与记录合同

实际剪映剪辑完成制作和各项观察后，使用 `scripts/finalize_delivery.py` 核对本轮交付。它只读取现有正式文件和检查证据，不渲染、不上传、不操作剪映；不替 AI 看图、听音或证明原生兼容。独立 SRT 纠错、独立素材任务按各自技能完成，不为了套本合同追加视频/合成验收。

```bash
python3 <video-editing-playbook>/scripts/finalize_delivery.py \
  --manifest /task/work/handoff-v2.json \
  --out /task/work/handoff-v2-ready.json
```

成功退出码为 0，输出 `delivery_ready=true`、各正式文件的路径/哈希/用途/层级/声音归属和可直接使用的 `links`。失败退出码为 2，记录错误且 `files=[]`、`links=[]`。输出记录必须是新路径，不能覆盖输入、旧记录、素材或技能文件。最终回复从成功清单取链接；回复前若任何输入、观察证据或正式文件变化，重新核对。

## 顶层记录

输入 JSON 使用 `schema="jianying-handoff/v1"`，必要字段如下。路径均为真实绝对路径，SHA-256 使用当前记录的 64 位小写十六进制值；示例尖括号内容须换成实际值，不能当成已检查证据。

```json
{
  "schema": "jianying-handoff/v1",
  "job_id": "本次任务稳定标识",
  "version_id": "v2",
  "operation": "revision",
  "product": "overlay",
  "source": {"path": "/task/source.mov", "sha256": "<实际哈希>"},
  "srt": {"path": "/task/source.srt", "sha256": "<实际哈希>"},
  "production_plan": {"path": "/task/work/actual-plan-v2.json", "sha256": "<本轮实际制作计划哈希>"},
  "uisfx_mode": "scene",
  "assets": [],
  "project": {"width": 1920, "height": 1080, "fps": "30000/1001", "total_frames": 2100},
  "checks": {},
  "files": []
}
```

`operation` 为 `initial`、`revision` 或 `redo`。`product` 为 `overlay`（默认完整透明包装）、`final_video`（明确要求的完整成片）、`audio`（仅声音交付）、`subtitle`（当前剪辑中的独立字幕）、`draft`（明确要求的可用草稿文件）或 `hybrid`。产品与唯一 `role="main"` 文件的 kind 必须匹配；辅助层使用 `role="auxiliary"`。audio/subtitle 单类产物不混入其他媒体种类，需要混合独立可编辑层时声明 hybrid。纯声音任务没有视频尺寸/运动要求，但仍核对工程帧基准、SRT/源时间和实际混音。实际剪辑中的字幕/草稿继续完成其适用证据，不可通过更换 product 规避所要求功能。

## 所有观察共用的形式

`checks.assets`、`checks.timeline`、`checks.srt_match`、`checks.compatibility` 和文件内各 review 都采用下列共同字段：

```json
{
  "job_id": "本次任务稳定标识",
  "version_id": "v2",
  "status": "pass",
  "finding": "对本轮真实对象、具体区间和已观察结果的说明",
  "targets": [{"path": "/task/outputs/全片包装_v2.mov", "sha256": "<当前文件哈希>"}],
  "evidence": [{"path": "/task/work/review/frame-000000300.png", "sha256": "<实际证据哈希>"}]
}
```

`pass` 必须有具体 finding、非空 evidence、真实可读且哈希相符的证据，不能只填“通过”。证据应当是该项实际观察的画面、声音、操作结果或来源记录，不能用无关文件凑数。helper 核对这些记录及文件一致性，观察真实性由执行 agent 负责。

同 job/version 的 targets 必须覆盖所需当前对象：素材检查覆盖 source、SRT、assets；时间安排/合成检查覆盖这些输入、production_plan 和全部交付文件；SRT 匹配覆盖 source、SRT 和 production_plan；兼容检查覆盖全部交付文件；每文件内容检查覆盖该正式文件；混音核听覆盖该带声音正式文件与 source。不同 job/version 的历史观察只有在额外记录非空 `reuse_reason`，且其 targets 的内容哈希覆盖所有所需当前对象时才能复用；文件或证据哈希失效即拒绝。即使原片和包装的字节相同，实际时间映射/计划换版后也不能继续使用未绑定新计划的旧观察。

`production_plan` 必须是本轮实际采用的已存在制作/时间映射计划，不为放行另造一份计划。`uisfx_mode` 使用该计划真实适用的 `scene`、`draft` 或 `production`。最终入口调用既有 UISFX 的 `load_context` 与 `validate_selection`，复核计划中的 SRT 身份、FPS、全片帧数和适用源片；缺少、过期或未完成的选声/留白绑定均不能放行。scene/draft 继续使用既有真实上下文；production 对应 Blender、FFmpeg 等真实制作计划，保留实际 scenes、source、布局和源时间映射，不要求假 HTML、假字体或新建草稿。入口不复制选声逻辑，也不因纯音频或留白跳过 UISFX；无适用真实上下文时记录缺口，不制造空工程绕过。

`checks.timeline` 与 `checks.srt_match` 还必须有非空 `anchors`。每个锚点是 `{timeline_frame,source_frame,srt_cue,finding,evidence}`，帧从 0 开始，工程帧须在全片范围内，srt_cue 标明实际对应字幕。锚点按本片实际风险覆盖代表性区间，执行判断见 [制作检查](production-checks.md)，不以仅填一个数字冒充核对全文或复杂变速映射。

`checks.compatibility` 还记录 `current_version`、`basis_version`、非空 `profile` 对象、具体 `change_assessment` 和布尔值 `revalidation_required`。profile 记录实际容器、视频/音频编码、像素格式、色彩/HDR 与所依赖功能，多文件可按文件 id 分列。需重新核实的路径必须在 `native_open_review` 用相同 review 形式给出适用的实际原生证据；可以复用对当前配置适用的证据，不要求每文件都重新导入。草稿文件另外必须有其文件自身的可打开证据。

## 每次必有视觉参考检查记录

每次实际剪辑的 `checks.visual_references` 都必须存在，使用上文共同 review 字段，targets 覆盖当前 `production_plan` 和全部正式交付文件；状态及证据须通过核对。该字段不可因继续剪辑、仅声音/字幕、复用旧素材而省略。

- `scope="researched"`：完成本轮双站搜索与看图；`materials` 为非空数组，每项用 `noun`、`purpose` 说明素材名词与镜头用途。
- `scope="reused"`：复用有效参考，另给非空 `reuse_reason`；仍保留原双站搜索与看图证据，并记录本轮正式画面对照。部分新增/部分复用用 researched，在 finding 写各项依据。
- `scope="not_required"`：仅没有新增或重做视觉内容时使用，`materials=[]`，`reason` 具体说明范围与依据；仍需要共同 review 的 finding、evidence 和当前 targets。工具不可用不能作为 not_required 的理由。

researched/reused 还必须记录：`searches.pinterest` 和 `searches.cosmos` 均为 `{status:"pass",method:"实际途径",queries:["实际搜索词"],evidence:[{path,sha256}]}`，Cosmos 的 method 必须为 `mcp`；`selected_references` 为非空数组，每项含 `url`、具体 `takeaway` 与非空 `image_evidence=[{path,sha256}]`，指向实际查看过的图片/截图；`design_rules` 用文本写采用的造型、构图、配色、材质、光影等规则；`comparison` 写本轮正式输出对照观察及修正结果。动态参考和连续观察的适用要求继续执行，图片仅证明保存了图，不证明 agent 已观看或作品美术合格。

核对器拦截缺记录、单站漏查、Cosmos 用浏览器冒充 MCP、只有网址没有图片、缺少美术规则或成品对照、证据哈希失效、未绑定当前计划/正式文件等情况；失败返回 `delivery_ready=false` 和空链接。它核对记录与文件一致性，不能独立证明 agent 实际调用了工具或做出了正确审美判断；实际执行与如实记录仍由 agent 负责。

## 文件记录与已有检查结果

每个 `files` 项包括 `id`、`path`、`sha256`、`label`、`kind`、`role`、整数 `layer`、`audio`（`present`/`absent`）、`alignment_frame=0`、`disposition`、`previous_files`、`content_review`。`layer` 从下到上排序，用于最终交付表；label 是面向用户的文件用途。`kind` 为 `overlay`、`video`、`audio`、`subtitle` 或 `draft`。

`disposition="new"` 的交付文件不能沿用 source/SRT/assets/production_plan 或本轮任意文件项 previous_files 的路径；核对器汇总全部旧层身份，并用 `samefile` 排除大小写别名、硬链接等指向同一源/旧文件的情况。返修/重做的主文件必须列出 `previous_files=[{path,sha256}]`，并实际保留旧文件。返修/重做中需要新文件的辅助层还必须声明 `layer_change`：`updated` 表示更新既有层，必须列出上一版 previous_files；`added` 表示首次新增，previous_files 必须为空。只有经核实仍适用的辅助层可用 `disposition="reused"`，同时写明 `reuse_reason`；主文件始终是新文件。已缓存素材可以继续复用制作，但不能覆盖任何旧正式交付或借另一层旧路径冒充新文件。

媒体文件用 `technical_report={path,sha256}` 指向 `verify_delivery.py` 生成的现有 `jianying-delivery-technical/v1` 报告。核对器要求 `technical_pass` 与完整解码通过，报告路径/媒体哈希/种类/音轨、精确帧率、实际解码帧数、全片帧数和视频宽高均与当前记录一致。透明层还须有实际 Alpha 取样。每个 `audio="present"` 的文件另需 `audio_review`，记录实际同段合听与口播/BGM 避让；没有声音时无需伪造听音记录。

字幕或草稿用 `structure_report={path,sha256}` 指向其适用检查记录，形状为 `{"schema":"jianying-artifact-check/v1","status":"pass","kind":"subtitle或draft","file":"实际绝对路径","file_sha256":"实际哈希","checks":{...}}`。字幕的 checks 要求 `parse/timing/content="pass"` 且交付文件确为可读带时戳 SRT；草稿要求 `parse/references/timeline="pass"`，并在文件项增加 `native_open_review`，绑定同一草稿哈希及真实可打开证据。仅 JSON 成功写出不能代替这项要求。

## 静态和连续动态证据

`checks.timeline.required_motion_ranges` 必须是数组。每个风险区间声明 `{file_id,start_frame,end_frame,risk}`，`risk` 为 `high` 或 `low`，区间采用 `[start_frame,end_frame)`。只允许指向视频文件，且全部在最终全片范围内。无视频或无运动风险用空数组；视频文件采用空数组时还需 `checks.timeline.motion_rationale` 解释其静态内容和取样依据，不能任意填 N/A。

每文件 `motion_reviews` 使用共同 review 字段，并加 `start_frame/end_frame/method`。观察范围必须覆盖对应声明区间；high 风险要求 `method="continuous"`，low 风险允许 `keyframes`。连续查看的是所需短区间，不要求全片播放。证据可以直接指向同一正式视频并复用其技术报告；若是单独提取的连续短媒体，则 evidence 的该项增加 `technical_report={path,sha256}` 指向其已有完整解码报告。报告必须绑定该证据路径与哈希，实际有至少两帧视频，且其帧数/帧率所确定的时长不短于声明观察区间；PNG、PNG 改后缀、过短片段或缺少实际视频技术报告的文件不能充当完整连续证据。

连续观察与必要合成关系仍按制作检查执行；helper 不会仅凭技术报告判断遮罩、动作或听感正确，也不重新生成测试片。

## 交付状态

全部必需项通过后，清单生成每个正式文件的绝对路径 Markdown 链接，自动处理中文、空格和标签中的方括号，并在发出链接前复核输入、计划、证据和正式文件的哈希及 UISFX 绑定。结果保存 production_plan 身份和 UISFX 完成摘要。清单固定声明 `user_performs=["import","placement","replacement"]`、`post_import_review=false`、`native_editor_mutated=false`，用户验收保持 `not_assessed`。用户导入后不自动检查，交付后结束。

可运行的隔离样例和失败边界见 `tests/finalize_delivery_test.py`。其中记录单元测试使用明确标注的 fixture；另有一项真实本地 QTRLE → 现有技术检查器 → 本核对器的串接，不能把 fixture 或测试通过说成用户视频已经通过内容/原生验收。
