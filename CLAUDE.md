# NodePulse - Claude Development Documentation

This document provides technical context for AI assistants and developers working on NodePulse.

## Project Overview

**NodePulse** is a Terminal User Interface (TUI) application for monitoring and controlling Bitcoin Core nodes in real-time. Built with Python and Textual, it provides an intuitive dashboard for node operators.

**Current Version:** 1.3.0
**Development Period:** October 19-20, 2025
**Platform:** macOS 12.7.6 (compatible with Python 3.9+)
**Bitcoin Core Version:** 30.0 (command-line only)

## Architecture

### Technology Stack

- **Textual 6.3.0** - Modern TUI framework (reactive UI, CSS-like styling)
- **Rich 14.2.0** - Terminal text rendering and formatting
- **psutil 7.1.1** - Cross-platform process detection
- **Bitcoin Core RPC** - Communication via `bitcoin-cli`

### Project Structure

```
~/Desktop/NodePulse/
├── src/
│   └── nodepulse.py          # Main application (~1700 lines)
├── config/                    # Reserved for future config files
├── docs/
│   └── QUICKSTART.md         # Quick start guide
├── requirements.txt           # Python dependencies
├── README.md                  # User documentation
└── CLAUDE.md                  # This file

~/bin/
└── nodepulse                  # Launcher script (sets ulimit)
```

### Code Architecture

**Main Components:**

1. **BitcoinNodeData** (Lines ~135-172)
   - Handles all RPC communication with Bitcoin Core
   - Methods: `get_blockchain_info()`, `get_network_info()`, `get_peer_info()`, etc.
   - Uses `bitcoin-cli` subprocess calls with JSON parsing

2. **BitcoinNodeController** (Lines ~73-133)
   - Controls bitcoind daemon (start/stop/restart)
   - Process detection using `psutil`
   - Handles `ulimit -n 4096` for file descriptor limits

3. **BitcoinConfigManager** (Lines ~181-307) **[NEW in v1.3]**
   - Reads and writes bitcoin.conf configuration file
   - Validates configuration settings
   - Creates backups before making changes
   - Handles default values for all settings

4. **SyncStatsTracker** (Lines ~174-242)
   - Tracks sync metrics over time using `deque(maxlen=60)`
   - Calculates blocks/hour and ETA
   - Detects sync completion events

5. **ClickableLabel** (Lines ~380-407) **[NEW in v1.3]**
   - Custom widget extending Label
   - Dual-state text (normal and hover)
   - Color change on hover (cyan → yellow + bold)
   - Used for all interactive buttons throughout the UI

6. **Panel Classes** (Lines ~371-1092)
   - `DashboardPanel` - Retro/terminal style welcome screen with navigation menu
   - `SyncPanel` - Blockchain sync status with progress bar
   - `SyncStatsPanel` - Sync speed and ETA calculations
   - `AlertsPanel` - Visual notifications with color coding
   - `RecentBlocksPanel` - Last 5 blocks with details
   - `NetworkPanel` - Peer connections and versions
   - `StoragePanel` - Disk usage for pruned nodes
   - `MempoolPanel` - Transaction pool and fee estimates
   - `ControlsPanel` - Interactive node controls with ClickableLabels
   - `SettingsPanel` - Bitcoin Core configuration editor **[NEW in v1.3]**

7. **ConfirmDialog** (Lines ~26-71)
   - Modal screen for dangerous operations (stop/restart)
   - Prevents accidental node shutdowns

8. **NodePulseApp** (Lines ~1520-1700+)
   - Main application class
   - Tabbed interface (5 tabs: Dashboard, Sync, Blockchain, Controls, Settings)
   - Auto-refresh every 5 seconds
   - Data aggregation and panel updates

### Data Flow

```
bitcoind (running)
    ↓
bitcoin-cli (RPC calls)
    ↓
BitcoinNodeData.run_command()
    ↓
NodePulseApp.refresh_data() [every 5s]
    ↓
Panel.update_data()
    ↓
Panel.update_render()
    ↓
Textual renders to terminal
```

## Critical Problems Solved

### Problem 1: Widget Rendering Issues (Major)

**Symptom:** All panels showed empty/black on both Dashboard and Controls tabs despite no errors.

**Root Cause:** CSS conflict with `height: 100%` causing Textual to miscalculate widget heights. Widgets were being created but rendered with 0 height.

**Solution Path:**
1. Created test apps to isolate the issue
2. Discovered that simple static widgets worked, but NodePulse panels didn't
3. Removed all CSS → panels appeared
4. Identified problematic CSS properties: `height: 100%`, complex nested selectors
5. Rewrote CSS with minimal rules focusing on margins and width only

