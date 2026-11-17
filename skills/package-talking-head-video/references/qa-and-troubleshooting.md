## User editing workflow precedence

普通剪映文件交付必须执行 [可用性检查](../../video-editing-playbook/references/file-delivery.md) 与正式改动区间内容检查；下文的旧版 Gate、固定八种结构、固定保护坐标及独立整片审阅仅在用户明确请求对应旧流程时参考，不覆盖总规则的实际人物区域、竖屏精选留白和手动导入分工。

Read [video-editing-playbook](../../video-editing-playbook/SKILL.md) first. Use failure recipes only for an actual reported problem. Repository tests and legacy Gate D run only on explicit request; formal-file decode, specifications, alpha and content checks remain mandatory under the shared delivery contract. The user performs acceptance and export.

# QA and troubleshooting

## Required repository checks

1. `npm test`
2. `npm run typecheck`
3. `npm run build`
4. `npm run verify:public`
5. `npm audit --omit=dev`

## Required artifact checks at Gate D

1. ffprobe output facts: dimensions, duration, fps, codecs, audio, size;
2. complete FFmpeg decode;
3. black-segment detection;
4. eight frames from eight distinct semantic structures;
5. 4×2 contact sheet;
6. SHA-256 for output and frames;
7. manifest read-back.
8. stable review frames sampled at 72% of each beat;
9. manual visual checklist from `visual-quality-gates.md` with no failures.

## Common failures

- **Chromium cannot decode HEVC:** create an H.264/AAC proxy with identical duration and no timeline changes.
- **Duplicate subtitles:** use `--captions burned-in` when the source already contains captions.
- **Everything looks like the same card:** inspect `data-structure-identity`; each semantic contract must use its own DOM/composition hierarchy, not just another palette.
- **Presenter is covered:** move foreground elements to the side lanes, or use verified behind-presenter layering with a synchronized subject matte; otherwise use opaque full-screen. Follow the shared occlusion reference for edge and motion QA.
- **Side card is mostly empty:** remove fixed top-to-bottom sizing, use content-fit height, and collapse two sparse rails into one compact rail when the semantics allow it.
- **Subtitle is covered:** keep critical content above the bottom 18% reserve.
- **Black SVG block:** put `fill="none"` directly on open SVG elements; do not rely only on CSS.
- **Evidence claim without proof:** supply an approved source asset or downgrade to `thesis-and-proof`.
- **Motion works only during playback:** remove timers, random values, transitions, and runtime state; derive motion from the current frame.
- **Build passes but output is wrong:** inspect the actual Gate C stills and Gate D artifact. Build status is not visual proof.
