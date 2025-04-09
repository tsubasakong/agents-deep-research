"""
Agent used to generate clarification questions for the user's research query.

The Agent takes as input a string containing the original query and generates
a set of clarification questions to help refine and improve the query.
"""

from pydantic import BaseModel, Field
from typing import List
from .baseclass import ResearchAgent
from ..llm_client import fast_model, model_supports_structured_output
from datetime import datetime
from .utils.parse_output import create_type_parser

class ClarificationOutput(BaseModel):
    """Output from the Clarification Agent"""
    clarification_questions: List[str] = Field(description="List of clarification questions to ask the user")
    explanation: str = Field(description="Brief explanation of why these clarifications would help with the research")


INSTRUCTIONS = f"""
You are a Research Clarification Assistant. Today's date is {datetime.now().strftime("%Y-%m-%d")}.
Your job is to generate thoughtful clarification questions that will help refine and improve a research query.

You will be given the original user query. Your task is to:
1. Analyze the query to identify any ambiguities, missing details, or areas that could benefit from clarification
2. Generate 3-5 focused clarification questions that would help improve the quality of the research
3. Provide a brief explanation of why these clarifications would help with the research

Be specific in your questions and tailor them to the original query. Ask questions that will:
- Clarify the scope and boundaries of the research
- Identify the user's specific needs or goals
- Understand the depth of information required
- Determine any constraints or preferences for the research approach

Only output JSON and follow the JSON schema below. Do not output anything else. I will be parsing this with Pydantic so output valid JSON only:
{ClarificationOutput.model_json_schema()}
"""

selected_model = fast_model

clarification_agent = ResearchAgent(
    name="ClarificationAgent",
    instructions=INSTRUCTIONS,
    model=selected_model,
    output_type=ClarificationOutput if model_supports_structured_output(selected_model) else None,
    output_parser=create_type_parser(ClarificationOutput) if not model_supports_structured_output(selected_model) else None
) 