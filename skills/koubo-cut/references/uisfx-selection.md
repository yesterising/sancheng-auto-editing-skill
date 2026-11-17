# UISFX 离线选声与同步

此文件是每次剪映自动剪辑必经的 UISFX 选声步骤，覆盖首次制作、继续剪辑、局部返修及仅字幕任务；实际剪辑仍先确认用户 SRT。修改 skill 或维护素材库无需 SRT。根据实际动作和口播语境，自主决定使用免费声音或留白，不以用户是否提到音效为触发条件，不让用户逐条报音效名。

## 必须完成并通过本地检查

每次都进入本流程，逐场/逐语义区间记录 `sound` 或 `silence`，带上具体动作、口播上下文、目的和理由。`start_frame`/`end_frame` 为判断覆盖范围，`anchor_frame` 为事件锚点；全片有意留白也要记录，不能用空 `events` 或空音轨代替判断。全片装配计划中每条决策必须给出实际 `scene_id`，范围位于该场之内，全部决策合起来覆盖完整时间轴。多个需要加强的动作可以有相互重叠的决策区间，不强制一种声音或一个事件覆盖整场。

使用总流程的 [语义事件](../../package-talking-head-video/references/semantic-events-and-reuse.md)时，声音决策沿用对应稳定事件 ID 或保留明确映射，`anchor_frame` 使用同一已解析全片帧。事件负责目标时间，本流程负责实际选声/留白与文件内锚点。事件、动作或语境改变时只重判相关决策，保留仍适用的材料；再按当前完整计划 `prepare`/`bind`/`check`，不能把复用旧声音文件等同于复用旧有效绑定，也不能因已有事件表跳过本流程。

仅字幕或明确不加声音的任务仍进入本流程，在当前修改范围记录留白原因，保护既有原声、BGM及无关音轨。局部返修只重判改动及其相关动作/语境，未变的有效决策复用，再绑定当前完整计划；不借强制步骤扩大返修范围。首次剪辑按全片判断，已有声音不因进入流程而强制重选。

先 `prepare` 输出实际声音和决策记录，把 `sounds`（或原生计划的 `draft_sounds`）写入当前制作计划，再 `bind` 将记录绑定到该计划。装配/交付前运行 `check`；`scene_pack.py validate/build` 与 `build_draft.py` 的正式入口也执行同一检查，没有跳过开关。缺记录、漏场景、时间基准不一致、字幕/画面计划或素材变化、声音落点/音量与记录不符时停止对应装配/导入，先补齐判断；即使最终零音效也须通过。该检查验证步骤与文件一致性，不验证审美或替代真实听感。

`bind` 只生成项目中的新计划文件，不操作剪映。记录包含当前计划与 SRT/相关视觉素材的指纹、决策报告哈希、实际音效文件哈希和声音落点；画面/字幕等实质变化后须重新进入选声步骤并绑定。旧计划仍可读取、比较和定点修改，正式装配前必须完成新绑定。原生界面/4B 路径用只读原生计划按 `--mode draft` 绑定、检查；这不授权创建新草稿。只有明确要求草稿文件才运行草稿生成器。

交付时简述“UISFX 选声已执行”、实际声音及主要留白原因。缺少前置 SRT或工具出错时明确报告阻塞，不能把未执行报成已完成；该步骤不增加用户确认、服务部署或付费调用。

## 先决定声音要做什么

在动作和时序确定后，为拟配声事件同时读取：1）画面实际发生的动作、速度、重量、材质、空间与接触/落稳点；2）口播前后句的意思、说话态度、重音及当前段落的叙事作用；3）声音要帮助观众感知的变化，如运动、接触、确认、反差或情绪。写出这三者如何支持选声，再确定候选音色、瞬态、时长与尾音；适合留白时明确记 `silence`。

禁止建立“口播关键词→音效 ID”、主题→固定音包、字幕类型→固定音效的表、正则或隐含轮换。上游 cue 和 category 是检索目录，不能当作中文语义判定。提到“钱”可能是冷静讲成本、展示增长或揭穿误区；应随该处画面与语气改变声音或留白，不能自动命中 purchase。不同词句出现相同物理动作，可以用同一声音；同一句话配不同动作，也可以选不同声音。示例用于说明判断方法，不能转成另一张固定映射表。

## 从真实文件缩小候选

用 `uisfx.py catalog` 了解音包的声学描述，按本次需要的声音质感与长度缩小到 2—4 个实际候选。现代、干净、有辨识度的声音可先比较 studio、scifi、glass、cinematic；它们只是本用户偏好的起查范围，选择仍由本次动作、口播和实际听感决定。避免长而松散的尾音挤占后一句，避免通过一味加音量制造“穿透力”；优先选起音清楚、在口播下仍可辨认的音色。UISFX 主要是短促 UI 声，不能冒称综艺梗音、真实物体拟音、剪映官方推荐或“爆款同款”；库内没有适用声音时留白或使用用户允许的其他免费素材，不硬套。

读取候选文件；用 `inspect --id` 检查真实起音、能量峰和时长，具备音频核听能力时听实际候选与该处口播。报告中的 onset/energy peak 只是 10 ms 窗口技术提示，不等于听感或语义最佳落点；没有听到时不能声称已试听。根据所选声音中需要对齐的起音/接触峰，明确填写 `source_anchor_ms`，不自动把所有文件的最大峰当作同一种锚点。检查相邻事件的强弱、尾音重叠和安静区间，不给每次文字出现配声。

默认候选为 864 个一次性声音，72 个 loop 不进入默认列表和事件编译。确需持续声时单独确定开始、结束、循环接缝和淡出，再用已有本地工具处理；不能把循环文件当作无截止时间的提示音。优先保持一条视频的声音质感连贯，反馈只改变获授权事件，不随机重选全片。

