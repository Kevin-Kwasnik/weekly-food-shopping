import os
from dotenv import load_dotenv
from strands import Agent
from strands.models.ollama import OllamaModel

#tools
import tools.kroger_products

load_dotenv()

model = OllamaModel(
    model_id="gpt-oss:120b-cloud",
    host="https://ollama.com"
)

agent = Agent(
    model=model,
    tools=[tools.kroger_products.search_kroger_products],
    system_prompt="You are an grocery shopping agent. Please prioritize the users preferences."
)


if __name__ == "__main__":
    print("Welcome to your grocery assistant! Type 'exit' to quit.")
    
    while True:
        user_input = input("\nYou: ")
        
        # Check for exit commands
        if user_input.lower() in ['exit', 'quit']:
            print("Exiting Grocery Assitant. Goodbye!")
            break
            
        # The agent maintains conversation history automatically 
        try:
            response = agent(user_input)
            print(f"\nAgent: {response}")
        except Exception as e:
            print(f"\nAgent Error: Whoops, something went wrong. ({e})")