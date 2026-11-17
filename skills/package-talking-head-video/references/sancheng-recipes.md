# 三橙配方与 HyperFrames 组件

当前剪映工程、SRT、字体、声音和交付分工以 [总规则](../../video-editing-playbook/SKILL.md) 为准。配方是可修改的动作起点，不是场景配额；先按语义选动作，再定参数。新增视觉优先遵循 [Lemo 接入优先级](../../video-editing-playbook/references/lemo-opuscar.md)，复杂三维需要时再走 Blender 路径。

按 [事件与场景契约](semantic-events-and-reuse.md)把行为实现与本期实例分开：复用现有配方或组件源码，本期另定内容、素材、实际字体/区域及事件输入。多个重要动作需要各自消费时间事件；配方参数不足时在本任务代码中适配，不把未实现字段当成有效控制。跨期复用仍检查长中文、条目数、画幅、避让、来源与 Alpha。

## 免费组件入口

已安装 hyperframes-registry（外部依赖，见仓库 README），上游原文归档与运行时版本见 [来源锁](../assets/registry-source.json)。上游原文独立归档，当前 skill 入口与本地 wrapper 统一执行用户规则。仅用本地开源渲染、已下载组件与有权使用的素材；这条增强路径不调用生成模型、账号权益、付费 API、云渲染或反馈上传。

通过本地固定版入口查询/下载，不在日常制作中触发 npm 下载、整包升级或移除旧技能：

```bash
node <skill-root>/scripts/registry_local.mjs search "before after wipe"
node <skill-root>/scripts/registry_local.mjs add before-after-wipe --dir /absolute/task/work/graphics
```

英文查询匹配本地词索引。目录可能报告跳过/未索引项；如实说明结果范围，不把搜索未命中当作组件不存在。`add` 从官方公共组件源下载源码，需要网络，无模型费用。已下载源码可以离线复用；固定本地示例在 `assets/registry-seed/`。不自动执行目录返回的反馈提交命令。

组件经常是 `<template>` 子合成，不能直接当独立页面截图。按它的挂载契约接入现有 HyperFrames 工程；需要进入本地场景渲染器时，先在任务 `work/` 适配为 `window.renderAt(t)`，所有脚本/字体/图片本地化，列入场景 `assets`。保持真实 Alpha，避免复制示例中的不透明全屏背景或英文字体。`custom-html` 不负责逐帧视频解码，也不产生原生剪映关键帧。

## 已实现配方

用 `python3 <skill-root>/scripts/scene_pack.py recipes` 读取机器可调用的 [配方目录](../assets/sancheng-recipes.json)。按 [配方生产](recipe-production.md) 使用用途/输入候选、事件参数、中文描边与真实资料几何；目录仅列本机实际实现，不替代 Lemo/HyperFrames 检索。以下二维动作已有可渲染实现：

| 配方 | 输入与动作 | 声音/实现边界 |
| --- | --- | --- |
| `impact-title` | 单行重点；快速缩放与轻微倾斜后落稳 | 声音峰值对齐落稳；首帧已有文字 |
| `evidence-focus` | 真实截图、焦点坐标与放大倍数 | 放大截图而非底下的口播原片 |
| `before-after` | 两张真实图片与两侧标签；分界揭示 | 以揭示完成作为可选声音锚点 |
| `object-converge` | 输入对象与结果；对象向结果汇聚 | 结果接管前输入对象可见 |
| `process-flow` | 2–6 个步骤；依序激活和连线 | 静音也可；不改变口播顺序 |
| `thesis-proof` | 单行观点、证据图、证据标签 | 用空间关系连接观点与证据 |
| `source-conclusions` | 真实图＋同版目标几何；结论逐条出现并框出依据 | 结论各有事件；来源持续可见 |
| `detail-overview` | 真实图＋同版目标几何；局部读清后拉回全图 | 拉回起止由事件控制，默认保留全图 |
| `path-converge` | 输入标签先连路径，再沿曲线汇入并留下结果 | 完成与阅读明确，按本期含义验证过程 |

`custom-html` 接收已按本片设计的本地页面，适合更复杂的组件改造。配方没有替代人物抠像、原片推近或画中画；这些仍由对应技能准备真实同步图层。模板只证明上述动作可生成，不保证任意长文字或构图都合适。

每场指定实际测量的 `zone=[x,y,w,h]`，相对画幅归一化；项目可声明脸部/字幕 `protected_regions`，工具拒绝相交。文字超宽时会报错，由 agent 提炼重点或重排，不默认换行/缩小。实际中文字体与字重显式绑定；工具检查文件与加载，汉字覆盖和合法使用仍由选字阶段确认。

## 从成片反馈改进配方

把“更有冲击力”等反馈定位成对象、时间段和可修改参数，再调用 [局部迭代](local-iteration.md)。只有用户确实接受的改法才可作为后续案例依据；文件生成、缓存复用和技术通过都不自动标为视觉验收。新增案例沿用已验证的代码和来源，避免累计空泛规则。
