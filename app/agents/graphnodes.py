# Modified from NVIDIA original: NVIDIARerank → FlagReranker (local cross-encoder)
# All node logic, state keys, print statements identical to original.

import os
import io
from contextlib import redirect_stdout, redirect_stderr
from multiagent import HybridRetriever
from utils import automation
from dotenv import load_dotenv
load_dotenv()


def _local_rerank(question, documents):
    """
    Local substitute for NVIDIARerank(model="nvidia/llama-3.2-nv-rerankqa-1b-v2").
    Uses FlagEmbedding cross-encoder; falls back to original order if unavailable.
    """
    try:
        from FlagEmbedding import FlagReranker
        reranker = FlagReranker(
            os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            use_fp16=True,
        )
        pairs = [(question, doc.page_content[:512]) for doc in documents]
        scores = reranker.compute_score(pairs)
        if isinstance(scores, float):
            scores = [scores]
        ranked = sorted(zip(scores, documents), key=lambda x: x[0], reverse=True)
        return [doc for _, doc in ranked]
    except Exception as e:
        print(f"Reranker unavailable ({e}), using original order")
        return documents


class Nodes:
    @staticmethod
    def retrieve(state):
        print("---RETRIEVE---")
        question = state["question"]
        path = state["path"]
        hybrid_retriever_instance = HybridRetriever(path)
        hybrid_retriever = hybrid_retriever_instance.get_retriever()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            documents = hybrid_retriever.get_relevant_documents(question)
        return {"documents": documents, "question": question}

    @staticmethod
    def rerank(state):
        print("LOCAL--RERANKER")
        question  = state["question"]
        documents = state["documents"]
        documents = _local_rerank(question, documents)
        return {"documents": documents, "question": question}

    @staticmethod
    def generate(state):
        print("GENERATE USING LLM")
        question  = state["question"]
        documents = state["documents"]
        generation = automation.rag_chain.invoke({"context": documents, "question": question})
        return {"documents": documents, "question": question, "generation": generation}

    @staticmethod
    def grade_documents(state):
        print("CHECKING DOCUMENT RELEVANCE TO QUESTION")
        question     = state["question"]
        ret_documents = state["documents"]
        filtered_docs = []
        for doc in ret_documents:
            score = automation.retrieval_grader.invoke(
                {"question": question, "document": doc.page_content}
            )
            grade = score.binary_score
            if grade == "yes":
                print("---GRADE: DOCUMENT RELEVANT---")
                filtered_docs.append(doc)
            else:
                print("---GRADE: DOCUMENT NOT RELEVANT---")
        return {"documents": filtered_docs, "question": question}

    @staticmethod
    def transform_query(state):
        print("REWRITE PROMPT")
        question  = state["question"]
        documents = state["documents"]
        better_question = automation.question_rewriter.invoke({"question": question})
        transform_count = state.get("transform_count", 0) + 1
        print(f"actual query : {question} \n Transformed query:{better_question}")
        return {"documents": documents, "question": better_question, "transform_count": transform_count}
