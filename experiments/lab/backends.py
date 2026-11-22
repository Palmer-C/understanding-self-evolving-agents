"""模型后端。

两种用途要分开，不许混用：
- `ScriptedBackend`：回放预写的回复，用来测**实验台本身**（工具链、预算、落盘）对不对。
  它不产生任何能力证据，跑出来的判定结果不得进入结果表。
- `OpenAIChatBackend`：真实调用，走 OpenAI 兼容的 chat completions 接口，只用标准库。

价格一律不在这里填：token 数照实记，折算美元要等 P-1 的定价表。
"""

from __future__ import annotations

import http.client
import json
import os
import pathlib
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

# 瞬时失败：本机出口对长连接不友好，读超时会发生；这些值得重试。
_RETRYABLE_ERRORS = (
    TimeoutError,
    socket.timeout,
    ConnectionError,
    urllib.error.URLError,
    ssl.SSLError,
    http.client.HTTPException,
)

# 值得重试的状态码：限流与服务端错误。其余 4xx 是请求本身的问题。
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def _load_local_env() -> None:
    """读同目录 .env（gitignored），仅补充未设置的变量；显式环境变量优先。

    这样夜班无论是否继承用户会话的环境变量，都能通过 experiments/lab/.env 拿到后端凭据。
    """
    env_path = pathlib.Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_local_env()


@dataclass
class LLMReply:
    text: str
    prompt_tokens: int
    completion_tokens: int
    raw: dict = None  # type: ignore[assignment]


class BackendUnavailable(RuntimeError):
    pass


class ScriptedBackend:
    """按脚本逐条返回回复。用完最后一条后重复最后一条，便于观察预算耗尽行为。"""

    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        if not replies:
            raise ValueError("ScriptedBackend 至少需要一条回复")
        self.replies = list(replies)
        self._i = 0

    def generate(self, messages: list[dict]) -> LLMReply:
        text = self.replies[min(self._i, len(self.replies) - 1)]
        self._i += 1
        prompt_tokens = sum(len(m.get("content", "")) // 4 for m in messages)
        return LLMReply(text=text, prompt_tokens=prompt_tokens, completion_tokens=len(text) // 4)


class OpenAIChatBackend:
    """OpenAI 兼容接口。配置全走环境变量，不写死模型名与价格。"""

    name = "openai-chat"

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 120.0,
        temperature: Optional[float] = None,
        max_retries: int = 4,
        retry_backoff: float = 3.0,
    ) -> None:
        self.model = model or os.environ.get("AGENT_LAB_MODEL")
        self.base_url = (base_url or os.environ.get("AGENT_LAB_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("AGENT_LAB_API_KEY")
        self.timeout = timeout
        # temperature 默认 None = 不写进请求体，用服务端默认值。
        # 需要"多次独立运行"时由调用方显式给值，四臂同值才公平。
        self.temperature = temperature
        # 瞬时失败重试：本机出口对长连接不友好（已登记 agent/BLOCKERS.md），
        # 一次读超时不该让整轮实验作废。只重试网络层与 429/5xx，
        # 并把重试次数记在 self.retries 上供运行器写进账——静默重试等于改数据。
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.retries = 0
        if not self.model or not self.api_key:
            raise BackendUnavailable(
                "缺少 AGENT_LAB_MODEL / AGENT_LAB_API_KEY；真实调用需要显式配置，不作默认假设"
            )

    def generate(self, messages: list[dict]) -> LLMReply:
        body = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        payload = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                # 429 / 5xx 值得重试；4xx 是请求本身的问题，重试没有意义
                if exc.code in _RETRYABLE_STATUS and attempt < self.max_retries:
                    last_exc = exc
                    self.retries += 1
                    time.sleep(self.retry_backoff * (attempt + 1))
                    continue
                raise BackendUnavailable(f"模型接口返回 {exc.code}: {exc.read()[:500]!r}") from exc
            except _RETRYABLE_ERRORS as exc:
                if attempt < self.max_retries:
                    last_exc = exc
                    self.retries += 1
                    time.sleep(self.retry_backoff * (attempt + 1))
                    continue
                raise BackendUnavailable(f"模型接口连接失败（已重试 {self.max_retries} 次）：{exc}") from exc
        else:  # pragma: no cover —— 上面两处 raise 已覆盖，留作兜底
            raise BackendUnavailable(f"模型接口调用失败：{last_exc}")
        choice = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return LLMReply(
            text=choice,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            raw=data,
        )


def build_backend(kind: str = "scripted", **kwargs):
    """工厂：只有显式选择 'openai' 才走真实调用。"""
    if kind == "scripted":
        return ScriptedBackend(kwargs["replies"])
    if kind == "openai":
        return OpenAIChatBackend(**kwargs)
    raise ValueError(f"未知后端：{kind}")
