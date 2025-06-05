"""
ETDI command-line interface
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional
import click

from ..types import OAuthConfig, ETDIClientConfig, SecurityLevel
from ..client import ETDIClient
from ..inspector import SecurityAnalyzer, TokenDebugger, OAuthValidator
from ..exceptions import ETDIError


@click.group()
@click.version_option()
def cli():
    """ETDI - Enhanced Tool Definition Interface for MCP"""
    pass


@cli.command()
@click.option('--config', '-c', type=click.Path(exists=True), help='ETDI configuration file')
@click.option('--provider', '-p', type=click.Choice(['auth0', 'okta', 'azure']), help='OAuth provider')
@click.option('--client-id', help='OAuth client ID')
@click.option('--client-secret', help='OAuth client secret')
@click.option('--domain', help='OAuth provider domain')
@click.option('--audience', help='OAuth audience (Auth0)')
@click.option('--security-level', type=click.Choice(['basic', 'enhanced', 'strict']), default='enhanced')
def discover(config, provider, client_id, client_secret, domain, audience, security_level):
    """Discover and verify ETDI tools"""
    
    async def _discover():
        try:
            # Load configuration
            if config:
                with open(config) as f:
                    config_data = json.load(f)
            else:
                if not all([provider, client_id, client_secret, domain]):
                    click.echo("Error: Either --config file or OAuth parameters required", err=True)
                    sys.exit(1)
                
                oauth_config = {
                    "provider": provider,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "domain": domain
                }
                
                if audience:
                    oauth_config["audience"] = audience
                
                config_data = {
                    "security_level": security_level,
                    "oauth_config": oauth_config
                }
            
            # Initialize ETDI client
            async with ETDIClient(config_data) as client:
                click.echo("🔍 Discovering ETDI tools...")
                
                tools = await client.discover_tools()
                
                if not tools:
                    click.echo("❌ No tools discovered")
                    return
                
                click.echo(f"✅ Discovered {len(tools)} tools:")
                
                for tool in tools:
                    status_icon = "✅" if tool.verification_status.value == "verified" else "⚠️"
                    click.echo(f"  {status_icon} {tool.name} (v{tool.version}) - {tool.verification_status.value}")
                    click.echo(f"     Provider: {tool.provider.get('name', 'Unknown')}")
                    click.echo(f"     Permissions: {[p.name for p in tool.permissions]}")
                
        except ETDIError as e:
            click.echo(f"❌ ETDI Error: {e}", err=True)
            sys.exit(1)
        except Exception as e:
            click.echo(f"❌ Unexpected error: {e}", err=True)
            sys.exit(1)
    
    asyncio.run(_discover())


@cli.command()
@click.argument('token')
@click.option('--format', type=click.Choice(['json', 'text']), default='text', help='Output format')
@click.option('--output', '-o', type=click.Path(), help='Output file')
def debug_token(token, format, output):
    """Debug and analyze an OAuth token"""
    
    try:
        debugger = TokenDebugger()
        debug_info = debugger.debug_token(token)
        
        if format == 'json':
            # Convert to JSON-serializable format
            result = {
                "is_valid_jwt": debug_info.is_valid_jwt,
                "header": {
                    "algorithm": debug_info.header.algorithm if debug_info.header else None,
                    "token_type": debug_info.header.token_type if debug_info.header else None,
                    "key_id": debug_info.header.key_id if debug_info.header else None,
                } if debug_info.header else None,
                "claims": [
                    {
                        "name": claim.name,
                        "value": str(claim.value),
                        "description": claim.description,
                        "is_standard": claim.is_standard,
                        "is_etdi_specific": claim.is_etdi_specific
                    }
                    for claim in debug_info.claims
                ],
                "etdi_compliance": debug_info.etdi_compliance,
                "security_issues": debug_info.security_issues,
                "recommendations": debug_info.recommendations
            }
            
            output_text = json.dumps(result, indent=2)
        else:
            output_text = debugger.format_debug_report(debug_info)
        
        if output:
            with open(output, 'w') as f:
                f.write(output_text)
            click.echo(f"✅ Debug report saved to {output}")
        else:
            click.echo(output_text)
            
    except Exception as e:
        click.echo(f"❌ Token debugging failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--config', '-c', type=click.Path(exists=True), help='ETDI configuration file')
@click.option('--provider', '-p', type=click.Choice(['auth0', 'okta', 'azure']), help='OAuth provider')
@click.option('--client-id', help='OAuth client ID')
@click.option('--client-secret', help='OAuth client secret')
@click.option('--domain', help='OAuth provider domain')
@click.option('--audience', help='OAuth audience (Auth0)')
@click.option('--timeout', default=10.0, help='Connection timeout in seconds')
def validate_provider(config, provider, client_id, client_secret, domain, audience, timeout):
    """Validate OAuth provider configuration and connectivity"""
    
    async def _validate():
        try:
            # Load configuration
            if config:
                with open(config) as f:
                    config_data = json.load(f)
                    oauth_config = OAuthConfig.from_dict(config_data["oauth_config"])
            else:
                if not all([provider, client_id, client_secret, domain]):
                    click.echo("Error: Either --config file or OAuth parameters required", err=True)
                    sys.exit(1)
                
                oauth_config = OAuthConfig(
                    provider=provider,
                    client_id=client_id,
                    client_secret=client_secret,
                    domain=domain,
                    audience=audience
                )
            
            # Validate provider
            validator = OAuthValidator()
            result = await validator.validate_provider(oauth_config.provider, oauth_config, timeout)
            
            click.echo(f"🔍 Validating OAuth provider: {result.provider_name}")
            click.echo(f"Configuration valid: {'✅' if result.configuration_valid else '❌'}")
            click.echo(f"Provider reachable: {'✅' if result.is_reachable else '❌'}")
            click.echo(f"JWKS accessible: {'✅' if result.jwks_accessible else '❌'}")
            click.echo(f"Token endpoint accessible: {'✅' if result.token_endpoint_accessible else '❌'}")
            
            if result.checks:
                click.echo("\nValidation Details:")
                for check in result.checks:
                    status = "✅" if check.passed else "❌"
                    click.echo(f"  {status} {check.message}")
                    
        except Exception as e:
            click.echo(f"❌ Provider validation failed: {e}", err=True)
            sys.exit(1)
    
    asyncio.run(_validate())


@cli.command()
@click.argument('tool_file', type=click.Path(exists=True))
@click.option('--format', type=click.Choice(['json', 'text']), default='text', help='Output format')
@click.option('--output', '-o', type=click.Path(), help='Output file')
def analyze_tool(tool_file, format, output):
    """Analyze security of a tool definition file"""
    
    async def _analyze():
        try:
            # Load tool definition
            with open(tool_file) as f:
                tool_data = json.load(f)
            
            # Convert to ETDIToolDefinition
            from ..types import ETDIToolDefinition
            tool = ETDIToolDefinition.from_dict(tool_data)
            
            # Analyze tool
            analyzer = SecurityAnalyzer()
            result = await analyzer.analyze_tool(tool)
            
            if format == 'json':
                # Convert to JSON-serializable format
                output_data = {
                    "tool_id": result.tool_id,
                    "tool_name": result.tool_name,
                    "security_score": result.overall_security_score,
                    "findings": [
                        {
                            "severity": finding.severity.value,
                            "message": finding.message,
                            "code": finding.code,
                            "recommendation": finding.recommendation
                        }
                        for finding in result.security_findings
                    ],
                    "recommendations": result.recommendations
                }
                
                output_text = json.dumps(output_data, indent=2)
            else:
                output_text = f"""
