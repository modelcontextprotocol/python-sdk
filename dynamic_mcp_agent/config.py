import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Internal LLM Configuration ---
# Base URL for your company's custom LLM API endpoint.
# This is used by the InternalAgentLLMClient to make requests.
INTERNAL_LLM_BASE_URL = os.getenv("INTERNAL_LLM_BASE_URL")

# API Key for your company's custom LLM.
# This is used for authenticating requests to the internal LLM.
INTERNAL_LLM_API_KEY = os.getenv("INTERNAL_LLM_API_KEY")


# --- Example Tool-Specific Configuration ---
# API Key for a hypothetical external service that one of your tools might use.
# Replace 'SOME_SERVICE' with the actual service name and add more as needed.
SOME_SERVICE_API_KEY = os.getenv("SOME_SERVICE_API_KEY")

# You can add more configuration variables here as your application grows.
# For example, database connection strings, other API keys, etc.

# It's good practice to check for essential configurations and raise an error
# if they are missing, or provide sensible defaults if possible.
# For this project, the core LLM endpoint and key are essential.
if not INTERNAL_LLM_BASE_URL:
    raise ValueError("INTERNAL_LLM_BASE_URL environment variable not set. Please configure it in your .env file.")

if not INTERNAL_LLM_API_KEY:
    print("Warning: INTERNAL_LLM_API_KEY environment variable not set. This might be required for the LLM client.")
    # Depending on the LLM client, this might not strictly be an error at startup
    # if the key can be passed in other ways or is not always required.
