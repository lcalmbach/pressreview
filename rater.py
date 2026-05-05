import json
import os
import re
from typing import Dict, List

import anthropic
from openai import OpenAI

from db import DEFAULT_DB_PATH, RELEVANCE_THRESHOLD, list_unrated_articles, update_article_relevance

MODELS: Dict[str, Dict] = {
    "Claude Haiku 4.5 (fast)":   {"provider": "anthropic", "model_id": "claude-haiku-4-5-20251001"},
    "Claude Sonnet 4.6":          {"provider": "anthropic", "model_id": "claude-sonnet-4-6"},
    "DeepSeek Chat":              {"provider": "deepseek",  "model_id": "deepseek-chat"},
    "DeepSeek Reasoner":          {"provider": "deepseek",  "model_id": "deepseek-reasoner"},
}

DEFAULT_MODEL_KEY = "Claude Haiku 4.5 (fast)"

SYSTEM_PROMPT = (
    "You are a relevance judge for a Basel city news digest. "
    "You rate articles on how relevant they are to Basel city politics, "
    "local governance, urban development, and public affairs in the Basel region. "
    "Respond only with a valid JSON object."
)

USER_PROMPT = """Rate the relevance of this article to Basel city affairs on a scale from 1 to 10.

Title: {title}
Summary: {summary}
Matched keywords: {keywords}

Scoring guide:
- 9–10: Directly about Basel city government, politics, or major local decisions
- 7–8: Clearly relevant to Basel residents or local affairs
- 5–6: Loosely related, Basel mentioned in passing
- 1–4: Not relevant to Basel local affairs

Respond with JSON only:
{{"score": <integer 1-10>, "reason": "<one short sentence>"}}"""


def _parse_response(text: str) -> tuple[int, str]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in response: {text!r}")
    data = json.loads(match.group())
    score = int(data["score"])
    if not 1 <= score <= 10:
        raise ValueError(f"Score out of range: {score}")
    return score, str(data["reason"])


def _call_anthropic(model_id: str, prompt: str) -> str:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model_id,
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _call_deepseek(model_id: str, prompt: str) -> str:
    client = OpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com",
    )
    response = client.chat.completions.create(
        model=model_id,
        max_tokens=256,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


def rate_articles(db_path: str = DEFAULT_DB_PATH, model_key: str = DEFAULT_MODEL_KEY) -> Dict:
    articles = list_unrated_articles(db_path)
    if not articles:
        return {"rated": 0, "skipped": 0, "errors": [], "model": model_key}

    model_cfg = MODELS.get(model_key, MODELS[DEFAULT_MODEL_KEY])
    provider = model_cfg["provider"]
    model_id = model_cfg["model_id"]

    rated = skipped = 0
    errors: List[str] = []

    for article in articles:
        prompt = USER_PROMPT.format(
            title=article["title"] or "",
            summary=article["summary"] or "",
            keywords=article["matched_keywords"] or "",
        )
        try:
            if provider == "anthropic":
                text = _call_anthropic(model_id, prompt)
            else:
                text = _call_deepseek(model_id, prompt)
            score, reason = _parse_response(text)
            update_article_relevance(article["id"], score, reason, db_path)
            rated += 1
        except Exception as exc:
            errors.append(f"Article {article['id']} ({article['title'][:40]}…): {exc}")
            skipped += 1

    return {
        "rated": rated,
        "skipped": skipped,
        "threshold": RELEVANCE_THRESHOLD,
        "model": model_key,
        "errors": errors,
    }
