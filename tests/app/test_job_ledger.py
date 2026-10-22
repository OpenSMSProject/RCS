import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath('app'))


def ledger_cls():
    try:
        module = importlib.import_module('services.jobLedger')
    except ModuleNotFoundError:
        pytest.fail('services.jobLedger is not implemented')
    assert hasattr(module, 'JobLedger'), 'JobLedger is not implemented'
    return module.JobLedger


def test_new_ledger_has_no_record(tmp_path):
    Ledger = ledger_cls()
    ledger = Ledger(str(tmp_path / 'jobs.json'))
    assert ledger.get('job-1') is None


def test_mark_survives_reopen_and_preserves_terminal_result(tmp_path):
    Ledger = ledger_cls()
    path = str(tmp_path / 'jobs.json')
    ledger = Ledger(path)
    ledger.mark('job-1', 'sent', {'state': 'sent', 'provider_ref': 'local'})
    reopened = Ledger(path)
    assert reopened.get('job-1')['state'] == 'sent'
    assert reopened.get('job-1')['result'] == {'state': 'sent', 'provider_ref': 'local'}


def test_inflight_record_becomes_ambiguous_after_restart(tmp_path):
    Ledger = ledger_cls()
    path = str(tmp_path / 'jobs.json')
    ledger = Ledger(path)
    ledger.mark('job-1', 'sending')
    reopened = Ledger(path)
    assert reopened.get('job-1')['state'] == 'ambiguous'


def test_prune_keeps_only_newest_entries(tmp_path):
    Ledger = ledger_cls()
    ledger = Ledger(str(tmp_path / 'jobs.json'))
    for index in range(525):
        ledger.mark(f'job-{index:04d}', 'failed', {'state': 'failed'})
    ledger.prune(500)
    assert len(ledger.records()) == 500
    assert ledger.get('job-0000') is None
    assert ledger.get('job-0524') is not None
