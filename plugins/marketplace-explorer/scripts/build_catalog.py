#!/usr/bin/env python3
"""Build a browsable catalog (HTML) of every plugin in every configured Codex marketplace.

Pulls the plugin inventory from the Codex CLI (`plugin list --json --available`), then reads
each plugin's own manifest and skill folders so the catalog shows what a plugin actually does,
not just its catalog blurb.

Chinese text comes from a translation cache (zh.json); anything missing is shown in the
original language and can be dumped for translation with --emit-untranslated.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import re
import subprocess
import sys
from html import escape
from pathlib import Path

MANIFEST_DIRS = (".codex-plugin", ".claude-plugin", ".cursor-plugin")
MANIFEST_NAME = "plugin.json"


def find_codex() -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        hits = glob.glob(os.path.join(local, "OpenAI", "Codex", "bin", "*", "codex.exe"))
        if hits:
            return max(hits, key=os.path.getmtime)
    for name in ("codex", "codex.exe", "codex.cmd"):
        found = shutil_which(name)
        if found:
            return found
    raise SystemExit("could not find the codex CLI; pass --codex")


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def load_inventory(codex: str) -> dict:
    proc = subprocess.run(
        [codex, "plugin", "list", "--json", "--available"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise SystemExit(f"`codex plugin list --json --available` failed:\n{proc.stderr.strip()}")
    return json.loads(proc.stdout)


def read_manifest(plugin_dir: Path | None) -> dict:
    if plugin_dir is None:
        return {}
    for d in MANIFEST_DIRS:
        candidate = plugin_dir / d / MANIFEST_NAME
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
    return {}


FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def parse_front_matter(text: str) -> dict:
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    current: str | None = None
    for raw in match.group(1).splitlines():
        if re.match(r"^\s+\S", raw) and current:
            fields[current] = (fields[current] + " " + raw.strip()).strip()
            continue
        if ":" in raw:
            key, _, value = raw.partition(":")
            current = key.strip()
            fields[current] = value.strip().strip("'\"")
    return fields


def first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def collect_markdown_dir(plugin_dir: Path | None, sub: str) -> list[dict]:
    out = []
    if plugin_dir is None:
        return out
    base = plugin_dir / sub
    if not base.is_dir():
        return out
    for path in sorted(base.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = parse_front_matter(text)
        out.append(
            {
                "name": fm.get("name") or path.stem,
                "description": fm.get("description", "").strip(),
                "title": first_heading(text),
                "path": str(path),
            }
        )
    return out


def collect_skills(plugin_dir: Path | None, manifest: dict) -> list[dict]:
    if plugin_dir is None:
        return []
    roots = []
    declared = manifest.get("skills")
    if isinstance(declared, str):
        roots.append(plugin_dir / declared.lstrip("./"))
    roots.append(plugin_dir / "skills")

    seen: dict[str, dict] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            try:
                text = skill_md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = parse_front_matter(text)
            name = fm.get("name") or skill_md.parent.name
            seen.setdefault(
                name,
                {
                    "name": name,
                    "description": fm.get("description", "").strip(),
                    "path": str(skill_md),
                },
            )
    return list(seen.values())


def collect_mcp(plugin_dir: Path | None, manifest: dict) -> dict:
    servers: dict[str, str] = {}
    if plugin_dir is None:
        return {"servers": [], "remote": [], "local": []}
    candidates = []
    declared = manifest.get("mcpServers")
    if isinstance(declared, str):
        candidates.append(plugin_dir / declared.lstrip("./"))
    candidates.append(plugin_dir / ".mcp.json")
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        block = data.get("mcpServers") or data.get("servers") or {}
        if not isinstance(block, dict):
            continue
        for name, spec in block.items():
            kind = "local"
            if isinstance(spec, dict) and any(k in spec for k in ("url", "serverUrl", "httpUrl", "endpoint")):
                kind = "remote"
            servers[name] = kind
    return {
        "servers": sorted(servers),
        "remote": sorted(n for n, k in servers.items() if k == "remote"),
        "local": sorted(n for n, k in servers.items() if k == "local"),
    }


SCRIPT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".ps1", ".cmd", ".bat", ".exe", ".rb", ".go"}


def collect_scripts(plugin_dir: Path | None, manifest: dict) -> list[str]:
    """Executable code shipped inside the plugin (excluding vendored node_modules)."""
    if plugin_dir is None:
        return []
    roots = []
    declared = manifest.get("scripts")
    if isinstance(declared, str):
        roots.append(plugin_dir / declared.lstrip("./"))
    roots.append(plugin_dir / "scripts")
    roots.append(plugin_dir / "bin")

    found: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or "node_modules" in path.parts:
                continue
            if path.suffix.lower() in SCRIPT_SUFFIXES:
                found.add(str(path.relative_to(plugin_dir)))
    return sorted(found)


TIER_ORDER = {"推荐": 0, "可用": 1, "仅接口": 2, "需确认": 3, "未下载": 4, "不可用": 5}

OFFICIAL_MARKETS = {"openai-bundled", "openai-primary-runtime", "openai-api-curated"}

MACOS_RE = re.compile(
    r"\b(xcode\w*|macos|mac app\w*|appkit|swiftpm|app intents|liquid glass|notariz\w*|ios app\w*|ios simulator|ipados)\b",
    re.I,
)
ANDROID_RE = re.compile(
    r"\b(android emulator|android sdk|avd|adb|logcat|simpleperf|perfetto|gfxinfo)\b", re.I
)


def detect_platform(record: dict) -> str:
    blob = " ".join([record["summary"], record["details"]] + [s["name"] for s in record["skills"]])
    blob = blob.replace("-", " ").replace("_", " ")
    if MACOS_RE.search(blob):
        return "需要 macOS"
    if ANDROID_RE.search(blob):
        return "需要 Android 环境"
    return "通用"


def score_plugin(record: dict, host_os: str, local_available: bool) -> dict:
    """Four gates (source / auto-execution / substance / platform) plus cost labels.

    Metadata-only: it decides whether a plugin is *safe and substantive*, not whether it is
    useful for a particular job. Usefulness needs the user's own context.
    """
    official = record["marketplace"] in OFFICIAL_MARKETS or record["developer"] == "OpenAI"
    has_license = bool(record["license"] or record["licenseFile"])
    workflow = bool(record["skills"] or record["commands"] or record["agents"])
    has_mcp = bool(record["mcp"]["servers"])
    platform = detect_platform(record)
    remote_mcp = bool(record["mcp"]["remote"])
    skills_with_desc = [s for s in record["skills"] if s["description"]]
    coverage = len(skills_with_desc) / len(record["skills"]) if record["skills"] else 0.0
    content_strong = (len(skills_with_desc) >= 3 and coverage >= 0.8) or bool(record["commands"])

    notes: list[str] = []
    risks: list[str] = []
    costs: list[str] = []

    if not local_available:
        risks.append("远程 Git 源，本地尚未下载，内容无法检查")
        return {
            "tier": "未下载",
            "platform": "未知",
            "needsAccount": False,
            "contentStrong": False,
            "skillCount": 0,
            "notes": notes,
            "risks": risks,
            "costs": costs,
        }

    # gate 1 - source
    if official:
        source_ok = True
        notes.append(f"来自 OpenAI 精选/自带市场（{record['marketplace']}）")
    elif record["developer"] and has_license and record["privacyPolicy"] and record["termsOfService"]:
        source_ok = True
        notes.append(f"第三方市场，署名 {record['developer']}，许可 / 隐私政策 / 条款齐全")
    else:
        source_ok = False
        risks.append("来源信息不全：自建市场，或缺少署名、许可、隐私政策")

    # gate 2 - automatic execution
    if record["hasHooks"]:
        risks.append("带 hooks：写入文件后会自动运行插件里的脚本")
    # gate 3 - substance
    if not workflow and not has_mcp:
        risks.append("空壳：没有技能、命令，也没有 MCP 接口")
    elif not workflow:
        risks.append("只有 MCP 接口，没有技能说明该怎么用")
    # gate 4 - platform
    if platform != "通用":
        risks.append(f"{platform}，当前是 {host_os}")

    if remote_mcp:
        costs.append("需要第三方账号（远程 MCP 服务）")
    if "Write" in record["capabilities"]:
        costs.append("会写文件")
    if record["apps"]:
        costs.append("需要界面交互")
    if record["scripts"]:
        costs.append(f"附带 {len(record['scripts'])} 个脚本")
    if record["installed"]:
        notes.append("已安装")
    if content_strong:
        notes.append(f"内容扎实：{len(record['skills'])} 个技能 / {len(record['commands'])} 个命令")

    if platform == "需要 macOS" and host_os != "Darwin":
        tier = "不可用"
    elif not workflow and not has_mcp:
        tier = "不可用"
    elif record["hasHooks"] or not source_ok:
        tier = "需确认"
    elif not workflow:
        tier = "仅接口"
    elif not content_strong:
        tier = "可用"
    else:
        tier = "推荐"

    return {
        "tier": tier,
        "platform": platform,
        "needsAccount": remote_mcp,
        "contentStrong": content_strong,
        "skillCount": len(record["skills"]),
        "notes": notes,
        "risks": risks,
        "costs": costs,
    }


def as_list(value) -> list:
    """Manifests are inconsistent: capabilities/defaultPrompt are sometimes a bare string."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str) and v.strip()]
    return []


