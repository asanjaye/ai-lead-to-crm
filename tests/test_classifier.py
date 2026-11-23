"""
Tests for the Lead Classifier Service

Run with: pytest tests/ -v
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import sys
sys.path.insert(0, 'services/lead-classifier')

from classifier import LeadClassifier, ClassificationResult, DraftReply


class TestClassificationResult:
    """Test ClassificationResult model validation."""
    
    def test_valid_hot_classification(self):
        result = ClassificationResult(
            classification="hot",
            intent="purchase inquiry",
            summary="Customer wants to buy immediately",
            confidence_score=0.95,
            reasoning="High urgency, mentions budget"
        )
        assert result.classification == "hot"
        assert result.confidence_score == 0.95
    
    def test_valid_warm_classification(self):
        result = ClassificationResult(
            classification="warm",
            intent="product research",
            summary="Exploring options",
            confidence_score=0.75,
            reasoning="Interested but not urgent"
        )
        assert result.classification == "warm"
    
    def test_valid_cold_classification(self):
        result = ClassificationResult(
            classification="cold",
            intent="general inquiry",
            summary="Just browsing",
            confidence_score=0.60,
            reasoning="No clear purchase intent"
        )
        assert result.classification == "cold"
    
    def test_valid_spam_classification(self):
        result = ClassificationResult(
            classification="spam",
            intent="bot submission",
            summary="Automated spam message",
            confidence_score=0.99,
            reasoning="Generic spam content"
        )
        assert result.classification == "spam"
    
    def test_invalid_classification_raises(self):
        with pytest.raises(ValueError):
            ClassificationResult(
                classification="invalid",
                intent="test",
                summary="test",
                confidence_score=0.5,
                reasoning="test"
            )
    
    def test_confidence_score_bounds(self):
        with pytest.raises(ValueError):
            ClassificationResult(
                classification="hot",
                intent="test",
                summary="test",
                confidence_score=1.5,
                reasoning="test"
            )
        
        with pytest.raises(ValueError):
            ClassificationResult(
                classification="hot",
                intent="test",
                summary="test",
                confidence_score=-0.1,
                reasoning="test"
            )


class TestDraftReply:
    """Test DraftReply model validation."""
    
    def test_valid_draft_reply(self):
        reply = DraftReply(
            subject="Re: Your Inquiry",
            body="Thank you for reaching out...",
            tone="professional",
            personalization_notes="Mentioned their company by name"
        )
        assert reply.subject == "Re: Your Inquiry"
        assert "Thank you" in reply.body
    
    def test_subject_max_length(self):
        with pytest.raises(ValueError):
            DraftReply(
                subject="x" * 300,
                body="test",
                tone="professional",
                personalization_notes="test"
            )


class TestLeadClassifier:
    """Test LeadClassifier with mocked LLM responses."""
    
    @pytest.fixture
    def mock_openai_response(self):
        return {
            "classification": "hot",
            "intent": "purchase inquiry",
            "summary": "Customer ready to buy",
            "confidence_score": 0.9,
            "reasoning": "Urgent language, budget mentioned"
        }
    
    @pytest.fixture
    def mock_reply_response(self):
        return {
            "subject": "Re: Your Inquiry",
            "body": "Thank you for your interest...",
            "tone": "professional",
            "personalization_notes": "Addressed specific needs"
        }
    
    @pytest.mark.asyncio
    async def test_classify_openai(self, mock_openai_response):
        """Test classification with mocked OpenAI response."""
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openai', 'OPENAI_API_KEY': 'test-key'}):
            with patch('classifier.AsyncOpenAI') as mock_client_class:
                mock_client = MagicMock()
                mock_client_class.return_value = mock_client
                
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = json.dumps(mock_openai_response)
                
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
                
                classifier = LeadClassifier()
                
                result = await classifier.classify(
                    name="Test User",
                    email="test@example.com",
                    company="Test Corp",
                    message="I want to buy your product immediately. Budget is $10k."
                )
                
                assert result.classification == "hot"
                assert result.confidence_score == 0.9
    
    @pytest.mark.asyncio
    async def test_generate_draft_reply(self, mock_openai_response, mock_reply_response):
        """Test draft reply generation."""
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openai', 'OPENAI_API_KEY': 'test-key'}):
            with patch('classifier.AsyncOpenAI') as mock_client_class:
                mock_client = MagicMock()
                mock_client_class.return_value = mock_client
                
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = json.dumps(mock_reply_response)
                
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
                
                classifier = LeadClassifier()
                
                classification = ClassificationResult(**mock_openai_response)
                
                reply = await classifier.generate_draft_reply(
                    name="Test User",
                    email="test@example.com",
                    company="Test Corp",
                    message="I want to buy your product.",
                    classification=classification
                )
                
                assert reply.subject == "Re: Your Inquiry"
                assert reply.tone == "professional"


class TestLeadInputValidation:
    """Test input validation logic."""
    
    def test_valid_email_formats(self):
        valid_emails = [
            "test@example.com",
            "user.name@domain.co.uk",
            "user+tag@example.org"
        ]
        for email in valid_emails:
            assert "@" in email and "." in email.split("@")[1]
    
    def test_message_minimum_length(self):
        too_short = "Hi"
        valid_length = "This is a detailed inquiry about your product and services."
        
        assert len(too_short) < 10
        assert len(valid_length) >= 10


class TestSampleLeads:
    """Test sample leads data integrity."""
    
    @pytest.fixture
    def sample_leads(self):
        with open('data/sample_leads.json') as f:
            return json.load(f)
    
    def test_sample_leads_count(self, sample_leads):
        """Verify we have the expected number of sample leads."""
        assert len(sample_leads) >= 20
        assert len(sample_leads) <= 30
    
    def test_sample_leads_structure(self, sample_leads):
        """Verify each lead has required fields."""
        required_fields = ['id', 'name', 'email', 'message', 'expected_classification']
        
        for lead in sample_leads:
            for field in required_fields:
                assert field in lead, f"Lead {lead.get('id')} missing field: {field}"
    
    def test_sample_leads_classifications(self, sample_leads):
        """Verify classifications are valid."""
        valid_classifications = {'hot', 'warm', 'cold', 'spam'}
        
        for lead in sample_leads:
            assert lead['expected_classification'] in valid_classifications
    
    def test_sample_leads_distribution(self, sample_leads):
        """Verify reasonable distribution across classifications."""
        distribution = {}
        for lead in sample_leads:
            cls = lead['expected_classification']
            distribution[cls] = distribution.get(cls, 0) + 1
        
        assert len(distribution) == 4
        
        for cls, count in distribution.items():
            assert count >= 2, f"Too few examples of {cls}"
    
    def test_unique_lead_ids(self, sample_leads):
        """Verify all lead IDs are unique."""
        ids = [lead['id'] for lead in sample_leads]
        assert len(ids) == len(set(ids))
    
    def test_valid_emails(self, sample_leads):
        """Verify all emails have valid format."""
        for lead in sample_leads:
            email = lead['email']
            assert '@' in email
            assert '.' in email.split('@')[1]


class TestWorkflowJson:
    """Test n8n workflow JSON integrity."""
    
    @pytest.fixture
    def workflow(self):
        with open('workflows/ai-lead-to-crm.json') as f:
            return json.load(f)
    
    def test_workflow_has_name(self, workflow):
        """Verify workflow has a name."""
        assert 'name' in workflow
        assert workflow['name'] == "AI Lead-to-CRM Workflow"
    
    def test_workflow_has_nodes(self, workflow):
        """Verify workflow has nodes."""
        assert 'nodes' in workflow
        assert len(workflow['nodes']) > 0
    
    def test_workflow_has_webhook_trigger(self, workflow):
        """Verify workflow has a webhook trigger."""
        node_types = [node['type'] for node in workflow['nodes']]
        assert 'n8n-nodes-base.webhook' in node_types
    
    def test_workflow_has_connections(self, workflow):
        """Verify workflow has connections between nodes."""
        assert 'connections' in workflow
        assert len(workflow['connections']) > 0
    
    def test_all_nodes_have_ids(self, workflow):
        """Verify all nodes have unique IDs."""
        ids = [node['id'] for node in workflow['nodes']]
        assert len(ids) == len(set(ids))
    
    def test_error_handling_nodes_exist(self, workflow):
        """Verify error handling nodes exist."""
        node_names = [node['name'] for node in workflow['nodes']]
        
        assert any('error' in name.lower() for name in node_names)
        assert any('log' in name.lower() for name in node_names)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
