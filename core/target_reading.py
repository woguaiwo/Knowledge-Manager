"""
Target Reading AI analysis.
Given a user's question and the full PDF text, ask the AI to find the most
relevant passages and return them as structured JSON.
"""
import json
import re
from typing import List, Dict

from core import api_client


_PROMPT_TEMPLATE = (
    "你是一个阅读助手。用户针对一篇 PDF 文档提出问题，请在文档中找出最相关的段落，"
    "并以 JSON 数组的形式返回。\n\n"
    "每个条目必须包含:\n"
    '- "page": 页码（从 1 开始）\n'
    '- "quote": 文档中的原文片段（1-3 句话）\n'
    '- "explanation": 简要说明该段落为何与问题相关\n\n'
    "用户问题: {question}\n\n"
    "文档内容:\n{pdf_text}\n\n"
    "请只返回 JSON 数组，不要添加 markdown 代码块或其他额外文字。"
)


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inside = False
        result = []
        for line in lines:
            if line.strip().startswith("```"):
                inside = not inside
                continue
            if inside:
                result.append(line)
        return "\n".join(result).strip()
    return text


def _parse_json_array(text: str) -> List[Dict]:
    """Parse the AI response into a list of result dicts."""
    text = _strip_markdown_fences(text)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    # Fallback: find the first JSON array in the text
    match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def analyze_document(pdf_text: str, question: str, provider: Dict) -> List[Dict]:
    """
    Ask the AI to find relevant passages for the given question.

    Returns a list of dicts with keys:
        page: int (1-based)
        quote: str
        explanation: str
    """
    prompt = _PROMPT_TEMPLATE.format(
        question=question.strip(),
        pdf_text=pdf_text.strip(),
    )

    messages = [
        {"role": "system", "content": "You are a helpful reading assistant."},
        {"role": "user", "content": prompt},
    ]

    response = api_client.explain_chat(
        messages,
        provider["base_url"],
        provider["api_key"],
        provider["model"],
        provider.get("proxy", ""),
    )

    if response.startswith("Error:"):
        raise RuntimeError(response)

    raw_results = _parse_json_array(response)
    results = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        page = item.get("page")
        quote = item.get("quote", "")
        explanation = item.get("explanation", "")
        try:
            page = int(page)
        except (ValueError, TypeError):
            continue
        if page < 1 or not quote:
            continue
        results.append({
            "page": page,
            "quote": str(quote).strip(),
            "explanation": str(explanation).strip(),
        })
    return results
