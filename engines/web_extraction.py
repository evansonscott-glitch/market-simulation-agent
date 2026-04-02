"""
Web Content Extraction Engine — Captures real webpage/form structure for simulation.

When the skill needs to simulate a user viewing a webpage or filling out a form,
this engine fetches the actual page and extracts structured content that can be
fed to personas during interviews.

Two extraction paths:
  - URL mode: Uses Scrapling Fetcher to fetch and parse a live URL
  - HTML mode: Uses Scrapling Adaptor to parse raw HTML (for local files, testing)

Falls back gracefully if Scrapling is not installed or the URL is unreachable.

Extraction modes:
  - webpage: Extracts headline, sections, CTAs, pricing, social proof, navigation
  - form: Extracts form fields, steps, labels, required fields, submit buttons
"""
import os
from typing import Dict, Any, List, Optional

from engines.logging_config import get_logger

logger = get_logger(__name__)


def _get_page(url_or_html: str):
    """
    Get a Scrapling page object from either a URL or raw HTML string.

    Returns (page, error_string). If page is None, error_string explains why.
    """
    is_html = url_or_html.strip().startswith("<") or "\n" in url_or_html[:200]

    if is_html:
        try:
            from scrapling.parser import Adaptor
            return Adaptor(url_or_html, url="local://"), None
        except ImportError:
            return None, "Scrapling not installed. Run: pip install scrapling"
        except Exception as e:
            return None, f"Failed to parse HTML: {e}"

    # URL mode — try Fetcher
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url_or_html)
        return page, None
    except ImportError:
        return None, "Scrapling fetchers not installed. Run: pip install 'scrapling[fetchers]'"
    except Exception as e:
        return None, f"Failed to fetch {url_or_html}: {e}"


def _safe_css(page, selector: str) -> list:
    """Safely run a CSS selector, returning empty list on failure."""
    try:
        return page.css(selector) or []
    except Exception:
        return []


def _el_text(el) -> str:
    """Safely extract text from an element."""
    try:
        return (el.text or "").strip()
    except Exception:
        return ""


