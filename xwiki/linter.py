"""wiki/ ヘルスチェック（stub）"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)


def lint(kb_root: Path, config: Config) -> None:
    """wiki/ の品質チェックレポートを生成する（未実装）"""
    # TODO: Phase 3 Task 3.2 で実装
    log.info("[stub] lint は未実装です（Phase 3 で実装予定）")
