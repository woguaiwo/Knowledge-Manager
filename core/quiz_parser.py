"""
Quiz Markdown parser.
Extracts structured questions from a .md file with YAML frontmatter.
"""
import re
from typing import List, Dict, Optional


def parse_quiz_markdown(text: str, base_dir: str = "") -> Dict:
    """
    Parse a quiz markdown file into structured data.

    Expected format:
    ---
    title: "Batch Name"
    topic: "Topic Name"
    ---

    ## Q1
    Question text (supports markdown, images ![alt](path))

    A. Option A
    B. Option B
    C. Option C

    **Answer: B**
    **Explanation:** Optional explanation

    Returns:
        {
            "meta": {"title": ..., "topic": ..., "description": ..., "tags": [...]},
            "questions": [
                {
                    "number": 1,
                    "text": "...",
                    "options": {"A": "...", "B": "..."},
                    "correct_answer": "B",
                    "explanation": "...",
                    "image_paths": ["..."],
                    "is_multiple_choice": False,
                }
            ]
        }
    """
    result = {
        "meta": {},
        "questions": [],
    }

    # Split frontmatter and body
    text = text.strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            body = parts[2].strip()
            result["meta"] = _parse_frontmatter(frontmatter)
        else:
            body = text
    else:
        body = text

    # Extract all image references from the entire text for path tracking
    all_image_paths = _extract_image_paths(body, base_dir)

    # Split into questions by ## Q{n} or ## 题目 {n}
    question_blocks = _split_questions(body)

    for idx, block in enumerate(question_blocks, start=1):
        q = _parse_question_block(block, idx, base_dir)
        if q:
            result["questions"].append(q)

    return result


def _parse_frontmatter(text: str) -> Dict:
    """Parse simple YAML-like frontmatter."""
    meta = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val.startswith("[") and val.endswith("]"):
                # Simple array: [a, b, c]
                val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
            meta[key] = val
    return meta


def _extract_image_paths(text: str, base_dir: str) -> List[str]:
    """Extract all image paths from markdown ![alt](path)."""
    paths = []
    for match in re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', text):
        path = match.group(2).strip()
        if not path.startswith("http") and base_dir:
            import os
            path = os.path.normpath(os.path.join(base_dir, path))
        paths.append(path)
    return paths


def _split_questions(text: str) -> List[str]:
    """Split markdown body into question blocks by ## Q{n} headers."""
    # Match ## Q1, ## Q2, ## 题目 1, etc.
    pattern = r'(^|\n)##\s+(Q\d+|题目\s*\d+)\s*\n'
    parts = re.split(pattern, text)
    # parts structure: [pre_text, newline, header_text, content, newline, header_text, content, ...]
    blocks = []
    if len(parts) >= 4:
        # Skip parts[0] (preamble before first question) and parts[1] (first separator)
        i = 2
        while i < len(parts):
            header = parts[i].strip()
            content = parts[i + 1] if i + 1 < len(parts) else ""
            blocks.append(content.strip())
            i += 3
    return blocks


def _parse_question_block(block: str, number: int, base_dir: str) -> Optional[Dict]:
    """Parse a single question block into structured dict."""
    lines = block.splitlines()
    if not lines:
        return None

    # Find answer and explanation lines
    answer = ""
    explanation = ""
    answer_line_idx = -1
    explanation_line_idx = -1

    for idx, line in enumerate(lines):
        stripped = line.strip()
        # Match **Answer: X** or **Answer:** X
        m = re.match(r'\*\*Answer\s*[:：]\s*\*\*\s*(.+)$', stripped)
        if m:
            answer = m.group(1).strip()
            answer_line_idx = idx
            continue
        m = re.match(r'\*\*Answer\s*[:：]\s*(.+?)\*\*$', stripped)
        if m:
            answer = m.group(1).strip()
            answer_line_idx = idx
            continue
        # Match **Explanation:** text or **Explanation: text**
        m = re.match(r'\*\*Explanation\s*[:：]\s*\*\*\s*(.*)$', stripped)
        if m:
            explanation = m.group(1).strip()
            explanation_line_idx = idx
            continue
        m = re.match(r'\*\*Explanation\s*[:：]\s*(.*?)\*\*$', stripped)
        if m:
            explanation = m.group(1).strip()
            explanation_line_idx = idx
            continue

    # Remove answer/explanation lines from content to get question text + options
    content_lines = []
    for idx, line in enumerate(lines):
        if idx == answer_line_idx or idx == explanation_line_idx:
            continue
        content_lines.append(line)

    # Parse options: lines starting with A/B/C/D/E... followed by . or )
    options = {}
    option_pattern = re.compile(r'^([A-Z])[\.\)\、]\s*(.+)$')
    option_line_indices = []

    for idx, line in enumerate(content_lines):
        m = option_pattern.match(line.strip())
        if m:
            opt_key = m.group(1)
            opt_text = m.group(2).strip()
            options[opt_key] = opt_text
            option_line_indices.append(idx)

    # Remove option lines to get pure question text
    question_text_lines = []
    for idx, line in enumerate(content_lines):
        if idx not in option_line_indices:
            question_text_lines.append(line)

    question_text = '\n'.join(question_text_lines).strip()

    # Extract image paths from question text
    image_paths = _extract_image_paths(question_text, base_dir)

    # Detect multiple choice
    correct_answers = [a.strip() for a in re.split(r'[,，\s]+', answer) if a.strip()]
    is_multiple_choice = len(correct_answers) > 1

    return {
        "number": number,
        "text": question_text,
        "options": options,
        "correct_answer": answer,
        "explanation": explanation,
        "image_paths": image_paths,
        "is_multiple_choice": is_multiple_choice,
    }
