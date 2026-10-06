"""Build a portable inventory from public organizer catalogs."""
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.active = None
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.active = [dict(attrs).get("href", ""), []]
    def handle_data(self, data):
        if self.active:
            self.active[1].append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.active:
            url, parts = self.active
            self.links.append((url, " ".join(" ".join(parts).split())))
            self.active = None


def role(label):
    s = label.lower()
    if any(x in s for x in ["comunicado", "resultado", "consulta", "edital", "relação", "formulário", "comprovante", "locais"]):
        return None
    if "padrão" in s or "padrões" in s:
        return "rubric"
    if "gabarito" in s:
        return "key_notice" if "justificativa" in s else "key"
    if any(x in s for x in ["caderno", "prova objetiva", "prova escrita", "provas escritas", "prova discursiva", "prova de "]):
        return "exam"
    return None


def main():
    assets = []
    for path in sorted((ROOT / "data/catalogs").glob("*")):
        if not path.stem.isdigit() or not path.stat().st_size:
            continue
        year = int(path.stem)
        rows = []
        if path.suffix == ".json":
            data = json.loads(path.read_text())
            for entry in (data.get("arquivosGabarito") or []) + (data.get("arquivosEdital") or []):
                rows.append((f"https://cdn.cebraspe.org.br/concursos/IRBR_{year%100:02}_DIPLOMACIA/arquivos/{entry['nomeArquivo']}", entry["descricaoArquivo"]))
        elif year in [2019, 2020, 2022, 2023]:
            parser = Links()
            parser.feed(path.read_text(errors="replace"))
            rows = [(urljoin("https://www.iades.com.br/inscricao/", u), re.sub(r"^\d\d/\d\d/\d{4}\s*-\s*", "", label)) for u, label in parser.links]
        for url, label in rows:
            kind = role(label)
            if not kind or not re.search(r"\.(pdf|zip)$", url, re.I):
                continue
            key = hashlib.sha256(url.encode()).hexdigest()[:12]
            assets.append({"id": f"{year}-{key}", "year": year, "role": kind,
                           "title": label, "url": url, "authority": "official",
                           "path": f"data/downloads/{year}/{key}{Path(url).suffix.lower()}",
                           "final": any(x in label.lower() for x in ["definitiv", "final", "retificado"])})
    extra = ROOT / "sources-extra.json"
    if extra.exists():
        assets.extend(json.loads(extra.read_text()))
    assets = list({asset["url"]: asset for asset in assets}.values())
    payload = {"schema_version": 1, "calendar_years": list(range(2015, 2027)),
               "edition_notes": {"2020": "Aplicação em 2021", "2021": "Provas da edição 2020"}, "assets": assets}
    (ROOT / "sources.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    for year in range(2015, 2027):
        batch = [x for x in assets if x["year"] == year]
        print(year, {role: sum(x["role"] == role for x in batch) for role in ["exam", "key", "rubric", "key_notice"]})


if __name__ == "__main__":
    main()