def plugin_record(entry: dict) -> dict:
    raw_path = entry.get("source", {}).get("path", "") or ""
    candidate = Path(raw_path)
    local_available = bool(raw_path) and candidate.is_absolute() and candidate.is_dir()
    plugin_dir = candidate if local_available else None
    manifest = read_manifest(plugin_dir)
    interface = manifest.get("interface") or {}
    license_files = sorted(p.name for p in plugin_dir.glob("LICENSE*")) if plugin_dir else []
    record = {
        "pluginId": entry.get("pluginId") or f"{entry.get('name')}@{entry.get('marketplaceName')}",
        "name": entry.get("name") or (plugin_dir.name if plugin_dir else raw_path),
        "displayName": interface.get("displayName") or manifest.get("name") or entry.get("name", ""),
        "marketplace": entry.get("marketplaceName", ""),
        "version": entry.get("version") or manifest.get("version", ""),
        "installed": bool(entry.get("installed")),
        "enabled": bool(entry.get("enabled")),
        "installPolicy": entry.get("installPolicy", ""),
        "authPolicy": entry.get("authPolicy", ""),
        "category": interface.get("category") or "",
        "summary": interface.get("shortDescription") or manifest.get("description", ""),
        "details": interface.get("longDescription") or manifest.get("description", ""),
        "capabilities": as_list(interface.get("capabilities")),
        "defaultPrompts": as_list(interface.get("defaultPrompt")),
        "developer": interface.get("developerName") or (manifest.get("author") or {}).get("name", ""),
        "homepage": interface.get("websiteURL") or manifest.get("homepage", ""),
        "license": manifest.get("license", ""),
        "licenseFile": bool(license_files),
        "privacyPolicy": interface.get("privacyPolicyURL", ""),
        "termsOfService": interface.get("termsOfServiceURL", ""),
        "commands": collect_markdown_dir(plugin_dir, "commands"),
        "agents": collect_markdown_dir(plugin_dir, "agents"),
        "skills": collect_skills(plugin_dir, manifest),
        "mcp": collect_mcp(plugin_dir, manifest),
        "scripts": collect_scripts(plugin_dir, manifest),
        "hasHooks": bool(plugin_dir and (plugin_dir / "hooks.json").is_file()),
        "apps": bool(plugin_dir and (plugin_dir / ".app.json").is_file()),
        "localAvailable": local_available,
        "path": raw_path or "(未下载)",
    }
    record["quality"] = score_plugin(record, platform.system(), local_available)
    return record


