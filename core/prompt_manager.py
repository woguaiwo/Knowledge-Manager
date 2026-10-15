"""
User-configurable AI prompt templates.

All prompts are stored in the SQLite settings table under keys prefixed with
"prompt_". This module provides the defaults and a simple get/save API.
"""
import json
from typing import Dict

from core import database


# Default prompts used across the application.
# Each entry maps a settings key to a dict with optional "system" and "user"
# fields. "user" templates may contain placeholders like {question}.
DEFAULT_PROMPTS: Dict[str, Dict[str, str]] = {
    "prompt_target_reading": {
        "system": "你是一个有帮助的阅读助手。",
        "user": (
            "你是一个阅读助手。用户针对一篇 PDF 文档提出问题，请在文档中找出所有相关的段落，"
            "并以 JSON 数组的形式返回。\n\n"
            "每个条目必须包含:\n"
            '- "page": 页码（从 1 开始）\n'
            '- "quote": 文档中的原文片段（可以是句子或段落，保留足够上下文）\n'
            '- "explanation": 说明该段落为何与问题相关，并给出你的分析\n\n'
            "用户问题: {question}\n\n"
            "文档内容:\n{pdf_text}\n\n"
            "请只返回 JSON 数组，不要添加 markdown 代码块或其他额外文字。"
        ),
    },
    "prompt_explain_selection": {
        "system": (
            "You are a helpful reading assistant. The user is reading a document "
            "and will ask you to explain words or phrases. Reply in Chinese with "
            "detailed explanations including definition and usage. "
            "Do NOT output your internal reasoning, chain-of-thought, or <think> tags; "
            "only output the final explanation."
        ),
        "user": '请解释这个词/短语："{selected_text}"{context}\n请用中文详细解释，包括定义和用法。',
    },
    "prompt_explain_image": {
        "system": (
            "You are a helpful reading assistant. The user is reading a document "
            "and may ask you to explain images or pages. Reply in Chinese with "
            "detailed explanations. "
            "Do NOT output your internal reasoning, chain-of-thought, or <think> tags; "
            "only output the final explanation."
        ),
        "user": "请解释这张图片的内容和含义",
    },
    "prompt_explain_page": {
        "system": (
            "You are a helpful reading assistant. The user is reading a document "
            "and may ask you to explain images or pages. Reply in Chinese with "
            "detailed explanations. "
            "Do NOT output your internal reasoning, chain-of-thought, or <think> tags; "
            "only output the final explanation."
        ),
        "user": "请解释这个页面的内容",
    },
    "prompt_quiz_parser": {
        "system": "You are a precise quiz extraction assistant. Output only valid JSON.",
        "user": (
            "You are a quiz parser. Extract all questions from the following markdown content.\n"
            "Return ONLY a JSON array in this exact format (no markdown code fences, no extra text):\n"
            "[\n"
            '  {\n'
            '    "number": 1,\n'
            '    "text": "question text in markdown",\n'
            '    "options": {"A": "option A text", "B": "option B text", ...},\n'
            '    "correct_answer": "B",\n'
            '    "explanation": "explanation text, can be empty string",\n'
            '    "is_multiple_choice": false\n'
            '  }\n'
            "]\n"
            "For multiple-choice questions, correct_answer may contain multiple letters like 'A,C'.\n"
            "Set is_multiple_choice to true when there are multiple correct answers.\n"
            "If a question lacks an explanation, use empty string.\n"
            "IMPORTANT: If any text contains LaTeX math with backslashes (like \\frac, \\sum), "
            "the backslashes inside JSON string values MUST be doubled (\\ -> \\\\ ) so they survive JSON parsing.\n\n"
            "Markdown content:\n"
            "---\n"
            "{content}\n"
            "---"
        ),
    },
    "prompt_definition": {
        "system": "You are a helpful assistant specialized in language learning.",
        "user": (
            "You are a helpful language-learning assistant. "
            "For each word or phrase below, provide a detailed explanation that includes BOTH definition AND interpretation.\n\n"
            "Requirements:\n"
            "1. Combine the provided context to explain the meaning.\n"
            "2. Include both an English explanation and a Chinese explanation.\n"
            "3. The explanation should not just be a dictionary definition; explain how the word/phrase is used in the given context.\n\n"
            "Return the result as a JSON array in this exact format:\n"
            "[\n"
            '  {"word": "...", "explanation_en": "...", "explanation_cn": "..."},\n'
            "  ...\n"
            "]\n\n"
            "Words/Phrases to explain:\n{words}\n\n"
            "Return ONLY the JSON array, no markdown code blocks, no extra text."
        ),
    },
}


def _serialize(prompt: Dict[str, str]) -> str:
    return json.dumps(prompt, ensure_ascii=False, indent=2)


def _deserialize(raw: str) -> Dict[str, str]:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {k: str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def get_prompt(key: str) -> Dict[str, str]:
    """Return the prompt dict for *key*, falling back to DEFAULT_PROMPTS."""
    default = DEFAULT_PROMPTS.get(key, {})
    raw = database.get_setting(key, "")
    if not raw:
        return dict(default)
    stored = _deserialize(raw)
    # Always include default fields so callers can rely on them.
    merged = dict(default)
    merged.update(stored)
    return merged


def save_prompt(key: str, prompt: Dict[str, str]) -> None:
    """Persist a prompt dict to settings."""
    database.save_setting(key, _serialize(prompt))


def reset_prompt(key: str) -> Dict[str, str]:
    """Reset a prompt to its built-in default."""
    default = DEFAULT_PROMPTS.get(key, {})
    save_prompt(key, default)
    return dict(default)


def list_prompt_keys() -> list[str]:
    """Return all configurable prompt keys."""
    return list(DEFAULT_PROMPTS.keys())
