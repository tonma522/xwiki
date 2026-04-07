"""コンバータレジストリ: 拡張子→エンジン のルーティングで Markdown に変換する"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# デフォルトのエンジンルーティング（拡張子→エンジン指定文字列）
DEFAULT_ROUTES: dict[str, str] = {
    "pdf": "docling",
    "docx": "markitdown",
    "pptx": "markitdown",
    "xlsx": "markitdown",
    "doc": "libreoffice->docx->markitdown",
    "ppt": "libreoffice->pptx->markitdown",
    "xls": "libreoffice->xlsx->markitdown",
}
FALLBACK_ENGINE = "tika"


@dataclass
class ConvertResult:
    text: str           # Markdown本文
    engine: str         # 使用エンジン名: "docling" | "markitdown" | "libreoffice->markitdown" | "tika" | "fallback"
    sidecar: dict = field(default_factory=dict)  # Docling JSON等の構造化データ（不要なら空dict）


def _convert_docling(src: Path) -> ConvertResult:
    """Docling を使ってファイルを Markdown に変換する"""
    try:
        from docling.document_converter import DocumentConverter  # type: ignore[import]
    except ImportError:
        warnings.warn(
            f"docling未インストール. markitdownにフォールバック: {src.name}",
            stacklevel=2,
        )
        return _convert_markitdown(src)

    converter = DocumentConverter()
    result = converter.convert(str(src))

    text = result.document.export_to_markdown()

    try:
        sidecar = result.document.export_to_dict()
    except Exception:
        sidecar = {}

    return ConvertResult(text=text, engine="docling", sidecar=sidecar)


def _convert_markitdown(src: Path) -> ConvertResult:
    """MarkItDown を使ってファイルを Markdown に変換する"""
    try:
        from markitdown import MarkItDown  # type: ignore[import]
    except ImportError:
        warnings.warn(
            f"markitdown未インストール. フォールバック: {src.name}",
            stacklevel=2,
        )
        return ConvertResult(
            text=f"_変換結果なし（元ファイル: {src.name}）_",
            engine="fallback",
            sidecar={},
        )

    md = MarkItDown()
    result = md.convert(str(src))
    text = result.text_content or ""

    if not text.strip():
        text = f"_変換結果なし（元ファイル: {src.name}）_"

    return ConvertResult(text=text, engine="markitdown", sidecar={})


def _normalize_with_libreoffice(src: Path, target_ext: str, tmpdir: Path) -> Path:
    """LibreOffice で src を target_ext 形式に変換し、変換後のファイルパスを返す"""
    import shutil
    import subprocess

    soffice = shutil.which("soffice")
    if soffice is None:
        raise RuntimeError(f"LibreOffice（soffice）がPATHに見つかりません: {src.name}")

    subprocess.run(
        [soffice, "--headless", "--convert-to", target_ext, "--outdir", str(tmpdir), str(src)],
        check=True,
        timeout=60,
        capture_output=True,
    )

    converted = tmpdir / f"{src.stem}.{target_ext}"
    if not converted.exists():
        raise RuntimeError(f"LibreOffice変換後のファイルが見つかりません: {converted}")

    return converted


def _convert_libreoffice_chain(src: Path, target_ext: str) -> ConvertResult:
    """LibreOffice で中間形式に変換してから MarkItDown に渡す"""
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            normalized = _normalize_with_libreoffice(src, target_ext, Path(tmpdir))
            result = _convert_markitdown(normalized)
            result.engine = f"libreoffice->{target_ext}->markitdown"
            return result
    except Exception as e:
        log.warning(f"LibreOffice変換失敗, tikaへフォールバック: {e}")
        return _convert_tika(src)


def _convert_tika(src: Path) -> ConvertResult:
    """Apache Tika を使ってファイルを Markdown に変換する"""
    try:
        from tika import parser as tika_parser  # type: ignore[import]

        parsed = tika_parser.from_file(str(src))
        text = (parsed.get("content") or "").strip()
        if not text:
            text = f"_変換結果なし（元ファイル: {src.name}）_"
        return ConvertResult(text=text, engine="tika", sidecar={})
    except ImportError:
        warnings.warn(
            f"tika未インストール: {src.name}",
            stacklevel=2,
        )
        return ConvertResult(
            text=f"_変換結果なし（元ファイル: {src.name}）_",
            engine="tika-failed",
            sidecar={},
        )
    except Exception as e:
        log.error(f"Tika変換エラー {src.name}: {e}")
        return ConvertResult(
            text=f"_変換結果なし（元ファイル: {src.name}）_",
            engine="tika-failed",
            sidecar={},
        )


def convert_file(src: Path, config: Any) -> ConvertResult:
    """ファイルを拡張子に応じたエンジンでMarkdownに変換する"""
    ext = src.suffix.lstrip(".").lower()
    routes: dict[str, str] = getattr(config, "convert_routes", {}) or {}
    # configのルートを優先してデフォルトとマージ
    merged: dict[str, str] = {**DEFAULT_ROUTES, **routes}
    engine_spec = merged.get(ext, FALLBACK_ENGINE)

    try:
        if engine_spec == "docling":
            return _convert_docling(src)
        elif engine_spec == "markitdown":
            return _convert_markitdown(src)
        elif engine_spec.startswith("libreoffice->"):
            # "libreoffice->docx->markitdown" → target_ext = "docx"
            parts = engine_spec.split("->")
            target_ext = parts[1]
            return _convert_libreoffice_chain(src, target_ext)
        elif engine_spec == "tika":
            return _convert_tika(src)
        else:
            log.warning(f"未知のエンジン指定: {engine_spec}. tika fallbackを試みます")
            return _convert_tika(src)
    except Exception as e:
        log.error(f"全エンジン失敗 {src.name}: {e}")
        return ConvertResult(
            text=f"_変換結果なし（元ファイル: {src.name}）_",
            engine="failed",
            sidecar={},
        )


def build_front_matter(src: Path, raw_rel: str, engine: str = "") -> str:
    """Obsidian 互換 YAML front matter を生成する"""
    from datetime import datetime

    stat = src.stat()
    ext = src.suffix.lower().lstrip(".")
    modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
    created = datetime.now().isoformat()

    engine_line = f'\nconverter_engine: "{engine}"' if engine else ""

    return (
        f'---\n'
        f'source: "{src.as_posix()}"\n'
        f'raw_path: "{raw_rel}"\n'
        f'tags: [raw, {ext}]\n'
        f'aliases: ["{src.stem}"]\n'
        f'created: {created}\n'
        f'modified: {modified}'
        f'{engine_line}\n'
        f'---\n\n'
        f'# {src.stem}\n\n'
    )
