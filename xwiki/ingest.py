"""raw/ レイヤー: X Drive のファイルを再帰走査して raw/ に MD 変換・取り込む"""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .converter import DEFAULT_ROUTES, ConvertResult, convert_file
from .state import Manifest, sha256

log = logging.getLogger(__name__)

# converter.py の DEFAULT_ROUTES キー + 一般的なフォールバック対象拡張子
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    f".{ext}" for ext in DEFAULT_ROUTES
) | frozenset({".pdf", ".docx", ".pptx", ".xlsx", ".doc", ".ppt", ".xls"})


@dataclass
class IngestResult:
    source_path: str
    raw_path: str
    status: str   # "ok" | "skip" | "error"
    reason: str = ""
    file_size_bytes: int = 0


def _is_excluded(path: Path, patterns: list[str]) -> bool:
    """ファイル名またはパス要素がいずれかのパターンに一致するか"""
    name = path.name
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        for part in path.parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def _write_file_longpath(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Windows ロングパス対応でファイルを書き込む"""
    abs_str = str(path.resolve())
    if os.name == "nt" and not abs_str.startswith("\\\\"):
        abs_str = "\\\\?\\" + abs_str
    Path(abs_str).write_text(content, encoding=encoding)


def ingest(source_dir: Path, kb_root: Path, config: Any, force: bool = False) -> None:
    """source_dir を再帰走査し、対応ファイルをkb/raw/に変換・保存する"""
    raw_root = kb_root / "raw"
    manifest_path = kb_root / "_meta" / "manifest.json"
    manifest = Manifest.load(manifest_path)

    exclude_patterns: list[str] = getattr(config, "exclude_patterns", []) or []
    max_file_size_mb: int = getattr(config, "max_file_size_mb", 100)
    convert_routes: dict[str, str] = getattr(config, "convert_routes", {}) or {}

    # サポート対象拡張子: DEFAULT_ROUTES + config.convert_routes のキー
    supported: frozenset[str] = SUPPORTED_EXTENSIONS | frozenset(
        f".{ext}" for ext in convert_routes
    )

    files = [
        p for p in source_dir.rglob("*")
        if p.is_file()
        and p.suffix.lower() in supported
        and not _is_excluded(p, exclude_patterns)
    ]

    log.info(f"対象ファイル数: {len(files)}")

    total = 0
    skipped = 0
    failed = 0

    try:
        for i, src in enumerate(files, 1):
            log.info(f"[{i}/{len(files)}] {src.name}")
            total += 1

            # ファイルサイズチェック
            size = src.stat().st_size
            max_bytes = max_file_size_mb * 1024 * 1024
            if size > max_bytes:
                log.warning(f"  スキップ（サイズ超過）: {size / 1024 / 1024:.1f} MB")
                skipped += 1
                continue

            # raw/ 内の出力パス
            try:
                rel = src.relative_to(source_dir)
            except ValueError:
                rel = Path(src.name)

            raw_path = raw_root / rel.with_suffix(".md")
            raw_rel = raw_path.relative_to(kb_root).as_posix()  # "raw/..."

            # 差分チェック
            current_hash = sha256(src)
            if not force and not manifest.is_changed(raw_rel, current_hash):
                log.info(f"  [スキップ] {src.name}")
                skipped += 1
                continue

            # 変換
            raw_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                result: ConvertResult = convert_file(src, config)

                # Obsidian互換 front matter 生成
                stat = src.stat()
                ext = src.suffix.lower().lstrip(".")
                modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
                created = datetime.now().isoformat()
                front_matter = (
                    f'---\n'
                    f'source: "{src.as_posix()}"\n'
                    f'tags: [raw, {ext}]\n'
                    f'created: "{created}"\n'
                    f'modified: "{modified}"\n'
                    f'aliases: ["{src.stem}"]\n'
                    f'converter_engine: "{result.engine}"\n'
                    f'---\n\n'
                )

                content = front_matter + result.text

                _write_file_longpath(raw_path, content, encoding="utf-8")

                manifest.mark_ingested(raw_rel, str(src), current_hash, converter_engine=result.engine)
                log.info(f"  完了 -> {raw_rel}")

            except Exception as e:
                log.error(f"  エラー: {e}")
                failed += 1
    finally:
        manifest.save(manifest_path)

    processed = total - skipped - failed
    log.info(f"[完了] {processed}件処理, {skipped}件スキップ, {failed}件失敗")
