---
name: hello-codex
description: Verify that the codex-plugins marketplace and its starter plugin are installed and working. Use when the user asks to test the plugin marketplace, check whether a plugin from codex-plugins loaded, or wants a quick smoke test of plugin wiring.
---

# Hello Codex

一个只读的自检技能：确认 `codex-plugins` 市场和 `starter` 插件确实被 Codex 加载了。

## 步骤

1. 找到这个 `SKILL.md` 所在的目录（`.../plugins/starter/skills/hello-codex/`），往上两级就是插件根目录。
2. 读插件根目录下的 `.codex-plugin/plugin.json`，取出 `name`、`version`、`description`。
3. 检查同级的 `skills/` 目录里有哪些技能目录，列出名字。
4. 用一小段话回报结果，包含插件的 `name`、`version`、技能列表，以及判断：如果 `plugin.json` 读得到、`hello-codex` 自己在列表里，就说明市场链路是通的。

## 注意

- 只读操作，不修改任何文件。
- 如果读不到 `plugin.json`，直接说明失败，不要猜版本号。
