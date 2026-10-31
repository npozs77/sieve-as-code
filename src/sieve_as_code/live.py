"""Read the account's live filters and mailboxes (FR-DISC.1, FR-PLAN.6)."""

from sieve_as_code.client import ProtonClient
from sieve_as_code.model import ClientError, FilterOrder, FilterSet


def discover(client: ProtonClient) -> FilterSet:
    """All live filters with Sieve content, in live order. Read-only. BR-1, BR-2."""
    filters = tuple(client.get_filter(ref.live_id) for ref in client.list_filters())
    names = [item.name for item in filters]
    for name in names:
        if names.count(name) > 1:
            raise ClientError(f"two live filters are named {name!r}")
    return FilterSet(filters, FilterOrder(tuple(names)))


def discover_targets(client: ProtonClient) -> frozenset[str]:
    """Name and path of every folder and label. BR-10, BR-16."""
    found = [*client.list_folders(), *client.list_labels()]
    return frozenset(value for target in found for value in (target.name, target.path))
