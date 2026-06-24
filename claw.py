import os
import requests 
from typing import Annotated
from dotenv import load_dotenv
import asyncio

# Import the harness and a web-search capable client
from agent_framework._harness._agent import create_harness_agent
from agent_framework.openai import OpenAIChatClient

# 1. Load your local .env file variables
load_dotenv()
ASHBY_API_KEY = os.getenv("ASHBY_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 2. Setup your OpenAI client for web search support
client = OpenAIChatClient(api_key=OPENAI_API_KEY)

# 3. Define the Ashby API tool
def query_ashby_jobs(
    status: Annotated[str, "Filter jobs by status, e.g., 'Open' or 'Closed'."] = "Open"
) -> dict:
    """Queries the Ashby API to retrieve a list of job postings."""
    url = "https://api.ashbyhq.com/jobBoard.listJobs" 
    headers = {"Authorization": f"Basic {ASHBY_API_KEY}"}
    payload = {"status": status}
    
    response = requests.post(url, json=payload, headers=headers)
    return response.json()

# 4. Wire everything into the agent harness
ashby_agent = create_harness_agent(
    client=client,
    agent_instructions="""
    You are an Ashby API assistant. 
    When asked about how to use an endpoint, you MUST use your web search tool 
    to read the live public documentation located at: https://developers.ashbyhq.com/
    before generating an API request payload.
    """,
    tools=[query_ashby_jobs],
    disable_web_search=False,
)

# 5. Interactive loop
async def main():
    print("🤖 Ashby ATS Claw Console Initialized.")
    print("Type your request below (or type 'quit' to exit):")
    print("-" * 50)
    
    session = ashby_agent.create_session()
    
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ['quit', 'exit']:
                break
                
            if not user_input.strip():
                continue
                
            print("\nClaw thinking...")
            response = await ashby_agent.get_response(session=session, prompt=user_input)
            print(f"\nClaw: {response.text}")
            
        except Exception as e:
            print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())