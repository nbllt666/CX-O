from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class DeduplicationService:
    def __init__(self, similarity_threshold: float = 0.95):
        self.similarity_threshold = similarity_threshold
        self._seen_hashes: set = set()

    def compute_hash(self, content: str) -> str:
        import hashlib

        normalized = content.strip().lower()
        return hashlib.md5(normalized.encode()).hexdigest()

    def is_duplicate(self, content: str) -> bool:
        content_hash = self.compute_hash(content)
        if content_hash in self._seen_hashes:
            return True
        self._seen_hashes.add(content_hash)
        return False

    def clear(self):
        self._seen_hashes.clear()
        logger.info("去重缓存已清除")

    def get_stats(self) -> dict:
        return {"cached_hashes": len(self._seen_hashes), "threshold": self.similarity_threshold}