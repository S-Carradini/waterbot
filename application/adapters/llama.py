from .base import ModelAdapter
import json
import os
import re
import asyncio

from openai import OpenAI
from langchain_openai import OpenAIEmbeddings


class LlamaAdapter(ModelAdapter):
    def __init__(
        self,
        model_id: str | None = None,
        *args,
        **kwargs,
    ):
        # Llama model id to pass to the OpenAI-compatible chat completions endpoint.
        self.model_id = model_id or os.getenv(
            "LLAMA_MODEL_ID",
            "meta-llama/Llama-3.3-70B-Instruct:novita",
        )

        # OpenAI-compatible auth/base_url configuration.
        # NOTE: This adapter expects your Llama provider to support the OpenAI
        # chat/completions API shape.
        api_key = os.getenv("LLAMA_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("LLAMA_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://router.huggingface.co/v1"

        if not api_key:
            raise ValueError("LLAMA_API_KEY (or OPENAI_API_KEY fallback) must be set for LlamaAdapter.")

        # Configure embeddings to use the same OpenAI-compatible endpoint/key as the chat model.
        # This avoids requiring `OPENAI_API_KEY` when `LLM_PROVIDER=llama`.
        self.embeddings = OpenAIEmbeddings(api_key=api_key, base_url=base_url)

        client_kwargs: dict[str, str] = {"api_key": api_key, "base_url": base_url}
        self.client = OpenAI(**client_kwargs)
        super().__init__(*args, **kwargs)

    def get_embeddings(self):
        return self.embeddings

    async def generate_llm_payload(self, messages, temperature):
        return json.dumps(
            {
                "messages": messages,
                "temperature": temperature,
            }
        )

    async def get_llm_detailed_body(
        self,
        kb_data,
        user_query,
        bot_response,
        max_tokens=512,
        temperature=0.5,
        language="en",
    ):
        system_prompt = await self.get_chat_detailed_prompt(kb_data, language=language)
        messages = []
        messages.append(
            {
                "role": "system",
                "content": system_prompt,
            }
        )
        inject_user_query = "<NEXTSTEPS_REQUEST>Provide me the action items<NEXTSTEPS_REQUEST>"
        messages = await self.build_message_chain_for_action(
            user_query=user_query,
            bot_response=bot_response,
            inject_user_query=inject_user_query,
            messages=messages,
        )

        llama_payload = await self.generate_llm_payload(messages=messages, temperature=temperature)
        return llama_payload

    async def get_llm_nextsteps_body(
        self,
        kb_data,
        user_query,
        bot_response,
        max_tokens=512,
        temperature=0.5,
        language="en",
    ):
        system_prompt = await self.get_action_item_prompt(kb_data, language=language)

        messages = []
        messages.append(
            {
                "role": "system",
                "content": system_prompt,
            }
        )
        inject_user_query = "<NEXTSTEPS_REQUEST>Provide me the action items<NEXTSTEPS_REQUEST>"
        messages = await self.build_message_chain_for_action(
            user_query=user_query,
            bot_response=bot_response,
            inject_user_query=inject_user_query,
            messages=messages,
        )

        llama_payload = await self.generate_llm_payload(messages=messages, temperature=temperature)
        return llama_payload

    async def get_llm_body(
        self,
        kb_data,
        chat_history,
        max_tokens=512,
        temperature=0.5,
        endpoint_type="default",
    ):
        # System prompt based on endpoint type
        if endpoint_type == "riverbot":
            system_prompt = "You are River. Answer as a river would."
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

        messages = [{"role": "system", "content": system_prompt}]
        for message in chat_history:
            messages.append(message)

        llama_payload = await self.generate_llm_payload(messages=messages, temperature=temperature)
        return llama_payload

    async def generate_response(self, llm_body):
        llm_body = json.loads(llm_body)

        # Wrap blocking LLM call in a thread (important under uvicorn/async).
        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model_id,
            messages=llm_body["messages"],
            temperature=llm_body["temperature"],
            stream=False,
        )

        response_body = response.choices[0].message.content
        response_content = re.sub(r"\n", "<br>", response_body)
        return response_content

    async def safety_checks(self, user_query):
        """
        Bypass safety checks by returning safe, default values.
        Kept identical to `application/adapters/openai.py`.
        """
        moderation_result = False
        intent_result = json.dumps(
            {
                "user_intent": 0,
                "prompt_injection": 0,
                "unrelated_topic": 0,
            }
        )
        return moderation_result, intent_result

