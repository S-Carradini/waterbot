import os
import boto3
import json
from datetime import datetime, timezone
import psycopg2
from psycopg2 import sql

# Initialize AWS clients
s3_client = boto3.client('s3')
ssm_client = boto3.client('ssm')
secretsmanager_client = boto3.client('secretsmanager')

# Get environment variables (injected by CDK)
s3_bucket = os.environ['S3_BUCKET']
param_name = os.environ['LAST_BACKUP_TIME_PARAM']
db_secret_arn = os.environ['DB_SECRET_ARN']
db_host = os.environ['DB_HOST']
db_name = os.environ['DB_NAME']


def get_db_credentials():
    """
    Retrieve database username and password from AWS Secrets Manager
    
    Returns:
        tuple: (username, password)
    """
    try:
        secret = secretsmanager_client.get_secret_value(SecretId=db_secret_arn)
        credentials = json.loads(secret['SecretString'])
        return credentials['username'], credentials['password']
    except Exception as e:
        print(f"Error retrieving database credentials: {str(e)}")
        raise


def serialize_row(row_dict):
    """
    Convert database row to JSON-serializable format
    
    Args:
        row_dict: Dictionary representing a database row
        
    Returns:
        dict: JSON-serializable dictionary
    """
    serialized = {}
    for key, value in row_dict.items():
        if isinstance(value, datetime):
            # Convert datetime to ISO format string
            serialized[key] = value.isoformat()
        elif value is None:
            serialized[key] = None
        else:
            serialized[key] = value
    return serialized


def handler(event, context):
    """
    Lambda handler for PostgreSQL incremental backups to S3
    
    This function:
    1. Checks when the last backup was performed (stored in SSM Parameter)
    2. Exports all messages since the last backup (or all if first run)
    3. Uploads the data to S3 in JSON format
    4. Updates the last backup timestamp
    
    Triggered by: EventBridge Rule (every 24 hours)
    """
    
    print("=" * 60)
    print("Starting PostgreSQL backup process")
    print("=" * 60)
    
    try:
        # Step 1: Get the last backup timestamp from SSM Parameter Store
        print(f"Retrieving last backup time from SSM: {param_name}")
        last_backup_time_param_value = ssm_client.get_parameter(Name=param_name)['Parameter']['Value']
        last_backup_time = datetime.fromisoformat(last_backup_time_param_value)
        
        print(f"Last backup was at: {last_backup_time}")
        
        # Step 2: Determine if this is the initial backup
        # Initial value set by CDK is 1970-01-01T00:00:00Z
        is_initial_backup = last_backup_time == datetime(1970, 1, 1, tzinfo=timezone.utc)
        new_backup_time = datetime.now(timezone.utc)
        
        if is_initial_backup:
            print("🆕 This is the INITIAL FULL backup")
            export_type = "FULL"
        else:
            print(f"📊 This is an INCREMENTAL backup (since {last_backup_time})")
            export_type = "INCREMENTAL"
        
        # Step 3: Get database credentials from Secrets Manager
        print("Retrieving database credentials from Secrets Manager")
        db_user, db_password = get_db_credentials()
        
        # Step 4: Connect to PostgreSQL
        print(f"Connecting to PostgreSQL at {db_host}/{db_name}")
        conn = psycopg2.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_password,
            port=5432,
            connect_timeout=30
        )
        cursor = conn.cursor()
        print("✅ Connected to PostgreSQL successfully")
        
        # Step 5: Build and execute the appropriate query
        if is_initial_backup:
            # Full backup: Get ALL messages
            query = "SELECT * FROM messages ORDER BY created_at;"
            print(f"Executing FULL backup query: {query}")
            cursor.execute(query)
        else:
            # Incremental backup: Get only messages created since last backup
            query = "SELECT * FROM messages WHERE created_at > %s ORDER BY created_at;"
            print(f"Executing INCREMENTAL backup query with timestamp: {last_backup_time}")
            cursor.execute(query, (last_backup_time,))
        
        # Step 6: Fetch all rows and convert to dictionaries
        rows = cursor.fetchall()
        column_names = [desc[0] for desc in cursor.description]
        
        print(f"📦 Retrieved {len(rows)} records from database")
        
        # Convert rows to list of dictionaries
        data = []
        for row in rows:
            row_dict = {}
            for i, col_name in enumerate(column_names):
                row_dict[col_name] = row[i]
            
            # Serialize the row (handle datetime, etc.)
            serialized_row = serialize_row(row_dict)
            data.append(serialized_row)
        
        # Step 7: Create export metadata and data package
        export_data = {
            "export_metadata": {
                "export_type": export_type,
                "export_time": new_backup_time.isoformat(),
                "start_time": last_backup_time.isoformat(),
                "end_time": new_backup_time.isoformat(),
                "record_count": len(data),
                "database": db_name,
                "table": "messages"
            },
            "records": data
        }
        
        # Step 8: Generate S3 key with organized folder structure
        timestamp = new_backup_time.strftime('%Y%m%d_%H%M%S')
        year_month = new_backup_time.strftime('%Y/%m')
        
        # Organize backups by year/month for easier management
        s3_key = f"postgres-backups/{export_type.lower()}/{year_month}/{timestamp}_messages.json"
        
        print(f"📤 Uploading to S3: s3://{s3_bucket}/{s3_key}")
        
        # Step 9: Upload to S3
        s3_client.put_object(
            Bucket=s3_bucket,
            Key=s3_key,
            Body=json.dumps(export_data, indent=2),
            ContentType='application/json',
            Metadata={
                'export-type': export_type,
                'record-count': str(len(data)),
                'export-timestamp': new_backup_time.isoformat()
            }
        )
        
        print("✅ Successfully uploaded to S3")
        
        # Step 10: Update the last backup timestamp in SSM
        print(f"Updating SSM parameter with new timestamp: {new_backup_time.isoformat()}")
        ssm_client.put_parameter(
            Name=param_name,
            Value=new_backup_time.isoformat(),
            Overwrite=True
        )
        
        print("✅ SSM parameter updated")
        
        # Step 11: Clean up database connection
        cursor.close()
        conn.close()
        
        # Step 12: Return success response
        result = {
            'statusCode': 200,
            'body': {
                'message': f'{export_type} backup completed successfully',
                's3_bucket': s3_bucket,
                's3_key': s3_key,
                'record_count': len(data),
                'export_type': export_type,
                'backup_time': new_backup_time.isoformat()
            }
        }
        
        print("=" * 60)
        print(f"✅ BACKUP COMPLETE - {len(data)} records backed up")
        print("=" * 60)
        
        return result
        
    except Exception as e:
        # Handle any errors and return failure response
        error_message = f"❌ Backup failed: {str(e)}"
        print(error_message)
        print("=" * 60)
        
        return {
            'statusCode': 500,
            'body': {
                'message': error_message,
                'error': str(e)
            }
        }