def extract_webpage(url_or_html: str) -> Dict[str, Any]:
    """
    Extract structured content from a webpage URL or raw HTML.

    Returns a dict with: url, title, meta_description, headline, sections,
    ctas, navigation, forms, images_alt, social_proof, pricing, raw_text.
    """
    page, error = _get_page(url_or_html)
    if page is None:
        return {"error": error, "url": url_or_html[:200]}

    result = {
        "url": url_or_html[:200] if not url_or_html.strip().startswith("<") else "local://",
        "title": "",
        "meta_description": "",
        "headline": "",
        "sections": [],
        "ctas": [],
        "navigation": [],
        "forms": [],
        "images_alt": [],
        "social_proof": [],
        "pricing": [],
        "raw_text": "",
    }

    # Title
    title_els = _safe_css(page, "title")
    if title_els:
        result["title"] = _el_text(title_els[0])

    # Meta description
    meta_els = _safe_css(page, 'meta[name="description"]')
    if meta_els:
        result["meta_description"] = meta_els[0].attrib.get("content", "")

    # Main headline (h1)
    h1s = _safe_css(page, "h1")
    if h1s:
        result["headline"] = _el_text(h1s[0])

    # Sections — h2s with their following content
    for h2 in _safe_css(page, "h2"):
        heading = _el_text(h2)
        if heading:
            parent = h2.parent
            section_text = _el_text(parent)[:500] if parent else ""
            result["sections"].append({"heading": heading, "content": section_text})

    # CTAs — buttons and action links
    cta_selectors = [
        "button", '[class*="cta"]', '[class*="btn"]',
        'a[href*="signup"]', 'a[href*="register"]', 'a[href*="demo"]',
        'a[href*="trial"]', 'a[href*="start"]', 'a[href*="get-started"]',
        'a[href*="buy"]', 'a[href*="pricing"]',
    ]
    seen_ctas = set()
    for selector in cta_selectors:
        for el in _safe_css(page, selector):
            text = _el_text(el)
            if text and text not in seen_ctas and len(text) < 100:
                seen_ctas.add(text)
                result["ctas"].append({
                    "text": text,
                    "href": el.attrib.get("href", ""),
                })

    # Navigation
    seen_nav = set()
    for nav in _safe_css(page, "nav a, header a"):
        text = _el_text(nav)
        if text and text not in seen_nav and len(text) < 50:
            seen_nav.add(text)
            result["navigation"].append(text)

    # Forms
    for form in _safe_css(page, "form"):
        form_data = {
            "action": form.attrib.get("action", ""),
            "method": form.attrib.get("method", "GET"),
            "fields": [],
        }
        for inp in _safe_css(form, "input, select, textarea"):
            field = {
                "type": inp.attrib.get("type", "text"),
                "name": inp.attrib.get("name", ""),
                "placeholder": inp.attrib.get("placeholder", ""),
                "required": "required" in inp.attrib,
                "label": "",
            }
            field_id = inp.attrib.get("id", "")
            if field_id:
                labels = _safe_css(page, f'label[for="{field_id}"]')
                if labels:
                    field["label"] = _el_text(labels[0])
            if field["name"] or field["placeholder"]:
                form_data["fields"].append(field)

        submit_btns = _safe_css(form, 'button[type="submit"], input[type="submit"]')
        if submit_btns:
            form_data["submit_text"] = _el_text(submit_btns[0]) or "Submit"
        result["forms"].append(form_data)

    # Images alt text
    for img in _safe_css(page, "img[alt]"):
        alt = img.attrib.get("alt", "").strip()
        if alt and len(alt) > 5:
            result["images_alt"].append(alt)

    # Social proof
    social_selectors = [
        '[class*="testimonial"]', '[class*="review"]', '[class*="quote"]',
        '[class*="social-proof"]', 'blockquote',
    ]
    for selector in social_selectors:
        for el in _safe_css(page, selector):
            text = _el_text(el)
            if text and len(text) > 20:
                result["social_proof"].append(text[:300])

    # Pricing
    for selector in ['[class*="pricing"]', '[class*="price"]', '[class*="plan"]']:
        for el in _safe_css(page, selector):
            text = _el_text(el)
            if text and len(text) > 10:
                result["pricing"].append(text[:500])

    # Raw visible text
    body = _safe_css(page, "body")
    if body:
        result["raw_text"] = _el_text(body[0])[:3000]

    logger.info("Extracted webpage: %d sections, %d CTAs, %d forms",
                len(result["sections"]), len(result["ctas"]), len(result["forms"]))
    return result


def extract_form(url_or_html: str) -> Dict[str, Any]:
    """Extract form structure from a URL or HTML. Adds form_summary."""
    result = extract_webpage(url_or_html)
    forms = result.get("forms", [])
    if forms:
        result["form_summary"] = {
            "total_forms": len(forms),
            "total_fields": sum(len(f.get("fields", [])) for f in forms),
            "required_fields": sum(
                1 for f in forms for field in f.get("fields", []) if field.get("required")
            ),
            "field_types": list(set(
                field.get("type", "text") for f in forms for field in f.get("fields", [])
            )),
        }
    return result


# ──────────────────────────────────────────────
# Prompt Formatters
# ──────────────────────────────────────────────

