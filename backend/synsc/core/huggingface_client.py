"""HuggingFace Hub integration for dataset metadata retrieval.

Fetches dataset cards (README), schema/features, and metadata from the
HuggingFace Hub API. Does NOT download actual dataset rows.
"""

import os
import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class HuggingFaceError(Exception):
    """Base exception for HuggingFace-related errors."""
    pass


class DatasetNotFoundError(HuggingFaceError):
    """Raised when a HuggingFace dataset is not found."""
    pass


def parse_hf_dataset_id(input_str: str) -> str:
    """Parse HuggingFace dataset ID from various input formats.

    Accepts:
    - Plain ID: "imdb", "openai/gsm8k"
    - HF URL: "https://huggingface.co/datasets/openai/gsm8k"

    Args:
        input_str: HuggingFace dataset ID or URL

    Returns:
        Normalized dataset ID (e.g. "openai/gsm8k" or "imdb")

    Raises:
        HuggingFaceError: If input format is invalid
    """
    input_str = input_str.strip()

    if input_str.startswith(("http://", "https://")):
        match = re.search(r"huggingface\.co/datasets/([^/?#]+(?:/[^/?#]+)?)", input_str)
        if match:
            return match.group(1)
        raise HuggingFaceError(f"Invalid HuggingFace dataset URL: {input_str}")

    # Validate plain ID: alphanumeric with dots, hyphens, underscores, optional namespace
    if re.match(r"^[a-zA-Z0-9._-]+(/[a-zA-Z0-9._-]+)?$", input_str):
        return input_str

    raise HuggingFaceError(f"Invalid HuggingFace dataset ID: {input_str}")


def get_dataset_info(hf_id: str, hf_token: str | None = None) -> dict[str, Any]:
    """Fetch metadata for a HuggingFace dataset.

    Args:
        hf_id: HuggingFace dataset identifier (e.g. "imdb", "openai/gsm8k")
        hf_token: Optional HuggingFace API token for higher rate limits

    Returns:
        Dictionary containing dataset metadata

    Raises:
        DatasetNotFoundError: If dataset doesn't exist
        HuggingFaceError: If API call fails
    """
    token = hf_token or os.getenv("HF_TOKEN")

    try:
        from huggingface_hub import HfApi
        from huggingface_hub.utils import RepositoryNotFoundError, GatedRepoError

        api = HfApi()
        info = api.dataset_info(hf_id, token=token)

        # Extract owner and name
        if "/" in hf_id:
            owner, name = hf_id.split("/", 1)
        else:
            owner = ""
            name = hf_id

        # Get dataset card content (README.md)
        card_content = ""
        try:
            from huggingface_hub import DatasetCard
            card = DatasetCard.load(hf_id, token=token)
            card_content = card.content or ""
        except Exception as e:
            logger.warning("Failed to fetch dataset card", hf_id=hf_id, error=str(e))

        # Extract description (first non-empty paragraph after YAML front matter)
        description = ""
        if card_content:
            # Strip YAML front matter (between --- markers)
            content_no_yaml = re.sub(r"^---\s*\n.*?\n---\s*\n", "", card_content, flags=re.DOTALL)
            paragraphs = [p.strip() for p in content_no_yaml.split("\n\n") if p.strip()]
            for para in paragraphs:
                # Skip headings and short lines
                if not para.startswith("#") and len(para) > 20:
                    description = para[:500]
                    break

        # Extract tags, languages, license from card_data
        tags = list(info.tags) if info.tags else []
        languages = []
        license_id = None

        if info.card_data:
            languages = info.card_data.get("language", []) or []
            if isinstance(languages, str):
                languages = [languages]
            license_id = info.card_data.get("license")

        # Extract features and splits from dataset_info if available
        features = {}
        splits = {}
        dataset_size_bytes = None

        if hasattr(info, "card_data") and info.card_data:
            ds_info = info.card_data.get("dataset_info")
            if ds_info:
                # dataset_info can be a list (multi-config) or dict
                if isinstance(ds_info, list) and ds_info:
                    ds_info = ds_info[0]
                if isinstance(ds_info, dict):
                    features = ds_info.get("features", {}) or {}
                    raw_splits = ds_info.get("splits", [])
                    if isinstance(raw_splits, list):
                        for s in raw_splits:
                            if isinstance(s, dict) and "name" in s:
                                splits[s["name"]] = {
                                    "num_examples": s.get("num_examples", 0),
                                    "num_bytes": s.get("num_bytes", 0),
                                }
                    elif isinstance(raw_splits, dict):
                        splits = raw_splits
                    dataset_size_bytes = ds_info.get("dataset_size") or ds_info.get("download_size")

        # Convert features to serializable format
        if isinstance(features, list):
            features_dict = {}
            for f in features:
                if isinstance(f, dict) and "name" in f:
                    features_dict[f["name"]] = {
                        k: v for k, v in f.items() if k != "name"
                    }
            features = features_dict

        return {
            "hf_id": hf_id,
            "owner": owner,
            "name": name,
            "description": description,
            "card_content": card_content,
            "tags": tags,
            "languages": languages,
            "license": license_id,
            "downloads": info.downloads or 0,
            "likes": info.likes or 0,
            "features": features,
            "splits": splits,
            "dataset_size_bytes": dataset_size_bytes,
            "is_private": info.private if hasattr(info, "private") else False,
            "is_gated": bool(info.gated) if hasattr(info, "gated") else False,
        }

    except RepositoryNotFoundError:
        raise DatasetNotFoundError(f"HuggingFace dataset not found: {hf_id}")
    except GatedRepoError:
        raise HuggingFaceError(
            f"Dataset '{hf_id}' is gated. Accept the license at "
            f"https://huggingface.co/datasets/{hf_id} and provide HF_TOKEN."
        )
    except (DatasetNotFoundError, HuggingFaceError):
        raise
    except Exception as e:
        raise HuggingFaceError(f"Failed to fetch dataset info: {str(e)}") from e
