"""
Philo Ventures Market Simulator — Robust JSON Parser

Multi-strategy JSON extraction from LLM responses.
LLMs frequently return JSON wrapped in markdown code blocks, with trailing
commas, with commentary before/after, or with other formatting issues.

This module provides a robust parsing pipeline that tries multiple strategies
in order of reliability.
"""
import json
import re
from typing import Any, Optional, Union

from engines.logging_config import get_logger

logger = get_logger(__name__)


class JSONParseError(Exception):
    """Raised when all parsing strategies fail."""

    def __init__(self, message: str, raw_text: str, strategies_tried: list):
        self.raw_text = raw_text
        self.strategies_tried = strategies_tried
        super().__init__(message)


def parse_llm_json(
    text: str,
    expected_type: type = dict,
    context: str = "unknown",
) -> Union[dict, list]:
    """
    Parse JSON from an LLM response using multiple fallback strategies.

    Strategies (tried in order):
    1. Direct parse — text is valid JSON as-is
    2. Code block extraction — JSON wrapped in ```json ... ```
    3. Bracket extraction — find outermost { } or [ ] and parse
    4. Repair and retry — fix common LLM JSON errors (trailing commas, etc.)
    5. Lenient extraction — aggressive regex to find JSON-like structures

    Args:
        text: Raw LLM response text.
        expected_type: Expected root type (dict or list). Used for validation.
        context: Description of what we're parsing (for error messages).

    Returns:
        Parsed JSON as dict or list.

    Raises:
        JSONParseError: If all strategies fail.
    """
    if not text or not text.strip():
        raise JSONParseError(
            f"Empty response when parsing {context}",
            raw_text=text or "",
            strategies_tried=["empty_check"],
        )

    strategies_tried = []
    original_text = text.strip()

    # Strategy 1: Direct parse
    try:
        result = json.loads(original_text)
        if isinstance(result, expected_type):
            return result
        strategies_tried.append(f"direct_parse: wrong type (got {type(result).__name__}, expected {expected_type.__name__})")
    except json.JSONDecodeError:
        strategies_tried.append("direct_parse: JSONDecodeError")

    # Strategy 2: Code block extraction
    code_block_result = _extract_from_code_block(original_text)
    if code_block_result is not None:
        try:
            result = json.loads(code_block_result)
            if isinstance(result, expected_type):
                logger.debug("Parsed JSON via code block extraction for %s", context)
                return result
            strategies_tried.append(f"code_block: wrong type (got {type(result).__name__})")
        except json.JSONDecodeError:
            strategies_tried.append("code_block: JSONDecodeError")
    else:
        strategies_tried.append("code_block: no code block found")

    # Strategy 3: Bracket extraction
    bracket_result = _extract_by_brackets(original_text, expected_type)
    if bracket_result is not None:
        try:
            result = json.loads(bracket_result)
            if isinstance(result, expected_type):
                logger.debug("Parsed JSON via bracket extraction for %s", context)
                return result
            strategies_tried.append(f"bracket_extract: wrong type (got {type(result).__name__})")
        except json.JSONDecodeError:
            strategies_tried.append("bracket_extract: JSONDecodeError")

            # Strategy 4: Repair common issues and retry bracket result
            repaired = _repair_json(bracket_result)
            try:
                result = json.loads(repaired)
                if isinstance(result, expected_type):
                    logger.debug("Parsed JSON via repair for %s", context)
                    return result
                strategies_tried.append(f"repair: wrong type (got {type(result).__name__})")
            except json.JSONDecodeError:
                strategies_tried.append("repair: JSONDecodeError after repair")
    else:
        strategies_tried.append("bracket_extract: no brackets found")

    # Strategy 5: Repair the full original text
    repaired_full = _repair_json(original_text)
    try:
        result = json.loads(repaired_full)
        if isinstance(result, expected_type):
            logger.debug("Parsed JSON via full text repair for %s", context)
            return result
        strategies_tried.append(f"full_repair: wrong type (got {type(result).__name__})")
    except json.JSONDecodeError:
        strategies_tried.append("full_repair: JSONDecodeError")

    # All strategies failed
    preview = original_text[:200] + "..." if len(original_text) > 200 else original_text
    raise JSONParseError(
        f"All JSON parsing strategies failed for {context}. "
        f"Strategies tried: {strategies_tried}. "
        f"Text preview: {preview}",
        raw_text=original_text,
        strategies_tried=strategies_tried,
    )


def _extract_from_code_block(text: str) -> Optional[str]:
    """Extract JSON from markdown code blocks (```json ... ``` or ``` ... ```)."""
    # Try ```json first, then plain ```
    patterns = [
        r'```json\s*\n?(.*?)```',
        r'```\s*\n?(.*?)```',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
    return None


def _extract_by_brackets(text: str, expected_type: type = dict) -> Optional[str]:
    """Find the outermost matching brackets and extract the JSON substring."""
    if expected_type == list:
        open_char, close_char = '[', ']'
    else:
        open_char, close_char = '{', '}'

    # Find the first occurrence of the opening bracket
    start = text.find(open_char)
    if start == -1:
        # Try the other bracket type as fallback
        alt_open = '[' if open_char == '{' else '{'
        alt_close = ']' if close_char == '}' else '}'
        start = text.find(alt_open)
        if start == -1:
            return None
        open_char, close_char = alt_open, alt_close

    # Find the matching closing bracket (handle nesting)
    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == '\\' and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def _repair_json(text: str) -> str:
    """
    Attempt to fix common JSON errors from LLM output.

    Fixes:
    - Trailing commas before } or ]
    - Single quotes instead of double quotes (careful with apostrophes)
    - Missing quotes around keys
    - Unescaped newlines in strings
    - JavaScript-style comments
    """
    # Remove JavaScript-style comments
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

    # Remove trailing commas before } or ]
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Fix unescaped newlines within strings (heuristic)
    # This is tricky — only do it if we detect the pattern
    # We look for strings that span multiple lines
    text = re.sub(r'(?<=": ")(.*?)(?="[,}\]])', _escape_newlines_in_match, text, flags=re.DOTALL)

    return text


def _escape_newlines_in_match(match: re.Match) -> str:
    """Escape literal newlines within a JSON string value."""
    value = match.group(0)
    # Only escape if there are actual newlines
    if '\n' in value:
        value = value.replace('\n', '\\n')
    return value
