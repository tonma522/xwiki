# Plan: xwiki パッケージ実装（Karpathyモデル LLM Knowledge Base）
**生成日**: 2026-04-07 / **レーン: Heavy** / **推定複雑度**: 高

## 概要

`crawler.py` プロトタイプを廃止し、`xwiki/` パッケージとして再構築する。
Karpathyの二層アーキテクチャ（`raw/` 機械変換層 + `wiki/` LLM編纂層）を実装し、
Obsidian互換のLLM Knowledge Baseを構築するCLIツール群を提供する。

```
X Drive ─[ingest]→ raw/ ─[compile]→ wiki/ ─[search/lint]→ ユーザー・LLMエージェント
```

## スコープ

In:
- `xwiki/` パッケージ全体の新規実装（7モジュール）
- `raw/` レイヤー: markitdown変換 + Obsidian互換YAML front matter
- `wiki/` レイヤー: LLM増分コンパイル（要約 → 概念記事 → INDEX）
- CLIサブコマンド: `ingest` / `compile` / `search` / `lint`
- `config.toml` 設定システム（OCR/チャンク/LLMモデルを外部化）
- 差分処理: md5ベースの増分実行（ingest/compile両層で独立）

Out:
- `crawler.py` の保持（実装完了後に廃止予定だが今回のスコープ外）
- OCR実装（`config.ocr_enabled` の設計のみ、実装は別タスク）
- Q&Aエージェント（Karpathyの「さらなる探索」）
- RAGパイプライン
- GUIフロントエンド

## 前提条件

- Python 3.14、markitdown 0.1.5 インストール済み
- `anthropic` パッケージが pip でインストール可能
- `ANTHROPIC_API_KEY` 環境変数が設定されている（compile/lint コマンド用）
- Xドライブへの読み取りアクセス確保済み

## 仮定

- LLMクライアントはAnthropic Claude APIのみ実装（OpenAI対応は `llm.py` のプロバイダー抽象で後から追加可能な設計にする）
- `wiki/` の規模が〜数百件ならRAG不要（Karpathyの知見。INDEXとサマリー読み込みで対応）
- Python 3.14 で `anthropic` パッケージが動作する（未確認 → 動作確認を C2 前に実施）
- Obsidian互換 = YAML front matter + `[[wikilink]]` 形式（Obsidianのデフォルト設定）
- チャンク分割はデフォルト無効（`chunk_size_tokens = 0`）。大規模ファイルが問題になった場合に有効化
- **kb-* スキル互換**: `_meta/manifest.json`（SHA-256）形式を採用し、`/kb-compile` / `/kb-lint` / `/kb-query` スキルとの相互運用を可能にする

## 調査サマリー

- **Fact**: `crawler.py:19` — `SUPPORTED_EXTENSIONS` 定義。xwiki/config.py に移行
- **Fact**: `crawler.py:43-56` — `CrawlState` (md5管理)。`xwiki/state.py` に移行・SHA-256 + manifest.json 形式に変更
- **Fact**: `crawler.py:76-91` — `build_meta_header()` → Obsidian front matter に改修
- **Fact**: `crawler.py:95-164` — `crawl()` メイン処理 → `xwiki/ingest.py` に移行
- **Fact**: `crawler.py:167-206` — `generate_index()`, `write_report()` → `xwiki/compiler.py` INDEX管理部分に統合
- **Evidence**: PDFテスト成功済み（`IHI/20260407.pdf` → `wiki_output/sources/20260407.md`）
- **Why it matters**: 単一ファイル構成では LLM 編纂層の追加が困難。パッケージ化が前提
- **Uncertainty**: anthropic パッケージの Python 3.14 互換性（C3 前に `pip install anthropic` で確認必須）

---

## Phase 1: raw/ レイヤー（xwiki パッケージ基盤）

**目的**: `crawler.py` の全機能を `xwiki/` パッケージに移行し、Obsidian互換raw/レイヤーを確立する  
**検証**: `python -m xwiki ingest IHI kb/` が動作し、`kb/raw/` に Obsidian互換MDが生成される

