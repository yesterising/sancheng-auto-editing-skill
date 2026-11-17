#!/usr/bin/env python3
"""仅在用户明确要求新草稿文件时生成工程；默认剪辑沿用当前剪映，不调用此脚本。

用法: build_draft.py --plan plan.json --work-dir DIR
plan.json 结构:
{
  "name": "2万打卡-cut",
  "orientation": "V",
  "srt": "/abs/user-captions.srt",
  "fps": "30", "total_frames": 1800,
  "uisfx_selection": {"...": "由 uisfx.py bind --mode draft 生成的完整记录"},
  "font": "已选原生字体枚举名",
  "add_subtitles": false,
  "subtitles": [{"text": "...", "start": 0.75, "end": 2.5}],
  "sounds": [{"file": "/abs/selected-sound.wav", "time": 1.25, "vol": 0.2}],
  "video": "/abs/source.mp4",
  "segments": [{"src": 1.58, "end": 3.04, "text": "..."}],   // src=源片开始秒
  "titles":  [{"text": "...", "start": 55.0, "end": 60.5}],
  "huas":    [{"text": "...", "highlights": [{"word": "...", "color": "red"}],
               "start": 38.0, "end": 41.0, "size": 10.0}],
  "emphases": [{"keyword": "...", "color": "red"}]
}
先确认用户 SRT，再加载编辑器依赖；字体必须明确，不回退。
声音只取显式 sounds；即使留白也须绑定 UISFX 决策后才建草稿。新增字幕须开启并提供来自 SRT/最终映射的时序，不自动折行或按字数摊时间。
"""
import argparse
import importlib.util
import json
import os
import sys

def load_runtime():
    """Load editor dependencies only after input validation."""
    global ClipSettings, FilterType, FontType, KF, KP
    global TextBorder, TextShadow, TextStyle, Timerange, TrackType, JyProject
    skill_root = os.getenv("JY_SKILL_ROOT", os.path.expanduser("~/.codex/skills/jianying-editor"))
    sys.path.insert(0, os.path.join(skill_root, "scripts"))
    sys.path.insert(0, os.path.join(skill_root, "scripts", "vendor"))
    from pyJianYingDraft import (
        ClipSettings, FilterType, FontType, Keyframe as KF, KeyframeProperty as KP,
        TextBorder, TextShadow, TextStyle, Timerange, TrackType,
    )
    from jy_wrapper import JyProject


GOLD = (1.0, 0.8, 0.22)
WHITE = (1.0, 1.0, 1.0)
RED = (1.0, 0.22, 0.22)
COLORS = {"red": RED, "gold": GOLD, "white": WHITE}


def us(sec: float) -> int:
    return int(sec * 1_000_000)


