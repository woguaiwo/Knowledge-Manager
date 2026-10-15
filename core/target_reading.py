"""
Target Reading AI analysis.
Given a user's question and the full PDF text, ask the AI to find the most
relevant passages and return them as structured JSON.
"""
import json
import re
from typing import List, Dict

from core import api_client, prompt_manager


_PROMPT_KEY = "prompt_target_reading"


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


def _analyze_single_text(pdf_text: str, question: str, provider: Dict) -> List[Dict]:
    """Send one chunk of text to the AI and parse the results."""
    cfg = prompt_manager.get_prompt(_PROMPT_KEY)
    user_template = cfg.get("user")
    if not user_template:
        user_template = prompt_manager.DEFAULT_PROMPTS[_PROMPT_KEY]["user"]
    prompt = user_template.format(
        question=question.strip(),
        pdf_text=pdf_text.strip(),
    )

    messages = [
        {"role": "system", "content": cfg.get("system", "")},
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
        # Surface token-limit / context errors clearly
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


def _deduplicate_results(results: List[Dict]) -> List[Dict]:
    """Remove duplicate results based on page + quote snippet."""
    seen = set()
    unique = []
    for item in results:
        page = item.get("page")
        quote = str(item.get("quote", "")).strip()
        key = (page, quote[:120])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _split_text_into_chunks(pdf_text: str, max_chunk_size: int = 8000) -> List[str]:
    """Split the document text into page-based chunks."""
    import re
    # Split by page markers like "--- Page 5 ---"
    pages = re.split(r'\n*--- Page (\d+) ---\n*', pdf_text)
    chunks = []
    current_chunk = ""
    current_size = 0

    for i in range(1, len(pages), 2):
        page_num = pages[i]
        page_text = pages[i + 1] if i + 1 < len(pages) else ""
        page_block = f"--- Page {page_num} ---\n{page_text}"
        if current_size + len(page_block) > max_chunk_size and current_chunk:
            chunks.append(current_chunk)
            current_chunk = page_block
            current_size = len(page_block)
        else:
            current_chunk += "\n\n" + page_block if current_chunk else page_block
            current_size += len(page_block) + 2 if current_chunk else len(page_block)

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def analyze_document(pdf_text: str, question: str, provider: Dict) -> List[Dict]:
    """
    Ask the AI to find relevant passages for the given question.
    For long documents the text is split into page-based chunks and analyzed
    chunk by chunk; results are merged.

    Returns a list of dicts with keys:
        page: int (1-based)
        quote: str
        explanation: str
    """
    if not pdf_text.strip():
        return []

    # Short document: analyze in one shot
    if len(pdf_text) <= 12000:
        return _analyze_single_text(pdf_text, question, provider)

    # Long document: page-based chunking
    chunks = _split_text_into_chunks(pdf_text, max_chunk_size=8000)
    all_results = []
    for chunk in chunks:
        try:
            chunk_results = _analyze_single_text(chunk, question, provider)
            all_results.extend(chunk_results)
        except RuntimeError as e:
            # If one chunk fails, continue with the others
            if "context length" in str(e).lower() or "maximum context" in str(e).lower():
                continue
            raise
    return _deduplicate_results(all_results)
