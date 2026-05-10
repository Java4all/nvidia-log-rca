# Modified from NVIDIA original: optional ChatOllama OR ChatNVIDIA
# Prompts and chain structure match upstream GenerativeAIExamples BAT.AI sample.

import json
import os

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_ollama import ChatOllama

from binary_score_models import GradeAnswer, GradeDocuments, GradeHallucinations

load_dotenv()


def _build_llm(ollama_model: str):
    """LLM for all chains — Ollama (local) or NVIDIA AI Endpoints (cloud/NIM)."""
    backend = os.getenv("LLM_BACKEND", "ollama").lower().strip()

    if backend == "nvidia":
        api_key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "LLM_BACKEND=nvidia requires NVIDIA_API_KEY in the environment."
            )
        os.environ["NVIDIA_API_KEY"] = api_key
        model = (
            os.getenv("NVIDIA_LLM_MODEL", "").strip()
            or "nvidia/llama-3.3-nemotron-super-49b-v1.5"
        )
        from langchain_nvidia_ai_endpoints import ChatNVIDIA

        return ChatNVIDIA(api_key=api_key, model=model)

    return ChatOllama(
        model=ollama_model,
        base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        temperature=0,
    )


class Nodeoutputs:
    def __init__(self, model: str, prompts_file: str):
        self.llm = _build_llm(model)
        self.prompts = self.load_prompts(prompts_file)
        self.setup_prompts()

    def load_prompts(self, prompts_file):
        with open(prompts_file, "r") as file:
            return json.load(file)

    def setup_prompts(self):
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.prompts["qa_system_prompt"]),
                ("user", self.prompts["qa_user_prompt"]),
            ]
        )
        self.rag_chain = self.prompt | self.llm | StrOutputParser()

        re_write_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.prompts["re_write_system"]),
                ("human", self.prompts["re_write_human"]),
            ]
        )
        self.question_rewriter = re_write_prompt | self.llm | StrOutputParser()

        grade_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.prompts["grade_system"]),
                ("human", self.prompts["grade_human"]),
            ]
        )
        self.retrieval_grader = grade_prompt | self.llm.with_structured_output(
            GradeDocuments
        )

        hallucination_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.prompts["hallucination_system"]),
                ("human", self.prompts["hallucination_human"]),
            ]
        )
        self.hallucination_grader = hallucination_prompt | self.llm.with_structured_output(
            GradeHallucinations
        )

        answer_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.prompts["answer_system"]),
                ("human", self.prompts["answer_human"]),
            ]
        )
        # graphedges checks "yes" in plain text — keep StrOutputParser (fork behavior)
        self.answer_grader = answer_prompt | self.llm | StrOutputParser()

    def format_docs(self, docs):
        return "\n\n".join(doc.page_content for doc in docs)


# Global singleton — mirrors original pattern
model = os.getenv("LLM_MODEL", "mistral:7b-instruct-q4_K_M")
prompts_file = os.path.join(os.path.dirname(__file__), "prompt.json")
automation = Nodeoutputs(model, prompts_file)
