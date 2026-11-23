"""
Lead Classifier Service - FastAPI microservice for AI-powered lead classification.

This service provides:
- Lead classification (hot/warm/cold/spam)
- Intent detection
- Summary generation
- Personalized reply drafting

Supports OpenAI and Anthropic as LLM providers, configurable via environment variables.
"""

import os
import time
from datetime import datetime
from typing import Literal

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from classifier import LeadClassifier, ClassificationResult, DraftReply

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

app = FastAPI(
    title="Lead Classifier API",
    description="AI-powered lead classification and reply drafting service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

classifier = LeadClassifier()


class LeadInput(BaseModel):
    """Input model for lead classification."""
    name: str = Field(..., min_length=1, max_length=255, description="Lead's full name")
    email: EmailStr = Field(..., description="Lead's email address")
    company: str | None = Field(None, max_length=255, description="Lead's company name")
    message: str = Field(..., min_length=10, max_length=10000, description="Lead's inquiry message")
    source: str = Field(default="web_form", description="Source of the lead")


class ClassifyRequest(BaseModel):
    """Request model for classification endpoint."""
    lead: LeadInput
    include_draft_reply: bool = Field(default=True, description="Whether to generate a draft reply")


class ClassifyResponse(BaseModel):
    """Response model for classification endpoint."""
    lead_id: str | None = None
    classification: ClassificationResult
    draft_reply: DraftReply | None = None
    processing_time_ms: int
    provider: str
    model: str
    timestamp: str


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    provider: str
    model: str
    timestamp: str


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    error_type: str
    retryable: bool
    timestamp: str


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        provider=classifier.provider,
        model=classifier.model,
        timestamp=datetime.utcnow().isoformat()
    )


@app.post("/classify", response_model=ClassifyResponse)
async def classify_lead(request: ClassifyRequest):
    """
    Classify a lead and optionally generate a draft reply.
    
    This endpoint:
    1. Analyzes the lead's message using an LLM
    2. Returns classification (hot/warm/cold/spam), intent, summary, and confidence
    3. Optionally generates a personalized draft reply
    
    The draft reply is NEVER auto-sent - it's returned for human approval.
    """
    start_time = time.time()
    log = logger.bind(
        email=request.lead.email,
        company=request.lead.company,
        source=request.lead.source
    )
    
    log.info("classification_started")
    
    try:
        classification = await classifier.classify(
            name=request.lead.name,
            email=request.lead.email,
            company=request.lead.company,
            message=request.lead.message
        )
        
        log.info(
            "classification_completed",
            classification=classification.classification,
            intent=classification.intent,
            confidence=classification.confidence_score
        )
        
        draft_reply = None
        if request.include_draft_reply and classification.classification != "spam":
            draft_reply = await classifier.generate_draft_reply(
                name=request.lead.name,
                email=request.lead.email,
                company=request.lead.company,
                message=request.lead.message,
                classification=classification
            )
            log.info("draft_reply_generated", subject=draft_reply.subject)
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        return ClassifyResponse(
            classification=classification,
            draft_reply=draft_reply,
            processing_time_ms=processing_time_ms,
            provider=classifier.provider,
            model=classifier.model,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        log.error("classification_failed", error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "error_type": type(e).__name__,
                "retryable": _is_retryable_error(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


@app.post("/classify/batch")
async def classify_batch(leads: list[LeadInput], include_draft_reply: bool = True):
    """
    Classify multiple leads in batch.
    
    Returns results for all leads, with individual errors tracked per lead.
    """
    results = []
    
    for lead in leads:
        try:
            request = ClassifyRequest(lead=lead, include_draft_reply=include_draft_reply)
            result = await classify_lead(request)
            results.append({"success": True, "data": result})
        except HTTPException as e:
            results.append({"success": False, "error": e.detail})
        except Exception as e:
            results.append({
                "success": False,
                "error": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "retryable": _is_retryable_error(e)
                }
            })
    
    return {
        "total": len(leads),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results
    }


@app.get("/providers")
async def list_providers():
    """List available LLM providers and current configuration."""
    return {
        "current_provider": classifier.provider,
        "current_model": classifier.model,
        "available_providers": ["openai", "anthropic"],
        "openai_models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "anthropic_models": ["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"]
    }


def _is_retryable_error(e: Exception) -> bool:
    """Determine if an error is retryable."""
    retryable_types = [
        "RateLimitError",
        "APIConnectionError",
        "Timeout",
        "ServiceUnavailableError",
        "InternalServerError"
    ]
    return type(e).__name__ in retryable_types or "rate" in str(e).lower() or "timeout" in str(e).lower()


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests."""
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = (time.time() - start_time) * 1000
    logger.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(process_time, 2)
    )
    
    return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
