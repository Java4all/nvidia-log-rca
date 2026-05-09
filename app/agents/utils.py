# Modified from NVIDIA original: ChatNVIDIA → ChatOllama
# All prompts, chain structure, Nodeoutputs class identical to original.

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from binary_score_models import GradeAnswer, GradeDocuments, GradeHallucinations
import os
from dotenv import load_dotenv
load_dotenv()
import json


class Nodeoutputs:
    def __init__(self, model, prompts_file):
        self.llm = ChatOllama(
            model=model,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
            temperature=0,
        )
        self.prompts = self.load_prompts(prompts_file)
        self.setup_prompts()

    def load_prompts(self, prompts_file):
        with open(prompts_file, 'r') as file:
            return json.load(file)

    def setup_prompts(self):
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self.prompts["qa_system_prompt"]),
            ("user",   self.prompts["qa_user_prompt"]),
        ])
        self.rag_chain = self.prompt | self.llm | StrOutputParser()

        re_write_prompt = ChatPromptTemplate.from_messages([
            ("system", self.prompts["re_write_system"]),
            ("human",  self.prompts["re_write_human"]),
        ])
        self.question_rewriter = re_write_prompt | self.llm | StrOutputParser()

        grade_prompt = ChatPromptTemplate.from_messages([
            ("system", self.prompts["grade_system"]),
            ("human",  self.prompts["grade_human"]),
        ])
        self.retrieval_grader = grade_prompt | self.llm.with_structured_output(GradeDocuments)

        hallucination_prompt = ChatPromptTemplate.from_messages([
            ("system", self.prompts["hallucination_system"]),
            ("human",  self.prompts["hallucination_human"]),
        ])
        self.hallucination_grader = hallucination_prompt | self.llm.with_structured_output(GradeHallucinations)

        answer_prompt = ChatPromptTemplate.from_messages([
            ("system", self.prompts["answer_system"]),
            ("human",  self.prompts["answer_human"]),
        ])
        # original graphedges calls .invoke() and checks "yes" in score_text.lower()
        # so we keep plain StrOutputParser to match that contract
        self.answer_grader = answer_prompt | self.llm | StrOutputParser()

    def format_docs(self, docs):
        return "\n\n".join(doc.page_content for doc in docs)


# Global singleton — mirrors original pattern
model        = os.getenv("LLM_MODEL", "mistral:7b-instruct-q4_K_M")
prompts_file = os.path.join(os.path.dirname(__file__), "prompt.json")
automation   = Nodeoutputs(model, prompts_file)
