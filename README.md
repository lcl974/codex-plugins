# codex-plugins

`lcl974` 的 Codex 插件市场（plugin marketplace）。

仓库结构：

```
.
├── .agents/plugins/marketplace.json   市场清单：列出这个市场里有哪些插件
└── plugins/<plugin-name>/             每个插件一个目录
    ├── .codex-plugin/plugin.json      插件清单
    ├── skills/<skill-name>/SKILL.md   技能
    └── README.md
```

## 在 Codex 里添加这个市场

命令行：

```bash
codex plugin marketplace add lcl974/codex-plugins
codex plugin marketplace list          # 确认已挂上
codex plugin list                      # 看这个市场里有哪些插件
codex plugin add starter@codex-plugins # 安装插件（<插件名>@<市场名>）
```

桌面应用：插件管理 → Add Marketplace → 填 `lcl974/codex-plugins`。

改了仓库内容之后，本地刷新快照：

```bash
codex plugin marketplace upgrade codex-plugins
```

移除市场：

```bash
codex plugin marketplace remove codex-plugins
```

## 新增一个插件

1. 建目录 `plugins/<plugin-name>/`。
2. 写 `plugins/<plugin-name>/.codex-plugin/plugin.json`（`name` 要和目录名一致）。
3. 在 `plugins/<plugin-name>/skills/<skill-name>/SKILL.md` 放技能，开头是 `name` 和 `description` 的 YAML front matter。
4. 在 `.agents/plugins/marketplace.json` 的 `plugins` 数组里加一条对应的条目。
5. commit + push，然后 `codex plugin marketplace upgrade codex-plugins`。

## 已包含的插件

| 插件 | 说明 |
| --- | --- |
| `starter` | 最小模板插件，用来验证市场链路是否通，也当写新插件的样板。 |
