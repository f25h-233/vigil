"""SiliconFlow 客户端（OpenAI 兼容接口）。

只用标准库 urllib —— 项目依赖表目前只有 sqlcipher3，
为一个 POST 请求引入 httpx 不划算。

契约由 _probe_refine.py 用真实消息实测确定，三处易错点刻在下面，
改提示词的人务必先读：

  1. ``response_format={"type": "json_object"}`` 会让模型返回**对象**
     而非裸数组。所以提示词必须要求 ``{"items": [...]}`` 这种外层包裹，
     不能要求返回数组。
  2. 不告诉模型「今天」是哪天，它会把「9月7号」猜成过去的年份
     （实测猜成了 2023）。所以 user 消息里必须注入当前日期。
  3. 模型倾向只处理第一条消息就停下（实测输出仅 88 token）。
     所以提示词必须明确「无价值的消息直接不出现在结果里」。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_BASE = "https://api.siliconflow.cn/v1/chat/completions"

# 实测默认：15 条消息 1170 输入 / 175 输出 token，
# 与 32B 档位在本批样本上质量持平，但便宜约一个数量级。
DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class LLMError(RuntimeError):
    """调用失败——重试耗尽，或响应无法解析。"""


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE
    timeout: int = 180
    max_retries: int = 3
    temperature: float = 0.1


@dataclass(frozen=True)
class LLMResult:
    payload: dict
    input_tokens: int
    output_tokens: int


def _loads(text: str) -> dict:
    """稳健解析模型输出：容忍 ``` 围栏与前后缀噪声。

    ⚠️ 两道闸都不能省——W2 审查实测抓出，两者都会**穿透 chat_json 的契约**：

    * **content 可能不是字符串**（`null` 或数字）。模型返回工具调用、或被内容
      过滤时就是 `null`，此时 `None.strip()` 抛 `AttributeError`；
      调用方按常理 `except LLMError`，会被崩掉整轮 refine。
    * **顶层可能是裸数组**。直接返回 list 的话，下游 `payload.get("items")`
      会抛 `AttributeError`——同样穿透契约。本函数声明的是 `-> dict`，
      就必须保证真的是 dict。
    """
    if not isinstance(text, str):
        raise ValueError(f"content 不是字符串，而是 {type(text).__name__}")

    stripped = _FENCE.sub("", text.strip())
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(stripped[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError(f"顶层不是 JSON 对象，而是 {type(parsed).__name__}")
    return parsed


def chat_json(
    cfg: LLMConfig,
    *,
    system: str,
    user: str,
    sleep=time.sleep,
) -> LLMResult:
    """发一次对话请求，返回解析后的 JSON 与 token 用量。

    sleep 可注入，测试里传 ``lambda _: None`` 就能免去真实等待。
    """
    body = json.dumps(
        {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": cfg.temperature,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")

    last_error: Exception | None = None

    for attempt in range(cfg.max_retries):
        request = urllib.request.Request(
            cfg.base_url,
            data=body,
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=cfg.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            # 4xx（限流除外）重试不会有不同结果——立刻失败，别白等
            if 400 <= exc.code < 500 and exc.code != 429:
                raise LLMError(f"HTTP {exc.code}: {detail}") from exc
            last_error = LLMError(f"HTTP {exc.code}: {detail}")
        except Exception as exc:  # noqa: BLE001 — 网络层什么都可能抛
            last_error = exc

        if attempt < cfg.max_retries - 1:
            sleep(2**attempt)
    else:
        raise LLMError(f"重试 {cfg.max_retries} 次仍失败: {last_error}")

    try:
        content = raw["choices"][0]["message"]["content"]
        payload = _loads(content)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        # ⚠️ 用 ValueError 而不是 json.JSONDecodeError：_loads 的两道
        # 「类型闸」抛的是 ValueError，而 JSONDecodeError 本就是它的子类，
        # 所以这一条同时覆盖两者。少 Catch 一种就会让它穿透契约。
        raise LLMError(f"响应解析失败: {type(exc).__name__}: {exc}") from exc

    usage = raw.get("usage") or {}
    return LLMResult(
        payload=payload,
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
    )
