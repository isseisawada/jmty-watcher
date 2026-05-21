"""closed listing の NEXT_DATA フィールドを調べる診断スクリプト。

PoC 限りの使い捨て。本番では使わない。
"""

from __future__ import annotations

import json
import re

import httpx

URL = "https://jmty.jp/hokkaido/sale-oth/article-1jpqgf"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', re.DOTALL
)

html = httpx.get(URL, headers={"User-Agent": UA}, follow_redirects=True, timeout=20).text
print(f"HTML bytes: {len(html)}")
print(f"text marker 'お問い合わせの受付は終了' in HTML: {'お問い合わせの受付は終了' in html}")
print(f"text marker '受付は終了' in HTML: {'受付は終了' in html}")
print(f"text marker '終了' in HTML: {'終了' in html}")

m = NEXT_DATA_RE.search(html)
if not m:
    print("__NEXT_DATA__ not found")
    raise SystemExit(1)

data = json.loads(m.group(1))
article = data["props"]["pageProps"]["articleResults"]["article"]

print()
print(f"article keys ({len(article)}):")
for k in sorted(article.keys()):
    v = article[k]
    repr_v = repr(v)
    if len(repr_v) > 80:
        repr_v = repr_v[:80] + "..."
    print(f"  {k}: {repr_v}")

print()
print("--- pageProps top-level keys ---")
for k in sorted(data["props"]["pageProps"].keys()):
    print(f"  {k}")

print()
print("--- articleResults keys ---")
for k in sorted(data["props"]["pageProps"]["articleResults"].keys()):
    print(f"  {k}")
