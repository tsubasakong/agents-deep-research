Deep Research Agent Architecture and MCP Refactor Plan

Using this doc https://openai.github.io/openai-agents-python/mcp/ to know how to implement the MCP server under the openai's agent sdk.

Need to implement the Cache for the MCP server.
```
Caching

Every time an Agent runs, it calls list_tools() on the MCP server. This can be a latency hit, especially if the server is a remote server. To automatically cache the list of tools, you can pass cache_tools_list=True to both MCPServerStdio and MCPServerSse. You should only do this if you're certain the tool list will not change.

If you want to invalidate the cache, you can call invalidate_tools_cache() on the servers.
```

and
End-to-end examples

View complete working examples at https://github.com/openai/openai-agents-python/tree/main/examples/mcp.

Use the `MCPServerStdio` mode to run the MCP server.

When using claude model, using `"claude-3-7-sonnet-20250219` check this doc https://docs.anthropic.com/en/api/getting-started and check if can use thinking mode in to the analysis process (https://docs.anthropic.com/en/docs/about-claude/models/extended-thinking-models?q=3.7)

##  Refactor Plan for MCP Integration

To migrate the current multi-agent system to use Claude with MCP (Model Context Protocol), we will refactor the tool registration and agent loop. The goal is to let Claude handle tool selection and invocation within its own conversation, using tool_use/tool_result messages, rather than orchestrating tools via separate agent calls. Below is a step-by-step refactor plan:

4.1 Replace Direct Tool Registration with MCP-Compatible Tools:
Instead of registering Python functions directly as tools for OpenAI models, we will expose those functions through an MCP server so Claude can call them. Concretely:
	•	Set up an MCP Server for Tools: We will create an MCP server process that serves the web_search and crawl_website functionalities. This can be done using the OpenAI Agents MCP extension. For example, we can write a small Python script or Node.js script (Anthropic provides an npm package for some tools ￼) that listens for tool calls. Using agents_mcp, we can launch it via MCPServerStdio for a local subprocess. The server should define the tools’ schema (e.g., web_search takes a query string; crawl_website takes a URL) and implement the logic by calling our existing Python functions or their underlying APIs.
	•	Configure Tool Definitions: Ensure that each tool has a descriptive name and input/output schema that MCP will convey to the model. For instance, define web_search with an input schema like {"query": "string"} and output containing maybe an array of snippets or a consolidated text. (We can choose to return a simplified output to Claude, such as a short summary of top results or a list of relevant passages, since Claude will incorporate whatever we give it into its answer.) Similarly, define crawl_website with input {"url": "string"}. The output can be a truncated page text or summary (to avoid overloading Claude with too much content). These definitions can be in a YAML or JSON config that the MCP server reads, or provided programmatically if using a library to stand up the server.
	•	Integrate with Agents SDK: In our code, instead of doing tools=[web_search_function] or search_agent.as_tool(), we will attach the MCP server to the main agent. Using the extension, this means changing the agent class import and initialization. For example, change:

from agents import Agent  # old

to:

from agents_mcp import Agent  # new MCP-enabled Agent class

Then, when creating our research agent that uses tools, pass the mcp_servers parameter. For instance:

server = MCPServerStdio(params={"command": "python", "args": ["mcp_tools.py"]})
agent = Agent(name="AssistantAgent",
              instructions=INSTRUCTIONS,
              mcp_servers=[server],
              model=claude_model)

(Here INSTRUCTIONS would be the combined prompt for our Claude agent – more on that below.) According to the MCP extension’s README, using agents_mcp.Agent with mcp_servers will automatically handle listing the tools and routing calls ￼. We will likely remove the tools=[ ... ] argument for this agent, since tools now come via the MCP server.
Implementation note: We might launch the MCP server at program start (e.g., using async with MCPServerStdio(...) as server: to ensure it’s running) and reuse it for each iteration or each section of DeepResearcher. The server overhead is small, and it could handle multiple tool calls sequentially.

