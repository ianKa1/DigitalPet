# Implementation Plan: Electron Desktop Pet MVP

## Overview

Building a minimal Electron app that displays Fluffball's idle.gif in a draggable, transparent, always-on-top window. The implementation follows Electron's main/renderer process architecture with secure IPC communication via a preload script.

---

## File Manifest

### New Directory Structure
```
DigitalPet/
├── electron-pet/                      # New Electron application
│   ├── main.js                        # Main process (window management)
│   ├── preload.js                     # Secure IPC bridge
│   ├── package.json                   # Dependencies and scripts
│   ├── renderer/
│   │   ├── index.html                 # UI structure
│   │   ├── styles.css                 # Transparent styling
│   │   └── app.js                     # Drag logic
│   └── assets/                        # Symlink to ../output/pets
```

### New Files to Create

**`electron-pet/package.json`**
- Purpose: Project configuration, dependencies, npm scripts
- Why: Define Electron app metadata and development commands

**`electron-pet/main.js`**
- Purpose: Main process - creates window, handles IPC
- Why: Entry point for Electron app, manages application lifecycle

**`electron-pet/preload.js`**
- Purpose: Secure bridge between main and renderer processes
- Why: Expose only necessary APIs to renderer (security best practice)

**`electron-pet/renderer/index.html`**
- Purpose: HTML structure for pet display
- Why: Define DOM elements for rendering the GIF

**`electron-pet/renderer/styles.css`**
- Purpose: Transparent styling, cursor states
- Why: Make window transparent, style drag interactions

**`electron-pet/renderer/app.js`**
- Purpose: Renderer logic - drag handling, GIF loading
- Why: Implement user interactions in the renderer process

**`electron-pet/assets/` (symlink)**
- Purpose: Link to `../output/pets/` directory
- Why: Access pet GIFs without duplicating files

### Files to Modify
```
(none - this is a new standalone Electron app)
```

### Files to Delete
```
(none)
```

---

## Implementation Steps

### Phase 1: Project Setup

#### Step 1: Create Electron project structure
- **Task**: Create directory and initialize npm project
- **Dependencies**: None
- **Commands**:
  ```bash
  cd /Users/kaimao/Projects/DigitalPet
  mkdir -p electron-pet/renderer
  cd electron-pet
  npm init -y
  ```
- **Success criteria**: `electron-pet/` directory exists with `package.json`

#### Step 2: Install dependencies
- **Task**: Install Electron and electron-builder
- **Dependencies**: Step 1 (needs package.json)
- **Commands**:
  ```bash
  npm install --save-dev electron@^28.0.0
  npm install --save-dev electron-builder@^24.0.0
  ```
- **Success criteria**: `node_modules/` and `package-lock.json` created

#### Step 3: Create symlink to pet assets
- **Task**: Link to existing pet GIF directory
- **Dependencies**: Step 1
- **Commands**:
  ```bash
  cd /Users/kaimao/Projects/DigitalPet/electron-pet
  ln -s ../output/pets assets
  ```
- **Success criteria**: `assets/Fluffball/animations/idle.gif` is accessible
- **Verification**: `ls -l assets/Fluffball/animations/idle.gif`

---

### Phase 2: Configuration

#### Step 4: Configure package.json
- **File**: `electron-pet/package.json`
- **Task**: Set up npm scripts and app metadata
- **Dependencies**: Step 2
- **Details**: Update the generated package.json with:
  - `main`: Point to `main.js` entry point
  - `scripts`: Add `start`, `build:mac`, `package` commands
  - `build`: Configure electron-builder for macOS

See **Code Structure** section below for full content.

---

### Phase 3: Main Process Implementation

