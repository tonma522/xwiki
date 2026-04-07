"""raw/ レイヤー: X Drive のファイルを crawl して raw/ に MD 変換・取り込む"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .converter import build_front_matter, convert_file
from .state import Manifest, sha256

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".pptx", ".ppt", ".docx", ".doc"}


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
        # ディレクトリ要素もチェック
        for part in path.parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def ingest(source_root: Path, kb_root: Path, config: Config, force: bool = False) -> list[IngestResult]:
    """
    source_root 配下の対象ファイルを kb_root/raw/ に MD 変換して書き出す。
    _meta/manifest.json でハッシュ差分管理を行う。
    """
    raw_root = kb_root / "raw"
    manifest_path = kb_root / "_meta" / "manifest.json"
    manifest = Manifest.load(manifest_path)

    results: list[IngestResult] = []
    files = [
        p for p in source_root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and not _is_excluded(p, config.exclude_patterns)
    ]

    log.info(f"対象ファイル数: {len(files)}")

    for i, src in enumerate(files, 1):
        log.info(f"[{i}/{len(files)}] {src.name}")

        size = src.stat().st_size
        max_bytes = config.max_file_size_mb * 1024 * 1024
        if size > max_bytes:
            log.warning(f"  スキップ（サイズ超過）: {size / 1024 / 1024:.1f} MB")
            results.append(IngestResult(str(src), "", "skip", f"size_exceeded:{size}", size))
            continue

        # raw/ 内の出力パス
        try:
            rel = src.relative_to(source_root)
        except ValueError:
            rel = Path(src.name)
        raw_path = raw_root / rel.with_suffix(".md")
        raw_rel = raw_path.relative_to(kb_root).as_posix()  # "raw/..."

        # 差分チェック
        current_hash = sha256(src)
        if not force and not manifest.is_changed(raw_rel, current_hash):
            log.info("  スキップ（変更なし）")
            continue

        # 変換・書き出し
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            body = convert_file(src, config)
            front = build_front_matter(src, raw_rel)
            raw_path.write_text(front + body, encoding="utf-8")
            manifest.mark_ingested(raw_rel, str(src), current_hash)
            results.append(IngestResult(str(src), str(raw_path), "ok", "", size))
            log.info(f"  完了 -> {raw_rel}")
        except Exception as e:
            log.error(f"  エラー: {e}")
            results.append(IngestResult(str(src), "", "error", str(e), size))

    manifest.save(manifest_path)

    ok = sum(1 for r in results if r.status == "ok")
    skip = sum(1 for r in results if r.status == "skip")
    err = sum(1 for r in results if r.status == "error")
    log.info(f"完了: {ok} 変換 / {skip} スキップ / {err} エラー")

    return results
