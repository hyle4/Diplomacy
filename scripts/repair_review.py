#!/usr/bin/env python3
"""Publish review items whose prompt kept the next command after the statement.

The official cell is left as stored. A prompt stays in review when its first
paragraph is not on the stored page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from vengine.grading import grade
from vengine.store import Store

ROOT = Path(__file__).resolve().parents[1]
CUT = re.compile(
    r"(?:^|\n)\s*(?:Texto para|Espa[cç]o livre|About the previous|Quest[aã]o\b|"
    r"Acerca d|Sabendo que|Em economias|Em relação ao|Considerando |Relativamente |"
    r"No que se refere|A respeito d|Tendo em vista|A partir do texto|Julgue os itens)|"
    r"(?<=\.)\s+(?:Tendo em vista|A partir do texto|Julgue os itens|Relativamente |Em relação ao)",
    re.I | re.M,
)


def compact(text: str) -> str:
    return " ".join(text.split())


def trim(prompt: str) -> str:
    match = CUT.search(prompt, 40)
    if match is None:
        return prompt.strip()
    cut = match.start()
    previous = prompt.rfind(".", 0, cut)
    if previous >= 40 and cut - previous < 120:
        cut = previous + 1
    return prompt[:cut].strip()


def on_page(store: Store, item, statement: str) -> bool:
    if not item.sources:
        return False
    source = item.sources[0]
    document = store.document(source.source_id)
    if document is None:
        return False
    page = next((entry for entry in document.pages if entry.number == source.page), None)
    if page is None:
        return False
    hay = compact("\n".join(block.text for block in page.blocks if block.text))
    needle = compact(statement)[:40]
    return len(needle) >= 12 and needle.casefold() in hay.casefold()


def response_for(item):
    spec = item.interaction
    if spec.kind == "boolean":
        return spec.correct
    if len(spec.correct) == 1:
        return spec.correct[0]
    return list(spec.correct)


def count_review(store: Store) -> int:
    total = 0
    offset = 0
    while True:
        page = store.list_exercises("needs_review", limit=500, offset=offset)
        total += len(page)
        if len(page) < 500:
            return total
        offset += len(page)


def main() -> int:
    store = Store(ROOT / "data")
    audit = json.loads((ROOT / "data" / "review-audit.json").read_text(encoding="utf-8"))
    published = []
    held = []
    for row in audit["unsupported"]:
        item = store.latest(row["exercise_id"])
        if item is None or item.status == "approved":
            continue
        original = "\n\n".join(block.text for block in item.prompt if block.text)
        trimmed = trim(original)
        first = trimmed.split("\n\n", 1)[0]
        if not trimmed or not on_page(store, item, first):
            held.append(row["label"])
            continue
        prompt = [block.model_dump(mode="json") for block in item.prompt]
        prompt[0]["text"] = trimmed
        metadata = dict(item.metadata)
        metadata["prompt_supported"] = True
        store.revise(item.exercise_id, {
            "prompt": prompt,
            "answer_origin": "official",
            "metadata": metadata,
        })
        latest = store.latest(item.exercise_id)
        if latest.passage_id:
            passage = store.latest_passage(latest.passage_id)
            if passage is not None and passage.status != "approved":
                store.approve_passage(passage.id)
            latest = store.latest(item.exercise_id)
        approved = store.approve(latest.id)
        result = grade(approved, response_for(approved))
        if result.outcome != "correct":
            held.append(row["label"])
            continue
        published.append(row["label"])
    review = count_review(store)
    print(json.dumps({"published": published, "held": held, "review": review}, ensure_ascii=False))
    return 0 if not held and review == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