### Task 1.1: パッケージスケルトン生成

- **推奨モデル**: `codex:low` — boilerplate/stub生成
- **対象**: `C:/dev/schedule/xwiki/` ディレクトリ（新規）
- **内容**: 7モジュールのスタブを作成する
  ```
  xwiki/
  ├── __init__.py          # バージョン定数のみ
  ├── __main__.py          # argparse: ingest/compile/search/lint サブコマンド（stubのみ）
  ├── config.py            # Config dataclass（フィールド定義のみ、TOML読み込み未実装）
  ├── state.py             # IngestState / CompileState dataclass（stub）
  ├── ingest.py            # ingest() 関数stub
  ├── converter.py         # convert_file() 関数stub
  ├── llm.py               # LLMClient class stub
  ├── compiler.py          # compile() 関数stub
  ├── search.py            # search() 関数stub
  └── linter.py            # lint() 関数stub
  ```
- **依存**: なし
- **受け入れ条件**: `python -m xwiki --help` がエラーなく実行できる
- **検証**: `python -m xwiki --help` でサブコマンド一覧が表示される

### Task 1.2: ingest.py + converter.py の実装（raw/レイヤー）

- **推奨モデル**: `codex:high` — crawler.pyを参照しながら多ファイルリファクタ
- **対象**: `xwiki/ingest.py`、`xwiki/converter.py`、`xwiki/state.py`
- **内容**:
  - `crawler.py` の `crawl()` → `ingest.py:ingest()` に移行
  - `crawler.py` の `CrawlState` → `state.py:Manifest` に改修（SHA-256 + manifest.json 形式）
    ```json
    {
      "sources": {
        "raw/営業部/提案書_A社.md": {
          "source_path": "X:/営業部/提案書_A社.xlsx",
          "content_hash": "sha256:abc...",
          "status": "raw",
          "ingested_at": "2026-04-07T14:38:00"
        }
      }
    }
    ```
    - `status` ライフサイクル: `raw` → `compiled`（kb-* スキルと互換）
  - `converter.py:convert_file(src: Path, config: Config) -> str` を実装
    - markitdown `convert(str)` 呼び出し
    - Excel後処理: `## Sheet: シート名` 区切り
    - PPT後処理: `## Slide N` 区切り
    - 空文字fallback: `_変換結果なし（元ファイル: {src.name}）_`
  - `build_meta_header()` → Obsidian互換YAML front matterに改修:
    ```yaml
    ---
    source: "X:/営業部/提案書_A社.xlsx"
    tags: [raw, excel]
    created: 2026-04-07T14:38:00
    modified: 2024-03-15T09:00:00
    aliases: ["提案書_A社"]
    ---
    ```
- **依存**: Task 1.1
- **受け入れ条件**: `kb/raw/` にObsidian互換MDが生成される。front matterがYAML validであること
- **検証**:
  - `python -m xwiki ingest IHI kb/` でPDFが変換される
  - 生成MDの front matter を `python -c "import yaml; yaml.safe_load(open('kb/raw/20260407.md').read().split('---')[1])"` でparse成功
  - `kb/_meta/manifest.json` が生成され、`status: "raw"` エントリが存在すること

### Task 1.3: config.py + __main__.py の実装（設定・CLI）

- **推奨モデル**: `codex:medium` — TOML読み込みとargparse
- **対象**: `xwiki/config.py`、`xwiki/__main__.py`、`config.toml`（サンプル新規）
- **内容**:
  - `Config` dataclass:
    ```python
    @dataclass
    class Config:
        source_path: Path
        kb_root: Path
        exclude_patterns: list[str]
        max_file_size_mb: int
        ocr_enabled: bool
        chunk_size_tokens: int
        llm_provider: str
        llm_model: str
        llm_max_tokens: int
        generate_concepts: bool
        generate_summaries: bool
    ```
  - `load_config(path: Path | None) -> Config` — TOMLファイルまたはデフォルト値
  - `__main__.py` CLIサブコマンド実装:
    ```bash
    python -m xwiki ingest [source] [--config config.toml] [--force]
    python -m xwiki compile [--config config.toml] [--force]
    python -m xwiki search <query> [--json]
    python -m xwiki lint
    ```
  - `config.toml` サンプルファイル（全設定項目をコメント付きで）
