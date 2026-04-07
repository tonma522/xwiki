"""wiki/ レイヤー: LLM による増分コンパイル（stub）"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import Config
from .state import Manifest

log = logging.getLogger(__name__)


def compile(kb_root: Path, config: Config, force: bool = False, dry_run: bool = False) -> None:
    """raw/ の MD を LLM で wiki/ に増分コンパイルする（未実装）"""
    # TODO: Phase 2 Task 2.2 / 2.3 で実装
    log.info("[stub] compile は未実装です（Phase 2 で実装予定）")