**Final CSS (Lines 719-745):**
```css
#dashboard-container {
    overflow-y: auto;
    padding: 1;
}

.row {
    width: 100%;
    height: auto;  /* NOT 100% */
    margin-bottom: 1;
}

.row > Static {
    width: 1fr;
    margin: 0 1;
}
```

**Key Lesson:** Avoid `height: 100%` in Textual CSS. Use `height: auto` and let Textual calculate heights based on content.

### Problem 2: Async Button Handler Error

**Symptom:**
```
NoActiveWorker: push_screen must be run from a worker when `wait_for_dismiss` is True
```

**Root Cause:** Modal dialogs (`push_screen_wait`) require a worker context in Textual, but event handlers run in the main event loop.

**Solution:**
Changed from:
```python
async def on_button_pressed(self, event):
    await self.stop_node()
```

To:
```python
def on_button_pressed(self, event):
    self.run_worker(self.stop_node())
```

**Location:** Lines 290-308 in `ControlsPanel`

### Problem 3: Panel Initialization Timing

**Initial Approach (Failed):**
```python
def __init__(self):
    self.sync_panel = SyncPanel()  # Created too early

def compose(self):
    yield self.sync_panel  # Already created
```

**Issue:** Widgets created before `compose()` weren't properly mounted.

**Final Solution:**
```python
def compose(self):
    yield SyncPanel()  # Create directly in yield

def on_mount(self):
    self.sync_panel = self.query_one(SyncPanel)  # Get reference after mount
```

**Location:** Lines 757-833

### Problem 4: Bitcoin Core Compatibility

**Challenge:** macOS 12.7.6 incompatible with Bitcoin-Qt GUI (requires macOS 13.0+)

**Solution:** Extracted command-line binaries from `.tar.gz`:
- `bitcoind` (daemon)
- `bitcoin-cli` (RPC client)
- Installed to `~/bin/`
- These binaries work on older macOS versions

### Problem 5: File Descriptor Limits

**Error:** `Not enough file descriptors available. -1 available, 160 required`

**Solution:** Set `ulimit -n 4096` in:
1. Launcher script: `~/bin/nodepulse`
2. Start node function: `BitcoinNodeController.start_node()`

## Version 1.3 Features

### New UI Design - Retro/Terminal Aesthetic

**Replaced:** Large ASCII art logo with compact retro style
**New Design Elements:**
- Compact ASCII logo using `░▒▓█` block characters
- Matrix-style color scheme (green/cyan/yellow)
- Banner borders with box drawing characters (`╔═══...═══╗`)
- Vertical navigation menu (one tab per line)
- ASCII-style interactive controls with `[▓▒░]` markers

**DashboardPanel** (Lines ~525-680):
```
░▒▓█  █▄  █  ████  █▀▄  █▀▀  █▀█  █  █  █    ▄▀▀  █▀▀  █▓▒░
░▒▓█  █ ▀▄█  █  █  █ █  █▀   █▀▀  █  █  █     ▀▄  █▀   █▓▒░
░▒▓█  █   █  ████  ▀▀   ▀▀▀  ▀    ▀▀▀   ▀▀▀  ▀▀   ▀▀▀  █▓▒░
```

### Settings Tab - Bitcoin Core Configuration

**New Tab:** Settings (Tab 5)
**Features:**
- Edit bitcoin.conf settings directly from the UI
- Configuration options:
  - Pruned Mode (Disable/4GB/10GB/50GB)
  - Max Connections (10/25/50/125)
  - DB Cache (300/450/1000/2000 MB)
  - RPC Server (Enable/Disable)
- Live preview of current and pending changes
- Apply/Reset/Reload functionality
- Automatic backup before changes
- Restart node option with confirmation
- 2-column grid layout for efficient space usage

**SettingsPanel** (Lines ~1093-1520):
- Inherits from `ScrollableContainer` for proper rendering
- Uses `ClickableLabel` widgets for all options
- Integrates with `BitcoinConfigManager` for safe config editing
- Modal confirmations for critical operations

### ClickableLabel Widget

**Custom Widget:** Replaces Button widgets throughout the app
**Features:**
- Dual-state text (normal and hover)
- Color transitions: cyan → yellow + bold
- Background change on hover
- Consistent ASCII style with brackets: `[▓▒░]`

**Implementation:**
```python
class ClickableLabel(Label):
    def on_enter(self) -> None:
        # Change to yellow + bold

    def on_leave(self) -> None:
        # Return to cyan normal
```

**Used in:**
- ControlsPanel (Start/Stop/Restart/Refresh/Clear Alerts)
- SettingsPanel (All configuration options + action buttons)

