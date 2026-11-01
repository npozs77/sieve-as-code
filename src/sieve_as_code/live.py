"""Read the account's live filters and mailboxes (FR-DISC.1, FR-PLAN.6)."""

from dataclasses import replace

from sieve_as_code.client import ProtonClient
from sieve_as_code.model import Filter, FilterOrder, FilterSet, Rename, Targets


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


def discover_targets(client: ProtonClient) -> Targets:
    """Path of every folder and name of every label. BR-10, BR-16."""
    return Targets(
        frozenset(folder.path for folder in client.list_folders()),
        frozenset(label.name for label in client.list_labels()),
    )
