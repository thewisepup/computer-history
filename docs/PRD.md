# Product Requirements Document

_Open Computer History — last updated 2026-11-16._

## Introduction

Open Computer History is an AI productivity app, designed to help you save time.
It understands where most of your working time is spent to propose automations
that remove bottlenecks so you can spend more time on higher leverage tasks.

## Target user

- **MVP:** myself, a technical solo founder, plus early adopters who are also
  technical engineers.
- Non-technical entrepreneurs looking to remove bottlenecks from their business.

## Struggles

- Not knowing where most of your time is spent.
- Not having the technical knowledge or capacity to automate tasks with AI.
- Wanting computer history accessible across devices.

## User stories

### Setup and capture

- As a user, this app starts when I log into my computer so my history is always
  being recorded.
- As a user, it captures a history of what I do on my computer.

### Projects

- As a user, AI classifies and proposes projects from my activity and labels each
  block with a project, one work type, and optional tags.
- As a user, I can confirm, rename, merge and add projects, and correct
  mislabelled blocks, from my AI assistant or the UI. My corrections shouldn't be
  overwritten.

### Insights

- As a user, I can see my time by project, work type, app or URL over any date
  range.
- As a user, I can see a daily timeline of my work blocks.
- As a user, I can ask my AI assistant questions about my projects and past work.

### Bottlenecks and suggestions

- As a user, I get a weekly review of time by project and work type and my top
  bottlenecks with evidence. It's generated automatically when the week ends, and
  on demand whenever I want.
- As a user, each review gives 1 to 3 automation suggestions, each with evidence,
  a workflow, and a ready-to-run prompt or Claude Code command.

### Where I use it

- As a user, my computer history is available to any AI assistant with MCP
  support (Claude or ChatGPT).
- As a user, I have a local web UI where I can view and edit computer history and
  view my timeline, bottlenecks, automation suggestions, etc. outside of an AI
  assistant.

## Functional requirements

- **Capture:** ActivityWatch for window, AFK and Chrome data, and your own
  capture agent for Accessibility text and screenshots, with text recognition on
  the Mac.
- **Ingest:** source adapters normalize everything into local SQLite.
- **Classify:** on a schedule, through OpenRouter with one hard-coded model,
  sending text only.
- **MCP:** read tools plus write tools for corrections and project management.
- **UI:** React, built and served by FastAPI.

## Non-functional requirements

- **Platform:** macOS only.
- **Network:** localhost only, with no remote access.
- **Data:** stored locally. Only text goes to the cloud LLM, and screenshots
  never leave the Mac.
- **Reliability:** starts at login, and catches up after sleep or other
  interruptions.
- **Integrity:** raw observations are never modified. Only normalized data
  changes, and corrected blocks are locked.
- **Speed:** MCP and UI answers within about 2 seconds, served from local SQLite.
- **Freshness:** activity is classified within about an hour.
- **Portability:** standard MCP, tested in both Claude and ChatGPT.
- **Retention:** everything is kept indefinitely, and disk usage is visible.
- **Extensibility:** new capture sources plug in without schema changes.

## Later requirements (not part of this version)

- Accessibility text capture
- Screenshot capture
- Deny-list / sensitive information redaction
- Manual corrections
- Manual corrections becomes context for future suggestions
- Suggestion status
- Data retention
- Personal vs actual work
- Prompt injection
- 1-step install
- Local models to process data
- Cloud sync
- Model choice picker
- Auth
- Native iOS app
- Audio capture
- Product analytics
- MCP apps