def format_webpage_for_prompt(extraction: Dict[str, Any]) -> str:
    """Format extracted webpage content into structured text for interview prompts."""
    if "error" in extraction and not extraction.get("title"):
        return f"[Could not extract webpage: {extraction['error']}]"

    parts = [f"# Webpage: {extraction.get('title', 'Untitled')}"]
    parts.append(f"**URL:** {extraction.get('url', 'N/A')}")

    if extraction.get("meta_description"):
        parts.append(f"**Meta Description:** {extraction['meta_description']}")

    if extraction.get("headline"):
        parts.append(f"\n## Above the Fold\n**Headline:** {extraction['headline']}")

    if extraction.get("navigation"):
        parts.append(f"**Navigation:** {', '.join(extraction['navigation'][:10])}")

    if extraction.get("sections"):
        parts.append("\n## Page Sections")
        for s in extraction["sections"][:10]:
            parts.append(f"\n### {s['heading']}")
            if s.get("content"):
                parts.append(s["content"][:300])

    if extraction.get("ctas"):
        parts.append("\n## Calls to Action")
        for cta in extraction["ctas"][:8]:
            parts.append(f"- **{cta['text']}**" + (f" → {cta['href']}" if cta.get("href") else ""))

    if extraction.get("pricing"):
        parts.append("\n## Pricing Section")
        for p in extraction["pricing"][:3]:
            parts.append(p)

    if extraction.get("social_proof"):
        parts.append("\n## Social Proof / Testimonials")
        for sp in extraction["social_proof"][:5]:
            parts.append(f"- {sp}")

    if extraction.get("images_alt"):
        parts.append("\n## Visual Elements (image descriptions)")
        for alt in extraction["images_alt"][:8]:
            parts.append(f"- {alt}")

    return "\n".join(parts)


def format_form_for_prompt(extraction: Dict[str, Any]) -> str:
    """Format extracted form content into structured text for form_test interviews."""
    if "error" in extraction and not extraction.get("forms"):
        return f"[Could not extract form: {extraction['error']}]"

    parts = [f"# Form / Signup Flow: {extraction.get('title', 'Untitled')}"]
    parts.append(f"**URL:** {extraction.get('url', 'N/A')}")

    forms = extraction.get("forms", [])
    if not forms:
        parts.append("\n**No forms detected on this page.**")
        if extraction.get("raw_text"):
            parts.append(f"\nPage content:\n{extraction['raw_text'][:1000]}")
        return "\n".join(parts)

    summary = extraction.get("form_summary", {})
    if summary:
        parts.append(f"\n**Total fields:** {summary.get('total_fields', 'N/A')}")
        parts.append(f"**Required fields:** {summary.get('required_fields', 'N/A')}")
        parts.append(f"**Field types:** {', '.join(summary.get('field_types', []))}")

    for i, form in enumerate(forms):
        parts.append(f"\n## Form {i + 1}" + (f" (action: {form['action']})" if form.get("action") else ""))
        parts.append(f"**Method:** {form.get('method', 'GET')}")

        if form.get("fields"):
            parts.append("\n**Fields (in order):**")
            for j, field in enumerate(form["fields"]):
                label = field.get("label") or field.get("placeholder") or field.get("name") or "Unlabeled"
                req = " *(required)*" if field.get("required") else ""
                parts.append(f"{j + 1}. **{label}** — type: {field.get('type', 'text')}{req}")

        if form.get("submit_text"):
            parts.append(f"\n**Submit button:** \"{form['submit_text']}\"")

    return "\n".join(parts)


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage:")
        print("  python3 engines/web_extraction.py webpage <url>")
        print("  python3 engines/web_extraction.py form <url>")
        print("  python3 engines/web_extraction.py webpage-html <path/to/file.html>")
        sys.exit(1)

    mode = sys.argv[1]
    target = sys.argv[2]

    # If target is a file path, read it
    if mode.endswith("-html") or (os.path.isfile(target) and target.endswith(".html")):
        with open(target, "r", encoding="utf-8") as f:
            target = f.read()
        mode = mode.replace("-html", "")

    if mode == "webpage":
        extraction = extract_webpage(target)
        print(format_webpage_for_prompt(extraction))
    elif mode == "form":
        extraction = extract_form(target)
        print(format_form_for_prompt(extraction))
    else:
        print(f"Unknown mode: {mode}. Use 'webpage' or 'form'.")
        sys.exit(1)
