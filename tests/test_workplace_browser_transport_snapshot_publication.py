"""No-API regression for final browser read publication/handle ownership."""

import asyncio

import pytest

from hivemind_assembly.automation.browser_engine.control_summaries import ControlSummaryError
from hivemind_assembly.automation.browser_engine.element_refs import MAX_SNAPSHOT_CHARS
from hivemind_assembly.automation.browser_engine.snapshot_publication import publish_authorized_snapshot


class Handle:
    def __init__(self, disposal_error=False):
        self.disposals = 0
        self.disposal_error = disposal_error

    async def dispose(self):
        self.disposals += 1
        if self.disposal_error:
            raise RuntimeError('disposal failed')


def fixture(*, label='Submit', count=1, disposal_error=False):
    handles = {}
    objects = []
    for n in range(count):
        handle = Handle(disposal_error)
        objects.append(handle)
        handles[str(n + 1)] = (handle, {
            'connected': True, 'tag': 'BUTTON', 'type': '', 'id': '',
            'name': '', 'label': label, 'text': 'Submit',
        })
    return handles, objects


def publish(session, handles, text='Safe page text', *, check=lambda s: None,
            redact=lambda text: text, token=lambda: 'fresh-token'):
    return asyncio.run(publish_authorized_snapshot(
        session, handles, text, check, redact, token))


def test_authorized_publication_installs_handles_without_disposal():
    handles, objects = fixture(count=2)
    session = {'snapshot': None, 'handles': {}}
    token, text, controls = publish(session, handles)
    assert token == 'fresh-token' and text == 'Safe page text'
    assert len(controls) == 2
    assert session == {'snapshot': 'fresh-token', 'handles': handles}
    assert [x.disposals for x in objects] == [0, 0]


def test_revoked_route_after_control_construction_disposes_uncommitted_handles():
    handles, objects = fixture(count=3)
    session = {'snapshot': None, 'handles': {}}
    def revoked(_):
        raise PermissionError('original route revoked')
    with pytest.raises(PermissionError, match='route revoked'):
        publish(session, handles, check=revoked)
    assert session['snapshot'] is None and session['handles'] == {}
    assert [x.disposals for x in objects] == [1, 1, 1]


def test_late_permission_error_is_not_masked_by_disposal_failure():
    handles, objects = fixture(disposal_error=True)
    with pytest.raises(PermissionError, match='revoked'):
        publish({'snapshot': None, 'handles': {}}, handles,
                check=lambda _: (_ for _ in ()).throw(PermissionError('revoked')))
    assert objects[0].disposals == 1


def test_malformed_control_metadata_fails_and_does_not_publish():
    handles, objects = fixture(label=None)
    session = {'snapshot': None, 'handles': {}}
    with pytest.raises(ControlSummaryError, match='oversized or invalid'):
        publish(session, handles)
    assert session['snapshot'] is None and session['handles'] == {}
    assert objects[0].disposals == 1


@pytest.mark.parametrize('returned', [None, ['not-text'], 'x' * (MAX_SNAPSHOT_CHARS + 1)])
def test_invalid_redacted_snapshot_fails_closed_and_cleans_handles(returned):
    handles, objects = fixture()
    session = {'snapshot': None, 'handles': {}}
    def redact(value):
        return value if value == 'Submit' else returned
    with pytest.raises(ControlSummaryError, match='redacted text'):
        publish(session, handles, redact=redact)
    assert session['snapshot'] is None and session['handles'] == {}
    assert objects[0].disposals == 1


@pytest.mark.parametrize('token', [None, '', 1])
def test_invalid_snapshot_id_does_not_publish(token):
    handles, objects = fixture()
    session = {'snapshot': None, 'handles': {}}
    with pytest.raises(ControlSummaryError, match='identifier'):
        publish(session, handles, token=lambda: token)
    assert session['snapshot'] is None and objects[0].disposals == 1


def test_cancellation_propagates_and_disposes_handles():
    handles, objects = fixture()
    session = {'snapshot': None, 'handles': {}}
    with pytest.raises(asyncio.CancelledError):
        publish(session, handles,
                check=lambda _: (_ for _ in ()).throw(asyncio.CancelledError()))
    assert session['snapshot'] is None and objects[0].disposals == 1


def test_rejected_snapshot_does_not_redact_or_export_private_control_values():
    handles, objects = fixture(label='https://site.invalid/?token=private')
    session = {'snapshot': None, 'handles': {}}
    returned = []
    def redact(value):
        returned.append(value)
        return value.replace('private', '***')
    with pytest.raises(PermissionError):
        publish(session, handles, check=lambda s: (_ for _ in ()).throw(PermissionError()), redact=redact)
    assert returned == ['https://site.invalid/?token=private']
    assert objects[0].disposals == 1
    assert session['snapshot'] is None
