# electron-pet Codebase

## Commands

```bash
npm start          # Run in development
npm run build:mac  # Build macOS app
```

## File Structure

```
electron-pet/
├── main.js         # Main process - window management, IPC handlers
├── stateManager.js # State machine - behavior states and transitions
├── preload.js      # IPC bridge - exposes APIs to renderer
├── package.json    # Dependencies, scripts, build config
├── renderer/
│   ├── index.html  # DOM structure
│   ├── styles.css  # Transparent window styling
│   └── app.js      # Drag logic, GIF loading, state triggers
└── assets/         # Symlink → ../output/pets
```

## StateManager Module (stateManager.js)

Decoupled state machine for pet behaviors. Manages state transitions and GIF mappings.

**State Configuration (STATE_CONFIG):**

| State | GIF | Future Properties |
|-------|-----|-------------------|
| `idle` | idle.gif | duration, transitions, sound (placeholders) |
| `dragged` | float.gif | duration, transitions, sound (placeholders) |

**StateManager Class:**

| Method | Purpose |
|--------|---------|
| `constructor(initialState)` | Initialize with state (default: 'idle') |
| `getCurrentState()` | Returns current state name |
| `getCurrentGif()` | Returns GIF filename for current state |
| `setState(newState)` | Transition to new state, returns GIF filename, throws on invalid state |
| `hasState(state)` | Check if state exists |
| `getAvailableStates()` | Returns array of all state names |
| `getStateConfig(state)` | Returns full config object for a state |

## Main Process (main.js)

Entry point. Creates transparent frameless window, manages StateManager, and handles IPC.

**Key Functions:**

| Function | Purpose |
|----------|---------|
| `createWindow()` | Creates BrowserWindow with transparent, frameless, always-on-top config |
| `loadPosition()` | Reads saved position from `userData/position.json` |
| `savePosition(x, y)` | Writes position to `userData/position.json` |
| `getConfigPath()` | Returns path to position config file |

**State Management:**
```javascript
stateManager = new StateManager('idle');  // Initialized in app.whenReady()
```

**IPC Handlers:**

| Channel | Type | Purpose |
|---------|------|---------|
| `get-gif-path` | handle | Returns path to current state's GIF (state-aware) |
| `move-window` | on | Moves window to `{x, y}` coordinates |
| `save-position` | on | Persists position to config file |
| `change-state` | on | Changes pet state, replies with `state-changed` event |
| `get-current-state` | handle | Returns `{state, gif}` object |

**Window Config:**
```javascript
{
  width: 200, height: 200,
  transparent: true,
  frame: false,
  alwaysOnTop: true,
  resizable: false,
  skipTaskbar: true,
  contextIsolation: true
}
```

## Preload Script (preload.js)

Secure bridge between main and renderer. Uses `contextBridge` to expose limited API.

**Exposed API (`window.electronAPI`):**

| Method | Purpose |
|--------|---------|
| `getGifPath()` | Returns Promise<string> with GIF file path |
| `moveWindow(x, y)` | Sends move-window IPC message |
| `savePosition(x, y)` | Sends save-position IPC message |
| `changeState(state)` | Sends change-state IPC message |
| `onStateChanged(callback)` | Listens for state-changed events, callback receives `{state, gifPath}` |
| `getCurrentState()` | Returns Promise<{state, gif}> with current state info |

## Renderer (renderer/)

### index.html
Minimal DOM structure:
```html
<div id="pet-container">
  <img id="pet-gif" draggable="false">
</div>
```

### styles.css
- Transparent background (`background: transparent`)
- Cursor states: `grab` default, `grabbing` when dragging
- User-select disabled to prevent text selection during drag

### app.js

**State Variables:**
```javascript
let isDragging = false;
let mouseOffsetX = 0;  // Mouse offset from window top-left
let mouseOffsetY = 0;
```

**Key Functions:**

| Function | Purpose |
|----------|---------|
| `loadGif()` | Fetches GIF path via IPC, sets `img.src` |
| `handleMouseDown(event)` | Starts drag, records mouse offset, adds `.dragging` class, changes state to 'dragged' |
| `handleMouseMove(event)` | Calculates new position, calls `moveWindow()` |
| `handleMouseUp(event)` | Ends drag, saves position, changes state to 'idle' |

**Event Listeners:**
- `mousedown` on `#pet-container` → start drag, trigger 'dragged' state
- `mousemove` on `document` → move during drag (document-level for smooth tracking)
- `mouseup` on `document` → end drag, trigger 'idle' state (document-level to catch release anywhere)
- `contextmenu` → prevented (no right-click menu)
- `onStateChanged` → updates `petGif.src` when state changes

## Logic Pipeline

### App Startup
```
app.whenReady()
  → stateManager = new StateManager('idle')
  → createWindow()
    → new BrowserWindow(config)
    → loadPosition() → read position.json
    → win.setPosition(x, y)
    → win.loadFile('renderer/index.html')
      → DOMContentLoaded
        → loadGif()
          → electronAPI.getGifPath()
            → IPC → main.js → stateManager.getCurrentGif() → 'idle.gif'
          → set img.src
```

### Drag Operation with State Changes
```
mousedown on #pet-container
  → isDragging = true
  → record mouseOffsetX/Y (event.clientX/Y)
  → add .dragging class
  → electronAPI.changeState('dragged')
    → IPC → main.js → stateManager.setState('dragged') → 'float.gif'
      → event.reply('state-changed', {state: 'dragged', gifPath: '...'})
        → renderer onStateChanged → petGif.src = 'float.gif'

mousemove (while isDragging)
  → calculate: newX = screenX - offsetX, newY = screenY - offsetY
  → electronAPI.moveWindow(newX, newY)
    → IPC → main.js → win.setPosition(x, y)

mouseup
  → isDragging = false
  → remove .dragging class
  → electronAPI.savePosition(finalX, finalY)
    → IPC → main.js → savePosition() → write position.json
  → electronAPI.changeState('idle')
    → IPC → main.js → stateManager.setState('idle') → 'idle.gif'
      → event.reply('state-changed', {state: 'idle', gifPath: '...'})
        → renderer onStateChanged → petGif.src = 'idle.gif'
```

## Data Storage

**Position config:**
- Path: `~/Library/Application Support/electron-pet/position.json`
- Format: `{"x": 100, "y": 200}`
- Read on startup, written on drag end

## Extension Points

**Add new state:**
1. `stateManager.js`: Add state to STATE_CONFIG with GIF filename
2. Trigger with `electronAPI.changeState('newState')` from renderer or main

**Add new IPC handler:**
1. `main.js`: Add `ipcMain.handle()` or `ipcMain.on()`
2. `preload.js`: Expose method via `contextBridge`
3. `app.js`: Call `window.electronAPI.newMethod()`

**Replace StateManager with AI agent:**
1. Create `AIStateManager extends StateManager` with custom logic
2. Replace `new StateManager()` in main.js
3. IPC handlers unchanged (same interface)

**Add right-click menu:**
1. `main.js`: Create `Menu` with items, show on IPC
2. `preload.js`: Expose `showContextMenu()`
3. `app.js`: Call on `contextmenu` event instead of preventing
