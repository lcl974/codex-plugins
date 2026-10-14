---
name: marketplace-catalog
description: Build or refresh a searchable Chinese HTML catalog of every plugin in every configured Codex marketplace, translating plugin and skill descriptions on the way. Use when the user asks where to find plugins, wants to browse or search the plugin marketplace, wants the plugin list in Chinese, or asks what plugins are available.
---

# 插件市场中文目录

把 Codex 里所有已配置市场（含未安装的插件）汇总成一个单文件 HTML，翻成中文，并按可靠性分档。

## 分档规则（脚本内置，自动判定）

四道闸门：

1. **来源**：来自 OpenAI 精选市场（openai-api-curated / openai-bundled / openai-primary-runtime），或第三方市场但署名发布方 + 许可 + 隐私政策 + 条款齐全。
2. **自动执行**：装 `hooks.json` 的插件降级——它会在写文件后自动运行插件里的脚本。
3. **内容**：必须有技能或命令；只有 MCP 接口、没有技能说明用法的，单独归为「仅接口」；什么都没有的是空壳。
4. **平台**：需要 macOS 的（Xcode/SwiftUI/AppKit 那类）在 Windows 上归「不可用」。

分档结果：

| 档位 | 含义 |
| --- | --- |
| 推荐 | 四道闸门全过 + 内容扎实（≥3 个带说明的技能，或有命令） |
| 可用 | 过闸门，但内容偏薄（比如只有 1 个技能） |
| 仅接口 | 只给了 MCP 工具，没有技能告诉模型怎么用 |
| 需确认 | 带 hooks，或来源信息不全（自建市场 / 缺许可与隐私政策） |
| 未下载 | 远程 Git 源，本地还没有内容可检查 |
| 不可用 | 需要 macOS，或空壳 |

另外打成本标签（不影响分档）：需要第三方账号（远程 MCP）、会写文件、需要界面交互、附带脚本。

这套规则只回答「能不能放心装、内容够不够实」，不回答「对你有没有用」——后者要用户自己的场景。

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