- **依存**: Task 1.1
- **受け入れ条件**: `--config config.toml` と設定ファイルなし（デフォルト値）の両方で動作する
- **検証**: `python -m xwiki ingest IHI kb/ --config config.toml` が動作する

> **C1-a / C1-b 並列実行可能**: Task 1.2 と Task 1.3 は独立しており並列実行可能

---

### ★ R1: raw/ レイヤー Code Review Gate

**タイミング**: Task 1.2 + Task 1.3 の両方が完了しマージされた後  
**対象ファイル**: `xwiki/ingest.py`、`xwiki/converter.py`、`xwiki/state.py`、`xwiki/config.py`、`xwiki/__main__.py`  
**重点観点**:
- Obsidian front matter が正しいYAML形式であること
- `IngestState` の差分管理ロジックに競合・データロスがないこと
- `convert_file()` の例外処理が全フォーマットで一貫していること
- CLIのサブコマンド設計が Phase 2 (compile/search/lint) を追加しやすい構造であること

---

## Phase 2: wiki/ レイヤー（LLM編纂）

**目的**: LLMがraw/を読んでwiki/を増分コンパイルするシステムを実装する  
**検証**: `python -m xwiki compile` で `kb/wiki/summaries/` と `kb/wiki/concepts/` と `kb/wiki/INDEX.md` が生成される

### Task 2.1: llm.py の実装（LLMクライアント）

- **推奨モデル**: `opus` — cross-service設計、新アーキテクチャ導入
- **対象**: `xwiki/llm.py`
- **内容**:
  - `LLMClient` クラスを実装（Anthropic Claude APIラッパー）
    ```python
    @dataclass
    class LLMClient:
        model: str
        max_tokens: int

        def complete(self, prompt: str, system: str = "") -> str: ...
        def complete_json(self, prompt: str, system: str = "") -> dict: ...
    ```
  - `anthropic` パッケージを使用（`pip install anthropic`）
  - `ANTHROPIC_API_KEY` 環境変数の存在確認（未設定時は明示的エラー）
  - レート制限リトライ（指数バックオフ、最大3回）
  - プロバイダー抽象: `provider: str = "anthropic"` フィールドで将来の差し替えに備える
- **依存**: Task 1.3（Config）
- **受け入れ条件**:
  - `LLMClient(model="claude-sonnet-4-6", max_tokens=8000).complete("hello")` が文字列を返す
  - APIキー未設定時に `EnvironmentError: ANTHROPIC_API_KEY が設定されていません` が発生する
- **検証**:
  - `python -c "from xwiki.llm import LLMClient; print(LLMClient(...).complete('テスト'))"` が動作する
  - **事前確認必須**: `pip install anthropic` が Python 3.14 で成功すること

### Task 2.2: compiler.py — サマリー生成

- **推奨モデル**: `opus` — LLM統合の核心、wiki/raw/間のレイヤー境界設計
- **対象**: `xwiki/compiler.py`、`xwiki/state.py`（`CompileState` 追加）
- **内容**:
  - CompileStateは独立ファイルを持たず、`_meta/manifest.json` の `status` フィールドで管理（`raw` → `compiled`）
  - `compile_summary(raw_md_path: Path, client: LLMClient) -> str` を実装
    - プロンプト（固定）:
      ```
      以下のドキュメントを読み、Obsidian互換のMarkdownサマリーを生成してください。

      出力形式:
      ---
      source_raw: "{raw_relative_path}"
      summary_of: "{filename}"
      concepts: [概念1, 概念2, ...]  # このドキュメントに登場する重要な固有名詞・概念（最大10個）
      generated: "{iso_datetime}"
      ---

      ## 概要
      （3文以内）

      ## キーポイント
      （箇条書き、最大5項目）

      ## 登場する概念
      （concepts: リストと対応する説明）
      ```
    - 入力トークン超過時: raw/MDを先頭2000トークンに切り詰めて処理
  - `compile(kb_root: Path, config: Config, force: bool)` メイン関数:
    1. `raw/` 配下の全MDをリストアップ
    2. CompileStateで未処理・変更済みのみフィルタ
    3. 逐次処理（1ファイル = 1 LLM call）
    4. `wiki/summaries/` に出力（raw/のディレクトリ構造を保持）
    5. CompileState更新
