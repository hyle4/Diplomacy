"""Retrieve public organizer catalogs; keep raw responses for reproducibility."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
import json

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "catalogs"
CEBRASPE_YEARS = [2015, 2016, 2017, 2018, 2024, 2025, 2026]
IADES = {2019: "dd54c0a4", 2020: "9b8989ec", 2022: "cd453c3f", 2023: "4a392209"}


def fetch(job):
    name, url = job
    path = CATALOG / name
    try:
        if not path.exists() or not path.stat().st_size:
            with urlopen(Request(url, headers={"User-Agent": "Diplomacy local study archive"}), timeout=45) as response:
                data = response.read()
            path.write_bytes(data)
        return {"file": name, "url": url, "bytes": path.stat().st_size}
    except Exception as exc:
        return {"file": name, "url": url, "error": str(exc)}


def main():
    CATALOG.mkdir(parents=True, exist_ok=True)
    jobs = []
    for year in CEBRASPE_YEARS:
        slug = f"IRBR_{year % 100:02}_DIPLOMACIA"
        jobs.append((f"{year}.json", f"https://apis.cebraspe.org.br/cebraspe/eventos/{slug}"))
        if year < 2019:
            jobs.append((f"{year}.html", f"https://cdn.cebraspe.org.br/concursos/{slug.lower() if year < 2017 else slug}/"))
    for year, code in IADES.items():
        jobs.append((f"{year}.html", f"https://www.iades.com.br/inscricao/ProcessoSeletivo.aspx?id={code}"))
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(fetch, jobs):
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
