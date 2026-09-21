"""Shared column-name resolution without data or verification dependencies."""


def resolve_column_name(requested: str, available: tuple[str, ...] | list[str]) -> str:
    """Resolve one requested name case-insensitively and preserve source casing."""
    name = requested.strip()
    if not name:
        raise ValueError("comparison column names must not be blank")

    matches = [candidate for candidate in available if candidate.casefold() == name.casefold()]
    if not matches:
        raise KeyError(f"comparison column not found: {name}")
    if len(matches) > 1:
        rendered = ", ".join(repr(match) for match in matches)
        raise ValueError(f"ambiguous case-insensitive column {name!r}: {rendered}")
    return matches[0]