4.2 Adjust the Agent Execution Loop for MCP-Style Planning:
With Claude handling tool use internally, we can simplify the orchestration loop. Claude will effectively combine the roles of ToolSelectorAgent and Tool Agents. Key changes:
	•	Single Agent for Planning+Execution: We will introduce a new Claude-based research agent (let’s call it ResearchAssistant) that is used in each iteration to both decide on actions and execute tools. This agent will use the Claude model and have access to the MCP server’s tools. Its prompt (instructions) will combine the logic of the former ToolSelector and the context that Tool Agents had. For example, the system instructions could say: “You are a research assistant. You have the following tools: WebSearch (search the web), SiteCrawler (crawl a website). When you need information, use web_search or crawl_website and I will provide the results. Continue the conversation by analyzing those results and incorporating them into your findings. Your goal is to address the given knowledge gap fully. Format your final findings as JSON in the specified schema.” This prompt guides Claude to autonomously pick and use tools. We also include the current knowledge gap and relevant context in the user prompt for this agent. Essentially, instead of us pre-running a ToolSelectorAgent and then multiple tool agents, we hand the problem (gap + context + tools) to Claude and let it figure it out in one go.
	•	Bypass ToolSelectorAgent: We no longer need to call the ToolSelectorAgent separately. The logic it performed (choosing which agent and query) will emerge from Claude’s own decision when it chooses a tool_use. Thus, in the iterative loop, we will skip await ResearchRunner.run(tool_selector_agent, ...) and related parsing ￼ for the Claude pathway. Instead, after the KnowledgeGapAgent outputs a gap, we go straight to invoking our Claude ResearchAssistant agent for that gap.
	•	Parallel Tool Calls vs Sequential: In the current implementation, multiple tool tasks could run in parallel. With Claude driving, tool calls will be sequential in a single conversation (Claude can only issue one tool_use at a time, wait for result, then decide next). However, Claude could potentially issue multiple distinct tool_use requests back-to-back without giving a final answer in between. The Agents SDK will feed each result and keep the conversation going. This sequential approach is acceptable, as Claude can still cover multiple queries if needed (the ToolSelectorAgent guidelines about “at most 3 agents at a time” ￼ become “up to 3 tool uses in one go”). We should verify that Claude’s reasoning doesn’t overly lengthen the conversation; in practice, Claude-2 has a large context and can handle multiple tool interactions in one response.
	•	Incorporating Memory: We will continue to use the Conversation object or a similar mechanism to provide Claude with prior context, but it may require less detail. Since Claude will see the immediate past tool outputs, the main thing to carry into the next iteration is a summary of what has been learned so far. We can use the ThinkingAgent’s output or simply the combined findings from all previous iterations for that. The KnowledgeGapAgent will still run at the start of each iteration to decide if more research is needed (we can run KnowledgeGapAgent on Claude as well, or keep it on a fast model if performance is a concern). Assuming we use Claude for KnowledgeGap too, it will have the full conversation (including all past tool results) in memory if we reuse the same agent instance. Alternatively, we can reset Claude’s context each iteration but feed a condensed history as before (the compile_conversation_history string). A practical approach: after each iteration, append a brief summary of new findings to a running “context” string, and provide that to Claude next time. This is similar to the original method, but we might simplify it since Claude itself produces the findings in JSON. For now, plan to maintain using conversation to store cumulative findings and thoughts, but use them mainly for the KnowledgeGapAgent’s input and final report. During the Claude tool-using agent run, rely on Claude’s own memory of earlier turns in that iteration.
	•	Example of Modified Loop:
	1.	Run KnowledgeGapAgent (could be a quick call using a smaller model, or even an internal logic check) to get next_gap.
	2.	If research_complete true, break loop.
	3.	Otherwise, run Claude ResearchAssistant with the next_gap and current context. Claude will produce some output after possibly using tools. We instruct Claude to output the findings in a structured way (e.g. in the same format as ToolAgentOutput or a custom format). For consistency, we might ask it to output: {"output": "...merged findings...","sources": ["..."]} similar to before, so we can parse it easily. Claude will have gotten the sources during its tool calls (since our web_search tool can return source URLs, and Claude can include them). If Claude doesn’t naturally include them, we explicitly instruct it to list the sources it used.
	4.	Parse Claude’s output to get a summary of findings and sources. Store these in conversation.set_latest_findings(...) and perhaps also generate a “thought” if Claude’s output didn’t include one. (We might not need a separate ThinkingAgent now; Claude effectively did the thinking while producing the findings. But we could still prompt Claude at the end, “Any reflections?” if we want a distinct thought.)
	5.	Loop back to KnowledgeGapAgent with the updated conversation.
	•	Fallback for Complex Queries: If we find Claude tends to produce a lot of text interwoven with tool calls, we may consider splitting its role: e.g., instruct Claude’s tool-use agent to only gather information and not draw final conclusions – then have a separate Claude prompt to reflect (like the thinking agent) if needed. However, an elegant approach is to incorporate the reflection in Claude’s final output of that iteration. For instance, after finishing tool uses, Claude could output a short analysis of whether the gap is resolved or if more is needed. We can include in the instructions something like: “After using the tools, output your findings and note if the gap is fully addressed or if further research is needed.” This way the KnowledgeGapAgent might be merged with the tool-use agent. But to minimize change, we’ll keep KnowledgeGapAgent as a distinct step for now and just have Claude output findings.

4.3 Replace Planner/Selector Logic with Claude’s Native Planning:
The current PlannerAgent (which made the initial outline) and ToolSelectorAgent (which picked tools each iteration) are tailored to GPT-4’s function-calling style. With Claude, we can streamline this:
	•	Initial Planning: We can still use the PlannerAgent to create a high-level report outline (sections) at the very beginning – this can be done with Claude as well (Claude will output a ReportPlan structure). This step can remain largely unchanged, just running on Claude. The main difference is in iterative research steps.
	•	Tool Selection: We will remove the explicit call to tool_selector_agent each iteration. Claude doesn’t need a separate “selector” – given the gap and the tools, it will decide on the fly. For example, previously the ToolSelectorAgent might output two search queries; under MCP, Claude might simply make two web_search calls sequentially. The effect is the same, but it’s driven by Claude’s reasoning. We should ensure Claude knows it can call the same tool multiple times. The guidelines we provided to the ToolSelector (like “you can list WebSearchAgent multiple times if needed” ￼) should be conveyed in Claude’s prompt. We will instruct: “You may call the web_search tool multiple times with different queries to cover the gap fully. Use the SiteCrawler tool if information is needed from a specific website.” This replaces the need for a separate selection plan structure.
	•	Parallelization Consideration: One loss in this refactor is parallel execution of tool agents (Claude’s tool calls are sequential). If parallel searches were a significant optimization, we might consider spawning multiple Claude agents in parallel, but that complicates context sharing. It’s probably acceptable to go sequential since Claude-2 is quite fast and can fetch results in one flowing conversation. We will note this in documentation but proceed with sequential tool use.
	•	Simplify Schema Passing: The JSON schemas for output (like ToolAgentOutput) might not need to be enforced at each small step. Instead, we can have Claude output directly the merged findings for an iteration in a simpler format. However, to minimize code changes down the line (e.g., reusing the same structures for consistency), we may keep the ToolAgentOutput format for the Claude agent’s output. That means instructing Claude to output {"output": "...", "sources": [ ... ]} at the end of each gap’s research. We should be cautious: Anthropic’s models don’t have an official function calling API, so they might not perfectly stick to JSON. We will likely rely on the same create_type_parser(ToolAgentOutput) logic to clean up Claude’s output if it deviates ￼ ￼. (The Agents SDK will attempt to parse it since we can set output_type=ToolAgentOutput for the Claude agent too – the SDK’s model_supports_structured_output currently considers "anthropic.com" as supporting structured output ￼, which may or may not be true. If it’s not reliable, we force output_parser usage for Claude.)
	•	Updating Code References: We will remove references to tool_selector_agent.run and the entire AgentSelectionPlan model from the main loop. The AgentTask and TOOL_AGENTS mapping become unnecessary in MCP mode. To avoid breaking the OpenAI GPT-4 path, we can make this conditional. For example, if model_provider == "anthropic", bypass the old tool selection and use the Claude agent; if using OpenAI, keep old behavior. This way we don’t lose the ability to use GPT-4. The code structure might look like:

