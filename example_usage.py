import asyncio
from app.manager import DeepResearchManager

manager = DeepResearchManager(
    max_iterations=5,
    max_time_minutes=10,
    verbose=True
)

query = "Write a report on Plato - who was he, what were his main works " \
        "and what are the main philosophical ideas he's known for"
output_length = "1000 words"
output_instructions = ""

report = asyncio.run(
    manager.run(
        query, 
        output_length=output_length, 
        output_instructions=output_instructions
    )
)

print(report.markdown)