# Modified from NVIDIA original: NVIDIAEmbeddings → OllamaEmbeddings
# All retriever logic, chunk sizes, weights identical to original.

import os
from langchain_ollama import OllamaEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores.faiss import FAISS
from dotenv import load_dotenv
load_dotenv()


class HybridRetriever:
    def __init__(self, file_path):
        self.file_path = file_path
        self.embeddings = self.initialize_embeddings()
        self.doc_splits = self.load_and_split_documents()
        self.bm25_retriever, self.faiss_retriever = self.create_retrievers()
        self.hybrid_retriever = self.create_hybrid_retriever()

    def initialize_embeddings(self):
        # Original: NVIDIAEmbeddings(model="nvidia/llama-3.2-nv-embedqa-1b-v2", truncate="END")
        return OllamaEmbeddings(
            model=os.getenv("EMBED_MODEL", "nomic-embed-text"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        )

    def load_and_split_documents(self):
        loader = TextLoader(self.file_path)
        docs = loader.load()
        # Identical chunk sizes to original
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=20000,
            chunk_overlap=10000,
        )
        return text_splitter.split_documents(docs)

    def create_retrievers(self):
        bm25_retriever = BM25Retriever.from_documents(self.doc_splits)
        faiss_vectorstore = FAISS.from_documents(self.doc_splits, self.embeddings)
        # Identical search params to original
        faiss_retriever = faiss_vectorstore.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs={"score_threshold": 0.8},
        )
        return bm25_retriever, faiss_retriever

    def create_hybrid_retriever(self):
        # Identical 0.5/0.5 weights to original
        return EnsembleRetriever(
            retrievers=[self.bm25_retriever, self.faiss_retriever],
            weights=[0.5, 0.5],
        )

    def get_retriever(self):
        return self.hybrid_retriever
