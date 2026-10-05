#!/usr/bin/env python3
"""Daily Scholar tracker and GitHub Pages builder. Python standard library only."""
from __future__ import annotations
import argparse
import copy
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parent


class TrackerError(Exception):
    pass


class BudgetExceeded(TrackerError):
    pass


def normalized(s):
    s = unicodedata.normalize('NFKC', s or '').casefold()
    s = re.sub(r'^\s*\[(?:pdf|html|citation)\]\s*', '', s)
    return ''.join(c for c in s if c.isalnum())


def safe_url(url):
    p = urllib.parse.urlsplit(url or '')
    return url if p.scheme in ('http', 'https') and p.netloc else ''


def author_id(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get('user', [''])[0]


def cites_id(cited_by):
    for field in ('link', 'serpapi_link'):
        value = urllib.parse.parse_qs(urllib.parse.urlsplit(cited_by.get(field, '')).query).get('cites', [''])[0]
        if re.fullmatch(r'\d+(?:,\d+)*', value):
            return value
    return ''


def work_key(title):
    # Same work may appear under several Scholar versions/URLs.
    return hashlib.sha256(normalized(title).encode()).hexdigest()[:24]


def json_get(url, params=None, headers=None, label='API'):
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        # Never print response bodies, request URLs or tokens.
        raise TrackerError(f'{label}: HTTP {exc.code}（检查密钥、额度或稍后重试）') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise TrackerError(f'{label}: 网络连接失败，稍后重试') from None
    except (ValueError, TypeError):
        raise TrackerError(f'{label}: 返回格式异常') from None
    if not isinstance(data, dict):
        raise TrackerError(f'{label}: 返回格式异常')
    if data.get('error'):
        raise TrackerError(f'{label}: 请求未成功（检查密钥及额度）')
    return data


class Config:
    def __init__(self):
        settings = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
        self.scholar_url = (os.getenv('SCHOLAR_URL') or settings.get('scholar_url', '')).strip()
        self.author_id = author_id(self.scholar_url)
        self.serp_key = os.getenv('SERPAPI_KEY', '').strip()
        self.openalex_key = os.getenv('OPENALEX_API_KEY', '').strip()
        self.zone = ZoneInfo(settings.get('timezone', 'Asia/Hong_Kong'))
        self.pages = int(settings.get('max_cited_pages_per_paper', 2))
        self.serp_budget = int(settings.get('max_serp_requests_per_day', 6))
        self.oa_budget = int(settings.get('max_openalex_requests_per_day', 40))
        self.reconcile_days = int(settings.get('reconcile_days', 7))
        self.data_dir = Path(os.getenv('DATA_DIR', str(ROOT / 'data')))
        for value in (self.pages, self.serp_budget, self.reconcile_days):
            if value < 1:
                raise TrackerError('分页、SerpApi 上限、复查间隔必须为正整数')
        if self.oa_budget < 0:
            raise TrackerError('OpenAlex 上限不能为负数')

    def missing(self):
        return ([ 'SCHOLAR_URL（须包含 user=）' ] if not self.author_id else []) + ([ 'SERPAPI_KEY' ] if not self.serp_key else [])


def blank_state(cfg):
    return {'schema': 1, 'author_id': cfg.author_id, 'profile': {}, 'papers': {},
            'works': {}, 'edges': {}, 'history': [], 'last_update': '',
            'usage': {}, 'warnings': []}


def validate_state(data, cfg):
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise TrackerError('存储数据格式不支持；不会覆盖已有文件')
    for key, typ in [('papers', dict), ('works', dict), ('edges', dict), ('history', list), ('usage', dict)]:
        if not isinstance(data.get(key), typ):
            raise TrackerError('存储数据不完整；不会覆盖已有文件')
    if data.get('author_id') != cfg.author_id:
        raise TrackerError('SCHOLAR_URL 与已有数据作者不同。请先备份并移走 data/state.json，再更换作者')
    return data


class Store:
    """Atomic local canonical state, committed to Git by the daily workflow."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.local_file = cfg.data_dir / 'state.json'

    def load(self):
        if not self.local_file.exists():
            return blank_state(self.cfg)
        try:
            return validate_state(json.loads(self.local_file.read_text(encoding='utf-8')), self.cfg)
        except (ValueError, OSError):
            raise TrackerError('数据读取失败；不会覆盖已有文件') from None

    def save(self, state):
        self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
        temp = self.local_file.with_suffix('.tmp')
        try:
            temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temp.replace(self.local_file)
        except OSError:
            raise TrackerError('数据保存失败') from None


class Sources:
    def __init__(self, cfg, state, day):
        self.cfg = cfg
        self.usage = state['usage'].setdefault(day, {'serpapi': 0, 'openalex': 0})
        self.usage['serp_limit'] = max(self.cfg.serp_budget, self.usage.get('serp_limit', 0))

    def serp(self, params):
        if self.usage['serpapi'] >= self.cfg.serp_budget:
            raise BudgetExceeded('已达当天 SerpApi 请求上限，剩余任务下次继续')
        self.usage['serpapi'] += 1
        return json_get('https://serpapi.com/search.json',
                        {**params, 'api_key': self.cfg.serp_key, 'hl': 'en'}, label='SerpApi')

    def profile(self):
        papers, profile, start = {}, {}, 0
        # Author list must complete before replacing the tracked paper list.
        while True:
            data = self.serp({'engine': 'google_scholar_author', 'author_id': self.cfg.author_id,
                              'start': start, 'num': 100, 'sort': 'citedby'})
            if start == 0:
                table = (data.get('cited_by') or {}).get('table') or []
                metrics = {}
                for row in table:
                    for name, values in row.items():
                        if isinstance(values, dict):
                            metrics[name] = values.get('all', 0)
                profile = {'name': (data.get('author') or {}).get('name', ''),
                           'metrics': metrics, 'url': self.cfg.scholar_url}
            rows = data.get('articles')
            if rows is None:
                raise TrackerError('SerpApi 未返回作者论文列表，稍后重试')
            fresh = 0
            for row in rows:
                pid = row.get('citation_id')
                if not pid:
                    continue
                if pid not in papers:
                    fresh += 1
                cb = row.get('cited_by') or {}
                papers[pid] = {'id': pid, 'title': row.get('title', ''), 'year': str(row.get('year', '')),
                               'authors': row.get('authors', ''), 'venue': row.get('publication', ''),
                               'citations': int(cb.get('value', 0) or 0), 'cites_id': cites_id(cb),
                               'url': safe_url(row.get('link', ''))}
            has_next = bool((data.get('serpapi_pagination') or {}).get('next'))
            if has_next and (not rows or not fresh):
                raise TrackerError('作者论文分页未完整返回；保留原有论文列表')
            if not has_next:
                break
            start += len(rows)
        return profile, papers

    def citing_page(self, cid, start):
        data = self.serp({'engine': 'google_scholar', 'cites': cid, 'start': start, 'num': 10})
        rows = data.get('organic_results', [])
        if not isinstance(rows, list):
            raise TrackerError('Scholar 详情格式异常，保留待查任务')
        if not rows and int((data.get('search_information') or {}).get('total_results', 0) or 0) > 0:
            raise TrackerError('Scholar 详情暂未返回，保留待查任务')
        return rows, bool((data.get('serpapi_pagination') or {}).get('next'))

    def oa(self, path, params=None):
        if self.usage['openalex'] >= self.cfg.oa_budget:
            raise BudgetExceeded('已达当天 OpenAlex 请求上限，单位信息下次继续补全')
        self.usage['openalex'] += 1
        headers = {'Authorization': 'Bearer ' + self.cfg.openalex_key} if self.cfg.openalex_key else {}
        return json_get('https://api.openalex.org/' + path, params, headers, 'OpenAlex')

    def enrich(self, work):
        doi = extract_doi(work.get('url', ''))
        if doi:
            try:
                item = self.oa('works/' + urllib.parse.quote('https://doi.org/' + doi, safe=':/'))
            except TrackerError as exc:
                if 'HTTP 404' not in str(exc):
                    raise
            else:
                if normalized(item.get('title')) == normalized(work['title']):
                    return metadata(item, 'DOI + exact title')
        query = re.sub(r'[^\w\s]', ' ', work['title'], flags=re.UNICODE)
        items = self.oa('works', {'search': query, 'per_page': 5}).get('results', [])
        candidates = [item for item in items if match_work(work, item)]
        if len(candidates) == 1:
            return metadata(candidates[0], 'exact title + author + year')
        return {'metadata_status': 'ambiguous' if candidates else 'unmatched', 'metadata_source': ''}


def extract_doi(url):
    match = re.search(r'10\.\d{4,9}/[^?#\s]+', urllib.parse.unquote(url or ''), re.I)
    return match.group(0).rstrip('.,;)').lower() if match else ''


def match_work(work, item):
    if normalized(work['title']) != normalized(item.get('title')):
        return False
    if work.get('year') and str(item.get('publication_year', '')) != str(work['year']):
        return False
    # Do not use title similarity alone to assign an institution.
    raw = work.get('authors_text', '').split(',')[0].replace('…', '').strip()
    parts = re.findall(r'[^\W\d_]+', raw, re.UNICODE)
    if not parts:
        return False
    surname = normalized(parts[-1])
    names = [(a.get('author') or {}).get('display_name', '') for a in item.get('authorships', [])]
    return any(surname in [normalized(p) for p in re.findall(r'[^\W\d_]+', name)] for name in names)


def metadata(item, match):
    authors = []
    for a in item.get('authorships', []):
        inst = [{'id': i.get('id', ''), 'name': i.get('display_name', ''),
                 'country': i.get('country_code', '')} for i in a.get('institutions', [])]
        authors.append({'name': (a.get('author') or {}).get('display_name', ''), 'institutions': inst,
                        'raw_affiliations': a.get('raw_affiliation_strings') or []})
    source = ((item.get('primary_location') or {}).get('source') or {}).get('display_name', '')
    return {'metadata_status': 'matched', 'metadata_source': 'OpenAlex', 'match_method': match,
            'openalex_id': item.get('id', ''), 'doi': item.get('doi', ''),
            'publication_date': item.get('publication_date', ''), 'authors': authors,
            'openalex_venue': source, 'openalex_url': safe_url(item.get('id', ''))}


def parse_citing(row):
    title = re.sub(r'^\s*\[(?:PDF|HTML|CITATION)\]\s*', '', row.get('title', ''), flags=re.I).strip()
    if not title:
        return None
    info = row.get('publication_info') or {}
    summary = info.get('summary', '')
    year_match = re.search(r'\b(?:19|20)\d{2}\b', summary)
    names = ', '.join(a.get('name', '') for a in info.get('authors', []) if a.get('name'))
    return {'id': work_key(title), 'title': title, 'url': safe_url(row.get('link', '')),
            'authors_text': names or summary.split(' - ')[0], 'scholar_summary': summary,
            'year': year_match.group(0) if year_match else '', 'metadata_status': 'pending',
            'authors': [], 'source': 'Google Scholar Cited By'}


def update_state(cfg, state, now, source_class=Sources):
    """Mutate a copy; caller only publishes after durable commit succeeds."""
    day = now.date().isoformat()
    source = source_class(cfg, state, day)
    warnings = []
    profile, current = source.profile()
    state['profile'] = profile
    previous = next((h for h in reversed(state['history']) if h['date'] < day), None)
    old_papers = state['papers']
    for paper in old_papers.values():
        paper['in_current_profile'] = False
    for pid, fresh in current.items():
        old = old_papers.get(pid)
        p = old if old is not None else {'baseline_done': False, 'scan_cursor': 0, 'scan_count': None,
                                        'last_full_scan': '', 'needs_scan': True}
        changed = old is not None and fresh['citations'] != old['citations']
        reference = (previous or {}).get('papers', {}).get(pid)
        p['delta'] = fresh['citations'] - reference if reference is not None else 0
        p.update(fresh)
        p['in_current_profile'] = True
        p['needs_scan'] = p['needs_scan'] or changed
        old_papers[pid] = p
    # Resume pending scans first. Weekly reconciliation catches net-zero changes.
    ordered = sorted(current, key=lambda pid: (old_papers[pid].get('last_scan_attempt', ''),
                     not bool(old_papers[pid].get('delta')), pid))
    for pid in ordered:
        p = old_papers[pid]
        last = p.get('last_full_scan')
        overdue = not last or (now.date() - datetime.fromisoformat(last).date()).days >= cfg.reconcile_days
        if not (p['needs_scan'] or overdue):
            continue
        if not p['cites_id']:
            if p['citations'] > 0:
                warnings.append(p['title'] + '：Scholar 未提供 Cited By ID，详情待查')
                continue
            p.update(baseline_done=True, needs_scan=False, scan_count=0, last_full_scan=day)
            continue
        p.setdefault('scan_started_count', p['citations'])
        complete = False
        # Freeze baseline flag for this scan: all first-import results remain baseline.
        baseline = not p['baseline_done']
        for _ in range(cfg.pages):
            try:
                rows, has_next = source.citing_page(p['cites_id'], p['scan_cursor'])
            except BudgetExceeded as exc:
                warnings.append(str(exc))
                break
            except TrackerError as exc:
                p['last_scan_attempt'] = now.isoformat()
                warnings.append(p['title'] + '：' + str(exc))
                break
            p['last_scan_attempt'] = now.isoformat()
            # A positive count with an empty first page is an unresolved discovery.
            if not rows and p['scan_cursor'] == 0 and p['citations'] > 0:
                warnings.append(p['title'] + '：计数已更新，引用列表暂为空；下次重试')
                break
            for row in rows:
                work = parse_citing(row)
                if not work:
                    continue
                wid = work['id']
                if wid not in state['works']:
                    state['works'][wid] = work
                eid = pid + '|' + wid
                if eid not in state['edges']:
                    state['edges'][eid] = {'target_id': pid, 'work_id': wid, 'detected_at': now.isoformat(),
                                           'is_baseline': baseline, 'source': 'Google Scholar Cited By'}
            if not has_next:
                complete = True
                break
            p['scan_cursor'] += 10
        if complete:
            p.update(baseline_done=True, needs_scan=(p.get('scan_started_count', p['citations']) != p['citations']), scan_cursor=0,
                     scan_count=p['citations'], last_full_scan=day)
            p.pop('scan_started_count', None)
        else:
            p['needs_scan'] = True
            warnings.append(p['title'] + '：引用详情扫描尚未完成，下次继续；已有结果已保留')
    # Retry unavailable metadata after seven days; pending metadata resumes tomorrow.
    for work in sorted(state['works'].values(), key=lambda w: (w.get('metadata_attempt', ''), w['id'])):
        status = work.get('metadata_status', 'pending')
        last_try = work.get('metadata_attempt', '')
        if status == 'matched':
            continue
        if status != 'pending' and last_try and (now.date() - datetime.fromisoformat(last_try).date()).days < 7:
            continue
        try:
            work.update(source.enrich(work))
            work['metadata_attempt'] = day
        except BudgetExceeded as exc:
            warnings.append(str(exc))
            break
        except TrackerError as exc:
            work['metadata_status'] = 'unavailable'
            work['metadata_attempt'] = day
            warnings.append(str(exc))
    snapshot = {'date': day, 'total': profile.get('metrics', {}).get('citations',
                 sum(p['citations'] for p in current.values())),
                'papers': {pid: p['citations'] for pid, p in current.items()}}
    state['history'] = [h for h in state['history'] if h['date'] != day] + [snapshot]
    state['history'].sort(key=lambda x: x['date'])
    state['last_update'] = now.isoformat()
    state['warnings'] = list(dict.fromkeys(warnings))
    return state


def export_csv(state):
    output = io.StringIO()
    fields = ['detected_at', 'is_baseline', 'target_title', 'citing_title', 'year', 'authors',
              'author_affiliations_json', 'institutions', 'doi', 'url', 'source', 'metadata_status']
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    def excel_safe(value):
        text = str(value)
        return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text
    for edge in state['edges'].values():
        work = state['works'][edge['work_id']]
        authors = work.get('authors', [])
        institutions = sorted({i['name'] for a in authors for i in a.get('institutions', [])})
        row = {'detected_at': edge['detected_at'], 'is_baseline': edge['is_baseline'],
            'target_title': state['papers'][edge['target_id']]['title'], 'citing_title': work['title'],
            'year': work.get('year', ''), 'authors': '; '.join(a['name'] for a in authors) or work.get('authors_text', ''),
            'author_affiliations_json': json.dumps(authors, ensure_ascii=False),
            'institutions': '; '.join(institutions), 'doi': work.get('doi', ''), 'url': work.get('url', ''),
            'source': edge['source'], 'metadata_status': work.get('metadata_status', '')}
        writer.writerow({key: excel_safe(value) for key, value in row.items()})
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def public_view(cfg, state):
    view = copy.deepcopy(state)
    view['status'] = {'timezone': str(cfg.zone), 'serp_budget': cfg.serp_budget, 'oa_budget': cfg.oa_budget}
    return view


def build_site(cfg, state, output):
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'web' / 'index.html', output / 'index.html')
    (output / 'data.json').write_text(json.dumps(public_view(cfg, state), ensure_ascii=False) + '\n', encoding='utf-8')
    (output / 'citations.csv').write_bytes(export_csv(state))
    (output / '.nojekyll').touch()


def summary(state):
    day = state.get('last_update', '')[:10]
    new = [e for e in state['edges'].values() if not e['is_baseline'] and e['detected_at'][:10] == day]
    lines = ['# Citation update', '', f"Author: {state['profile'].get('name', 'Not initialized')}",
             f"Updated: {state.get('last_update') or 'Not initialized'}",
             f"Total citations: {state['profile'].get('metrics', {}).get('citations', 0)}",
             f'Newly detected citation relationships today: {len(new)}', '']
    for edge in new:
        work = state['works'][edge['work_id']]
        target = state['papers'][edge['target_id']]
        # Plain text within a code block avoids accidental Markdown interpretation.
        lines += ['```text', work['title'].replace('```', ''), 'Cites: ' + target['title'].replace('```', '')]
        for author in work.get('authors', []):
            lines.append((author['name'] + ' — ' + '; '.join(i['name'] for i in author.get('institutions', []))).replace('```', ''))
        if not work.get('authors'):
            lines.append(work.get('authors_text', '').replace('```', ''))
        lines += ['```', '']
    if state.get('warnings'):
        lines += ['## Pending tasks', ''] + ['- ' + w.replace('\n', ' ') for w in state['warnings']]
    return '\n'.join(lines) + '\n'


def load_env_file(path):
    """Read KEY=value without shell evaluation; never print credentials."""
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if sep and key.strip() in ('SERPAPI_KEY', 'OPENALEX_API_KEY', 'SCHOLAR_URL'):
            os.environ.setdefault(key.strip(), value.strip().strip('\"\''))


def run_update(cfg, store, now=None, source_class=Sources):
    state = store.load()
    candidate = copy.deepcopy(state)
    try:
        update_state(cfg, candidate, now or datetime.now(cfg.zone), source_class)
    except Exception:
        # Retain successful history and consumed quota when the profile API fails.
        state['usage'] = candidate['usage']
        store.save(state)
        raise
    store.save(candidate)
    return candidate


def update_or_reuse(cfg, store, now=None, source_class=Sources):
    """A local budget pause can publish an existing snapshot without a new fetch."""
    try:
        return run_update(cfg, store, now, source_class)
    except BudgetExceeded as exc:
        state = store.load()
        if not state.get('last_update'):
            raise
        # Deployment notice only: do not change the saved snapshot or its date.
        state['warnings'] = list(dict.fromkeys(state.get('warnings', []) + [
            str(exc) + '；本次发布已有快照，未刷新引用数据。'
        ]))
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-only', action='store_true', help='Build dashboard without API requests')
    parser.add_argument('--env-file', help='Local KEY=value secrets file; do not commit it')
    parser.add_argument('--output', type=Path, default=ROOT / 'site')
    args = parser.parse_args()
    try:
        if args.env_file:
            load_env_file(args.env_file)
        cfg = Config()
        store = Store(cfg)
        if args.build_only:
            state = store.load()
        else:
            if cfg.missing():
                raise TrackerError('尚未配置：' + '、'.join(cfg.missing()))
            state = update_or_reuse(cfg, store)
        build_site(cfg, state, args.output)
        report = summary(state)
        print(report)
        if os.getenv('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as file:
                file.write(report)
        return 0
    except TrackerError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print('运行失败；数据未重置。请检查配置、文件权限及 API 返回格式。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
