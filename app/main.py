import asyncio
import argparse
from .manager import DeepResearchManager
from dotenv import load_dotenv

load_dotenv(override=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Research Assistant")
    parser.add_argument("--query", type=str, help="Research query")
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
    
    args = parser.parse_args()
    
    # If no query is provided via command line, prompt the user
    query = args.query if args.query else input("What would you like to research? ")
    
    print(f"Starting deep research on: {query}")
    print(f"Max iterations: {args.max_iterations}, Max time: {args.max_time} minutes")
    
    manager = DeepResearchManager(
        max_iterations=args.max_iterations,
        max_time_minutes=args.max_time,
        verbose=args.verbose
    )
    
    report = await manager.run(
        query, 
        output_length=args.output_length, 
        output_instructions=args.output_instructions
    )

    print(
        "\n\nFINAL REPORT:\n"
        "============\n\n"
        f"{report.markdown}"
    )

if __name__ == "__main__":
    asyncio.run(main())
