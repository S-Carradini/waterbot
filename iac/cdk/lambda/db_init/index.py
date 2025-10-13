import os
import boto3
import json
import psycopg2

# Initialize AWS clients
secretsmanager_client = boto3.client('secretsmanager')


def get_db_credentials(secret_arn):
    """
    Retrieve database username and password from AWS Secrets Manager
    
    Args:
        secret_arn: The ARN of the secret containing database credentials
        
    Returns:
        tuple: (username, password)
    """
    secret = secretsmanager_client.get_secret_value(SecretId=secret_arn)
    credentials = json.loads(secret['SecretString'])
    return credentials['username'], credentials['password']


def handler(event, context):
    """
    CloudFormation Custom Resource handler for database initialization
    
    This function is triggered by CDK during stack deployment.
    It creates the necessary tables and indexes in PostgreSQL.
    
    CDK Provider Framework sends three types of requests:
    - Create: When the resource is first created
    - Update: When the resource properties change
    - Delete: When the stack is being deleted
    
    Returns a dictionary that CDK Provider Framework converts to CloudFormation response.
    """
    
    try:
        # Get the request type from CloudFormation
        request_type = event.get('RequestType', 'Create')
        print(f"Received {request_type} request from CloudFormation")
        
        # On Delete, we don't drop tables (to preserve data)
        # Just return success response
        if request_type == 'Delete':
            print("Delete request - skipping database operations")
            return {
                'PhysicalResourceId': 'db-init-resource',
                'Data': {
                    'Message': 'Delete request - no action taken to preserve data'
                }
            }
        
        # Get environment variables (injected by CDK)
        db_host = os.environ['DB_HOST']
        db_name = os.environ['DB_NAME']
        db_secret_arn = os.environ['DB_SECRET_ARN']
        
        print(f"Connecting to database: {db_host}/{db_name}")
        
        # Retrieve credentials from Secrets Manager
        db_user, db_password = get_db_credentials(db_secret_arn)
        
        # Connect to PostgreSQL
        conn = psycopg2.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_password,
            port=5432,
            connect_timeout=10  # Timeout after 10 seconds if can't connect
        )
        
        # Enable autocommit so our DDL statements execute immediately
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("Connected to database successfully")
        
        # Create the messages table with all necessary columns
        create_table_query = """
        -- Main messages table
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            session_uuid VARCHAR(255) NOT NULL,
            msg_id VARCHAR(255) NOT NULL,
            user_query TEXT NOT NULL,
            response_content TEXT NOT NULL,
            source JSONB,  -- JSONB allows efficient querying of JSON data
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Index on session_uuid for fast lookups by session
        CREATE INDEX IF NOT EXISTS idx_session_uuid ON messages(session_uuid);
        
        -- Index on created_at for time-based queries and sorting
        CREATE INDEX IF NOT EXISTS idx_created_at ON messages(created_at);
        
        -- Index on msg_id for unique message lookups
        CREATE INDEX IF NOT EXISTS idx_msg_id ON messages(msg_id);
        
        -- Composite index for session + time queries (common pattern)
        CREATE INDEX IF NOT EXISTS idx_session_created ON messages(session_uuid, created_at);
        """
        
        print("Executing table creation SQL...")
        cursor.execute(create_table_query)
        print("Tables and indexes created successfully")
        
        # Verify the table was created
        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'messages'
        """)
        table_count = cursor.fetchone()[0]
        
        if table_count == 1:
            print("Verified: messages table exists")
        else:
            raise Exception("Table verification failed")
        
        # Clean up
        cursor.close()
        conn.close()
        
        # Return success response (CDK Provider Framework handles CloudFormation)
        return {
            'PhysicalResourceId': 'db-init-resource',
            'Data': {
                'Message': 'Database initialized successfully',
                'TablesCreated': 'messages',
                'Status': 'SUCCESS'
            }
        }
        
    except Exception as e:
        # If anything goes wrong, log the error and raise it
        # CDK Provider Framework will handle sending failure to CloudFormation
        error_message = f"Error initializing database: {str(e)}"
        print(error_message)
        
        # Raise the exception so CDK Provider Framework knows it failed
        raise Exception(error_message)