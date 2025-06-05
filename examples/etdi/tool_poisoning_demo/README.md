# ETDI Tool Poisoning Prevention Demos

This directory contains comprehensive demonstrations of how ETDI (Enhanced Tool Definition Interface) prevents tool poisoning attacks in MCP (Model Context Protocol) environments. The demos feature **detailed logging and explanatory messages** that show exactly what's happening at each step of the attack and prevention process.

## 🚀 Complete Setup Guide - Step by Step

### Prerequisites ✅

Before starting, ensure you have:

1. **Python 3.11+** installed with pip and venv
2. **Auth0 Account** (free tier sufficient) - we'll set this up

### Step 1: Repository and Environment Setup

```bash
# 1. Clone the repository (if not already done)
git clone <your-repository-url>
cd python-sdk-etdi

# 2. Create and activate virtual environment
python -m venv .venv

# On macOS/Linux:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate

# 3. Install the ETDI package in development mode
pip install -e .

# 4. Navigate to the tool poisoning demo
cd examples/etdi/tool_poisoning_demo

# 5. Install demo-specific dependencies
pip install -r requirements.txt
```

### Step 2: Auth0 Setup (Required for Full Functionality)

#### 2.1 Create Auth0 Account

1. Go to [auth0.com](https://auth0.com) and sign up for a free account
2. Create a new tenant (choose any name, e.g., "etdi-demo")
3. Complete the setup wizard

#### 2.2 Create Application

1. In Auth0 Dashboard, go to **Applications** → **Create Application**
2. Choose **Machine to Machine Applications**
3. Name it "ETDI Tool Provider Demo"
4. Select your default API or create a new one:
   - **Name**: "ETDI Tool Registry API"
   - **Identifier**: `https://api.etdi-tools.demo.com`
5. Authorize the application for your API

#### 2.3 Get Your Credentials

1. In your application settings, note:
   - **Domain** (e.g., `your-tenant.auth0.com`)
   - **Client ID** (32-character string)
   - **Client Secret** (for machine-to-machine auth)

#### 2.4 Configure Environment Variables

```bash
# Copy the example environment file
cp ../.env.example ../.env

# Edit the .env file with your actual credentials
nano ../.env
# OR use your preferred editor: code ../.env, vim ../.env, etc.
```

Update your `.env` file with your Auth0 credentials:
```env
# Auth0 Configuration - Replace with your actual values
ETDI_AUTH0_DOMAIN=your-tenant.auth0.com
ETDI_CLIENT_ID=your-client-id-here

# Demo Configuration
ETDI_DEMO_MODE=true
ETDI_VERBOSE=true
```

### To run the demo

```
python3.11 run_real_server_demo.py 
```