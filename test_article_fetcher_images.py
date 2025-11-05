"""Tests for the enhanced ArticleFetcher image selection logic."""

import os

# Provide required environment variables before importing application modules
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("EXA_API_KEY", "test-key")

from newsaggregator.fetchers.article_fetcher import ArticleFetcher


def test_select_best_image_prefers_high_quality_images(monkeypatch):
    hero_image = "https://cdn.example.com/uploads/2024/05/hero-image-1200x800.jpg"
    logo_image = "https://cdn.example.com/logo.png"

    # Avoid performing real network calls during testing
    monkeypatch.setattr(
        ArticleFetcher,
        "_url_returns_image",
        staticmethod(lambda url: True)
    )

    best_image = ArticleFetcher.select_best_image([logo_image, hero_image])

    assert best_image == hero_image


def test_select_best_image_uses_fallback_articles(monkeypatch):
    fallback_image = "https://images.example.com/articles/feature-photo-1024x768.jpg"
    fallback_article = "https://news.example.com/story"

    def fake_returns_image(url):
        return url == fallback_image

    calls = []

    def fake_find_article_images(url):
        calls.append(url)
        return [fallback_image]

    monkeypatch.setattr(
        ArticleFetcher,
        "_url_returns_image",
        staticmethod(fake_returns_image)
    )
    monkeypatch.setattr(
        ArticleFetcher,
        "find_article_images",
        staticmethod(fake_find_article_images)
    )

    best_image = ArticleFetcher.select_best_image([], fallback_urls=[fallback_article])

    assert best_image == fallback_image
    assert calls == [fallback_article]


def test_select_best_image_returns_ranked_candidate_when_validation_fails(monkeypatch):
    candidate_image = "https://cdn.example.com/uploads/story-feature-1280x720.jpg"

    monkeypatch.setattr(
        ArticleFetcher,
        "_url_returns_image",
        staticmethod(lambda url: False)
    )

    best_image = ArticleFetcher.select_best_image([candidate_image])

    assert best_image == candidate_image
