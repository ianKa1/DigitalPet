# Feature Specification: Electron Desktop Pet MVP

## Overview

Build a minimal Electron desktop application that displays an animated GIF pet on the desktop with drag functionality. The app shows a frameless, always-on-top transparent window that users can click and drag around the screen. The architecture is designed to be extensible for future behavior states and interactions.

## Problem Statement

**Current state**: The DigitalPet project generates animated pet sprites as GIF files, but they only exist as static files in the filesystem. Users cannot interact with or display their generated pets on their desktop.

**User need**: Users want to bring their generated digital pets to life by displaying them as interactive desktop companions that they can see and interact with while working.

**Target users**: DigitalPet users who have generated pet animations and want to display them as desktop widgets.

## Proposed Solution

Create a lightweight Electron application that:
1. Displays a pet GIF in a frameless, transparent window
2. Keeps the pet always visible on top of other windows
3. Allows users to drag the pet around the screen
4. Provides an extensible architecture for adding behavior states and interactions

**Why Electron**: Cross-platform compatibility, web technologies (HTML/CSS/JS) for easy GIF rendering, mature ecosystem, and straightforward packaging for distribution.

## Technical Design

### Architecture Overview

```
electron-pet/
├── main.js              # Electron main process (window management)
├── preload.js           # Bridge between main and renderer (security)
├── renderer/
│   ├── index.html       # UI structure
│   ├── styles.css       # Styling (transparency, positioning)
│   └── app.js           # Renderer logic (drag, interactions)
├── package.json         # Dependencies and scripts
└── assets/              # Pet GIFs (symlink to DigitalPet output)
```

### Components

#### 1. Main Process (`main.js`)
**Responsibility**: Create and manage the pet window

**Key features**:
- Create BrowserWindow with transparent, frameless configuration
- Set always-on-top behavior
- Handle window position persistence (remember last position)
- IPC communication with renderer process

**Window configuration**:
```javascript
{
  width: 200,              // Adjust based on GIF size
  height: 200,
  transparent: true,       // Transparent background
  frame: false,            // No title bar/borders
  alwaysOnTop: true,       // Stay above other windows
  resizable: false,        // Fixed size for MVP
  webPreferences: {
    preload: path.join(__dirname, 'preload.js'),
    contextIsolation: true // Security best practice
  }
}
```

#### 2. Preload Script (`preload.js`)
**Responsibility**: Secure bridge between main and renderer processes

**Exposed APIs**:
- `window.electronAPI.getGifPath()` - Get current pet GIF path
- `window.electronAPI.savePosition(x, y)` - Persist window position
- Future: `window.electronAPI.changeBehavior(state)` for behavior changes

#### 3. Renderer Process (`renderer/`)

**`index.html`**:
```html
<div id="pet-container">
  <img id="pet-gif" src="" draggable="false">
</div>
```

**`styles.css`**:
- Transparent body background
- Cursor styles (grab/grabbing during drag)
- GIF sizing and centering

**`app.js`**:
- Load GIF on startup
- Implement drag functionality
- Handle click events (for future interactions)

### Data Flow

```
App Startup
    ↓
[Main Process] Creates transparent window
    ↓
[Preload] Exposes secure APIs
    ↓
[Renderer] Loads pet GIF
    ↓
User drags pet
    ↓
[Renderer] Calculates mouse offset → Updates window position
    ↓
[Main Process] Moves window
    ↓
[Optional] Save position to config
```

### Drag Implementation

**Mouse events**:
1. `mousedown` on pet → Start drag (record mouse offset)
2. `mousemove` → Calculate new position, move window via IPC
3. `mouseup` → End drag

**Position calculation**:
```javascript
// Renderer calculates screen coordinates
newX = event.screenX - mouseOffsetX
newY = event.screenY - mouseOffsetY

// Send to main process to move window
ipcRenderer.send('move-window', { x: newX, y: newY })
```

### Extensibility Design

**Behavior State System** (future):
```javascript
// State manager (to be added)
const behaviors = {
  idle: 'animations/idle.gif',
  walk: 'animations/walk.gif',
  jump: 'animations/jump.gif'
}

function changeBehavior(newBehavior) {
  document.getElementById('pet-gif').src = behaviors[newBehavior]
}
```

**Input/Logic Hooks** (future):
- Click detection → trigger behavior change
- Timer-based state changes → random idle animations
- Desktop awareness → react to screen edges

### Technology Stack

