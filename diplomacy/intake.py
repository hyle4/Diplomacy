"""Conservative, reproducible transcription of the official CACD layouts.

Original pages remain authoritative. No question or answer is generated.
Only the canonical Tipo A is transcribed; every variant remains in the archive.
"""
import re
import subprocess
import unicodedata
from pathlib import Path

from vengine.exam import ExamBundle, ExamQuestion


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower())
                   if not unicodedata.combining(c))


def pdf_files(path):
    files = sorted(path.with_suffix('').glob('*.pdf')) if path.suffix == '.zip' else [path]
    return [p for p in files if not p.name.startswith('._') and p.read_bytes().startswith(b'%PDF')]


def parse_key_text(text):
    """Match complete visual grid rows; reject missing/duplicate/conflicting cells."""
    iades = 'Prova Tipo' in text
    active = not iades
    result = {}
    for page, body in enumerate(text.split('\f'), 1):
        pending = []
        grouped = True
        for line in body.splitlines():
            variant = re.search(r'Prova Tipo\s*[“"\']?([A-D])', line)
            if variant:
                active = variant[1] == 'A'
                pending = []
            if not active:
                continue
            groups = re.findall(r'Questão\s*(\d+)', line, re.I)
            if groups:
                pending = list(map(int, groups))
                grouped = True
                continue
            if re.match(r'\s*Item\s+\d', line, re.I):
                pending = list(map(int, re.findall(r'\d+', line)))
                grouped = False
                continue
            values = re.sub(r'^\s*Gabarito\s+', '', line, flags=re.I).strip().split()
            while values and values[-1] == '0':
                values.pop()
            if pending and values and all(x in {'C', 'E', 'X', '#'} for x in values):
                if len(values) != len(pending) * (4 if grouped else 1):
                    raise ValueError(f'Incomplete answer row on page {page}')
                for index, value in enumerate(values):
                    label = f'{pending[index // 4]}.{index % 4 + 1}' if grouped else str(pending[index])
                    if label in result:
                        raise ValueError(f'Duplicate answer cell {label}')
                    # IADES uses # for annulment; its legend X denotes changed ink,
                    # never accept X as an IADES cell without a checked definition.
                    if iades and value == 'X':
                        raise ValueError('Unexpected IADES X cell; inspect original')
                    result[label] = {'value': 'X' if value == '#' else value, 'page': page}
                pending = []
        if pending:
            raise ValueError(f'Unfinished answer row on page {page}')
    if not result:
        raise ValueError('No complete official key grid found')
    return result


def read_key(path):
    text = subprocess.check_output(['pdftotext', '-layout', str(path), '-'], timeout=60).decode()
    return parse_key_text(text)


def clean_page(raw):
    lines = []
    for line in raw.replace('\r', '').splitlines():
        stripped = line.strip()
        if (re.search(r'CE[BS]RASPE|CESPE|Cespe|Cebraspe', stripped)
                or stripped.startswith('||') or stripped == 'PROVA APLICADA'
                or re.match(r'CONCURSO PÚBLICO.*PÁGINA', stripped)
                or re.match(r'^PÁGINA \d+/', stripped)):
            continue
        lines.append(stripped)
    return '\n'.join(lines)