if using_claude:
    # Claude will handle tool use
    assistant_agent = ...  # Claude Agent with MCP
    result = await ResearchRunner.run(assistant_agent, conversation_input)
    findings = result.final_output_as(ToolAgentOutput).output
    sources = result.final_output_as(ToolAgentOutput).sources
    conversation.set_latest_findings([findings])
    # (Claude's output is already a synthesis of all tools it used)
else:
    # Existing logic with tool_selector_agent and parallel tool execution
    ...

We’ll maintain the KnowledgeGapAgent call before this block and loop accordingly.

4.4 Modify Schemas and Logic for Claude’s Tool-Calling Behavior:
A few schema/logic tweaks are needed to align with Claude’s MCP style:
	•	Tool Response Formatting: Ensure the MCP server’s tool responses are concise and useful. For instance, our current web_search returns a list of detailed ScrapeResult objects (with title, text, etc.). We might modify the MCP version of web_search to directly return a summarized snippet of results or only the most relevant parts, since Claude will incorporate whatever is returned into its context. Alternatively, we let Claude see the raw list and filter itself. In practice, it may be better to do some light processing: e.g., return the top 3 snippets with their URLs. We should also watch token length – if a search returns 10 long snippets, sending all to Claude might waste tokens. So our MCP tool function could do what the WebSearchAgent’s LLM was doing: filter for relevance ￼ and maybe truncate. This isn’t a schema change per se, but an adjustment in tool implementation to better suit Claude.
	•	No Need for AgentSelectionPlan schema: We can deprecate the AgentSelectionPlan and AgentTask models in MCP mode. They were part of the old chain-of-thought for GPT-4. Now, Claude’s decisions are not explicitly returned as data, they are implicit in the conversation. So those classes can be retained for OpenAI mode, but won’t be used in Claude mode. We’ll update documentation/comments to reflect that when using Claude, tool selection is internal and doesn’t produce an AgentSelectionPlan. (If desired, we could log Claude’s tool_use choices to some structure for debugging, but it’s not needed for functionality.)
	•	Memory Handling: Because Claude will carry the tool results in the conversation, the KnowledgeGapAgent’s prompt can possibly be simpler. It will still receive the full history text for compatibility, but note that in Claude’s own mind it “knows” what happened last iteration. To avoid confusion or duplication, we might limit the history given to KnowledgeGapAgent to the high-level summary of each iteration (perhaps just the  sections without the raw tool call details). This is a prompt tuning detail. The KnowledgeGapAgent schema remains the same.
	•	Tracing and Iteration Control: With Claude taking on more work per iteration, each iteration might be slower (because one call does tool use + summary). We should enforce the same max_iterations and max_time constraints. Those are already checked in _check_constraints() each loop ￼. If Claude’s reasoning doesn’t terminate (unlikely, but if it hallucinated an endless need to search), the loop and time limits will stop it. We’ll test to ensure Claude eventually produces an output and doesn’t get stuck in a tool-use loop (the Agents SDK should end the run when Claude outputs a non-tool message as final).

4.5 Step-by-Step Implementation Summary:
	1.	Integrate Agents MCP Extension: Add openai-agents-mcp to requirements and import its Agent class. Set up an MCP server for our tools. Test listing tools to verify Claude will see web_search and crawl_website with correct descriptions.
	2.	Create Combined Claude Agent Prompt: Merge relevant parts of ToolSelectorAgent.INSTRUCTIONS ￼ and WebSearchAgent.INSTRUCTIONS guidelines (like quoting facts, not repeating failed searches, etc.) into a single instruction set for Claude. Include tool usage format (maybe provide an example of tool_use/tool_result in the prompt so Claude knows the syntax). Also instruct the output format (JSON with output and sources). For instance:
“You have two tools: (1) web_search – searches Google for a query (use for broad info); (2) crawl_website – fetches pages from a given website (use for specific sites). When you need to use a tool, respond with a tool_use message. I (the system) will reply with a tool_result. Continue this until you have enough information. Finally, output your findings in JSON: {"output": "...", "sources": ["..."]}. Include source URLs in your output. Do not produce the final answer until you have gathered all necessary info.”

