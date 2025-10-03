import boto3

class S3Manager():
    def __init__(self, bucket_name, *args, **kwargs):
        self.client = boto3.client('s3', region_name='us-east-1')

        self.bucket_name=bucket_name
        
        super().__init__(*args,**kwargs)
    
    async def upload(self,key,body):
        self.client.put_object(Bucket=self.bucket_name, Key=key, Body=body.encode(), ContentDisposition='attachment; filename="session-transcript.txt"', ContentType='text/plain')
    
    async def generate_presigned(self,key,expiration_seconds=1800):
        try:
            # Generate the presigned URL
            url = self.client.generate_presigned_url(
                ClientMethod='get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': key
                },
                ExpiresIn=expiration_seconds
            )
            return url
        except Exception as e:
            print(f"Error generating presigned URL: {e}")
            return None

