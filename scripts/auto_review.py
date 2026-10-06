#!/usr/bin/env python3
"""Publish CACD drafts that already carry an official answer.

agy only flags prompts that are not on the stored page. It cannot replace a
gabarito cell. Annulled drafts are archived. Written pages become open practice
and stay ungraded.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from vengine.grading import grade
from vengine.store import Store

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
AGY = Path.home() / ".local" / "bin" / "agy"
PROGRESS = DATA / "review-audit-progress.jsonl"
AUDIT_PATH = DATA / "review-audit.json"
GRADE_PATH = DATA / "grade-report.json"
WORKERS = 4
BATCH = 8

AUDIT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string"},
                    "prompt_supported": {"type": "boolean"},
                },
                "required": ["label", "prompt_supported"],
            },
        }
    },
    "required": ["items"],
}


def every(store: Store, status: str):
    items = []
    offset = 0
    while True:
        page = store.list_exercises(status, limit=500, offset=offset)
        items.extend(page)
        if len(page) < 500:
            return items
        offset += len(page)


def prompt_text(item) -> str:
    return "\n\n".join(block.text for block in item.prompt if block.text)


def compact(text: str) -> str:
    return " ".join(text.split())


def statement_absent(prompt: str, page: str) -> bool:
    parts = [part.strip() for part in prompt.split("\n\n") if part.strip()]
    statement = parts[-1] if parts else prompt
    needle = compact(statement)[:40]
    if len(needle) < 24:
        needle = compact(prompt)[:40]
    if len(needle) < 12:
        return False
    return needle.casefold() not in compact(page).casefold()


def official_cell(item) -> str:
    spec = item.interaction
    if spec.kind == "boolean":
        return "C" if spec.correct else "E"
    return spec.correct[0]


def official_response(item):
    spec = item.interaction
    if spec.kind == "boolean":
        return spec.correct
    if len(spec.correct) == 1:
        return spec.correct[0]
    return list(spec.correct)


def page_index(store: Store, items) -> dict[tuple[str, int], str]:
    texts: dict[tuple[str, int], str] = {}
    sources = {item.sources[0].source_id for item in items if item.sources}
    for source_id in sources:
        document = store.document(source_id)
        if document is None:
            continue
        for page in document.pages:
            texts[(source_id, page.number)] = "\n".join(
                block.text for block in page.blocks if block.text)
    return texts


def archive_annulled(store: Store, items) -> int:
    ids = [item.id for item in items if item.metadata.get("annulled")]
    archived = 0
    for start in range(0, len(ids), 100):
        archived += store.archive_review(ids[start:start + 100])
    return archived


def batches(items) -> list[list]:
    grouped: dict[tuple[str, int], list] = {}
    for item in items:
        source_id = item.sources[0].source_id
        grouped.setdefault((source_id, item.metadata.get("page")), []).append(item)
    chunks = []
    for key in sorted(grouped, key=lambda pair: (pair[0], pair[1] or 0)):
        page_items = sorted(grouped[key], key=lambda item: item.label or "")
        for start in range(0, len(page_items), BATCH):
            chunks.append(page_items[start:start + BATCH])
    return chunks


def batch_key(chunk) -> str:
    source_id = chunk[0].sources[0].source_id
    page = chunk[0].metadata.get("page")
    labels = ",".join(item.exercise_id for item in chunk)
    return f"{source_id}:{page}:{labels}"


def audit_prompt(chunk, page_text: str) -> str:
    lines = [
        "Do not use tools. Reason only from the SOURCE pasted below.",
        "For each ITEM, set prompt_supported true only when that item statement",
        "is present in SOURCE. Do not replace or invent the official cell.",
        "",
        "SOURCE:",
        page_text,
        "",
        "ITEMS:",
    ]
    for item in chunk:
        lines.append(f"label: {item.label}")
        lines.append(f"official: {official_cell(item)}")
        lines.append("prompt:")
        lines.append(prompt_text(item))
        lines.append("")
    return "\n".join(lines)


def agy_items(raw: str) -> list[dict]:
    payload = json.loads(raw)
    structured = payload.get("structured_output")
    if not isinstance(structured, dict):
        response = payload.get("response")
        if not isinstance(response, str):
            raise ValueError("agy returned no structured audit")
        structured = json.loads(response)
    rows = structured.get("items")
    if not isinstance(rows, list):
        raise ValueError("agy audit is missing items")
    parsed = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("prompt_supported"), bool):
            raise ValueError("agy audit item is missing prompt_supported")
        parsed.append({"label": str(row.get("label", "")),
                       "prompt_supported": row["prompt_supported"]})
    return parsed


def call_agy(prompt: str) -> list[dict]:
    command = [
        str(AGY), "-p", prompt, "--output-format", "json",
        "--json-schema", json.dumps(AUDIT_SCHEMA, separators=(",", ":")),
        "--sandbox", "--disable-slash-commands", "--effort", "low",
        "--print-timeout", "120s",
    ]
    last = "agy returned no audit"
    for _ in range(3):
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=150,
                                  cwd=ROOT)
        except subprocess.TimeoutExpired:
            last = "agy timed out"
            continue
        if done.returncode != 0:
            last = (done.stderr or done.stdout or "agy failed")[-400:]
            continue
        try:
            return agy_items(done.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            last = str(exc)
    raise RuntimeError(last)


def load_progress() -> dict[str, dict]:
    done = {}
    if not PROGRESS.exists():
        return done
    for line in PROGRESS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            done[row["batch"]] = row
    return done


def audit(chunks, pages) -> dict[str, dict]:
    done = load_progress()
    pending = [chunk for chunk in chunks if batch_key(chunk) not in done]
    print(f"audit {len(chunks) - len(pending)} cached, {len(pending)} remaining", flush=True)
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)

    def one(chunk):
        source_id = chunk[0].sources[0].source_id
        page = chunk[0].metadata.get("page")
        results = call_agy(audit_prompt(chunk, pages.get((source_id, page), "")))
        return {
            "batch": batch_key(chunk),
            "source_id": source_id,
            "page": page,
            "items": [{"exercise_id": item.exercise_id, "label": item.label} for item in chunk],
            "results": results,
        }

    with PROGRESS.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(WORKERS) as pool:
        futures = {pool.submit(one, chunk): chunk for chunk in pending}
        finished = len(chunks) - len(pending)
        for future in as_completed(futures):
            row = future.result()
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            done[row["batch"]] = row
            finished += 1
            print(f"audit {finished}/{len(chunks)} page {row['page']}", flush=True)
    return done


def disqualify(store: Store, records: dict[str, dict], pages, current) -> list[dict]:
    by_id = {item.exercise_id: item for item in current}
    unsupported = []
    kept = 0
    for record in records.values():
        verdict = {row["label"]: row["prompt_supported"] for row in record["results"]}
        page_text = pages.get((record["source_id"], record["page"]), "")
        for ref in record["items"]:
            if verdict.get(ref["label"], True):
                continue
            item = by_id.get(ref["exercise_id"])
            if item is None:
                continue
            if not statement_absent(prompt_text(item), page_text):
                kept += 1
                continue
            entry = {"exercise_id": item.exercise_id, "label": item.label,
                     "source_id": record["source_id"], "page": record["page"],
                     "prompt_supported": False}
            unsupported.append(entry)
            if item.answer_origin != "official" and item.metadata.get("prompt_supported") is False:
                continue
            metadata = dict(item.metadata)
            metadata["prompt_supported"] = False
            store.revise(item.exercise_id, {
                "answer_origin": "unknown",
                "metadata": metadata,
                "review_notes": [*item.review_notes, "Prompt is not on the stored page."],
            })
    print(f"unsupported {len(unsupported)}; agy rejections kept {kept}", flush=True)
    return unsupported


def publish_written(store: Store) -> int:
    published = 0
    seen: set[str] = set()
    for item in every(store, "needs_review"):
        if item.metadata.get("type") != "written" and item.interaction.kind != "rubric":
            continue
        if item.metadata.get("prompt_supported") is False:
            continue
        if item.passage_id and item.passage_id not in seen:
            seen.add(item.passage_id)
            passage = store.latest_passage(item.passage_id)
            if passage is not None and passage.status != "approved":
                store.approve_passage(passage.id)
        latest = store.latest(item.exercise_id)
        if latest is None or latest.status == "approved":
            continue
        if latest.metadata.get("annulled") or latest.metadata.get("prompt_supported") is False:
            continue
        store.approve(latest.id)
        published += 1
    return published


def grade_approved(store: Store, unsupported: list[dict]) -> dict:
    failures = []
    scored = 0
    correct = 0
    annulled_approved = []
    for item in every(store, "approved"):
        if item.metadata.get("annulled"):
            annulled_approved.append(item.label)
        if item.interaction.kind not in {"boolean", "choice"}:
            continue
        scored += 1
        result = grade(item, official_response(item))
        if result.outcome == "correct":
            correct += 1
        else:
            failures.append({"label": item.label, "exercise_id": item.exercise_id,
                             "outcome": result.outcome})
    review = every(store, "needs_review")
    unsupported_ids = {row["exercise_id"] for row in unsupported}
    review_ids = {item.exercise_id for item in review}
    report = {
        "scored": scored,
        "correct": correct,
        "failures": failures,
        "review_remaining": len(review_ids),
        "unsupported": len(unsupported_ids),
        "annulled_approved": annulled_approved,
        "review_matches_unsupported": review_ids == unsupported_ids,
    }
    return report


def main() -> int:
    if not AGY.is_file() or not os.access(AGY, os.X_OK):
        print("agy is not installed at ~/.local/bin/agy", file=sys.stderr)
        return 2
    store = Store(DATA)
    archived = archive_annulled(store, every(store, "needs_review"))
    print(f"archived annulled {archived}", flush=True)
    review = every(store, "needs_review")
    objective = [item for item in review
                 if item.metadata.get("type") == "objective"
                 and item.interaction.kind in {"boolean", "choice"}]
    pending = [item for item in objective if item.answer_origin == "official"]
    pages = page_index(store, objective)
    records = audit(batches(pending), pages)
    unsupported = disqualify(store, records, pages, objective)
    AUDIT_PATH.write_text(json.dumps({"unsupported": unsupported}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    accepted = store.accept_official()
    print(f"accept-official {accepted}", flush=True)
    written = publish_written(store)
    print(f"published written {written}", flush=True)
    report = grade_approved(store, unsupported)
    report["accept_official"] = accepted
    report["written_published"] = written
    report["archived_annulled"] = archived
    GRADE_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in
                      ("scored", "correct", "review_remaining", "unsupported")}, indent=2))
    clean = (not report["failures"] and not report["annulled_approved"]
             and report["review_matches_unsupported"] and report["correct"] == report["scored"])
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main())