This gives Claude the road-map on how to proceed. (We’ll refine this with a bit of experimentation.)
	3.	Modify IterativeResearcher Loop: In iterative_research.py, add a branch for using the Claude agent. When a gap is identified, if using Claude, run the new ResearchAssistant agent instead of ToolSelector + manual tool execution. After Runner.run, parse the result into findings and sources. We can reuse ToolAgentOutput for parsing as noted. Set conversation.latest_findings and maybe also append these findings to a cumulative list for the final writer. We may skip adding a “tool call” entry to conversation, since Claude’s tool calls aren’t logged in our Conversation (though we could log something like [Agent] Claude used web_search on "X" for completeness). If needed for traceability, we can capture Claude’s tool_use events via the SDK’s tracing or callback hooks and insert them into the conversation log, but that’s optional.
	4.	Adjust WriterAgent Input: Ensure the final WriterAgent (which compiles the report) gets all the information. Previously, it likely got the outline and the detailed text for each section (which was composed of all findings in that section’s iterative research). In the new flow, the findings are still stored in conversation.history per iteration. The WriterAgent can proceed similarly – it will find all findings in the Conversation. The difference is that those findings might already be well-structured, since Claude gave them to us. The writer’s job remains to merge them into a coherent report, following format instructions. We might consider using Claude for writing as well, since it can handle long outputs, but GPT-4 might be fine too. In either case, that part of the pipeline can remain the same logically.
	5.	Deactivate Redundant Components: After confirming the new approach works, we can remove or disable the ToolSelectorAgent and Tool Agents for the Claude path. We will update the documentation accordingly: the “Tool Agents” layer is bypassed for models that can do MCP (Claude). We’ll keep their code for compatibility (one could still run the system with GPT-4 as before by toggling a setting). But in Claude mode, those agents won’t be called. The KnowledgeGapAgent and WriterAgent remain in use (we might run KnowledgeGap on Claude or not – to be decided; running it on Claude ensures consistent comprehension, but it could be slight overkill. We might try using Claude for everything to reduce dependencies on multiple models).

This plan routes tool usage through Claude’s MCP interface, effectively consolidating the plan-and-act steps. The refactored system will be simpler in terms of agent count: for each iteration we’ll have just KnowledgeGapAgent and the Claude ResearchAssistant agent (which encompasses tool use and initial synthesis). This should maintain or improve the quality of research, since Claude can dynamically decide to dig deeper if needed (e.g., it can make a second search query if the first results were insufficient, something the current static plan might not always do).

5. Deliverables

Code Map (Updated Architecture)

After refactoring, the architecture will change from multiple specialized agents to a more streamlined flow. Below is a diagram and description of the new architecture using Claude with MCP:
	•	KnowledgeGapAgent (fast LLM) – Identifies knowledge gaps from current state.
	•	ResearchAssistant (Claude with MCP tools) – Addresses the gap by calling tools and gathering findings. This single agent replaces the ToolSelector + Tool Agents sequence. Claude uses web_search and crawl_website as needed via tool calls. It outputs a summary of findings with references.
	•	(Loop) – The findings are logged. If gaps remain, the loop repeats: KnowledgeGapAgent reevaluates and possibly another round with ResearchAssistant is performed for the next gap. Claude’s internal memory of prior tool interactions helps it not duplicate work.
	•	WriterAgent (GPT-4 or Claude) – Synthesizes the final report. It takes the accumulated findings for all sections and produces the final multi-page report with the requested format and citations.

This can be visualized in a flowchart:

User Query 
   ↓ 
[ KnowledgeGapAgent ] 
   → outputs {gaps} 
   ↓ (for each gap)  
[ Claude ResearchAssistant ] --(tool_use/tool_result)--> [ WebSearch / Crawler tools ]  
   ← (tool results fed back) -- 
   → outputs findings for gap 
   ↓ 
(back to KnowledgeGapAgent until no gaps remain) 
   ↓ 
[ WriterAgent ] 
   → Final Report with sources

In this diagram, the bidirectional arrow between ResearchAssistant and WebSearch/Crawler tools indicates Claude’s iterative tool use: it requests a tool, gets the result, possibly requests again, etc., all inside that agent step. The loop between KnowledgeGapAgent and ResearchAssistant continues until KnowledgeGapAgent says all gaps are resolved ￼. Finally, WriterAgent compiles the results into the output document.

The code structure in the repository will reflect this new flow. The agents/tool_agents module becomes optional; in Claude mode, those agents aren’t invoked. Instead, we utilize the agents_mcp extension and the tools module functions directly. The conversation management (Conversation class) still exists but fewer entries are added (tool calls from Claude might not be explicitly logged, though their outcomes are). The end result is a simpler agent hierarchy when using Claude: effectively a two-layer system (one high-level reasoning agent with tools, plus the existing gap evaluator and writer).

Gap Analysis: OpenAI Agents SDK vs Claude’s MCP Tool Use

