"""
API client for AI services.
Supports OpenAI-compatible chat completions API.
"""
import json
import os
import sys
from typing import List, Dict

# Fix certifi CA bundle path when running inside PyInstaller bundle
if getattr(sys, 'frozen', False):
    _base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    for _sub in ('certifi/cacert.pem', '_internal/certifi/cacert.pem'):
        _ca = os.path.join(_base, _sub)
        if os.path.isfile(_ca):
            os.environ['REQUESTS_CA_BUNDLE'] = _ca
            os.environ['SSL_CERT_FILE'] = _ca
            break

import requests

from core.logger import get_logger

_logger = get_logger()


# Reasoning-capable models expose their internal trace in several different
# ways. Some providers use a separate reasoning_content/reasoning field, while
# others put <think> or <analysis> tags directly in content. The UI should
# receive the final answer only, so these markers are handled at the API
# boundary before any streaming text reaches a widget or chat history.
_REASONING_START_MARKERS = (
    "<think>",
    "<thinking>",
    "<analysis>",
    "<reasoning>",
    "<thought>",
    "<deliberation>",
    "<|thinking|>",
    "<|begin_of_thought|>",
    "<|channel|>analysis<|message|>",
    "<|channel|>reasoning<|message|>",
    "### analysis",
    "### reasoning",
    "### thought",
    "### thinking",
)
_REASONING_LINE_START_MARKERS = (
    "analysis:",
    "reasoning:",
    "thinking:",
    "thought:",
    "思考：",
    "思考:",
    "分析：",
    "分析:",
    "推理过程：",
    "推理过程:",
)
_REASONING_END_MARKERS = (
    "</think>",
    "</thinking>",
    "</analysis>",
    "</reasoning>",
    "</thought>",
    "</deliberation>",
    "<|endofthinking|>",
    "<|end_of_thought|>",
    "<|channel|>final<|message|>",
    "### final answer",
    "### answer",
)
_REASONING_LINE_END_MARKERS = (
    "final answer:",
    "final:",
    "answer:",
    "最终答案：",
    "最终答案:",
    "答案：",
    "答案:",
    "结论：",
    "结论:",
)


class _ReasoningContentFilter:
    """Remove model reasoning while preserving arbitrary chunk boundaries."""

    def __init__(self):
        self._buffer = ""
        self._in_reasoning = False

    @staticmethod
    def _find_marker(text: str, markers: tuple[str, ...], line_start_only: bool = False):
        lowered = text.lower()
        found = []
        for marker in markers:
            search_from = 0
            while True:
                index = lowered.find(marker, search_from)
                if index < 0:
                    break
                if not line_start_only or index == 0 or text[index - 1] in "\r\n":
                    found.append((index, marker))
                    break
                search_from = index + 1
        if not found:
            return None
        return min(found, key=lambda item: item[0])

    @staticmethod
    def _trailing_marker_prefix_length(text: str, markers: tuple[str, ...]) -> int:
        """Keep a suffix that may be the beginning of a split marker."""
        lowered = text.lower()
        longest = 0
        for marker in markers:
            max_length = min(len(marker) - 1, len(lowered))
            for length in range(1, max_length + 1):
                if lowered.endswith(marker[:length]):
                    longest = max(longest, length)
        return longest

    def feed(self, chunk: str) -> str:
        """Consume one provider chunk and return only safe answer text."""
        if not chunk:
            return ""
        self._buffer += str(chunk)
        output = []

        while self._buffer:
            if self._in_reasoning:
                end_candidates = [
                    self._find_marker(self._buffer, _REASONING_END_MARKERS),
                    self._find_marker(
                        self._buffer, _REASONING_LINE_END_MARKERS, line_start_only=True
                    ),
                ]
                end_candidates = [candidate for candidate in end_candidates if candidate]
                end = min(end_candidates, key=lambda item: item[0]) if end_candidates else None
                if end is None:
                    keep = self._trailing_marker_prefix_length(
                        self._buffer, _REASONING_END_MARKERS + _REASONING_LINE_END_MARKERS
                    )
                    if keep:
                        self._buffer = self._buffer[-keep:]
                    else:
                        self._buffer = ""
                    break
                index, marker = end
                self._buffer = self._buffer[index + len(marker):]
                self._in_reasoning = False
                continue

            start_candidates = [
                self._find_marker(self._buffer, _REASONING_START_MARKERS),
                self._find_marker(
                    self._buffer, _REASONING_LINE_START_MARKERS, line_start_only=True
                ),
            ]
            end_candidates = [
                self._find_marker(self._buffer, _REASONING_END_MARKERS),
                self._find_marker(
                    self._buffer, _REASONING_LINE_END_MARKERS, line_start_only=True
                ),
            ]
            start_candidates = [candidate for candidate in start_candidates if candidate]
            end_candidates = [candidate for candidate in end_candidates if candidate]
            start = min(start_candidates, key=lambda item: item[0]) if start_candidates else None
            end = min(end_candidates, key=lambda item: item[0]) if end_candidates else None
            candidates = [item for item in (start, end) if item is not None]
            if not candidates:
                keep = self._trailing_marker_prefix_length(
                    self._buffer,
                    _REASONING_START_MARKERS
                    + _REASONING_LINE_START_MARKERS
                    + _REASONING_END_MARKERS
                    + _REASONING_LINE_END_MARKERS,
                )
                safe_length = len(self._buffer) - keep
                if safe_length:
                    output.append(self._buffer[:safe_length])
                    self._buffer = self._buffer[safe_length:]
                break

            index, marker = min(candidates, key=lambda item: item[0])
            if start is not None and index == start[0] and marker == start[1]:
                output.append(self._buffer[:index])
                self._buffer = self._buffer[index + len(marker):]
                self._in_reasoning = True
            else:
                # A dangling end marker can occur when the provider sends the
                # opening tag in a separate reasoning field. Remove it too.
                output.append(self._buffer[:index])
                self._buffer = self._buffer[index + len(marker):]

        return "".join(output)

    def finish(self) -> str:
        """Flush a final safe suffix at end of a response."""
        if self._in_reasoning:
            self._buffer = ""
            return ""
        result = self._buffer
        self._buffer = ""
        return result


