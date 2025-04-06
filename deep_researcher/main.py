import asyncio
import argparse
from .iterative_research import IterativeResearcher
from .deep_research import DeepResearcher
from typing import Literal
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv(override=True)

def save_report_to_file(report: str, query: str) -> str:
    """Save the report to a markdown file with a timestamp in the filename."""
    # Create reports directory if it doesn't exist
    os.makedirs('reports', exist_ok=True)
    
    # Create a filename based on the query and timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Clean the query to make it filename-friendly
    clean_query = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in query)
    clean_query = clean_query[:50]  # Limit length
    filename = f"reports/report_{clean_query}_{timestamp}.md"
    
    # Save the report
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report)
    
    return filename

async def main() -> None:
    parser = argparse.ArgumentParser(description="Deep Research Assistant")
    parser.add_argument("--query", type=str, help="Research query")
    parser.add_argument("--model", type=str, choices=["deep", "simple"], 
                        help="Mode of research (deep or simple)", default="deep")
    parser.add_argument("--max-iterations", type=int, default=5,
                       help="Maximum number of iterations for deep research")
    parser.add_argument("--max-time", type=int, default=10,
                       help="Maximum time in minutes for deep research")
    parser.add_argument("--output-length", type=str, default="5 pages",
                       help="Desired output length for the report")
    parser.add_argument("--output-instructions", type=str, default="",
                       help="Additional instructions for the report")
    parser.add_argument("--verbose", action="store_true",
                       help="Print status updates to the console")
    parser.add_argument("--tracing", action="store_true",
                       help="Enable tracing for the research (only valid for OpenAI models)")
    parser.add_argument("--save-to-file", action="store_true",
                       help="Save the report to a markdown file")
    
    args = parser.parse_args()
    
    # If no query is provided via command line, prompt the user
    query = args.query if args.query else input("What would you like to research? ")
    
    print(f"Starting deep research on: {query}")
    print(f"Max iterations: {args.max_iterations}, Max time: {args.max_time} minutes")
    
    if args.model == "deep":
        manager = DeepResearcher(
            max_iterations=args.max_iterations,
            max_time_minutes=args.max_time,
            verbose=args.verbose,
            tracing=args.tracing
        )
        report = await manager.run(query)
    else:
        manager = IterativeResearcher(
            max_iterations=args.max_iterations,
            max_time_minutes=args.max_time,
            verbose=args.verbose,
            tracing=args.tracing
        )
        report = await manager.run(
            query, 
            output_length=args.output_length, 
            output_instructions=args.output_instructions
        )

    print("\n=== Final Report ===")
    print(report)
    
    if args.save_to_file:
        filename = save_report_to_file(report, query)
        print(f"\nReport saved to: {filename}")

# Command line entry point
def cli_entry():
    """Entry point for the command-line interface."""
    asyncio.run(main())

if __name__ == "__main__":
    cli_entry()