Aspect	OpenAI Agents SDK (Function-Call style)	Claude MCP (Model Context Protocol)
Tool Definitions	Tools are Python functions or sub-agents registered in code. The SDK auto-generates a JSON schema for each and includes it in the model’s functions field for OpenAI models ￼. E.g., GPT-4 knows a function web_search with a given schema and will “call” it.	Tools are defined on an MCP server and listed to the model at runtime. The Anthropic API expects a tool list with name, description, and schema in the prompt/request ￼. Claude sees these as available actions (similar to how it sees the text of a system message).
Tool Invocation Protocol	For OpenAI (ChatGPT) models, the LLM outputs a function call when it wants to use a tool (e.g., {"name": "web_search", "arguments": {...}}). The Agents SDK Runner intercepts this, executes the function, then provides the function’s return value back to the model as a JSON result ￼ ￼ (internally formatted as an assistant message with function_call or just directly inserted, depending on API). The model then continues generating the final answer.	Claude uses tool_use messages to request a tool and expects a tool_result message in reply. This is a turn-based interaction embedded in the conversation ￼. The Agents SDK’s MCP integration handles this: when Claude outputs {"tool_use":{...}}, the SDK calls the tool on the MCP server and injects {"tool_result":{...}} back to Claude ￼. Claude can repeat this cycle multiple times before returning a normal message. The exchange is part of a single conversational session (stream).
Agent Orchestration	Typically requires multiple agent instances and handoffs. In our original design, one agent (ToolSelector) decides which tool agents to call, then the main program runs each tool agent via the SDK sequentially or in parallel, and feeds their outputs to another agent (Thinking) ￼ ￼. The developer orchestrates these steps explicitly in code.	Orchestration is largely handled by the model itself. We collapse the chain: Claude decides if/when to call tools and does so directly. The developer’s code does not need to route between different sub-agents; it only needs to provide Claude with the available tools and respond to tool calls. Essentially, the model’s policy (when to search, what to search) is learned from the prompt and the results, rather than enforced by calling a separate ToolSelector agent. This simplifies the control flow – one agent (Claude) can replace several.
Memory and State	The SDK or developer must maintain state between calls. Each agent call is a fresh API interaction, so the conversation history (past findings, etc.) must be stitched together and given as input (e.g., the compiled history string we pass to KnowledgeGapAgent and others) ￼ ￼. Memory is external to the model’s awareness except as re-provided context.	The conversation with Claude naturally accumulates context. As tools are used within one session, Claude “remembers” the results (they’re part of the ongoing messages). There’s still state between iterations (each iteration is a new Claude session in our plan unless we keep one session throughout). We will still feed Claude a summary of prior iterations for gap evaluation, but within a single iteration’s tool-use phase, no extra code is needed to remember results – Claude’s own context handles it. This reduces the chance of context mismatch or forgetting information, as long as it’s within Claude’s token limit.
Output Handling	Each agent produces structured output (as JSON) which the code then parses to Python objects ￼ ￼. The final result is composed by the WriterAgent based on all gathered info. OpenAI’s structured output feature can enforce JSON directly for each agent’s result. However, managing many JSON outputs (plan, tasks, findings) requires careful parsing and passing of data between agents.	Claude can generate a final structured output for an iteration or task if instructed, but it doesn’t have an API-level JSON enforcement. We rely on Claude following the prompt to output the findings in JSON. The SDK’s MCP util can then parse it with our Pydantic models. In practice, this means possibly more post-processing of Claude’s output (to fix minor format issues). The benefit is that we get one coherent output per gap, already integrating all tool findings, rather than many small JSON pieces that we have to assemble. The final report writing is similar – we can either have Claude write it in one go (with the collected info) or use the existing WriterAgent.
Parallelism	Possible to run multiple tool agents in parallel (as our original code did with asyncio) ￼ ￼, since the plan is known upfront. This improves speed but at the cost of the model not being able to adjust mid-way.	Tool calls are sequential in a single conversation (Claude decides one at a time). This is more reflective and can adapt the next call based on the previous result, but may be slower for multiple queries. Claude could potentially issue concurrent calls if the MCP spec allowed bundling, but currently it does not – it’s turn-based. So we trade off some parallelism for better adaptive planning.

Implication: The MCP approach leads to a simpler, more model-centric loop: Claude handles decision-making and tool usage dynamically. The OpenAI SDK with function calls required more developer-driven sequencing (explicit tool selection and parallel management). With Claude, the flow is more flexible – e.g., Claude might choose to call crawl_website only if a web search result suggests it, whereas the old system might have needed to anticipate that in the ToolSelector step. This should make the agent more robust to different queries, at the cost of a bit more complexity in parsing the model’s outputs (since we must handle tool_use/tool_result messages).

Migration Plan (Refactor Instructions)

Following the above analysis, here is a detailed migration plan to implement the Claude MCP-based design:
	1.	Install and Import MCP Support: Make sure the openai-agents-mcp extension (or the version of OpenAI Agents SDK that includes MCP) is installed. In the codebase, update imports in relevant files:
	•	In agent definition files (like where PlannerAgent or new Claude agent is defined), use from agents_mcp import Agent, Runner instead of from agents import Agent, Runner for the agents that will use MCP. The MCP extension provides its own Agent class (subclassing the base but adding MCP capabilities) ￼.
	•	Import the MCP server class needed. For local tools, MCPServerStdio is convenient; if we choose an HTTP approach, MCPServerSse could be used with a hosted server. For now, plan on MCPServerStdio.
	2.	Create MCP Server Config for Tools: Develop a configuration for the MCP server to expose web_search and crawl_website:
	•	Write a script or module (e.g., deep_researcher/mcp_tools.py) that uses the mcp_agent library to define these tools. This might involve creating an AgentServer instance, adding tool handlers for each function. Each tool handler will call our existing implementation from tools/web_search.py or tools/crawl_website.py. Ensure to catch exceptions and return error messages as needed (so a tool_result can handle tool errors gracefully).
	•	Alternatively, utilize any pre-built MCP tool definitions. (Anthropic doesn’t have a built-in web search tool, but OpenAI’s Tools API has a web search; however, that’s separate from MCP. Likely easiest is to implement ourselves or find an open-source MCP server for web search.)
	•	Example pseudo-code for mcp_tools.py (using a hypothetical simple interface):

from mcp import Tool, run_server
import asyncio
from deep_researcher.tools import web_search, crawl_website

async def web_search_tool(query: str) -> str:
    results = await web_search(query)
    # Format the results concisely:
    summaries = [f"- {r.title}: {r.snippet}" for r in results[:3]]
    return "\n".join(summaries) + f"\nSources: {[r.url for r in results[:3]]}"

