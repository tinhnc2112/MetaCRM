"""Dialect-portable SQL ordering helpers."""

from __future__ import annotations


def ascending_with_nulls_at_end(column):
    """Sort non-null values ascending, followed by null values."""
    return column.is_(None).asc(), column.asc()


def descending_with_nulls_at_end(column):
    """Sort non-null values descending, followed by null values."""
    return column.is_(None).asc(), column.desc()
