"""Read the account's live filters and mailboxes (FR-DISC.1, FR-PLAN.6)."""

from dataclasses import replace

from sieve_as_code.client import ProtonClient
from sieve_as_code.model import Filter, FilterOrder, FilterSet, Rename


def _number_duplicates(
    filters: tuple[Filter, ...],
) -> tuple[tuple[Filter, ...], tuple[Rename, ...]]:
    """BR-2: the first of a name keeps it; later ones become `name (1)`, `name (2)`."""
    taken = {item.name for item in filters}
    seen: set[str] = set()
    numbered: list[Filter] = []
    renames: list[Rename] = []
    for item in filters:
        name, count = item.name, 0
        while name in seen or (name != item.name and name in taken):
            count += 1
            name = f"{item.name} ({count})"
        seen.add(name)
        if name != item.name:
            renames.append(Rename(item.name, name))
        numbered.append(replace(item, name=name))
    return tuple(numbered), tuple(renames)


def discover(client: ProtonClient) -> FilterSet:
    """All live filters with Sieve content, in live order. Read-only. BR-1, BR-2."""
    listed = tuple(client.get_filter(ref.live_id) for ref in client.list_filters())
    filters, renames = _number_duplicates(listed)
    names = tuple(item.name for item in filters)
    return FilterSet(filters, FilterOrder(names), renames)


def discover_targets(client: ProtonClient) -> frozenset[str]:
    """Name and path of every folder and label. BR-10, BR-16."""
    found = [*client.list_folders(), *client.list_labels()]
    return frozenset(value for target in found for value in (target.name, target.path))