async def crawl_tool(url: str) -> str:
    text = await crawl_website(url)
    return text[:1000]  # return first 1000 chars for example

tools = [
    Tool(name="web_search", description="Search the web for information.", func=web_search_tool, inputs={"query": "string"}),
    Tool(name="crawl_website", description="Crawl a website URL and return page text.", func=crawl_tool, inputs={"url": "string"})
]
# run_server launches an MCP stdio server with these tools:
run_server(tools)

This is illustrative – the actual server setup may differ. The key point is defining the tool name, description, and input schema.

	•	Test this server standalone by running it and sending a sample list_tools or tool_use JSON to ensure it responds correctly.

	3.	Integrate MCP Server in Main Workflow: Modify the DeepResearcher and/or IterativeResearcher to initialize the MCP server and Claude model:
	•	Load the Anthropic API key from environment (e.g., ANTHROPIC_API_KEY). The llm_client.py already has logic to create OpenAIChatCompletionsModel for anthropic with the right base_url ￼. We can use that or directly instantiate via the SDK:

from agents.model import OpenAIChatCompletionsModel
claude_model = OpenAIChatCompletionsModel(model="claude-2", base_url="https://api.anthropic.com/v1/", api_key=ANTHROPIC_API_KEY)


	•	Start the MCP server:

server = MCPServerStdio(params={"command": "python", "args": ["-u", "deep_researcher/mcp_tools.py"]})
await server.start()  # if using as async, or `async with server:` block
tools = await server.list_tools()  # not strictly needed, but can log to verify tools loaded

We may integrate this into the IterativeResearcher.run() before entering the loop, or as a context manager around the whole research session. Using async with server is a clean approach to ensure it shuts down after use.

	•	Create the Claude-powered agent for tool usage (call it assistant_agent):

assistant_agent = Agent(
    name="ResearchAssistant",
    instructions=CLAUDE_INSTRUCTIONS,
    model=claude_model,
    mcp_servers=[server],
    output_type=ToolAgentOutput if not skip_json else None,
    output_parser=create_type_parser(ToolAgentOutput) if not skip_json else None
)

The CLAUDE_INSTRUCTIONS string will be crafted as described in step 4 with guidance on tool use. We use output_type=ToolAgentOutput to tell the SDK we expect a ToolAgentOutput JSON at the end. Although Anthropic doesn’t enforce, the SDK might treat Anthropic similarly to OpenAI in its model_supports_structured_output (which it does currently) ￼, so it might try to enforce JSON. We might override model_supports_structured_output for anthropic to False if needed, to use our parser approach. But initial attempt can rely on Claude to output JSON.

	•	Note: The KnowledgeGapAgent and WriterAgent can either remain using OpenAI models (gpt-3.5/gpt-4) or we can also switch them to use Claude for consistency. It might make sense to use Claude for all steps to maintain a single conversation style. However, using Claude for quick evaluations or final long outputs might be expensive. A hybrid approach is fine (fast model for gap eval, Claude for deep info gathering, GPT-4 for final writing). For this plan, we will keep KnowledgeGapAgent as is (maybe GPT-3.5) and WriterAgent as GPT-4, and we’ll focus the Claude usage on the main research loop actions.

	4.	Refactor Iteration Loop: Pseudocode for the new loop inside IterativeResearcher.run:

for iteration in range(max_iterations):
    # 1. Knowledge Gap Analysis (same as before)
    evaluation = await ResearchRunner.run(knowledge_gap_agent, conversation_input)
    gaps = evaluation.final_output_as(KnowledgeGapOutput).outstanding_gaps
    if evaluation.research_complete or not gaps:
        break  # done researching
    gap = gaps[0]
    self.conversation.set_latest_gap(gap)
    # 2. Claude uses tools to research the gap
    user_message = f"KNOWLEDGE GAP: {gap}\n" \
                   f"CONTEXT: {background_context or 'None'}\n" \
                   f"PREVIOUS FINDINGS: {self.conversation.get_all_findings()}"  # maybe provide all findings so far
    result = await ResearchRunner.run(assistant_agent, user_message)
    # The assistant_agent will internally call tools and finally return a JSON
    output = result.final_output_as(ToolAgentOutput)
    findings_text = output.output
    sources_list = output.sources
    # Log findings and sources
    self.conversation.set_latest_findings([findings_text])
    if self.verbose:
        print(f"Findings:\n{findings_text}\nSources: {sources_list}")
    # Optionally, we can also get a "thought" from Claude here, but KnowledgeGapAgent will re-evaluate anyway.
    # Continue loop to next gap
# After loop, compile report
report = await ResearchRunner.run(writer_agent, self.conversation.compile_conversation_history())

