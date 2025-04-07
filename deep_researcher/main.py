import asyncio
import argparse
from .iterative_research import IterativeResearcher
from .deep_research import DeepResearcher
from typing import Literal
from dotenv import load_dotenv
import os
from datetime import datetime
import sys

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

async def main():
    """Main entry point for the deep researcher CLI."""
    parser = argparse.ArgumentParser(description="Deep Researcher CLI")
    parser.add_argument("--query", type=str, help="The query to research")
    parser.add_argument("--iterations", type=int, default=5, help="Maximum number of research iterations")
    parser.add_argument("--max-iterations", type=int, default=5, help="Alias for --iterations")
    parser.add_argument("--max-time", type=int, default=10, help="Maximum time in minutes")
    parser.add_argument("--model", type=str, default="simple", choices=["simple", "complex"], help="Model type to use")
    parser.add_argument("--output-length", type=str, default="", help="Description of the desired output length")
    parser.add_argument("--output-instructions", type=str, default="", help="Instructions for formatting the final report")
    parser.add_argument("--context", type=str, default="", help="Additional context to provide for the research")
    parser.add_argument("--background", type=str, default="", help="Alias for --context")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--trace", action="store_true", help="Enable tracing with the OpenAI SDK")
    parser.add_argument("--use-claude", action="store_true", help="Use Claude with MCP for research")
    parser.add_argument("--output", type=str, default="-", help="Output file path (- for stdout)")
    args = parser.parse_args()

    # Check that a query was provided
    if not args.query:
        parser.error("The --query argument is required")

    # Support both --iterations and --max-iterations
    max_iterations = args.iterations if args.iterations != 5 else args.max_iterations
    
    # Support both --context and --background
    background_context = args.context if args.context else args.background

    # Initialize the deep researcher
    try:
        manager = IterativeResearcher(
            max_iterations=max_iterations,
            max_time_minutes=args.max_time,
            verbose=args.verbose,
            tracing=args.trace,
            use_claude=args.use_claude
        )
        
        # Run the research process
        report = await manager.run(
            query=args.query,
            output_length=args.output_length,
            output_instructions=args.output_instructions,
            background_context=background_context
        )
        
        # Write the report to stdout or a file
        if args.output == "-":
            print(report)
        else:
            with open(args.output, "w") as f:
                f.write(report)
                
        return 0
    except Exception as e:
        print(f"Error running research: {str(e)}", file=sys.stderr)
        if args.verbose:
            import traceback
            print(traceback.format_exc(), file=sys.stderr)
        return 1

# Command line entry point
def cli_entry():
    """Entry point for the command-line interface."""
    asyncio.run(main())

if __name__ == "__main__":
    cli_entry()
