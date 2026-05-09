from .base import ModelAdapter
import json
from openai import OpenAI
import re
from langchain_openai import OpenAIEmbeddings
from datetime import datetime
import asyncio


class OpenAIAdapter(ModelAdapter):
    def __init__(self, model_id="gpt-3.5-turbo", region=None, *args, **kwargs):
        self.embeddings = OpenAIEmbeddings()
        self.model_id=model_id
        self.client = OpenAI()
        super().__init__(*args,**kwargs)
    
    def get_embeddings( self ):
        return self.embeddings

    async def generate_llm_payload(self, messages, temperature ):
        return json.dumps(
            {
                "messages":messages,
                "temperature": temperature,
            }
        )  
    

    async def get_llm_detailed_body( self, kb_data, user_query,bot_response, max_tokens=512, temperature=.5, language='en' ):
        system_prompt=await self.get_chat_detailed_prompt(kb_data, language=language)
        messages=[]
        messages.append(
            {
                'role':'system',
                'content':system_prompt
            }
        )
        inject_user_query="<NEXTSTEPS_REQUEST>Provide me the action items<NEXTSTEPS_REQUEST>"
        messages=await self.build_message_chain_for_action(user_query=user_query,bot_response=bot_response,inject_user_query=inject_user_query,messages=messages)

        openai_payload = await self.generate_llm_payload(messages=messages, temperature=temperature)

        return openai_payload
    

    async def get_llm_nextsteps_body( self, kb_data, user_query,bot_response, max_tokens=512, temperature=.5, language='en' ):
        system_prompt=await self.get_action_item_prompt(kb_data, language=language)


        messages=[]
        messages.append(
            {
                'role':'system',
                'content':system_prompt
            }
        )
        inject_user_query="<NEXTSTEPS_REQUEST>Provide me the action items<NEXTSTEPS_REQUEST>"
        messages=await self.build_message_chain_for_action(user_query=user_query,bot_response=bot_response,inject_user_query=inject_user_query,messages=messages)
        
        openai_payload = await self.generate_llm_payload(messages=messages, temperature=temperature)

        return openai_payload
    

    async def get_llm_body( self, kb_data, chat_history, max_tokens=512, temperature=.5, endpoint_type="default" ):
        # system_prompt = """
        # You are a helpful assistant named Blue that provides information about water in Arizona.

        # You will be provided with Arizona water-related queries.

        # The governor of Arizona is Katie Hobbs.

        # When asked the name of the governor or current governor, you should respond with the name Katie Hobbs.

        # For any other inquiries regarding the names of elected officials excluding the name of the governor, you should respond: 'The most current information on the names of elected officials is available at az.gov.'

        # Verify not to include any information that is irrelevant to the current query.

        # Use the following knowledge: 
        # <knowledge>
        # {kb_data}
        # </knowledge>

        # You should answer in 4-5 sentences in a friendly tone and include details within those 4-5 sentences. You can include more information when available. Avoid lists.

        # For longer responses, please add a paragraph break to separate distinct points. Also, add a line break between the main response and the closing line.

        # At the end of each message, please include - 

        # "I would love to tell you more! Just click the buttons below or ask a follow-up question."
        # """

        # system_prompt=system_prompt.format(kb_data=kb_data)


        # System prompt based on endpoint type
        if endpoint_type == "riverbot":
            # Riverbot system prompt
            system_prompt = f"""You are River. Answer as a river would."""
        elif endpoint_type == "spanish":
            system_prompt = f"""
        Eres una asistente amable llamada Blue que ofrece información sobre el agua en Arizona.

        Responde siempre en español (registro neutral) y adapta los ejemplos a residentes de Arizona.

        Cuando te pregunten por nombres de funcionarios electos, excepto la gobernadora, responde: "La información más actualizada sobre los funcionarios electos está disponible en az.gov."

        Evita incluir información irrelevante o especulativa.

        Utiliza el siguiente conocimiento para responder las preguntas:
        <knowledge>
        {kb_data}
        </knowledge>

        Responde en 150 palabras o menos con un tono cercano, sin usar listas.

        En respuestas más largas, separa los párrafos con saltos de línea y agrega un salto adicional antes de la frase de cierre.

        Al final de cada mensaje incluye:

        "¡Me encantaría contarte más! Solo haz clic en los botones de abajo o haz una pregunta de seguimiento."
        """
        else:
            system_prompt = f"""
        You are a helpful assistant named Blue that provides information about water in Arizona.

        You will be provided with Arizona water-related queries.

        For any other inquiries regarding the names of elected officials excluding the name of the governor, you should respond: 'The most current information on the names of elected officials is available at az.gov.'

        Verify not to include any information that is irrelevant to the current query.

        Use the following knowledge to answer questions: 
        <knowledge>
        {kb_data}
        </knowledge>

        You should answer in 150 words or less in a friendly tone and include details within the word limit. 

        Avoid lists.
        
        For longer responses (2 sentences), please separate each paragraph with a line break to improve readability. Additionally, add a line break before the closing line.

        At the end of each message, please include - 

        "I would love to tell you more! Just click the buttons below or ask a follow-up question."
        """

        messages=[
            {
                "role":"system",
                "content":system_prompt
            }
        ]
        for message in chat_history:
            messages.append(message)
        
        openai_payload = await self.generate_llm_payload(messages=messages, temperature=temperature)

        return openai_payload

    async def generate_response(self,llm_body):
        llm_body = json.loads(llm_body)

        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model_id,
            messages=llm_body["messages"],
            temperature=llm_body["temperature"],
            stream=False,
        )

        response_body = response.choices[0].message.content

        response_content = re.sub(r'\n', '<br>', response_body)

        return response_content
    
    # async def safety_checks(self, user_query):
    #     async def ModerationCheck(user_query):
    #         #print('timestamp starting moderation check: ',datetime.now().strftime(' %H:%M:%S'))
    #         response = self.client.moderations.create(input=user_query)
    #         moderation_output = response.results[0].flagged
    #         #print('timestamp exiting moderation check: ',datetime.now().strftime(' %H:%M:%S'))
    #         #print(moderation_output)
    #         return moderation_output
    #     async def UserIntentCheck(user_query,temperature=.5,max_tokens=512):
    #         system_prompt=await self.get_intent_system_prompt()
            
    #         messages=[
    #             {
    #                 "role":"system",
    #                 "content":system_prompt
    #             }
    #         ]
    #         messages.append(
    #             {
    #                 'role':'user',
    #                 'content':user_query
    #             }
    #         )

            
    #         response = self.client.chat.completions.create(
    #             model=self.model_id,
    #             messages=messages,
    #             temperature=temperature,
    #             max_tokens=max_tokens,
    #             stream=False 
    #         )


    #         return response.choices[0].message.content
    
    #     # Run both coroutines concurrently
    #     moderation_result, intent_result = await asyncio.gather(
    #         ModerationCheck(user_query),
    #         UserIntentCheck(user_query)
    #     )


    #     return moderation_result,intent_result

    async def safety_checks(self, user_query):
        """
        Bypass safety checks by returning safe, default values.
        """
        # Always return False for moderation_result (no moderation issues)
        # Return a safe, valid JSON string for intent_result
        moderation_result = False
        intent_result = json.dumps({
            "user_intent": 0,         # No harmful user intent
            "prompt_injection": 0,    # No prompt injection detected
            "unrelated_topic": 0      # No unrelated topic flagged
        })
        return moderation_result, intent_result