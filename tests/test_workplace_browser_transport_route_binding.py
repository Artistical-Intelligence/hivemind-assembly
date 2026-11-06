"""No-provider, offline browser route revocation checks."""

from hivemind_assembly.automation.browser_engine.route_binding import (
    bound_route_is_current, profile_route_binding,
)


def config():
    return {'routes': {'primary': {'profile': 'operator', 'provider': 'chat'},
                       'backup': {'profile': 'operator', 'provider': 'chat'},
                       'other': {'profile': 'different'}}}


def test_exact_route_binding_allows_unmodified_profile_and_unrelated_route_changes():
    cfg = config()
    bound = profile_route_binding(cfg, 'operator')
    assert bound == ('backup', 'primary')
    assert bound_route_is_current(cfg, 'operator', bound)
    cfg['routes']['other'] = {'profile': 'third'}
    assert bound_route_is_current(cfg, 'operator', bound)


def test_removed_original_route_denied_even_when_profile_still_exists():
    cfg = config()
    bound = profile_route_binding(cfg, 'operator')
    del cfg['routes']['primary']
    assert profile_route_binding(cfg, 'operator') == ('backup',)
    assert not bound_route_is_current(cfg, 'operator', bound)


def test_same_profile_transferred_to_different_route_is_not_same_permission():
    cfg = config()
    bound = profile_route_binding(cfg, 'operator')
    del cfg['routes']['primary']
    cfg['routes']['replacement'] = {'profile': 'operator'}
    assert not bound_route_is_current(cfg, 'operator', bound)


def test_reassignment_of_existing_route_revokes_original_binding():
    cfg = config()
    bound = profile_route_binding(cfg, 'operator')
    cfg['routes']['backup']['profile'] = 'different'
    assert not bound_route_is_current(cfg, 'operator', bound)


def test_new_route_using_same_profile_requires_new_authorization():
    cfg = config()
    bound = profile_route_binding(cfg, 'operator')
    cfg['routes']['new'] = {'profile': 'operator'}
    assert not bound_route_is_current(cfg, 'operator', bound)


def test_missing_corrupted_or_forged_config_fails_closed():
    for invalid in (None, {}, {'routes': None}, {'routes': []},
                    {'routes': {'bad': {'profile': 'operator'}}}):
        assert not bound_route_is_current(invalid, 'operator', ('primary',))
    assert not bound_route_is_current(config(), 'operator', ())
    assert not bound_route_is_current(config(), 'operator', ['backup', 'primary'])
    assert not bound_route_is_current(config(), None, ('backup',))
    assert profile_route_binding({'routes': {'bad': 'string'}}, 'operator') == ()
