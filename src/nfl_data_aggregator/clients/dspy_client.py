"""DSPy LM configuration supporting multiple providers."""

import logging

from ..config.config import settings

logger = logging.getLogger(__name__)


def configure_dspy_lm(
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.3,
):
    """Create and return a DSPy LM instance.

    Args:
        provider: LLM provider ("anthropic", "openai", "google"). Defaults to settings.
        model: Model name. Defaults to settings.DSPY_MODEL.
        api_key: API key. Defaults to settings based on provider.
        temperature: Generation temperature.

    Returns:
        A dspy.LM instance.
    """
    import dspy

    provider = provider or settings.DSPY_LM_PROVIDER
    model = model or settings.DSPY_MODEL

    # Build litellm-style model string
    if provider == "anthropic":
        model_str = f"anthropic/{model}" if not model.startswith("anthropic/") else model
        api_key = api_key or settings.ANTHROPIC_API_KEY
    elif provider == "openai":
        model_str = f"openai/{model}" if not model.startswith("openai/") else model
        api_key = api_key or settings.OPENAI_API_KEY
    elif provider == "google":
        model_str = f"google/{model}" if not model.startswith("google/") else model
        api_key = api_key or settings.GOOGLE_GENAI_API_KEY
    else:
        model_str = model
        api_key = api_key

    kwargs = {"model": model_str, "temperature": temperature}
    if api_key:
        kwargs["api_key"] = api_key

    lm = dspy.LM(**kwargs)
    logger.info("Configured DSPy LM: provider=%s, model=%s", provider, model_str)
    return lm


def init_dspy(
    provider: str | None = None,
    model: str | None = None,
    temperature: float = 0.3,
):
    """Configure DSPy globally with the specified LM.

    Returns the configured LM instance.
    """
    import dspy

    lm = configure_dspy_lm(provider=provider, model=model, temperature=temperature)
    dspy.configure(lm=lm)
    return lm
