# marketplace-explorer

把 Codex 里所有插件市场的内容翻成中文，并生成一个能搜索、能点开看细节的本地页面。

页面还会按四道闸门给每个插件分档：**推荐 / 可用 / 仅接口 / 需确认 / 未下载 / 不可用**，
并单独标注「需要第三方账号」「会写文件」「需要界面交互」这类使用成本。

两个技能：

- `marketplace-catalog`：扫全部市场 → 翻译 → 生成中文 HTML 目录
- `plugin-inspect`：把某个插件的完整内容（清单、技能、命令、子代理、MCP、hooks）用中文摊开讲

两个脚本（都在 `scripts/`，只用 Python 标准库）：

- `build_catalog.py`：调 `codex plugin list --json --available` 拉清单，再读每个插件自己的
  `plugin.json` 和 `skills/`、`commands/`、`agents/`，渲染成单文件 HTML
- `translate.py`：把缺失的中文补进 `zh.json` 缓存。接口地址和密钥直接从 `~/.codex/config.toml`
  里读（仓库里不存任何密钥），因此换 provider 也不用改代码

手动跑：

```bash
python scripts/build_catalog.py --out catalog.html
python scripts/build_catalog.py --emit-untranslated missing.json
python scripts/translate.py --zh scripts/zh.json --missing missing.json
```

`zh.json` 是增量缓存：翻译过一次的文案下次直接命中，所以新装了市场只翻增量部分。