def _message_content(message: Dict) -> str:
    """Extract assistant content without falling back to reasoning fields."""
    content = message.get("content", "") if isinstance(message, dict) else ""
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") in (
                None, "text", "output_text", "input_text"
            ):
                parts.append(str(part.get("text", "")))
        return "".join(parts)
    return "" if content is None else str(content)


def _strip_reasoning(text: str) -> str:
    """Remove embedded reasoning blocks from a complete response."""
    if not text:
        return ""
    content_filter = _ReasoningContentFilter()
    return content_filter.feed(text) + content_filter.finish()




def _resolve_url(base_url: str) -> str:
    """Smart URL resolution to avoid duplicate /v1 paths.
    Supports arbitrary version suffixes like /v1, /v3, etc."""
    import re
    base_url = base_url.strip()
    if base_url.endswith("/chat/completions"):
        return base_url
    base_url = base_url.rstrip("/")
    # If URL already ends with any /vN version path, just append endpoint
    if re.search(r'/v\d+$', base_url):
        return base_url + "/chat/completions"
    # Default fallback to /v1
    return base_url + "/v1/chat/completions"


def build_prompt(words_data: List[Dict]) -> str:
    """
    Build a prompt that asks the AI to explain each word/phrase with context.
    words_data: list of dicts with keys: word, context
    """
    lines = []
    for item in words_data:
        word = item.get("word", "")
        ctx = item.get("context", "")
        if ctx:
            lines.append(f'- "{word}" (context: {ctx})')
        else:
            lines.append(f'- "{word}"')

    cfg = prompt_manager.get_prompt("prompt_definition")
    user_template = cfg.get("user")
    if not user_template:
        user_template = prompt_manager.DEFAULT_PROMPTS["prompt_definition"]["user"]
    return user_template.format(words="\n".join(lines))


def generate_definitions(
    words_data: List[Dict],
    base_url: str,
    api_key: str,
    model: str,
    proxy: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096
) -> str:
    """
    Send vocabulary list to AI API and request formatted explanations.
    Returns the AI response content as string.
    """
    url = _resolve_url(base_url)
    prompt = build_prompt(words_data)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    if "kimi" in model.lower():
        temperature = 1

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_manager.get_prompt("prompt_definition").get("system", "")},
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    proxies = {}
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    _logger.info(f"[API] generate_definitions -> {url} model={model}")
    try:
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            proxies=proxies,
            timeout=120
        )
        _logger.info(f"[API] generate_definitions response {resp.status_code}")
        # Detailed error reporting for 4xx/5xx
        if not resp.ok:
            try:
                err_detail = resp.json()
                err_msg = err_detail.get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text
            _logger.error(f"[API] generate_definitions error: {resp.status_code} {err_msg}")
            return (
                f"Error: API request failed. {resp.status_code} {resp.reason}\n"
                f"URL: {url}\n"
                f"Model: {model}\n"
                f"Detail: {err_msg}"
            )
        data = resp.json()
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]
        _logger.warning("[API] generate_definitions unexpected format")
        return "Error: Unexpected API response format."
    except requests.exceptions.RequestException as e:
        _logger.error(f"[API] generate_definitions request exception: {e}")
        return f"Error: API request failed. {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


def explain_chat(
    messages: List[Dict],
    base_url: str,
    api_key: str,
    model: str,
    proxy: str = "",
) -> str:
    """
    Send a chat conversation to AI API.
    messages: list of {"role": "system"/"user"/"assistant", "content": "..."}
    Returns the AI assistant's response content as string.
    """
    url = _resolve_url(base_url)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    temperature = 0.7
    max_tokens = 4096
    if "kimi" in model.lower():
        temperature = 1

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    proxies = {}
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            proxies=proxies,
            timeout=120
        )
        if not resp.ok:
            try:
                err_detail = resp.json()
                err_msg = err_detail.get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text
            return (
                f"Error: API request failed. {resp.status_code} {resp.reason}\n"
                f"URL: {url}\n"
                f"Model: {model}\n"
                f"Detail: {err_msg}"
            )
        data = resp.json()
        if "choices" in data and len(data["choices"]) > 0:
            content = _message_content(data["choices"][0].get("message", {}))
            return _strip_reasoning(content)
        return "Error: Unexpected API response format."
    except requests.exceptions.RequestException as e:
        return f"Error: API request failed. {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"