#### Step 5: Create main process
- **File**: `electron-pet/main.js`
- **Task**: Implement window creation and IPC handlers
- **Dependencies**: Step 4 (needs package.json configured)
- **Key functions to implement**:
  - `createWindow()` - Create transparent, frameless window
  - `app.on('ready')` - Initialize app
  - `ipcMain.handle('get-gif-path')` - Return GIF file path
  - `ipcMain.on('move-window')` - Move window to new position
  - `ipcMain.on('save-position')` - Persist window position

See **Code Structure** section for detailed implementation.

---

### Phase 4: Preload Script

#### Step 6: Create preload script
- **File**: `electron-pet/preload.js`
- **Task**: Expose secure IPC APIs to renderer
- **Dependencies**: Step 5 (main.js defines IPC handlers)
- **APIs to expose**:
  - `window.electronAPI.getGifPath()` - Get pet GIF path
  - `window.electronAPI.moveWindow(x, y)` - Move window
  - `window.electronAPI.savePosition(x, y)` - Save position

This ensures renderer cannot access Node.js directly (security).

---

### Phase 5: Renderer Implementation

#### Step 7: Create HTML structure
- **File**: `electron-pet/renderer/index.html`
- **Task**: Define DOM structure for pet display
- **Dependencies**: None (can be done in parallel with Steps 5-6)
- **Elements**:
  - Container `<div id="pet-container">`
  - Image `<img id="pet-gif" draggable="false">`
  - Load `styles.css` and `app.js`

#### Step 8: Create CSS styling
- **File**: `electron-pet/renderer/styles.css`
- **Task**: Style for transparency and drag UX
- **Dependencies**: Step 7 (references HTML elements)
- **Key styles**:
  - Transparent body background
  - Remove default margins/padding
  - Center GIF in window
  - Cursor states: `grab` (default), `grabbing` (during drag)
  - Prevent text selection during drag

#### Step 9: Implement drag logic
- **File**: `electron-pet/renderer/app.js`
- **Task**: Handle mouse events for dragging
- **Dependencies**: Steps 6, 7, 8 (needs preload API, HTML, CSS)
- **Key functions**:
  - `loadGif()` - Load pet GIF on startup
  - `handleMouseDown(event)` - Start drag, record mouse offset
  - `handleMouseMove(event)` - Calculate new position, move window
  - `handleMouseUp(event)` - End drag, save position
  - Event listener setup

---

### Phase 6: Testing & Verification

#### Step 10: Manual testing
- **Task**: Test all functional requirements
- **Dependencies**: All previous steps
- **Test scenarios**:
  1. Run `npm start` - app launches
  2. Verify transparent window, frameless, always-on-top
  3. Test drag - click and move pet around screen
  4. Close and reopen - pet appears at last position
  5. Test with multiple apps open - pet stays on top

---

## Code Structure

### `electron-pet/package.json`

**Purpose**: Project configuration and scripts

**Full content**:
```json
{
  "name": "electron-pet",
  "version": "1.0.0",
  "description": "Desktop pet companion app",
  "main": "main.js",
  "scripts": {
    "start": "electron .",
    "build:mac": "electron-builder --mac",
    "package": "electron-builder"
  },
  "keywords": ["electron", "pet", "desktop"],
  "author": "",
  "license": "MIT",
  "devDependencies": {
    "electron": "^28.0.0",
    "electron-builder": "^24.0.0"
  },
  "build": {
    "appId": "com.digitalpet.electron",
    "mac": {
      "category": "public.app-category.entertainment",
      "target": ["dir"]
    },
    "files": [
      "main.js",
      "preload.js",
      "renderer/**/*",
      "assets/**/*"
    ]
  }
}
```

**Key fields**:
- `main`: Entry point is `main.js`
- `scripts.start`: Launch app in dev mode
- `build.files`: Include only necessary files in build

---

### `electron-pet/main.js`

**Purpose**: Main process - window management and IPC

**Key imports**:
```javascript
const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
```

