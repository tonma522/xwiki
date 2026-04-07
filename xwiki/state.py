"""KB マニフェスト管理（kb-* スキル互換の manifest.json 形式）"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def sha256(path: Path) -> str:
    """ファイルの SHA-256 ハッシュを返す（64KB チャンク）"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class SourceEntry:
    source_path: str          # 元ファイルの絶対パス
    content_hash: str         # sha256:<hex>
    status: str               # "raw" | "compiled"
    ingested_at: str = ""
    compiled_at: str = ""


@dataclass
class Manifest:
    """_meta/manifest.json の読み書きを担当する"""
    sources: dict[str, SourceEntry] = field(default_factory=dict)
    # key = raw/ 配下の相対パス（例: "raw/営業部/提案書.md"）

    def is_changed(self, raw_rel: str, current_hash: str) -> bool:
        """ソースが変更されているか（未登録含む）"""
        entry = self.sources.get(raw_rel)
        if entry is None:
            return True
        return entry.content_hash != f"sha256:{current_hash}"

    def mark_ingested(self, raw_rel: str, source_path: str, content_hash: str) -> None:
        self.sources[raw_rel] = SourceEntry(
            source_path=source_path,
            content_hash=f"sha256:{content_hash}",
            status="raw",
            ingested_at=datetime.now().isoformat(),
        )

    def mark_compiled(self, raw_rel: str) -> None:
        if raw_rel in self.sources:
            self.sources[raw_rel].status = "compiled"
            self.sources[raw_rel].compiled_at = datetime.now().isoformat()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "sources": {
                k: {
                    "source_path": v.source_path,
                    "content_hash": v.content_hash,
                    "status": v.status,
                    "ingested_at": v.ingested_at,
                    "compiled_at": v.compiled_at,
                }
                for k, v in self.sources.items()
            }
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        sources = {
            k: SourceEntry(**v)
            for k, v in raw.get("sources", {}).items()
        }
        return cls(sources=sources)
