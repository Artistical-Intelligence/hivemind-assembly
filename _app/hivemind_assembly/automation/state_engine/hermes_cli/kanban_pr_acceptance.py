# Derived from NousResearch/hermes-agent at c0015464f0f40d52c5702a84cf58e70361f4a04c.
# MIT; copyright (c) 2025 Nous Research. See LICENSE.
# Modified for HA: selected storage/task code; private imports; no upstream launcher.
import re
_PR = re.compile('pr:(?P<repo>[^/]+/[^/]+)')

def validate_contract(value):
    if value is None or value == '':
        return None
    raise ValueError('Use HA acceptance contracts; upstream PR execution is not enabled')

def collect_acceptance(*args, **kwargs):
    return {'ok': False, 'classification': 'unsupported', 'head_sha': None, 'pr_url': None, 'checks': [], 'recovery': 'Use HA independent acceptance. No upstream credential lookup was performed.'}
