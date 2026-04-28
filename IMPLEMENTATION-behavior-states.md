# Implementation Plan: Pet Behavior States

## Overview

Adding a behavior state system to the desktop pet with a decoupled StateManager module. The pet will display "float.gif" when dragged and "idle.gif" when stationary. Main process owns state logic, renderer is pure view layer.

---

## File Manifest

### New Files to Create

**`electron-pet/stateManager.js`**
- Purpose: State machine module with state configuration and transition logic
- Why: Decoupled from main.js for testability and future AI/agent replacement

### Files to Modify

**`electron-pet/main.js`**
- Add: Require StateManager, instantiate stateManager
- Add: Two new IPC handlers (`change-state`, `get-current-state`)
- Why: Wire StateManager to IPC layer

**`electron-pet/preload.js`**
- Add: Three new API methods to `electronAPI`
- Add: State change listener setup
- Why: Expose state APIs to renderer securely

**`electron-pet/renderer/app.js`**
- Modify: `handleMouseDown()` - trigger state change to 'dragged'
- Modify: `handleMouseUp()` - trigger state change to 'idle'
- Modify: `loadGif()` - use state-based GIF loading
- Add: `onStateChanged` listener to update GIF
- Why: React to user interactions with state changes

### Files to Delete
```
(none)
```

---

## Implementation Steps

### Phase 1: State Manager Module

#### Step 1: Create StateManager module
- **File**: `electron-pet/stateManager.js`
- **Task**: Implement state machine with configuration and methods
- **Dependencies**: None
- **Details**: Create STATE_CONFIG and StateManager class with full API

**Success criteria**: StateManager can be required and instantiated independently

---

### Phase 2: Main Process Integration

#### Step 2: Integrate StateManager into main.js
- **File**: `electron-pet/main.js`
- **Task**: Add StateManager require, instantiate, and IPC handlers
- **Dependencies**: Step 1 (needs stateManager.js)
- **Changes**:
  - Add `require('./stateManager')` at top
  - Instantiate `stateManager` after imports
  - Add `change-state` IPC handler
  - Add `get-current-state` IPC handler
  - Modify `get-gif-path` to use stateManager (optional improvement)

**Success criteria**: Main process has stateManager instance and IPC handlers respond

---

### Phase 3: Preload API

#### Step 3: Add state APIs to preload script
- **File**: `electron-pet/preload.js`
- **Task**: Expose state change methods to renderer
- **Dependencies**: Step 2 (IPC handlers must exist)
- **Changes**:
  - Add `changeState(state)` method
  - Add `onStateChanged(callback)` listener setup
  - Add `getCurrentState()` method

**Success criteria**: Renderer can call state APIs via `window.electronAPI`

---

### Phase 4: Renderer Updates

#### Step 4: Update drag handlers for state changes
- **File**: `electron-pet/renderer/app.js`
- **Task**: Trigger state changes on mouse down/up
- **Dependencies**: Step 3 (needs preload APIs)
- **Changes**:
  - In `handleMouseDown()`: Add `window.electronAPI.changeState('dragged')`
  - In `handleMouseUp()`: Add `window.electronAPI.changeState('idle')`

**Success criteria**: Dragging triggers state change IPC messages

---

#### Step 5: Add state change listener
- **File**: `electron-pet/renderer/app.js`
- **Task**: Listen for state changes and update GIF
- **Dependencies**: Step 4
- **Changes**:
  - Add `onStateChanged` listener that updates `petGif.src`
  - Modify `loadGif()` to use `getCurrentState()`

**Success criteria**: GIF changes when state changes

---

### Phase 5: Testing

#### Step 6: Manual testing
- **Task**: Verify all functional requirements
- **Dependencies**: All previous steps
- **Test scenarios**:
  1. Launch app → idle.gif displays
  2. Drag pet → float.gif displays immediately
  3. Release → idle.gif returns immediately
  4. Multiple drag cycles → works consistently

**Success criteria**: All acceptance tests pass

---

## Code Structure

### `electron-pet/stateManager.js` (NEW)

**Purpose**: State machine module

**State Configuration**:
```javascript
const STATE_CONFIG = {
  idle: {
    gif: 'idle.gif',
    // Future properties (placeholder):
    // duration: null,
    // transitions: [],
    // sound: null,
  },
  dragged: {
    gif: 'float.gif',
    // Future properties (placeholder):
    // duration: null,
    // transitions: [],
    // sound: null,
  },
  // Future states (placeholder):
  // clicked: { gif: 'bounce.gif' },
  // sleeping: { gif: 'sleep.gif' },
  // curious: { gif: 'curious_look.gif' },
};
```

