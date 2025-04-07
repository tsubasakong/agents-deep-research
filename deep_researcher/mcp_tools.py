"""
MCP Server for Deep Researcher tools.

This module implements an MCP (Model Context Protocol) server that exposes the
web_search and crawl_website tools to Claude or other MCP-compatible models.
"""

import asyncio
from typing import List, Dict, Any
from agents.mcp import MCPTool
from agents.mcp.server import MCPServerStdio
from .tools.web_search import web_search, ScrapeResult
from .tools.crawl_website import crawl_website


async def web_search_tool(query: str) -> str:
    """Format web search results for MCP."""
    try:
        results = await web_search(query)
        
        # Check if results is a string (error message)
        if isinstance(results, str):
            return results
        
        # Format the results concisely
        formatted_results = []
        sources = []
        
        for r in results[:5]:  # Limit to top 5 results
            formatted_results.append(f"- {r.title}: {r.snippet if hasattr(r, 'snippet') else r.description}")
            sources.append(r.url)
        
        result_text = "\n".join(formatted_results)
        source_text = f"\nSources: {sources}"
        
        return result_text + source_text
    except Exception as e:
        return f"Error performing web search: {str(e)}"


async def crawl_tool(url: str) -> str:
    """Format website crawling results for MCP."""
    try:
        results = await crawl_website(url)
        
        # Check if results is a string (error message)
        if isinstance(results, str):
            return results
        
        # Format the results concisely
        formatted_results = []
        sources = []
        
        for r in results[:5]:  # Limit to top 5 pages
            content_preview = r.text[:500] + "..." if len(r.text) > 500 else r.text
            formatted_results.append(f"Page: {r.title or r.url}\n{content_preview}")
            sources.append(r.url)
        
        result_text = "\n\n".join(formatted_results)
        source_text = f"\n\nSources: {sources}"
        
        return result_text + source_text
    except Exception as e:
        return f"Error crawling website: {str(e)}"


def main():
    """Run the MCP server."""
    tools = [
        MCPTool(
            name="web_search",
            description="Search the web for information using Google. Returns snippets and URLs.",
            function=web_search_tool,
            parameters={
                "query": {
                    "type": "string",
                    "description": "The search query to use (3-5 words works best)"
                }
            }
        ),
        MCPTool(
            name="crawl_website",
            description="Crawl a website URL and extract text content from multiple pages.",
            function=crawl_tool,
            parameters={
                "url": {
                    "type": "string",
                    "description": "The URL of the website to crawl"
                }
            }
        )
    ]
    
    # Create and run the MCP server with the tools
    server = MCPServerStdio(
        params={
            "command": "python",
            "args": ["-m", "agents.mcp.stdio_server"]
        },
        name="Deep Researcher Tools"
    )
    
    asyncio.run(server.serve_tools(tools))


if __name__ == "__main__":
    main() 