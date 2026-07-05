"""Custom exceptions for lore."""


class LoreError(Exception):
    """Base exception for lore."""


class QdrantError(LoreError):
    """Qdrant operation failed."""


class ConfigError(LoreError):
    """Invalid configuration."""


class DocumentNotFoundError(LoreError):
    """Document not found in prepared directory."""