**Function: `createWindow()`**
```javascript
function createWindow() {
  // Purpose: Create and configure the pet window
  // Returns: BrowserWindow instance

  const win = new BrowserWindow({
    width: 200,
    height: 200,
    transparent: true,        // Transparent background
    frame: false,             // No window frame
    alwaysOnTop: true,        // Stay on top
    resizable: false,         // Fixed size
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, // Security
      nodeIntegration: false  // Security
    }
  });

  // Load the HTML
  win.loadFile('renderer/index.html');

  // Load saved position (if exists)
  const savedPosition = loadPosition();
  if (savedPosition) {
    win.setPosition(savedPosition.x, savedPosition.y);
  }

  return win;
}
```

**Function: `loadPosition()`**
```javascript
function loadPosition() {
  // Purpose: Load saved window position from config file
  // Returns: {x: number, y: number} or null

  const configPath = path.join(app.getPath('userData'), 'position.json');

  try {
    if (fs.existsSync(configPath)) {
      const data = fs.readFileSync(configPath, 'utf8');
      return JSON.parse(data);
    }
  } catch (error) {
    console.error('Failed to load position:', error);
  }

  return null;
}
```

**Function: `savePosition(x, y)`**
```javascript
function savePosition(x, y) {
  // Purpose: Save window position to config file
  // Input: x (number), y (number) - screen coordinates

  const configPath = path.join(app.getPath('userData'), 'position.json');
  const data = JSON.stringify({ x, y });

  try {
    fs.writeFileSync(configPath, data, 'utf8');
  } catch (error) {
    console.error('Failed to save position:', error);
  }
}
```

**IPC Handlers**:
```javascript
// Handle: Get GIF path request from renderer
ipcMain.handle('get-gif-path', () => {
  return path.join(__dirname, 'assets/Fluffball/animations/idle.gif');
});

// Handle: Move window request from renderer
ipcMain.on('move-window', (event, { x, y }) => {
  const win = BrowserWindow.fromWebContents(event.sender);
  if (win) {
    win.setPosition(x, y);
  }
});

// Handle: Save position request from renderer
ipcMain.on('save-position', (event, { x, y }) => {
  savePosition(x, y);
});
```

**App lifecycle**:
```javascript
app.whenReady().then(() => {
  createWindow();

  // macOS: Re-create window when dock icon clicked
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

// Quit when all windows closed (except macOS)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
```

---

### `electron-pet/preload.js`

**Purpose**: Secure IPC bridge

**Full content**:
```javascript
const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods to renderer process
contextBridge.exposeInMainWorld('electronAPI', {
  // Get the GIF file path
  getGifPath: () => ipcRenderer.invoke('get-gif-path'),

  // Move the window to new position
  moveWindow: (x, y) => ipcRenderer.send('move-window', { x, y }),

  // Save current position
  savePosition: (x, y) => ipcRenderer.send('save-position', { x, y })
});
```

**Why this pattern**:
- `contextBridge`: Safely exposes APIs without breaking context isolation
- `ipcRenderer.invoke`: For async request-response (get-gif-path)
- `ipcRenderer.send`: For one-way messages (move-window, save-position)

---

### `electron-pet/renderer/index.html`

**Purpose**: UI structure

**Full content**:
```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Desktop Pet</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <div id="pet-container">
    <img id="pet-gif" src="" alt="Pet" draggable="false">
  </div>

  <script src="app.js"></script>
</body>
</html>
```

**Key attributes**:
- `draggable="false"`: Prevent default browser drag behavior
- No extra content: Minimal DOM for performance

---

### `electron-pet/renderer/styles.css`

**Purpose**: Transparent styling and drag UX

**Full content**:
```css
/* Reset and base styles */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body {
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: transparent;  /* Transparent background */
}

body {
  /* Prevent text selection during drag */
  -webkit-user-select: none;
  user-select: none;

  /* Remove any default margins/padding */
  margin: 0;
  padding: 0;
}

/* Pet container - center the GIF */
#pet-container {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;  /* Show grab cursor */
}

#pet-container.dragging {
  cursor: grabbing;  /* Show grabbing cursor during drag */
}

/* Pet image */
#pet-gif {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  pointer-events: none;  /* Let clicks pass through to container */
}
```

