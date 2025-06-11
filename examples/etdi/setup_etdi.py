#!/usr/bin/env python3
"""
ETDI Setup Script - Makes ETDI seamless to use
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any


def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < (3, 9):
        print("❌ Python 3.9 or higher is required")
        sys.exit(1)
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detected")


def install_dependencies():
    """Install required dependencies"""
    print("📦 Installing ETDI dependencies...")
    
    try:
        # Install in development mode
        subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."], 
                      check=True, cwd=Path(__file__).parent)
        print("✅ ETDI installed successfully")
        
        # Install additional dependencies
        subprocess.run([sys.executable, "-m", "pip", "install", "click", "httpx"], 
                      check=True)
        print("✅ Additional dependencies installed")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Installation failed: {e}")
        sys.exit(1)


def create_config_directory():
    """Create ETDI configuration directory"""
    config_dir = Path.home() / ".etdi"
    config_dir.mkdir(exist_ok=True)
    
    # Create subdirectories
    (config_dir / "config").mkdir(exist_ok=True)
    (config_dir / "approvals").mkdir(exist_ok=True)
    (config_dir / "logs").mkdir(exist_ok=True)
    
    print(f"✅ Configuration directory created: {config_dir}")
    return config_dir


def create_default_config(config_dir: Path):
    """Create default ETDI configuration"""
    config_file = config_dir / "config" / "etdi-config.json"
    
    if config_file.exists():
        print(f"⚠️ Configuration already exists: {config_file}")
        return config_file
    
    default_config = {
        "security_level": "enhanced",
        "oauth_config": {
            "provider": "auth0",
            "client_id": "YOUR_CLIENT_ID",
            "client_secret": "YOUR_CLIENT_SECRET",
            "domain": "your-domain.auth0.com",
            "audience": "https://your-api.example.com",
            "scopes": ["read:tools", "execute:tools"]
        },
        "allow_non_etdi_tools": True,
        "show_unverified_tools": False,
        "verification_cache_ttl": 300,
        "storage_config": {
            "path": str(config_dir / "approvals"),
            "encryption_enabled": True
        }
    }
    
    with open(config_file, 'w') as f:
        json.dump(default_config, f, indent=2)
    
    print(f"✅ Default configuration created: {config_file}")
    return config_file


def test_installation():
    """Test ETDI installation"""
    print("🧪 Testing ETDI installation...")
    
    try:
        # Test basic import
        import mcp.etdi
        print("✅ ETDI module imports successfully")
        
        # Test CLI
        result = subprocess.run([sys.executable, "-m", "mcp.etdi.cli", "--help"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ ETDI CLI is working")
        else:
            print("⚠️ ETDI CLI may have issues")
        
        # Test core components
        from mcp.etdi import ETDIClient, SecurityAnalyzer, TokenDebugger
        print("✅ Core ETDI components available")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def setup_environment():
    """Setup environment variables"""
    print("🌍 Setting up environment...")
    
    env_file = Path.home() / ".etdi" / ".env"
    
    if env_file.exists():
        print(f"⚠️ Environment file already exists: {env_file}")
        return
    
    env_content = """# ETDI Environment Variables
# Copy this file and update with your OAuth provider credentials

# Auth0 Configuration
ETDI_CLIENT_ID=your-auth0-client-id
ETDI_CLIENT_SECRET=your-auth0-client-secret
ETDI_DOMAIN=your-domain.auth0.com
ETDI_AUDIENCE=https://your-api.example.com

# Okta Configuration (alternative)
# ETDI_CLIENT_ID=your-okta-client-id
# ETDI_CLIENT_SECRET=your-okta-client-secret
# ETDI_DOMAIN=your-domain.okta.com

# Azure AD Configuration (alternative)
# ETDI_CLIENT_ID=your-azure-client-id
# ETDI_CLIENT_SECRET=your-azure-client-secret
# ETDI_DOMAIN=your-tenant-id

# ETDI Configuration
ETDI_CONFIG_PATH=$HOME/.etdi/config/etdi-config.json
ETDI_SECURITY_LEVEL=enhanced
"""
    
    with open(env_file, 'w') as f:
        f.write(env_content)
    
    print(f"✅ Environment template created: {env_file}")


def print_next_steps(config_file: Path):
    """Print next steps for the user"""
    print("\n" + "=" * 60)
    print("🎉 ETDI Setup Complete!")
    print("=" * 60)
    
    print("\n📋 Next Steps:")
    print("1. Configure OAuth Provider:")
    print(f"   Edit: {config_file}")
    print("   Update client_id, client_secret, and domain")
    
    print("\n2. Test ETDI CLI:")
    print("   etdi --help")
    print("   etdi init-config --provider auth0")
    print("   etdi validate-provider --config ~/.etdi/config/etdi-config.json")
    
    print("\n3. Use ETDI in Python:")
    print("   from mcp.etdi import ETDIClient")
    print("   # See examples in examples/etdi/")
    
    print("\n4. Run Examples:")
    print("   python examples/etdi/basic_usage.py")
    print("   python examples/etdi/oauth_providers.py")
    
    print("\n📚 Documentation:")
    print("   README.md - Complete usage guide")
    print("   examples/etdi/ - Working examples")
    print("   docs/ - Detailed documentation")
    
    print("\n🔧 Configuration Files:")
    print(f"   Config: {config_file}")
    print(f"   Environment: {Path.home() / '.etdi' / '.env'}")
    print(f"   Approvals: {Path.home() / '.etdi' / 'approvals'}")


def main():
    """Main setup function"""
    print("🚀 ETDI Setup Script")
    print("=" * 40)
    
    # Check requirements
    check_python_version()
    
    # Install dependencies
    install_dependencies()
    
    # Create configuration
    config_dir = create_config_directory()
    config_file = create_default_config(config_dir)
    
    # Setup environment
    setup_environment()
    
    # Test installation
    if test_installation():
        print_next_steps(config_file)
    else:
        print("\n❌ Setup completed with issues. Please check the installation.")
        sys.exit(1)


if __name__ == "__main__":
    main()