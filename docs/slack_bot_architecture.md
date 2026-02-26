# Philo Ventures Market Simulator — Slack Bot Architecture

## 1. Executive Summary

This document outlines the technical architecture for the **Philo Ventures Market Simulator**, a Slack-native conversational AI agent. The agent will enable Philo Ventures partners and portfolio founders to initiate, scope, and review market simulations directly within Slack. The primary design goal is to create a frictionless, conversational interface that abstracts the complexity of the underlying simulation engine, transforming it from a command-line tool into a thinking partner.

## 2. Core Interaction Model

The entire user journey will occur within a Slack thread, providing a persistent, shareable record of each simulation.

1.  **Initiation**: A user starts a conversation by mentioning the bot in a channel or sending it a direct message (e.g., "@MarketSim, I want to test a new product idea").
2.  **Scoping (Dialogue Phase)**: The agent engages in a multi-turn dialogue to sharpen the user's request into a testable hypothesis. It will ask clarifying questions to define the product, target market, key assumptions, and user-provided context (transcripts, customer lists).
3.  **Plan & Approval**: The agent synthesizes the dialogue into a formal simulation plan (audience size, archetypes, interview questions) and presents it to the user in a structured Slack message with "Approve" and "Modify" buttons.
4.  **Execution (Async Phase)**: Upon approval, the agent sends a confirmation message ("Running your simulation now. This will take 15-30 minutes. I'll notify you when it's complete.") and triggers the backend simulation pipeline.
5.  **Delivery**: Once the simulation is complete, the agent posts the results back into the original thread. This includes a summary of key findings, a link to the full McKinsey-style presentation, and attached files for the detailed report and transcripts.

## 3. System Architecture

The system is composed of two main components: the **Slack Bot Front-End** and the **Simulation Engine Back-End**.

### 3.1. Slack Bot Front-End (Bolt for Python)

We will use the **Slack Bolt for Python** framework, which is designed for building modern, interactive Slack apps.

| Component | Implementation Details |
| :--- | :--- |
| **App Entry Point** | A single `app.py` will initialize the Bolt app and register all listeners. It will use Socket Mode for real-time communication, eliminating the need for a public-facing HTTP endpoint. |
| **Event Listeners** | - `app_mention` / `message.im`: To detect when a user initiates a conversation.\n- `block_actions`: To handle button clicks for "Approve" / "Modify" actions on the simulation plan. |
| **Conversation Management** | - Each simulation will be managed in a dedicated Slack thread (`thread_ts`).\n- Conversation state (current step, user inputs, generated config) will be stored in a simple in-memory dictionary keyed by `thread_ts` for short-term interactions. For more robust state persistence, a lightweight database like SQLite could be added later. |
| **File Handling** | The bot will listen for `file_shared` events within the conversation thread. When a user uploads a file, the bot will download it using the Slack API, save it to a temporary directory, and pass the file path to the backend simulation engine. |
| **Message Formatting** | We will use Block Kit to create rich, interactive messages for presenting the simulation plan, status updates, and final results. |

### 3.2. Simulation Engine Back-End (Python Application)

This is the refactored, reusable Python application we have already built. The Slack bot will invoke it as a separate process.

| Component | Implementation Details |
| :--- | :--- |
| **Invocation** | The Slack bot will trigger the simulation by spawning a new process using Python's `subprocess` module: `subprocess.Popen(['python3', 'run.py', 'path/to/generated_config.yaml'])`. This ensures the long-running simulation does not block the Slack bot's event loop. |
| **Configuration** | The scoping dialogue will programmatically generate the `config.yaml` file required by the simulation engine. This file will be saved to a unique directory for each simulation run. |
| **Output Handling** | The simulation engine will write all its output (report, transcripts, charts) to a dedicated output directory. The path to this directory will be passed back to the Slack bot upon completion. |
| **Status & Completion** | The `run.py` script will be modified to write a `status.json` file at key milestones (e.g., `{"status": "running_interviews"}`). The Slack bot can poll this file to provide progress updates. Upon completion, it will write a `completion.json` file with the path to the output directory. |

## 4. Technical Requirements & Dependencies

- **Slack App Configuration**:
    - A new Slack App will be created in the Philo Ventures workspace.
    - **Scopes**: `app_mentions:read`, `chat:write`, `files:read`, `im:history`, `im:read`, `im:write`.
    - **Socket Mode**: Enabled.
    - **Event Subscriptions**: `app_mention`, `message.im`, `file_shared`, `block_actions`.
- **Python Environment**:
    - `slack-bolt`: For the bot framework.
    - `slack-sdk`: For interacting with the Slack API.
    - `openai`: For LLM calls.
    - `pyyaml`: For config file handling.
- **Deployment**:
    - The bot can be run on any server or cloud instance (e.g., AWS EC2, Google Cloud Run) where the Python environment can be set up. For initial deployment, it can be run from a dedicated machine.

## 5. Next Steps

1.  Create the Slack App in the Philo Ventures workspace and obtain the necessary tokens (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`).
2.  Build the Slack bot front-end (`app.py`) with listeners for initiating conversations and handling file uploads.
3.  Implement the conversational scoping logic to generate the `config.yaml` file.
4.  Integrate the `subprocess` call to trigger the backend simulation engine.
5.  Build the logic for delivering the final report and attachments back to the Slack thread.

---

### References
[1] Slack Technologies, LLC. (2026). *Developing apps with AI features*. Slack API. [https://docs.slack.dev/ai/developing-ai-apps/](https://docs.slack.dev/ai/developing-ai-apps/)
[2] Slack Technologies, LLC. (2026). *slack-samples/bolt-python-assistant-template*. GitHub. [https://github.com/slack-samples/bolt-python-assistant-template](https://github.com/slack-samples/bolt-python-assistant-template)
