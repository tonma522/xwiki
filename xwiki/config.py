"""設定ファイル読み込みと Config dataclass"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class Config:
    # --- ingest ---
    source_path: Path = field(default_factory=lambda: Path("."))
    kb_root: Path = field(default_factory=lambda: Path("kb"))
    exclude_patterns: list[str] = field(default_factory=lambda: [
        "*.tmp", "~$*", ".DS_Store", "Thumbs.db"
    ])
    max_file_size_mb: int = 100
    ocr_enabled: bool = False

    # --- converter ---
    convert_routes: dict[str, str] = field(default_factory=lambda: {
        "pdf": "docling",
        "docx": "markitdown",
        "pptx": "markitdown",
        "xlsx": "markitdown",
        "doc": "libreoffice->docx->markitdown",
        "ppt": "libreoffice->pptx->markitdown",
        "xls": "libreoffice->xlsx->markitdown",
    })
    libreoffice_path: str = ""  # 空文字 = PATHから検索

    # --- compile ---
    chunk_size_tokens: int = 0   # 0 = 無効（小さいファイルは分割不要）
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 8000
    generate_summaries: bool = True
    generate_concepts: bool = True


def load_config(path: Path | None = None) -> Config:
    """TOMLファイルを読み込みConfigを返す。pathがNoneまたは存在しない場合はデフォルト値を返す。

    TOML構造のマッピング:
      [ingest]       -> source_path, kb_root, exclude_patterns, max_file_size_mb, ocr_enabled
      [convert]      -> libreoffice_path
      [convert.routes] -> convert_routes
      [compile]      -> chunk_size_tokens, llm_provider, llm_model, llm_max_tokens,
                        generate_summaries, generate_concepts

    Args:
        path: TOMLファイルのパス。Noneまたは存在しないパスの場合はデフォルト値を返す。

    Returns:
        Config dataclass インスタンス。

    Raises:
        ValueError: TOMLのパースに失敗した場合。
    """
    if path is None or not path.exists():
        return Config()

    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"設定ファイルのパースに失敗しました: {path}\n{exc}") from exc

    ingest: dict[str, Any] = raw.get("ingest", {})
    convert: dict[str, Any] = raw.get("convert", {})
    compile_: dict[str, Any] = raw.get("compile", {})

    defaults = Config()

    return Config(
        # ingest セクション
        source_path=Path(ingest.get("source_path", str(defaults.source_path))),
        kb_root=Path(ingest.get("kb_root", str(defaults.kb_root))),
        exclude_patterns=ingest.get("exclude_patterns", defaults.exclude_patterns),
        max_file_size_mb=int(ingest.get("max_file_size_mb", defaults.max_file_size_mb)),
        ocr_enabled=bool(ingest.get("ocr_enabled", defaults.ocr_enabled)),

        # convert セクション（TOMLのroutes指定はデフォルトとマージ: config優先）
        convert_routes={**defaults.convert_routes, **convert.get("routes", {})},
        libreoffice_path=str(convert.get("libreoffice_path", defaults.libreoffice_path)),

        # compile セクション
        chunk_size_tokens=int(compile_.get("chunk_size_tokens", defaults.chunk_size_tokens)),
        llm_provider=str(compile_.get("llm_provider", defaults.llm_provider)),
        llm_model=str(compile_.get("llm_model", defaults.llm_model)),
        llm_max_tokens=int(compile_.get("llm_max_tokens", defaults.llm_max_tokens)),
        generate_summaries=bool(compile_.get("generate_summaries", defaults.generate_summaries)),
        generate_concepts=bool(compile_.get("generate_concepts", defaults.generate_concepts)),
    )
