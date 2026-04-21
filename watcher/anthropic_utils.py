"""Anthropic APIとのやり取りで使う共通ユーティリティ。

- プロンプトテンプレートの読み込み
- 画像URLをbase64に落として content block に添付
- モデル応答からJSON本体のみ抽出
"""

from __future__ import annotations

import base64
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Anthropic APIが受け付ける画像MIMEに限定する
_ALLOWED_MEDIA = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def render(template: str, **kwargs: Any) -> str:
    """`.format_map` で欠損キーは空文字に。Noneは 'なし' と表示する。"""
    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return ""

    safe = {k: ("なし" if v is None else v) for k, v in kwargs.items()}
    return template.format_map(_Safe(safe))


def fetch_image_blocks(image_urls: list[str], max_images: int = 3) -> list[dict[str, Any]]:
    """画像URLをDLしてAnthropicの image content block に変換する。失敗した分はスキップ。"""
    blocks: list[dict[str, Any]] = []
    for url in image_urls[:max_images]:
        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
            media_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            if media_type not in _ALLOWED_MEDIA:
                logger.debug("skip image %s (media_type=%s)", url, media_type)
                continue
            b64 = base64.standard_b64encode(resp.content).decode("ascii")
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                }
            )
        except httpx.HTTPError as e:
            logger.warning("image fetch failed url=%s err=%s", url, e)
    return blocks


_CODEBLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """モデル出力から最初のJSONオブジェクトを抽出。厳密JSONが理想だがフォールバックを用意。"""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    match = _CODEBLOCK_RE.search(stripped)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 最後の砦: 最初の { から対応する } までを切り出す
    start = stripped.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(stripped[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = stripped[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"Failed to extract JSON from model output: {text[:300]}")
