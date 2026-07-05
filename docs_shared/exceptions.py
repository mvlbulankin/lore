"""Custom exceptions for lore."""


class LoreError(Exception):
    """Base exception for lore."""


class QdrantError(LoreError):
    """Qdrant operation failed."""


class ConfigError(LoreError):
    """Invalid configuration."""


class DocumentNotFoundError(LoreError):
    """Document not found in prepared directory."""


class CudaNotAvailableError(LoreError, RuntimeError):
    """ONNX execution provider (e.g. CUDA) is not available in the runtime.

    Raised by Embedder.__init__ when the requested provider cannot be
    initialised. Indicates a host-level misconfiguration
    (nvidia-container-toolkit not installed, driver mismatch, no GPU).
    """
