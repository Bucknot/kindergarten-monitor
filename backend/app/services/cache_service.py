import os
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from backend.app.config import settings
from backend.app.services.stt.base import consolidate_utterance_dicts

logger = logging.getLogger(__name__)


class CacheService:
    def __init__(self):
        self.cache_dir = Path(settings.STORAGE_PATH) / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def compute_file_hash(self, file_path: str) -> str:
        """
        Fast & robust hash of audio files.
        Uses file size + sampled blocks (start, middle, end) to hash even 1GB files in milliseconds.
        """
        if not os.path.exists(file_path):
            return ""

        size = os.path.getsize(file_path)
        hasher = hashlib.sha256()
        hasher.update(str(size).encode())

        chunk_size = 4 * 1024 * 1024  # 4MB
        with open(file_path, "rb") as f:
            # First chunk
            hasher.update(f.read(chunk_size))
            if size > 3 * chunk_size:
                # Middle chunk
                f.seek(size // 2)
                hasher.update(f.read(chunk_size))
                # Last chunk
                f.seek(max(0, size - chunk_size))
                hasher.update(f.read(chunk_size))
            else:
                hasher.update(f.read())

        return hasher.hexdigest()

    @staticmethod
    def _sanitize_model_name(model_name: Optional[str]) -> str:
        if not model_name:
            return ""
        return model_name.replace("/", "_").replace(":", "_").replace(" ", "_").strip().lower()

    def get_stt_cache(
        self,
        file_hash: str,
        stt_provider: Optional[str] = None,
        stt_model: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves cached STT result by file hash, provider, and model with consolidated speech turns.
        Guarantees that a cached transcription from one model is never reused for another model.
        """
        if not file_hash:
            return None

        cache_file = None

        # 1. Look for model-specific cache file: stt_{provider}_{model}_{hash}.json
        if stt_provider and stt_model:
            sanitized_model = self._sanitize_model_name(stt_model)
            model_file = self.cache_dir / f"stt_{stt_provider}_{sanitized_model}_{file_hash}.json"
            if model_file.exists():
                cache_file = model_file

        # 2. Look for provider-specific cache file only if no specific model was requested
        if not cache_file and stt_provider and not stt_model:
            prov_file = self.cache_dir / f"stt_{stt_provider}_{file_hash}.json"
            if prov_file.exists():
                cache_file = prov_file

        # 3. Fallback to generic cache file only if neither provider nor model requested
        if not cache_file and not stt_provider and not stt_model:
            generic_file = self.cache_dir / f"stt_{file_hash}.json"
            if generic_file.exists():
                cache_file = generic_file

        if cache_file and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Verify provider match
                cached_prov = data.get("stt_provider")
                if stt_provider and cached_prov and cached_prov != stt_provider:
                    logger.info(
                        f"[Cache BYPASS] Found cache '{cache_file.name}' from provider '{cached_prov}', "
                        f"but requested provider is '{stt_provider}'. Running fresh transcription."
                    )
                    return None

                # Verify model match: if a model was requested, cache MUST have that exact model!
                if stt_model:
                    cached_model = data.get("stt_model")
                    if not cached_model or self._sanitize_model_name(cached_model) != self._sanitize_model_name(stt_model):
                        logger.info(
                            f"[Cache BYPASS] Cache model '{cached_model}' differs from requested model '{stt_model}'. "
                            f"Running fresh transcription."
                        )
                        return None

                # Consolidate fragmented speech turns
                raw_utts = data.get("utterances", [])
                consolidated = consolidate_utterance_dicts(raw_utts, max_gap_seconds=3.0)
                data["utterances"] = consolidated

                display_model = data.get("stt_model") or stt_model or "default"
                logger.info(
                    f"[Cache HIT] Loaded cached STT for provider '{cached_prov or stt_provider}' "
                    f"(model: {display_model}) and hash {file_hash} with {len(consolidated)} consolidated turns"
                )
                return data
            except Exception as e:
                logger.warning(f"Error reading STT cache {cache_file}: {e}")
        return None

    def save_stt_cache(
        self,
        file_hash: str,
        source_filename: str,
        duration_seconds: float,
        file_size_bytes: int,
        stt_provider: str,
        speakers: List[Dict[str, Any]],
        utterances: List[Dict[str, Any]],
        stt_model: Optional[str] = None
    ) -> str:
        """Persists STT transcription & speaker diarization into provider/model-isolated cache files."""
        if not file_hash:
            return ""

        consolidated = consolidate_utterance_dicts(utterances, max_gap_seconds=3.0)

        cache_data = {
            "file_hash": file_hash,
            "source_filename": source_filename,
            "duration_seconds": duration_seconds,
            "file_size_bytes": file_size_bytes,
            "stt_provider": stt_provider,
            "stt_model": stt_model,
            "speakers": speakers,
            "utterances": consolidated
        }

        # 1. Save to model-specific cache file if model provided
        primary_file = None
        if stt_model:
            sanitized_model = self._sanitize_model_name(stt_model)
            model_file = self.cache_dir / f"stt_{stt_provider}_{sanitized_model}_{file_hash}.json"
            try:
                with open(model_file, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)
                primary_file = model_file
            except Exception as e:
                logger.warning(f"Error saving model-specific STT cache: {e}")

        # 2. Save to provider-specific cache file
        prov_file = self.cache_dir / f"stt_{stt_provider}_{file_hash}.json"
        try:
            with open(prov_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            if not primary_file:
                primary_file = prov_file
            logger.info(f"Saved STT cache for provider '{stt_provider}' (model: {stt_model}) to {prov_file.name}")
        except Exception as e:
            logger.warning(f"Error saving STT cache: {e}")

        # 3. Save to generic cache file
        generic_file = self.cache_dir / f"stt_{file_hash}.json"
        try:
            with open(generic_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return str(primary_file or prov_file)

    def consolidate_disk_cache(self) -> int:
        """Consolidates all existing cache files on disk."""
        updated = 0
        for cache_file in self.cache_dir.glob("stt_*.json"):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                raw = data.get("utterances", [])
                consolidated = consolidate_utterance_dicts(raw, max_gap_seconds=3.0)
                if len(consolidated) != len(raw):
                    data["utterances"] = consolidated
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    logger.info(f"Consolidated cache file {cache_file.name}: {len(raw)} -> {len(consolidated)} turns")
                    updated += 1
            except Exception as e:
                logger.warning(f"Error consolidating {cache_file}: {e}")
        return updated


cache_service = CacheService()