def build(records: list[dict]) -> list[dict]:
    records.sort(
        key=lambda r: (
            TIER_ORDER.get(r["quality"]["tier"], 9),
            0 if r["quality"]["contentStrong"] else 1,
            -r["quality"]["skillCount"],
            r["marketplace"],
            r["category"],
            r["displayName"].lower(),
        )
    )
    return records


def translated(value: str, zh: dict) -> str:
    if not value:
        return ""
    return zh.get(value.strip()) or ""


def collect_strings(records: list[dict]) -> list[str]:
    strings: dict[str, None] = {}
    for record in records:
        for key in ("summary", "details", "category"):
            value = (record.get(key) or "").strip()
            if value:
                strings.setdefault(value, None)
        for cap in record["capabilities"]:
            if isinstance(cap, str) and cap.strip():
                strings.setdefault(cap.strip(), None)
        for prompt in record["defaultPrompts"]:
            if isinstance(prompt, str) and prompt.strip():
                strings.setdefault(prompt.strip(), None)
        for item in record["skills"] + record["commands"] + record["agents"]:
            desc = (item.get("description") or "").strip()
            if desc:
                strings.setdefault(desc, None)
    return list(strings)


CSS = """
:root{--bg:#0f1115;--card:#171a21;--line:#262b36;--fg:#e6e8ee;--dim:#9aa3b2;--accent:#4f8cff;--ok:#2ea043;--warn:#d29922;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:"Segoe UI","Microsoft YaHei",system-ui,-apple-system,sans-serif;font-size:14px;line-height:1.6}
header{position:sticky;top:0;background:rgba(15,17,21,.94);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:16px 24px;z-index:5}
h1{margin:0 0 4px;font-size:18px}
.meta{color:var(--dim);font-size:12px}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;align-items:center}
input[type=search],select{background:var(--card);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:7px 10px;font-size:13px;min-width:220px}
select{min-width:0}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{background:var(--card);border:1px solid var(--line);border-radius:999px;padding:5px 12px;cursor:pointer;font-size:12px;color:var(--dim)}
.chip.on{background:var(--accent);border-color:var(--accent);color:#fff}
main{padding:20px 24px 60px;display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(380px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.card h2{margin:0;font-size:15px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.pid{color:var(--dim);font-size:11px;font-family:ui-monospace,Consolas,monospace}
.badge{font-size:11px;border-radius:999px;padding:2px 8px;border:1px solid var(--line);color:var(--dim)}
.badge.on{color:#fff;background:var(--ok);border-color:var(--ok)}
.badge.cat{color:var(--warn);border-color:var(--warn)}
.badge.tier-good{color:#fff;background:#1f6feb;border-color:#1f6feb}
.badge.tier-ok{color:#0b3d2c;background:#3fb950;border-color:#3fb950}
.badge.tier-info{color:#a5d6ff;border-color:#30455f}
.badge.tier-warn{color:#f0b429;border-color:#f0b429}
.badge.tier-none{color:#8b949e;border-color:#30363d}
.badge.tier-bad{color:#f85149;border-color:#f85149}
.summary{font-size:13px}
.orig{color:var(--dim);font-size:12px;font-style:italic}
details{border-top:1px dashed var(--line);padding-top:8px}
summary{cursor:pointer;color:var(--accent);font-size:12px;list-style:none}
summary::-webkit-details-marker{display:none}
.kv{font-size:12px;color:var(--dim);margin-top:6px}
.kv b{color:var(--fg);font-weight:600}
ul{margin:6px 0 0;padding-left:18px}
li{margin-bottom:3px}
.zh{color:var(--fg)}
.en{color:var(--dim);font-size:12px}
code{background:#0b0d11;border:1px solid var(--line);border-radius:6px;padding:1px 6px;font-family:ui-monospace,Consolas,monospace;font-size:12px}
.path{word-break:break-all;color:var(--dim);font-size:11px;font-family:ui-monospace,Consolas,monospace}
.empty{color:var(--dim);padding:40px;text-align:center}
"""

