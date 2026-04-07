"""wiki/ ヘルスチェック"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .compiler import _parse_concepts_val, _parse_front_matter, _safe_concept_filename

log = logging.getLogger(__name__)


@dataclass
class LintIssue:
    severity: str  # "error" | "warning" | "info"
    file: str      # 対象ファイル（kb_root 相対パス）
    message: str


def lint(kb_root: Path, client: Any = None) -> list[LintIssue]:
    """wiki/ の品質チェックレポートを生成する"""
    issues: list[LintIssue] = []

    summaries_root = kb_root / "wiki" / "summaries"
    concepts_root = kb_root / "wiki" / "concepts"

    # summaries の全ファイル
    summary_files = sorted(summaries_root.rglob("*.md")) if summaries_root.exists() else []
    # concepts の全ファイル
    concept_files = sorted(concepts_root.rglob("*.md")) if concepts_root.exists() else []

    # --- concepts/ の全 MD を1パスで読み込み: linked_stems 収集 + 壊れたリンク検出 ---
    linked_stems: set[str] = set()
    for cf in concept_files:
        rel = cf.relative_to(kb_root).as_posix()
        try:
            text = cf.read_text(encoding="utf-8")
        except Exception as e:
            log.warning(f"  読み込み失敗 {cf}: {e}")
            continue
        for link in re.findall(r'\[\[([^\]]+)\]\]', text):
            name = link.strip()
            linked_stems.add(name)
            # チェック2: 壊れたリンク（LLM 生成の [[wikilink]] 名をサニタイズしてからパス検証）
            safe_name = _safe_concept_filename(name)
            target = concepts_root / f"{safe_name}.md"
            if not target.exists():
                issues.append(LintIssue(
                    severity="error",
                    file=rel,
                    message=f"壊れたリンク: [[{name}]] in {rel}",
                ))

    # --- チェック1: 孤立 summary（concepts/ からリンクされていない summaries/ の MD）---
    for sf in summary_files:
        rel = sf.relative_to(kb_root).as_posix()
        if sf.stem not in linked_stems:
            issues.append(LintIssue(
                severity="warning",
                file=rel,
                message=f"孤立 summary: {rel}",
            ))

    # --- チェック3: concepts が空の summaries ---
    for sf in summary_files:
        rel = sf.relative_to(kb_root).as_posix()
        try:
            fm = _parse_front_matter(sf)
        except Exception as e:
            log.warning(f"  front matter 解析失敗 {sf}: {e}")
            continue
        concepts_val = fm.get("concepts", [])
        concept_names = _parse_concepts_val(concepts_val, sf)
        if not concept_names:
            issues.append(LintIssue(
                severity="warning",
                file=rel,
                message=f"concepts が空: {rel}",
            ))

    # --- LLM チェック（client が None でない場合のみ）---
    # TODO: LLM チェックは将来実装

    # --- レポート生成 ---
    _write_report(kb_root, issues)

    # --- stdout に要約出力 ---
    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    print(f"Lint 完了: エラー {error_count} 件, 警告 {warning_count} 件")
    for issue in issues:
        print(f"  [{issue.severity}] {issue.file}: {issue.message}")

    return issues


def _write_report(kb_root: Path, issues: list[LintIssue]) -> None:
    """wiki/_health/report.md にレポートを書き出す"""
    health_dir = kb_root / "wiki" / "_health"
    health_dir.mkdir(parents=True, exist_ok=True)
    report_path = health_dir / "report.md"

    now = datetime.now().isoformat()
    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    lines: list[str] = []
    lines.append("# Wiki Health Report")
    lines.append(f"_生成: {now}_")
    lines.append("")
    lines.append("## サマリー")
    lines.append(f"- エラー: {error_count} 件")
    lines.append(f"- 警告: {warning_count} 件")
    lines.append("")
    lines.append("## 詳細")
    lines.append("")
    lines.append("### Errors")
    lines.append("")
    if errors:
        for issue in errors:
            lines.append(f"- {issue.file}: {issue.message}")
    else:
        lines.append("_なし_")
    lines.append("")
    lines.append("### Warnings")
    lines.append("")
    if warnings:
        for issue in warnings:
            lines.append(f"- {issue.file}: {issue.message}")
    else:
        lines.append("_なし_")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"  report.md 書き出し: {report_path.relative_to(kb_root)}")
