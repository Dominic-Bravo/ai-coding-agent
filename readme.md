🛠️ Setup
1. Prerequisites
Python 3.8+

An API Key from Google AI Studio

2. Install Dependencies
Bash
pip install openai rich
3. Configure Environment
Set your API key in your terminal session:
Windows (CMD):

DOS
set GEMINI_API_KEY=your_actual_key_here
PowerShell:

PowerShell
$env:GEMINI_API_KEY="your_actual_key_here"
🖥️ Usage
Run the agent from the root directory:

Bash
python manager.py
Enter your project idea (e.g., "Create a simple CRUD API for a bookstore").

The Architect will provide a plan.

The Engineer will draft the code.

The Reviewer will check for "STATUS: FIX REQUIRED".

The final result will be saved to final_output.txt.

🧠 Role Definitions (llm/provider.py)
The system utilizes a central "Role Factory":

Architect: The Planner.

Engineer: The Builder (Stack-agnostic).

Reviewer: The Quality Gate.

Dom: The Project Lead & Interface.

🛡️ Security Note
Never hardcode your API key in provider.py. This project is designed to read the key from environment variables to prevent accidental leaks.
"""