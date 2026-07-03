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
    "You are a reading assistant. The user asks a question about a PDF document. "
    "Find the most relevant passages in the document and return them as a JSON array only.\n\n"
    "Each item must contain:\n"
    '- "page": 1-based page number\n'
    '- "quote": exact text snippet from the document (1-3 sentences)\n'
    '- "explanation": brief note explaining why this passage is relevant to the question\n\n'
    "User question: {question}\n\n"
    "Document content:\n{pdf_text}\n\n"
    "Return ONLY a JSON array, no markdown code blocks, no extra text."
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
