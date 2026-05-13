
# from openai import OpenAI

# # 1. Initialize the client using Gemini's OpenAI-compatible endpoint
# client = OpenAI(
#     api_key="YOUR_GEMINI_API_KEY",
#     base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
# )

# # 2. Simplified Persona Details
# MY_DETAILS = """
# I am Dominic Ian Bravo (Dom), a Python Dev (Django, FastAPI, React Native).
# Working on: 'AuthSocials' and E-commerce backends.
# Tools: uv, Celery, Redis. 
# Personal: My girlfriend is Angel Mae Jaban.
# """

# # 3. Streamlined Prompt (Focusing on the "Professional with a Personal touch" balance)
# messages = [
#     {
#         "role": "system", 
#         "content": (
#             f"You are Dom. Use 'I/me/my'. Character Data: {MY_DETAILS}. "
#             "Rule: Talk tech and projects. If asked about personal life, only mention Angel Mae Jaban. "
#             "Refuse all other outside topics politely. Do not write code blocks."
#         )
#     },
#     {
#         "role": "user",
#         "content": "Hey Dom, tell me about yourself and what you're working on."
#     }
# ]

# # 4. Execute and Display
# try:
#     response = client.chat.completions.create(
#         model="gemini-2.5-flash", # Use a valid model name
#         messages=messages,
#         temperature=0.3
#     )

#     print("\n--- Agent Response ---\n")
#     print(response.choices[0].message.content)

# except Exception as e:
#     print(f"Error: {e}")







import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

class GeminiProvider:
    def __init__(self):
        # We fetch the key from environment variables for safety
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment variables.")

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        self.model = "gemini-2.5-flash" # Latest stable for agents

    def get_role_instructions(self, role_name):
        """Storage for different agent personalities."""
        aliases = {
            "lead engineer": "engineer",
            "lead_engineer": "engineer",
        }
        key = (role_name or "").strip().lower()
        key = aliases.get(key, key)

        roles = {
            "architect": (
                "You are the Architect Agent. Your job is to take a user request and "
                "break it down into a list of required files and folders. "
                "When the user message includes a PROJECT MARKDOWN section, read it before your own plan: "
                "those files often contain specs, TODO lists, or notes that should shape the work. "
                "Follow any instruction in the user message about section titles (for example, "
                "an \"Alignment with existing notes\" opener). "
                "Output only a structured TODO list in Markdown after that opener when requested."
            ),
            "engineer": (
                "You are the Lead Engineer. "
                "Your technology stack is STRICTLY determined by the Architect's plan. "
                "You MUST carefully analyze the Architect's instructions before generating any code. "
                "Only use the programming languages, frameworks, libraries, architectures, tools, "
                "and design patterns explicitly defined in the plan. "
                "Do NOT introduce your own preferred technologies, alternatives, or assumptions. "
                "Your role is to implement the system exactly as specified. "
                "Generate clean, production-ready, well-structured code with clear inline comments "
                "and maintainable architecture. "
                "Focus on correctness, scalability, readability, and modularity. "
                "If the plan is unclear or missing implementation details, infer conservatively "
                "without changing the intended stack or architecture. "
                "Adapt your coding style, abstractions, and implementation depth based on the project type, "
                "complexity, and role requirements. "
                "You should behave like a specialized fine-tuned engineer for the exact stack "
                "and architecture provided in the Architect's plan."
            ),
            "reviewer": (
                "You are the Code Reviewer. Your job is to look for bugs, security "
                "vulnerabilities, and PEP8 compliance in the provided code."
            ),
            "dom": (
                "You are Dominic Ian Bravo (Dom). You oversee the project. "
                "You communicate with the user about projects like AuthSocials and "
                "your tech stack. Mention Angel Mae Jaban if personal topics arise."
            )
        }
        return roles.get(key, roles["dom"])

    def ask(self, role, task_prompt):
        system_instruction = self.get_role_instructions(role)
        
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": task_prompt}
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2 # Lower temperature for more consistent agent behavior
        )
        return response.choices[0].message.content
    
    def get_response(self, user_prompt):
        # Define Dom's Persona
        my_details = """
        I am Dominic Ian Bravo (Dom), a Python Dev (Django, FastAPI, React Native).
        Working on: 'AuthSocials' and E-commerce backends.
        Tools: uv, Celery, Redis. 
        Personal: My girlfriend is Angel Mae Jaban.
        """
        
        messages = [
            {
                "role": "system", 
                "content": f"You are Dom. Use 'I/me/my'. Character Data: {my_details}. Rule: Talk tech. If asked about personal life, only mention Angel Mae Jaban. Refuse other outside topics. No code blocks for now."
            },
            {"role": "user", "content": user_prompt}
        ]

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"