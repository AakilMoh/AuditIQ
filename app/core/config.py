import os
from dotenv import load_dotenv
from openai import OpenAI
import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings

#Loading enviroment variables globally
load_dotenv()

# (Goes up from config.py -> core -> app -> mini_collectiq)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#Centralizing Database Paths
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", os.path.join(BASE_DIR, "databases", "collectiq.sqlite"))
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", os.path.join(BASE_DIR, "databases", "chromadb"))

# Centralized Model Definitions
PRIMARY_AUDITOR_MODEL = os.getenv("PRIMARY_AUDITOR_MODEL", "meta/llama-3.1-70b-instruct")
VERIFIER_MODEL = os.getenv("VERIFIER_MODEL", "google/gemma-4-31b-it")

#Ensuring required directories exist before the app boots
os.makedirs("databases", exist_ok=True)
os.makedirs("logs", exist_ok=True)

#Initializing Global Nvidia Client
llm_client = OpenAI(
    base_url = "https://integrate.api.nvidia.com/v1",
    api_key = os.getenv("NVIDIA_API_KEY")
)

#Audio Client Groq
audio_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY")
)

#Defining the Global Embedding Function
class NvidiaEmbeddingFunction(EmbeddingFunction):
    def __init__(self):
        self.client = llm_client
        
    def __call__(self, input: Documents) -> Embeddings:
        response = self.client.embeddings.create(
            model="nvidia/nv-embed-v1",
            input=input,
            encoding_format="float"
        )
        return [r.embedding for r in response.data]

nvidia_ef = NvidiaEmbeddingFunction()