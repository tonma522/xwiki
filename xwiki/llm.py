"""LLM API クライアント（Anthropic Claude ラッパー）"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass


@dataclass
class LLMClient:
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8000

    def _get_client(self):  # type: ignore[return]
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

    def complete(self, prompt: str, system: str = "") -> str:
        """プロンプトを送信してテキスト応答を返す（リトライあり）"""
        client = self._get_client()
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        for attempt in range(3):
            try:
                response = client.messages.create(**kwargs)
                return response.content[0].text
            except Exception as e:
                err_str = str(e).lower()
                if "rate_limit" in err_str or "overloaded" in err_str:
                    wait = 2 ** attempt * 5
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError("LLM API: リトライ上限（3回）に達しました")
