## User editing workflow precedence

普通剪映文件交付必须执行 [可用性检查](../../video-editing-playbook/references/file-delivery.md) 与正式改动区间内容检查；下文的旧版 Gate、固定八种结构、固定保护坐标及独立整片审阅仅在用户明确请求对应旧流程时参考，不覆盖总规则的实际人物区域、竖屏精选留白和手动导入分工。

Read [video-editing-playbook](../../video-editing-playbook/SKILL.md) first. Legacy approval and review workflow: use only when the user explicitly requests this gated review/export mode. Ordinary editing uses the direct workflow in the skill entrypoint and must not invoke the bundled gate CLI. The user performs acceptance and export.

# Four cumulative gates

## Gate A — source and plan

No approval flags. Write `BRIEF.md`, `SOURCE_PROBE.json`, `STORYBOARD.md`, `storyboard.json`, and `input-manifest.json`. Record hashes, media properties, every SRT cue, caption mode, semantic structures, placement, evidence status, full-screen exceptions, and risks. Do not build review visuals or render.

Show the plan to the user and stop. Approval must refer to this exact job.

## Gate B — composition inputs

Requires `--approve-gate-a --approve-gate-b`. Prepare the browser-compatible continuous source, props, and renderer project. No final video.

## Gate C — review evidence

Requires `--approve-gate-a --approve-gate-b --approve-gate-c`. Generate eight semantically distinct stills and a contact sheet from the real composition. A video with fewer than eight distinct structures fails Gate C. Review hierarchy, face clearance, subtitle clearance, evidence legibility, doodle meaning, and structural difference. No final MP4.

## Gate D — final export

Requires all four approval flags plus `--render`. Render the final artifact, probe it, decode the entire file, detect black segments, extract eight representative frames, build a contact sheet, and write `RENDER_MANIFEST.json` with hashes and media facts.

Never describe an unrendered project, component gallery, or contact sheet as a delivered video.
