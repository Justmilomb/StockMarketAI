# Running AutoConfig on a Cloud VM

## Provider Options (ranked by cost)

| Rank | Provider | Instance | vCPU | RAM | ~Cost/hr | Notes |
|------|----------|----------|------|-----|----------|-------|
| 1 | **Google Cloud** | c2d-standard-32 | 32 | 128 GB | **FREE** | $300 credit for new accounts (90 days) |
| 2 | **Vultr** | Optimized 32 vCPU | 32 | 128 GB | ~$0.57 | Easy signup, reliable, hourly billing |
| 3 | **Linode/Akamai** | Dedicated 32 vCPU | 32 | 64 GB | ~$0.58 | Easy signup, reliable, hourly billing |
| 4 | **DigitalOcean** | CPU-Optimized 32 | 32 | 64 GB | ~$0.95 | Easiest signup of all |
| 5 | **AWS EC2** | c7a.8xlarge | 32 | 64 GB | ~$1.00 | Spot instances ~$0.35/hr (can be interrupted) |

**Best pick:** Google Cloud if you've never used it — $300 free credit = ~300 hours of 32 vCPU for nothing.
**Best pick (no free tier):** Vultr — simple, cheap, hourly billed, delete when done.

---

## Setup Instructions

### 1. Create the server

Pick a provider above. Create a server with:
- **OS:** Ubuntu 24.04
- **Size:** 32+ vCPU dedicated (CPU-optimized)
- **Region:** closest to you
- **Auth:** SSH key or password

Note the server's IP address.

### 2. SSH into the server

```bash
ssh root@<YOUR-SERVER-IP>
```

### 3. Install everything (paste this entire block)

```bash
# System dependencies
apt update && apt install -y python3-pip python3-venv git nodejs npm tmux

# Install Claude Code CLI
npm install -g @anthropic-ai/claude-code

# Authenticate Claude CLI (gives you a URL — open it in your local browser)
claude login

# Clone your repo
git clone <YOUR-REPO-URL> ~/StockMarketAI
cd ~/StockMarketAI

# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Copy local files to the server

Run these **from your Windows machine** (new terminal).

If you have `scp` (Git Bash / WSL):
```bash
scp config.json root@<IP>:~/StockMarketAI/
scp data/terminal_history.db root@<IP>:~/StockMarketAI/data/
scp models/ensemble/*.joblib root@<IP>:~/StockMarketAI/models/ensemble/

# If you have prior autoconfig results:
scp autoconfig/results.tsv root@<IP>:~/StockMarketAI/autoconfig/
scp autoconfig/best_config.json root@<IP>:~/StockMarketAI/autoconfig/
```

If you don't have `scp`, use WinSCP (https://winscp.net/) — drag and drop.

### 5. Run autoconfig (inside tmux so it survives SSH disconnect)

```bash
cd ~/StockMarketAI
source .venv/bin/activate

# Start a tmux session (keeps running even if SSH drops)
tmux new -s autoconfig

# Launch autoconfig
python autoconfig/run.py --batch-size 10
```

**Detach from tmux:** press `Ctrl+B` then `D` (it keeps running in the background).

**Reconnect later:**
```bash
ssh root@<IP>
tmux attach -t autoconfig
```

**Stop autoconfig:** press `Ctrl+C` inside the tmux session. Progress is saved automatically.

### 6. Pull results back to your local machine

From your Windows machine:
```bash
scp root@<IP>:~/StockMarketAI/autoconfig/results.tsv autoconfig/
scp root@<IP>:~/StockMarketAI/autoconfig/best_config.json autoconfig/
```

### 7. DESTROY THE SERVER

Go to your cloud provider's dashboard and **delete the server**. Billing stops immediately.

**Do not leave it running overnight by accident** — even at $0.57/hr that's $13.70/day.

---

## Environment Variables

| Variable | Needed? | Notes |
|----------|---------|-------|
| Claude CLI auth | **Yes** | `claude login` on the server (step 3) |
| `GEMINI_API_KEY` | No | Not used — pipeline uses Claude CLI |
| `T212_API_KEY` | No | Autoconfig only runs backtests, no live trading |

The only auth needed is `claude login` — it uses your existing Claude subscription.

---

## Cost Estimates

| Scenario | Provider | Duration | Cost |
|----------|----------|----------|------|
| Overnight run (10 hrs) | Google Cloud (free tier) | 10 hrs | **$0** |
| Overnight run (10 hrs) | Vultr 32 vCPU | 10 hrs | ~$5.70 |
| Weekend run (48 hrs) | Google Cloud (free tier) | 48 hrs | **$0** |
| Weekend run (48 hrs) | Vultr 32 vCPU | 48 hrs | ~$27 |

---

## Quick Reference

```
SSH in:              ssh root@<IP>
Reconnect tmux:      tmux attach -t autoconfig
Check progress:      cat autoconfig/results.tsv | wc -l
View best config:    cat autoconfig/best_config.json
Stop autoconfig:     Ctrl+C (inside tmux)
Detach tmux:         Ctrl+B then D
```
