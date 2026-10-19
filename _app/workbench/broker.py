"""v0.1 compatibility facade: the legacy broker selects reverse engineering."""

from hivemind_assembly.core.broker import Broker as CoreBroker, CORE_CAPABILITIES
from hivemind_assembly.domains.reverse_engineering.domain import (
    ReverseEngineeringDomain,
)

CAPABILITIES = {
    c.name for c in (*CORE_CAPABILITIES, *ReverseEngineeringDomain.capabilities)
}
MUTATIONS = {
    c.name
    for c in (*CORE_CAPABILITIES, *ReverseEngineeringDomain.capabilities)
    if c.mutates_project
}


class Broker(CoreBroker):
    def __init__(self, controller, config, domain=None):
        super().__init__(
            controller,
            config,
            domain=domain if domain is not None else ReverseEngineeringDomain(),
        )