- **依存**: Task 2.1（LLMClient）、Task 1.2（IngestState）
- **受け入れ条件**:
  - `kb/wiki/summaries/` に `concepts:` フィールドを持つMDが生成される
  - 2回目の `compile` 実行で変更がないファイルはスキップされる
- **検証**:
  - `python -m xwiki compile` 後、`kb/wiki/summaries/20260407.md` の front matterに `concepts:` が存在する
  - `--force` なしで再実行して「スキップ」ログが出ること

### Task 2.3: compiler.py — 概念記事生成 + INDEX管理

- **推奨モデル**: `sonnet` — Task 2.2 パターンを踏襲した拡張実装
- **対象**: `xwiki/compiler.py`（拡張）
- **内容**:
  - `gather_concepts(kb_root: Path) -> dict[str, list[Path]]`:
    - 全 `wiki/summaries/` MDのfront matter `concepts:` を収集
    - 概念名 → 登場するsummaryファイルリストのマッピングを返す
  - `compile_concept_article(concept: str, summaries: list[Path], client: LLMClient) -> str`:
    - プロンプト（固定）で概念記事を生成。`[[wikilink]]` 形式で関連ドキュメントにリンク
    - 出力: `wiki/concepts/{概念名}.md`
  - `update_index(kb_root: Path)`:
    - LLMを使わず機械的に生成（高速・低コスト）
    - `wiki/INDEX.md` に概念一覧・summaries一覧・孤立ファイル一覧を記載
  - `compile()` メイン関数にステップ追加:
    1. サマリー生成（Task 2.2）
    2. 概念収集
    3. 概念記事生成（新規概念のみ）
    4. INDEX更新
- **依存**: Task 2.2
- **受け入れ条件**:
  - `kb/wiki/concepts/` に `[[wikilink]]` を含む記事が生成される
  - `kb/wiki/INDEX.md` に概念一覧とsummaries一覧が記載される
- **検証**:
  - 2つ以上のサンプルドキュメントをコンパイルし、共通概念の記事が生成されること
  - `[[wikilink]]` が存在する概念記事ファイルが対応するsummaryに対応すること

---

### ★ R2: wiki/ レイヤー Code Review Gate

**タイミング**: Task 2.3 完了後  
**対象ファイル**: `xwiki/llm.py`、`xwiki/compiler.py`（全体）  
**重点観点**:
- LLMプロンプトが空文字・トークン超過・APIエラー時に安全に降格（fallback）するか
- `CompileState` の増分管理がingest/compile両層で競合しないか
- `[[wikilink]]` の対象ファイルが実際に存在することを保証しているか
- コスト制御: 1ファイル=1 LLM callの保証と、不必要な再コンパイルの防止

---

## Phase 3: ツール群

**目的**: LLMエージェントがwikiを操作するためのCLIツールを整備する  
**検証**: `python -m xwiki search "クエリ"` と `python -m xwiki lint` が動作する

### Task 3.1: search.py の実装

- **推奨モデル**: `codex:medium` — 直接的なファイル検索ロジック
- **対象**: `xwiki/search.py`
- **内容**:
  - `search(kb_root: Path, query: str, json_output: bool) -> list[SearchResult]`
  - 検索範囲: `wiki/` 配下の全MD（summaries/ + concepts/）
  - マッチング: `query` を空白で分割しAND検索（大文字小文字無視）
  - スコアリング: タイトルマッチ > concepts: マッチ > 本文マッチ
  - 出力（通常モード）:
    ```
    kb/wiki/concepts/製品A.md [score: 3]
      > 製品Aは...
    ```
  - 出力（`--json` モード）: LLMエージェントがツールとして呼び出せるJSON
    ```json
    [{"path": "...", "score": 3, "excerpt": "..."}]
    ```
