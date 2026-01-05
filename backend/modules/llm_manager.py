from typing import Iterable
from langchain.chat_models.base import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
import re
from logger import logger


class SimpleAgent:

    def __init__(
        self,
        model: BaseChatModel,
        system_prompt: str = "You are a friendly conversational partner who always answers in plain text without using any Markdown symbols like #, *, or backticks, or emojis; avoid lists, titles, or structured formatting and just talk in a flowing, natural way; keep your tone casual, like chatting with a friend, using simple everyday language and short sentences, with room for natural fillers such as “well,” “you know,” or “sort of,” while avoiding academic or overly polished style.",
    ):
        self.model = model
        system_prompt = SystemMessage(content=system_prompt)
        self.session_history = [system_prompt]

    def _filter_response(self, response: str) -> str:
        """Filter out unwanted characters from the response."""
        filtered_response = response.replace("#", "").replace("**", "").replace("`", "")
        # Replace "number." with "number" to avoid markdown-like numbering
        filtered_response = re.sub(r"(\d+)\.", r"\1", filtered_response)
        return filtered_response

    def generate_stream(self, input: str) -> Iterable[str]:
        user_prompt = HumanMessage(input)
        self.session_history.append(user_prompt)
        response = self.model.stream(self.session_history)
        self.session_history.append(AIMessage(content=""))
        try:
            for chunk in response:
                filtered_chunk = self._filter_response(chunk.content)
                self.session_history[-1].content += filtered_chunk
                yield filtered_chunk
            logger.debug(f"SimpleAgent stream completed, full history: {self.session_history}")
        except GeneratorExit:
            logger.warning("SimpleAgent stream was closed before completion")
            raise
        except Exception as e:
            logger.error(f"SimpleAgent stream error: {e}")
            raise

    def copy(self) -> "SimpleAgent":
        return SimpleAgent(self.model, self.session_history[0].content)