def validate_plan(plan, require_selection=True):
    """Reject missing user inputs before creating an editor project."""
    srt = plan.get("srt")
    if not srt:
        raise ValueError("缺少用户提供的 SRT；请先提供当前视频对应的字幕文件。")
    try:
        with open(srt, encoding="utf-8-sig") as f:
            srt_text = f.read()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"SRT 无法读取：{srt}") from exc
    if "-->" not in srt_text:
        raise ValueError(f"SRT 未包含可用的字幕时间轴：{srt}")
    if not plan.get("font"):
        raise ValueError("缺少本项目已选字体 font；不能自动回退字体。")
    if plan.get("add_subtitles") and not plan.get("subtitles"):
        raise ValueError("新增字幕需要明确的 subtitles 时序，取自 SRT 或最终剪切映射。")
    if plan.get("farts"):
        raise ValueError("声音请通过显式 sounds 事件指定实际文件，不使用旧版自动配声字段。")
    sounds = []
    for item in plan.get("sounds", []):
        path = item["file"]
        if not os.path.isabs(path):
            if not plan.get("sfx_dir"):
                raise ValueError("声音须使用绝对路径，或显式提供 sfx_dir。")
            path = os.path.join(plan["sfx_dir"], path)
        if not os.path.isfile(path):
            raise ValueError(f"指定音效文件不存在：{path}")
        sounds.append((item["time"], path, item.get("vol", 0.7)))
    if require_selection:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uisfx.py')
        spec = importlib.util.spec_from_file_location('draft_uisfx_gate', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_selection(plan, 'draft')
    return sounds


def add_hua(project, text, highlights, start, end, size, y, font):
    # 统一字号：去掉 highlight 里的 size 覆盖，避免同一行文字大小不一/变形
    # 全句先铺一层基础金色样式，未高亮文字才不会丢失样式/撑大换行
    hl = [{"word": text, "color": GOLD}] + [{k: v for k, v in h.items() if k != "size"} for h in highlights]
    seg = project.add_rich_text(
        text, highlights=hl,
        start_time=us(start), duration=us(end - start), track_name="HuaZi",
        style=TextStyle(size=size, color=GOLD, bold=True, align=1, auto_wrapping=False, max_line_width=0.92),
        font=font,
        border=TextBorder(color=(0, 0, 0), alpha=1.0, width=46),
        shadow=TextShadow(color=(0, 0, 0), alpha=0.9, diffuse=40, distance=6, angle=-45),
        clip_settings=ClipSettings(transform_y=y),
    )
    if seg is None:
        return
    seg.add_keyframe(KP.alpha, 0, 1.0)
    for t, v in ((0, 1.9), (0.3, 0.92), (0.5, 1.05), (0.7, 1.0)):
        seg.add_keyframe(KP.uniform_scale, us(t), v, **KF.EASE_OUT)
    seg.add_keyframe(KP.rotation, 0, -6, **KF.EASE_OUT)
    seg.add_keyframe(KP.rotation, us(0.45), 0, **KF.EASE_OUT)


def add_title(project, text, start, end, size, y, font):
    seg = project.add_text_simple(
        text, start_time=us(start), duration=us(end - start), track_name="Titles",
        style=TextStyle(size=size, color=GOLD, bold=True, align=1, auto_wrapping=False, max_line_width=0.9),
        font=font,
        border=TextBorder(color=(0, 0, 0), alpha=1.0, width=34),
        shadow=TextShadow(color=(0, 0, 0), alpha=0.8, diffuse=10, distance=4, angle=-45),
        clip_settings=ClipSettings(transform_y=y),
    )
    if seg is not None:
        for t, v in ((0, 1.35), (0.25, 0.97), (0.45, 1.0)):
            seg.add_keyframe(KP.uniform_scale, us(t), v, **KF.EASE_OUT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--work-dir", required=True)
    args = ap.parse_args()
    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)

    try:
        sfx_plan = validate_plan(plan)
    except ValueError as exc:
        ap.error(str(exc))
    load_runtime()
    font = getattr(FontType, plan["font"], None)
    if font is None:
        ap.error(f"当前原生接口不支持已选字体：{plan['font']}；请使用可满足该字体的制作路径。")
    filter_spec = plan.get("filter")
    filter_type = None
    if filter_spec:
        filter_type = getattr(FilterType, filter_spec["name"], None)
        if filter_type is None:
            ap.error(f"当前接口不支持滤镜：{filter_spec['name']}")

    vertical = plan.get("orientation", "V") == "V"
    w, h = (1080, 1920) if vertical else (1920, 1080)
    project = JyProject(plan["name"], width=w, height=h, overwrite=plan.get("overwrite", False))
    video_local = plan["video"]  # Reuse the source path; no source-media backup.

    # 1. 主视频：按剪辑点切段（每段独立出入点）
    segs = plan["segments"]
    t = 0.0
    video_segs = []
    for s in segs:
        dur = s["end"] - s["src"]
        seg = project.add_media_safe(
            video_local, start_time=us(t), duration=us(dur),
            track_name="VideoTrack", source_start=us(s["src"]),
        )
        if seg is not None:
            video_segs.append({"start": t, "end": t + dur})
        t += dur
    print(f"video segments: {len(video_segs)} total {t:.2f}s")
    if filter_type is not None:
        project.script.add_track(TrackType.filter, "滤镜")
        project.script.add_filter(filter_type, Timerange(0, us(t)),
                                  intensity=filter_spec.get("intensity", 45))
    # Only add explicitly requested BGM, referencing its existing file.
    bgm_name = plan.get("bgm")
    if bgm_name:
        bgm_src = bgm_name if os.path.isabs(bgm_name) else os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "bgm", bgm_name)
        if os.path.exists(bgm_src):
            bgm_seg = project.add_media_safe(bgm_src, start_time=0, duration=us(t), track_name="BGM")
            if bgm_seg is not None:
                bgm_seg.volume = plan.get("bgm_vol", 0.14)

    # 2. 按显式最终时序新增字幕与重点高亮
    sub_size, sub_y = (8.5, -0.536) if vertical else (6.5, -0.8)
    emph_size = 9.5 if vertical else 7.5
    sub_shadow = TextShadow(color=(0, 0, 0), alpha=1.0, diffuse=50, distance=3, angle=-45)
    sub_clip = ClipSettings(transform_y=sub_y)
    emph_map = plan.get("emphases") or []
    hua_windows = [(hua["start"], hua["end"]) for hua in plan.get("huas", [])]

    def _overlap(a, b):
        return a[0] < b[1] and b[0] < a[1]

    # Explicit cues carry SRT/final-edit timing; no character-proportional retiming.
    entries = []
    if plan.get("add_subtitles"):
        for cue in plan["subtitles"]:
            emph = next((e for e in emph_map if e["keyword"] in cue["text"]), None)
            entries.append({**cue, "emph": emph})
    # 花字出现时隐藏重叠的常规字幕
    entries = [e for e in entries if not any(_overlap((e["start"], e["end"]), w) for w in hua_windows)]
    emph_times = []
    structure_words = plan.get("structure_words") or []
    for e in entries:
        sw = next((w for w in structure_words if w in e["text"]), None)
        if sw:
            # Explicit structure words receive visual emphasis; sound is event-driven.
            seg = project.add_rich_text(
                e["text"], highlights=[
                    {"word": e["text"], "color": WHITE},
                    {"word": sw, "color": GOLD, "bold": True},
                ],
                start_time=us(e["start"]), duration=us(e["end"] - e["start"]),
                track_name="Subtitles",
                style=TextStyle(size=emph_size + 2.5, color=WHITE, bold=True, align=1,
                                auto_wrapping=False, max_line_width=0.86),
                font=font, border=None, shadow=sub_shadow, clip_settings=sub_clip,
            )
            if seg is not None:
                seg.add_keyframe(KP.uniform_scale, 0, 1.25, **KF.EASE_OUT)
                seg.add_keyframe(KP.uniform_scale, us(0.4), 1.0, **KF.EASE_OUT)
        elif e["emph"]:
            color = COLORS.get(e["emph"]["color"], GOLD)
            seg = project.add_rich_text(
                e["text"], highlights=[
                    {"word": e["text"], "color": WHITE},
                    {"word": e["emph"]["keyword"], "color": color, "bold": True},
                ],
                start_time=us(e["start"]), duration=us(e["end"] - e["start"]),
                track_name="Subtitles",
                style=TextStyle(size=emph_size, color=WHITE, bold=True, align=1,
                                auto_wrapping=False, max_line_width=0.86),
                font=font, border=None, shadow=sub_shadow, clip_settings=sub_clip,
            )
            if seg is not None:
                seg.add_keyframe(KP.uniform_scale, 0, 1.1, **KF.EASE_OUT)
                seg.add_keyframe(KP.uniform_scale, us(0.35), 1.0, **KF.EASE_OUT)
            emph_times.append(e["start"])
        else:
            project.add_text_simple(
                e["text"], start_time=us(e["start"]), duration=us(e["end"] - e["start"]),
                track_name="Subtitles",
                style=TextStyle(size=sub_size, color=WHITE, bold=True, align=1,
                                auto_wrapping=False, max_line_width=0.86),
                font=font, border=None, shadow=sub_shadow, clip_settings=sub_clip,
            )
    print(f"subtitles: {len(entries)}, emphasis: {len(emph_times)}")

    # 3. 标题 + 花字
    title_size, title_y = (7.5, -0.453) if vertical else (6.5, -0.60)
    hua_y = -0.430 if vertical else -0.60  # 竖版 UI y=-826，比字幕高
    def_hua_size = 13.0 if vertical else 10.0
    for ttl in plan.get("titles", []):
        add_title(project, ttl["text"], ttl["start"], ttl["end"], ttl.get("size", title_size), title_y, font)
    for hua in plan.get("huas", []):
        hl = [{"word": x["word"], "color": COLORS.get(x.get("color", "red"), RED),
               "bold": True} for x in hua.get("highlights", [])]
        add_hua(project, hua["text"], hl, hua["start"], hua["end"],
                hua.get("size", def_hua_size), hua_y, font)

    # 4. 音效
    for ts, path, vol in sorted(sfx_plan):
        seg = project.add_media_safe(path,
                                     start_time=us(ts), track_name="SFX")
        if seg is not None:
            seg.volume = vol
    print(f"sfx: {len(sfx_plan)}")

    project.save()
    print("DRAFT_PATH", os.path.join(project.root, project.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