- **依存**: Phase 2完了
- **受け入れ条件**: 既知のキーワードで検索し、関連ファイルが上位に来る。`--json` でJSON出力
- **検証**: `python -m xwiki search "テスト" --json` がJSONを出力する

### Task 3.2: linter.py の実装（ヘルスチェック）

- **推奨モデル**: `codex:medium` — パターン分析ロジック
- **対象**: `xwiki/linter.py`
- **内容**:
  - `lint(kb_root: Path, client: LLMClient | None)` — LLMなしで動作する機械的チェック + オプションのLLMチェック
  - 機械的チェック（常時実行）:
    - 孤立ファイル: `[[wikilink]]` でリンクされていないsummaries
    - 壊れたリンク: `[[概念名]]` に対応する `wiki/concepts/概念名.md` が存在しない
    - 空のconcepts: front matterの `concepts: []` が空
  - LLMチェック（`ANTHROPIC_API_KEY` がある場合のみ）:
    - 矛盾検出: 同一概念について異なる説明をしているsummary
    - 欠損概念候補: summaries内に頻出するが記事がない語句
  - 出力: `kb/wiki/_health/report.md`（Obsidianで閲覧可能）
- **依存**: Phase 2完了
- **受け入れ条件**: `kb/wiki/_health/report.md` が生成され、孤立ファイル数が記載される
- **検証**: 意図的に孤立ファイルを作成し、レポートに検出されること

---

## テスト戦略

- **テスト姿勢**: verification-first
- **例外理由**: LLM出力は非決定的。内容の正しさより「構造と形式の正しさ」を検証。ファイル変換処理はtest-firstが不自然
- **検証対象と手順**:
  1. **raw/レイヤー**: `python -m xwiki ingest IHI kb/` → front matter YAML parse成功
  2. **差分処理**: 2回目 `ingest` でスキップログが出ること（冪等性）
  3. **config**: `--config config.toml` と設定なしの両方で動作
  4. **LLMクライアント**: `ANTHROPIC_API_KEY` 設定・未設定の両方で正しい動作
  5. **summaries**: `compile` 後に `concepts:` フィールドが存在すること
  6. **concepts**: `[[wikilink]]` の対象ファイルが実在すること
  7. **search**: 既知クエリで期待ファイルが上位にくること
  8. **lint**: 孤立ファイルが正確に検出されること
- **実行コマンド**:
  ```bash
  python -m xwiki ingest IHI kb/
  python -m xwiki compile
  python -m xwiki search "テスト" --json
  python -m xwiki lint
  ```

## リスクと対策

| リスク | 影響度 | 対策 |
|--------|--------|------|
| anthropic パッケージが Python 3.14 非対応 | 致命的 | C3（Task 2.1）前に `pip install anthropic` で確認。非対応なら `httpx` で直接APIコール |
| LLMが `concepts:` フィールドを省略・フォーマット違反 | 高 | `compile_summary()` 内でfront matter検証。失敗時は `concepts: []` でfallback |
| LLMコール数増大によるコスト爆発 | 高 | 増分処理で変更ファイルのみ再処理。`--dry-run` フラグでコール数を事前確認できるよう設計 |
| `[[wikilink]]` の概念名に表記ゆれ | 中 | `linter.py` の壊れたリンク検出で早期発見。概念記事生成プロンプトで正規化を指示 |
| Xドライブのファイル数が数万件 | 中 | 逐次処理だが差分管理で2回目以降は高速。進捗表示（`[N/M]` ログ）で状況把握 |
| Windowsロングパス制限（260文字） | 低 | `ingest.py` で `\\?\` プレフィックスを使用 |

## ロールバック計画

- `raw/` と `wiki/` はいつでも削除・再生成可能（冪等設計）
- `_meta/ingest_state.json` / `_meta/compile_state.json` を削除すれば全ファイルを再処理
- `crawler.py` は削除せず残すため、rollback時は旧スクリプトで復旧可能
- LLM APIコストのロールバックは不可能 → `--dry-run` で事前確認を徹底

---

## Appendix: コミット計画

```
C0 ──→ C1-a ─┐
              ├─→ merge ──★R1──→ C2 ──→ C3 ──★R2──→ C4
         C1-b ─┘