**Class: StateManager**

```javascript
class StateManager {
  constructor(initialState = 'idle') {
    this.currentState = initialState;
    this.stateConfig = STATE_CONFIG;
  }

  getCurrentState() {
    // Returns: string - current state name
    return this.currentState;
  }

  getCurrentGif() {
    // Returns: string - GIF filename for current state
    return this.stateConfig[this.currentState].gif;
  }

  setState(newState) {
    // Input: string - new state name
    // Returns: string - GIF filename for new state
    // Throws: Error if state doesn't exist

    if (!this.stateConfig[newState]) {
      throw new Error(`Unknown state: ${newState}`);
    }
    this.currentState = newState;
    return this.getCurrentGif();
  }

  hasState(state) {
    // Input: string - state name to check
    // Returns: boolean - true if state exists
    return state in this.stateConfig;
  }

  getAvailableStates() {
    // Returns: string[] - array of all state names
    return Object.keys(this.stateConfig);
  }
}

module.exports = StateManager;
```

---

### `electron-pet/main.js` (MODIFIED)

**Changes to add**:

**At top of file** (after existing requires):
```javascript
const StateManager = require('./stateManager');
```

**After imports** (before createWindow):
```javascript
// Initialize state manager
const stateManager = new StateManager('idle');
```

**New IPC handler** (add after existing IPC handlers):
```javascript
// Handle state change request from renderer
ipcMain.on('change-state', (event, newState) => {
  try {
    const gifFileName = stateManager.setState(newState);
    const fullPath = path.join(__dirname, 'assets', 'Fluffball', 'animations', gifFileName);

    // Send new GIF path back to renderer
    event.reply('state-changed', {
      state: newState,
      gifPath: fullPath
    });
  } catch (error) {
    console.error('State change error:', error);
    // Don't crash - just log the error
  }
});

// Get current state (for initialization or debugging)
ipcMain.handle('get-current-state', () => {
  return {
    state: stateManager.getCurrentState(),
    gif: stateManager.getCurrentGif()
  };
});
```

**Optional improvement** (modify existing `get-gif-path` handler):
```javascript
// Get the GIF path for the pet
ipcMain.handle('get-gif-path', () => {
  const gifFileName = stateManager.getCurrentGif();
  return path.join(__dirname, 'assets', 'Fluffball', 'animations', gifFileName);
});
```

---

### `electron-pet/preload.js` (MODIFIED)

**Changes to add**:

**Inside `electronAPI` object** (add to existing APIs):
```javascript
contextBridge.exposeInMainWorld('electronAPI', {
  // ... existing APIs (getGifPath, moveWindow, savePosition) ...

  /**
   * Change pet state
   * @param {string} state - New state name ('idle', 'dragged', etc.)
   */
  changeState: (state) => ipcRenderer.send('change-state', state),

  /**
   * Listen for state changes from main process
   * @param {function} callback - Called with {state, gifPath} when state changes
   */
  onStateChanged: (callback) => ipcRenderer.on('state-changed', (event, data) => callback(data)),

  /**
   * Get current state
   * @returns {Promise<{state: string, gif: string}>} Current state and GIF filename
   */
  getCurrentState: () => ipcRenderer.invoke('get-current-state')
});
```

---

### `electron-pet/renderer/app.js` (MODIFIED)

**Modification 1: handleMouseDown**

**Current code** (lines 31-41):
```javascript
function handleMouseDown(event) {
  isDragging = true;
  mouseOffsetX = event.clientX;
  mouseOffsetY = event.clientY;
  petContainer.classList.add('dragging');
}
```

**New code**:
```javascript
function handleMouseDown(event) {
  isDragging = true;
  mouseOffsetX = event.clientX;
  mouseOffsetY = event.clientY;
  petContainer.classList.add('dragging');

  // NEW: Change state to 'dragged'
  window.electronAPI.changeState('dragged');
}
```

---

**Modification 2: handleMouseUp**

**Current code** (lines 64-76):
```javascript
function handleMouseUp(event) {
  if (!isDragging) return;

  isDragging = false;
  petContainer.classList.remove('dragging');

  const finalX = event.screenX - mouseOffsetX;
  const finalY = event.screenY - mouseOffsetY;
  window.electronAPI.savePosition(finalX, finalY);
}
```

**New code**:
```javascript
function handleMouseUp(event) {
  if (!isDragging) return;

  isDragging = false;
  petContainer.classList.remove('dragging');

  const finalX = event.screenX - mouseOffsetX;
  const finalY = event.screenY - mouseOffsetY;
  window.electronAPI.savePosition(finalX, finalY);

  // NEW: Return to 'idle' state
  window.electronAPI.changeState('idle');
}
```

