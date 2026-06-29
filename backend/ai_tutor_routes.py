"""
K8S NetLab - AI Tutor Routes

POST /api/ai/chat  — SSE streaming AI tutoring assistant.
                     Maintains per-session chat history in memory.
                     Powered by DeepSeek (OpenAI-compatible API).
"""

import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel

from backend import config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["ai-tutor"])

# In-memory chat history: session_token → list of {"role", "content"} dicts
_chat_histories: dict[str, list[dict]] = {}

# How long (seconds) to keep idle histories before pruning
_HISTORY_TTL = 3600
_history_timestamps: dict[str, float] = {}

_SYSTEM_PROMPT = """\
你是一名 Kubernetes 实验平台的 AI 助教，专门帮助学生理解 K8s 概念和完成实验。

## 角色定位
- 你是教学助手，不是搜索引擎
- 用简洁的类比解释抽象概念
- 引导学生自己思考，不直接给出完整答案
- 支持中英文提问，统一用中文回答

## 回答风格
- 每次回复不超过 200 字
- 优先用示例说话，而非罗列定义
- 遇到操作类问题，先问"你看到了什么错误？"
- 遇到概念类问题，先给一句核心类比

## 边界
- 只回答 Kubernetes / 容器 / 云原生相关问题
- 不写完整的 YAML 或命令（让学生自己动手）
- 不替学生直接完成实验步骤
"""

_MAX_MESSAGE_LEN = 1000


def _get_client() -> OpenAI:
    if not config.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=503, detail="AI tutor not configured")
    return OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )


def _prune_old_histories() -> None:
    now = time.time()
    expired = [k for k, t in _history_timestamps.items() if now - t > _HISTORY_TTL]
    for k in expired:
        _chat_histories.pop(k, None)
        _history_timestamps.pop(k, None)


class ChatRequest(BaseModel):
    message: str
    case_id: Optional[str] = None


def _stream_reply(messages: list[dict]) -> StreamingResponse:
    client = _get_client()

    def _generate():
        try:
            stream = client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,  # type: ignore[arg-type]  # built dynamically from valid role/content dicts; runtime-correct
                stream=True,
                max_tokens=512,
                temperature=0.7,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta  # type: ignore[union-attr]  # stream=True narrows type at runtime; mypy cannot infer
                if delta.content:
                    yield f"data: {json.dumps({'text': delta.content}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.error("DeepSeek stream error: %s", exc)
            yield f"data: {json.dumps({'error': '服务暂时不可用，请稍后重试'})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@router.post("/chat", summary="AI tutor SSE chat")
async def ai_chat(
    req: ChatRequest,
    session_token: Optional[str] = Cookie(None),
) -> StreamingResponse:
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    msg = req.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Empty message")
    if len(msg) > _MAX_MESSAGE_LEN:
        raise HTTPException(status_code=400, detail="Message too long")

    _prune_old_histories()

    history = _chat_histories.setdefault(session_token, [])
    _history_timestamps[session_token] = time.time()

    # Build context: system + optional case context + history + new message
    system_content = _SYSTEM_PROMPT
    if req.case_id:
        system_content += f"\n\n当前学生正在学习案例 **{req.case_id}**，请结合该案例背景回答。"

    messages: list[dict] = [{"role": "system", "content": system_content}]
    # Keep last N turns to stay within token budget
    recent = history[-(config.AI_TUTOR_MAX_TURNS * 2):]
    messages.extend(recent)
    messages.append({"role": "user", "content": msg})

    # Append user message to history (before streaming; reply appended after)
    history.append({"role": "user", "content": msg})

    # Stream reply, also collect full text to persist to history
    client = _get_client()
    full_reply: list[str] = []

    def _generate():
        try:
            stream = client.chat.completions.create(
                model=config.DEEPSEEK_MODEL,
                messages=messages,  # type: ignore[arg-type]  # built dynamically from valid role/content dicts; runtime-correct
                stream=True,
                max_tokens=512,
                temperature=0.7,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta  # type: ignore[union-attr]  # stream=True narrows type at runtime; mypy cannot infer
                if delta.content:
                    full_reply.append(delta.content)
                    yield f"data: {json.dumps({'text': delta.content}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.error("DeepSeek stream error: %s", exc)
            yield f"data: {json.dumps({'error': '服务暂时不可用，请稍后重试'})}\n\n"
        finally:
            # Persist assistant reply to history
            if full_reply:
                history.append({"role": "assistant", "content": "".join(full_reply)})
            yield "data: [DONE]\n\n"

    return StreamingResponse(_generate(), media_type="text/event-stream")


@router.delete("/chat/history", summary="Clear current session chat history")
async def clear_history(
    session_token: Optional[str] = Cookie(None),
) -> dict:
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    _chat_histories.pop(session_token, None)
    _history_timestamps.pop(session_token, None)
    return {"cleared": True}
