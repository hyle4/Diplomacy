"""Resumable download stage with content checks and per-file SHA-256 receipts."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen
import json
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def fetch(asset):
    path = ROOT / asset["path"]
    receipt = path.with_suffix(path.suffix + ".json")
    if path.exists() and receipt.exists():
        prior = json.loads(receipt.read_text())
        if sha256(path.read_bytes()).hexdigest() == prior.get("sha256"):
            return asset["id"], "cached"
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            with urlopen(Request(asset["url"], headers={"User-Agent": "Diplomacy local study archive"}), timeout=60) as response:
                raw = response.read(80 * 1024 * 1024)
                final_url = response.url
            expected = b"PK" if path.suffix == ".zip" else b"%PDF"
            if not raw.startswith(expected):
                raise ValueError("Unexpected content: expected PDF or ZIP")
            temp = path.with_suffix(path.suffix + ".part")
            temp.write_bytes(raw)
            temp.replace(path)
            receipt.write_text(json.dumps({"url": asset["url"], "resolved_url": final_url,
                "sha256": sha256(raw).hexdigest(), "bytes": len(raw),
                "fetched_at": datetime.now(timezone.utc).isoformat()}, indent=2))
            if path.suffix == ".zip":
                with zipfile.ZipFile(path) as archive:
                    out = path.with_suffix("")
                    out.mkdir(exist_ok=True)
                    for info in archive.infolist():
                        if info.filename.lower().endswith(".pdf") and info.file_size < 80*1024*1024:
                            name = Path(info.filename.replace("\\", "/")).name
                            (out / name).write_bytes(archive.read(info))
            return asset["id"], "downloaded"
        except Exception as exc:
            if attempt == 2:
                return asset["id"], "FAILED: " + str(exc)
            time.sleep(attempt + 1)


def main():
    assets = json.loads((ROOT / "sources.json").read_text())["assets"]
    failures = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(fetch, item) for item in assets]):
            key, status = future.result()
            print(key, status, flush=True)
            if status.startswith("FAILED"):
                failures.append({"id": key, "error": status})
    (ROOT / "data/download-errors.json").write_text(json.dumps(failures, indent=2))
    print(f"Assets: {len(assets)}; failed: {len(failures)}")


if __name__ == "__main__":
    main()
