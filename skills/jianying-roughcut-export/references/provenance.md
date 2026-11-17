# 来源与安装范围

本机技能 `jianying-roughcut-export` 是针对用户粗剪交接需求的封装，不是上游发布的同名 skill。

- 上游仓库：https://github.com/Vincentwei1021/video-shotcraft
- 固定提交：`5e71af35a2daee492dd3ea93e5e8903f32dcd13c`
- `vendor/mac_draft.py`：原样保存 `jianying-export/mac_draft.py`，没有修改。
- `references/upstream-jianying-export.md`：原样保存上游导出教程。
- 上游 Apache-2.0 许可证随模块保留于 `vendor/LICENSE`。
- `scripts/install_draft.py`：本机新增包装，保留暂存源、拒绝覆盖同名草稿，补充实际应用进程名检查。
- 未安装完整 video-shotcraft 宣传片工作流、Remotion、video-talkcraft 或任何音频识别模型。
- 运行时：`~/.local/share/codex/jianying-roughcut-export/.venv`，Python 3.11；依赖锁定记录同目录 `requirements.lock`。

模块不是一个独立的上游 SKILL.md 目录，所以通过 Skill Creator 本机封装，而非将整仓库作为宣传片技能加载。更新需重新审阅上游差异并测试，不自动追踪 main。
