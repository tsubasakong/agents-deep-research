"""
Example usage of the DeepResearcher to produce a report.

See deep_output.txt for the console output from running this script, and deep_output.pdf for the final report
"""

import asyncio
from deep_researcher import DeepResearcher

manager = DeepResearcher(
    max_iterations=3,
    max_time_minutes=10,
    verbose=True,
    tracing=True
)

query = "Write a comprehensive report on the company Buena (buena.com) from an investor's perspective, including the company's history, products, financials, market (size, growth and trends) and competitors."

report = asyncio.run(
    manager.run(
        query
    )
)

print("\n=== Final Report ===")
print(report)