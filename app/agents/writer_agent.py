"""
Agent used to synthesize a final report using the summaries produced from the previous steps and agents.

The WriterAgent takes as input a string in the following format:
===========================================================
ORIGINAL QUERY: <original user query>

CURRENT DRAFT: <findings from initial research or drafted content>

KNOWLEDGE GAPS BEING ADDRESSED: <knowledge gaps being addressed>

NEW INFORMATION: <any additional information gathered from specialized agents>
===========================================================

The Agent then:
1. Creates an outline for the report structure
2. Generates a comprehensive markdown report based on all available information
3. Includes proper citations for sources in the format [1], [2], etc.
4. Returns a string containing the markdown formatted report

The WriterAgent defined here generates the final structured report in markdown format.
"""
from agents import Agent
from ..llm_client import reasoning_model
from datetime import datetime

PROMPT = (
    f"You are a senior researcher tasked with writing comprehensively answering a research query. Today's date is {datetime.now().strftime('%Y-%m-%d')}.\n"
    "You will be provided with the original query along with research findings put together by a research assistant.\n"
    "Your objective is to generate the final response in markdown format.\n"
    "The response should be as lengthy and detailed as possible with the information provided, focusing on answering the original query.\n"
    "In your final output, include references to the source URLs for all information and data gathered. "
    "This should be formatted in the form of a square numbered bracket next to the relevant information, "
    "followed by a list of URLs at the end of the response, per the example below.\n\n"
    "EXAMPLE REFERENCE FORMAT:\n"
    "The company has XYZ products [1]. It operates in the software services market which is expected to grow at 10% per year [2].\n\n"
    "References:\n"
    "[1] https://example.com/first-source-url\n"
    "[2] https://example.com/second-source-url\n\n"
    "GUIDELINES:\n"
    "* Answer the query directly, do not include unrelated or tangential information.\n"
    "* Adhere to any instructions on the length of your final response if provided in the user prompt.\n"
    "* If any additional guidelines are provided in the user prompt, follow them exactly and give them precedence over these system instructions.\n"
)


writer_agent = Agent(
    name="WriterAgent",
    instructions=PROMPT,
    model=reasoning_model,
)
