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

    prompt = (
        "You are a helpful language-learning assistant. "
        "For each word or phrase below, provide a detailed explanation that includes BOTH definition AND interpretation.\n\n"
        "Requirements:\n"
        "1. Combine the provided context to explain the meaning.\n"
        "2. Include both an English explanation and a Chinese explanation.\n"
        "3. The explanation should not just be a dictionary definition; explain how the word/phrase is used in the given context.\n\n"
        "Return the result as a JSON array in this exact format:\n"
        '[\n'
        '  {"word": "...", "explanation_en": "...", "explanation_cn": "..."},\n'
        '  ...\n'
        ']\n\n'
        "Words/Phrases to explain:\n" + "\n".join(lines) + "\n\n"
        "Return ONLY the JSON array, no markdown code blocks, no extra text."
    )
    return prompt


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
            {"role": "system", "content": "You are a helpful assistant specialized in language learning."},
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
    proxy: str = ""
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
            return data["choices"][0]["message"]["content"]
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
    max_tokens: int = 4096
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
                    content = data["choices"][0]["message"]["content"]
                    if content:
                        yield content
                else:
                    _logger.warning(f"[API] non-stream response missing choices: {data.keys()}")
            except Exception as e:
                _logger.error(f"[API] non-stream parse error: {e}")
                yield f"Error: Unexpected API response format. {str(e)}"
            return

        for line in resp.iter_lines():
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
                content = delta.get("content", "")
                # DeepSeek-R1 uses reasoning_content for thinking process
                if not content:
                    content = delta.get("reasoning_content", "")
                if content:
                    yield content
            except Exception as e:
                _logger.debug(f"[API] SSE parse error on line: {line_str[:80]}... error: {e}")
                continue

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