**Key design decisions**:
- `background: transparent`: Makes window background transparent
- `cursor: grab/grabbing`: Visual feedback for drag
- `user-select: none`: Prevent text selection artifacts
- `pointer-events: none` on img: Ensures container handles mouse events

---

### `electron-pet/renderer/app.js`

**Purpose**: Drag logic and GIF loading

**State variables**:
```javascript
let isDragging = false;    // Track drag state
let mouseOffsetX = 0;      // Mouse offset from window top-left
let mouseOffsetY = 0;
```

**Function: `loadGif()`**
```javascript
async function loadGif() {
  // Purpose: Load pet GIF on app startup
  // Called: On DOMContentLoaded

  try {
    const gifPath = await window.electronAPI.getGifPath();
    const petImg = document.getElementById('pet-gif');
    petImg.src = gifPath;
  } catch (error) {
    console.error('Failed to load GIF:', error);
  }
}
```

**Function: `handleMouseDown(event)`**
```javascript
function handleMouseDown(event) {
  // Purpose: Start drag operation
  // Input: MouseEvent
  // Side effects: Sets isDragging, records mouse offset, updates cursor

  isDragging = true;

  // Calculate offset from mouse to window top-left
  // This keeps the pet from "jumping" when you start dragging
  mouseOffsetX = event.clientX;
  mouseOffsetY = event.clientY;

  // Update cursor
  document.getElementById('pet-container').classList.add('dragging');
}
```

**Function: `handleMouseMove(event)`**
```javascript
function handleMouseMove(event) {
  // Purpose: Move window during drag
  // Input: MouseEvent
  // Side effects: Sends move-window IPC message

  if (!isDragging) return;

  // Calculate new window position
  // event.screenX/Y gives screen coordinates of mouse
  // Subtract offset to keep mouse position relative to pet
  const newX = event.screenX - mouseOffsetX;
  const newY = event.screenY - mouseOffsetY;

  // Send to main process to move window
  window.electronAPI.moveWindow(newX, newY);
}
```

**Function: `handleMouseUp(event)`**
```javascript
function handleMouseUp(event) {
  // Purpose: End drag operation
  // Input: MouseEvent
  // Side effects: Sets isDragging=false, saves position, updates cursor

  if (!isDragging) return;

  isDragging = false;

  // Update cursor
  document.getElementById('pet-container').classList.remove('dragging');

  // Save final position
  const finalX = event.screenX - mouseOffsetX;
  const finalY = event.screenY - mouseOffsetY;
  window.electronAPI.savePosition(finalX, finalY);
}
```

**Event listener setup**:
```javascript
// Load GIF when page loads
document.addEventListener('DOMContentLoaded', loadGif);

// Drag event listeners
const container = document.getElementById('pet-container');

container.addEventListener('mousedown', handleMouseDown);
document.addEventListener('mousemove', handleMouseMove);  // Document-level for smooth drag
document.addEventListener('mouseup', handleMouseUp);      // Document-level to catch release anywhere
```

**Why document-level for move/up**:
- `mousemove` on document: Ensures smooth dragging even if mouse moves fast
- `mouseup` on document: Catches mouse release even if outside window

---

## Data Flow

### App Startup Flow
```
User launches app
    ↓
[main.js] app.whenReady() fires
    ↓
createWindow() called
    ↓
BrowserWindow created with transparent, frameless config
    ↓
loadPosition() reads saved position from userData/position.json
    ↓
Window positioned at saved location (or default)
    ↓
renderer/index.html loaded
    ↓
[preload.js] exposes electronAPI to renderer
    ↓
[app.js] DOMContentLoaded fires
    ↓
loadGif() calls window.electronAPI.getGifPath()
    ↓
[main.js] IPC handler returns GIF path
    ↓
[app.js] Sets img.src to GIF path
    ↓
Pet visible on screen
```