JS = """
const q = document.getElementById('q');
const market = document.getElementById('market');
const cards = [...document.querySelectorAll('.card')];
const filters = { status: 'all', tier: 'all' };
function apply(){
  const needle = q.value.trim().toLowerCase();
  let shown = 0;
  cards.forEach(card=>{
    const text = card.dataset.search;
    const okQ = !needle || text.includes(needle);
    const okM = market.value === 'all' || card.dataset.market === market.value;
    const okS = filters.status === 'all' || card.dataset.status === filters.status;
    const okT = filters.tier === 'all' || card.dataset.tier === filters.tier;
    const visible = okQ && okM && okS && okT;
    card.style.display = visible ? '' : 'none';
    if (visible) shown++;
  });
  document.getElementById('count').textContent = shown;
}
q.addEventListener('input', apply);
market.addEventListener('change', apply);
document.querySelectorAll('.chip[data-group]').forEach(chip=>{
  chip.addEventListener('click', ()=>{
    const group = chip.dataset.group;
    filters[group] = chip.dataset.value;
    document.querySelectorAll(`.chip[data-group="${group}"]`).forEach(c=>c.classList.remove('on'));
    chip.classList.add('on');
    apply();
  });
});
apply();
"""


def render(records: list[dict], zh: dict, out_path: Path) -> None:
    markets = sorted({r["marketplace"] for r in records})
    total = len(records)
    installed = sum(1 for r in records if r["installed"])
    tiers = ("推荐", "可用", "仅接口", "需确认", "未下载", "不可用")
    tier_counts = {tier: sum(1 for r in records if r["quality"]["tier"] == tier) for tier in tiers}
    translated_count = sum(1 for s in collect_strings(records) if s in zh)
    total_strings = len(collect_strings(records))

    options = "".join(f'<option value="{escape(m)}">{escape(m)}</option>' for m in markets)
    cards = []
    for r in records:
        def zh_or_en(text: str, css: str = "summary") -> str:
            text = (text or "").strip()
            if not text:
                return ""
            cn = translated(text, zh)
            if cn:
                return f'<div class="{css} zh">{escape(cn)}</div><div class="orig">{escape(text)}</div>'
            return f'<div class="{css}">{escape(text)}</div>'

        status_badge = (
            '<span class="badge on">已安装</span>'
            if r["installed"]
            else '<span class="badge">未安装</span>'
        )
        tier = r["quality"]["tier"]
        tier_class = {
            "推荐": "tier-good",
            "可用": "tier-ok",
            "仅接口": "tier-info",
            "需确认": "tier-warn",
            "未下载": "tier-none",
            "不可用": "tier-bad",
        }[tier]
        tier_badge = f'<span class="badge {tier_class}">{tier}</span>'
        cat = f'<span class="badge cat">{escape(r["category"])}</span>' if r["category"] else ""

        detail_bits = []
        quality = r["quality"]
        quality_lines = [f"平台：{quality['platform']}"]
        if quality["notes"]:
            quality_lines.append("通过：" + "；".join(quality["notes"]))
        if quality["risks"]:
            quality_lines.append("注意：" + "；".join(quality["risks"]))
        if quality["costs"]:
            quality_lines.append("使用成本：" + "；".join(quality["costs"]))
        detail_bits.append(
            "<div class='kv'><b>评分</b><div>" + "<br>".join(escape(line) for line in quality_lines) + "</div></div>"
        )
        if r["skills"]:
            items = []
            for s in r["skills"]:
                cn = translated(s["description"], zh)
                desc = f'<div class="zh">{escape(cn)}</div>' if cn else ""
                raw = f'<div class="en">{escape(s["description"])}</div>' if s["description"] else ""
                items.append(f'<li><b>{escape(s["name"])}</b>{desc}{raw}</li>')
            detail_bits.append(f"<div class='kv'><b>技能 ({len(r['skills'])})</b><ul>{''.join(items)}</ul></div>")
        if r["commands"]:
            items = "".join(f'<li>{escape(c["name"])} — {escape(c["description"] or c["title"])}</li>' for c in r["commands"])
            detail_bits.append(f"<div class='kv'><b>命令 ({len(r['commands'])})</b><ul>{items}</ul></div>")
        if r["agents"]:
            items = "".join(f'<li>{escape(a["name"])} — {escape(a["description"] or a["title"])}</li>' for a in r["agents"])
            detail_bits.append(f"<div class='kv'><b>子代理 ({len(r['agents'])})</b><ul>{items}</ul></div>")
        if r["mcp"]["servers"]:
            label = "、".join(
                f"{name}（{'远程' if name in r['mcp']['remote'] else '本地'}）" for name in r["mcp"]["servers"]
            )
            detail_bits.append(f"<div class='kv'><b>MCP 服务</b>: {escape(label)}</div>")
        if r["scripts"]:
            detail_bits.append(f"<div class='kv'><b>附带脚本</b>: {escape(', '.join(r['scripts'][:6]))}</div>")
        if r["capabilities"]:
            caps = ", ".join(translated(c, zh) or c for c in r["capabilities"])
            detail_bits.append(f"<div class='kv'><b>能力</b>: {escape(caps)}</div>")
        if r["defaultPrompts"]:
            items = "".join(f"<li>{escape(translated(p, zh) or p)}</li>" for p in r["defaultPrompts"])
            detail_bits.append(f"<div class='kv'><b>示例提示词</b><ul>{items}</ul></div>")
        if r["hasHooks"]:
            detail_bits.append("<div class='kv'><b>hooks</b>: 有（安装后自动生效的钩子）</div>")
        if r["license"]:
            detail_bits.append(f"<div class='kv'><b>许可</b>: {escape(r['license'])}</div>")
        if r["homepage"]:
            detail_bits.append(f"<div class='kv'><b>主页</b>: <a href='{escape(r['homepage'])}' style='color:var(--accent)'>{escape(r['homepage'])}</a></div>")
        detail_bits.append(f"<div class='kv'><b>安装</b>: <code>codex plugin add {escape(r['pluginId'])}</code></div>")
        detail_bits.append(f"<div class='kv'><b>本地路径</b><div class='path'>{escape(r['path'])}</div></div>")

        search_blob = " ".join(
            [r["pluginId"], r["displayName"], r["category"], r["summary"], r["details"]]
            + [translated(r["summary"], zh), translated(r["details"], zh)]
            + [s["name"] for s in r["skills"]]
            + [s["description"] for s in r["skills"]]
            + r["quality"]["costs"]
            + [r["quality"]["platform"]]
            + (["本地即可", "不需要账号"] if not r["quality"]["needsAccount"] else [])
        ).lower()

        cards.append(
            f"""<article class="card" data-status="{'on' if r['installed'] else 'off'}" data-tier="{escape(tier)}" data-market="{escape(r['marketplace'])}" data-search="{escape(search_blob)}">
  <h2>{escape(r['displayName'])} {tier_badge} {status_badge} {cat}</h2>
  <div class="pid">{escape(r['pluginId'])} · v{escape(r['version'] or '?')} · {escape(r['developer'])}</div>
  {zh_or_en(r['summary'])}
  <details>
    <summary>展开：看具体内容（{len(r['skills'])} 技能 / {len(r['commands'])} 命令 / {len(r['agents'])} 子代理）</summary>
    {"".join(detail_bits)}
  </details>
</article>"""
        )

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Codex 插件目录</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>Codex 插件目录</h1>
  <div class="meta">共 {total} 个插件（已装 {installed}），来自 {len(markets)} 个市场 ｜ {" · ".join(f"{t} {tier_counts[t]}" for t in tiers)} ｜ 中文覆盖 {translated_count}/{total_strings} 条文案 ｜ 生成于 {escape(__import__('time').strftime('%Y-%m-%d %H:%M'))}</div>
  <div class="controls">
    <input id="q" type="search" placeholder="搜索插件名 / 技能 / 中文描述…">
    <select id="market"><option value="all">全部市场</option>{options}</select>
    <div class="chips">
      <span class="chip on" data-group="tier" data-value="all">全部</span>
      {"".join(f'<span class="chip" data-group="tier" data-value="{t}">{t} {tier_counts[t]}</span>' for t in tiers)}
    </div>
    <div class="chips">
      <span class="chip on" data-group="status" data-value="all">安装状态不限</span>
      <span class="chip" data-group="status" data-value="on">已安装</span>
      <span class="chip" data-group="status" data-value="off">未安装</span>
    </div>
    <span class="meta">当前显示 <span id="count">{total}</span> 个</span>
  </div>
