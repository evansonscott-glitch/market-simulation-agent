# Slack Bot Setup Guide

This guide walks you through creating the Slack app and deploying the Market Simulator bot. Total time: ~10 minutes.

---

## Step 1: Create the Slack App (5 minutes)

You'll need **Slack workspace admin access** for this step.

### 1.1. Create the App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"**
3. Choose **"From scratch"**
4. App Name: `Market Simulator` (or whatever you prefer)
5. Pick your workspace
6. Click **"Create App"**

### 1.2. Enable Socket Mode

Socket Mode lets the bot connect without needing a public URL — much simpler for deployment.

1. In the left sidebar, click **"Socket Mode"**
2. Toggle **"Enable Socket Mode"** to ON
3. It will ask you to create an App-Level Token:
   - Token Name: `socket-token`
   - Scope: `connections:write`
   - Click **"Generate"**
4. **Copy the token** (starts with `xapp-`) — you'll need this later

### 1.3. Set Bot Permissions (OAuth Scopes)

1. In the left sidebar, click **"OAuth & Permissions"**
2. Scroll down to **"Scopes" → "Bot Token Scopes"**
3. Add these scopes:

| Scope | Why |
| :--- | :--- |
| `app_mentions:read` | So the bot can respond when @mentioned |
| `chat:write` | So the bot can send messages |
| `commands` | For slash commands (`/simulate`, `/sim-status`, `/sim-cancel`) |
| `files:write` | To upload report files |
| `im:history` | To read DMs sent to the bot |
| `im:read` | To access DM channels |
| `im:write` | To send DMs |

### 1.4. Enable Events

1. In the left sidebar, click **"Event Subscriptions"**
2. Toggle **"Enable Events"** to ON
3. Under **"Subscribe to bot events"**, add:
   - `app_mention`
   - `message.im`
4. Click **"Save Changes"**

### 1.5. Create Slash Commands

1. In the left sidebar, click **"Slash Commands"**
2. Create these three commands:

| Command | Description | Usage Hint |
| :--- | :--- | :--- |
| `/simulate` | Start a new market simulation | `[optional: brief description of what to simulate]` |
| `/sim-status` | Check the status of your running simulation | |
| `/sim-cancel` | Cancel your current simulation | |

### 1.6. Allow DMs

1. In the left sidebar, click **"App Home"**
2. Under **"Show Tabs"**, make sure **"Messages Tab"** is checked
3. Check **"Allow users to send Slash commands and messages from the messages tab"**

### 1.7. Install the App

1. In the left sidebar, click **"Install App"** (or **"OAuth & Permissions"**)
2. Click **"Install to Workspace"**
3. Review the permissions and click **"Allow"**
4. **Copy the "Bot User OAuth Token"** (starts with `xoxb-`) — you'll need this

---

## Step 2: Collect Your Tokens

You should now have three values:

| Token | Starts with | Where to find it |
| :--- | :--- | :--- |
| **Bot Token** | `xoxb-` | OAuth & Permissions → Bot User OAuth Token |
| **App Token** | `xapp-` | Basic Information → App-Level Tokens |
| **OpenAI API Key** | `sk-` | Your OpenAI account |

---

## Step 3: Deploy the Bot

### Option A: Docker (Recommended)

1. Clone the repo on your server:
   ```bash
   git clone https://github.com/YOUR_USERNAME/market-simulation-agent.git
   cd market-simulation-agent
   ```

2. Create the `.env` file:
   ```bash
   cp .env.example .env
   ```

3. Edit `.env` and paste in your three tokens:
   ```
   SLACK_BOT_TOKEN=xoxb-your-token
   SLACK_APP_TOKEN=xapp-your-token
   OPENAI_API_KEY=sk-your-key
   ```

4. Start the bot:
   ```bash
   docker compose up -d
   ```

5. Check it's running:
   ```bash
   docker compose logs -f
   ```

   You should see: `Starting Market Simulator Slack Bot...`

### Option B: Direct Python (No Docker)

1. Clone the repo:
   ```bash
   git clone https://github.com/YOUR_USERNAME/market-simulation-agent.git
   cd market-simulation-agent
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set environment variables:
   ```bash
   export SLACK_BOT_TOKEN=xoxb-your-token
   export SLACK_APP_TOKEN=xapp-your-token
   export OPENAI_API_KEY=sk-your-key
   ```

4. Run the bot:
   ```bash
   python slack_bot/app.py
   ```

### Option C: Railway (Easiest Cloud Hosting)

1. Push the repo to GitHub
2. Go to [railway.app](https://railway.app) and create a new project
3. Connect your GitHub repo
4. Add the three environment variables in Railway's dashboard
5. Deploy — Railway will auto-detect the Dockerfile

---

## Step 4: Test It

1. Open Slack
2. Find the **Market Simulator** bot in your DMs (or invite it to a channel)
3. Send it a message: `Hey, I want to test an assumption about a product`
4. The bot should respond and start asking you questions
5. Or use: `/simulate I want to test whether affiliate managers would prefer a Slack agent`

---

## How It Works

### Starting a Simulation

You can start a simulation three ways:
- **DM the bot** with a description of what you want to test
- **@mention the bot** in a channel
- **Use `/simulate`** with an optional description

### The Conversation Flow

1. The bot asks you about the product, target market, and assumptions
2. It helps you articulate testable hypotheses and suggests persona archetypes
3. When it has enough info, it presents a config summary for your approval
4. You say "yes" and it runs the simulation (5-15 minutes)
5. Results are posted back to the thread with the full report and transcripts

### Commands

| Command | What it does |
| :--- | :--- |
| `/simulate` | Start a new simulation |
| `/sim-status` | Check if a simulation is running |
| `/sim-cancel` | Cancel a running simulation |

---

## Troubleshooting

**Bot doesn't respond to DMs:**
- Make sure "Messages Tab" is enabled in App Home settings
- Make sure `message.im` event is subscribed

**Bot doesn't respond to @mentions:**
- Make sure `app_mention` event is subscribed
- Make sure the bot is invited to the channel

**"not_authed" or "invalid_auth" errors:**
- Double-check your `SLACK_BOT_TOKEN` starts with `xoxb-`
- Double-check your `SLACK_APP_TOKEN` starts with `xapp-`
- Make sure the app is installed to the workspace

**Simulation fails:**
- Check the logs: `docker compose logs -f`
- Make sure your `OPENAI_API_KEY` is valid and has credits