### Drag Flow
```
User clicks pet
    ↓
[app.js] handleMouseDown() fires
    ↓
Record mouse offset (clientX, clientY)
    ↓
Set isDragging = true
    ↓
Add 'dragging' class (cursor changes to grabbing)
    ↓
User moves mouse
    ↓
[app.js] handleMouseMove() fires (repeatedly)
    ↓
Calculate new position: screenX/Y - offset
    ↓
window.electronAPI.moveWindow(newX, newY)
    ↓
[preload.js] forwards IPC message
    ↓
[main.js] ipcMain.on('move-window') handler
    ↓
win.setPosition(x, y)
    ↓
Window moves on screen
    ↓
User releases mouse
    ↓
[app.js] handleMouseUp() fires
    ↓
Set isDragging = false
    ↓
Remove 'dragging' class (cursor back to grab)
    ↓
window.electronAPI.savePosition(finalX, finalY)
    ↓
[main.js] savePosition() writes to userData/position.json
```

### Position Persistence
```
Window moved
    ↓
Final position calculated
    ↓
IPC: save-position message sent
    ↓
[main.js] savePosition(x, y)
    ↓
JSON.stringify({x, y})
    ↓
Write to app.getPath('userData')/position.json
    ↓
File saved
    ↓
(Next app launch)
    ↓
loadPosition() reads position.json
    ↓
Returns {x, y} or null
    ↓
Window positioned at saved location
```

**Position file location**:
- macOS: `~/Library/Application Support/electron-pet/position.json`
- Format: `{"x": 100, "y": 200}`

---

## Test Plan

### Manual Testing (Step 10)

**Test 1: App Launch**
- Action: Run `npm start` from electron-pet directory
- Expected: App window appears on screen
- Verify: Pet GIF is visible

**Test 2: Transparency**
- Action: With app running, look at window edges
- Expected: Desktop/other windows visible through transparent areas
- Verify: Only the pet GIF is visible, no window background

**Test 3: Frameless Window**
- Action: Look at window borders
- Expected: No title bar, no close button, no borders
- Verify: Window has no OS chrome

**Test 4: Always-on-Top**
- Action: Open other applications (browser, terminal)
- Expected: Pet remains visible above other windows
- Verify: Click on other windows, pet still visible

**Test 5: Drag Functionality**
- Action: Click on pet and drag to different screen position
- Expected: Pet moves smoothly with mouse
- Verify: No lag, cursor changes to "grabbing"

**Test 6: Drag Release**
- Action: Release mouse button during drag
- Expected: Pet stays at new position, cursor changes back to "grab"
- Verify: Position is stable

**Test 7: Position Persistence**
- Action:
  1. Drag pet to specific location
  2. Quit app (Cmd+Q or force quit)
  3. Restart app
- Expected: Pet appears at same location as before quit
- Verify: Check `~/Library/Application Support/electron-pet/position.json` exists

**Test 8: Edge Cases**
- Action: Drag pet partially off-screen
- Expected: Pet can be dragged off-screen (no bounds checking in MVP)
- Note: This is expected behavior for MVP

**Test 9: Multiple Monitors** (if applicable)
- Action: Drag pet across multiple screens
- Expected: Pet can be dragged to any screen
- Verify: Position persistence works across screens

**Test 10: Performance**
- Action: Drag pet rapidly around screen
- Expected: Smooth movement, no lag or stuttering
- Verify: Check CPU usage (should be minimal)

---

## Configuration & Dependencies

### Dependencies to Install
```json
{
  "electron": "^28.0.0",        // Desktop app framework
  "electron-builder": "^24.0.0" // Build and package tool
}
```

**Why these versions**:
- Electron 28: Latest stable with modern security features
- electron-builder: Industry standard for packaging