**Core**:
- Electron (latest stable, ~v28+)
- Node.js (bundled with Electron)
- Vanilla JavaScript (no framework needed for MVP)

**Dependencies**:
```json
{
  "electron": "^28.0.0",
  "electron-builder": "^24.0.0"  // For packaging
}
```

## Success Criteria

### Functional Requirements

✅ **Must have** (MVP):
1. Pet GIF displays in transparent window
2. Window is always on top of other applications
3. User can click and drag pet to any screen position
4. Window has no frame/decorations (frameless)
5. Pet remains visible and draggable after moving
6. App launches successfully on macOS

✅ **Should have** (extensibility):
7. Code structure allows easy addition of new behaviors
8. Clear separation between main/renderer processes
9. Window position persists between app restarts

### Non-Functional Requirements

- **Performance**: Smooth dragging with no lag (<16ms frame time)
- **Memory**: Low footprint (<100MB for single pet)
- **Startup**: App launches in <2 seconds
- **Compatibility**: Works on macOS 12+ (MVP), Windows/Linux (future)

### Acceptance Tests

1. **Display test**: Launch app → Pet GIF appears on screen
2. **Transparency test**: Desktop/windows visible through transparent areas
3. **Always-on-top test**: Open other apps → Pet stays visible
4. **Drag test**: Click and drag pet → Moves smoothly to new position
5. **Release test**: Release mouse → Pet stays at new position
6. **Restart test**: Close and reopen app → Pet appears at last position

## Non-Goals

**Explicitly out of scope for MVP**:
- Multiple pets on screen simultaneously
- Behavior state changes (idle, walk, jump) - architecture supports, not implemented
- User interactions beyond drag (right-click menu, double-click)
- Pet AI or personality responses
- Integration with Gemini API for dynamic behaviors
- Custom pet selection UI (hardcoded to Fluffball idle.gif)
- System tray integration
- Auto-start on login
- Cross-platform builds (Mac only for MVP)

**Future considerations**:
- Behavior state machine with transitions
- Interaction menu (right-click for actions)
- Pet selector UI to choose different pets
- Desktop awareness (sit on windows, avoid cursor)
- Sound effects
- Settings panel (opacity, size, behaviors)

## Implementation Notes

### File Structure
```
DigitalPet/
├── electron-pet/           # New Electron app directory
│   ├── main.js
│   ├── preload.js
│   ├── renderer/
│   │   ├── index.html
│   │   ├── styles.css
│   │   └── app.js
│   ├── package.json
│   └── assets/            # Symlink to ../output/pets/
└── output/
    └── pets/
        └── Fluffball/
            └── animations/
                └── idle.gif  # Source GIF
```

### Development Commands
```bash
# Setup
cd electron-pet
npm install

# Development (with hot reload)
npm start

# Build for macOS
npm run build:mac

# Package distributable
npm run package
```

### Security Considerations

- **Context isolation**: Enabled to prevent renderer from accessing Node.js directly
- **Preload script**: Only expose necessary APIs to renderer
- **No remote content**: All assets loaded locally
- **No eval()**: Avoid dynamic code execution

### GIF Loading Strategy

**MVP** (hardcoded):
```javascript
const gifPath = path.join(__dirname, 'assets/pets/Fluffball/animations/idle.gif')
```

**Future** (configurable):
```javascript
const config = {
  currentPet: 'Fluffball',
  currentBehavior: 'idle'
}
const gifPath = `assets/pets/${config.currentPet}/animations/${config.currentBehavior}.gif`
```

## Open Questions

- [ ] **Window size**: Should it auto-detect GIF dimensions or use fixed size? (Suggestion: Auto-detect for flexibility)
- [ ] **Multiple screens**: How should pet behave with multiple monitors? (Suggestion: Stay on current screen)
- [ ] **Close behavior**: Should there be a way to close the app besides force quit? (Suggestion: Right-click → Quit in future iteration)
- [ ] **Packaging**: DMG installer or simple .app bundle? (Suggestion: .app for MVP, DMG for distribution)

## Next Steps

1. Review and approve this specification
2. Create implementation plan (file-by-file breakdown)
3. Set up Electron project structure
4. Implement core window + drag functionality
5. Test on macOS
6. (Future) Add behavior state system
7. (Future) Build for distribution

---

**Estimated Complexity**: Simple (1-2 days for MVP)

**Key Files to Create**: 5 files (main.js, preload.js, index.html, styles.css, app.js, package.json)