This pseudocode shows the core changes: replacing tool selection and execution with one assistant_agent call. We supply it with the current gap and all prior findings as context (Claude will also have tool outputs from this iteration in-session). We then parse the output and store it. We’d repeat for additional gaps if any.
We have to ensure the assistant_agent prompt (CLAUDE_INSTRUCTIONS) is designed to take the user_message in that format. It could be something like: “You will be given a knowledge gap and some context. Use the available tools to find information to fill the gap.” and the user_message provides the KNOWLEDGE GAP and PREVIOUS FINDINGS. Alternatively, we include previous findings in system instructions each time. We might need to experiment with where to put context so that Claude doesn’t ignore it. Likely fine as part of the user message.

	5.	Testing the Refactored Flow: Once implemented, test with a few example queries:
	•	Use a small topic with a clear sub-question to see if Claude calls the tools appropriately. For instance, query: “Who was the first person in space and what year did it happen?” KnowledgeGapAgent might identify two pieces (the person, the year or context). Claude might call web_search for “first person in space” -> gets result about Yuri Gagarin 1961, then possibly it has enough to answer. Ensure it outputs JSON with that info.
	•	Check that if multiple iterations are needed, the loop works. E.g., a broader query: “Explain quantum computing and its history.” The PlannerAgent (outline creator) might break this into subtopics (we might have to integrate PlannerAgent differently or just treat the whole query as one gap for Claude in iterative mode for now). In iterative mode, KnowledgeGapAgent might always return not complete until some condition; we need to see if it properly turns true when enough info gathered.
	•	Evaluate that sources are being collected and passed to WriterAgent. The final WriterAgent should incorporate those sources into citations. If WriterAgent expects sources inline (like “[1]” references), we may need to ensure the sources from Claude are formatted or at least available to it. Possibly we modify WriterAgent’s prompt to consider conversation.get_all_findings() (which contain source URLs) and instruct it to cite them.
	•	Performance: measure how many API calls are made. In the old system, each iteration could trigger: GapAgent call, ToolSelector call, multiple ToolAgent calls, ThinkingAgent call – e.g., 4-5 model calls per iteration. In the new system, we have: GapAgent, Claude (which internally may stream multiple tool calls but it’s one external call), possibly Thinking (but we dropped explicit thinking). So ~2 model calls per iteration. This is more efficient in terms of API round-trips, though Claude’s single call might consume more tokens (since it handles more logic internally).
	6.	Iterate on Claude Prompting: If Claude isn’t using the tools correctly or formatting outputs right, adjust CLAUDE_INSTRUCTIONS. For example:
	•	If Claude sometimes tries to answer without using a tool even when it lacks info, emphasize in instructions: “Always use the tools if the answer is not immediately known or to verify facts.” Potentially provide a one-turn example in the prompt showing a tool_use -> tool_result -> pattern.
	•	If Claude’s output JSON is malformed (say it forgets quotes or adds commentary outside JSON), we might need to add a final system nudge: “Remember: Output ONLY the JSON.” and rely on the parser to fix minor issues. The create_type_parser can handle out-of-order keys or small errors, but not a completely free-form answer.
	•	If Claude doesn’t list sources in the JSON, ensure during the tool_result handling on our side, we append source URLs to the content we return. E.g., in web_search_tool above, we included a “Sources: […]” line. Claude could then easily include those in its final output. We might also instruct: “List any sources provided in the tool results in the sources field of your output.”
	7.	Maintain OpenAI Compatibility (if needed): We should preserve the option to use the original GPT-based pipeline. Perhaps add a flag or check on model type. If use_claude is True, do the Claude/MCP path; if False, do the original path. This can be controlled by an environment variable or parameter (the README suggests the tool is compatible with multiple providers ￼). This way, users can choose to run with OpenAI models or Claude. In code, we may do:

if model_provider == "anthropic":
    ... (Claude loop as above)
else:
    ... (old tool selection and execution code)

Ensure all necessary imports (agents_mcp, etc.) are gated to when we use them, to avoid requiring those packages when using OpenAI mode only.

	8.	Update Documentation and Comments:
	•	Clearly note in README or usage docs that if using Claude (via setting PROVIDER=anthropic and providing an Anthropic API key), the system now uses an integrated tool-calling approach. Mention that TOOL_AGENTS and ToolSelector are bypassed in that case.
	•	In comments within code, explain that assistant_agent (Claude) handles what ToolSelectorAgent + ToolAgents did.
	•	Adjust the Implementing Custom Tool Agents section of README ￼ to clarify that for non-MCP usage one must add to TOOL_AGENTS, but for MCP/Claude, one would instead add the tool to the MCP server and include it in Claude’s prompt.
	9.	Prototype Example Verification:
	•	Take one of the sample outputs from the README’s examples (e.g., “Life and Works of Plato”) and run the new pipeline with Claude. Compare the final report with the sample. It should cover similar points and have references. We expect differences in style, but it should be comprehensive. This validates that Claude with tools can achieve the same depth.
	•	If there are gaps (maybe Claude didn’t dig as much), consider increasing iterations or instructing KnowledgeGapAgent to force more iterations. Possibly Claude might consider the answer done sooner than GPT-4 did. In that case, we might rely on KnowledgeGapAgent (which might be GPT-3.5) to catch if things are missing. We can always nudge by adjusting its completeness criteria or allow more iterations.

Prototype Refactor Example (Refactoring a Tool Agent to MCP)

Let’s refactor the WebSearchAgent and its usage as a prototype:
	•	Before (WebSearchAgent with OpenAI SDK): The WebSearchAgent was defined as:

search_agent = ResearchAgent(
    name="WebSearchAgent",
    instructions=INSTRUCTIONS,  # had steps to use web_search tool
    tools=[web_search_tool],    # web_search function
    model=fast_model,
    output_type=ToolAgentOutput ...
)

It would be invoked via PlannerAgent or ToolSelectorAgent. The LLM inside would output something like {"function": "web_search", "args": {...}} to call the tool, then get results, then output a summary JSON.

	•	After (Claude using MCP): We eliminate the WebSearchAgent entirely from flow. Instead, we ensure the web_search function is on the MCP server. Where PlannerAgent (Claude) would have used WebSearchAgent, now Claude itself uses tool_use: web_search.

For example, consider the conversation when Claude is addressing a gap:
	•	Claude (as ResearchAssistant) receives: “KNOWLEDGE GAP: Explain quantum computing history.” It knows it has web_search tool. It might respond:

{"tool_use": {"tool": "web_search", "input": "quantum computing history timeline"}}


	•	Our MCP server executes that query and returns a tool_result like:

{"tool_result": {"tool": "web_search", "output": "- Quantum computing field founded in 1980s...\n- 1994: Shor's algorithm...\nSources: ['https://example.com/quantum_history', 'https://another.com/quantum_timeline']"}}


	•	Claude reads this, and perhaps asks for more:

{"tool_use": {"tool": "web_search", "input": "quantum computing key milestones 2000s"}}

(Another search query focused on 2000s.)

	•	We execute it, return results.
	•	Claude then produces a final message (since we told it to output JSON final findings):

{"output": "Quantum computing has its roots in the 1980s... In 1994, Peter Shor developed ... In the 2000s, experimental quantum processors emerged ...", "sources": ["https://example.com/quantum_history","https://another.com/quantum_timeline"]}


	•	This is captured by the SDK as the final output for that agent run.

In code, we parse that into a ToolAgentOutput object and proceed. The prototype shows how one tool (web_search) is now called via MCP. The same applies to crawl_website: instead of having a CrawlerAgent, Claude would do tool_use: crawl_website when needed (for example, if a search result source needs deeper info, Claude could decide to crawl it if our instructions encourage using the crawler for domain-specific info).

We should also test a scenario involving the crawl_website to ensure Claude uses it. For instance, if the query is about “Tesla’s financial report 2021” – KnowledgeGap might identify a gap that requires going to Tesla’s investor site. Claude might do tool_use: web_search (find Tesla investor site), then tool_use: crawl_website on that URL, then compile findings. This would prove the multi-tool capability in one agent.

Testing Strategy

After implementing the refactor, we will validate the system thoroughly:
	•	Unit Tests for Tools via MCP: Write tests for the mcp_tools.py server functions. For example, simulate a web_search call and ensure it returns a string containing expected info and sources. Similarly test crawl_website on a sample HTML input (perhaps using a local file or a known small page). Ensuring these lower-level functions work prevents tool invocation errors at runtime.
	•	Integration Test with Claude (if possible in non-production): Using a smaller Anthropic model (Claude Instant or 1-sha if available) or a sandbox, run a full iteration on a known question and inspect logs:
	•	Confirm that the tool_use and tool_result messages appear as expected. The Agents SDK’s trace or debug mode can show these events. We want to see that when Claude requests a tool, the server executes and returns a result, and then Claude continues.
	•	Check that the final result of the iteration is correctly parsed into ToolAgentOutput and that outstanding_gaps reduce or go empty accordingly.
	•	Comparison with Original Behavior: Run the original multi-agent version and the new Claude version on the same query (with the same research constraints like max_iterations=2 or 3) and compare outputs:
	•	Are the key facts present in both? Did Claude maybe miss some detail the multi-step process found? If so, possibly Claude stopped early – we might then adjust the prompt to be more exhaustive or allow one more iteration.
	•	Is Claude introducing any factual errors? The tool usage should minimize that, but double-check. The KnowledgeGapAgent will also help catch if something is incomplete.
	•	Compare lengths: Claude’s combined summary per iteration might be more concise or more verbose. If it’s too concise, maybe instruct it to be thorough. If too verbose, we can live with it or ask it to be succinct since the WriterAgent will later refine.
	•	Final Report Validation: Ensure that the final WriterAgent (which likely still runs on GPT-4 or Claude) gets everything. We pass it the conversation.compile_conversation_history(), which now contains all iterations with findings (and maybe the gaps and maybe the tools used if we logged them). The compile function might need minor tweak if we changed how actions are stored. For example, we might not have stored explicit <action> entries for tool uses as we did before (since no ToolSelector step). We can decide to log Claude’s tool calls in the conversation. It could be useful for traceability to append in conversation.tool_calls something like "Claude used web_search on 'X query'". The compiled history would then include an <action> section for that iteration. This is optional for functionality (the WriterAgent might not need to know the queries run), but it could provide transparency. Alternatively, we focus the conversation history on findings and thoughts, which is likely sufficient for WriterAgent to do its job (it mainly needs the content to write about).
	•	Error Handling: Simulate errors, e.g., what if web_search tool returns an error (like API limit reached or no results found)? Our MCP server should catch exceptions and return a message like "No relevant results found". Claude should handle that (maybe it will try a different query). We should test that Claude doesn’t break on an empty result. Possibly add logic: if no results, our web_search_tool returns a specific output, and Claude’s prompt should mention that if a tool result is not useful, it can decide to try a different approach. Observing a few edge cases will ensure robustness.
	•	Performance and Rate Limits: Using Claude means each tool use still counts against context and prompt tokens. If Claude calls many tools or the results are long, it could rack up tokens. However, since we limit to relevant snippets, it should be manageable. We will test with the max_time_minutes parameter – for a large query, does it finish under the time? If not, we may reduce scope or instruct Claude to limit length of intermediate results (perhaps by truncating in the MCP server as we did with crawl_tool snippet).
	•	User Experience: Finally, run the CLI (deep_researcher/main.py) in both --verbose and normal mode with Claude as backend. In verbose mode, printouts should show progress (we might include prints like “Tool use: web_search -> got X results” to mimic the step-by-step progress previously shown by verbose). Ensure no exceptions are thrown and the output is neatly printed at the end.

Through these testing steps, we will verify correctness and completeness of the refactored system. The refactor will be successful when the Deep Researcher can run with Anthropic Claude, dynamically use the web and crawler tools, and produce a detailed report comparable to the original implementation, all while maintaining clarity and using the structured MCP interaction for tool usage.