## 本机入口

素材位于本技能 `assets/uisfx/sounds/`，12 音包共 936 个 MP3。`manifest.json` 保存上游目录，`LICENSE-AUDIO` 保存 CC0 声明，`SOURCE.json` 保存固定提交及逐文件 SHA-256。仅包含音频数据，不运行上游网页或 npm 包；运行时只读本地文件，无账号、服务、模型下载、积分和付费接口，素材缺失或校验失败时报告原因，不联网补取或切换收费源。

加载既有运行环境后调用：

```sh
source "$SKILLS_DIR"/koubo-cut/runtime.env
"$KOUBO_PYTHON" "$SKILLS_DIR"/koubo-cut/scripts/uisfx.py catalog --pack studio
"$KOUBO_PYTHON" "$SKILLS_DIR"/koubo-cut/scripts/uisfx.py inspect --id studio/snap
"$KOUBO_PYTHON" "$SKILLS_DIR"/koubo-cut/scripts/uisfx.py verify
"$KOUBO_PYTHON" "$SKILLS_DIR"/koubo-cut/scripts/uisfx.py prepare --plan /absolute/project/sfx-plan.json --out-dir /absolute/project/work/sfx-v1
"$KOUBO_PYTHON" "$SKILLS_DIR"/koubo-cut/scripts/uisfx.py bind --context /absolute/project/work/scene-plan.json --receipt /absolute/project/work/sfx-v1/resolved.json --out /absolute/project/work/scene-plan-reviewed.json
"$KOUBO_PYTHON" "$SKILLS_DIR"/koubo-cut/scripts/uisfx.py check --context /absolute/project/work/scene-plan-reviewed.json
```

`prepare` 只执行 Codex 已结合上下文作出的选择，不自行分类口播。计划使用 `schema: uisfx-events/v1`、原片 `fps`、`total_frames` 和 `events` 数组。每个事件必须有稳定 `id`、`decision`（sound/silence）、`visual_action`、`speech_context`、`purpose`、`reason`、`anchor_frame`，正式剪辑还需 `start_frame`/`end_frame` 以及全片场景的 `scene_id`。声音事件另需明确的 `sound_id`（如 `studio/snap`）、`gain`（线性倍数）、`source_anchor_ms` 及 `anchor_kind`（contact/settle/speech_stress/reveal/motion_start）。这些字段由实际事件决定，不使用示例值作默认。安静事件不填写声音 ID、增益和文件内锚点。

输出到项目的新目录，保留原计划与素材。脚本生成 48 kHz 双声道 PCM16 WAV 及 `resolved.json`；其中 `sounds` 可原样接入 `package-talking-head-video/scripts/scene_pack.py` 的全片计划，须保持相同 fps 和 total_frames，再用 `bind` 生成带 `uisfx_selection` 的正式计划供装配器读取。`at_frame` 是画面/口播的目标锚点，`peak_offset_frames` 是文件内部锚点；现有装配器按两者之差计算播放开始，精度受项目帧率限制。原生计划使用 `draft_sounds`，提供实际 `fps`、`total_frames`、SRT、字体、源视频与最终 `segments`，按 `bind/check --mode draft` 验证；只在用户明确要新草稿时才交给 `build_draft.py`。显式 4B 的现有工程独立音轨按相同开始时刻、增益和来源布置，遵循其原有入口。

### 真实 Blender 或 FFmpeg 制作计划

已有制作路径不使用 scene_pack 或草稿结构时，用 `bind/check --mode production` 直接绑定实际计划，不伪造 HTML、配方、字体或新草稿。计划包含 `srt`、`source` 本地路径，`project.fps/total_frames`，按顺序完整覆盖全片的 `scenes`（各有 `id/start_frame/end_frame`），以及从同一 `prepare` 报告取得的显式 `sounds`（留白为 `[]`）。各场真实 renderer、布局、源映射等字段保持原样；外部场景、脚本、贴图等文件依赖列入顶层或该场的 `assets` 名称到路径映射，可选的 `project.font.file` 有实际文件才声明。相对路径以当前计划文件目录解析，绑定后的新计划保存真实绝对路径。

```sh
"$KOUBO_PYTHON" "$SKILLS_DIR"/koubo-cut/scripts/uisfx.py bind --mode production --context /absolute/project/work/actual-production-plan.json --receipt /absolute/project/work/sfx-v2/resolved.json --out /absolute/project/work/actual-production-plan-reviewed.json
"$KOUBO_PYTHON" "$SKILLS_DIR"/koubo-cut/scripts/uisfx.py check --mode production --context /absolute/project/work/actual-production-plan-reviewed.json
```

该适配先确认 SRT 可读，再检查实际源片、时序和声明依赖；绑定 SRT/源片/依赖的实际内容与完整计划（仅排除绑定记录自身），源映射、布局、场景或素材变化均使旧绑定失效。选声、留白覆盖、场景归属、实际声音文件及落点继续复用同一套 `prepare`、决策检查和 `validate_selection`，不另设自动选声或渲染流程。最终交付清单以该已绑定计划作为 `production_plan`，`uisfx_mode="production"`；核对器读取并检查绑定，不表示已完成渲染或内容观察。独立素材与 SRT 纠错不为套用此适配制造完整口播计划。

每个声音保留动作、语境、选声理由、来源提交、许可、哈希及落点。增益结合真实口播调整，不能把上游 UI 默认音量当作混音答案。按总规则核听正式输出本次改动区间，最多两轮定点返修；这是局部质量检查，不额外建立试听审批流程。按既有交付方式统一从 00:00 对齐，通过文件可用性检查后由用户自行导入；本脚本只准备素材与计划，不能将其成功运行报成已导入或已剪辑。
