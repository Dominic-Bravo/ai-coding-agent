from llm.provider import GeminiProvider
from rich.console import Console
from rich.panel import Panel

console = Console()

def save_to_file(filename, content):
    # Ensure it's in the current directory
    with open(filename, "w") as f:
        f.write(content)
    console.print(f"[bold green]💾 Saved to {filename}[/bold green]")

def main():
    ai = GeminiProvider()
    
    console.print(Panel("[bold magenta]Multi-Agent Coding System Active[/bold magenta]"))
    
    user_request = console.input("[bold cyan]What project are we building today? [/bold cyan]")

    # STEP 1: The Architect Plans
    with console.status("[bold yellow]Architect is planning..."):
        plan = ai.ask("architect", f"Plan this project: {user_request}")
    console.print(Panel(plan, title="Architect's Blueprint", border_style="yellow"))

    # # STEP 2: Dom Explains the Vibe
    # with console.status("[bold green]Dom is checking context..."):
    #     commentary = ai.ask("dom", f"How does this fit our stack? Project: {user_request}")
    # console.print(Panel(commentary, title="Dom's Thoughts", border_style="green"))

    # STEP 3: The Engineer Starts Coding (Example: First task)
    with console.status("[bold blue]Engineer is writing code..."):
        engineer_code = ai.ask("lead engineer", f"Based on this plan, write the main entry point: {plan}")
    console.print(Panel(engineer_code, title="Engineer's Output", border_style="blue"))
    
    # Inside manager.py

    with console.status("[bold red]Reviewer is analyzing code..."):
        # The reviewer sees the code AND the original plan to ensure requirements were met
        review_results = ai.ask("reviewer", f"Target Code: {engineer_code}\nOriginal Plan: {plan}")
    
    console.print(Panel(review_results, title="Step 3: Code Review Feedback", border_style="red"))

    final_output = engineer_code
    
    # 4. (Optional) AUTO-FIX PHASE
    if "FIX REQUIRED" in review_results.upper() or "BUG" in review_results.upper():
        with console.status("[bold magenta]Engineer is applying fixes based on review..."):
            final_code = ai.ask("engineer", f"Fix this code based on these review comments: {review_results}\nCode: {engineer_code}")
        console.print(Panel(final_code, title="Step 4: Final Refined Code", border_style="green"))

    # Save a record of the final result
    save_to_file("final_output.txt", final_output)
    
if __name__ == "__main__":
    main()