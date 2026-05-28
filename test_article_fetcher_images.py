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


def test_modern_news_cdn_transform_urls_pass_shape_filter():
    assert ArticleFetcher._is_valid_image_url(
        "https://npr.brightspotcdn.com/dims3/default/strip/false/crop/7821x4399+0+790/"
        "resize/1400/quality/85/format/jpeg/?url=http%3A%2F%2Fnpr-brightspot.s3.amazonaws.com"
        "%2F25%2Fb2%2Ff567559249c18cc7516f3c3dd248%2Fgettyimages-2275664381.jpg"
    )
    assert ArticleFetcher._is_valid_image_url(
        "https://dims.apnews.com/dims4/default/ab25a62/2147483647/strip/true/"
        "crop/1189x792+6+0/resize/980x653!/quality/90/?url=https%3A%2F%2Fassets.apnews.com"
        "%2F0d%2Ff2%2Fff2f23bdb777c03a9debb384aee8%2F3f54babfbdf04c7f803715488dd5228e"
    )


def test_modern_news_cdn_ranking_prefers_large_article_art():
    large_article_image = (
        "https://dims.apnews.com/dims4/default/ab25a62/2147483647/strip/true/"
        "crop/1189x792+6+0/resize/980x653!/quality/90/?url=https%3A%2F%2Fassets.apnews.com"
        "%2F0d%2Ff2%2Fff2f23bdb777c03a9debb384aee8%2F3f54babfbdf04c7f803715488dd5228e"
    )
    author_headshot = (
        "https://dims.apnews.com/dims4/default/fe1826b/2147483647/strip/true/"
        "crop/5110x5110+0+0/resize/100x100!/quality/90/?url=https%3A%2F%2Fassets.apnews.com"
        "%2Fdd%2F95%2F947180014d4bb339a3b0e7cfbf13%2Fjon-gambrell-headshot-2024-square-jon-gambrell.jpg"
    )
    wordmark = (
        "https://dims.apnews.com/dims4/default/bc1ddbf/2147483647/strip/true/"
        "crop/2851x1534+0+0/resize/240x129!/quality/90/?url=https%3A%2F%2Fassets.apnews.com"
        "%2F22%2F25%2F9576fafb4e768552fed602a60238%2Fap-pri-wordmarktagline-rgb-dbg.png"
    )

    assert not ArticleFetcher._is_valid_image_url(author_headshot)
    assert not ArticleFetcher._is_valid_image_url(wordmark)
    assert ArticleFetcher._rank_images([author_headshot, wordmark, large_article_image]) == [large_article_image]
