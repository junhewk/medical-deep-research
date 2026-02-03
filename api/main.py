"""
Medical Deep Research - FastAPI Backend

This module provides the REST API for the research engine,
wrapping the DeepAgentResearchSystem for use by the Next.js frontend.
"""

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Load environment variables
load_dotenv()

# Add the source directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# In-memory research store (for real-time progress tracking)
# In production, this would use Redis or similar
research_jobs: Dict[str, Dict[str, Any]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    print("Starting Medical Deep Research API...")
    yield
    print("Shutting down Medical Deep Research API...")


app = FastAPI(
    title="Medical Deep Research API",
    description="Evidence-Based Medical Research Assistant API",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    """Request model for starting research."""

    research_id: Optional[str] = None
    query: str
    llm_provider: str = "openai"
    model: str = "gpt-4o"
    user_id: Optional[str] = None


class ResearchResponse(BaseModel):
    """Response model for research status."""

    id: str
    query: str
    status: str
    progress: int
    phase: Optional[str] = None
    planning_steps: List[Dict[str, Any]] = []
    active_agents: List[Dict[str, Any]] = []
    tool_executions: List[Dict[str, Any]] = []
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


def get_llm(provider: str, model: str):
    """Get the appropriate LLM based on provider."""
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=os.getenv("OPENAI_API_KEY"),
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
        )
    elif provider == "google" or provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )
    elif provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        )
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


async def run_research(research_id: str, request: ResearchRequest):
    """Run the research process in the background."""
    try:
        # Update status to running
        research_jobs[research_id]["status"] = "running"
        research_jobs[research_id]["phase"] = "initializing"

        # Import research system
        try:
            from local_deep_research.deep_agent_system import DeepAgentResearchSystem
            from local_deep_research.web_search_engines.engines.pubmed_search import (
                PubMedSearchEngine,
            )
        except ImportError as e:
            research_jobs[research_id]["status"] = "failed"
            research_jobs[research_id]["error"] = f"Import error: {str(e)}"
            return

        # Get LLM
        llm = get_llm(request.llm_provider, request.model)

        # Create search engine
        search = PubMedSearchEngine()

        # Create research system
        system = DeepAgentResearchSystem(
            llm=llm,
            search=search,
            max_iterations=10,
            research_id=research_id,
        )

        # Set progress callback
        def progress_callback(message: str, progress: int, metadata: dict):
            research_jobs[research_id]["progress"] = progress
            research_jobs[research_id]["phase"] = metadata.get("phase", "processing")

            if metadata.get("planning_steps"):
                research_jobs[research_id]["planning_steps"] = metadata["planning_steps"]

            if metadata.get("active_agents"):
                research_jobs[research_id]["active_agents"] = metadata["active_agents"]

            if metadata.get("tool_executions"):
                research_jobs[research_id]["tool_executions"] = metadata[
                    "tool_executions"
                ]

        system.set_progress_callback(progress_callback)

        # Run research
        result = system.analyze_topic(request.query)

        # Update with results
        research_jobs[research_id]["status"] = "completed"
        research_jobs[research_id]["progress"] = 100
        research_jobs[research_id]["phase"] = "complete"
        research_jobs[research_id]["result"] = result.get(
            "formatted_findings", str(result)
        )
        research_jobs[research_id]["completed_at"] = datetime.now().isoformat()

    except Exception as e:
        research_jobs[research_id]["status"] = "failed"
        research_jobs[research_id]["error"] = str(e)
        research_jobs[research_id]["phase"] = "error"


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Medical Deep Research API",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/research", response_model=Dict[str, str])
async def start_research(
    request: ResearchRequest, background_tasks: BackgroundTasks
):
    """Start a new research job."""
    research_id = request.research_id or str(uuid.uuid4())

    # Initialize research job
    research_jobs[research_id] = {
        "id": research_id,
        "query": request.query,
        "status": "pending",
        "progress": 0,
        "phase": "queued",
        "planning_steps": [],
        "active_agents": [],
        "tool_executions": [],
        "result": None,
        "error": None,
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
    }

    # Start research in background
    background_tasks.add_task(run_research, research_id, request)

    return {"research_id": research_id}


@app.get("/research/{research_id}", response_model=ResearchResponse)
async def get_research(research_id: str):
    """Get research status and progress."""
    if research_id not in research_jobs:
        raise HTTPException(status_code=404, detail="Research not found")

    job = research_jobs[research_id]

    return ResearchResponse(
        id=job["id"],
        query=job["query"],
        status=job["status"],
        progress=job["progress"],
        phase=job.get("phase"),
        planning_steps=job.get("planning_steps", []),
        active_agents=job.get("active_agents", []),
        tool_executions=job.get("tool_executions", []),
        result=job.get("result"),
        error=job.get("error"),
        created_at=job.get("created_at"),
        completed_at=job.get("completed_at"),
    )


@app.delete("/research/{research_id}")
async def cancel_research(research_id: str):
    """Cancel a running research job."""
    if research_id not in research_jobs:
        raise HTTPException(status_code=404, detail="Research not found")

    research_jobs[research_id]["status"] = "cancelled"
    research_jobs[research_id]["phase"] = "cancelled"

    return {"message": "Research cancelled"}


@app.get("/research")
async def list_research():
    """List all research jobs."""
    return list(research_jobs.values())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