### Environment Setup
- Node.js: Version 18+ (included with Electron)
- macOS: 12+ recommended
- Disk space: ~500MB (node_modules + Electron binaries)

### Configuration Files Created

**`position.json`** (auto-generated):
- Location: `~/Library/Application Support/electron-pet/position.json`
- Format:
  ```json
  {
    "x": 100,
    "y": 200
  }
  ```
- Created by: First drag operation
- Purpose: Remember window position between sessions

---

## Open Questions for Implementation

- [ ] **GIF size detection**: Should we auto-detect idle.gif dimensions and resize window? (Recommendation: Start with fixed 200x200, add auto-detection later if needed)

- [ ] **Error handling**: What if idle.gif is missing? (Recommendation: Show error message in dev mode, gracefully fail in production)

- [ ] **Position bounds**: Should we prevent pet from going completely off-screen? (Recommendation: Not for MVP, add bounds checking in future)

- [ ] **Close mechanism**: How should user close the app? (Recommendation: Force quit for MVP, add right-click menu in next iteration)

---

## Development Workflow

### Initial Setup
```bash
cd /Users/kaimao/Projects/DigitalPet
mkdir -p electron-pet/renderer
cd electron-pet
npm init -y
npm install --save-dev electron@^28.0.0 electron-builder@^24.0.0
ln -s ../output/pets assets
```

### Development Mode
```bash
cd /Users/kaimao/Projects/DigitalPet/electron-pet
npm start
```

**What happens**:
1. Electron launches in dev mode
2. Opens DevTools (if needed for debugging)
3. Hot-reload not configured for MVP (restart app to see changes)

### Building for Distribution
```bash
npm run build:mac
```

**Output**: `dist/mac/electron-pet.app`

### Debugging Tips
- Open DevTools: In `main.js` add `win.webContents.openDevTools()`
- Check console: Look for errors in renderer DevTools
- IPC debugging: Add `console.log()` in IPC handlers
- Position debugging: Check `position.json` file contents

---

## Security Considerations

**✅ Implemented**:
- Context isolation enabled (renderer can't access Node.js)
- Preload script limits exposed APIs
- No remote content loading
- No eval() or dynamic code execution

**⚠️ Future considerations**:
- Code signing (required for macOS distribution)
- Notarization (required for macOS Gatekeeper)
- Content Security Policy (if adding web content)

---

## Extensibility Notes

### Adding New Behaviors (Future)

The current architecture supports adding behavior states with minimal changes:

**1. Update preload.js**:
```javascript
changeBehavior: (behavior) => ipcRenderer.send('change-behavior', behavior)
```

**2. Update main.js**:
```javascript
ipcMain.on('change-behavior', (event, behavior) => {
  // Handle behavior change
});
```

**3. Update app.js**:
```javascript
const behaviors = {
  idle: 'assets/Fluffball/animations/idle.gif',
  walk: 'assets/Fluffball/animations/walk.gif',
  jump: 'assets/Fluffball/animations/jump.gif'
};

function changeBehavior(newBehavior) {
  document.getElementById('pet-gif').src = behaviors[newBehavior];
}
```

**4. Add interaction triggers**:
- Click detection
- Timer-based transitions
- External events (time of day, etc.)

---

## Next Steps

✅ Review this implementation plan
✅ Confirm approach before writing code
⬜ Execute Phase 1: Project Setup (Steps 1-3)
⬜ Execute Phase 2: Configuration (Step 4)
⬜ Execute Phase 3: Main Process (Step 5)
⬜ Execute Phase 4: Preload Script (Step 6)
⬜ Execute Phase 5: Renderer (Steps 7-9)
⬜ Execute Phase 6: Testing (Step 10)

---

**Estimated time**: 2-3 hours for MVP implementation
**Files to create**: 6 files + symlink
**Lines of code**: ~300 total (well-commented)

Does this implementation approach look good? Should I proceed with writing the code?