```

### コミット一覧

| # | コミット対象 | メッセージ | 検証ゲート |
|---|------------|----------|----------|
| C0 | `xwiki/` スケルトン7モジュール（stub） | `feat: xwiki パッケージスケルトン` | `python -m xwiki --help` 動作 |
| C1-a | `ingest.py` + `converter.py` + `state.py` | `feat: raw/ レイヤー実装（ingest + converter）` | YAML parse成功 |
| C1-b | `config.py` + `__main__.py` + `config.toml` | `feat: 設定システムとCLI実装` | `--config` 動作 |
| merge | C1-a + C1-b | — | **★R1 実施** |
| C2 | `llm.py` | `feat: Anthropic LLMクライアント実装` | `pip install anthropic` 確認後 |
| C3 | `compiler.py`（summaries + concepts + INDEX） | `feat: wiki/ レイヤー LLM増分コンパイラ実装` | summaries生成確認 |
| **★R2** | — | — | wiki/レイヤー全体レビュー |
| C4 | `search.py` + `linter.py` | `feat: 検索CLIとヘルスチェック実装` | search/lint動作確認 |

### Code Review Gate 詳細

| ゲート | タイミング | 対象ファイル | 重点観点 |
|--------|-----------|------------|---------|
| R1 | C1-a + C1-b merge後 | `ingest.py`, `converter.py`, `state.py`, `config.py`, `__main__.py` | front matter整合性・差分管理ロジック・CLI拡張性 |
| R2 | C3完了後 | `llm.py`, `compiler.py` | APIエラー処理・増分管理・コスト制御・wikilink整合性 |

**中断条件**: R1 または R2 で `[High]` が `max-rounds`（2）到達後も残存する場合、次フェーズへ進まずユーザーに報告する。

## Appendix: モデル割り当てサマリー

| Task | モデル | 実行方式 | 理由 |
|------|--------|---------|------|
| 1.1 スケルトン | `codex:low` | Codex | boilerplate生成・反復作業 |
| 1.2 ingest+converter | `codex:high` | Codex | crawler.pyからの多ファイルリファクタ |
| 1.3 config+CLI | `codex:medium` | Codex | TOMLパターン・argparseの標準実装 |
| 2.1 llm.py | `opus` | Claude | 新アーキテクチャ導入・cross-service設計 |
| 2.2 compiler summaries | `opus` | Claude | wiki/raw/レイヤー境界設計・LLM統合核心 |
| 2.3 compiler concepts | `sonnet` | Claude | Task 2.2パターン踏襲の拡張実装 |
| 3.1 search.py | `codex:medium` | Codex | 直接的なファイル検索ロジック |
| 3.2 linter.py | `codex:medium` | Codex | パターン分析・レポート生成 |

**モデル分布**: Opus ×2 / Sonnet ×1 / codex:high ×1 / codex:medium ×3 / codex:low ×1  
**並列実行候補**: C1-a（Task 1.2）× C1-b（Task 1.3）

---

## Codex Review Notes
- **ラウンド数**: 1 / max-rounds 3
- **停止理由**: self-review 反映後 no-blocking-findings
- **残存 findings**: なし
- **反映した修正**:
  - [Medium] `_meta/manifest.json`（SHA-256）を採用し kb-* スキルと互換化
  - [Medium] `status: raw → compiled` ライフサイクルを採用（CompileState を manifest に統合）
  - `anthropic` pip 確認タイミングを「C3前」→「C2前」に修正
