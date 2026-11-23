-- =============================================================================
-- AI Lead-to-CRM Workflow - Database Schema
-- =============================================================================
-- This schema creates a CRM-like data store for leads.
-- Compatible with PostgreSQL. For Google Sheets/Airtable migration, see README.

-- Create leads database (separate from n8n's internal db)
CREATE DATABASE leads_db;

\connect leads_db;

-- -----------------------------------------------------------------------------
-- Leads Table - Core lead data
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    
    -- Contact Information
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    company VARCHAR(255),
    message TEXT NOT NULL,
    
    -- AI Classification Results
    classification VARCHAR(20) CHECK (classification IN ('hot', 'warm', 'cold', 'spam')),
    intent VARCHAR(100),
    summary TEXT,
    confidence_score DECIMAL(3, 2),
    
    -- Processing Status
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN (
        'pending',           -- Just received
        'classified',        -- AI has classified
        'draft_created',     -- Reply drafted
        'awaiting_approval', -- Waiting for human review
        'approved',          -- Human approved reply
        'rejected',          -- Human rejected reply
        'sent',              -- Reply sent
        'error'              -- Processing failed
    )),
    
    -- Draft Reply (held for approval)
    draft_reply TEXT,
    draft_subject VARCHAR(255),
    
    -- Approval Tracking
    approved_by VARCHAR(255),
    approved_at TIMESTAMP,
    rejection_reason TEXT,
    
    -- Metadata
    source VARCHAR(100) DEFAULT 'web_form',
    ip_address INET,
    user_agent TEXT,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    
    -- Error Tracking
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    last_error_at TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- Processing Log - Audit trail for all operations
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS processing_log (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    
    -- Log Entry Details
    action VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL,
    details JSONB,
    
    -- Error Information (if applicable)
    error_type VARCHAR(100),
    error_message TEXT,
    stack_trace TEXT,
    
    -- Execution Context
    workflow_execution_id VARCHAR(255),
    node_name VARCHAR(255),
    
    -- Timing
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- Approval Queue - Pending human approvals
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS approval_queue (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
    
    -- Approval Request Details
    request_type VARCHAR(50) DEFAULT 'send_reply',
    priority INTEGER DEFAULT 5,
    
    -- Draft Content for Review
    draft_subject VARCHAR(255),
    draft_body TEXT,
    
    -- Status
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN (
        'pending',
        'approved',
        'rejected',
        'expired'
    )),
    
    -- Reviewer Info
    assigned_to VARCHAR(255),
    reviewed_by VARCHAR(255),
    reviewed_at TIMESTAMP,
    review_notes TEXT,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    
    -- n8n Callback
    callback_webhook_url TEXT,
    callback_execution_id VARCHAR(255)
);

-- -----------------------------------------------------------------------------
-- Error Log - Detailed error tracking for reliability
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS error_log (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL,
    
    -- Error Details
    error_type VARCHAR(100) NOT NULL,
    error_code VARCHAR(50),
    error_message TEXT NOT NULL,
    stack_trace TEXT,
    
    -- Context
    workflow_name VARCHAR(255),
    node_name VARCHAR(255),
    execution_id VARCHAR(255),
    
    -- Request/Response Data (sanitized)
    request_data JSONB,
    response_data JSONB,
    
    -- Recovery
    is_retryable BOOLEAN DEFAULT TRUE,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP,
    resolution_notes TEXT,
    
    -- Notification
    notification_sent BOOLEAN DEFAULT FALSE,
    notification_sent_at TIMESTAMP,
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -----------------------------------------------------------------------------
-- Indexes for Performance
-- -----------------------------------------------------------------------------
CREATE INDEX idx_leads_status ON leads(status);
CREATE INDEX idx_leads_classification ON leads(classification);
CREATE INDEX idx_leads_created_at ON leads(created_at DESC);
CREATE INDEX idx_leads_email ON leads(email);

CREATE INDEX idx_processing_log_lead_id ON processing_log(lead_id);
CREATE INDEX idx_processing_log_created_at ON processing_log(created_at DESC);
CREATE INDEX idx_processing_log_action ON processing_log(action);

CREATE INDEX idx_approval_queue_status ON approval_queue(status);
CREATE INDEX idx_approval_queue_lead_id ON approval_queue(lead_id);
CREATE INDEX idx_approval_queue_priority ON approval_queue(priority DESC);

CREATE INDEX idx_error_log_lead_id ON error_log(lead_id);
CREATE INDEX idx_error_log_resolved ON error_log(resolved);
CREATE INDEX idx_error_log_created_at ON error_log(created_at DESC);

-- -----------------------------------------------------------------------------
-- Trigger for updated_at
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- -----------------------------------------------------------------------------
-- Views for Reporting
-- -----------------------------------------------------------------------------
CREATE VIEW lead_summary AS
SELECT 
    classification,
    COUNT(*) as total_leads,
    COUNT(*) FILTER (WHERE status = 'sent') as sent_count,
    COUNT(*) FILTER (WHERE status = 'approved') as approved_count,
    COUNT(*) FILTER (WHERE status = 'rejected') as rejected_count,
    COUNT(*) FILTER (WHERE status = 'error') as error_count,
    AVG(confidence_score) as avg_confidence
FROM leads
GROUP BY classification;

CREATE VIEW pending_approvals AS
SELECT 
    aq.id as approval_id,
    l.id as lead_id,
    l.name,
    l.email,
    l.company,
    l.classification,
    l.intent,
    l.summary,
    aq.draft_subject,
    aq.draft_body,
    aq.priority,
    aq.created_at,
    aq.expires_at
FROM approval_queue aq
JOIN leads l ON aq.lead_id = l.id
WHERE aq.status = 'pending'
ORDER BY aq.priority DESC, aq.created_at ASC;

CREATE VIEW recent_errors AS
SELECT 
    el.*,
    l.name as lead_name,
    l.email as lead_email
FROM error_log el
LEFT JOIN leads l ON el.lead_id = l.id
WHERE el.created_at > NOW() - INTERVAL '24 hours'
ORDER BY el.created_at DESC;

-- -----------------------------------------------------------------------------
-- Sample Data for Testing (commented out - use eval/sample_leads.json instead)
-- -----------------------------------------------------------------------------
-- INSERT INTO leads (name, email, company, message) VALUES
-- ('Test User', 'test@example.com', 'Test Corp', 'This is a test message');

COMMENT ON TABLE leads IS 'Core leads table storing inbound lead information and AI classification results';
COMMENT ON TABLE processing_log IS 'Audit log tracking all workflow operations for debugging and compliance';
COMMENT ON TABLE approval_queue IS 'Queue for leads awaiting human approval before sending replies';
COMMENT ON TABLE error_log IS 'Detailed error tracking for monitoring and retry logic';
