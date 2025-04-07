from __future__ import annotations
import asyncio
import time
import os
from typing import Dict, List, Optional
from agents import custom_span, gen_trace_id, trace, Agent, Runner
from agents.mcp import MCPServerStdio
from .agents.baseclass import ResearchRunner
from .agents.writer_agent import writer_agent
from .agents.knowledge_gap_agent import KnowledgeGapOutput, knowledge_gap_agent
from .agents.tool_selector_agent import AgentTask, AgentSelectionPlan, tool_selector_agent
from .agents.thinking_agent import thinking_agent
from .agents.tool_agents import TOOL_AGENTS, ToolAgentOutput
from .agents.research_assistant import create_research_assistant
from pydantic import BaseModel, Field


class IterationData(BaseModel):
    """Data for a single iteration of the research loop."""
    gap: str = Field(description="The gap addressed in the iteration", default_factory=list)
    tool_calls: List[str] = Field(description="The tool calls made", default_factory=list)
    findings: List[str] = Field(description="The findings collected from tool calls", default_factory=list)
    thought: List[str] = Field(description="The thinking done to reflect on the success of the iteration and next steps", default_factory=list)


class Conversation(BaseModel):
    """A conversation between the user and the iterative researcher."""
    history: List[IterationData] = Field(description="The data for each iteration of the research loop", default_factory=list)

    def add_iteration(self, iteration_data: Optional[IterationData] = None):
        if iteration_data is None:
            iteration_data = IterationData()
        self.history.append(iteration_data)
    
    def set_latest_gap(self, gap: str):
        self.history[-1].gap = gap

    def set_latest_tool_calls(self, tool_calls: List[str]):
        self.history[-1].tool_calls = tool_calls

    def set_latest_findings(self, findings: List[str]):
        self.history[-1].findings = findings

    def set_latest_thought(self, thought: str):
        self.history[-1].thought = thought

    def get_latest_gap(self) -> str:
        return self.history[-1].gap
    
    def get_latest_tool_calls(self) -> List[str]:
        return self.history[-1].tool_calls
    
    def get_latest_findings(self) -> List[str]:
        return self.history[-1].findings
    
    def get_latest_thought(self) -> str:
        return self.history[-1].thought
    
    def get_all_findings(self) -> List[str]:
        return [finding for iteration_data in self.history for finding in iteration_data.findings]

    def compile_conversation_history(self) -> str:
        """Compile the conversation history into a string."""
        conversation = ""
        for iteration_num, iteration_data in enumerate(self.history):
            conversation += f"[ITERATION {iteration_num + 1}]\n\n"
            if iteration_data.thought:
                conversation += f"{self.get_thought_string(iteration_num)}\n\n"
            if iteration_data.gap:
                conversation += f"{self.get_task_string(iteration_num)}\n\n"
            if iteration_data.tool_calls:
                conversation += f"{self.get_action_string(iteration_num)}\n\n"
            if iteration_data.findings:
                conversation += f"{self.get_findings_string(iteration_num)}\n\n"

        return conversation
    
    def get_task_string(self, iteration_num: int) -> str:
        """Get the task for the current iteration."""
        if self.history[iteration_num].gap:
            return f"<task>\nAddress this knowledge gap: {self.history[iteration_num].gap}\n</task>"
        return ""
    
    def get_action_string(self, iteration_num: int) -> str:
        """Get the action for the current iteration."""
        if self.history[iteration_num].tool_calls:
            joined_calls = '\n'.join(self.history[iteration_num].tool_calls)
            return (
                "<action>\nCalling the following tools to address the knowledge gap:\n"
                f"{joined_calls}\n</action>"
            )
        return ""
        
    def get_findings_string(self, iteration_num: int) -> str:
        """Get the findings for the current iteration."""
        if self.history[iteration_num].findings:
            joined_findings = '\n\n'.join(self.history[iteration_num].findings)
            return f"<findings>\n{joined_findings}\n</findings>"
        return ""
    
    def get_thought_string(self, iteration_num: int) -> str:
        """Get the thought for the current iteration."""
        if self.history[iteration_num].thought:
            return f"<thought>\n{self.history[iteration_num].thought}\n</thought>"
        return ""
    
    def latest_task_string(self) -> str:
        """Get the latest task."""
        return self.get_task_string(len(self.history) - 1)
    
    def latest_action_string(self) -> str:
        """Get the latest action."""
        return self.get_action_string(len(self.history) - 1)
    
    def latest_findings_string(self) -> str:
        """Get the latest findings."""
        return self.get_findings_string(len(self.history) - 1)
    
    def latest_thought_string(self) -> str:
        """Get the latest thought."""
        return self.get_thought_string(len(self.history) - 1)
    

