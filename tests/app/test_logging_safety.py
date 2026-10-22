from pathlib import Path

def test_local_sms_logging_does_not_include_recipient_or_body():
    source=Path('app/services/postApi.py').read_text(encoding='utf-8')
    for line in source.splitlines():
        if 'print(' in line or 'log_activities(' in line:
            assert 'item.number' not in line
            assert 'item.text' not in line
