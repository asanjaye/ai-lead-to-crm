# Demo Recording Script

**Duration:** 2-3 minutes  
**Audience:** Engineers and operators evaluating AI lead automation  
**Goal:** Show the complete lead-to-approval flow with a hot lead example

---

## Pre-Recording Checklist

- [ ] All services running (`docker-compose up -d`)
- [ ] n8n workflow imported and activated
- [ ] Approval UI open at http://localhost:3001 (empty queue)
- [ ] Terminal ready for curl command
- [ ] Clean browser tabs (n8n, Approval UI)

---

## Recording Script

### Opening (15 seconds)

**[Screen: README with architecture diagram]**

> "Hi, I'm Ashwin. This is a production-ready AI lead qualification workflow I built with n8n. It automatically classifies incoming leads, drafts personalized responses, and routes them for human approval before anything sends. Let me show you how it works."

---

### Part 1: Show the Workflow (30 seconds)

**[Screen: n8n workflow editor]**

> "Here's the n8n workflow. When a lead comes in through the webhook, it's validated and stored in the database. Then it goes to our AI classifier — I'm using GPT-4o-mini but this works with Claude too."

**[Hover over the classification node]**

> "The AI classifies the lead as hot, warm, cold, or spam, extracts their intent, writes a summary, and drafts a personalized reply. Notice the error branch here — if anything fails, it logs the error and sends a Slack notification."

**[Hover over the approval queue node]**

> "Non-spam leads go to this approval queue. The key thing is: nothing sends without human approval."

---

### Part 2: Submit a Test Lead (30 seconds)

**[Screen: Terminal + Approval UI side by side]**

> "Let me submit a test lead. This is a typical hot lead — urgent language, budget mentioned, decision maker."

**[Run the curl command]**

```bash
curl -X POST http://localhost:5678/webhook/lead-intake \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Sarah Chen",
    "email": "sarah@techstartup.io",
    "company": "TechStartup Inc",
    "message": "We need lead automation ASAP. Budget approved for Q1, can we schedule a call this week?"
  }'
```

**[Show the JSON response]**

> "It returns immediately with the lead ID and classification. Let's check the approval queue."

---

### Part 3: Human Approval Interface (45 seconds)

**[Screen: Approval UI dashboard]**

> "Here's our approval dashboard. We can see the lead classified as 'hot' with high confidence. The AI identified the intent as a purchase inquiry."

**[Click into the lead detail]**

> "Let's review the draft. The AI wrote a personalized response addressing their urgency and offering a call. Notice how it picked up on 'this week' from their message."

**[Show the editable fields]**

> "I can edit this before approving. Maybe I want to add specific availability..."

**[Make a small edit]**

> "Now I'll approve it. In production, this would queue the email for sending through SendGrid or your email provider."

**[Click Approve]**

> "Done. The lead is now marked as approved, and we have a full audit trail."

---

### Part 4: Error Handling & Reliability (20 seconds)

**[Screen: n8n workflow, zoom on error branch]**

> "One thing clients always ask about is reliability. If the AI service is down, the workflow retries 3 times with exponential backoff. If it still fails, it logs the error, marks the lead for manual review, and sends a Slack alert. The lead is never lost."

---

### Part 5: Evaluation Harness (20 seconds)

**[Screen: Terminal running eval dry-run]**

> "There are 25 labeled synthetic leads in the repo — seven hot, seven warm, seven cold, and four spam. The eval script can dry-run against that set, or call a live classifier when an API key is configured. Unit tests also cover the data shape and workflow JSON."

**[Show the dry-run distribution briefly]**

---

### Closing (15 seconds)

**[Screen: README]**

> "Everything here is ready to run locally: Docker Compose, PostgreSQL for the CRM store, and notes on connecting to HubSpot, Salesforce, or Google Sheets. Full source is on GitHub at github.com/asanjaye/ai-lead-to-crm."

**[End screen: ashwinsanjaye.com · github.com/asanjaye · sanjaye@usc.edu]**

---

## Alternative Scenarios to Demo

If you want to show more variety:

### Spam Detection
```bash
curl -X POST http://localhost:5678/webhook/lead-intake \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Super Deals",
    "email": "deals@cheap-meds.xyz",
    "message": "AMAZING OPPORTUNITY!!! Make $5000 per day! Click here!!!"
  }'
```
> "Watch how it filters this obvious spam — it goes straight to the log, no approval needed."

### Cold Lead
```bash
curl -X POST http://localhost:5678/webhook/lead-intake \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Student Researcher",
    "email": "student@university.edu",
    "message": "Hi, I am a student researching AI applications. Can you tell me how your system works?"
  }'
```
> "This gets classified as cold — still creates an approval but with a more educational response."

### Validation Error
```bash
curl -X POST http://localhost:5678/webhook/lead-intake \
  -H "Content-Type: application/json" \
  -d '{
    "name": "",
    "email": "not-an-email",
    "message": "hi"
  }'
```
> "Invalid inputs are caught early and return a helpful error."

---

## Post-Recording

1. Trim dead air and mistakes
2. Add subtle background music (optional)
3. Add end card with contact links (ashwinsanjaye.com · github.com/asanjaye · sanjaye@usc.edu)
4. Export at 1080p
5. Upload to YouTube (unlisted) and link from the README if desired

---

## Technical Notes for Recording

- **Screen resolution:** 1920x1080 recommended
- **Font size:** Increase terminal and browser zoom to 125%
- **Notifications:** Turn off system notifications
- **Microphone:** Test audio levels before starting
- **Pacing:** Pause between sections, can be tightened in editing
