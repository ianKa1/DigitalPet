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
├── preload.js      # IPC bridge - exposes APIs to renderer
├── package.json    # Dependencies, scripts, build config
├── renderer/
│   ├── index.html  # DOM structure
│   ├── styles.css  # Transparent window styling
│   └── app.js      # Drag logic, GIF loading
└── assets/         # Symlink → ../output/pets
```

## Main Process (main.js)

Entry point. Creates transparent frameless window and handles IPC.

**Key Functions:**

| Function | Purpose |
|----------|---------|
| `createWindow()` | Creates BrowserWindow with transparent, frameless, always-on-top config |
| `loadPosition()` | Reads saved position from `userData/position.json` |
| `savePosition(x, y)` | Writes position to `userData/position.json` |
| `getConfigPath()` | Returns path to position config file |

**IPC Handlers:**

| Channel | Type | Purpose |
|---------|------|---------|
| `get-gif-path` | handle (async) | Returns path to current pet GIF |
| `move-window` | on | Moves window to `{x, y}` coordinates |
| `save-position` | on | Persists position to config file |

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
| `handleMouseDown(event)` | Starts drag, records mouse offset, adds `.dragging` class |
| `handleMouseMove(event)` | Calculates new position, calls `moveWindow()` |
| `handleMouseUp(event)` | Ends drag, saves position |

**Event Listeners:**
- `mousedown` on `#pet-container` → start drag
- `mousemove` on `document` → move during drag (document-level for smooth tracking)
- `mouseup` on `document` → end drag (document-level to catch release anywhere)
- `contextmenu` → prevented (no right-click menu)

## Logic Pipeline

### App Startup
```
app.whenReady()
  → createWindow()
    → new BrowserWindow(config)
    → loadPosition() → read position.json
    → win.setPosition(x, y)
    → win.loadFile('renderer/index.html')
      → DOMContentLoaded
        → loadGif()
          → electronAPI.getGifPath()
            → IPC → main.js returns GIF path
          → set img.src
```

### Drag Operation
```
mousedown on #pet-container
  → isDragging = true
  → record mouseOffsetX/Y (event.clientX/Y)
  → add .dragging class

mousemove (while isDragging)
  → calculate: newX = screenX - offsetX, newY = screenY - offsetY
  → electronAPI.moveWindow(newX, newY)
    → IPC → main.js → win.setPosition(x, y)

mouseup
  → isDragging = false
  → remove .dragging class
  → electronAPI.savePosition(finalX, finalY)
    → IPC → main.js → savePosition() → write position.json
```

## Data Storage

**Position config:**
- Path: `~/Library/Application Support/electron-pet/position.json`
- Format: `{"x": 100, "y": 200}`
- Read on startup, written on drag end

## Extension Points

**Add new IPC handler:**
1. `main.js`: Add `ipcMain.handle()` or `ipcMain.on()`
2. `preload.js`: Expose method via `contextBridge`
3. `app.js`: Call `window.electronAPI.newMethod()`

**Add new behavior/GIF:**
1. Modify `get-gif-path` handler to accept behavior parameter
2. Add `changeBehavior(name)` to preload API
3. Call from renderer when behavior should change

**Add right-click menu:**
1. `main.js`: Create `Menu` with items, show on IPC
2. `preload.js`: Expose `showContextMenu()`
3. `app.js`: Call on `contextmenu` event instead of preventing
