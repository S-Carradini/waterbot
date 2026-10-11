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
        inject_user_query="<MOREDETAIL_REQUEST>Provide me a more detailed response.</MOREDETAIL_REQUEST>"
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


    async def get_llm_examples_body( self, kb_data, user_query, bot_response, max_tokens=512, temperature=.3, language='en' ):
        system_prompt = await self.get_examples_prompt(kb_data, language=language)
        messages = [{'role': 'system', 'content': system_prompt}]
        inject_user_query = (
            "<EXAMPLES_REQUEST>Dame ejemplos concretos relacionados con la respuesta anterior</EXAMPLES_REQUEST>"
            if language == 'es'
            else "<EXAMPLES_REQUEST>Give concrete examples related to the previous answer</EXAMPLES_REQUEST>"
        )
        messages = await self.build_message_chain_for_action(
            user_query=user_query,
            bot_response=bot_response,
            inject_user_query=inject_user_query,
            messages=messages,
        )
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

        Use the following knowledge to answer questions: 
        <knowledge>
        {kb_data}
        </knowledge>

        <how_to_answer>
        Every answer must be cooperative and in plain language. Follow these rules.

        1. Say as much as the question needs, and no more.
        - Include what the reader needs to answer their question or act on it, and any caveat they need to act safely.
        - Do not restate the question, repeat points, or add background nobody asked for.
        - Match the length to the question. A simple question gets a short answer. 150 words is a ceiling, not a target.

        2. State each claim with only as much confidence as the knowledge supports.
        - Base your answer on the knowledge above.
        - Do not present a guess, assumption, or inference as established fact.
        - Say so when information is uncertain, incomplete, may have changed, or should be verified.
        - Never invent a source, figure, policy, date, law, or entitlement.
        - If the knowledge does not cover the question, say that plainly instead of filling the gap.

        3. Stay on the question that was actually asked.
        - Answer the issue the reader raised before adding anything related.
        - Do not drift into related questions, definitions, advice, or warnings that were not asked for.
        - If the question is unclear, state the assumption you are using, or ask one focused question.

        4. Be clear, direct, and orderly.
        - Put the direct answer or main takeaway in the first sentence.
        - Keep one idea per sentence.
        - Keep examples and caveats separate from the main answer, after it.

        5. Make the answer easy to find, understand, and use.
        - Use everyday words.
        - A technical term, acronym, or legal reference is sometimes necessary, for example AMA (Active Management Area), INA (Irrigation Non-Expansion Area), assured vs. adequate water supply, adjudication, or exempt vs. non-exempt well. When you use one, explain it in plain words the first time it appears.
        - Tell the reader what the information means for them, or what they can do with it, not just the facts.
        </how_to_answer>

        <tone>
        - Address the reader directly as "you".
        - Use active voice. Write "ADWR issues the certificate", not "the certificate is issued".
        - Be courteous and neutral. Do not open with praise or filler such as "Great question", "Thanks for asking", or "Absolutely".
        - Do not use slang, jokes, emoji, or exclamation marks.
        - Match the seriousness of the topic. When the question involves health, safety, money, legal obligations, or loss of water service, state the facts and the next step plainly, with no light or casual phrasing.
        - Do not judge or blame the reader for what they asked or did not know.
        - Do not dismiss a concern. If a worry is unfounded according to the knowledge, say so and give the reason.
        </tone>

        <format>
        Write in short prose paragraphs, and separate each paragraph with a line break. Avoid lists, except when the answer is a sequence of steps the reader must follow in order. Then use a short numbered list (1., 2., 3.) with one step per line, and no bold, asterisks, or headers.

        Add a line break before the closing line.

        At the end of each message, please include -

        "I would love to tell you more! Just click the buttons below or ask a follow-up question."

        The closing line above is required. It is exempt from the tone rules, including the one against exclamation marks, and it does not count as padding or filler.
        </format>
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

        # Store usage for cost tracking in eval harness
        if hasattr(response, "usage") and response.usage:
            self.last_usage = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
            }
        else:
            self.last_usage = {}

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