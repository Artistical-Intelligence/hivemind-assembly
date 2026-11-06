"""Deterministic, no-browser regressions for live route-policy revocation."""
import copy

from hivemind_assembly.automation.browser_engine.route_policy import (
    route_policy_fingerprint, route_policy_is_current,
)


def config():
    return {'routes': {
        'alpha': {'profile': 'native', 'surface': 'chat', 'model': 'configured-model',
                  'permissions': {'send': False, 'read': True},
                  'prompt': {'system': 'original', 'options': [1, 2]}},
        'beta': {'profile': 'native', 'surface': 'chat', 'permissions': {'read': True}},
        'other': {'profile': 'unrelated', 'permissions': {'send': False}},
    }}


def test_same_route_definitions_preserve_authority_despite_dictionary_order():
    cfg = config()
    original = route_policy_fingerprint(cfg, 'native')
    assert original and original.startswith('sha256:')
    reordered = {'routes': dict(reversed(list(cfg['routes'].items())))}
    assert route_policy_is_current(reordered, 'native', original)
    assert len(original) == 71


def test_route_prompt_and_nested_permission_changes_revoke_existing_page():
    for mutate in (
        lambda cfg: cfg['routes']['alpha']['prompt'].update(system='changed'),
        lambda cfg: cfg['routes']['alpha']['permissions'].update(send=True),
        lambda cfg: cfg['routes']['alpha']['prompt']['options'].append(3),
        lambda cfg: cfg['routes']['alpha'].update(model='different-model'),
        lambda cfg: cfg['routes']['alpha'].update(surface='work'),
    ):
        cfg = config()
        fingerprint = route_policy_fingerprint(cfg, 'native')
        mutate(cfg)
        assert not route_policy_is_current(cfg, 'native', fingerprint)


def test_original_route_ids_and_profile_do_not_authorize_changed_route_values():
    cfg = config()
    original = route_policy_fingerprint(cfg, 'native')
    cfg['routes']['beta']['permissions']['read'] = False
    assert tuple(sorted(n for n, r in cfg['routes'].items() if r['profile'] == 'native')) == ('alpha', 'beta')
    assert not route_policy_is_current(cfg, 'native', original)


def test_added_removed_and_reassigned_routes_revoke_profile_authority():
    for mutate in (
        lambda cfg: cfg['routes'].pop('alpha'),
        lambda cfg: cfg['routes'].update(gamma={'profile': 'native'}),
        lambda cfg: cfg['routes']['alpha'].update(profile='unrelated'),
    ):
        cfg = config()
        fingerprint = route_policy_fingerprint(cfg, 'native')
        mutate(cfg)
        assert not route_policy_is_current(cfg, 'native', fingerprint)


def test_unrelated_route_mutation_does_not_invalidate_existing_profile():
    cfg = config()
    original = route_policy_fingerprint(cfg, 'native')
    cfg['routes']['other']['permissions']['send'] = True
    assert route_policy_is_current(cfg, 'native', original)


def test_invalid_or_noncanonical_route_configuration_fails_closed():
    original = route_policy_fingerprint(config(), 'native')
    for bad in (None, '', 7, 'sha256:' + 'z' * 64, 'sha256:short'):
        assert not route_policy_is_current(config(), 'native', bad)
    for invalid in (None, {}, {'routes': None}, {'routes': []},
                    {'routes': {'bad': {'profile': 'native', 'value': object()}}},
                    {'routes': {'bad': {'profile': 'native', 'weight': float('nan')}}}):
        assert route_policy_fingerprint(invalid, 'native') is None
        assert not route_policy_is_current(invalid, 'native', original)


def test_snapshot_does_not_follow_nested_mutations_by_reference():
    cfg = config()
    initial = copy.deepcopy(cfg)
    original = route_policy_fingerprint(cfg, 'native')
    cfg['routes']['alpha']['permissions']['read'] = False
    assert not route_policy_is_current(cfg, 'native', original)
    assert route_policy_is_current(initial, 'native', original)
