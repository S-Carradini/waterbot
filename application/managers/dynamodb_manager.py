import boto3
import datetime
import re
import mappings.custom_tags as custom_tags


class DynamoDBManager():
    def __init__(self, messages_table, *args, **kwargs):
        self.client = boto3.resource('dynamodb', region_name='us-west-2')
        self.messages_table=messages_table
        
        super().__init__(*args,**kwargs)
    
    async def sanitize_html(self,text_to_sanitize):
        """
        Sanitizes the user input by removing all HTML tags except for a whitelist.
        
        Args:
            user_input (str): The user input to be sanitized.
        
        Returns:
            str: The sanitized user input.
        """
        if text_to_sanitize is None:
            return None
        
        # Define a whitelist of allowed HTML tags
        allowed_tags = custom_tags.allow_list
        
        # Use a regular expression to remove all HTML tags except the whitelisted ones
        sanitized_input = re.sub(r'<(?!/?(' + '|'.join(allowed_tags) + r')\b)(?:[^>"\']+|"[^"]*"|\'[^\']*\')*>',
                                '', text_to_sanitize)
        
        return sanitized_input
    
    #Deprecated function : Replaced with log_message for PostgreSQL
    async def write_msg(self, 
                        session_uuid, 
                        msg_id, 
                        user_query, 
                        response_content, 
                        source=None, 
                        rating=None, 
                        comment=None ):
        
        # clean of any injected HTML
        comment=await self.sanitize_html(comment)

        messages_table = self.client.Table(self.messages_table)
        msg_id=str(msg_id )

        # Get the current timestamp
        timestamp = datetime.datetime.now()
        # Convert timestamp to ISO 8601 string
        iso_string = timestamp.isoformat()

        # Insert into dynamodb all items
        messages_table.put_item(
            Item={
                'sessionId': session_uuid,
                'timestamp': iso_string,
                'msgId': msg_id,
                'userQuery': user_query,
                'responseContent': response_content,
                'source': source,
                'reaction': rating,
                'userComment': comment
            }
        )

    async def update_rating_fields(self, session_uuid, message_id, reaction, userComment):
        messages_table = self.client.Table(self.messages_table)
        message_id=str(message_id )

        # clean of any injected HTML
        userComment=await self.sanitize_html(userComment)

        if reaction is not None:
            try:
                response = messages_table.update_item(
                    Key={
                        'sessionId': session_uuid,
                        'msgId': message_id
                    },
                    UpdateExpression='SET reaction = :r',
                    ExpressionAttributeValues={
                        ':r': reaction,
                    },
                    ReturnValues='UPDATED_NEW'
                )
                return response
            except Exception as e:
                print(f"Error updating rating fields: {e}")
                return None
            
        if userComment is not None:
            try:
                response = messages_table.update_item(
                    Key={
                        'sessionId': session_uuid,
                        'msgId': message_id
                    },
                    UpdateExpression='SET userComment = :r',
                    ExpressionAttributeValues={
                        ':r': userComment
                    },
                    ReturnValues='UPDATED_NEW'
                )
                return response
            except Exception as e:
                print(f"Error updating rating fields: {e}")
                return None