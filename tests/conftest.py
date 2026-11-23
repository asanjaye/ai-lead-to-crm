"""
Pytest configuration and fixtures.
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "services" / "lead-classifier"))


@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def sample_hot_lead():
    """Sample hot lead for testing."""
    return {
        "name": "Test Decision Maker",
        "email": "decision@enterprise.com",
        "company": "Enterprise Corp",
        "message": "URGENT: We need this solution immediately. Budget approved for $50k. When can we start?",
        "expected_classification": "hot"
    }


@pytest.fixture
def sample_warm_lead():
    """Sample warm lead for testing."""
    return {
        "name": "Research Manager",
        "email": "research@midsize.co",
        "company": "Midsize Company",
        "message": "We're evaluating solutions for next quarter. Could you send pricing and case studies?",
        "expected_classification": "warm"
    }


@pytest.fixture
def sample_cold_lead():
    """Sample cold lead for testing."""
    return {
        "name": "Curious Browser",
        "email": "curious@gmail.com",
        "company": None,
        "message": "Just wondering how this works. I'm a student doing research.",
        "expected_classification": "cold"
    }


@pytest.fixture
def sample_spam_lead():
    """Sample spam lead for testing."""
    return {
        "name": "Spam Bot",
        "email": "spam@fake-domain.xyz",
        "company": None,
        "message": "MAKE MONEY FAST!!! Click here for free crypto!!! Limited time offer!!!",
        "expected_classification": "spam"
    }
