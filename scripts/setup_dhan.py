#!/usr/bin/env python3
"""Dhan Sandbox Setup — get your free paper trading credentials.

1. Go to https://developer.dhanhq.co/
2. Sign up with email + mobile (NO Demat account needed!)
3. Copy your Client ID and Access Token from the dashboard
4. Run this script to test the connection

No KYC. No funding. No fees. Instant setup.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from src.paper_trading.broker import DhanSandboxBackend

console = Console()


def main():
    console.print(Panel.fit(
        "[bold cyan]Dhan Sandbox Setup[/bold cyan]\n\n"
        "Free paper trading API — no Demat, no KYC, no fees.\n"
        "Sign up at: [underline]https://developer.dhanhq.co/[/underline]",
        border_style="cyan",
    ))

    # Load existing env if available
    env_path = Path(__file__).parent.parent / ".env"
    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip().strip('"')

    # Get credentials
    client_id = existing.get("DHAN_CLIENT_ID", "")
    access_token = existing.get("DHAN_ACCESS_TOKEN", "")

    if not client_id:
        client_id = Prompt.ask("\n[cyan]Dhan Client ID[/cyan]", default="").strip()
    else:
        console.print(f"\n[dim]DHAN_CLIENT_ID found in .env: {client_id[:8]}...[/dim]")

    if not access_token:
        access_token = Prompt.ask("[cyan]Dhan Access Token[/cyan]", default="").strip()
    else:
        console.print(f"[dim]DHAN_ACCESS_TOKEN found in .env: {access_token[:12]}...[/dim]")

    if not client_id or not access_token:
        console.print("\n[red]Both Client ID and Access Token are required.[/red]")
        console.print("Get them from: https://developer.dhanhq.co/")
        return

    # Test connection
    console.print("\n[yellow]Testing Dhan sandbox connection...[/yellow]")
    backend = DhanSandboxBackend(client_id=client_id, access_token=access_token)

    if backend.connect():
        console.print("\n[green]✓ Dhan sandbox connected![/green]")

        # Get fund details
        funds = backend.get_funds()
        if funds:
            console.print(f"[dim]Sandbox funds: {funds}[/dim]")

        # Save to .env
        save = Prompt.ask(
            "\n[cyan]Save credentials to .env?[/cyan]",
            choices=["y", "n"],
            default="y",
        )
        if save == "y":
            _save_env(env_path, client_id, access_token, existing)
            console.print("[green]✓ Credentials saved to .env[/green]")

        console.print("\n[bold green]Ready to paper trade![/bold green]")
        console.print("Run: [cyan]python scripts/run_paper.py[/cyan]")

        # Test order placement
        test = Prompt.ask(
            "\n[cyan]Test a dummy order?[/cyan]",
            choices=["y", "n"],
            default="n",
        )
        if test == "y":
            result = backend.place_order("RELIANCE", "BUY", 10, 2500.0, order_type="MARKET")
            console.print(f"\n[dim]Test order result:[/dim]")
            console.print_json(data=result)

    else:
        console.print("\n[red]✗ Dhan sandbox connection failed.[/red]")
        console.print("Check your Client ID and Access Token at https://developer.dhanhq.co/")


def _save_env(env_path: Path, client_id: str, access_token: str, existing: dict):
    """Update .env with Dhan credentials."""
    existing["DHAN_CLIENT_ID"] = client_id
    existing["DHAN_ACCESS_TOKEN"] = access_token
    existing.setdefault("PAPER_TRADING_BROKER", "dhan")

    lines = []
    for k, v in existing.items():
        lines.append(f"{k}={v}")

    env_path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
