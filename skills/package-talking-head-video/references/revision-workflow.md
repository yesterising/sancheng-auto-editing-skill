# 正式输出的局部检查与有限返修

按总规则的正式文件检查执行，并遵循 [可用性与手动交付](../../video-editing-playbook/references/file-delivery.md)。检查已生成的正式文件，抽取物只放本任务 work/；不生成另一版测试片、不新建剪映测试工程、不主动保存/重开、不导出整条口播。检查与用户验收分别记录，检查通过不能记为用户已认可。

[代表镜头预演](../../video-editing-playbook/references/visual-quality-and-preflight.md) 是批量制作前对本片正式场景的内部开发与观察，可在 `work/` 生成必要阅读态和连续短区间；上述限制针对另做测试成片或审批片。预演与本阶段共享同一问题的自动返修预算，正式文件仍须独立完成本流程的实际观察。

## 定位范围与执行

完成原有 SRT、字体、动作与来源准备后生成正式素材。每个 build 记录本版输入、场景缓存键、时间范围、声音内容指纹及其实际占用帧区间 `effective_range_frames`；区间从制作时的实际音频采样事实确定，旧声音检查不重新读取可能已变短或已不存在的历史声源。返修用旧/新 build 的实际场景键确定改动，不能拿两版计划重新读取同一个已变化文件来推断历史。声音范围包含被删除声音原来占用的区间。历史 build 缺少占用范围时，从该事件已知实际起音帧保守检查到片末；helper 在 `audio_scope_fallbacks` 列明来源与原因，检查记录必须说明该范围是保守回退，不能冒称已精确定位旧尾音。首次正式制作没有旧版时，各新增场景属于改动范围，观察关键动作，不全片逐帧扫描。

```bash
python3 <skill-root>/scripts/revision_workflow.py policy
python3 <skill-root>/scripts/revision_workflow.py sample --plan /task/work/plan-v2.json --build /task/outputs/v2.mov.build.json --previous-build /task/outputs/v1.mov.build.json --out-dir /task/work/review-v2 --ffmpeg /existing/ffmpeg --ffprobe /existing/ffprobe
```

静态样本只是基础提取，高风险短动态还必须按 [制作检查](../../video-editing-playbook/references/production-checks.md) 连续查看同版正式组合并记录证据，不能因本 helper 抽样通过就直接交付。最终仍由总规则的统一清单核对同版记录和链接。

首次制作省略 previous-build。helper 验证正式文件哈希、尺寸、帧率、帧数与 Alpha 像素格式，再按改动场景取首帧、入场落稳、阅读态和末帧。场内有 [已实现事件](recipe-production.md) 时，额外取事件前/当/后帧及有关连续窗口，生成 `event_windows` 与带场景/帧号的 `contact-sheet.html`；窗口使用实际工程帧率并限于本场，必要时按动作范围扩展。评估须对事件留具体证据，不能只看场景中点。相关声音从同一正式文件按改动区间提取。Alpha 像素格式不证明每个区间实际透明，图片也不能证明声音听感。排查漏音可按配方生产参考使用 `sound-check`；它不替代 UISFX 判断或混听。

agent 用当前图像/音频读取能力实际观察提取物：1）文字内容、真实字形、运动极值截字；2）脸、手、字幕和证据可读性；3）全屏与人物窗口覆盖、真实源时间映射和同步；4）声音冲击点、尾音、叠加及已知口播/BGM 遮蔽。只看孤立包装不能证明与原片的遮挡和混音。对本次新增/改动的实际叠加组合，必须在 work/ 按交付层级将原片对应帧与全部正式层合看，并将相关声音与原口播/BGM 同段合听，复用制作中可用的同版证据；检查首尾、转场和重点动作/阅读态，不复制备份原片或生成整片测试成片。用户只负责导入/拖入/替换，素材和合成关系检查不能转交用户；用户导入后不再自动检查。无法读取的声音/画面明确记 unavailable。

上述 helper 对应 scene_pack 的正式素材路径。Blender、真实人物层及剪映原生文字沿各自已有的动作/场景计划，读取本次正式输出或原生改动区间的必要画面与声音，记录同样的范围、证据和返修轮次；不为了套 helper 制造空 HTML、重建工程或烘焙替代底片。原生区间无法实际读取时如实记录检查缺口，不把计划或草稿 JSON 当作已见画面。

对每个改动场景及相关声音留具体观察，引用真实提取物，不能只填“效果通过”。示例 findings：

```json
{"visual_status":"issues","audio_status":"not_applicable","observations":[{"kind":"visual","evidence":"/task/work/review-v2/frame-000000216.png","finding":"冲击标题入场超出右边界；缩短重点或重新排版"}]}
```

```bash
python3 <skill-root>/scripts/revision_workflow.py assess --review /task/work/review-v2/review.json --findings /task/work/findings-v2.json --out /task/work/assessment-v2.json
```

状态使用 pass/issues/unavailable；没有对应改动取样时用 not_applicable。unavailable 需 visual_limitation/audio_limitation 说明原因。helper 只校验记录，不替 agent 看图听音，也不生成审美分数。

## 停止条件

首次观察 repair_round=0。发现可明确定位、仍在原范围内的问题时生成定点 patch，重建正式新版并对照紧邻旧 build；下一次 sample 加 `--prior-review /task/work/assessment-v2.json`。最多两轮自动返修，第三轮被拒绝。内容观察通过后进入文件交付检查，不能直接跳过全文件技术解码与兼容性核对。能力缺失、两轮后仍有问题、问题不确定或需要改变原片剪切/脚本时停止自动循环；未通过文件不作为可用成品交付，只能分别交付独立可用且无需用户修复/逐场拼接的部分并报告整体未完成，不扩展范围或反复要求用户审批。用户后来的新反馈可启动新一轮明确返修任务，不能把同一问题自动重命名绕过次数。

正式文件通过内容、技术与兼容性检查后，展示并链接交给用户自己导入和拖入；返修或重做均生成新文件并提供新文件链接，保留旧版，由用户自己替换；不代导入或替换。展示不重新启动另一套审阅。本流程在交付后结束，用户导入后不再自动检查；独立整片验收属于另一个明确任务。