---

**Modification 3: loadGif**

**Current code** (lines 18-25):
```javascript
async function loadGif() {
  try {
    const gifPath = await window.electronAPI.getGifPath();
    petGif.src = gifPath;
  } catch (error) {
    console.error('Failed to load GIF:', error);
  }
}
```

**New code** (state-aware initialization):
```javascript
async function loadGif() {
  try {
    // Load initial state-based GIF
    const gifPath = await window.electronAPI.getGifPath();
    petGif.src = gifPath;
  } catch (error) {
    console.error('Failed to load GIF:', error);
  }
}
```
*(Note: This can stay mostly the same since get-gif-path now uses stateManager)*

---

**Addition 4: State change listener**

**Add after the loadGif function** (before event listeners section):
```javascript
/**
 * Handle state changes from main process
 * @param {object} data - {state: string, gifPath: string}
 */
function handleStateChange(data) {
  const { state, gifPath } = data;

  // Update GIF immediately
  petGif.src = gifPath;

  // Optional: Log for debugging
  console.log(`State changed to: ${state}`);
}

// Set up state change listener
window.electronAPI.onStateChanged(handleStateChange);
```

**Or inline** (add after existing event listeners, around line 95):
```javascript
// Listen for state changes from main process
window.electronAPI.onStateChanged((data) => {
  const { state, gifPath } = data;
  petGif.src = gifPath;
  console.log(`State changed to: ${state}`);
});
```

---

## Data Flow

### App Startup Flow

```
app.whenReady()
  ↓
[main.js] createWindow()
  ↓
[main.js] stateManager = new StateManager('idle')
  ↓
[renderer] DOMContentLoaded
  ↓
[renderer] loadGif()
  ↓
getGifPath() via IPC
  ↓
[main.js] stateManager.getCurrentGif() → 'idle.gif'
  ↓
Returns path: 'assets/Fluffball/animations/idle.gif'
  ↓
[renderer] petGif.src = gifPath
  ↓
Pet displays idle.gif
```

### Drag Start Flow

```
User clicks pet
  ↓
[renderer] handleMouseDown() fires
  ↓
isDragging = true, offset recorded
  ↓
changeState('dragged') via IPC
  ↓
[main.js] receives 'change-state' event
  ↓
stateManager.setState('dragged')
  ↓
Returns 'float.gif'
  ↓
Build full path: 'assets/Fluffball/animations/float.gif'
  ↓
event.reply('state-changed', { state: 'dragged', gifPath })
  ↓
[renderer] onStateChanged callback
  ↓
petGif.src = gifPath
  ↓
Pet displays float.gif (instant transition)
```

### Drag End Flow

```
User releases mouse
  ↓
[renderer] handleMouseUp() fires
  ↓
isDragging = false
  ↓
savePosition(finalX, finalY) via IPC
  ↓
changeState('idle') via IPC
  ↓
[main.js] stateManager.setState('idle')
  ↓
Returns 'idle.gif'
  ↓
event.reply('state-changed', { state: 'idle', gifPath })
  ↓
[renderer] onStateChanged callback
  ↓
petGif.src = 'idle.gif'
  ↓
Pet displays idle.gif (instant transition)
```

### State Data Structures

**STATE_CONFIG format**:
```javascript
{
  stateName: {
    gif: string,        // Required: GIF filename
    // duration: number,   // Placeholder: ms before auto-transition
    // transitions: [],    // Placeholder: valid next states
    // sound: string,      // Placeholder: audio file
  }
}
```

**IPC Message formats**:

**change-state** (renderer → main):
```javascript
{
  channel: 'change-state',
  data: 'dragged'  // state name as string
}
```

**state-changed** (main → renderer):
```javascript
{
  channel: 'state-changed',
  data: {
    state: 'dragged',
    gifPath: '/path/to/assets/Fluffball/animations/float.gif'
  }
}
```

**get-current-state** response:
```javascript
{
  state: 'idle',
  gif: 'idle.gif'
}
```

---

## Test Plan

### Manual Testing (Step 6)

**Test 1: Default State**
- Action: Launch app (`npm start`)
- Expected: Pet displays idle.gif
- Verify: Visual check - bunny in idle animation

**Test 2: Drag Start State**
- Action: Click and start dragging pet
- Expected: Instant switch to float.gif
- Verify: Floating animation appears immediately

**Test 3: Drag End State**
- Action: Release mouse after drag
- Expected: Instant switch back to idle.gif
- Verify: Idle animation resumes immediately

**Test 4: Multiple Drag Cycles**
- Action: Drag → release → drag → release (5 times)
- Expected: Smooth transitions every time
- Verify: No lag, no stuck states

