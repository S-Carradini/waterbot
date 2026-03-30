import os
import pathlib


class LocalTranscriptManager():
    """Volume-based transcript storage for Railway (no S3 dependency)."""

    def __init__(self, storage_path: str):
        self.storage_path = pathlib.Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    async def upload(self, key: str, body: str):
        filepath = self.storage_path / key
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(body, encoding="utf-8")

    async def generate_presigned(self, key: str, expiration_seconds: int = 1800):
        filepath = self.storage_path / key
        if filepath.exists():
            return f"/transcript-file/{key}"
        return None
