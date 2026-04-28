# Feature Specification: Pet Behavior States

## Overview

Add a behavior state system to the desktop pet that switches animations based on user interactions. When dragging, the pet displays "float.gif"; when idle, it shows "idle.gif". The system uses a decoupled StateManager module for easy extensibility to more complex behaviors (AI-driven, time-based, etc.) in the future.

## Problem Statement

**Current state**: The pet always displays `idle.gif` regardless of what's happening. Dragging the pet shows the same static animation, making it feel lifeless.

**User need**: The pet should react to interactions with appropriate animations - floating while being dragged, idle when stationary. This makes the pet feel more alive and responsive.

**Target users**: Desktop pet users who want their pet to feel interactive and dynamic.

## Proposed Solution

Implement a behavior state system with:
1. **State machine** in a decoupled `StateManager` module
2. **Two initial states**: `idle` (default) and `dragged` (during mouse drag)
3. **State-to-GIF mapping**: Each state maps to an animation file
4. **Extensible design**: Dictionary/interface to add new states without code restructuring
5. **Immediate transitions**: State changes trigger instant GIF swaps

**Architecture decision**: State logic lives in main process (StateManager module), renderer is a pure view layer. This enables future extensions like timers, AI agents, or system-event triggers.

## Technical Design

### Architecture Overview

```
Main Process:
  main.js              # IPC wiring, delegates to StateManager
  stateManager.js      # State machine logic (NEW)

Renderer:
  app.js               # Sends events, displays GIF based on state
```

### Components

#### 1. StateManager Module (`stateManager.js`)

**Responsibility**: Centralized state logic, transitions, and configuration

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

  // Get current state
  getCurrentState() {
    return this.currentState;
  }

  // Get GIF for current state
  getCurrentGif() {
    return this.stateConfig[this.currentState].gif;
  }

  // Transition to new state
  setState(newState) {
    if (!this.stateConfig[newState]) {
      throw new Error(`Unknown state: ${newState}`);
    }
    this.currentState = newState;
    return this.getCurrentGif();
  }

  // Check if state exists
  hasState(state) {
    return state in this.stateConfig;
  }

  // Get all available states
  getAvailableStates() {
    return Object.keys(this.stateConfig);
  }
}
```

#### 2. Main Process (`main.js`)

**New IPC Handlers**:

```javascript
const StateManager = require('./stateManager');
const stateManager = new StateManager('idle');

