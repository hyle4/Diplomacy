"""Recover known public file names when the old catalog pages fail."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen
import json

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = {
    2015: [
        ("154IRBRDIPLOMATA2015_001_01.PDF", "exam", "Prova objetiva – manhã"),
        ("154IRBRDIPLOMATA2015_001_05.PDF", "exam", "Prova objetiva – tarde"),
        ("Gab_Definitivo_154IRBRDIPLOMATA2015_001_01.PDF", "key", "Gabarito definitivo – manhã"),
        ("Gab_Definitivo_154IRBRDIPLOMATA2015_001_05.PDF", "key", "Gabarito definitivo – tarde"),
        ("179IRBRDIPLOMATA2015_DISC_01.pdf", "exam", "Prova escrita de Língua Portuguesa"),
        ("181IRBRDIPL3aFASE_005NDDIP_01.pdf", "exam", "Prova escrita de Direito"),
        ("181IRBRDIPL3aFASE_001LI_01.pdf", "exam", "Prova escrita de Língua Inglesa"),
        ("181IRBRDIPL3aFASE_002HB_01.pdf", "exam", "Prova escrita de História do Brasil"),
        ("181IRBRDIPL3aFASE_003PIG_01.pdf", "exam", "Prova escrita de Política Internacional e Geografia"),
        ("181IRBRDIPL3aFASE_004NE_01.pdf", "exam", "Prova escrita de Economia"),
        ("181IRBRDIPL3aFASE_006LELF_01.pdf", "exam", "Terceira fase – Prova de Língua Espanhola e Língua Francesa"),
        ("Gab_Definitivo_181IRBRDIPL3aFASE_006LELF_01.pdf", "key", "Gabarito definitivo – Terceira fase – Espanhol e Francês"),
    ],
    2016: [
        ("263_IRBR_DIPL_1F_001_01.PDF", "exam", "Prova objetiva – manhã"),
        ("263_IRBR_DIPL_1F_002_01.PDF", "exam", "Prova objetiva – tarde"),
        ("Gab_Definitivo_263_IRBR_DIPL_1F_001_01.PDF", "key", "Gabarito definitivo – manhã"),
        ("Gab_Definitivo_263_IRBR_DIPL_1F_002_01.PDF", "key", "Gabarito definitivo – tarde"),
        ("264_IRBR_DISC_001_01.PDF", "exam", "Prova escrita de Língua Portuguesa"),
        ("265_IRBR_DISC_001_01.PDF", "exam", "Prova escrita de Língua Inglesa"),
        ("265_IRBR_DISC_002_01.PDF", "exam", "Prova escrita de História do Brasil"),
        ("266_IRBR_DISC_001_01.PDF", "exam", "Prova escrita de Política Internacional e Geografia"),
        ("266_IRBR_DISC_002_01.PDF", "exam", "Prova escrita de Economia"),
        ("267_IRBR_DISC_001_01.PDF", "exam", "Prova escrita de Direito"),
        ("267_IRBR_002_01.PDF", "exam", "Terceira fase – Prova de Língua Espanhola e Língua Francesa"),
        ("Gab_Definitivo_267_IRBR_002_01.PDF", "key", "Gabarito definitivo – Terceira fase – Espanhol e Francês"),
    ],
}


def retrieve(task):
    year, name, kind, title = task
    url = f"https://cdn.cebraspe.org.br/concursos/IRBR_{year%100:02}_DIPLOMACIA/arquivos/{name}"
    key = sha256(url.encode()).hexdigest()[:12]
    path = f"data/downloads/{year}/{key}.pdf"
    try:
        with urlopen(Request(url, headers={"User-Agent": "Diplomacy local study archive"}), timeout=30) as response:
            data = response.read()
        if not data.startswith(b"%PDF"):
            raise ValueError("not a PDF")
        dest = ROOT / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dest.with_suffix(".pdf.json").write_text(json.dumps({"url": url, "sha256": sha256(data).hexdigest(), "bytes": len(data)}))
        return {"id": f"{year}-{key}", "year": year, "role": kind, "title": title,
                "url": url, "authority": "official", "path": path, "final": kind == "key"}
    except Exception as exc:
        print(year, name, str(exc), flush=True)
        return None


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=3) as pool:
        found = [x for x in pool.map(retrieve, [(year, *entry) for year, entries in CANDIDATES.items() for entry in entries]) if x]
    (ROOT / "sources-extra.json").write_text(json.dumps(found, ensure_ascii=False, indent=2))
    print("Recovered", len(found), "official files")
