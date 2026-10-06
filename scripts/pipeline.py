"""Run after download.py. Uses only the public V-engine intake and Store APIs."""
import fcntl
import hashlib
import json
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from diplomacy.intake import fold, objective, pdf_files, read_key, written
from vengine.documents import parse
from vengine.exam import ingest_structured
from vengine.models import ContentBlock, PassageRevision, SourceRef
from vengine.store import Store


def write_json(path, payload):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def subject(text):
    text = fold(text)
    for needle, name in [('portugues', 'Língua Portuguesa'), ('ingles', 'Língua Inglesa'),
                         ('historia', 'História do Brasil'), ('geografia', 'Geografia'),
                         ('politica', 'Política Internacional'), ('economia', 'Economia'),
                         ('direito', 'Direito'), ('espanhol', 'Espanhol e Francês'),
                         ('frances', 'Espanhol e Francês')]:
        if needle in text:
            return name
    return 'Prova escrita'


def main():
    data = ROOT / 'data'
    data.mkdir(exist_ok=True)
    lock = (data / 'pipeline.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    store = Store(data)
    stage = data / 'staging'
    stage.mkdir(exist_ok=True)
    assets = json.loads((ROOT / 'sources.json').read_text())['assets']
    archive, booklets, failures = [], [], []
    keys = {}
    for asset in assets:
        path = ROOT / asset['path']
        receipt = json.loads(path.with_suffix(path.suffix + '.json').read_text())
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt['sha256']:
            raise ValueError(f'Checksum failed: {asset["id"]}')
        for file in pdf_files(path):
            src = store.add_source(file, 'application/pdf', file.name if path.suffix == '.zip' else Path(asset['url']).name)
            archive.append({**asset, 'source_id': src['id'], 'filename': src['name'], 'sha256': src['sha256']})
        if asset['role'] == 'key' and asset['final']:
            if any(t in fold(asset['title']) for t in ('adaptada', 'especial')):
                continue
            try:
                keys[asset['id']] = read_key(path)
            except Exception as exc:
                failures.append({'asset_id': asset['id'], 'filename': path.name, 'error': str(exc)})
                print(f'REVIEW key {asset["id"]}: {exc}', flush=True)
    for asset in assets:
        if asset['role'] != 'exam':
            continue
        title_lower = fold(asset['title'])
        if any(t in title_lower for t in ('adaptada', 'especial')):
            continue
        for file in pdf_files(ROOT / asset['path']):
            if 'tipo' in fold(file.name) and not ('tipo a' in fold(file.name)):
                continue
            source = store.add_source(file, 'application/pdf')
            document = store.document(source['id'])
            if document is None:
                document = parse(file, source['id'], file.name)
                store.save_document(document)
            objective_mode = 'objetiva' in title_lower or (asset['year'] <= 2016 and 'espanhola' in title_lower)
            period = 'Tarde' if 'tarde' in title_lower or '35 a 73' in title_lower else 'Manhã'
            key_asset, cells = None, {}
            if objective_mode:
                language = 'espanhola' in title_lower
                candidates = [a for a in assets if a['year'] == asset['year'] and a['id'] in keys]
                if asset['year'] not in (2019, 2020, 2022, 2023):
                    candidates = [a for a in candidates if (('espanhol' in fold(a['title'])) == language)
                                  and (language or (('tarde' in fold(a['title']) or '35 a 73' in fold(a['title'])) == (period == 'Tarde')))]
                if len(candidates) != 1:
                    raise ValueError(f'Ambiguous final key for {asset["id"]}: {len(candidates)}')
                key_asset = candidates[0]
                cells = dict(keys[key_asset['id']])
                if asset['year'] in (2019, 2020, 2022, 2023):
                    split = 35 if asset['year'] == 2023 else 34
                    cells = {k: v for k, v in cells.items() if (int(k.split('.')[0]) <= split) == (period == 'Manhã')}
                short = 'Espanhol e Francês' if language else f'Objetiva · {period}'
            else:
                short = subject(file.name if (ROOT / asset['path']).suffix == '.zip' else asset['title'])
            title = f'CACD {asset["year"]} · {short}'
            try:
                bundle, details = objective(document, cells, title) if objective_mode else written(document, title)
                stage_path = stage / f'{source["sha256"]}.json'
                stage_path.write_text(bundle.model_dump_json(indent=2) + '\n')
                result = ingest_structured(store, stage_path, file, subject='CACD')
                collection_id = result['collection_id']
                key_source = store.add_source(ROOT / key_asset['path'], 'application/pdf') if key_asset else None
                if key_source and store.document(key_source['id']) is None:
                    store.save_document(parse(ROOT / key_asset['path'], key_source['id']))
                latest = []
                while True:
                    page = store.list_exercises(collection_id=collection_id, limit=500, offset=len(latest))
                    latest.extend(page)
                    if len(page) < 500:
                        break
                for item in latest:
                    info = details[item.label]
                    answer = cells.get(item.label)
                    page = info['page']
                    ref = SourceRef(source_id=source['id'], page=page)
                    passage_id = uuid5(NAMESPACE_URL, f'diplomacy:page:{source["sha256"]}:{page}').hex
                    passage = store.latest_passage(passage_id)
                    if passage is None:
                        passage = PassageRevision(passage_id=passage_id, collection_id=collection_id,
                                      title=f'Página {page}', blocks=[ContentBlock(kind='image', source=ref)],
                                      sources=[ref], status='needs_review')
                        store.save_passage(passage)
                    meta = {'year': asset['year'], 'asset_id': asset['id'], 'type': 'objective' if objective_mode else 'written',
                            'subject': short, 'source_pages': len(document.pages),
                            'page': page, 'context_page': info['context_page'],
                            'annulled': bool(answer and answer['value'] == 'X'),
                            'boolean_labels': {'true': 'Certo', 'false': 'Errado'},
                            'key_asset': key_asset['id'] if key_asset else None,
                            'transcription_version': 1}
                    updates = {'title': f'Item {item.label}' if objective_mode else f'Página {page}',
                               'language': 'pt-BR', 'metadata': meta, 'contexts': passage.blocks,
                               'passage_id': passage_id, 'passage_revision_id': passage.id,
                               'review_notes': ['Confira o enunciado, o texto de apoio e o gabarito nas páginas originais.', *info['issues']]}
                    if answer:
                        updates['answer_origin'] = 'official'
                        updates['answer_source'] = SourceRef(source_id=key_source['id'], page=answer['page'],
                            quote=f'Questão/item {item.label}; caderno canônico; gabarito definitivo').model_dump()
                        if answer['value'] == 'X':
                            updates['review_notes'].append('Item anulado no gabarito definitivo; excluído da prática pontuada.')
                    if item.metadata != meta:
                        store.revise(item.exercise_id, updates)
                row = {'id': collection_id, 'year': asset['year'], 'title': short, 'type': 'objective' if objective_mode else 'written',
                       'source_id': source['id'], 'pages': len(document.pages), 'count': len(latest),
                       'annulled': sum(v['value'] == 'X' for v in cells.values()),
                       'expected': len(cells) if objective_mode else None,
                       'key_source_id': key_source['id'] if key_source else None, 'asset_id': asset['id']}
                booklets.append(row)
                if objective_mode and len(latest) != len(cells):
                    failures.append({'asset_id': asset['id'], 'filename': file.name,
                                     'error': f'Item count {len(latest)} != key cells {len(cells)}'})
                print(f'{title}: {len(latest)}; anulados {row["annulled"]}', flush=True)
            except Exception as exc:
                failures.append({'asset_id': asset['id'], 'filename': file.name, 'error': str(exc)})
                print(f'REVIEW {title}: {exc}', flush=True)
    write_json(data / 'archive.json', archive)
    write_json(data / 'booklets.json', booklets)
    report = {'years': list(range(2015, 2027)), 'edition_notes': {'2020': 'Aplicação em 2021', '2021': 'Edição 2020; sem edição própria'},
              'download_assets': len(assets), 'pdf_files': len(archive), 'booklets': len(booklets),
              'objective_items': sum(b['count'] for b in booklets if b['type'] == 'objective'),
              'written_pages': sum(b['count'] for b in booklets if b['type'] == 'written'),
              'annulled': sum(b['annulled'] for b in booklets), 'failures': failures,
              'approval': 'A revisão e a aprovação são feitas pelo usuário na interface.',
              'by_year': {str(year): {'booklets': sum(b['year'] == year for b in booklets),
                          'pdf_files': sum(a['year'] == year for a in archive),
                          'objective_items': sum(b['count'] for b in booklets if b['year'] == year and b['type'] == 'objective')}
                          for year in range(2015, 2027)}}
    write_json(data / 'coverage.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('by_year', 'years', 'edition_notes')}, ensure_ascii=False))
    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
