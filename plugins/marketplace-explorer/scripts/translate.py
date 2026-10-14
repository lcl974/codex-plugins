#!/usr/bin/env python3
"""Translate catalog strings into Chinese and cache them in zh.json.

Reads the provider endpoint and API key straight out of ~/.codex/config.toml (no secrets are
stored in this repo), batches the strings, and merges results into the cache as it goes, so an
interrupted run can simply be restarted.

Usage:
    python translate.py --zh zh.json --missing missing.json --model deepseek-chat
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SYSTEM_PROMPT = (
    "你是技术文档译者，负责把 Codex 插件市场的英文文案翻成简体中文。"
    "规则：1) 只输出 JSON 数组，长度与顺序和输入完全一致，不要解释、不要代码块围栏；"
    "2) 产品名、厂商名、命令、包名、路径、代码标识符、URL 保持原样；"
    "3) 术语统一：plugin=插件，skill=技能，marketplace=市场，command=命令，agent=子代理，hook=钩子，"
    "MCP server=MCP 服务，token=令牌，commit=提交，pull request=PR；"
    "4) 语气简洁自然，像给开发者看的产品说明，不要机翻腔；"
    "5) 已经是中文的条目原样返回。"
)

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def read_provider(config_path: Path, model_provider: str | None) -> tuple[str, str, str]:
    text = config_path.read_text(encoding="utf-8")
    if model_provider is None:
        match = re.search(r'(?m)^\s*model_provider\s*=\s*"([^"]+)"', text)
        model_provider = match.group(1) if match else None

    blocks = re.split(r"(?m)^\[model_providers\.([^\]]+)\]\s*$", text)
    providers: dict[str, str] = {}
    for i in range(1, len(blocks) - 1, 2):
        providers[blocks[i]] = blocks[i + 1]

    if model_provider and model_provider in providers:
        block = providers[model_provider]
    else:
        block = next((b for b in providers.values() if "experimental_bearer_token" in b), "")

    base = re.search(r'(?m)^\s*base_url\s*=\s*"([^"]+)"', block)
    token = re.search(r'(?m)^\s*experimental_bearer_token\s*=\s*"([^"]+)"', block)
    name = re.search(r'(?m)^\s*name\s*=\s*"([^"]+)"', block)
    if not base or not token:
        raise SystemExit(f"could not find base_url / experimental_bearer_token in {config_path}")
    return base.group(1).rstrip("/"), token.group(1), (name.group(1) if name else model_provider or "?")


def needs_translation(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 4:
        return False
    if CJK_RE.search(stripped):
        cjk = len(CJK_RE.findall(stripped))
        if cjk / max(1, len(stripped)) > 0.25:
            return False
    return bool(re.search(r"[A-Za-z]", stripped))


def chunk(items: list[str], char_budget: int, max_items: int) -> list[list[str]]:
    batches, current, size = [], [], 0
    for item in items:
        if current and (size + len(item) > char_budget or len(current) >= max_items):
            batches.append(current)
            current, size = [], 0
        current.append(item)
        size += len(item)
    if current:
        batches.append(current)
    return batches


def extract_json_array(text: str) -> list[str]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array in response: {text[:200]}")
    return json.loads(text[start : end + 1])


def call_api(base: str, token: str, model: str, batch: list[str], timeout: int = 120) -> list[str]:
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
            ],
            "temperature": 0.2,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return extract_json_array(data["choices"][0]["message"]["content"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zh", required=True, help="translation cache to create/update")
    parser.add_argument("--missing", required=True, help="JSON array of strings to translate")
    parser.add_argument("--config", default=str(Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "config.toml"))
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--batch-chars", type=int, default=3000)
    parser.add_argument("--batch-items", type=int, default=12)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0, help="only translate the first N strings (0 = all)")
    args = parser.parse_args()

    base, token, provider = read_provider(Path(args.config), None)
    print(f"provider={provider} endpoint={base}/chat/completions model={args.model}")

    zh_path = Path(args.zh)
    zh: dict[str, str] = {}
    if zh_path.is_file():
        zh = json.loads(zh_path.read_text(encoding="utf-8"))

    todo = [s for s in json.loads(Path(args.missing).read_text(encoding="utf-8")) if s not in zh]
    todo = [s for s in todo if needs_translation(s)]
    if args.limit:
        todo = todo[: args.limit]
    print(f"to translate: {len(todo)} strings (cache has {len(zh)})")

    batches = chunk(todo, args.batch_chars, args.batch_items)
    print(f"batches: {len(batches)}")

    done = 0
    lock_errors = 0

    def handle(batch: list[str]) -> tuple[list[str], list[str]]:
        last_error = ""
        for attempt in range(1, args.retries + 1):
            try:
                result = call_api(base, token, args.model, batch)
                if len(result) != len(batch):
                    raise ValueError(f"length mismatch: sent {len(batch)} got {len(result)}")
                return batch, result
            except (urllib.error.URLError, ValueError, KeyError, TimeoutError, OSError) as exc:
                last_error = str(exc)
                time.sleep(2 * attempt)
        print(f"  batch failed ({len(batch)} strings): {last_error}", file=sys.stderr)
        return batch, []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for batch, result in pool.map(handle, batches):
            if result:
                for src, dst in zip(batch, result):
                    if isinstance(dst, str) and dst.strip():
                        zh[src] = dst.strip()
                done += len(result)
                zh_path.write_text(json.dumps(zh, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
                print(f"  +{len(result)} (total translated {len(zh)})")

    print(f"done: {done} new translations, cache now {len(zh)}")


if __name__ == "__main__":
    main()