def objective(document, answers, title):
    pages = [clean_page('\n'.join(b.text for b in p.blocks)) for p in document.pages]
    starts, body = [], ''
    for number, page in enumerate(pages, 1):
        starts.append((len(body), number))
        body += page + '\n'

    def page_at(offset):
        return next(p for start, p in reversed(starts) if start <= offset)

    grouped = any('.' in key for key in answers)
    pattern = r'(?im)^\s*QUESTÃO\s+(\d+)\b' if grouped else r'(?m)^(\d{1,3})[ \t]+(?=\S)'
    candidates = list(re.finditer(pattern, body))
    expected = sorted({int(x.split('.')[0]) for x in answers})
    headings, next_index = [], 0
    for match in candidates:
        if next_index < len(expected) and int(match[1]) == expected[next_index]:
            headings.append(match)
            next_index += 1
    if len(headings) != len(expected):
        raise ValueError(f'Question headings: {len(headings)}/{len(expected)}; missing {expected[next_index:]}')
    questions, details = [], {}
    last_text_page = 1
    for i, heading in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
        section = body[heading.end():end].strip()
        number = int(heading[1])
        source_page = page_at(heading.start())
        issues = []
        if grouped:
            items = list(re.finditer(r'(?m)^([1-4])[ \t]+(?=\S)', section))
            sequences = [items[j:j+4] for j in range(len(items)-3)
                         if [int(m[1]) for m in items[j:j+4]] == [1, 2, 3, 4]]
            if not sequences:
                raise ValueError(f'No complete 1–4 assertion sequence in question {number}')
            selected = sequences[-1]
            stem = section[:selected[0].start()].strip()
            if len(sequences) != 1:
                issues.append('Conferir os limites dos itens na página original.')
            for j, match in enumerate(selected):
                stop = selected[j+1].start() if j < 3 else len(section)
                assertion = section[match.end():stop].strip()
                # Explicit following passage/subject markers do not belong to item 4.
                boundary = re.search(r'(?im)^(?:Texto\s+[IVX\d]|Text\s+[IVX\d]|Espaço livre|LÍNGUA [A-ZÁÉÍÓÚ ]+|HISTÓRIA [A-Z ]+|POLÍTICA INTERNACIONAL|NOÇÕES DE|ECONOMIA|DIREITO)\b', assertion)
                if boundary:
                    assertion = assertion[:boundary.start()].strip()
                label = f'{number}.{j+1}'
                prompt = (stem + '\n\n' + assertion).strip()
                item_page = page_at(heading.end() + section.find(assertion)) if assertion else source_page
                questions.append(ExamQuestion(number=number, item=j+1, page=source_page,
                                 prompt=prompt, answer=answers[label]['value']))
                details[label] = {'page': source_page, 'item_page': item_page,
                                  'context_page': last_text_page, 'issues': issues}
        else:
            label = str(number)
            # The page is always shown with its governing text/command. A new
            # command after a statement is retained for source review, never guessed away.
            questions.append(ExamQuestion(number=number, page=source_page, prompt=section,
                             options={'C': 'Certo', 'E': 'Errado'},
                             answer=answers[label]['value'] if answers[label]['value'] != 'X' else None))
            details[label] = {'page': source_page, 'item_page': source_page,
                              'context_page': max(1, source_page-1), 'issues': issues}
        if len(section) > 1600:
            last_text_page = source_page
    return ExamBundle(title=title, questions=questions), details


def written(document, title):
    """One source-linked exercise per prompt page; skip blank ruled draft pages.

    Do not try to split continuous essays/translations by guessed line numbers.
    All pages remain reachable in the original reader.
    """
    questions, details = [], {}
    for p in document.pages:
        text = clean_page('\n'.join(b.text for b in p.blocks))
        prose = re.sub(r'\b\d+\b|RASCUNHO|QUESTÃO|REDAÇÃO|RESUMO|TRANSLATION|COMPOSITION|SUMMARY|DRAFT|TRADUÇÃO', '', text, flags=re.I)
        if len(re.findall(r'[A-Za-zÀ-ÿ]{3,}', prose)) < 40:
            continue
        if p.number == 1 and ('INSTRUÇÕES' in text or 'INSTRUÇÕES GERAIS' in text) and len(document.pages) > 3:
            continue
        label = str(p.number)
        questions.append(ExamQuestion(number=p.number, page=p.number, prompt=text))
        details[label] = {'page': p.number, 'item_page': p.number,
                          'context_page': max(1, p.number-1), 'issues': []}
    if not questions:
        raise ValueError('No written prompt pages found')
    return ExamBundle(title=title, questions=questions), details