### 5-Tab Interface

**Navigation:**
1. **Dashboard** - Welcome screen with retro design + navigation menu
2. **Sync** - Blockchain sync status, stats, and alerts
3. **Blockchain** - Network, storage, mempool info
4. **Controls** - Node management (start/stop/restart)
5. **Settings** - Bitcoin Core configuration editor

**Keyboard Shortcuts:**
- `1-5` - Switch to respective tabs
- `q` - Quit
- `r` - Refresh now

**Footer:** Only shows `q Quit` and `r Refresh` (tab navigation hidden)

### Problem 6: Settings Panel Rendering (v1.3)

**Initial Issue:** Action buttons (Apply Changes, Reset to Defaults, Reload Config) not visible in Settings tab

**Attempts:**
1. Added `ScrollableContainer` wrapper → caused double scroll bars
2. Removed container → buttons still invisible
3. Changed `SettingsPanel` from `Static` to `ScrollableContainer` → ✅ Fixed

**Root Cause:** `Static` widgets don't expand to fit all children when content exceeds viewport

**Solution:** Changed base class from `Static` to `ScrollableContainer`
```python
class SettingsPanel(ScrollableContainer):  # Was Static
```

**Layout Optimization:**
- Removed unnecessary `Static("")` spacers
- Added `margin-bottom: 1` to grid CSS
- Set `height: auto` on columns
- Result: Compact, elegant layout with all buttons visible

## Design Decisions

### Why Textual?

**Alternatives Considered:**
- Web interface (Flask/FastAPI + React) - Too heavy for simple monitoring
- GUI (PyQt/Tkinter) - Not suitable for server environments
- Simple CLI output - No real-time updates, poor UX

**Textual Benefits:**
- Works over SSH
- Low resource usage
- Reactive updates
- Rich text formatting
- CSS-like styling

### Why Pruned Node (4GB)?

User requirement for disk space management. Configured with `prune=4096` in `bitcoin.conf`.

### Dashboard Layout: 2-Column Grid

**Rationale:**
- Maximizes information density
- Natural reading flow (left to right, top to bottom)
- Most panels fit well in ~50% width
- Mempool gets full width (more data to display)

### Auto-Refresh Interval: 5 Seconds

**Considerations:**
- Fast enough: Feels responsive
- Not too fast: Avoids spamming RPC calls
- Battery/CPU friendly
- User can manually refresh with `r` key

### Alert System Color Coding

- 🟢 **Green (Success):** Positive events (sync complete, peers recovered)
- 🟡 **Yellow (Warning):** Attention needed (low peers)
- 🔴 **Red (Error):** Problems (node not responding)
- 🔵 **Cyan (Info):** Informational messages

## Code Patterns

### Panel Update Pattern

All panels follow this pattern:

```python
class ExamplePanel(Static):
    def __init__(self):
        super().__init__("⚠️  Waiting for data...")
        self.data = None

    def update_data(self, new_data):
        """Called by NodePulseApp.refresh_data()"""
        self.data = new_data
        self.update_render()

    def update_render(self):
        """Generates Rich Panel and updates display"""
        if not self.data:
            self.update("⚠️  Waiting for data...")
            return

        table = Table.grid(padding=(0, 2))
        # ... build table ...

        panel = Panel(table, title="Title", border_style="color")
        self.update(panel)
```

### RPC Call Pattern

```python
def run_command(self, *args):
    try:
        cmd = [self.bitcoin_cli] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return json.loads(result.stdout)
        return None
    except Exception:
        return None
```

**Error Handling:** Silent failures return `None`. Calling code checks for `None` and displays "Waiting..." or error alerts.

## Configuration

### Bitcoin Core Configuration

**File:** `~/Library/Application Support/Bitcoin/bitcoin.conf`

```
# Bitcoin Core Configuration
# Nodo podado a 4GB

# Habilita el modo de poda y establece el límite a 4096 MB (4 GB)
prune=4096
```

### Environment Setup

**PATH Configuration (`~/.zshrc`):**
```bash
export PATH="$HOME/bin:$PATH"
```

**Launcher Script (`~/bin/nodepulse`):**
```bash
#!/bin/bash
NODEPULSE_DIR="$HOME/Desktop/NodePulse/src"
PYTHON3=$(which python3)
ulimit -n 4096 2>/dev/null
exec "$PYTHON3" "$NODEPULSE_DIR/nodepulse.py" "$@"
```

## Performance Considerations

### Memory Usage

- **Base app:** ~40-60 MB
- **With history tracking:** ~80-100 MB (60 data points × 7 panels)
- **Peak:** ~150 MB during block processing