class IterativeResearcher:
    """Manager for the iterative research workflow that conducts research on a topic or subtopic by running a continuous research loop."""

    def __init__(
        self, 
        max_iterations: int = 5,
        max_time_minutes: int = 10,
        verbose: bool = True,
        tracing: bool = False,
        use_claude: bool = False
    ):
        self.max_iterations: int = max_iterations
        self.max_time_minutes: int = max_time_minutes
        self.start_time: float = None
        self.iteration: int = 0
        self.conversation: Conversation = Conversation()
        self.should_continue: bool = True
        self.verbose: bool = verbose
        self.tracing: bool = tracing
        self.use_claude: bool = use_claude or os.getenv("USE_CLAUDE", "").lower() == "true"
        self.mcp_server = None
        self.research_assistant = None
        
    async def run(
            self, 
            query: str,
            output_length: str = "",  # A text description of the desired output length, can be left blank
            output_instructions: str = "",  # Instructions for the final report (e.g. don't include any headings, just a couple of paragraphs of text)
            background_context: str = "",
        ) -> str:
        """Run the deep research workflow for a given query."""
        self.start_time = time.time()

        if self.tracing:
            trace_id = gen_trace_id()
            workflow_trace = trace("iterative_researcher", trace_id=trace_id)
            print(f"View trace: https://platform.openai.com/traces/trace?trace_id={trace_id}")
            workflow_trace.start(mark_as_current=True)

        self._log_message("=== Starting Iterative Research Workflow ===")
        
        # Check if Claude is enabled and Anthropic API key is set
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if self.use_claude and (not anthropic_api_key or anthropic_api_key.startswith("<") or anthropic_api_key.endswith(">")):
            self._log_message("WARNING: Using Claude with MCP was requested, but no valid Anthropic API key was found.")
            self._log_message("Falling back to the standard research flow without Claude.")
            self.use_claude = False
        
        # Iterative research loop
        if self.use_claude:
            self._log_message("Using Claude with MCP for research")
            # Use async context manager for MCP server
            async with MCPServerStdio(
                        params={
                            "command": "/Users/frankhe/.local/bin/mcp-proxy",
                            "args": ["https://sequencer-v2.heurist.xyz/toolf22e9e8c/sse"],
                        },
                        # Enable tools caching per the OpenAI SDK documentation
                        cache_tools_list=True,
                        name="MCP Proxy Server"
                ) as mcp_server:
                # Create the research assistant
                self.research_assistant = create_research_assistant()
                # Add MCP server to the research assistant
                self.research_assistant.mcp_servers = [mcp_server]
                
                # List tools to verify they're available
                tools = await mcp_server.list_tools()
                self._log_message(f"MCP server started with {len(tools)} tools")
                
                # Run the iterative research loop
                report = await self._run_research_loop(query, output_length, output_instructions, background_context, mcp_server)
        else:
            # Run the iterative research loop without MCP
            report = await self._run_research_loop(query, output_length, output_instructions, background_context)
        
        elapsed_time = time.time() - self.start_time
        self._log_message(f"IterativeResearcher completed in {int(elapsed_time // 60)} minutes and {int(elapsed_time % 60)} seconds after {self.iteration} iterations.")
        
        if self.tracing:
            workflow_trace.finish(reset_current=True)

        return report

    async def _run_research_loop(
            self, 
            query: str,
            output_length: str = "",
            output_instructions: str = "",
            background_context: str = "",
            mcp_server = None
        ) -> str:
        """Run the iterative research loop."""
        while self.should_continue and self._check_constraints():
            self.iteration += 1
            self._log_message(f"\n=== Starting Iteration {self.iteration} ===")

            # Set up blank IterationData for this iteration
            self.conversation.add_iteration()

            # 1. Generate observations
            observations: str = await self._generate_observations(query, background_context=background_context)

            # 2. Evaluate current gaps in the research
            evaluation: KnowledgeGapOutput = await self._evaluate_gaps(query, background_context=background_context)
            
            # Check if we should continue or break the loop
            if not evaluation.research_complete:
                next_gap = evaluation.outstanding_gaps[0]
                
                if self.use_claude and mcp_server:
                    # Use Claude with MCP for research
                    await self._claude_research(next_gap, query, mcp_server, background_context=background_context)
                else:
                    # 3. Select agents to address knowledge gap (original flow)
                    selection_plan: AgentSelectionPlan = await self._select_agents(next_gap, query, background_context=background_context)

                    # 4. Run the selected agents to gather information
                    results: Dict[str, ToolAgentOutput] = await self._execute_tools(selection_plan.tasks)
            else:
                self.should_continue = False
                self._log_message("=== IterativeResearcher Marked As Complete - Finalizing Output ===")
        
        # Create final report
        return await self._create_final_report(query, length=output_length, instructions=output_instructions)
    
    async def _claude_research(self, gap: str, query: str, mcp_server, background_context: str = ""):
        """Use Claude with MCP to research a knowledge gap."""
        self._log_message(f"Claude researching gap: {gap}")
        
        # Set the gap in the conversation
        self.conversation.set_latest_gap(gap)
        self._log_message(self.conversation.latest_task_string())
        
        # Prepare the user message for Claude
        previous_findings = '\n'.join(self.conversation.get_all_findings()) or "No previous findings."
        background = f"BACKGROUND CONTEXT:\n{background_context}" if background_context else ""
        
        user_message = f"""
        KNOWLEDGE GAP: {gap}
        
        ORIGINAL QUERY: {query}
        
        {background}
        
        PREVIOUS FINDINGS: 
        {previous_findings}
        """
        
        # Create a placeholder for the raw response
        raw_response = ""
        
        try:
            # Run Claude with MCP tools 
            result = await Runner.run(
                self.research_assistant,
                user_message
            )
            
            # Try to parse as structured output
            try:
                # Save the raw response in case we need it for error handling
                raw_response = result.final_output
                
                # Extract the output and sources
                output = result.final_output_as(ToolAgentOutput)
                findings_text = output.output
                sources_list = output.sources
                
                self._log_message("<debug>Successfully parsed Claude's response as structured JSON</debug>")
            except Exception as parse_error:
                self._log_message(f"<debug>Failed to parse Claude's response as structured JSON: {str(parse_error)}</debug>")
                # Fall back to custom parsing
                findings_text = self._extract_findings_from_text(raw_response)
                sources_list = self._extract_sources_from_text(raw_response)
                
                # Create a properly formatted output
                output = ToolAgentOutput(
                    output=findings_text,
                    sources=sources_list
                )
            
            # Add findings to conversation
            self.conversation.set_latest_findings([findings_text])
            
            # Log the action that Claude took
            tool_calls = [
                f"[Agent] Claude ResearchAssistant [Gap] {gap}"
            ]
            self.conversation.set_latest_tool_calls(tool_calls)
            self._log_message(self.conversation.latest_action_string())
            
            # Log the findings
            self._log_message(f"<findings>\n{findings_text}\n\nSources: {sources_list}\n</findings>")
            
            return output
        except Exception as e:
            # Handle the case where Claude's response processing failed completely
            self._log_message(f"Error processing Claude's response: {str(e)}")
            
            # Use our robust parsing functions to extract what we can
            findings_text = self._extract_findings_from_text(raw_response)
            sources = self._extract_sources_from_text(raw_response)
            
            # If extraction failed and we got empty findings, create a fallback message
            if not findings_text.strip():
                findings_text = f"Error processing response for knowledge gap: {gap}. The research assistant encountered an issue with formatting the output."
            
            # Create a properly formatted output
            output = ToolAgentOutput(
                output=findings_text,
                sources=sources
            )
            
            # Add findings to conversation
            self.conversation.set_latest_findings([findings_text])
            
            # Log the action that Claude took
            self.conversation.set_latest_tool_calls([
                f"[Agent] Claude ResearchAssistant [Gap] {gap}"
            ])
            self._log_message(self.conversation.latest_action_string())
            
            # Log the findings
            self._log_message(f"<findings>\n{findings_text}\n\nSources: {sources}\n</findings>")
            
            return output
    
    def _extract_findings_from_text(self, text: str) -> str:
        """Extract findings from Claude's raw text response."""
        import json
        import re
        
        # If text is None or empty, return a default message
        if not text or not isinstance(text, str):
            return "No valid findings could be extracted from the response."
        
        # =================================================================
        # Strategy 1: Look for complete valid JSON and extract "output" field
        # =================================================================
        
        # Remove code block markers if present
        cleaned_text = re.sub(r'```(?:json)?\s*(.*?)\s*```', r'\1', text, flags=re.DOTALL)
        
        # Try to find valid JSON objects in the text
        json_candidates = []
        
        # First, try to find the most obvious JSON object (everything between { and })
        json_match = re.search(r'(\{.*\})', cleaned_text, re.DOTALL)
        if json_match:
            json_candidates.append(json_match.group(1))
        
        # Then try to find smaller JSON objects that might be valid
        json_matches = re.findall(r'(\{[^{]*?\})', cleaned_text, re.DOTALL)
        json_candidates.extend(json_matches)
        
        # Try each candidate
        for json_str in json_candidates:
            try:
                data = json.loads(json_str.strip())
                if isinstance(data, dict) and "output" in data:
                    return data["output"]
            except json.JSONDecodeError:
                continue
        
        # =================================================================
        # Strategy 2: Look for the "output" field using regex
        # =================================================================
        output_patterns = [
            r'"output"\s*:\s*"(.*?)"(?=\s*,|\s*\})', # Standard JSON format
            r'"output"\s*:\s*"(.+?)"(?=\s*,|\s*\})', # Multi-line output
            r'"output"\s*:\s*"(.*?)"', # Simple pattern
        ]
        
        for pattern in output_patterns:
            match = re.search(pattern, cleaned_text, re.DOTALL)
            if match:
                # Unescape JSON string escapes
                output = match.group(1)
                output = output.replace('\\"', '"').replace('\\\\', '\\')
                return output
        
        # =================================================================
        # Strategy 3: Look for content in specific sections
        # =================================================================
        section_patterns = [
            r'(?:findings|output|results):\s*(.*?)(?:(?:sources|references):|$)',
            r'<findings>(.*?)</findings>',
            r'\*\*findings\*\*\s*:(.*?)(?:\*\*sources\*\*|$)',
        ]
        
        for pattern in section_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
        
        # =================================================================
        # Strategy 4: If nothing else worked, return cleaned text
        # =================================================================
        
        # Remove any obvious non-findings content
        result = text
        
        # Remove content about tool usage
        result = re.sub(r'I(?:\'ll| will| need to)? use the (web_search|crawl_website) tool.*?\n', '', result, flags=re.IGNORECASE)
        result = re.sub(r'Let me (search|look|find|research).*?\n', '', result, flags=re.IGNORECASE)
        
        # Remove introductory phrases
        result = re.sub(r'^(Here\'s what I found about|Based on my research|According to my findings|My findings on).*?\n', '', result, flags=re.IGNORECASE)
        result = re.sub(r'^(Here are|These are) (my|the) (findings|results).*?\n', '', result, flags=re.IGNORECASE)
        
        # Remove section headers and formatting
        result = re.sub(r'#+\s*Sources:?.*?$', '', result, flags=re.MULTILINE)
        result = re.sub(r'\*\*Sources:?\*\*.*?$', '', result, flags=re.MULTILINE)
        result = re.sub(r'Sources:?(\s*\n.*?)+$', '', result, flags=re.DOTALL)
        
        return result.strip()
    
    def _extract_sources_from_text(self, text: str) -> List[str]:
        """Extract sources from Claude's raw text response."""
        import json
        import re
        
        sources = []
        
        # If text is None or empty, return empty sources
        if not text or not isinstance(text, str):
            return sources
        
        # =================================================================
        # Strategy 1: Look for complete valid JSON and extract "sources" field
        # =================================================================
        
        # Remove code block markers if present
        cleaned_text = re.sub(r'```(?:json)?\s*(.*?)\s*```', r'\1', text, flags=re.DOTALL)
        
        # Try to find valid JSON objects in the text
        json_candidates = []
        
        # First, try to find the most obvious JSON object (everything between { and })
        json_match = re.search(r'(\{.*\})', cleaned_text, re.DOTALL)
        if json_match:
            json_candidates.append(json_match.group(1))
        
        # Then try to find smaller JSON objects that might be valid
        json_matches = re.findall(r'(\{[^{]*?\})', cleaned_text, re.DOTALL)
        json_candidates.extend(json_matches)
        
        # Try each candidate
        for json_str in json_candidates:
            try:
                data = json.loads(json_str.strip())
                if isinstance(data, dict) and "sources" in data:
                    if isinstance(data["sources"], list):
                        return [str(s) for s in data["sources"]]
            except json.JSONDecodeError:
                continue
        
        # =================================================================
        # Strategy 2: Look for the "sources" array using regex
        # =================================================================
        
        # Try to extract the sources array
        sources_array_pattern = r'"sources"\s*:\s*\[(.*?)\]'
        sources_match = re.search(sources_array_pattern, cleaned_text, re.DOTALL)
        if sources_match:
            array_content = sources_match.group(1)
            # Find quoted strings in the array
            quoted_sources = re.findall(r'"(.*?)"', array_content)
            if quoted_sources:
                sources.extend([s.replace('\\"', '"') for s in quoted_sources])
                return sources
        
        # =================================================================
        # Strategy 3: Look for sources in dedicated sections
        # =================================================================
        
        # Try to find a "Sources:" section
        section_patterns = [
            r'(?:^|\n)(?:##+\s*|\*\*)?sources(?:\**|:)+\s*((?:.+\n?)+)',
            r'(?:^|\n)(?:##+\s*|\*\*)?references(?:\**|:)+\s*((?:.+\n?)+)',
            r'(?:^|\n)sources:\s*\n((?:.+\n?)+)',
        ]
        
        for pattern in section_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                section = match.group(1)
                # Extract URLs from the section
                urls = re.findall(r'(https?://[^\s\n"\'<>()[\]]+)', section)
                if urls:
                    sources.extend(urls)
        
        # =================================================================
        # Strategy 4: Extract all URLs from the text as a last resort
        # =================================================================
        if not sources:
            # Extract any URLs in the text
            urls = re.findall(r'(https?://[^\s\n"\'<>()[\]]+)', text)
            sources.extend(urls)
        
        # =================================================================
        # Clean and deduplicate the sources
        # =================================================================
        
        # Clean up URLs (remove trailing punctuation)
        sources = [re.sub(r'[.,;:\'")\]]+$', '', url) for url in sources]
        
        # Remove duplicates while maintaining order
        seen = set()
        sources = [url for url in sources if not (url in seen or seen.add(url))]
        
        return sources
    
    def _check_constraints(self) -> bool:
        """Check if we've exceeded our constraints (max iterations or time)."""
        if self.iteration >= self.max_iterations:
            self._log_message("\n=== Ending Research Loop ===")
            self._log_message(f"Reached maximum iterations ({self.max_iterations})")
            return False
        
        elapsed_minutes = (time.time() - self.start_time) / 60
        if elapsed_minutes >= self.max_time_minutes:
            self._log_message("\n=== Ending Research Loop ===")
            self._log_message(f"Reached maximum time ({self.max_time_minutes} minutes)")
            return False
        
        return True
    
    async def _evaluate_gaps(
        self, 
        query: str,
        background_context: str = ""
    ) -> KnowledgeGapOutput:
        """Evaluate the current state of research and identify knowledge gaps."""

        background = f"BACKGROUND CONTEXT:\n{background_context}" if background_context else ""

        input_str = f"""
        Current Iteration Number: {self.iteration}
        Time Elapsed: {(time.time() - self.start_time) / 60:.2f} minutes of maximum {self.max_time_minutes} minutes

        ORIGINAL QUERY:
        {query}

        {background}

        HISTORY OF ACTIONS, FINDINGS AND THOUGHTS:
        {self.conversation.compile_conversation_history() or "No previous actions, findings or thoughts available."}        
        """

        result = await ResearchRunner.run(
            knowledge_gap_agent,
            input_str,
        )
        
        evaluation = result.final_output_as(KnowledgeGapOutput)

        if not evaluation.research_complete:
            next_gap = evaluation.outstanding_gaps[0]
            self.conversation.set_latest_gap(next_gap)
            self._log_message(self.conversation.latest_task_string())
        
        return evaluation
    
    async def _select_agents(
        self, 
        gap: str, 
        query: str,
        background_context: str = ""
    ) -> AgentSelectionPlan:
        """Select agents to address the identified knowledge gap."""
        
        background = f"BACKGROUND CONTEXT:\n{background_context}" if background_context else ""

        input_str = f"""
        ORIGINAL QUERY:
        {query}

        KNOWLEDGE GAP TO ADDRESS:
        {gap}

        {background}

        HISTORY OF ACTIONS, FINDINGS AND THOUGHTS:
        {self.conversation.compile_conversation_history() or "No previous actions, findings or thoughts available."}
        """
        
        result = await ResearchRunner.run(
            tool_selector_agent,
            input_str,
        )
        
        selection_plan = result.final_output_as(AgentSelectionPlan)

        # Add the tool calls to the conversation
        self.conversation.set_latest_tool_calls([
            f"[Agent] {task.agent} [Query] {task.query} [Entity] {task.entity_website if task.entity_website else 'null'}" for task in selection_plan.tasks
        ])
        self._log_message(self.conversation.latest_action_string())
        
        return selection_plan
    
    async def _execute_tools(self, tasks: List[AgentTask]) -> Dict[str, ToolAgentOutput]:
        """Execute the selected tools concurrently to gather information."""
        with custom_span("Execute Tool Agents"):
            # Create a task for each agent
            async_tasks = []
            for task in tasks:
                async_tasks.append(self._run_agent_task(task))
            
            # Run all tasks concurrently
            num_completed = 0
            results = {}
            for future in asyncio.as_completed(async_tasks):
                gap, agent_name, result = await future
                results[f"{agent_name}_{gap}"] = result
                num_completed += 1
                self._log_message(f"<processing>\nTool execution progress: {num_completed}/{len(async_tasks)}\n</processing>")

            # Add findings from the tool outputs to the conversation
            findings = []
            for tool_output in results.values():
                findings.append(tool_output.output)
            self.conversation.set_latest_findings(findings)

            return results
    
    async def _run_agent_task(self, task: AgentTask) -> tuple[str, str, ToolAgentOutput]:
        """Run a single agent task and return the result."""
        try:
            agent_name = task.agent
            agent = TOOL_AGENTS.get(agent_name)
            if agent:
                result = await ResearchRunner.run(
                    agent,
                    task.model_dump_json(),
                )
                # Extract ToolAgentOutput from RunResult
                output = result.final_output_as(ToolAgentOutput)
            else:
                output = ToolAgentOutput(
                    output=f"No implementation found for agent {agent_name}",
                    sources=[]
                )
            
            return task.gap, agent_name, output
        except Exception as e:
            error_output = ToolAgentOutput(
                output=f"Error executing {task.agent} for gap '{task.gap}': {str(e)}",
                sources=[]
            )
            return task.gap, task.agent, error_output
        
    async def _generate_observations(self, query: str, background_context: str = "") -> str:
        """Generate observations from the current state of the research."""
                
        background = f"BACKGROUND CONTEXT:\n{background_context}" if background_context else ""

        input_str = f"""
        ORIGINAL QUERY:
        {query}

        {background}

        HISTORY OF ACTIONS, FINDINGS AND THOUGHTS:
        {self.conversation.compile_conversation_history() or "No previous actions, findings or thoughts available."}
        """
        result = await ResearchRunner.run(
            thinking_agent,
            input_str,
        )

        # Add the observations to the conversation
        observations = result.final_output
        self.conversation.set_latest_thought(observations)
        self._log_message(self.conversation.latest_thought_string())
        return observations

    async def _create_final_report(
        self, 
        query: str,
        length: str = "",
        instructions: str = ""
        ) -> str:
        """Create the final response from the completed draft."""
        self._log_message("=== Drafting Final Response ===")

        length_str = f"* The full response should be approximately {length}.\n" if length else ""
        instructions_str = f"* {instructions}" if instructions else ""
        guidelines_str = ("\n\nGUIDELINES:\n" + length_str + instructions_str).strip('\n') if length or instructions else ""

        all_findings = '\n\n'.join(self.conversation.get_all_findings()) or "No findings available yet."

        input_str = f"""
        Provide a response based on the query and findings below with as much detail as possible. {guidelines_str}

        QUERY: {query}

        FINDINGS:
        {all_findings}
        """

        result = await ResearchRunner.run(
            writer_agent,
            input_str,
        )
        
        self._log_message("Final response from IterativeResearcher created successfully")
        
        return result.final_output
    
    def _log_message(self, message: str) -> None:
        """Log a message if verbose is True"""
        if self.verbose:
            print(message)