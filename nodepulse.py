#!/usr/bin/env python3
"""
NodePulse - Bitcoin Core Terminal Dashboard
A beautiful terminal UI for monitoring your Bitcoin node in real-time.
"""

import json
import subprocess
import os
import psutil
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, Label, Button, TabbedContent, TabPane
from textual.reactive import reactive
from textual.screen import ModalScreen
from rich.text import Text
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskID
from rich.table import Table


class ConfirmDialog(ModalScreen):
    """Confirmation dialog for dangerous operations"""

    CSS = """
    ConfirmDialog {
        align: center middle;
    }

    #dialog {
        width: 60;
        height: 11;
        border: thick $primary 80%;
        background: $surface;
        padding: 1 2;
    }

    #buttons {
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }

    Button {
        margin: 0 2;
    }
    """

    def __init__(self, message: str, action: str):
        super().__init__()
        self.message = message
        self.action = action

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static(f"[bold yellow]{self.message}[/]", id="question")
            with Horizontal(id="buttons"):
                yield Button("Yes", variant="error", id="yes")
                yield Button("No", variant="primary", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
            self.dismiss(False)


class BitcoinNodeController:
    """Controls for starting/stopping Bitcoin node"""

    def __init__(self, bitcoind_path=None):
        self.bitcoind = bitcoind_path or os.path.expanduser("~/bin/bitcoind")
        self.bitcoin_cli = os.path.expanduser("~/bin/bitcoin-cli")

    def is_running(self):
        """Check if bitcoind is running"""
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                if 'bitcoind' in proc.info['name'].lower():
                    return True
                if proc.info['cmdline'] and any('bitcoind' in arg for arg in proc.info['cmdline']):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    async def start_node(self):
        """Start bitcoind daemon"""
        try:
            # Set ulimit before starting
            process = await asyncio.create_subprocess_exec(
                "sh", "-c", f"ulimit -n 4096 && {self.bitcoind} -daemon",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
            output = stdout.decode() + stderr.decode()
            return process.returncode == 0, output
        except Exception as e:
            return False, str(e)

    async def stop_node(self):
        """Stop bitcoind daemon"""
        try:
            process = await asyncio.create_subprocess_exec(
                self.bitcoin_cli, "stop",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
            output = stdout.decode() + stderr.decode()
            return process.returncode == 0, output
        except Exception as e:
            return False, str(e)

    async def get_uptime(self):
        """Get node uptime in seconds"""
        try:
            process = await asyncio.create_subprocess_exec(
                self.bitcoin_cli, "uptime",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
            if process.returncode == 0:
                return int(stdout.decode().strip())
        except:
            pass
        return None


class BitcoinNodeData:
    """Handles communication with Bitcoin Core via bitcoin-cli"""

    def __init__(self, bitcoin_cli_path=None):
        self.bitcoin_cli = bitcoin_cli_path or os.path.expanduser("~/bin/bitcoin-cli")

    async def run_command(self, *args):
        """Execute bitcoin-cli command and return JSON result (async)"""
        try:
            cmd = [self.bitcoin_cli] + list(args)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
            if process.returncode == 0:
                return json.loads(stdout.decode())
            return None
        except Exception as e:
            return None

    async def get_blockchain_info(self):
        return await self.run_command("getblockchaininfo")

    async def get_network_info(self):
        return await self.run_command("getnetworkinfo")

    async def get_peer_info(self):
        return await self.run_command("getpeerinfo")

    async def get_mempool_info(self):
        return await self.run_command("getmempoolinfo")

    async def estimate_smart_fee(self, conf_target):
        return await self.run_command("estimatesmartfee", str(conf_target))

    async def get_block_hash(self, height):
        return await self.run_command("getblockhash", str(height))

    async def get_block(self, block_hash):
        return await self.run_command("getblock", block_hash, "1")

    async def get_uptime(self):
        """Get node uptime in seconds"""
        result = await self.run_command("uptime")
        if result is not None:
            return result
        return 0


class BitcoinConfigManager:
    """Manages Bitcoin Core configuration file (bitcoin.conf)"""

    def __init__(self, config_path=None):
        if config_path:
            self.config_path = Path(config_path)
        else:
            self.config_path = Path.home() / "Library" / "Application Support" / "Bitcoin" / "bitcoin.conf"

    def read_config(self):
        """Read and parse bitcoin.conf, returning a dict of settings"""
        settings = {}

        if not self.config_path.exists():
            return settings

        try:
            with open(self.config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue

                    # Parse key=value pairs
                    if '=' in line:
                        key, value = line.split('=', 1)
                        settings[key.strip()] = value.strip()
        except Exception as e:
            return settings

        return settings

    def write_config(self, settings):
        """Write settings to bitcoin.conf, preserving structure and comments"""
        if not self.config_path.exists():
            return False, "Config file not found"

        try:
            # Create backup first
            self.backup_config()

            # Read current file to preserve comments
            with open(self.config_path, 'r') as f:
                lines = f.readlines()

            # Update lines with new settings
            new_lines = []
            updated_keys = set()

            for line in lines:
                stripped = line.strip()

                # Keep comments and empty lines
                if not stripped or stripped.startswith('#'):
                    new_lines.append(line)
                    continue

                # Update existing settings
                if '=' in stripped:
                    key = stripped.split('=', 1)[0].strip()
                    if key in settings:
                        # Update this setting
                        new_lines.append(f"{key}={settings[key]}\n")
                        updated_keys.add(key)
                    else:
                        # Keep original line
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            # Add new settings that weren't in the file
            for key, value in settings.items():
                if key not in updated_keys:
                    new_lines.append(f"\n# Added by NodePulse\n{key}={value}\n")

            # Write back to file
            with open(self.config_path, 'w') as f:
                f.writelines(new_lines)

            return True, "Configuration saved successfully"

        except Exception as e:
            return False, f"Error writing config: {str(e)}"

    def backup_config(self):
        """Create a backup of bitcoin.conf"""
        if not self.config_path.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.config_path.parent / f"bitcoin.conf.backup.{timestamp}"

        try:
            import shutil
            shutil.copy2(self.config_path, backup_path)
        except:
            pass

    def validate_setting(self, key, value):
        """Validate configuration values"""
        validations = {
            'prune': lambda v: v == '0' or (v.isdigit() and int(v) >= 550),
            'maxconnections': lambda v: v.isdigit() and 8 <= int(v) <= 125,
            'dbcache': lambda v: v.isdigit() and 4 <= int(v) <= 16384,
            'rpcport': lambda v: v.isdigit() and 1024 <= int(v) <= 65535,
        }

        if key in validations:
            try:
                if not validations[key](str(value)):
                    return False, f"Invalid value for {key}"
            except:
                return False, f"Invalid value for {key}"

        return True, "Valid"

    def get_default_settings(self):
        """Return default Bitcoin Core settings"""
        return {
            'prune': '0',  # 0 = disabled (full node)
            'maxconnections': '125',
            'dbcache': '450',
            'server': '0',
            'rpcport': '8332',
        }


class SyncStatsTracker:
    """Track sync statistics over time"""

    def __init__(self, max_history=60):
        self.max_history = max_history
        self.history = deque(maxlen=max_history)
        self.start_time = datetime.now()
        self.initial_blocks = None
        self.was_syncing = None

    def update(self, blocks, headers, is_syncing):
        """Update with new data point"""
        now = datetime.now()

        if self.initial_blocks is None:
            self.initial_blocks = blocks

        sync_completed = self.was_syncing and not is_syncing
        self.was_syncing = is_syncing

        self.history.append({
            'time': now,
            'blocks': blocks,
            'headers': headers,
            'is_syncing': is_syncing
        })

        return sync_completed

    def get_blocks_per_hour(self):
        """Calculate blocks per hour"""
        if len(self.history) < 2:
            return 0

        recent_data = list(self.history)[-12:]
        if len(recent_data) < 2:
            return 0

        oldest = recent_data[0]
        newest = recent_data[-1]

        time_diff = (newest['time'] - oldest['time']).total_seconds() / 3600
        if time_diff == 0:
            return 0

        block_diff = newest['blocks'] - oldest['blocks']
        return block_diff / time_diff

    def get_eta(self, current_blocks, total_headers):
        """Estimate time to completion"""
        bph = self.get_blocks_per_hour()
        if bph == 0 or current_blocks >= total_headers:
            return None

        blocks_remaining = total_headers - current_blocks
        hours_remaining = blocks_remaining / bph

        return timedelta(hours=hours_remaining)

    def get_uptime(self):
        """Get time since tracking started"""
        return datetime.now() - self.start_time

    def get_blocks_synced(self):
        """Get total blocks synced since start"""
        if not self.history or self.initial_blocks is None:
            return 0
        return self.history[-1]['blocks'] - self.initial_blocks


class ClickableLabel(Label):
    """Label with hover effects"""

    def __init__(self, normal_text: str, hover_text: str, **kwargs):
        super().__init__(normal_text, **kwargs)
        self.normal_text = normal_text
        self.hover_text = hover_text
        self.is_hovered = False

    def on_enter(self) -> None:
        """Mouse entered the label"""
        self.is_hovered = True
        self.update(self.hover_text)

    def on_leave(self) -> None:
        """Mouse left the label"""
        self.is_hovered = False
        self.update(self.normal_text)

    def set_texts(self, normal: str, hover: str) -> None:
        """Update both normal and hover texts"""
        self.normal_text = normal
        self.hover_text = hover
        if self.is_hovered:
            self.update(self.hover_text)
        else:
            self.update(self.normal_text)


class ControlsPanel(Static):
    """Display node controls"""

    def __init__(self, controller, alerts_panel):
        super().__init__()
        self.controller = controller
        self.alerts_panel = alerts_panel

    def compose(self) -> ComposeResult:
        """Create control widgets"""
        yield Static("", id="node-status")
        yield Static("[dim green]┌─ NODE MANAGEMENT[/]", classes="section-header")
        yield ClickableLabel(
            "  ├─ [cyan][▓▒░][/cyan] Start Node",
            "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]Start Node[/bold]",
            id="action-start"
        )
        yield ClickableLabel(
            "  ├─ [cyan][▓▒░][/cyan] Stop Node",
            "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]Stop Node[/bold]",
            id="action-stop"
        )
        yield ClickableLabel(
            "  └─ [cyan][▓▒░][/cyan] Restart Node",
            "  └─ [bold yellow][▓▒░][/bold yellow] [bold]Restart Node[/bold]",
            id="action-restart"
        )
        yield Static("")
        yield Static("[dim green]┌─ DATA MANAGEMENT[/]", classes="section-header")
        yield ClickableLabel(
            "  ├─ [cyan][▓▒░][/cyan] Refresh Data",
            "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]Refresh Data[/bold]",
            id="action-refresh"
        )
        yield ClickableLabel(
            "  └─ [cyan][▓▒░][/cyan] Clear Alerts",
            "  └─ [bold yellow][▓▒░][/bold yellow] [bold]Clear Alerts[/bold]",
            id="action-clear"
        )

    def on_mount(self) -> None:
        """Update status on mount"""
        self.run_worker(self.update_status(), exclusive=True)
        self.set_interval(5, lambda: self.run_worker(self.update_status(), exclusive=True))

    async def update_status(self) -> None:
        """Update node status display"""
        is_running = self.controller.is_running()
        uptime = await self.controller.get_uptime()

        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left", style="cyan")
        table.add_column(justify="left")

        if is_running:
            table.add_row("Node Status:", "[bold green]🟢 Running[/]")
            if uptime:
                hours = uptime // 3600
                minutes = (uptime % 3600) // 60
                table.add_row("Uptime:", f"[dim]{hours}h {minutes}m[/]")
        else:
            table.add_row("Node Status:", "[bold red]🔴 Stopped[/]")
            table.add_row("", "[dim]Node is not running[/]")

        panel = Panel(table, title="⚙️  Node Controls", border_style="cyan")
        status_widget = self.query_one("#node-status", Static)
        status_widget.update(panel)

    async def on_click(self, event) -> None:
        """Handle label clicks"""
        # Check if a ClickableLabel was clicked
        if not isinstance(event.widget, (Label, ClickableLabel)):
            return

        action_id = event.widget.id

        if action_id == "action-start":
            self.run_worker(self.start_node())
        elif action_id == "action-stop":
            self.run_worker(self.stop_node())
        elif action_id == "action-restart":
            self.run_worker(self.restart_node())
        elif action_id == "action-refresh":
            if self.alerts_panel:
                self.alerts_panel.add_alert("Manual refresh triggered", "info")
            self.app.refresh_data()
        elif action_id == "action-clear":
            if self.alerts_panel:
                self.alerts_panel.alerts = []
                self.alerts_panel.update_render()
                self.alerts_panel.add_alert("Alerts cleared", "info")

    async def start_node(self) -> None:
        """Start the node"""
        if self.controller.is_running():
            self.alerts_panel.add_alert("Node is already running", "warning")
            return

        self.alerts_panel.add_alert("Starting node...", "info")
        success, message = await self.controller.start_node()

        if success:
            self.alerts_panel.add_alert("Node started successfully ✓", "success")
        else:
            self.alerts_panel.add_alert(f"Failed to start node: {message[:50]}", "error")

        await self.update_status()

    async def stop_node(self) -> None:
        """Stop the node with confirmation"""
        if not self.controller.is_running():
            self.alerts_panel.add_alert("Node is not running", "warning")
            return

        confirmed = await self.app.push_screen_wait(
            ConfirmDialog("Are you sure you want to stop the node?", "stop")
        )

        if confirmed:
            self.alerts_panel.add_alert("Stopping node...", "info")
            success, message = await self.controller.stop_node()

            if success:
                self.alerts_panel.add_alert("Node stopped successfully ✓", "success")
            else:
                self.alerts_panel.add_alert(f"Failed to stop node: {message[:50]}", "error")

            await self.update_status()

    async def restart_node(self) -> None:
        """Restart the node with confirmation"""
        confirmed = await self.app.push_screen_wait(
            ConfirmDialog("Are you sure you want to restart the node?", "restart")
        )

        if confirmed:
            self.alerts_panel.add_alert("Restarting node...", "info")

            # Stop first
            if self.controller.is_running():
                success, _ = await self.controller.stop_node()
                if success:
                    self.alerts_panel.add_alert("Node stopped, waiting 3s...", "info")
                    await self.app.sleep(3)

            # Then start
            success, message = await self.controller.start_node()
            if success:
                self.alerts_panel.add_alert("Node restarted successfully ✓", "success")
            else:
                self.alerts_panel.add_alert(f"Failed to restart: {message[:50]}", "error")

            await self.update_status()


class DashboardPanel(Static):
    """Main dashboard with welcome screen and quick stats"""

    def __init__(self):
        super().__init__("⚠️  Loading...")
        self.node_running = False
        self.blockchain_info = None
        self.network_info = None
        self.uptime = 0

    def update_data(self, node_running, blockchain_info, network_info, uptime):
        self.node_running = node_running
        self.blockchain_info = blockchain_info
        self.network_info = network_info
        self.uptime = uptime
        self.update_render()

    def update_render(self):
        # Retro terminal banner
        banner_top = "╔═══════════════════════════════════════════════════════════════════════════╗"
        banner_bot = "╚═══════════════════════════════════════════════════════════════════════════╝"

        # Retro ASCII Art Logo (more compact, terminal style)
        logo = """
        ░▒▓█  █▄  █  ████  █▀▄  █▀▀  █▀█  █  █  █    ▄▀▀  █▀▀  █▓▒░
        ░▒▓█  █ ▀▄█  █  █  █ █  █▀   █▀▀  █  █  █     ▀▄  █▀   █▓▒░
        ░▒▓█  █   █  ████  ▀▀   ▀▀▀  ▀    ▀▀▀   ▀▀▀  ▀▀   ▀▀▀  █▓▒░"""

        # Node Status with retro indicators
        if self.node_running:
            node_status_text = "RUNNING"
            node_indicator = "[bold green]███[/]"
            node_color = "green"
        else:
            node_status_text = "OFFLINE"
            node_indicator = "[bold red]███[/]"
            node_color = "red"

        # Sync Status with ASCII progress bar
        if self.blockchain_info:
            blocks = self.blockchain_info.get("blocks", 0)
            headers = self.blockchain_info.get("headers", 0)
            progress = self.blockchain_info.get("verificationprogress", 0) * 100

            # Create retro progress bar
            bar_width = 30
            filled = int((progress / 100) * bar_width)
            sync_bar = "█" * filled + "░" * (bar_width - filled)

            sync_status = f"[cyan]{blocks:,}[/cyan] / [dim]{headers:,}[/dim]"
            sync_percent = f"[yellow]{progress:.1f}%[/yellow]"
        else:
            sync_bar = "░" * 30
            sync_status = "[dim]N/A[/dim]"
            sync_percent = "[dim]---[/dim]"

        # Network Status with connection indicators
        if self.network_info:
            connections = self.network_info.get("connections", 0)
            subversion = self.network_info.get("subversion", "")

            # Create visual peer indicator
            peer_blocks = min(connections, 10)
            peer_visual = "▓" * peer_blocks + "░" * (10 - peer_blocks)
            peer_status = f"[green]{connections:02d}[/green]"

            core_version = subversion.replace("/", "").replace("Satoshi:", "v")
        else:
            peer_visual = "░" * 10
            peer_status = "[dim]00[/dim]"
            core_version = "[dim]N/A[/dim]"

        # Uptime with retro format
        if self.uptime > 0:
            hours = int(self.uptime // 3600)
            minutes = int((self.uptime % 3600) // 60)
            uptime_str = f"[cyan]{hours:03d}h:{minutes:02d}m[/cyan]"
        else:
            uptime_str = "[dim]000h:00m[/dim]"

        # Build retro content
        content = Text()
        content.append(banner_top + "\n", style="bold green")
        content.append(logo + "\n", style="bold cyan")
        content.append(banner_bot + "\n", style="bold green")
        content.append("\n")
        content.append("        ▓▒░ BITCOIN CORE TERMINAL MONITORING SYSTEM ░▒▓\n", style="dim green italic")
        content.append("\n")

        # Status grid with retro styling
        status_table = Table.grid(padding=(0, 2))
        status_table.add_column(justify="left", style="dim green")
        status_table.add_column(justify="left")
        status_table.add_column(justify="left", style="dim green")
        status_table.add_column(justify="left")

        # Row 1: Node Status & Version
        status_table.add_row(
            "┌─ NODE STATUS",
            f"{node_indicator} [{node_color}]{node_status_text}[/{node_color}]",
            "┌─ VERSION",
            "[yellow]NodePulse v1.3.0[/yellow]"
        )

        # Row 2: Uptime & Core Version
        status_table.add_row(
            "├─ UPTIME",
            uptime_str,
            "├─ BITCOIN CORE",
            f"[yellow]{core_version}[/yellow]"
        )

        # Row 3: Sync Progress
        status_table.add_row(
            "├─ SYNC BLOCKS",
            sync_status,
            "",
            ""
        )

        # Row 4: Progress bar
        status_table.add_row(
            "└─ PROGRESS",
            f"[{sync_bar}] {sync_percent}",
            "",
            ""
        )

        status_table.add_row("", "", "", "")

        # Row 5: Network
        status_table.add_row(
            "┌─ NETWORK PEERS",
            f"{peer_status} [{peer_visual}]",
            "",
            ""
        )

        # Separator
        separator = "═" * 75

        # Navigation menu with retro style (vertical list)
        nav_table = Table.grid(padding=(0, 2))
        nav_table.add_column(justify="left", style="bold cyan", width=35)
        nav_table.add_column(justify="left", style="dim")

        nav_table.add_row(
            "[▓▒░ 1 ░▒▓] DASHBOARD",
            "→ Overview, Quick Stats"
        )
        nav_table.add_row(
            "[▓▒░ 2 ░▒▓] SYNC STATUS",
            "→ Sync, Stats, Alerts"
        )
        nav_table.add_row(
            "[▓▒░ 3 ░▒▓] BLOCKCHAIN INFO",
            "→ Network, Storage, Pool"
        )
        nav_table.add_row(
            "[▓▒░ 4 ░▒▓] NODE CONTROLS",
            "→ Start, Stop, Restart"
        )
        nav_table.add_row(
            "[▓▒░ 5 ░▒▓] SETTINGS",
            "→ Bitcoin Core Configuration"
        )

        # Final assembly
        final_content = Table.grid()
        final_content.add_column(justify="center")
        final_content.add_row("")
        final_content.add_row(content)
        final_content.add_row("")
        final_content.add_row(status_table)
        final_content.add_row("")
        final_content.add_row(Text(separator, style="dim green"))
        final_content.add_row("")
        final_content.add_row(nav_table)
        final_content.add_row("")

        panel = Panel(final_content, border_style="bold green", padding=(1, 3))
        self.update(panel)


class SyncPanel(Static):
    """Display blockchain synchronization status"""

    def __init__(self):
        super().__init__("⚠️  Waiting for node data...")
        self.blockchain_info = None

    def update_data(self, blockchain_info):
        self.blockchain_info = blockchain_info
        self.update_render()

    def update_render(self):
        if not self.blockchain_info:
            self.update("⚠️  Waiting for node data...")
            return

        blocks = self.blockchain_info.get("blocks", 0)
        headers = self.blockchain_info.get("headers", 0)
        progress = self.blockchain_info.get("verificationprogress", 0) * 100
        ibd = self.blockchain_info.get("initialblockdownload", False)
        chain = self.blockchain_info.get("chain", "unknown")
        pruned = self.blockchain_info.get("pruned", False)
        prune_size = self.blockchain_info.get("prune_target_size", 0) / (1024**3)

        bar_width = 40
        filled = int((progress / 100) * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        status = "🔄 Syncing" if ibd else "✅ Synced"

        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left", style="cyan")
        table.add_column(justify="left")

        table.add_row("Status:", f"[bold green]{status}[/]")
        table.add_row("Chain:", f"[yellow]{chain.upper()}[/]")
        table.add_row("Blocks:", f"[bold]{blocks:,}[/] / {headers:,}")
        table.add_row("Progress:", f"[{bar}] {progress:.2f}%")
        table.add_row("Mode:", f"[magenta]{'Pruned' if pruned else 'Full Node'}[/]")
        if pruned:
            table.add_row("Prune Limit:", f"[magenta]{prune_size:.1f} GB[/]")

        panel = Panel(table, title="⛓️  Blockchain Sync", border_style="blue")
        self.update(panel)


class SyncStatsPanel(Static):
    """Display sync statistics and ETA"""

    def __init__(self):
        super().__init__()
        self.stats = None
        self.update("⚠️  Waiting for sync data...")

    def update_data(self, tracker, blockchain_info):
        if not blockchain_info:
            self.update("⚠️  Waiting for sync data...")
            return

        blocks = blockchain_info.get("blocks", 0)
        headers = blockchain_info.get("headers", 0)
        is_syncing = blockchain_info.get("initialblockdownload", False)

        bph = tracker.get_blocks_per_hour()
        eta = tracker.get_eta(blocks, headers)
        uptime = tracker.get_uptime()
        blocks_synced = tracker.get_blocks_synced()

        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left", style="cyan")
        table.add_column(justify="left")

        table.add_row("Speed:", f"[bold green]{bph:,.0f}[/] blocks/hour")

        if is_syncing and eta:
            days = eta.days
            hours = eta.seconds // 3600
            minutes = (eta.seconds % 3600) // 60

            if days > 0:
                eta_str = f"{days}d {hours}h"
            elif hours > 0:
                eta_str = f"{hours}h {minutes}m"
            else:
                eta_str = f"{minutes}m"

            table.add_row("ETA:", f"[yellow]{eta_str}[/]")
        else:
            table.add_row("ETA:", "[green]Synced![/]")

        uptime_hours = int(uptime.total_seconds() // 3600)
        uptime_minutes = int((uptime.total_seconds() % 3600) // 60)
        table.add_row("Uptime:", f"[dim]{uptime_hours}h {uptime_minutes}m[/]")
        table.add_row("Synced:", f"[dim]{blocks_synced:,} blocks[/]")

        panel = Panel(table, title="📊 Sync Stats", border_style="blue")
        self.update(panel)


class AlertsPanel(Static):
    """Display alerts and notifications"""

    def __init__(self):
        super().__init__("[dim]Initializing alerts...[/]")
        self.alerts = []

    def add_alert(self, message, level="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.alerts.append({
            'time': timestamp,
            'message': message,
            'level': level
        })
        self.alerts = self.alerts[-5:]
        self.update_render()

    def update_render(self):
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="left", style="dim")
        table.add_column(justify="left")

        if not self.alerts:
            table.add_row("", "[dim]No alerts[/]")
        else:
            for alert in reversed(self.alerts):
                level_color = {
                    'success': 'green',
                    'warning': 'yellow',
                    'error': 'red',
                    'info': 'cyan'
                }.get(alert['level'], 'white')

                icon = {
                    'success': '✅',
                    'warning': '⚠️',
                    'error': '❌',
                    'info': 'ℹ️'
                }.get(alert['level'], '•')

                table.add_row(
                    f"[dim]{alert['time']}[/]",
                    f"[{level_color}]{icon} {alert['message']}[/]"
                )

        panel = Panel(table, title="🔔 Alerts", border_style="yellow")
        self.update(panel)


class RecentBlocksPanel(Static):
    """Display recently processed blocks"""

    def __init__(self):
        super().__init__("⚠️  Waiting for blocks...")
        self.blocks = []
        self.cached_height = None

    async def update_data(self, bitcoin, current_height):
        if current_height == 0:
            self.update("⚠️  Waiting for blocks...")
            return

        # Skip if height hasn't changed
        if self.cached_height == current_height and self.blocks:
            return

        self.cached_height = current_height
        blocks_to_show = 3  # Reduced from 5 to 3 for performance
        new_blocks = []

        # Get all block hashes in parallel
        heights = [current_height - i for i in range(blocks_to_show) if current_height - i >= 0]
        block_hashes = await asyncio.gather(*[bitcoin.get_block_hash(h) for h in heights])

        # Get all block details in parallel
        valid_hashes = [(h, hash_val) for h, hash_val in zip(heights, block_hashes) if hash_val]
        if valid_hashes:
            blocks_data = await asyncio.gather(*[bitcoin.get_block(hash_val) for _, hash_val in valid_hashes])

            for (height, block_hash), block in zip(valid_hashes, blocks_data):
                if block:
                    new_blocks.append({
                        'height': height,
                        'hash': block_hash,
                        'time': block.get('time', 0),
                        'tx': block.get('nTx', 0),
                        'size': block.get('size', 0) / 1024,
                    })

        self.blocks = new_blocks
        self.update_render()

    def update_render(self):
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="right", style="cyan")
        table.add_column(justify="left", style="dim")
        table.add_column(justify="right", style="yellow")
        table.add_column(justify="right", style="green")

        if not self.blocks:
            table.add_row("", "[dim]No blocks yet[/]", "", "")
        else:
            for block in self.blocks:
                block_time = datetime.fromtimestamp(block['time'])
                time_str = block_time.strftime("%H:%M:%S")
                hash_short = block['hash'][:8] + "..."

                table.add_row(
                    f"{block['height']:,}",
                    f"{hash_short}",
                    f"{block['tx']} txs",
                    f"{block['size']:.0f} KB"
                )

        panel = Panel(table, title="📦 Recent Blocks", border_style="cyan")
        self.update(panel)


class NetworkPanel(Static):
    """Display network connections and peer info"""

    def __init__(self):
        super().__init__("⚠️  Waiting for network data...")
        self.network_info = None
        self.peer_info = None

    def update_data(self, network_info, peer_info):
        self.network_info = network_info
        self.peer_info = peer_info
        self.update_render()

    def update_render(self):
        if not self.network_info:
            self.update("⚠️  Waiting for network data...")
            return

        connections = self.network_info.get("connections", 0)
        connections_in = self.network_info.get("connections_in", 0)
        connections_out = self.network_info.get("connections_out", 0)
        subversion = self.network_info.get("subversion", "")

        peer_versions = {}
        if self.peer_info:
            for peer in self.peer_info:
                ver = peer.get("subver", "Unknown")
                peer_versions[ver] = peer_versions.get(ver, 0) + 1

        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left", style="cyan")
        table.add_column(justify="left")

        table.add_row("Total Peers:", f"[bold green]{connections}[/]")
        table.add_row("Inbound:", f"[green]{connections_in}[/]")
        table.add_row("Outbound:", f"[green]{connections_out}[/]")
        table.add_row("Your Version:", f"[yellow]{subversion}[/]")

        if peer_versions:
            table.add_row("", "")
            table.add_row("[dim]Peer Clients:[/]", "")
            for ver, count in sorted(peer_versions.items(), key=lambda x: x[1], reverse=True)[:3]:
                table.add_row(f"  {ver[:30]}", f"{count}")

        panel = Panel(table, title="🌐 Network", border_style="green")
        self.update(panel)


class StoragePanel(Static):
    """Display disk usage and pruning info"""

    def __init__(self):
        super().__init__("⚠️  Waiting for storage data...")
        self.blockchain_info = None

    def update_data(self, blockchain_info):
        self.blockchain_info = blockchain_info
        self.update_render()

    def update_render(self):
        if not self.blockchain_info:
            self.update("⚠️  Waiting for storage data...")
            return

        size_on_disk = self.blockchain_info.get("size_on_disk", 0) / (1024**3)
        pruned = self.blockchain_info.get("pruned", False)
        prune_target = self.blockchain_info.get("prune_target_size", 0) / (1024**3)

        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left", style="cyan")
        table.add_column(justify="left")

        table.add_row("Used Space:", f"[bold yellow]{size_on_disk:.2f} GB[/]")

        if pruned and prune_target > 0:
            percentage = (size_on_disk / prune_target) * 100
            bar_width = 30
            filled = int((percentage / 100) * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)

            table.add_row("Prune Limit:", f"[magenta]{prune_target:.1f} GB[/]")
            table.add_row("Usage:", f"[{bar}] {percentage:.1f}%")
        else:
            table.add_row("Mode:", "[green]Full Node[/]")

        panel = Panel(table, title="💾 Storage", border_style="yellow")
        self.update(panel)


class MempoolPanel(Static):
    """Display mempool information"""

    def __init__(self):
        super().__init__("⚠️  Waiting for mempool data...")
        self.mempool_info = None
        self.fee_estimates = {}

    def update_data(self, mempool_info, fee_estimates):
        self.mempool_info = mempool_info
        self.fee_estimates = fee_estimates
        self.update_render()

    def update_render(self):
        if not self.mempool_info:
            self.update("⚠️  Waiting for mempool data...")
            return

        size = self.mempool_info.get("size", 0)
        bytes_size = self.mempool_info.get("bytes", 0) / (1024**2)
        usage = self.mempool_info.get("usage", 0) / (1024**2)
        max_usage = self.mempool_info.get("maxmempool", 0) / (1024**2)

        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left", style="cyan")
        table.add_column(justify="left")

        table.add_row("Transactions:", f"[bold]{size:,}[/]")
        table.add_row("Size:", f"[yellow]{bytes_size:.2f} MB[/]")
        table.add_row("Memory:", f"[yellow]{usage:.2f} / {max_usage:.0f} MB[/]")

        if self.fee_estimates:
            table.add_row("", "")
            table.add_row("[dim]Fee Estimates (sat/vB):[/]", "")

            for target, data in sorted(self.fee_estimates.items()):
                if data and "feerate" in data:
                    feerate_btc_kb = data["feerate"]
                    sat_vb = (feerate_btc_kb * 100000000) / 1000
                    table.add_row(f"  {target} blocks:", f"[green]{sat_vb:.1f}[/]")

        panel = Panel(table, title="📋 Mempool", border_style="magenta")
        self.update(panel)


class SettingsPanel(ScrollableContainer):
    """Display and edit Bitcoin node configuration"""

    def __init__(self, config_manager, controller, alerts_panel):
        super().__init__()
        self.config_manager = config_manager
        self.controller = controller
        self.alerts_panel = alerts_panel
        self.current_settings = {}
        self.pending_changes = {}

    def compose(self) -> ComposeResult:
        """Create settings widgets"""
        yield Static("", id="settings-display")

        # Grid layout with 2 columns
        with Horizontal(id="settings-grid"):
            # Left column
            with Vertical(classes="settings-column"):
                # Pruned Mode options
                yield Static("[dim green]┌─ PRUNED MODE[/]", classes="section-header")
                yield ClickableLabel(
                    "  ├─ [cyan][▓▒░][/cyan] Disable (Full Node)",
                    "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]Disable (Full Node)[/bold]",
                    id="prune-0"
                )
                yield ClickableLabel(
                    "  ├─ [cyan][▓▒░][/cyan] 4 GB",
                    "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]4 GB[/bold]",
                    id="prune-4096"
                )
                yield ClickableLabel(
                    "  ├─ [cyan][▓▒░][/cyan] 10 GB",
                    "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]10 GB[/bold]",
                    id="prune-10240"
                )
                yield ClickableLabel(
                    "  └─ [cyan][▓▒░][/cyan] 50 GB",
                    "  └─ [bold yellow][▓▒░][/bold yellow] [bold]50 GB[/bold]",
                    id="prune-51200"
                )

                # Max Connections options
                yield Static("[dim green]┌─ MAX CONNECTIONS[/]", classes="section-header")
                yield ClickableLabel(
                    "  ├─ [cyan][▓▒░][/cyan] 10",
                    "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]10[/bold]",
                    id="maxconn-10"
                )
                yield ClickableLabel(
                    "  ├─ [cyan][▓▒░][/cyan] 25",
                    "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]25[/bold]",
                    id="maxconn-25"
                )
                yield ClickableLabel(
                    "  ├─ [cyan][▓▒░][/cyan] 50",
                    "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]50[/bold]",
                    id="maxconn-50"
                )
                yield ClickableLabel(
                    "  └─ [cyan][▓▒░][/cyan] 125 (default)",
                    "  └─ [bold yellow][▓▒░][/bold yellow] [bold]125 (default)[/bold]",
                    id="maxconn-125"
                )

            # Right column
            with Vertical(classes="settings-column"):
                # DB Cache options
                yield Static("[dim green]┌─ DB CACHE (MB)[/]", classes="section-header")
                yield ClickableLabel(
                    "  ├─ [cyan][▓▒░][/cyan] 300",
                    "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]300[/bold]",
                    id="dbcache-300"
                )
                yield ClickableLabel(
                    "  ├─ [cyan][▓▒░][/cyan] 450 (default)",
                    "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]450 (default)[/bold]",
                    id="dbcache-450"
                )
                yield ClickableLabel(
                    "  ├─ [cyan][▓▒░][/cyan] 1000",
                    "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]1000[/bold]",
                    id="dbcache-1000"
                )
                yield ClickableLabel(
                    "  └─ [cyan][▓▒░][/cyan] 2000",
                    "  └─ [bold yellow][▓▒░][/bold yellow] [bold]2000[/bold]",
                    id="dbcache-2000"
                )

                # RPC Server options
                yield Static("[dim green]┌─ RPC SERVER[/]", classes="section-header")
                yield ClickableLabel(
                    "  ├─ [cyan][▓▒░][/cyan] Enable RPC",
                    "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]Enable RPC[/bold]",
                    id="rpc-enable"
                )
                yield ClickableLabel(
                    "  └─ [cyan][▓▒░][/cyan] Disable RPC",
                    "  └─ [bold yellow][▓▒░][/bold yellow] [bold]Disable RPC[/bold]",
                    id="rpc-disable"
                )

        # Action buttons (full width)
        yield Static("[dim green]┌─ ACTIONS[/]", classes="section-header")
        yield ClickableLabel(
            "  ├─ [green][▓▒░][/green] Apply Changes",
            "  ├─ [bold green][▓▒░][/bold green] [bold]Apply Changes[/bold]",
            id="action-apply"
        )
        yield ClickableLabel(
            "  ├─ [yellow][▓▒░][/yellow] Reset to Defaults",
            "  ├─ [bold yellow][▓▒░][/bold yellow] [bold]Reset to Defaults[/bold]",
            id="action-reset"
        )
        yield ClickableLabel(
            "  └─ [cyan][▓▒░][/cyan] Reload Config",
            "  └─ [bold cyan][▓▒░][/bold cyan] [bold]Reload Config[/bold]",
            id="action-reload"
        )

    def on_mount(self) -> None:
        """Load config on mount"""
        self.load_config()

    def load_config(self) -> None:
        """Load current configuration from bitcoin.conf"""
        self.current_settings = self.config_manager.read_config()
        self.pending_changes = {}
        self.update_display()

    def update_display(self) -> None:
        """Update the settings display"""
        # Get current or pending values
        prune = self.pending_changes.get('prune', self.current_settings.get('prune', '0'))
        maxconn = self.pending_changes.get('maxconnections', self.current_settings.get('maxconnections', '125'))
        dbcache = self.pending_changes.get('dbcache', self.current_settings.get('dbcache', '450'))
        server = self.pending_changes.get('server', self.current_settings.get('server', '0'))

        # Convert prune to GB for display
        if prune == '0':
            prune_display = "Disabled (Full Node)"
        else:
            prune_gb = int(prune) / 1024
            prune_display = f"{prune_gb:.1f} GB"

        # RPC status
        rpc_status = "Enabled" if server == '1' else "Disabled"

        # Build display table
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="left", style="dim green")
        table.add_column(justify="left")
        table.add_column(justify="left", style="dim green")
        table.add_column(justify="left")

        table.add_row(
            "┌─ CURRENT CONFIG",
            "",
            "┌─ PENDING CHANGES",
            f"[yellow]{len(self.pending_changes)}[/yellow]"
        )
        table.add_row("", "", "", "")

        table.add_row(
            "├─ Pruned Mode:",
            f"[cyan]{prune_display}[/cyan]",
            "├─ Config File:",
            "[dim]bitcoin.conf[/dim]"
        )

        table.add_row(
            "├─ Max Connections:",
            f"[cyan]{maxconn}[/cyan]",
            "├─ Node Status:",
            "[green]Running[/green]" if self.controller.is_running() else "[red]Stopped[/red]"
        )

        table.add_row(
            "├─ DB Cache:",
            f"[cyan]{dbcache} MB[/cyan]",
            "",
            ""
        )

        table.add_row(
            "└─ RPC Server:",
            f"[cyan]{rpc_status}[/cyan]",
            "",
            ""
        )

        # Warning if changes pending
        if self.pending_changes:
            table.add_row("", "", "", "")
            table.add_row(
                "[yellow]⚠ Changes pending[/yellow]",
                "[dim]Click 'Apply Changes'[/dim]",
                "",
                ""
            )

        banner_top = "═" * 75
        banner = Text(banner_top, style="dim green")

        content = Table.grid()
        content.add_column(justify="center")
        content.add_row("")
        content.add_row(table)
        content.add_row("")
        content.add_row(banner)
        content.add_row("")

        panel = Panel(content, title="⚙️  Bitcoin Core Configuration", border_style="bold green", padding=(1, 2))

        display_widget = self.query_one("#settings-display", Static)
        display_widget.update(panel)

        # Update option labels to show selected state
        self.update_option_labels()

    def update_option_labels(self) -> None:
        """Update all option labels to show selected state"""
        # Get current or pending values
        prune = self.pending_changes.get('prune', self.current_settings.get('prune', '0'))
        maxconn = self.pending_changes.get('maxconnections', self.current_settings.get('maxconnections', '125'))
        dbcache = self.pending_changes.get('dbcache', self.current_settings.get('dbcache', '450'))
        server = self.pending_changes.get('server', self.current_settings.get('server', '0'))

        # Update Pruned Mode labels
        text_map = {'0': 'Disable (Full Node)', '4096': '4 GB', '10240': '10 GB', '51200': '50 GB'}
        for value in ['0', '4096', '10240', '51200']:
            label = self.query_one(f"#prune-{value}", ClickableLabel)
            is_selected = (prune == value)
            symbol = "███" if is_selected else "▓▒░"
            color = "yellow" if is_selected else "cyan"
            prefix = '├' if value != '51200' else '└'
            text = text_map[value]

            normal = f"  {prefix}─ [{color}][{symbol}][/{color}] {text}"
            hover = f"  {prefix}─ [bold yellow][{symbol}][/bold yellow] [bold]{text}[/bold]"
            label.set_texts(normal, hover)

        # Update Max Connections labels
        for value in ['10', '25', '50', '125']:
            label = self.query_one(f"#maxconn-{value}", ClickableLabel)
            is_selected = (maxconn == value)
            symbol = "███" if is_selected else "▓▒░"
            color = "yellow" if is_selected else "cyan"
            prefix = '├' if value != '125' else '└'
            text = value + (" (default)" if value == '125' else "")

            normal = f"  {prefix}─ [{color}][{symbol}][/{color}] {text}"
            hover = f"  {prefix}─ [bold yellow][{symbol}][/bold yellow] [bold]{text}[/bold]"
            label.set_texts(normal, hover)

        # Update DB Cache labels
        for value in ['300', '450', '1000', '2000']:
            label = self.query_one(f"#dbcache-{value}", ClickableLabel)
            is_selected = (dbcache == value)
            symbol = "███" if is_selected else "▓▒░"
            color = "yellow" if is_selected else "cyan"
            prefix = '├' if value != '2000' else '└'
            text = value + (" (default)" if value == '450' else "")

            normal = f"  {prefix}─ [{color}][{symbol}][/{color}] {text}"
            hover = f"  {prefix}─ [bold yellow][{symbol}][/bold yellow] [bold]{text}[/bold]"
            label.set_texts(normal, hover)

        # Update RPC Server labels
        enable_label = self.query_one("#rpc-enable", ClickableLabel)
        disable_label = self.query_one("#rpc-disable", ClickableLabel)

        enable_selected = (server == '1')
        disable_selected = (server == '0')

        enable_symbol = "███" if enable_selected else "▓▒░"
        disable_symbol = "███" if disable_selected else "▓▒░"
        enable_color = "yellow" if enable_selected else "cyan"
        disable_color = "yellow" if disable_selected else "cyan"

        enable_label.set_texts(
            f"  ├─ [{enable_color}][{enable_symbol}][/{enable_color}] Enable RPC",
            f"  ├─ [bold yellow][{enable_symbol}][/bold yellow] [bold]Enable RPC[/bold]"
        )
        disable_label.set_texts(
            f"  └─ [{disable_color}][{disable_symbol}][/{disable_color}] Disable RPC",
            f"  └─ [bold yellow][{disable_symbol}][/bold yellow] [bold]Disable RPC[/bold]"
        )

    async def on_click(self, event) -> None:
        """Handle label clicks"""
        # Check if a ClickableLabel was clicked
        if not isinstance(event.widget, (Label, ClickableLabel)):
            return

        label_id = event.widget.id

        # Pruned Mode
        if label_id and label_id.startswith("prune-"):
            prune_value = label_id.split("-")[1]
            self.pending_changes['prune'] = prune_value
            self.update_display()

        # Max Connections
        elif label_id and label_id.startswith("maxconn-"):
            maxconn_value = label_id.split("-")[1]
            self.pending_changes['maxconnections'] = maxconn_value
            self.update_display()

        # DB Cache
        elif label_id and label_id.startswith("dbcache-"):
            dbcache_value = label_id.split("-")[1]
            self.pending_changes['dbcache'] = dbcache_value
            self.update_display()

        # RPC Server
        elif label_id == "rpc-enable":
            self.pending_changes['server'] = '1'
            self.update_display()
        elif label_id == "rpc-disable":
            self.pending_changes['server'] = '0'
            self.update_display()

        # Action buttons
        elif label_id == "action-apply":
            self.run_worker(self.apply_changes())
        elif label_id == "action-reset":
            self.run_worker(self.reset_to_defaults())
        elif label_id == "action-reload":
            self.load_config()
            if self.alerts_panel:
                self.alerts_panel.add_alert("Configuration reloaded", "info")

    async def apply_changes(self) -> None:
        """Apply pending changes to bitcoin.conf"""
        if not self.pending_changes:
            if self.alerts_panel:
                self.alerts_panel.add_alert("No changes to apply", "warning")
            return

        # Confirm changes
        change_summary = "\n".join([f"{k}: {v}" for k, v in self.pending_changes.items()])
        confirmed = await self.app.push_screen_wait(
            ConfirmDialog(
                f"Apply these changes to bitcoin.conf?\n\n{change_summary}\n\nThis will create a backup.",
                "apply"
            )
        )

        if not confirmed:
            return

        # Validate all changes
        for key, value in self.pending_changes.items():
            valid, msg = self.config_manager.validate_setting(key, value)
            if not valid:
                if self.alerts_panel:
                    self.alerts_panel.add_alert(f"Validation failed: {msg}", "error")
                return

        # Merge with current settings
        new_settings = {**self.current_settings, **self.pending_changes}

        # Write to file
        success, message = self.config_manager.write_config(new_settings)

        if success:
            if self.alerts_panel:
                self.alerts_panel.add_alert("Configuration saved ✓", "success")

            # Ask if user wants to restart node
            if self.controller.is_running():
                restart = await self.app.push_screen_wait(
                    ConfirmDialog(
                        "Restart the node to apply changes?",
                        "restart"
                    )
                )

                if restart:
                    if self.alerts_panel:
                        self.alerts_panel.add_alert("Restarting node...", "info")

                    # Stop
                    success, _ = await self.controller.stop_node()
                    if success:
                        await self.app.sleep(3)

                    # Start
                    success, msg = await self.controller.start_node()
                    if success:
                        if self.alerts_panel:
                            self.alerts_panel.add_alert("Node restarted ✓", "success")
                    else:
                        if self.alerts_panel:
                            self.alerts_panel.add_alert(f"Failed to start: {msg[:50]}", "error")

            # Reload config
            self.load_config()
        else:
            if self.alerts_panel:
                self.alerts_panel.add_alert(f"Failed: {message}", "error")

    async def reset_to_defaults(self) -> None:
        """Reset configuration to defaults"""
        confirmed = await self.app.push_screen_wait(
            ConfirmDialog(
                "Reset all settings to Bitcoin Core defaults?\n\nThis will create a backup.",
                "reset"
            )
        )

        if not confirmed:
            return

        defaults = self.config_manager.get_default_settings()
        success, message = self.config_manager.write_config(defaults)

        if success:
            if self.alerts_panel:
                self.alerts_panel.add_alert("Reset to defaults ✓", "success")
            self.load_config()
        else:
            if self.alerts_panel:
                self.alerts_panel.add_alert(f"Failed: {message}", "error")


class NodePulseApp(App):
    """Main NodePulse Application"""

    CSS = """
    #home-container, #sync-container, #blockchain-container {
        overflow-y: auto;
        padding: 1;
        align: center top;
    }

    #home-container > Static,
    #sync-container > Static,
    #blockchain-container > Static {
        width: 100%;
        margin-bottom: 1;
    }

    #controls, #settings {
        align: center top;
        padding: 2;
        overflow-y: auto;
    }

    #controls > Static, #settings > Static {
        width: 100%;
        margin-bottom: 1;
    }

    #controls > Label, #settings > Label,
    #controls > ClickableLabel, #settings > ClickableLabel {
        width: 100%;
        padding: 0 2;
    }

    #controls > Label:hover, #settings > Label:hover,
    #controls > ClickableLabel:hover, #settings > ClickableLabel:hover {
        background: $accent-darken-2;
    }

    .section-header {
        width: 100%;
        margin-top: 1;
    }

    #settings-grid {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    .settings-column {
        width: 1fr;
        padding: 0 1;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh Now", show=True),
        Binding("1", "switch_tab('home')", "Dashboard", show=False),
        Binding("2", "switch_tab('sync')", "Sync", show=False),
        Binding("3", "switch_tab('blockchain')", "Blockchain", show=False),
        Binding("4", "switch_tab('controls')", "Controls", show=False),
        Binding("5", "switch_tab('settings')", "Settings", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.bitcoin = BitcoinNodeData()
        self.controller = BitcoinNodeController()
        self.tracker = SyncStatsTracker()
        self.config_manager = BitcoinConfigManager()

        # Panels - will be created in compose
        self.dashboard_panel = None
        self.sync_panel = None
        self.sync_stats_panel = None
        self.alerts_panel = None
        self.recent_blocks_panel = None
        self.network_panel = None
        self.storage_panel = None
        self.mempool_panel = None
        self.controls_panel = None
        self.settings_panel = None

        # State tracking
        self.last_peer_count = None
        self.last_blocks = None
        self.node_was_responsive = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with TabbedContent():
            # Tab 1: Dashboard (Welcome screen)
            with TabPane("1 Dashboard", id="home"):
                with ScrollableContainer(id="home-container"):
                    yield DashboardPanel()

            # Tab 2: Sync (Synchronization status)
            with TabPane("2 Sync", id="sync"):
                with ScrollableContainer(id="sync-container"):
                    yield SyncPanel()
                    yield SyncStatsPanel()
                    yield AlertsPanel()

            # Tab 3: Blockchain (Network and mempool info)
            with TabPane("3 Blockchain", id="blockchain"):
                with ScrollableContainer(id="blockchain-container"):
                    yield RecentBlocksPanel()
                    yield NetworkPanel()
                    yield StoragePanel()
                    yield MempoolPanel()

            # Tab 4: Controls (Node management)
            with TabPane("4 Controls", id="controls"):
                yield ControlsPanel(self.controller, None)

            # Tab 5: Settings (Configuration management)
            with TabPane("5 Settings", id="settings"):
                yield SettingsPanel(self.config_manager, self.controller, None)

        yield Footer()

    def on_mount(self) -> None:
        self.title = "NodePulse - Bitcoin Core Dashboard"
        self.sub_title = "v1.3 - Dashboard + Monitoring + Controls"

        # Get references to panels after they're mounted
        self.dashboard_panel = self.query_one(DashboardPanel)
        self.sync_panel = self.query_one(SyncPanel)
        self.sync_stats_panel = self.query_one(SyncStatsPanel)
        self.alerts_panel = self.query_one(AlertsPanel)
        self.recent_blocks_panel = self.query_one(RecentBlocksPanel)
        self.network_panel = self.query_one(NetworkPanel)
        self.storage_panel = self.query_one(StoragePanel)
        self.mempool_panel = self.query_one(MempoolPanel)
        self.controls_panel = self.query_one(ControlsPanel)
        self.settings_panel = self.query_one(SettingsPanel)

        # Update controls and settings panels with alerts reference
        self.controls_panel.alerts_panel = self.alerts_panel
        self.settings_panel.alerts_panel = self.alerts_panel

        self.alerts_panel.add_alert("NodePulse v1.3 started", "success")
        self.run_worker(self.refresh_data(), exclusive=True)
        self.set_interval(10, lambda: self.run_worker(self.refresh_data(), exclusive=True))

    async def refresh_data(self) -> None:
        """Refresh node data using async calls and parallelization"""
        # Get active tab to only update visible panels
        tabbed_content = self.query_one(TabbedContent)
        active_tab = tabbed_content.active

        node_running = self.controller.is_running()

        # Parallelize main RPC calls
        blockchain_info, network_info, peer_info, mempool_info, uptime = await asyncio.gather(
            self.bitcoin.get_blockchain_info(),
            self.bitcoin.get_network_info(),
            self.bitcoin.get_peer_info(),
            self.bitcoin.get_mempool_info(),
            self.bitcoin.get_uptime(),
            return_exceptions=True
        )

        # Handle exceptions
        if isinstance(blockchain_info, Exception):
            blockchain_info = None
        if isinstance(network_info, Exception):
            network_info = None
        if isinstance(peer_info, Exception):
            peer_info = None
        if isinstance(mempool_info, Exception):
            mempool_info = None
        if isinstance(uptime, Exception):
            uptime = 0

        # Always update Dashboard panel (visible on 'home' tab)
        if active_tab == "home":
            self.dashboard_panel.update_data(node_running, blockchain_info, network_info, uptime)

        if blockchain_info is None:
            if self.node_was_responsive:
                self.alerts_panel.add_alert("Node not responding!", "error")
                self.node_was_responsive = False
            return
        else:
            if not self.node_was_responsive:
                self.alerts_panel.add_alert("Node connection restored", "success")
                self.node_was_responsive = True

        blocks = blockchain_info.get("blocks", 0)
        headers = blockchain_info.get("headers", 0)
        is_syncing = blockchain_info.get("initialblockdownload", False)

        sync_completed = self.tracker.update(blocks, headers, is_syncing)
        if sync_completed:
            self.alerts_panel.add_alert("Blockchain sync completed! 🎉", "success")

        if network_info:
            peer_count = network_info.get("connections", 0)
            if self.last_peer_count is not None:
                if peer_count < 3 and self.last_peer_count >= 3:
                    self.alerts_panel.add_alert(f"Low peer count: {peer_count}", "warning")
                elif peer_count >= 3 and self.last_peer_count < 3:
                    self.alerts_panel.add_alert(f"Peer count recovered: {peer_count}", "success")
            self.last_peer_count = peer_count

        # Only update panels if their tab is active
        if active_tab == "sync":
            if blockchain_info:
                self.sync_panel.update_data(blockchain_info)
                self.sync_stats_panel.update_data(self.tracker, blockchain_info)

        if active_tab == "blockchain":
            # Parallelize fee estimates
            fee_estimates_data = await asyncio.gather(
                self.bitcoin.estimate_smart_fee(1),
                self.bitcoin.estimate_smart_fee(3),
                self.bitcoin.estimate_smart_fee(6),
                return_exceptions=True
            )
            fee_estimates = {
                1: fee_estimates_data[0] if not isinstance(fee_estimates_data[0], Exception) else None,
                3: fee_estimates_data[1] if not isinstance(fee_estimates_data[1], Exception) else None,
                6: fee_estimates_data[2] if not isinstance(fee_estimates_data[2], Exception) else None
            }

            if blockchain_info:
                self.storage_panel.update_data(blockchain_info)

                if not hasattr(self, '_block_refresh_counter'):
                    self._block_refresh_counter = 0
                self._block_refresh_counter += 1
                if self._block_refresh_counter % 3 == 0:  # Reduced frequency
                    await self.recent_blocks_panel.update_data(self.bitcoin, blocks)

            if network_info:
                self.network_panel.update_data(network_info, peer_info)

            if mempool_info:
                self.mempool_panel.update_data(mempool_info, fee_estimates)

    def action_refresh(self) -> None:
        self.alerts_panel.add_alert("Manual refresh triggered", "info")
        self.run_worker(self.refresh_data(), exclusive=True)

    def action_switch_tab(self, tab_id: str) -> None:
        """Switch to a specific tab"""
        tabbed_content = self.query_one(TabbedContent)
        tabbed_content.active = tab_id


def main():
    """Entry point for NodePulse"""
    app = NodePulseApp()
    app.run()


if __name__ == "__main__":
    main()