def explain_chat_stream(
    messages: List[Dict],
    base_url: str,
    api_key: str,
    model: str,
    proxy: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    cancel_event=None,
):
    """
    Send a chat conversation to AI API with streaming (SSE).
    messages: list of {"role": "system"/"user"/"assistant", "content": "..."}
    Yields content chunks as they arrive.
    If an error occurs, yields a single string starting with "Error:".
    """
    url = _resolve_url(base_url)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    if "kimi" in model.lower():
        temperature = 1

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True
    }

    proxies = {}
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    _logger.info(f"[API] explain_chat_stream -> {url} model={model} stream=True")
    try:
        if cancel_event is not None and cancel_event.is_set():
            return
        resp = requests.post(
            url,
            headers=headers,
            json=payload,
            proxies=proxies,
            timeout=(10, 60),
            stream=True
        )
        _logger.info(f"[API] explain_chat_stream response {resp.status_code}")
        if not resp.ok:
            try:
                err_detail = resp.json()
                err_msg = err_detail.get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text
            _logger.error(f"[API] explain_chat_stream error: {resp.status_code} {err_msg}")
            yield (
                f"Error: API request failed. {resp.status_code} {resp.reason}\n"
                f"URL: {url}\n"
                f"Model: {model}\n"
                f"Detail: {err_msg}"
            )
            return

        # Some providers ignore stream=True and return full JSON.
        # Detect this by Content-Type and fallback to non-streaming parse.
        content_type = resp.headers.get("Content-Type", "")
        if "text/event-stream" not in content_type:
            try:
                data = resp.json()
                if "choices" in data and len(data["choices"]) > 0:
                    content = _message_content(data["choices"][0].get("message", {}))
                    content = _strip_reasoning(content)
                    if content:
                        yield content
                else:
                    _logger.warning(f"[API] non-stream response missing choices: {data.keys()}")
            except Exception as e:
                _logger.error(f"[API] non-stream parse error: {e}")
                yield f"Error: Unexpected API response format. {str(e)}"
            return

        content_filter = _ReasoningContentFilter()
        for line in resp.iter_lines():
            if cancel_event is not None and cancel_event.is_set():
                # Closing the response releases the socket as soon as the
                # iterator yields control.  The worker also stops forwarding
                # queued chunks, so closing the popup remains immediate.
                try:
                    resp.close()
                except Exception:
                    pass
                return
            if not line:
                continue
            line_str = line.decode("utf-8")
            # Handle both "data: {...}" and "data:{...}" (no space)
            if not line_str.startswith("data:"):
                continue
            data_str = line_str[5:].lstrip()
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
                choices = data.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                content = _message_content(delta)
                # reasoning_content/reasoning is intentionally ignored. It is
                # the model's internal trace, not the assistant answer.
                if content:
                    if content_filter is not None:
                        content = content_filter.feed(content)
                    if content:
                        yield content
            except Exception as e:
                _logger.debug(f"[API] SSE parse error on line: {line_str[:80]}... error: {e}")
                continue
        if content_filter is not None:
            remaining = content_filter.finish()
            if remaining:
                yield remaining

    except requests.exceptions.RequestException as e:
        yield f"Error: API request failed. {str(e)}"
    except Exception as e:
        yield f"Error: {str(e)}"


def parse_definitions(response_text: str) -> List[Dict]:
    """
    Parse the AI response into a list of definition dicts.
    Returns a list of {"word": ..., "explanation_en": ..., "explanation_cn": ...}.
    If parsing fails, returns an empty list.
    """
    if not response_text or response_text.startswith("Error:"):
        return []

    text = response_text.strip()

    # Try to extract JSON from markdown code block
    if text.startswith("```"):
        # Find the first ```json or ``` and extract content
        lines = text.splitlines()
        json_lines = []
        in_json = False
        for line in lines:
            if line.strip().startswith("```"):
                if in_json:
                    break
                in_json = True
                continue
            if in_json:
                json_lines.append(line)
        text = "\n".join(json_lines).strip()

    try:
        data = json.loads(text)
        if isinstance(data, list):
            results = []
            for item in data:
                if isinstance(item, dict):
                    results.append({
                        "word": item.get("word", ""),
                        "explanation_en": item.get("explanation_en", ""),
                        "explanation_cn": item.get("explanation_cn", ""),
                    })
            return results
        return []
    except Exception:
        # Fallback: try to find a JSON array anywhere in the text
        import re
        match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                results = []
                for item in data:
                    if isinstance(item, dict):
                        results.append({
                            "word": item.get("word", ""),
                            "explanation_en": item.get("explanation_en", ""),
                            "explanation_cn": item.get("explanation_cn", ""),
                        })
                return results
            except Exception:
                pass
        return []
