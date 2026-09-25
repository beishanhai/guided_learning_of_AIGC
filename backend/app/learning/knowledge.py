"""知识卡片库（§3 学习内容 / §4.2 证据可追溯）。

- 文件 knowledge/cards.yaml 是内容真源，人工审校后进入版本控制；
- 启动时同步进 knowledge_cards 表，供检索与引用；
- 模型的 knowledge_ids 只能来自这里，模型只被允许给出标签。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ..config import get_settings


@dataclass
class KnowledgeCard:
    id: str
    topic: str
    title: str
    content: str
    source: str = ""
    reviewer: str = ""
    version: str = "k1"
    tags: list[str] = field(default_factory=list)
    applicable_intents: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    pitfalls: list[str] = field(default_factory=list)
    review_status: str = "reviewed"


@dataclass
class KnowledgeBase:
    version: str
    reviewer: str
    cards: dict[str, KnowledgeCard]

    @property
    def ids(self) -> set[str]:
        return set(self.cards.keys())

    @property
    def tags(self) -> set[str]:
        out: set[str] = set()
        for card in self.cards.values():
            out.update(card.tags)
            out.add(card.topic)
        return out

    def get(self, card_id: str) -> KnowledgeCard | None:
        return self.cards.get(card_id)

    def by_topic(self, topic: str) -> list[KnowledgeCard]:
        return [c for c in self.cards.values() if c.topic == topic]

    def resolve(self, tags: list[str], intent: str, limit: int = 3) -> list[KnowledgeCard]:
        """按标签与学习意图检索卡片，保持稳定排序，便于测试与复现。"""

        scored: list[tuple[int, str, KnowledgeCard]] = []
        for card in self.cards.values():
            score = 0
            card_tags = set(card.tags) | {card.topic}
            for tag in tags:
                if tag in card_tags:
                    score += 2
            if intent and intent in (card.applicable_intents or []):
                score += 1
            if score > 0:
                scored.append((-score, card.id, card))
        scored.sort()
        return [item[2] for item in scored[:limit]]

    def for_intent(self, intent: str, limit: int = 8) -> list[KnowledgeCard]:
        cards = [c for c in self.cards.values() if intent in (c.applicable_intents or [])]
        cards.sort(key=lambda c: (c.topic, c.id))
        return cards[:limit]


def load_knowledge_base(path: Path | None = None) -> KnowledgeBase:
    settings = get_settings()
    target = Path(path or settings.knowledge_path)
    if not target.exists():
        return KnowledgeBase(version=settings.knowledge_version, reviewer="", cards={})
    with open(target, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    version = str(raw.get("version") or settings.knowledge_version)
    reviewer = str(raw.get("reviewer") or "")
    cards: dict[str, KnowledgeCard] = {}
    for item in raw.get("cards") or []:
        card = KnowledgeCard(
            id=str(item["id"]),
            topic=str(item.get("topic") or "general"),
            title=str(item.get("title") or item["id"]),
            content=str(item.get("content") or "").strip(),
            source=str(item.get("source") or ""),
            reviewer=str(item.get("reviewer") or reviewer),
            version=str(item.get("version") or version),
            tags=[str(t) for t in (item.get("tags") or [])],
            applicable_intents=[str(t) for t in (item.get("applicable_intents") or [])],
            examples=[str(t) for t in (item.get("examples") or [])],
            pitfalls=[str(t) for t in (item.get("pitfalls") or [])],
            review_status=str(item.get("review_status") or "reviewed"),
        )
        cards[card.id] = card
    return KnowledgeBase(version=version, reviewer=reviewer, cards=cards)


@lru_cache(maxsize=1)
def get_knowledge_base() -> KnowledgeBase:
    return load_knowledge_base()


def reset_knowledge_cache() -> None:
    get_knowledge_base.cache_clear()


def sync_knowledge_cards() -> int:
    """把 YAML 卡片同步进数据库，保证引用可追溯（id 必须存在）。"""

    from ..db import session_scope
    from ..models import KnowledgeCard as KnowledgeCardRow

    base = get_knowledge_base()
    count = 0
    with session_scope() as session:
        existing = {row.id: row for row in session.query(KnowledgeCardRow).all()}
        for card in base.cards.values():
            row = existing.get(card.id)
            if row is None:
                row = KnowledgeCardRow(id=card.id)
                session.add(row)
            row.topic = card.topic
            row.title = card.title
            row.content = card.content
            row.source = card.source
            row.reviewer = card.reviewer
            row.version = card.version
            row.tags = card.tags
            row.applicable_intents = card.applicable_intents
            row.examples = card.examples
            row.pitfalls = card.pitfalls
            row.review_status = card.review_status
            count += 1
    return count
