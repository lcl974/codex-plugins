---
name: marketplace-catalog
description: Build or refresh a searchable Chinese HTML catalog of every plugin in every configured Codex marketplace, translating plugin and skill descriptions on the way. Use when the user asks where to find plugins, wants to browse or search the plugin marketplace, wants the plugin list in Chinese, or asks what plugins are available.
---

# 插件市场中文目录

把 Codex 里所有已配置市场（含未安装的插件）汇总成一个单文件 HTML，并翻成中文。

## 步骤

1. 定位脚本目录：本技能所在的插件根目录下的 `scripts/`（即 `.../plugins/marketplace-explorer/scripts/`）。
2. 先生成一次目录，同时看还缺哪些翻译：

   ```bash
   python <plugin>/scripts/build_catalog.py --out <workspace>/outputs/marketplace-catalog.html --json-out <workspace>/outputs/marketplace-catalog.json
   python <plugin>/scripts/build_catalog.py --emit-untranslated <work>/missing.json
   ```

3. `missing.json` 里还有内容就补翻译（增量，已翻过的会跳过）：

   ```bash
   python <plugin>/scripts/translate.py --zh <plugin>/scripts/zh.json --missing <work>/missing.json
   ```

4. 再跑一次第 2 步的第一条命令，让页面用上新的译文。
5. 把生成好的 HTML 路径告诉用户。

## 说明

- 用户新加了市场（`codex plugin marketplace add ...`）之后，重复 2–4 步即可，只会翻增量部分。
- `translate.py` 的接口地址和密钥是从 `~/.codex/config.toml` 里的 provider 配置读的。要在用之前跟用户说一句「会用你 config 里配置的那个模型接口来翻译」，别默认用户已经知道。
- 翻译有成本（按 token 计），量大时先告诉用户大概规模再跑。
- 目录只是读文件，不会改任何插件的状态；装不装插件交给用户决定。
