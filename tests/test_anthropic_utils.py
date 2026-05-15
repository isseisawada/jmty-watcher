"""anthropic_utils.extract_json と render の振る舞いを確認。"""

from __future__ import annotations

import pytest

from watcher.anthropic_utils import extract_json, render


def test_extract_json_plain() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_codeblock() -> None:
    text = '```json\n{"a": 1, "b": [1,2]}\n```'
    assert extract_json(text) == {"a": 1, "b": [1, 2]}


def test_extract_json_with_leading_text() -> None:
    text = 'もちろんです。以下が結果です:\n{"a": 1}\n\n以上です。'
    assert extract_json(text) == {"a": 1}


def test_extract_json_balanced_braces() -> None:
    text = 'prefix {"outer": {"inner": [1,2]}} suffix'
    assert extract_json(text) == {"outer": {"inner": [1, 2]}}


def test_extract_json_raises_on_garbage() -> None:
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_render_substitutes_none_as_japanese_default() -> None:
    out = render("name={name}, age={age}", name="alice", age=None)
    assert out == "name=alice, age=なし"


def test_render_missing_key_becomes_empty() -> None:
    out = render("hello {missing} world")
    assert out == "hello  world"
