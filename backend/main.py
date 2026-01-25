from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Any
import os
import asyncio
from backend.dependencies import get_current_user, supabase


app = FastAPI(title="BeePrepared API", description="Knowledge Architecture Pipeline")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Node(BaseModel):
    id: str
    type: str
    data: Any
    position: dict

class Edge(BaseModel):
    id: str
    source: str
    target: str

class RunRequest(BaseModel):
    project_id: str
    nodes: List[Node]
    edges: List[Edge]

@app.get("/")
async def root():
    return {"status": "operational", "service": "BeePrepared API"}

@app.post("/run")
async def run_pipeline(
    request: RunRequest, 
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user)
):
    """
    Activates the architectural pipeline for a project.
    """
    # Verify project ownership
    project = supabase.table("projects").select("*").eq("id", request.project_id).eq("user_id", user_id).execute()
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found or access denied")

    # Filter for process nodes that need activation
    process_nodes = [n for n in request.nodes if n.type == 'process']
    
    if not process_nodes:
        return {"message": "No process nodes found in architecture", "activated_nodes": 0}

    # Start background processing
    background_tasks.add_task(process_pipeline, request.project_id, request.nodes, request.edges, user_id)

    return {
        "message": "Pipeline activation initiated",
        "activated_nodes": len(process_nodes),
        "project_id": request.project_id
    }

async def process_pipeline(project_id: str, nodes: List[Node], edges: List[Edge], user_id: str):
    """
    Simulates the background processing of knowledge nodes.
    """
    # 1. Update all process nodes to 'processing' status
    updated_nodes = []
    for node in nodes:
        node_dict = node.dict()
        if node.type == 'process':
            node_dict['data']['status'] = 'processing'
            node_dict['data']['progress'] = 10
        updated_nodes.append(node_dict)

    # Persist intermediate status
    supabase.table("projects").update({"nodes": updated_nodes}).eq("id", project_id).execute()

    # 2. Simulate multi-stage processing
    for percent in [30, 60, 90, 100]:
        await asyncio.sleep(2) # Simulate work
        
        for node in updated_nodes:
            if node['type'] == 'process':
                node['data']['progress'] = percent
                if percent == 100:
                    node['data']['status'] = 'ready'
        
        # Update progress in DB
        supabase.table("projects").update({"nodes": updated_nodes}).eq("id", project_id).execute()

    # 3. Finalize: Identify connected result nodes and mark them as ready
    # In a real scenario, this is where we'd generate the actual artifacts
    for edge in edges:
        source_node = next((n for n in updated_nodes if n['id'] == edge.source), None)
        target_node = next((n for n in updated_nodes if n['id'] == edge.target), None)
        
        if source_node and target_node:
            if source_node['type'] == 'process' and target_node['type'] == 'result':
                target_node['data']['status'] = 'ready'

    supabase.table("projects").update({"nodes": updated_nodes}).eq("id", project_id).execute()

@app.post("/ingest")
def ingest_file(file_url: str, user_id: str = Depends(get_current_user)):
    return {"message": f"Processing file for user {user_id}", "url": file_url}