### CPU Usage

- **Idle:** <1% CPU
- **During refresh:** 2-5% CPU spike (RPC calls + rendering)
- **Average:** ~1-2% CPU sustained

### Network Usage

RPC calls every 5 seconds:
- `getblockchaininfo` (~1 KB)
- `getnetworkinfo` (~0.5 KB)
- `getpeerinfo` (~5-10 KB depending on peers)
- `getmempoolinfo` (~0.5 KB)
- `estimatesmartfee` × 3 (~1.5 KB)
- `getblockhash` + `getblock` × 5 (~25 KB, only every 25 seconds)

**Total:** ~30-40 KB every 5 seconds = ~6-8 KB/s average

## Testing Approach

### Test Files Created

1. **test_textual.py** - Basic Textual functionality test
2. **test_custom_static.py** - Custom Static widget test with Rich Panels
3. **test_nodepulse_exact.py** - Replicate NodePulse structure
4. **test_real_panels.py** - Import actual NodePulse panels

**Testing Strategy:**
1. Start with simplest possible test (Hello World)
2. Gradually add complexity (tabs, containers, custom widgets)
3. Import real components to isolate issues
4. Compare working vs broken versions to identify differences

## Future Development Considerations

### For Version 1.4

**NodePulse Configuration File:**
- TOML format (`config/nodepulse.toml`)
- Settings: refresh_interval, theme, alert_thresholds, custom_rpc_calls
- Load in `NodePulseApp.__init__()`

**Custom Refresh Interval:**
- Add to Settings tab
- Validate: minimum 1 second, maximum 60 seconds
- Update `set_interval()` call dynamically

**Color Themes:**
- Textual supports theme switching
- Create theme files: `themes/dark.css`, `themes/light.css`, `themes/matrix.css`
- Add to Settings tab with live preview

**Stats Export:**
- Add "Export Stats" button to Settings tab
- Format: CSV or JSON
- Include: timestamp, blocks, peers, mempool size, fees, sync speed
- Use Python's `csv` or `json` modules

**Advanced Bitcoin Core Settings:**
- Expand Settings tab with more options:
  - `blocksonly`, `listen`, `upnp`, `txindex`
  - Network settings (port, bind address)
  - RPC authentication (rpcuser, rpcpassword)

### For Version 2.0

**Multi-Node Support:**
- Config: `[[nodes]]` array with multiple node configs
- UI: Dropdown or tabs to switch between nodes
- Data: Separate `BitcoinNodeData` instances per node

**Historical Charts:**
- Use Textual's `PlotExt` widget or ASCII art
- Track: blocks/hour over time, peer count over time
- Storage: SQLite or JSON file

**Web Interface:**
- Backend: Keep NodePulse as core, add FastAPI wrapper
- Frontend: Simple dashboard using Chart.js
- WebSocket: Real-time updates
- Authentication: Basic auth or API keys

## Common Issues & Solutions

### Issue: "command not found: nodepulse"

**Solution:**
```bash
source ~/.zshrc  # Reload PATH
# or
export PATH="$HOME/bin:$PATH"
```

### Issue: "Node not responding!" alert

**Causes:**
1. bitcoind not running → Start with "Start Node" button
2. bitcoind still loading → Wait 10-30 seconds
3. RPC port blocked → Check firewall
4. bitcoin-cli path wrong → Verify `~/bin/bitcoin-cli` exists

### Issue: Panels show "Waiting for data..." indefinitely

**Diagnosis:**
```bash
~/bin/bitcoin-cli getblockchaininfo
```

If this fails, NodePulse can't get data either.

### Issue: High CPU usage

**Possible causes:**
1. Too many RPC calls → Check refresh interval
2. Large peer count → `getpeerinfo` returns lots of data
3. Memory leak → Check for growing memory usage over time

**Solution:** Restart NodePulse, consider increasing refresh interval.

## Bitcoin Core RPC Reference

### Commands Used by NodePulse

| Command | Frequency | Purpose | Data Size |
|---------|-----------|---------|-----------|
| `getblockchaininfo` | Every 5s | Sync status, blocks, headers | ~1 KB |
| `getnetworkinfo` | Every 5s | Peer count, version | ~0.5 KB |
| `getpeerinfo` | Every 5s | Individual peer details | ~5-10 KB |
| `getmempoolinfo` | Every 5s | Transaction pool stats | ~0.5 KB |
| `estimatesmartfee 1` | Every 5s | Fee estimate for 1 block | ~0.5 KB |
| `estimatesmartfee 3` | Every 5s | Fee estimate for 3 blocks | ~0.5 KB |
| `estimatesmartfee 6` | Every 5s | Fee estimate for 6 blocks | ~0.5 KB |
| `getblockhash <height>` | Every 25s | Block hash for height | ~0.1 KB |
| `getblock <hash>` | Every 25s | Block details (5 blocks) | ~5 KB each |
| `uptime` | Every 2s | Node uptime in seconds | ~10 bytes |
| `stop` | Manual | Stop bitcoind daemon | ~50 bytes |

