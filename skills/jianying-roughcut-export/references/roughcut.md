# 原始素材粗剪建轨

使用固定的本机虚拟环境运行项目自己的建轨脚本。该组件负责落地已有剪辑方案；语义选材与配音对齐应先完成。

```python
import pyJianYingDraft as d

folder = d.DraftFolder(STAGING)  # 外部暂存目录，不是剪映草稿库
script = folder.create_draft(NAME, 1920, 1080, fps=30)
for kind, name in [(d.TrackType.video, '主画面'),
                   (d.TrackType.audio, '人声'),
                   (d.TrackType.audio, '音乐'),
                   (d.TrackType.text, '中文字幕')]:
    script.append_track(d.TrackSpec(kind, name=name))
video = d.VideoMaterial(VIDEO_PATH)
# 成片0～3秒取原素材5～8秒。保留完整原文件便于用户调整入出点。
script.add_segment(d.VideoSegment(video, d.Timerange(0, 3_000_000),
                   source_timerange=d.Timerange(5_000_000, 3_000_000)), '主画面')
script.add_segment(d.AudioSegment(VOICE_PATH, d.Timerange(0, 3_000_000)), '人声')
script.add_segment(d.TextSegment('这里是已校对的字幕', d.Timerange(0, 3_000_000),
                   style=d.TextStyle(size=6.0, color=(1, 1, 1), align=1)), '中文字幕')
script.save()
```

所有路径由真实素材确定，示例变量不是默认值。字体、位置、画幅、音量按参考片和实际预览设定。视频与人声不属于同一源时，确保原视频自带声音被静音（VideoSegment 支持 volume 参数，使用前检查已安装 API）。音频源不足时调整范围，不自动拉伸真人音频。

同轨片段不重叠；需要同时显示的画面和同时播放的音频分别建轨。相邻段用统一整数边界相减得出时长，避免独立舍入引入缝隙。镜头顺序调整可能需要同步字幕与声音，不能仅改变画面后宣称整体同步。

运行 install_draft.py 前必须确认外部暂存草稿及其媒体完整。首次打包后仍在剪映中实际检查，字幕可读和媒体存在并不证明声音听感或内容正确。
