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
    # compile時のメタデータ
    prompt_hash: str = ""                # compile時のプロンプトSHA-256（ingest時は空文字）
    model_id: str = ""                   # compile時のモデルID（ingest時は空文字）
    compiler_schema_version: str = ""    # compile時のスキーマバージョン（ingest時は空文字）
    converter_engine: str = ""           # 使用したコンバータエンジン名（例: "docling", "markitdown"）


@dataclass
class Manifest:
    """_meta/manifest.json の読み書きを担当する"""
    schema_version: str = "1"
    sources: dict[str, SourceEntry] = field(default_factory=dict)
    # key = raw/ 配下の相対パス（例: "raw/営業部/提案書.md"）

    def is_changed(self, raw_rel: str, current_hash: str) -> bool:
        """ソースが変更されているか（未登録含む）"""
        entry = self.sources.get(raw_rel)
        if entry is None:
            return True
        return entry.content_hash != f"sha256:{current_hash}"

    def is_changed_for_compile(
        self,
        raw_rel: str,
        current_hash: str,
        prompt_hash: str,
        model_id: str,
        schema_version: str,
    ) -> bool:
        """コンパイル要否判定: content_hash / prompt_hash / model_id / schema_version のいずれかが変化"""
        entry = self.sources.get(raw_rel)
        if entry is None:
            return True
        return (
            entry.status != "compiled"
            or entry.content_hash != f"sha256:{current_hash}"
            or entry.prompt_hash != prompt_hash
            or entry.model_id != model_id
            or entry.compiler_schema_version != schema_version
        )

    def mark_ingested(
        self,
        raw_rel: str,
        source_path: str,
        content_hash: str,
        converter_engine: str = "",
    ) -> None:
        self.sources[raw_rel] = SourceEntry(
            source_path=source_path,
            content_hash=f"sha256:{content_hash}",
            status="raw",
            ingested_at=datetime.now().isoformat(),
            converter_engine=converter_engine,
        )

    def mark_compiled(
        self,
        raw_rel: str,
        prompt_hash: str = "",
        model_id: str = "",
        schema_version: str = "",
    ) -> None:
        if raw_rel in self.sources:
            self.sources[raw_rel].status = "compiled"
            self.sources[raw_rel].compiled_at = datetime.now().isoformat()
            self.sources[raw_rel].prompt_hash = prompt_hash
            self.sources[raw_rel].model_id = model_id
            self.sources[raw_rel].compiler_schema_version = schema_version

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": self.schema_version,
            "sources": {
                k: {
                    "source_path": v.source_path,
                    "content_hash": v.content_hash,
                    "status": v.status,
                    "ingested_at": v.ingested_at,
                    "compiled_at": v.compiled_at,
                    "prompt_hash": v.prompt_hash,
                    "model_id": v.model_id,
                    "compiler_schema_version": v.compiler_schema_version,
                    "converter_engine": v.converter_engine,
                }
                for k, v in self.sources.items()
            },
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        schema_version = raw.get("schema_version", "1")
        sources: dict[str, SourceEntry] = {}
        for k, v in raw.get("sources", {}).items():
            # 旧フォーマット互換: 新フィールドが存在しない場合は空文字で補完
            entry = SourceEntry(
                source_path=v.get("source_path", ""),
                content_hash=v.get("content_hash", ""),
                status=v.get("status", "raw"),
                ingested_at=v.get("ingested_at", ""),
                compiled_at=v.get("compiled_at", ""),
                prompt_hash=v.get("prompt_hash", ""),
                model_id=v.get("model_id", ""),
                compiler_schema_version=v.get("compiler_schema_version", ""),
                converter_engine=v.get("converter_engine", ""),
            )
            sources[k] = entry
        return cls(schema_version=schema_version, sources=sources)
