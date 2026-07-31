"""Tests for the shared nav walkers (scripts/docs/navigation.py): label extraction and relabelling."""

from navigation import NavEntry, nav_labels, relabel_nav

# Nested sections, explicit labels, bare paths, an external link, a repeated
# label, and the site name (product name, never translated).
NAV: list[NavEntry] = [
    {"Test docs": "index.md"},
    {"Get started": ["get-started/index.md", {"Installation": "get-started/installation.md"}]},
    {"Servers": [{"Subscriptions": "servers/subscriptions.md"}]},
    {"Clients": ["client/index.md", {"Subscriptions": "client/subscriptions.md"}]},
    {"Blog": "https://example.org/blog"},
    "translations.md",
    {"API Reference": "api/"},
]


def test_nav_labels_lists_titles_and_explicit_labels_once_in_nav_order() -> None:
    labels = nav_labels(NAV, site_name="Test docs")

    assert labels == ["Get started", "Installation", "Servers", "Subscriptions", "Clients", "Blog", "API Reference"]


def test_relabel_nav_swaps_covered_labels_and_leaves_the_rest_english() -> None:
    labels = {
        "Get started": "はじめに",
        "Installation": "インストール",
        "Blog": "ブログ",
        "API Reference": "API リファレンス",
    }

    assert relabel_nav(NAV, labels) == [
        {"Test docs": "index.md"},
        {"はじめに": ["get-started/index.md", {"インストール": "get-started/installation.md"}]},
        {"Servers": [{"Subscriptions": "servers/subscriptions.md"}]},
        {"Clients": ["client/index.md", {"Subscriptions": "client/subscriptions.md"}]},
        {"ブログ": "https://example.org/blog"},
        "translations.md",
        {"API リファレンス": "api/"},
    ]