// Handle state change request from renderer
ipcMain.on('change-state', (event, newState) => {
  try {
    const gifPath = stateManager.setState(newState);
    const fullPath = path.join(__dirname, 'assets/Fluffball/animations', gifPath);

    // Send new GIF path back to renderer
    event.reply('state-changed', {
      state: newState,
      gifPath: fullPath
    });
  } catch (error) {
    console.error('State change error:', error);
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

#### 3. Preload Script (`preload.js`)

**New APIs**:
```javascript
contextBridge.exposeInMainWorld('electronAPI', {
  // ... existing APIs ...

  // Change pet state
  changeState: (state) => ipcRenderer.send('change-state', state),

  // Listen for state changes
  onStateChanged: (callback) => ipcRenderer.on('state-changed', (event, data) => callback(data)),

  // Get current state
  getCurrentState: () => ipcRenderer.invoke('get-current-state')
});
```

#### 4. Renderer (`app.js`)

**Modified drag handlers**:
```javascript
function handleMouseDown(event) {
  isDragging = true;
  mouseOffsetX = event.clientX;
  mouseOffsetY = event.clientY;
  petContainer.classList.add('dragging');

  // NEW: Change state to 'dragged'
  window.electronAPI.changeState('dragged');
}

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

**State change listener**:
```javascript
// Listen for state changes from main process
window.electronAPI.onStateChanged((data) => {
  const { state, gifPath } = data;

  // Update GIF immediately
  petGif.src = gifPath;

  // Optional: Log for debugging
  console.log(`State changed to: ${state}`);
});
```

**Initialization**:
```javascript
async function loadGif() {
  try {
    // Load initial state
    const { gif } = await window.electronAPI.getCurrentState();
    const gifPath = await window.electronAPI.getGifPath();
    petGif.src = gifPath;
  } catch (error) {
    console.error('Failed to load GIF:', error);
  }
}
```

### Data Flow

#### App Startup
```
App starts
  ↓
[main.js] stateManager = new StateManager('idle')
  ↓
[renderer] loadGif()
  ↓
getCurrentState() via IPC
  ↓
[main.js] returns { state: 'idle', gif: 'idle.gif' }
  ↓
[renderer] displays idle.gif
```

#### State Change (Drag Start)
```
User presses mouse
  ↓
[renderer] handleMouseDown()
  ↓
changeState('dragged') via IPC
  ↓
[main.js] receives 'change-state' event
  ↓
stateManager.setState('dragged')
  ↓
Returns 'float.gif'
  ↓
[main.js] event.reply('state-changed', { state: 'dragged', gifPath: '...' })
  ↓
[renderer] onStateChanged callback
  ↓
petGif.src = gifPath (float.gif)
  ↓
Pet displays floating animation
```

#### State Change (Drag End)
```
User releases mouse
  ↓
[renderer] handleMouseUp()
  ↓
changeState('idle') via IPC
  ↓
[main.js] stateManager.setState('idle')
  ↓
Returns 'idle.gif'
  ↓
[renderer] onStateChanged callback
  ↓
petGif.src = 'idle.gif'
  ↓
Pet displays idle animation
```

### File Structure

```
electron-pet/
├── main.js                    # IPC wiring (modified)
├── stateManager.js            # State machine module (NEW)
├── preload.js                 # Add state APIs (modified)
├── renderer/
│   └── app.js                 # State change triggers (modified)
└── assets/
    └── Fluffball/animations/
        ├── idle.gif           # Default state
        ├── float.gif          # Dragged state
        ├── bounce.gif         # (Future state)
        ├── sleep.gif          # (Future state)
        └── ...
```

### Extensibility Design

#### Adding New States (Future)

**Step 1**: Add to STATE_CONFIG
```javascript
const STATE_CONFIG = {
  // ... existing states ...
  sleeping: {
    gif: 'sleep.gif',
    duration: 5000,  // Auto-transition after 5s
    transitions: ['idle', 'curious'],  // Valid next states
  }
};
```

**Step 2**: Trigger state change from renderer or main
```javascript
// From renderer (user interaction)
window.electronAPI.changeState('sleeping');

// From main (timer/AI trigger)
setTimeout(() => {
  stateManager.setState('sleeping');
  mainWindow.webContents.send('state-changed', {
    state: 'sleeping',
    gifPath: path.join(__dirname, 'assets/Fluffball/animations/sleep.gif')
  });
}, 60000); // After 1 minute of idle
```

#### Future Extension: AI Agent

**StateManager can be replaced with AIStateManager**:
```javascript
class AIStateManager extends StateManager {
  async decideNextState(context) {
    // Call Gemini API with context
    const decision = await callGeminiAPI({
      currentState: this.currentState,
      timeOfDay: context.timeOfDay,
      userActivity: context.userActivity,
      personality: context.personality
    });

    return this.setState(decision.nextState);
  }
}
```

**No changes needed in**:
- main.js IPC handlers (same interface)
- renderer (same API)
- preload (same bridge)

#### Future Extension: Time-Based Transitions

```javascript
// In main.js
function setupTimers() {
  // After 5 minutes of idle, switch to sleeping
  let idleTimer = null;

  stateManager.on('state-changed', (newState) => {
    if (newState === 'idle') {
      idleTimer = setTimeout(() => {
        stateManager.setState('sleeping');
        notifyRenderer('sleeping');
      }, 5 * 60 * 1000);
    } else {
      clearTimeout(idleTimer);
    }
  });
}
```

## Success Criteria

### Functional Requirements

✅ **Must have**:
1. Pet displays `idle.gif` by default
2. Pet displays `float.gif` when being dragged
3. Pet immediately returns to `idle.gif` when drag ends
4. StateManager module is decoupled from main.js
5. New states can be added by editing STATE_CONFIG only
6. State changes are instant (no visible delay)

✅ **Should have** (extensibility):
7. State configuration includes placeholder for future properties (duration, transitions, sound)
8. StateManager class can be replaced/extended without changing IPC layer
9. Comments indicate where future states can be added

### Non-Functional Requirements

- **Performance**: State changes complete in <16ms (instant visual transition)
- **Reliability**: Invalid state names throw clear errors (don't crash app)
- **Maintainability**: Adding a new state requires changes in only one place (STATE_CONFIG)

### Acceptance Tests

1. **Default state**: Launch app → Pet shows idle.gif
2. **Drag start**: Click and start dragging → Pet switches to float.gif instantly
3. **Drag end**: Release mouse → Pet switches back to idle.gif instantly
4. **Multiple drags**: Drag multiple times → Transitions work every time
5. **Invalid state**: Call changeState('invalid') → Error logged, app doesn't crash
6. **Extensibility**: Add new state to STATE_CONFIG → Can trigger it without code changes

## Non-Goals

**Explicitly out of scope for this iteration**:
- Automatic state transitions (timers, random changes)
- AI-driven state decisions
- State transition animations (smooth blending between GIFs)
- Sound effects for states
- State persistence (remembering state between sessions)
- Multiple states active simultaneously
- State history/logging

**Future considerations**:
- Event-based state machine (emit events on transitions)
- State duration limits (auto-transition after time)
- State transition rules (valid next states)
- Context-aware states (time of day, user activity)
- Personality system (different pets react differently)
- State analytics (which states are most common)

## Implementation Notes

### State Configuration Format

The STATE_CONFIG object uses this structure:
```javascript
{
  stateName: {
    gif: 'filename.gif',          // Required
    // duration: number,          // Optional: ms before auto-transition
    // transitions: string[],     // Optional: valid next states
    // sound: 'filename.mp3',     // Optional: audio to play
    // priority: number,          // Optional: for conflict resolution
  }
}
```

For MVP, only `gif` is required. Other properties are placeholders.

### Error Handling

**Invalid state name**:
```javascript
try {
  stateManager.setState('nonexistent');
} catch (error) {
  console.error('State error:', error.message);
  // Fall back to idle state
  stateManager.setState('idle');
}
```

**Missing GIF file**:
- Handle in renderer's `onStateChanged` callback
- If GIF fails to load, log error but don't crash
- Consider fallback to idle.gif

### Performance Considerations

- State changes are synchronous (no async needed for MVP)
- IPC round-trip should be <5ms on modern hardware
- GIF loading is browser-optimized (instant for small files)
- No batching needed - state changes are infrequent

### Testing Strategy

**Unit tests** (stateManager.test.js):
- Test `setState()` with valid states
- Test `setState()` with invalid states (should throw)
- Test `getCurrentGif()` returns correct file
- Test `getAvailableStates()` returns all states

**Integration tests**:
- Drag pet → verify float.gif loads
- Release pet → verify idle.gif loads
- Rapid drag/release cycles → verify no race conditions

**Manual tests**:
- Visual verification of GIF transitions
- Test with missing GIF files (error handling)
- Test state persistence across app restart (future)

## Open Questions

- [ ] **Transition smoothness**: Should there be a brief crossfade between GIFs, or instant swap is okay? (Current: instant)
- [ ] **State priority**: If multiple triggers happen simultaneously (e.g., click + timer), which wins? (Future consideration)
- [ ] **State persistence**: Should the pet remember its state between sessions? (Currently: always starts in 'idle')
- [ ] **Animation sync**: If returning to idle from dragged, should idle.gif restart from frame 0 or continue? (Current: browser default)

## Next Steps

1. Review and approve this specification
2. Create implementation plan (file-by-file breakdown)
3. Implement StateManager module
4. Add IPC handlers in main.js
5. Update preload.js with state APIs
6. Modify renderer drag handlers
7. Test state transitions
8. (Future) Extend with timers/AI/advanced features

**Estimated Complexity**: Moderate (1 day for MVP + state system)

**Key Files to Create**: 1 new file (stateManager.js)
**Key Files to Modify**: 3 files (main.js, preload.js, app.js)
