import os
import pathlib

import boto3


class S3Manager():
    def __init__(self, bucket_name, *args, **kwargs):
        self.client = boto3.client('s3', region_name='us-east-1')

        self.bucket_name=bucket_name

        super().__init__(*args,**kwargs)

    async def upload(self,key,body):
        self.client.put_object(Bucket=self.bucket_name, Key=key, Body=body.encode(), ContentType='text/plain')

    async def generate_presigned(self,key,expiration_seconds=1800):
        try:
            # Generate the presigned URL
            url = self.client.generate_presigned_url(
                ClientMethod='get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': key,
                    'ResponseContentDisposition': 'attachment; filename="session-transcript.txt"',
                    'ResponseContentType': 'text/plain'
                },
                ExpiresIn=expiration_seconds
            )
            return url
        except Exception as e:
            print(f"Error generating presigned URL: {e}")
            return None


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

