"""Offline control-output privacy and size fences; no browser or model API."""

import pytest

from hivemind_assembly.automation.browser_engine.control_summaries import (
    ControlSummaryError, MAX_CONTROL_FIELD_CHARS, MAX_CONTROL_LABEL_CHARS,
    bounded_control_summaries,
)
from hivemind_assembly.automation.browser_engine.redaction import scrub_url_credentials


def identity(**overrides):
    data = {'connected': True, 'tag': 'BUTTON', 'type': '', 'id': '',
            'name': '', 'label': 'Save', 'text': 'Save'}
    data.update(overrides)
    return data


def controls(data):
    return bounded_control_summaries(data, scrub_url_credentials)


def test_normal_control_labels_and_refs_preserved():
    items = {'12': (object(), identity()), '13': (object(), identity(label='', name='Next'))}
    assert controls(items) == [
        {'ref': '12', 'tag': 'BUTTON', 'label': 'Save'},
        {'ref': '13', 'tag': 'BUTTON', 'label': 'Next'},
    ]


def test_url_credentials_in_control_label_are_redacted():
    raw = 'Login https://alice:supersecret@example.org/account?access_token=leak'
    result = controls({'1': (object(), identity(label=raw))})
    assert 'supersecret' not in str(result)
    assert 'leak' not in str(result)
    assert '***@' in result[0]['label']
    assert 'access_token=***' in result[0]['label']


@pytest.mark.parametrize('bad', [None, 1, {}, ['not a string']])
def test_control_label_must_be_bounded_string(bad):
    with pytest.raises(ControlSummaryError, match='oversized or invalid'):
        controls({'1': (object(), identity(label=bad))})


def test_oversized_unselected_identity_field_is_also_refused():
    with pytest.raises(ControlSummaryError, match='oversized'):
        controls({'1': (object(), identity(id='x' * (MAX_CONTROL_FIELD_CHARS + 1)))})


def test_exact_field_bound_is_allowed():
    assert len(controls({'1': (object(), identity(label='z' * MAX_CONTROL_FIELD_CHARS))})[0]['label']) == MAX_CONTROL_FIELD_CHARS


def test_aggregate_budget_is_enforced_independently_of_snapshot_size():
    count = MAX_CONTROL_LABEL_CHARS // MAX_CONTROL_FIELD_CHARS
    assert len(controls({str(i): (object(), identity(label='x' * MAX_CONTROL_FIELD_CHARS)) for i in range(count)})) == count
    with pytest.raises(ControlSummaryError, match='too much'):
        controls({str(i): (object(), identity(label='x' * MAX_CONTROL_FIELD_CHARS)) for i in range(count + 1)})


@pytest.mark.parametrize('bad', [[], {'x': (object(), identity())}, {'1': (object(), {'connected': True})},
                                        {'1': (object(), identity(connected=False))}])
def test_malformed_refs_or_identities_fail_closed(bad):
    with pytest.raises(ControlSummaryError):
        controls(bad)


def test_no_redaction_callback_is_rejected():
    with pytest.raises(ControlSummaryError):
        bounded_control_summaries({'1': (object(), identity())}, None)
