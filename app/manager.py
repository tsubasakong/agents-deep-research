from __future__ import annotations
import asyncio
import time
import json
from typing import Dict, List
from agents import Runner, custom_span, gen_trace_id, trace
from .agents.writer_agent import ReportData, writer_agent
from .agents.knowledge_gap_agent import KnowledgeGapOutput, knowledge_gap_agent
from .agents.tool_selector_agent import AgentTask, AgentSelectionPlan, tool_selector_agent
from .agents.tool_agents import TOOL_AGENTS, ToolAgentOutput


class DeepResearchManager:
    """Manager for the deep research workflow that operates in an iterative loop."""

    def __init__(
        self, 
        max_iterations: int = 5,
        max_time_minutes: int = 10,
        verbose: bool = True
    ):
        self.max_iterations: int = max_iterations
        self.max_time_minutes: int = max_time_minutes
        self.start_time: float = None
        self.iteration: int = 0
        self.historical_thinking: List[KnowledgeGapOutput] = []
        self.historical_findings: List[str] = []
        self.historical_tool_calls: List[str] = []
        self.should_continue: bool = True
        self.verbose: bool = verbose

    async def run(
            self, 
            query: str,
            output_length: str = "",  # A text description of the desired output length, can be left blank
            output_instructions: str = ""  # Instructions for the final report (e.g. don't include any headings, just a couple of paragraphs of text)
        ) -> ReportData:
        """Run the deep research workflow for a given query."""
        trace_id = gen_trace_id()
        self.start_time = time.time()
        
        with trace("Deep Research trace", trace_id=trace_id):
            print(f"View trace: https://platform.openai.com/traces/{trace_id}")
            self._log_message("Starting deep research workflow...")
            
            # Iterative research loop
            while self.should_continue and self._check_constraints():
                self.iteration += 1
                self._log_message(f"\n=== Starting Iteration {self.iteration} ===")
                
                # 1. Evaluate the current state of research
                evaluation = await self._evaluate_state(query)
                
                # Check if we should continue or break the loop
                if not evaluation.research_complete:
                    # 2. Select agents to address knowledge gaps
                    next_gap = evaluation.outstanding_gaps[0]
                    selection_plan: AgentSelectionPlan = await self._select_agents(next_gap, query)
                    self.historical_tool_calls.extend([f"[Agent] {task.agent}: [Query] {task.query} / [Entity] {task.entity_website}" for task in selection_plan.tasks])

                    # 3. Run the selected agents to gather information
                    results: Dict[str, ToolAgentOutput] = await self._execute_tools(selection_plan.tasks)
                    for tool_output in results.values():
                        self.historical_findings.append(tool_output.output)
                    # # 4. Update the draft with new information
                else:
                    self.should_continue = False
                    self._log_message("Research complete! Final draft is ready.")
            
            # Create final report
            report = await self._create_final_report(query, length=output_length, instructions=output_instructions)
            
            elapsed_time = time.time() - self.start_time
            self._log_message(f"Research completed in {int(elapsed_time // 60)} minutes and {int(elapsed_time % 60)} seconds after {self.iteration} iterations.")
            
            return report
    
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
    
    async def _evaluate_state(self, query: str) -> KnowledgeGapOutput:
        """Evaluate the current state of research and identify knowledge gaps."""
        self._log_message("Evaluating current research state...")
        
        # Prepare input for the state evaluator
        if not self.historical_thinking:
            historical_thinking_str = "No previous evaluation available."
        else:
            historical_thinking_str = '\n\n'.join(json.dumps(item.model_dump()) for item in self.historical_thinking)

        input_str = f"""
        Current Iteration Number: {self.iteration}
        Time Elapsed: {(time.time() - self.start_time) / 60:.2f} minutes of maximum {self.max_time_minutes} minutes
        
        ORIGINAL QUERY:
        {query}

        PREVIOUS ANALYSES:
        {historical_thinking_str}
        
        FINDINGS COLLECTED:
        {'\n\n'.join(self.historical_findings) if self.historical_findings else "No findings available yet."}
        """

        result = await Runner.run(
            knowledge_gap_agent,
            input_str,
        )
        
        evaluation = result.final_output_as(KnowledgeGapOutput)
        self._log_message(f"Identified {len(evaluation.outstanding_gaps)} knowledge gaps:\n" + '\n'.join(evaluation.outstanding_gaps))
        self._log_message(f"Research complete: {evaluation.research_complete}")
        
        # Store the evaluation for the next iteration
        self.historical_thinking.extend([evaluation])
        
        return evaluation
    
    async def _select_agents(self, gap: str, query: str) -> AgentSelectionPlan:
        """Select agents to address the identified knowledge gap."""
        self._log_message("Selecting appropriate agents for the knowledge gap...")
        
        input_str = f"""
        ORIGINAL QUERY:
        {query}

        KNOWLEDGE GAP TO ADDRESS:
        {gap}
        """
        
        result = await Runner.run(
            tool_selector_agent,
            input_str,
        )
        
        selection_plan = result.final_output_as(AgentSelectionPlan)
        self._log_message(f"Selected {len(selection_plan.tasks)} agent tasks:\n" + '\n'.join([f"{task.agent}: {task.query} / {task.entity_website}" for task in selection_plan.tasks]))
        
        return selection_plan
    
    async def _execute_tools(self, tasks: List[AgentTask]) -> Dict[str, ToolAgentOutput]:
        """Execute the selected tools concurrently to gather information."""
        with custom_span("Execute Tool Agents"):
            self._log_message("Executing tool agents to gather information...")
            
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
                self._log_message(f"Tool execution progress: {num_completed}/{len(async_tasks)}")
            
            self._log_message("Tool execution completed")
            return results
    
    async def _run_agent_task(self, task: AgentTask) -> tuple[str, str, ToolAgentOutput]:
        """Run a single agent task and return the result."""
        try:
            agent_name = task.agent
            agent = TOOL_AGENTS.get(agent_name)
            if agent:
                result = await Runner.run(
                    agent,
                    json.dumps(task.model_dump()),
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
    
    async def _create_final_report(
            self, 
            query: str,
            length: str = "",
            instructions: str = ""
        ) -> ReportData:
        """Create the final report from the completed draft."""
        self._log_message("Creating final report...")

        length_str = f"* The full response should be approximately {length}.\n" if length else ""
        instructions_str = f"* {instructions}" if instructions else ""
        guidelines_str = ("\n\nGUIDELINES:\n" + length_str + instructions_str).strip('\n') if length or instructions else ""

        input_str = f"""
        Provide a detailed response based on the query and findings below. {guidelines_str}

        QUERY: {query}

        FINDINGS:
        {'\n\n'.join(self.historical_findings) if self.historical_findings else "No findings available yet."}
        """

        result = await Runner.run(
            writer_agent,
            input_str,
        )
        
        report = result.final_output_as(ReportData)
        self._log_message("Final report created successfully")
        
        return report
    
    def _log_message(self, message: str) -> None:
        """Log a message if verbose is True"""
        if self.verbose:
            print(message)