### Important Fields

**From `getblockchaininfo`:**
- `blocks` - Current block count
- `headers` - Total headers received
- `verificationprogress` - Chainwork-based sync progress (0.0 to 1.0)
- `initialblockdownload` - Boolean, true if syncing
- `pruned` - Boolean, true if pruned node
- `prune_target_size` - Pruning limit in bytes
- `size_on_disk` - Total blockchain size in bytes

**From `getnetworkinfo`:**
- `connections` - Total peer count
- `connections_in` - Inbound peers
- `connections_out` - Outbound peers
- `subversion` - Node version string

**From `getmempoolinfo`:**
- `size` - Transaction count
- `bytes` - Mempool size in bytes
- `usage` - Memory usage in bytes
- `maxmempool` - Max memory limit

## Keyboard Shortcuts

| Key | Action | Implementation |
|-----|--------|----------------|
| `q` | Quit NodePulse | Textual built-in |
| `r` | Refresh data now | Calls `refresh_data()` |
| `1` | Switch to Dashboard | `switch_tab('home')` |
| `2` | Switch to Sync | `switch_tab('sync')` |
| `3` | Switch to Blockchain | `switch_tab('blockchain')` |
| `4` | Switch to Controls | `switch_tab('controls')` |
| `5` | Switch to Settings | `switch_tab('settings')` |

**Location:** `BINDINGS` list at lines ~1578-1585
**Note:** Tab navigation bindings are hidden from footer (show=False), only `q` and `r` are visible

## Error Messages

### User-Facing Alerts

- "NodePulse v1.2 started" - App initialized successfully
- "Node not responding!" - RPC calls failing
- "Node connection restored" - RPC calls working again
- "Low peer count: X" - Less than 3 peers connected
- "Peer count recovered: X" - Back to 3+ peers
- "Blockchain sync completed! 🎉" - IBD finished
- "Manual refresh triggered" - User pressed 'r'
- "Node started successfully ✓" - bitcoind launched
- "Node stopped successfully ✓" - bitcoind shutdown
- "Failed to start node: <error>" - Start command failed
- "Node is already running" - Tried to start when running
- "Node is not running" - Tried to stop when not running

### Technical Errors (Should Not Appear to User)

These indicate bugs if seen:
- `AttributeError: 'NoneType' object has no attribute 'add_alert'` - Panel reference is None
- `NoActiveWorker: push_screen must be run from a worker` - Async context issue
- Widget rendering as empty - CSS height conflicts

## Development Environment

**System:** macOS 12.7.6 (Darwin 21.6.0)
**Python:** 3.9+
**Shell:** zsh
**Terminal:** Any with 256-color support
**Bitcoin Core:** 30.0 (command-line tools only)

## Special Considerations

### Why verificationprogress vs blocks?

User asked: "If 220,239/919,845 blocks synced, why does it show 0.99% progress?"

**Answer:**
- `blocks` = Simple count of blocks downloaded
- `verificationprogress` = Chainwork-based progress (more accurate)
- Early blocks (2009-2012) have low difficulty → fast to verify
- Recent blocks (2024+) have high difficulty → slow to verify
- 1% chainwork ≠ 1% blocks, especially early in sync
- Block 220,239 might only represent 1% of total chainwork

### Pruned Node Behavior

- Keeps recent blocks + headers
- Deletes old block data when exceeding prune limit
- `prune_target_size` = 4096 MB = 4 GB
- Actual usage may fluctuate around limit
- `size_on_disk` shows current usage
- Pruned nodes can't serve old blocks to peers (lower connections_in)

## Credits & Attribution

**Built with:**
- [Textual](https://github.com/Textualize/textual) by Textualize
- [Rich](https://github.com/Textualize/rich) by Textualize
- [psutil](https://github.com/giampaolo/psutil) by Giampaolo Rodola
- [Bitcoin Core](https://bitcoincore.org/) - The Bitcoin reference implementation

**Developed by:** Gabriel VF
**AI Assistant:** Claude (Anthropic)
**Development Date:** October 19-20, 2025

---

**For questions or issues:** See README.md troubleshooting section or review this document for technical context.
