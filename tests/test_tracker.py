"""Offline behavioral regression tests. No credentials or outbound API calls."""
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import tracker as app


NOW = datetime.fromisoformat('2026-10-05T03:00:00+08:00')


def row(title, author='A Smith', year='2026', url='https://example.org/paper'):
    return {'title': title, 'link': url, 'publication_info': {'summary': f'{author} - Example Journal, {year}'}}


class MockSources:
    count = 1
    pages = {0: ([row('Citing Alpha')], False)}
    calls = []

    def __init__(self, cfg, state, day):
        self.usage = state['usage'].setdefault(day, {'serpapi': 0, 'openalex': 0})

    def profile(self):
        self.usage['serpapi'] += 1
        return {'name': 'Test Author', 'metrics': {'citations': self.count}}, {
            'target': {'id': 'target', 'title': 'Target Paper', 'year': '2026', 'authors': 'Test Author',
                       'venue': '', 'citations': self.count, 'cites_id': '123', 'url': ''}}

    def citing_page(self, cid, start):
        self.calls.append(start)
        value = self.pages[start]
        if isinstance(value, Exception):
            raise value
        self.usage['serpapi'] += 1
        return value

    def enrich(self, work):
        return {'metadata_status': 'unmatched'}


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'SCHOLAR_URL': 'https://scholar.google.com/citations?user=test',
            'SERPAPI_KEY': 'private-serp-secret',
            'OPENALEX_API_KEY': 'private-oa-secret',
            'DATA_DIR': self.temp.name}, clear=True)
        self.env.start()
        self.cfg = app.Config()
        self.cfg.pages = 10
        MockSources.count = 1
        MockSources.pages = {0: ([row('Citing Alpha')], False)}
        MockSources.calls = []

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def first(self):
        return app.update_state(self.cfg, app.blank_state(self.cfg), NOW, MockSources)

    def test_first_import_is_baseline_then_new_event_without_duplicate(self):
        state = self.first()
        self.assertTrue(all(e['is_baseline'] for e in state['edges'].values()))
        MockSources.count = 2
        MockSources.pages = {0: ([row('Citing Alpha'), row('Citing Beta')], False)}
        app.update_state(self.cfg, state, NOW + timedelta(days=1), MockSources)
        self.assertEqual(len(state['edges']), 2)
        self.assertEqual(sum(not e['is_baseline'] for e in state['edges'].values()), 1)
        app.update_state(self.cfg, state, NOW + timedelta(days=1, minutes=20), MockSources)
        self.assertEqual(len(state['edges']), 2)
        self.assertEqual(len(state['history']), 2)

    def test_no_change_avoids_details_until_periodic_reconciliation(self):
        state = self.first()
        MockSources.calls.clear()
        app.update_state(self.cfg, state, NOW + timedelta(days=1), MockSources)
        self.assertEqual(MockSources.calls, [])
        # Net-zero count: replacement work must still be discovered during reconciliation.
        MockSources.pages = {0: ([row('Citing Beta')], False)}
        app.update_state(self.cfg, state, NOW + timedelta(days=7), MockSources)
        self.assertEqual(len(state['edges']), 2)
        self.assertEqual(sum(not e['is_baseline'] for e in state['edges'].values()), 1)

    def test_failed_detail_fetch_is_retried_even_without_new_count_change(self):
        state = self.first()
        MockSources.count = 2
        MockSources.pages = {0: app.TrackerError('temporary API failure')}
        app.update_state(self.cfg, state, NOW + timedelta(days=1), MockSources)
        self.assertTrue(state['papers']['target']['needs_scan'])
        self.assertEqual(state['papers']['target']['scan_count'], 1)
        MockSources.pages = {0: ([row('Citing Alpha'), row('Citing Beta')], False)}
        app.update_state(self.cfg, state, NOW + timedelta(days=2), MockSources)
        self.assertFalse(state['papers']['target']['needs_scan'])
        self.assertEqual(len(state['edges']), 2)

    def test_pagination_resumes_initial_baseline_without_false_notifications(self):
        self.cfg.pages = 1
        MockSources.count = 11
        MockSources.pages = {0: ([row('Alpha')], True), 10: ([row('Beta')], False)}
        state = self.first()
        self.assertFalse(state['papers']['target']['baseline_done'])
        self.assertEqual(state['papers']['target']['scan_cursor'], 10)
        app.update_state(self.cfg, state, NOW + timedelta(days=1), MockSources)
        self.assertTrue(state['papers']['target']['baseline_done'])
        self.assertEqual(MockSources.calls, [0, 10])
        self.assertTrue(all(e['is_baseline'] for e in state['edges'].values()))

    def test_empty_list_with_positive_count_remains_pending(self):
        MockSources.pages = {0: ([], False)}
        state = self.first()
        self.assertTrue(state['papers']['target']['needs_scan'])
        self.assertFalse(state['papers']['target']['baseline_done'])

    def test_duplicate_urls_for_same_title_are_one_work(self):
        MockSources.count = 2
        MockSources.pages = {0: ([row('Citing Alpha'), row('[PDF] Citing Alpha', url='https://example.net/other')], False)}
        state = self.first()
        self.assertEqual(len(state['works']), 1)
        self.assertEqual(len(state['edges']), 1)

    def test_count_decrease_is_visible_and_does_not_delete_history(self):
        state = self.first()
        MockSources.count = 0
        MockSources.pages = {0: ([], False)}
        app.update_state(self.cfg, state, NOW + timedelta(days=1), MockSources)
        self.assertEqual(state['papers']['target']['delta'], -1)
        self.assertEqual(len(state['edges']), 1)

    def test_matching_rejects_wrong_author_year_or_near_title(self):
        work = app.parse_citing(row('Citing Alpha'))
        item = {'title': 'Citing Alpha', 'publication_year': 2026,
                'authorships': [{'author': {'display_name': 'Alice Smith'}}]}
        self.assertTrue(app.match_work(work, item))
        wrong = copy.deepcopy(item)
        wrong['authorships'][0]['author']['display_name'] = 'Alice Jones'
        self.assertFalse(app.match_work(work, wrong))
        wrong = {**item, 'publication_year': 2025}
        self.assertFalse(app.match_work(work, wrong))
        wrong = {**item, 'title': 'Citing Alpha: An Extension'}
        self.assertFalse(app.match_work(work, wrong))

    def test_metadata_retains_author_to_institution_mapping(self):
        item = {'authorships': [
            {'author': {'display_name': 'Alice'}, 'institutions': [{'id': 'I1', 'display_name': 'University A'}]},
            {'author': {'display_name': 'Bob'}, 'institutions': [{'id': 'I2', 'display_name': 'University B'}]}]}
        result = app.metadata(item, 'test')
        self.assertEqual(result['authors'][0]['institutions'][0]['name'], 'University A')
        self.assertEqual(result['authors'][1]['institutions'][0]['name'], 'University B')

    def test_ambiguous_exact_matches_do_not_assign_institutions(self):
        source = app.Sources(self.cfg, app.blank_state(self.cfg), '2026-10-05')
        item = {'title': 'Citing Alpha', 'publication_year': 2026,
                'authorships': [{'author': {'display_name': 'Alice Smith'}, 'institutions': [{'display_name': 'Unsafe Guess'}]}]}
        with patch.object(source, 'oa', return_value={'results': [item, copy.deepcopy(item)]}):
            result = source.enrich(app.parse_citing(row('Citing Alpha')))
        self.assertEqual(result['metadata_status'], 'ambiguous')
        self.assertNotIn('authors', result)

    def test_budget_is_persistent_across_updates(self):
        state = app.blank_state(self.cfg)
        self.cfg.serp_budget = 1
        with patch('tracker.json_get', return_value={}):
            app.Sources(self.cfg, state, '2026-10-05').serp({})
            with self.assertRaises(app.BudgetExceeded):
                app.Sources(self.cfg, state, '2026-10-05').serp({})
            app.Sources(self.cfg, state, '2026-10-06').serp({})

    def test_local_store_roundtrip_and_refuses_other_author_or_corrupt_data(self):
        store = app.Store(self.cfg)
        state = self.first()
        store.save(state)
        self.assertEqual(store.load(), state)
        self.cfg.author_id = 'someone-else'
        with self.assertRaises(app.TrackerError):
            store.load()
        store.local_file.write_text('{broken')
        with self.assertRaises(app.TrackerError):
            store.load()

    def test_real_profile_parser_preserves_ids_counts_and_pagination(self):
        source = app.Sources(self.cfg, app.blank_state(self.cfg), '2026-10-05')
        page1 = {'author': {'name': 'Test Author'}, 'cited_by': {'table': [{'citations': {'all': 15}}]},
            'articles': [{'citation_id': 'test:A', 'title': 'Paper A', 'cited_by': {
                'value': 10, 'serpapi_link': 'https://serpapi.com/search.json?cites=123'}}],
            'serpapi_pagination': {'next': 'https://serpapi.com/search.json?start=1'}}
        page2 = {'articles': [{'citation_id': 'test:B', 'title': 'Paper B', 'cited_by': {
            'value': 5, 'link': 'https://scholar.google.com/scholar?cites=456'}}]}
        with patch.object(source, 'serp', side_effect=[page1, page2]) as mock:
            profile, papers = source.profile()
        self.assertEqual(profile['metrics']['citations'], 15)
        self.assertEqual(papers['test:A']['cites_id'], '123')
        self.assertEqual(papers['test:B']['citations'], 5)
        self.assertEqual(mock.call_args_list[1].args[0]['start'], 1)

    def test_export_protects_against_csv_formulas(self):
        MockSources.pages = {0: ([row('=DANGEROUS()')], False)}
        body = app.export_csv(self.first()).decode('utf-8-sig')
        self.assertIn("'=DANGEROUS()", body)


    def test_same_day_rerun_preserves_daily_delta(self):
        state = self.first()
        MockSources.count = 3
        MockSources.pages = {0: ([row('Alpha'), row('Beta')], False)}
        app.update_state(self.cfg, state, NOW + timedelta(days=1), MockSources)
        app.update_state(self.cfg, state, NOW + timedelta(days=1, hours=1), MockSources)
        self.assertEqual(state['papers']['target']['delta'], 2)
        self.assertEqual(len(state['history']), 2)

    def test_rotates_limited_budget_to_unscanned_paper(self):
        class LimitedSources(MockSources):
            remaining = 1
            seen = []
            def profile(inner):
                profile, papers = super().profile()
                papers['target']['citations'] = 20
                papers['other'] = {**papers['target'], 'id': 'other', 'title': 'Other Paper', 'cites_id': '456'}
                return profile, papers
            def citing_page(inner, cid, start):
                if LimitedSources.remaining == 0:
                    raise app.BudgetExceeded('budget')
                LimitedSources.remaining -= 1
                LimitedSources.seen.append(cid)
                return [row('Paper ' + cid)], True
        self.cfg.pages = 1
        state = app.update_state(self.cfg, app.blank_state(self.cfg), NOW, LimitedSources)
        LimitedSources.remaining = 1
        app.update_state(self.cfg, state, NOW + timedelta(days=1), LimitedSources)
        self.assertEqual(set(LimitedSources.seen), {'123', '456'})

    def test_count_change_during_scan_queues_rescan(self):
        self.cfg.pages = 1
        MockSources.count = 11
        MockSources.pages = {0: ([row('Alpha')], True), 10: ([row('Beta')], False)}
        state = self.first()
        MockSources.count = 12
        app.update_state(self.cfg, state, NOW + timedelta(days=1), MockSources)
        self.assertTrue(state['papers']['target']['needs_scan'])
        self.assertTrue(state['papers']['target']['baseline_done'])
        self.assertEqual(state['papers']['target']['scan_cursor'], 0)

    def test_failed_profile_preserves_counts_and_quota(self):
        state = self.first()
        store = app.Store(self.cfg)
        store.save(state)
        class FailedSources(MockSources):
            def profile(inner):
                inner.usage['serpapi'] += 1
                raise app.TrackerError('API failure')
        with self.assertRaises(app.TrackerError):
            app.run_update(self.cfg, store, NOW + timedelta(days=1), FailedSources)
        saved = store.load()
        self.assertEqual(saved['history'], state['history'])
        self.assertEqual(saved['works'], state['works'])
        self.assertEqual(saved['usage']['2026-10-06']['serpapi'], 1)

    def test_static_build_has_csv_and_no_credentials(self):
        from pathlib import Path
        output = Path(self.temp.name) / 'output'
        state = self.first()
        app.build_site(self.cfg, state, output)
        payload = (output / 'data.json').read_text()
        self.assertEqual(json.loads(payload)['author_id'], 'test')
        self.assertTrue((output / 'citations.csv').read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertTrue((output / 'index.html').exists())
        for secret in (self.cfg.serp_key, self.cfg.openalex_key):
            self.assertNotIn(secret, payload)

    def test_incomplete_profile_is_not_accepted(self):
        source = app.Sources(self.cfg, app.blank_state(self.cfg), NOW.date().isoformat())
        with patch.object(source, 'serp', return_value={'articles': [], 'serpapi_pagination': {'next': 'next'}}):
            with self.assertRaises(app.TrackerError):
                source.profile()

    def test_doi_not_in_openalex_falls_back_to_title(self):
        source = app.Sources(self.cfg, app.blank_state(self.cfg), NOW.date().isoformat())
        work = app.parse_citing(row('Citing Alpha', url='https://doi.org/10.1234/example'))
        item = {'title': 'Citing Alpha', 'publication_year': 2026,
                'authorships': [{'author': {'display_name': 'Alice Smith'}}]}
        with patch.object(source, 'oa', side_effect=[app.TrackerError('OpenAlex: HTTP 404'), {'results': [item]}]):
            self.assertEqual(source.enrich(work)['metadata_status'], 'matched')

if __name__ == '__main__':
    unittest.main()
