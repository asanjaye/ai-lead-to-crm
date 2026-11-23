"""
Approval UI - Simple web interface for reviewing and approving lead replies.

This service provides a human-in-the-loop interface for:
- Viewing pending approval requests
- Reviewing AI-generated draft replies
- Approving, editing, or rejecting replies
- Triggering n8n webhooks on approval/rejection
"""

import os
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import httpx
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(
    title="Lead Approval UI",
    description="Human-in-the-loop approval interface for AI-generated lead replies",
    version="1.0.0"
)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://n8n:n8n_password@localhost:5432/leads_db")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://n8n:5678")

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def get_db_connection():
    """Get a database connection."""
    parsed = urlparse(DATABASE_URL)
    return psycopg2.connect(
        host=parsed.hostname,
        port=parsed.port or 5432,
        user=parsed.username,
        password=parsed.password,
        dbname=parsed.path[1:],
        cursor_factory=RealDictCursor
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard showing pending approvals."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                aq.id as approval_id,
                l.id as lead_id,
                l.name,
                l.email,
                l.company,
                l.message,
                l.classification,
                l.intent,
                l.summary,
                l.confidence_score,
                aq.draft_subject,
                aq.draft_body,
                aq.priority,
                aq.created_at,
                aq.callback_webhook_url
            FROM approval_queue aq
            JOIN leads l ON aq.lead_id = l.id
            WHERE aq.status = 'pending'
            ORDER BY aq.priority DESC, aq.created_at ASC
        """)
        
        pending = cur.fetchall()
        
        cur.execute("""
            SELECT 
                classification,
                COUNT(*) as count
            FROM leads
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY classification
        """)
        stats = {row['classification']: row['count'] for row in cur.fetchall()}
        
        cur.execute("""
            SELECT COUNT(*) as count 
            FROM approval_queue 
            WHERE status = 'pending'
        """)
        pending_count = cur.fetchone()['count']
        
        cur.execute("""
            SELECT COUNT(*) as count 
            FROM approval_queue 
            WHERE status = 'approved' AND reviewed_at > NOW() - INTERVAL '24 hours'
        """)
        approved_today = cur.fetchone()['count']
        
        conn.close()
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "pending_approvals": pending,
            "stats": stats,
            "pending_count": pending_count,
            "approved_today": approved_today
        })
        
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": str(e)
        })


@app.get("/approval/{approval_id}", response_class=HTMLResponse)
async def view_approval(request: Request, approval_id: int):
    """View details of a specific approval request."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                aq.id as approval_id,
                l.id as lead_id,
                l.name,
                l.email,
                l.company,
                l.message,
                l.classification,
                l.intent,
                l.summary,
                l.confidence_score,
                aq.draft_subject,
                aq.draft_body,
                aq.priority,
                aq.created_at,
                aq.callback_webhook_url,
                aq.callback_execution_id
            FROM approval_queue aq
            JOIN leads l ON aq.lead_id = l.id
            WHERE aq.id = %s
        """, (approval_id,))
        
        approval = cur.fetchone()
        conn.close()
        
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")
        
        return templates.TemplateResponse("approval_detail.html", {
            "request": request,
            "approval": approval
        })
        
    except HTTPException:
        raise
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": str(e)
        })


@app.post("/approval/{approval_id}/approve")
async def approve_lead(
    approval_id: int,
    edited_subject: str = Form(...),
    edited_body: str = Form(...),
    reviewer_name: str = Form(default="Human Reviewer")
):
    """Approve a lead reply (optionally with edits)."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT callback_webhook_url, callback_execution_id, lead_id
            FROM approval_queue
            WHERE id = %s AND status = 'pending'
        """, (approval_id,))
        
        approval = cur.fetchone()
        if not approval:
            conn.close()
            raise HTTPException(status_code=404, detail="Approval not found or already processed")
        
        cur.execute("""
            UPDATE approval_queue
            SET status = 'approved',
                reviewed_by = %s,
                reviewed_at = NOW(),
                draft_subject = %s,
                draft_body = %s
            WHERE id = %s
        """, (reviewer_name, edited_subject, edited_body, approval_id))
        
        cur.execute("""
            UPDATE leads
            SET status = 'approved',
                approved_by = %s,
                approved_at = NOW(),
                draft_subject = %s,
                draft_reply = %s
            WHERE id = %s
        """, (reviewer_name, edited_subject, edited_body, approval['lead_id']))
        
        cur.execute("""
            INSERT INTO processing_log (lead_id, action, status, details)
            VALUES (%s, 'human_approval', 'approved', %s)
        """, (
            approval['lead_id'],
            f'{{"reviewer": "{reviewer_name}", "edited": true}}'
        ))
        
        conn.commit()
        
        if approval['callback_webhook_url']:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        approval['callback_webhook_url'],
                        json={
                            "approval_id": approval_id,
                            "lead_id": approval['lead_id'],
                            "status": "approved",
                            "subject": edited_subject,
                            "body": edited_body,
                            "reviewer": reviewer_name,
                            "execution_id": approval['callback_execution_id']
                        },
                        timeout=10.0
                    )
            except Exception as webhook_error:
                cur.execute("""
                    INSERT INTO processing_log (lead_id, action, status, details, error_message)
                    VALUES (%s, 'webhook_callback', 'error', '{}', %s)
                """, (approval['lead_id'], str(webhook_error)))
                conn.commit()
        
        conn.close()
        return RedirectResponse(url="/?approved=true", status_code=303)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/approval/{approval_id}/reject")
async def reject_lead(
    approval_id: int,
    rejection_reason: str = Form(...),
    reviewer_name: str = Form(default="Human Reviewer")
):
    """Reject a lead reply."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT callback_webhook_url, callback_execution_id, lead_id
            FROM approval_queue
            WHERE id = %s AND status = 'pending'
        """, (approval_id,))
        
        approval = cur.fetchone()
        if not approval:
            conn.close()
            raise HTTPException(status_code=404, detail="Approval not found or already processed")
        
        cur.execute("""
            UPDATE approval_queue
            SET status = 'rejected',
                reviewed_by = %s,
                reviewed_at = NOW(),
                review_notes = %s
            WHERE id = %s
        """, (reviewer_name, rejection_reason, approval_id))
        
        cur.execute("""
            UPDATE leads
            SET status = 'rejected',
                rejection_reason = %s
            WHERE id = %s
        """, (rejection_reason, approval['lead_id']))
        
        cur.execute("""
            INSERT INTO processing_log (lead_id, action, status, details)
            VALUES (%s, 'human_approval', 'rejected', %s)
        """, (
            approval['lead_id'],
            f'{{"reviewer": "{reviewer_name}", "reason": "{rejection_reason}"}}'
        ))
        
        conn.commit()
        
        if approval['callback_webhook_url']:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        approval['callback_webhook_url'],
                        json={
                            "approval_id": approval_id,
                            "lead_id": approval['lead_id'],
                            "status": "rejected",
                            "reason": rejection_reason,
                            "reviewer": reviewer_name,
                            "execution_id": approval['callback_execution_id']
                        },
                        timeout=10.0
                    )
            except Exception:
                pass
        
        conn.close()
        return RedirectResponse(url="/?rejected=true", status_code=303)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history", response_class=HTMLResponse)
async def approval_history(request: Request, limit: int = 50):
    """View history of processed approvals."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT 
                aq.id as approval_id,
                l.name,
                l.email,
                l.classification,
                aq.status,
                aq.reviewed_by,
                aq.reviewed_at,
                aq.review_notes
            FROM approval_queue aq
            JOIN leads l ON aq.lead_id = l.id
            WHERE aq.status != 'pending'
            ORDER BY aq.reviewed_at DESC
            LIMIT %s
        """, (limit,))
        
        history = cur.fetchall()
        conn.close()
        
        return templates.TemplateResponse("history.html", {
            "request": request,
            "history": history
        })
        
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": str(e)
        })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3001)
