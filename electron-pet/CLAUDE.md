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
├── wanderManager.js # Autonomous movement - wander behavior controller
├── preload.js      # IPC bridge - exposes APIs to renderer
├── package.json    # Dependencies, scripts, build config
├── renderer/
│   ├── index.html  # DOM structure
│   ├── styles.css  # Transparent window styling
│   └── app.js      # Drag logic, GIF loading, state triggers, wander controls
└── assets/         # Symlink → ../output/pets
```

## StateManager Module (stateManager.js)

Decoupled state machine for pet behaviors. Manages state transitions and GIF mappings.

**State Configuration (STATE_CONFIG):**

| State | GIF | Future Properties |
|-------|-----|-------------------|
| `idle` | idle.gif | duration, transitions, sound (placeholders) |
| `dragged` | float.gif | duration, transitions, sound (placeholders) |
| `wander` | hop.gif | duration, transitions, sound (placeholders) |

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

## WanderManager Module (wanderManager.js)

Autonomous movement controller for pet wandering behavior. Manages timer-based random movement with smooth linear interpolation and screen boundary constraints.

**Configuration (WANDER_CONFIG):**

| Setting | Value | Purpose |
|---------|-------|---------|
| `minInterval` | 3000 ms | Minimum delay between movements |
| `maxInterval` | 8000 ms | Maximum delay between movements |
| `minDistance` | 100 px | Minimum movement distance |
| `maxDistance` | 300 px | Maximum movement distance |
| `fps` | 60 | Animation frame rate |
| `speed` | 150 px/s | Movement speed |

**WanderManager Class:**

| Method | Purpose |
|--------|---------|
| `constructor(window, onStateChange)` | Initialize with BrowserWindow and state change callback |
| `start()` | Begin autonomous wander behavior, triggers state change to 'wander' |
| `stop()` | Stop wander behavior, clears timers, triggers state change to 'idle' |
| `pause()` | Temporarily pause wander (during drag), preserves state for resume |
| `resume()` | Resume wander after pause |
| `isActive()` | Returns true if wandering and not paused |

**Internal Methods:**

| Method | Purpose |
|--------|---------|
| `_scheduleNextWander()` | Schedule next movement after random delay |
| `_executeWander()` | Execute single wander movement to random target |
| `_animate()` | Animation loop using linear interpolation at configured FPS |
| `_calculateTargetPosition(current)` | Calculate valid random target within screen bounds |
| `_clearTimers()` | Clear wander and animation timers |
| `_randomInterval()` | Generate random delay between min/max interval |
| `_distance(p1, p2)` | Calculate Euclidean distance between points |
| `_lerp(start, end, t)` | Linear interpolation between values |

**Movement Algorithm:**
1. Random delay (3-8s) before each movement
2. Random angle and distance (100-300px) from current position
3. Target validated within screen bounds (tries up to 10 random targets)
4. Duration calculated from distance and speed
5. Linear interpolation animates position at 60 FPS
6. Repeat cycle when movement completes

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
wanderManager = new WanderManager(mainWindow, onStateChangeCallback);  // Initialized after window creation
```

**IPC Handlers:**

| Channel | Type | Purpose |
|---------|------|---------|
| `get-gif-path` | handle | Returns path to current state's GIF (state-aware) |
| `move-window` | on | Moves window to `{x, y}` coordinates |
| `save-position` | on | Persists position to config file |
| `change-state` | on | Changes pet state, replies with `state-changed` event |
| `get-current-state` | handle | Returns `{state, gif}` object |
| `start-wander` | on | Starts autonomous wander behavior |
| `stop-wander` | on | Stops wander behavior completely |
| `pause-wander` | on | Pauses wander temporarily (used during drag) |
| `resume-wander` | on | Resumes wander after pause |

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
| `startWander()` | Starts autonomous wander behavior |
| `stopWander()` | Stops wander behavior |
| `pauseWander()` | Pauses wander temporarily |
| `resumeWander()` | Resumes wander after pause |

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
| `initializeWander()` | Starts wander behavior after 1s delay on app startup |
| `handleMouseDown(event)` | Starts drag, records mouse offset, adds `.dragging` class, pauses wander, changes state to 'dragged' |
| `handleMouseMove(event)` | Calculates new position, calls `moveWindow()` |
| `handleMouseUp(event)` | Ends drag, saves position, resumes wander |

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
        → initializeWander() (after 1s delay)
          → electronAPI.startWander()
            → IPC → main.js → wanderManager.start()
              → schedule first wander (3-8s delay)
              → state change callback → 'wander' state → 'hop.gif'
```

### Drag Operation with State Changes
```
mousedown on #pet-container
  → isDragging = true
  → record mouseOffsetX/Y (event.clientX/Y)
  → add .dragging class
  → electronAPI.pauseWander()
    → IPC → main.js → wanderManager.pause() → clears timers
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
  → electronAPI.resumeWander()
    → IPC → main.js → wanderManager.resume()
      → schedule next wander
      → state change callback → 'wander' state → 'hop.gif'
```

### Wander Behavior Cycle
```
Wander started (initializeWander or resumeWander)
  → wanderManager._scheduleNextWander()
    → setTimeout(random 3-8s)
      → wanderManager._executeWander()
        → get current position
        → _calculateTargetPosition() → random angle & distance (100-300px)
          → validate within screen bounds (up to 10 attempts)
        → calculate duration from distance/speed
        → wanderManager._animate()
          → 60 FPS loop using setTimeout
          → _lerp() for smooth position interpolation
          → win.setPosition(x, y) each frame
          → on completion → _scheduleNextWander() (repeat cycle)

Wander paused (during drag)
  → wanderManager.pause()
    → clear timers
    → preserve state

Wander resumed (after drag)
  → wanderManager.resume()
    → restart cycle from _scheduleNextWander()
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

**Modify wander behavior:**
1. `wanderManager.js`: Adjust WANDER_CONFIG constants (intervals, distance, speed)
2. Modify `_calculateTargetPosition()` for custom movement patterns
3. Replace `_lerp()` with different interpolation (easing, bezier curves)

**Replace StateManager with AI agent:**
1. Create `AIStateManager extends StateManager` with custom logic
2. Replace `new StateManager()` in main.js
3. IPC handlers unchanged (same interface)

**Add right-click menu:**
1. `main.js`: Create `Menu` with items, show on IPC
2. `preload.js`: Expose `showContextMenu()`
3. `app.js`: Call on `contextmenu` event instead of preventing
