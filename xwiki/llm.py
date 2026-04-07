"""LLM API クライアント（Anthropic Claude ラッパー）"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMClient:
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8000
    provider: str = "anthropic"

    def _get_client(self) -> Any:
        """anthropic クライアントを遅延初期化する"""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY が設定されていません。"
                "環境変数に API キーを設定してください。"
            )
        try:
            import anthropic
            return anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError(
                "anthropic パッケージがインストールされていません。"
                "`pip install anthropic` を実行してください。"
            )

    def _build_system_with_cache(self, system: str) -> list[dict[str, Any]] | None:
        """system が空でない場合は cache_control を付与した list 形式で返す。空の場合は None"""
        if not system:
            return None
        return [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _call_with_retry(self, call_fn: Any) -> Any:
        """指数バックオフで最大3回リトライする"""
        for attempt in range(3):
            try:
                return call_fn()
            except Exception as e:
                err_str = str(e).lower()
                if "rate_limit" in err_str or "overloaded" in err_str:
                    wait = 2 ** attempt * 5
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError("LLM API: リトライ上限（3回）に達しました")

    def complete(self, prompt: str, system: str = "") -> str:
        """プロンプトを送信してテキスト応答を返す（リトライあり）"""
        client = self._get_client()
        system_param = self._build_system_with_cache(system)
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_param is not None:
            kwargs["system"] = system_param

        def call() -> str:
            response = client.messages.create(**kwargs)
            for block in response.content:
                if block.type == "text":
                    return block.text
            raise ValueError("LLM がテキストブロックを返しませんでした")

        return self._call_with_retry(call)

    def complete_json(self, prompt: str, system: str, schema: dict[str, Any]) -> dict[str, Any]:
        """structured outputs（tool use 経由の JSON）を使用して dict を返す"""
        client = self._get_client()
        system_param = self._build_system_with_cache(system)
        tools = [
            {
                "name": "structured_output",
                "description": "指定されたスキーマに従って構造化データを出力する",
                "input_schema": schema,
            }
        ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "tools": tools,
            "tool_choice": {"type": "tool", "name": "structured_output"},
        }
        if system_param is not None:
            kwargs["system"] = system_param

        def call() -> dict[str, Any]:
            response = client.messages.create(**kwargs)
            for block in response.content:
                if block.type == "tool_use":
                    result = block.input
                    if not isinstance(result, dict):
                        raise ValueError(
                            f"LLM が dict でない structured output を返しました: {type(result)}"
                        )
                    return result
            raise ValueError("LLM が structured output を返しませんでした")

        return self._call_with_retry(call)

    def prompt_hash(self, prompt: str, system: str = "") -> str:
        """プロンプトと system の組み合わせを SHA-256 でハッシュ化して返す"""
        return hashlib.sha256((system + "\n---\n" + prompt).encode("utf-8")).hexdigest()
