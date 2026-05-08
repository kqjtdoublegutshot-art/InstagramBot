import json
import logging
import random
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

RULES_FILE = Path(__file__).parent / "rules.json"


def load_rules() -> list[dict]:
    """rules.json을 매번 읽어 반환 — 서버 재시작 없이 룰 수정 가능."""
    try:
        return json.loads(RULES_FILE.read_text(encoding="utf-8")).get("rules", [])
    except Exception as e:
        log.error("rules.json 로드 실패: %s", e)
        return []


def save_rules(rules: list[dict]):
    RULES_FILE.write_text(
        json.dumps({"rules": rules}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_matching_rule(comment_text: str, rules: list[dict], media_id: Optional[str] = None) -> Optional[dict]:
    text = comment_text.lower()
    for rule in rules:
        rule_media_id = rule.get("media_id")
        # media_id가 지정된 룰은 해당 게시물에서만 적용
        if rule_media_id and rule_media_id != media_id:
            continue
        min_keywords = rule.get("min_keywords", 1)
        matched = sum(1 for keyword in rule.get("keywords", []) if keyword.lower() in text)
        if matched >= min_keywords:
            return rule
    return None


def has_rule_for_media(media_id: Optional[str], rules: list[dict]) -> bool:
    """해당 media_id에 대한 룰이 하나라도 있으면 True."""
    for rule in rules:
        if rule.get("media_id") == media_id:
            return True
    return False


def pick_message(value: str | list[str]) -> str:
    """문자열 또는 배열 모두 지원 — 배열이면 랜덤 선택."""
    if isinstance(value, list):
        return random.choice(value)
    return value
