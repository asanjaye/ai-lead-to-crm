"""
Lead Classifier - LLM-powered classification and reply generation.

Supports OpenAI and Anthropic providers with structured output for reliable parsing.
"""

import os
import json
from typing import Literal

from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

OPENAI_AVAILABLE = True
ANTHROPIC_AVAILABLE = True

try:
    from openai import AsyncOpenAI, RateLimitError as OpenAIRateLimitError, APIConnectionError as OpenAIAPIConnectionError
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAIRateLimitError = Exception
    OpenAIAPIConnectionError = Exception

try:
    from anthropic import AsyncAnthropic, RateLimitError as AnthropicRateLimitError, APIConnectionError as AnthropicAPIConnectionError
except ImportError:
    ANTHROPIC_AVAILABLE = False
    AnthropicRateLimitError = Exception
    AnthropicAPIConnectionError = Exception


class ClassificationResult(BaseModel):
    """Structured output for lead classification."""
    classification: Literal["hot", "warm", "cold", "spam"] = Field(
        ..., 
        description="Lead quality classification"
    )
    intent: str = Field(
        ..., 
        max_length=100,
        description="Primary intent of the inquiry (e.g., 'pricing inquiry', 'technical question', 'partnership request')"
    )
    summary: str = Field(
        ..., 
        max_length=500,
        description="Brief summary of the lead's needs and context"
    )
    confidence_score: float = Field(
        ..., 
        ge=0.0, 
        le=1.0,
        description="Confidence in the classification (0.0-1.0)"
    )
    reasoning: str = Field(
        ...,
        description="Brief explanation of why this classification was chosen"
    )


class DraftReply(BaseModel):
    """Structured output for draft reply."""
    subject: str = Field(..., max_length=255, description="Email subject line")
    body: str = Field(..., description="Email body content")
    tone: str = Field(..., description="Tone used (professional, friendly, etc.)")
    personalization_notes: str = Field(
        ..., 
        description="Notes on how the reply was personalized"
    )


CLASSIFICATION_SYSTEM_PROMPT = """You are an expert lead qualification assistant for a business. Your job is to analyze inbound leads and classify them accurately.

Classification criteria:
- HOT: High purchase intent, urgent need, decision maker, good fit, ready to buy/engage
- WARM: Genuine interest, exploring options, may need nurturing, potential fit
- COLD: Low intent, early research stage, unclear fit, requires significant nurturing
- SPAM: Irrelevant, bot-generated, sales pitches, job seekers, clearly not a potential customer

Consider these factors:
1. Specificity of inquiry (vague vs. detailed questions)
2. Mention of timeline, budget, or decision-making authority
3. Company size and relevance (if mentioned)
4. Tone and professionalism
5. Whether they're asking about specific products/services vs. generic inquiries

Respond with a JSON object matching the required schema. Be accurate and consistent."""

REPLY_SYSTEM_PROMPT = """You are a professional business development representative drafting personalized email replies to leads.

Guidelines:
1. Match the tone to the lead classification (more enthusiastic for hot leads, more educational for cold)
2. Address their specific questions or needs mentioned in their message
3. Include a clear call-to-action appropriate to their stage
4. Keep replies concise but warm (150-300 words typically)
5. Personalize based on their company and stated needs
6. Never be pushy or salesy - focus on being helpful
7. For spam leads, generate a polite decline or generic response

The reply will be reviewed by a human before sending, so make it ready to send but flag anything that needs customization.

Respond with a JSON object matching the required schema."""


class LeadClassifier:
    """Lead classification service supporting multiple LLM providers."""
    
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()
        
        if self.provider == "openai":
            if not OPENAI_AVAILABLE:
                raise RuntimeError("OpenAI package not installed")
            self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        elif self.provider == "anthropic":
            if not ANTHROPIC_AVAILABLE:
                raise RuntimeError("Anthropic package not installed")
            self.client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((OpenAIRateLimitError, OpenAIAPIConnectionError, AnthropicRateLimitError, AnthropicAPIConnectionError))
    )
    async def classify(
        self,
        name: str,
        email: str,
        company: str | None,
        message: str
    ) -> ClassificationResult:
        """Classify a lead using the configured LLM provider."""
        
        user_prompt = f"""Analyze this inbound lead and provide a classification:

Name: {name}
Email: {email}
Company: {company or 'Not provided'}

Message:
{message}

Respond with a JSON object containing:
- classification: "hot", "warm", "cold", or "spam"
- intent: Primary intent (max 100 chars)
- summary: Brief summary of needs (max 500 chars)
- confidence_score: 0.0-1.0
- reasoning: Why this classification"""

        if self.provider == "openai":
            return await self._classify_openai(user_prompt)
        else:
            return await self._classify_anthropic(user_prompt)
    
    async def _classify_openai(self, user_prompt: str) -> ClassificationResult:
        """Classify using OpenAI with structured output."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=500
        )
        
        result = json.loads(response.choices[0].message.content)
        return ClassificationResult(**result)
    
    async def _classify_anthropic(self, user_prompt: str) -> ClassificationResult:
        """Classify using Anthropic with structured output."""
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=500,
            system=CLASSIFICATION_SYSTEM_PROMPT + "\n\nRespond ONLY with a valid JSON object, no other text.",
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        content = response.content[0].text
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        
        result = json.loads(content.strip())
        return ClassificationResult(**result)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((OpenAIRateLimitError, OpenAIAPIConnectionError, AnthropicRateLimitError, AnthropicAPIConnectionError))
    )
    async def generate_draft_reply(
        self,
        name: str,
        email: str,
        company: str | None,
        message: str,
        classification: ClassificationResult
    ) -> DraftReply:
        """Generate a draft reply for human approval."""
        
        user_prompt = f"""Draft a personalized email reply to this lead:

Lead Information:
- Name: {name}
- Email: {email}
- Company: {company or 'Not provided'}
- Classification: {classification.classification}
- Intent: {classification.intent}
- Summary: {classification.summary}

Original Message:
{message}

Generate a professional reply that:
1. Addresses their specific needs
2. Matches the appropriate tone for a {classification.classification} lead
3. Includes a relevant call-to-action
4. Is ready for human review before sending

Respond with a JSON object containing:
- subject: Email subject line
- body: Full email body
- tone: Description of tone used
- personalization_notes: How the reply was personalized"""

        if self.provider == "openai":
            return await self._generate_reply_openai(user_prompt)
        else:
            return await self._generate_reply_anthropic(user_prompt)
    
    async def _generate_reply_openai(self, user_prompt: str) -> DraftReply:
        """Generate reply using OpenAI."""
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": REPLY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=1000
        )
        
        result = json.loads(response.choices[0].message.content)
        return DraftReply(**result)
    
    async def _generate_reply_anthropic(self, user_prompt: str) -> DraftReply:
        """Generate reply using Anthropic."""
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            system=REPLY_SYSTEM_PROMPT + "\n\nRespond ONLY with a valid JSON object, no other text.",
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        content = response.content[0].text
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        
        result = json.loads(content.strip())
        return DraftReply(**result)
