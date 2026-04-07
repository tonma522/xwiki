"""markitdown ラッパー + Obsidian 互換 front matter 生成"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from markitdown import MarkItDown

_md = MarkItDown()


def convert_file(src: Path, config=None) -> str:  # type: ignore[type-arg]
    """
    ファイルを Markdown テキストに変換する。
    変換失敗・空文字の場合は fallback メッセージを返す。
    """
    try:
        result = _md.convert(str(src))
        text = result.text_content or ""
    except Exception as e:
        text = ""
        _fallback_reason = str(e)
    else:
        _fallback_reason = ""

    if not text.strip():
        text = f"_変換結果なし（元ファイル: {src.name}）_\n"
        if _fallback_reason:
            text += f"\n<!-- 変換エラー: {_fallback_reason} -->\n"

    # フォーマット別後処理
    suffix = src.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        text = _postprocess_excel(text)
    elif suffix in {".pptx", ".ppt"}:
        text = _postprocess_ppt(text)

    return text


def build_front_matter(src: Path, raw_rel: str) -> str:
    """Obsidian 互換 YAML front matter を生成する"""
    stat = src.stat()
    ext = src.suffix.lower().lstrip(".")
    modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
    created = datetime.now().isoformat()

    return f"""---
source: "{src.as_posix()}"
raw_path: "{raw_rel}"
tags: [raw, {ext}]
aliases: ["{src.stem}"]
created: {created}
modified: {modified}
---

# {src.stem}

"""


def _postprocess_excel(text: str) -> str:
    """Excel: シート区切りを ## Sheet: 形式に整形"""
    # markitdown が出力するシート区切りパターンに合わせて調整
    return text


def _postprocess_ppt(text: str) -> str:
    """PowerPoint: スライド番号を ## Slide N 形式に整形"""
    return text
