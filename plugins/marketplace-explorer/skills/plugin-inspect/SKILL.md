---
name: plugin-inspect
description: Explain what one specific Codex plugin actually contains and does, in Chinese - its manifest, skills, commands, subagents, MCP servers and hooks. Use when the user asks what a plugin does, asks to see the contents of a plugin, or wants to compare plugins before installing.
---

# 看某个插件的具体内容

给一个 `插件名` 或 `插件名@市场名`，把它里面的东西用中文摊开讲。

## 步骤

1. 拿到插件的本地路径，最快的办法是查目录数据：

   ```bash
   python <plugin>/scripts/build_catalog.py --json-out <work>/catalog.json
   ```

   然后在 `catalog.json` 里按 `name` / `pluginId` 找到这条记录，取 `path`。

2. 直接读这些文件（有哪个读哪个）：

   - `<path>/.codex-plugin/plugin.json`（或 `.claude-plugin/`）：清单、`interface` 里的介绍、能力、默认提示词
   - `<path>/skills/*/SKILL.md`：每个技能的 YAML front matter 和正文要点
   - `<path>/commands/*.md`、`<path>/agents/*.md`：命令和子代理
   - `<path>/.mcp.json`：挂了哪些 MCP 服务
   - `<path>/hooks.json`：有没有自动钩子
   - `<path>/README.md`：作者自己写的说明

3. 用中文回报，结构建议：这个插件是干什么的 → 提供了哪些技能（逐个一句话）→ 命令/子代理/MCP → 装它需要什么（要不要账号、要不要 API key）→ 是否已安装，没装的话给 `codex plugin add <pluginId>`。

## 注意

- 直接读原文，别只看市场清单里的简短描述，清单里往往没有描述。
- 全部是只读操作。不要顺手替用户安装插件。
