"""Local site customizations for legacy runtimes."""

try:
    import importlib.metadata as _metadata
except Exception:  # pragma: no cover
    _metadata = None

if _metadata and not hasattr(_metadata, "packages_distributions"):
    try:
        import importlib_metadata as _metadata_backport
    except Exception:  # pragma: no cover
        _metadata_backport = None

    if _metadata_backport:
        def _packages_distributions():
            """Provide backported packages_distributions for Python <3.10."""
            return _metadata_backport.packages_distributions()

        _metadata.packages_distributions = _packages_distributions