**Test 5: Invalid State (Error Handling)**
- Action: In DevTools console, run `window.electronAPI.changeState('invalid')`
- Expected: Error logged in console, app doesn't crash
- Verify: Check console for error message, pet stays functional

**Test 6: Rapid Drag**
- Action: Quickly click-drag-release multiple times
- Expected: No race conditions, state always correct
- Verify: Pet always returns to idle after release

**Test 7: State Persistence**
- Action: Drag pet → quit app → restart
- Expected: App starts in idle state (not dragged)
- Verify: Pet shows idle.gif on startup

**Test 8: GIF Loading**
- Action: Verify both GIF files exist and load
- Expected: Both idle.gif and float.gif display correctly
- Verify: No broken images, smooth animations

---

## Configuration & Dependencies

### No New Dependencies
```
(none - using existing Electron installation)
```

### Existing Dependencies
```json
{
  "electron": "^28.0.0",         // Already installed
  "electron-builder": "^24.0.0"  // Already installed
}
```

---

## Error Handling

### Invalid State Names

**In stateManager.js**:
```javascript
setState(newState) {
  if (!this.stateConfig[newState]) {
    throw new Error(`Unknown state: ${newState}`);
  }
  // ... proceed with state change
}
```

**In main.js IPC handler**:
```javascript
ipcMain.on('change-state', (event, newState) => {
  try {
    const gifFileName = stateManager.setState(newState);
    // ... send state-changed reply
  } catch (error) {
    console.error('State change error:', error);
    // Don't send reply - renderer keeps current state
  }
});
```

### Missing GIF Files

**In renderer** (onStateChanged callback):
```javascript
window.electronAPI.onStateChanged((data) => {
  const { state, gifPath } = data;
  petGif.src = gifPath;

  // Image load error handled by browser
  petGif.onerror = () => {
    console.error(`Failed to load GIF for state: ${state}`);
    // Optionally: fallback to idle.gif
  };
});
```

---

## Extensibility Examples

### Adding a New State (Future)

**Step 1**: Add to STATE_CONFIG in `stateManager.js`:
```javascript
const STATE_CONFIG = {
  idle: { gif: 'idle.gif' },
  dragged: { gif: 'float.gif' },
  // NEW STATE:
  sleeping: {
    gif: 'sleep.gif',
    // duration: 10000,  // Wake up after 10s
  },
};
```

**Step 2**: Trigger from anywhere:
```javascript
// From renderer (user clicks "sleep" button)
window.electronAPI.changeState('sleeping');

// From main (timer trigger)
setTimeout(() => {
  mainWindow.webContents.send('state-changed', {
    state: 'sleeping',
    gifPath: path.join(__dirname, 'assets/Fluffball/animations/sleep.gif')
  });
}, 60000); // After 1 minute
```

That's it! No other code changes needed.

---

### Future: AI-Driven States

**Replace StateManager with AIStateManager**:
```javascript
// In main.js
const AIStateManager = require('./aiStateManager');
const stateManager = new AIStateManager('idle');

// IPC handlers unchanged - same interface!
```

**AIStateManager extends StateManager**:
```javascript
class AIStateManager extends StateManager {
  async decideNextState(context) {
    const decision = await callGeminiAPI({
      currentState: this.currentState,
      context: context
    });
    return this.setState(decision.state);
  }
}
```

---

## Open Questions for Implementation

- [ ] **GIF Preloading**: Should we preload float.gif on startup to ensure instant transition? (Probably not needed - GIFs are small)

- [ ] **State Validation**: Should we validate state names in renderer before sending IPC? (No - let main process be source of truth)

- [ ] **Error Recovery**: If state change fails, should we retry or fall back to idle? (Current: log error, stay in current state)

- [ ] **DevTools**: Should we add a dev command to trigger any state? (Useful for testing, add later)

---

## Next Steps

✅ Review this implementation plan
⬜ Execute Phase 1: Create stateManager.js (Step 1)
⬜ Execute Phase 2: Integrate into main.js (Step 2)
⬜ Execute Phase 3: Update preload.js (Step 3)
⬜ Execute Phase 4: Update renderer drag handlers (Step 4)
⬜ Execute Phase 5: Add state listener (Step 5)
⬜ Execute Phase 6: Manual testing (Step 6)
⬜ Update CLAUDE.md documentation

---

**Estimated time**: 1-2 hours for implementation + testing
**Files to create**: 1 (stateManager.js)
**Files to modify**: 3 (main.js, preload.js, app.js)
**Lines of code to add**: ~100 total

Does this implementation approach look good? Should I proceed with writing the code?