</header>
<main>
{"".join(cards)}
</main>
<script>{JS}</script>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=None, help="path to the codex executable")
    parser.add_argument("--zh", default=str(Path(__file__).with_name("zh.json")), help="translation cache")
    parser.add_argument("--out", default="catalog.html", help="output HTML path")
    parser.add_argument(
        "--emit-untranslated",
        nargs="?",
        const="-",
        default=None,
        metavar="PATH",
        help="write untranslated strings as JSON (default: stdout, ASCII-escaped) and exit",
    )
    parser.add_argument("--json-out", default=None, help="also write the raw catalog data as JSON")
    args = parser.parse_args()

    codex = args.codex or find_codex()
    inventory = load_inventory(codex)
    entries = list(inventory.get("installed", [])) + list(inventory.get("available", []))

    records = build([plugin_record(e) for e in entries])

    zh_path = Path(args.zh)
    zh = {}
    if zh_path.is_file():
        zh = json.loads(zh_path.read_text(encoding="utf-8"))

    if args.emit_untranslated:
        missing = [s for s in collect_strings(records) if s not in zh]
        payload = json.dumps(missing, ensure_ascii=False, indent=2)
        if args.emit_untranslated == "-":
            print(json.dumps(missing, ensure_ascii=True, indent=2))
        else:
            Path(args.emit_untranslated).write_text(payload, encoding="utf-8")
            print(f"untranslated: {len(missing)} strings -> {args.emit_untranslated}")
        return

    out_path = Path(args.out)
    render(records, zh, out_path)
    print(f"catalog: {out_path} ({len(records)} plugins)")

    for tier in ("推荐", "可用", "仅接口", "需确认", "未下载", "不可用"):
        picked = [r for r in records if r["quality"]["tier"] == tier]
        print(f"{tier}: {len(picked)}")
        if tier in ("推荐", "不可用", "需确认"):
            for r in picked:
                reason = "；".join(r["quality"]["risks"]) or "；".join(r["quality"]["notes"])
                print(f"  - {r['pluginId']}  [{reason}]")

    if args.json_out:
        json_path = Path(args.json_out)
        json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"data: {json_path}")


if __name__ == "__main__":
    main()