Security Analysis Report for {result.tool_name}
{'=' * 50}

Tool ID: {result.tool_id}
Version: {result.tool_version}
Provider: {result.provider_name}
Security Score: {result.overall_security_score:.1f}/100

Security Findings:
{'-' * 20}
"""
                for finding in result.security_findings:
                    output_text += f"[{finding.severity.value.upper()}] {finding.message}\n"
                    if finding.recommendation:
                        output_text += f"  → {finding.recommendation}\n"
                
                if result.recommendations:
                    output_text += f"\nRecommendations:\n{'-' * 20}\n"
                    for rec in result.recommendations:
                        output_text += f"• {rec}\n"
            
            if output:
                with open(output, 'w') as f:
                    f.write(output_text)
                click.echo(f"✅ Analysis report saved to {output}")
            else:
                click.echo(output_text)
                
        except Exception as e:
            click.echo(f"❌ Tool analysis failed: {e}", err=True)
            sys.exit(1)
    
    asyncio.run(_analyze())


@cli.command()
@click.option('--output', '-o', type=click.Path(), default='etdi-config.json', help='Output configuration file')
@click.option('--provider', '-p', type=click.Choice(['auth0', 'okta', 'azure']), required=True, help='OAuth provider')
@click.option('--security-level', type=click.Choice(['basic', 'enhanced', 'strict']), default='enhanced')
def init_config(output, provider, security_level):
    """Initialize ETDI configuration file"""
    
    try:
        config = {
            "security_level": security_level,
            "oauth_config": {
                "provider": provider,
                "client_id": "YOUR_CLIENT_ID",
                "client_secret": "YOUR_CLIENT_SECRET",
                "domain": f"your-domain.{provider}.com"
            },
            "allow_non_etdi_tools": True,
            "show_unverified_tools": False,
            "verification_cache_ttl": 300
        }
        
        if provider == "auth0":
            config["oauth_config"]["audience"] = "https://your-api.example.com"
        
        with open(output, 'w') as f:
            json.dump(config, f, indent=2)
        
        click.echo(f"✅ ETDI configuration created: {output}")
        click.echo("📝 Please update the OAuth credentials in the configuration file")
        
    except Exception as e:
        click.echo(f"❌ Configuration creation failed: {e}", err=True)
        sys.exit(1)


def main():
    """Main CLI entry point"""
    cli()


if __name__ == '__main__':
    main()