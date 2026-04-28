# Implementation Plan: Pet Wander Behavior

## Overview

Adding autonomous movement to the desktop pet with a new WanderManager module. The pet will randomly pick positions on screen and smoothly move there via linear interpolation, displaying hop.gif during movement. Triggered by random timers (2-5 min) or right-click (test mode).

---

## File Manifest

### New Files to Create

**`electron-pet/wanderManager.js`**
- Purpose: Movement logic, timing, target selection
- Why: Decoupled module for wander behavior (testable, replaceable)

### Files to Modify

**`electron-pet/stateManager.js`**
- Add: 'wander' state to STATE_CONFIG
- Why: New state for hopping animation during movement

**`electron-pet/main.js`**
- Add: Require WanderManager, instantiate after window creation
- Add: 3 new IPC handlers (trigger-wander, cancel-wander, set-wander-enabled)
- Why: Wire WanderManager to IPC layer

**`electron-pet/preload.js`**
- Add: 3 new API methods to `electronAPI`
- Why: Expose wander controls to renderer

**`electron-pet/renderer/app.js`**
- Modify: `handleMouseDown()` - call cancelWander before changing state
- Modify: `contextmenu` event - trigger wander on right-click (test mode)
- Why: Cancel wander on drag, test trigger on right-click

### Files to Delete
```
(none)
```

---

## Implementation Steps

### Phase 1: State Configuration

#### Step 1: Add 'wander' state to StateManager
- **File**: `electron-pet/stateManager.js`
- **Task**: Add new state to STATE_CONFIG
- **Dependencies**: None
- **Changes**: Add 'wander' entry with hop.gif

**Success criteria**: StateManager can transition to 'wander' state

---

### Phase 2: WanderManager Module

#### Step 2: Create WanderManager class
- **File**: `electron-pet/wanderManager.js`
- **Task**: Implement complete WanderManager with all methods
- **Dependencies**: Step 1 (will use stateManager)
- **Methods to implement**:
  - `constructor(window, stateManager)`
  - `startTimer()`
  - `stopTimer()`
  - `wander()`
  - `getRandomTarget()`
  - `moveToTarget(target)`
  - `cancelWander()`
  - `setEnabled(enabled)`
  - Helper: `randomBetween(min, max)`

**Success criteria**: WanderManager can be required and instantiated

---

### Phase 3: Main Process Integration

#### Step 3: Integrate WanderManager into main.js
- **File**: `electron-pet/main.js`
- **Task**: Add WanderManager require, instantiation, and IPC handlers
- **Dependencies**: Step 2 (needs wanderManager.js)
- **Changes**:
  - Import WanderManager at top
  - Declare `wanderManager` variable
  - Instantiate in `app.whenReady()` after createWindow
  - Call `wanderManager.startTimer()`
  - Add 3 IPC handlers

**Success criteria**: Main process has wander manager and IPC responds

---

### Phase 4: Preload API

#### Step 4: Add wander APIs to preload
- **File**: `electron-pet/preload.js`
- **Task**: Expose 3 wander methods via contextBridge
- **Dependencies**: Step 3 (IPC handlers must exist)
- **Changes**: Add triggerWander, cancelWander, setWanderEnabled

**Success criteria**: Renderer can call wander APIs

---

### Phase 5: Renderer Updates

#### Step 5: Update renderer for wander control
- **File**: `electron-pet/renderer/app.js`
- **Task**: Add cancel on drag, trigger on right-click
- **Dependencies**: Step 4 (needs preload APIs)
- **Changes**:
  - In `handleMouseDown()`: Add `window.electronAPI.cancelWander()`
  - In `contextmenu` listener: Replace with `window.electronAPI.triggerWander()`

**Success criteria**: Dragging cancels wander, right-click triggers it

---

### Phase 6: Testing

#### Step 6: Manual testing
- **Task**: Verify all functional requirements
- **Dependencies**: All previous steps
- **Test scenarios**: See Test Plan section below

**Success criteria**: All acceptance tests pass

---

## Code Structure

### `electron-pet/stateManager.js` (MODIFIED)

**Change to STATE_CONFIG**:

**Current** (lines 12-33):
```javascript
const STATE_CONFIG = {
  idle: {
    gif: 'idle.gif',
    // ...
  },
  dragged: {
    gif: 'float.gif',
    // ...
  },
  // Future states (placeholder):
  // clicked: { gif: 'bounce.gif' },
  // sleeping: { gif: 'sleep.gif' },
  // curious: { gif: 'curious_look.gif' },
  // wiggle: { gif: 'wiggle_ears.gif' },
  // hop: { gif: 'hop.gif' },
};
```

**New**:
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
  wander: {
    gif: 'hop.gif',
    // Future properties (placeholder):
    // speed: 200,           // pixels per second
    // trajectory: 'linear', // linear, bezier, random
    // duration: null,
    // transitions: [],
    // sound: null,
  },
  // Future states (placeholder):
  // clicked: { gif: 'bounce.gif' },
  // sleeping: { gif: 'sleep.gif' },
  // curious: { gif: 'curious_look.gif' },
  // wiggle: { gif: 'wiggle_ears.gif' },
};
```

---

### `electron-pet/wanderManager.js` (NEW)

**Purpose**: Autonomous movement manager

**Full implementation**:

```javascript
/**
 * WanderManager - Autonomous pet movement
 *
 * Manages random wandering behavior with smooth movement animation.
 * Decoupled from main process for testing and AI integration.
 */

const { screen } = require('electron');

/**
 * Helper: Generate random number between min and max (inclusive)
 * @param {number} min - Minimum value
 * @param {number} max - Maximum value
 * @returns {number} Random integer
 */
function randomBetween(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

/**
 * WanderManager class
 * Handles timing, target selection, and smooth movement
 */
class WanderManager {
  /**
   * Create a new WanderManager
   * @param {BrowserWindow} window - The pet window
   * @param {StateManager} stateManager - State manager instance
   */
  constructor(window, stateManager) {
    this.window = window;
    this.stateManager = stateManager;
    this.isWandering = false;
    this.wanderTimer = null;
    this.animationTimeout = null;
    this.enabled = true; // Feature flag for right-click trigger
  }

  /**
   * Start the random wander timer
   * Schedules wander at random 2-5 minute intervals
   */
  startTimer() {
    // Random interval between 2-5 minutes (in milliseconds)
    const interval = randomBetween(120000, 300000);

    this.wanderTimer = setTimeout(() => {
      this.wander();
      // Reschedule next wander
      this.startTimer();
    }, interval);

    console.log(`Next wander scheduled in ${Math.round(interval / 1000)}s`);
  }

  /**
   * Stop the wander timer
   */
  stopTimer() {
    if (this.wanderTimer) {
      clearTimeout(this.wanderTimer);
      this.wanderTimer = null;
    }
  }

  /**
   * Execute a wander to random position
   * @returns {Promise<void>} Resolves when movement complete
   */
  async wander() {
    // Don't start new wander if already wandering
    if (this.isWandering) {
      console.log('Already wandering, skipping');
      return;
    }

    try {
      const target = this.getRandomTarget();
      await this.moveToTarget(target);
    } catch (error) {
      console.error('Wander error:', error);
      this.isWandering = false;
      this.stateManager.setState('idle');
    }
  }

  /**
   * Get random target position on current screen
   * Ensures pet stays fully on-screen
   * @returns {{x: number, y: number}} Target coordinates
   */
  getRandomTarget() {
    // Get current window position
    const currentPos = this.window.getPosition();

    // Get display containing the current window
    const display = screen.getDisplayNearestPoint({
      x: currentPos[0],
      y: currentPos[1]
    });

    const { x, y, width, height } = display.bounds;
    const windowSize = this.window.getSize();
    const windowWidth = windowSize[0];
    const windowHeight = windowSize[1];

    // Calculate valid range to keep window fully on-screen
    const minX = x;
    const maxX = x + width - windowWidth;
    const minY = y;
    const maxY = y + height - windowHeight;

    const targetX = randomBetween(minX, maxX);
    const targetY = randomBetween(minY, maxY);

    console.log(`Wander target: (${targetX}, ${targetY})`);

    return { x: targetX, y: targetY };
  }

  /**
   * Smoothly move window to target position
   * Uses linear interpolation over fixed 2-second duration
   * @param {{x: number, y: number}} target - Target coordinates
   * @returns {Promise<void>} Resolves when movement complete
   */
  async moveToTarget(target) {
    const startPos = this.window.getPosition();
    const startTime = Date.now();
    const duration = 2000; // 2 seconds

    this.isWandering = true;

    // Change state to wander (triggers hop.gif)
    const gifFileName = this.stateManager.setState('wander');
    const gifPath = require('path').join(
      __dirname,
      'assets',
      'Fluffball',
      'animations',
      gifFileName
    );

    // Notify renderer of state change
    this.window.webContents.send('state-changed', {
      state: 'wander',
      gifPath: gifPath
    });

    return new Promise((resolve) => {
      const animate = () => {
        // Check if cancelled
        if (!this.isWandering) {
          resolve();
          return;
        }

        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);

        // Linear interpolation
        const x = startPos[0] + (target.x - startPos[0]) * progress;
        const y = startPos[1] + (target.y - startPos[1]) * progress;

        this.window.setPosition(Math.round(x), Math.round(y));

        if (progress < 1) {
          // Continue animation
          this.animationTimeout = setTimeout(animate, 16); // ~60fps
        } else {
          // Movement complete
          this.isWandering = false;

          // Return to idle state
          const idleGif = this.stateManager.setState('idle');
          const idlePath = require('path').join(
            __dirname,
            'assets',
            'Fluffball',
            'animations',
            idleGif
          );

          this.window.webContents.send('state-changed', {
            state: 'idle',
            gifPath: idlePath
          });

          console.log('Wander complete');
          resolve();
        }
      };

      animate();
    });
  }

  /**
   * Cancel current wander
   * Called when user drags pet or interrupts movement
   */
  cancelWander() {
    if (!this.isWandering) {
      return;
    }

    console.log('Wander cancelled');

    // Stop animation
    this.isWandering = false;
    if (this.animationTimeout) {
      clearTimeout(this.animationTimeout);
      this.animationTimeout = null;
    }

    // Return to idle state
    try {
      const idleGif = this.stateManager.setState('idle');
      const idlePath = require('path').join(
        __dirname,
        'assets',
        'Fluffball',
        'animations',
        idleGif
      );

      this.window.webContents.send('state-changed', {
        state: 'idle',
        gifPath: idlePath
      });
    } catch (error) {
      console.error('Error returning to idle:', error);
    }
  }

  /**
   * Enable or disable wander feature
   * @param {boolean} enabled - True to enable, false to disable
   */
  setEnabled(enabled) {
    this.enabled = enabled;
    console.log(`Wander feature ${enabled ? 'enabled' : 'disabled'}`);
  }
}

module.exports = WanderManager;
```

---

### `electron-pet/main.js` (MODIFIED)

**Changes to add**:

**At top** (after existing requires, line 4):
```javascript
const WanderManager = require('./wanderManager');
```

**After stateManager declaration** (line 7):
```javascript
let wanderManager = null;
```

**In `app.whenReady()`** (after createWindow call, around line 138):
```javascript
app.whenReady().then(() => {
  // Initialize state manager
  stateManager = new StateManager('idle');

  createWindow();

  // Initialize wander manager after window created
  wanderManager = new WanderManager(mainWindow, stateManager);
  wanderManager.startTimer();

  // macOS: Re-create window when dock icon clicked
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});
```

**New IPC handlers** (add after get-current-state handler, before "App lifecycle"):
```javascript
// Trigger wander (for right-click testing)
ipcMain.on('trigger-wander', (event) => {
  if (wanderManager && wanderManager.enabled) {
    wanderManager.wander();
  }
});

// Cancel wander (called when user starts dragging)
ipcMain.on('cancel-wander', (event) => {
  if (wanderManager && wanderManager.isWandering) {
    wanderManager.cancelWander();
  }
});

// Enable/disable wander feature
ipcMain.on('set-wander-enabled', (event, enabled) => {
  if (wanderManager) {
    wanderManager.setEnabled(enabled);
  }
});
```

---

### `electron-pet/preload.js` (MODIFIED)

**Inside `electronAPI` object** (add after getCurrentState):
```javascript
contextBridge.exposeInMainWorld('electronAPI', {
  // ... existing APIs ...

  /**
   * Trigger wander behavior (test only)
   */
  triggerWander: () => ipcRenderer.send('trigger-wander'),

  /**
   * Cancel current wander
   */
  cancelWander: () => ipcRenderer.send('cancel-wander'),

  /**
   * Enable/disable wander feature
   * @param {boolean} enabled
   */
  setWanderEnabled: (enabled) => ipcRenderer.send('set-wander-enabled', enabled)
});
```

---

### `electron-pet/renderer/app.js` (MODIFIED)

**Modification 1: Cancel wander on drag start**

**Current** `handleMouseDown()` (lines 31-43):
```javascript
function handleMouseDown(event) {
  isDragging = true;
  mouseOffsetX = event.clientX;
  mouseOffsetY = event.clientY;
  petContainer.classList.add('dragging');

  // Change state to 'dragged'
  window.electronAPI.changeState('dragged');
}
```

**New**:
```javascript
function handleMouseDown(event) {
  isDragging = true;
  mouseOffsetX = event.clientX;
  mouseOffsetY = event.clientY;
  petContainer.classList.add('dragging');

  // Cancel any ongoing wander
  window.electronAPI.cancelWander();

  // Change state to 'dragged'
  window.electronAPI.changeState('dragged');
}
```

---

**Modification 2: Right-click trigger (test mode)**

**Current** `contextmenu` listener (lines 92-94):
```javascript
// Prevent context menu (right-click) for cleaner UX
document.addEventListener('contextmenu', (event) => {
  event.preventDefault();
});
```

**New**:
```javascript
// Right-click handler
document.addEventListener('contextmenu', (event) => {
  event.preventDefault();

  // TEMP: Trigger wander on right-click for testing
  // TODO: Remove this or add feature flag when done testing
  window.electronAPI.triggerWander();
});
```

---

## Data Flow

### Auto Wander Flow
```
Timer fires (2-5 min)
  ↓
[wanderManager] wander()
  ↓
getRandomTarget() → {x: 450, y: 300}
  ↓
Check isWandering (skip if true)
  ↓
moveToTarget(target)
  ↓
isWandering = true
  ↓
stateManager.setState('wander')
  ↓
window.webContents.send('state-changed', {state: 'wander', gifPath: 'hop.gif'})
  ↓
[renderer] onStateChanged → petGif.src = 'hop.gif'
  ↓
Animation loop (60fps):
  Calculate progress (elapsed / 2000)
  Lerp position: x = startX + (targetX - startX) * progress
  window.setPosition(x, y)
  ↓
Progress reaches 1.0
  ↓
isWandering = false
  ↓
stateManager.setState('idle')
  ↓
window.webContents.send('state-changed', {state: 'idle', gifPath: 'idle.gif'})
  ↓
[renderer] onStateChanged → petGif.src = 'idle.gif'
  ↓
startTimer() reschedules next wander
```

### Right-Click Trigger Flow
```
User right-clicks pet
  ↓
[renderer] contextmenu event
  ↓
event.preventDefault()
  ↓
window.electronAPI.triggerWander()
  ↓
IPC → main.js receives 'trigger-wander'
  ↓
if (wanderManager.enabled):
  wanderManager.wander()
  ↓
(same flow as auto wander)
```

### Drag Cancellation Flow
```
Pet is wandering (hop.gif showing, moving)
  ↓
User clicks to drag
  ↓
[renderer] handleMouseDown()
  ↓
window.electronAPI.cancelWander()
  ↓
IPC → main.js receives 'cancel-wander'
  ↓
if (wanderManager.isWandering):
  wanderManager.cancelWander()
  ↓
isWandering = false
  ↓
clearTimeout(animationTimeout)
  ↓
stateManager.setState('idle')
  ↓
window.webContents.send('state-changed', {state: 'idle', gifPath: 'idle.gif'})
  ↓
[renderer] continues with drag (state changes to 'dragged')
```

---

## Test Plan

### Manual Testing (Step 6)

**Test 1: Auto Wander**
- Action: Launch app → Wait 2-5 minutes
- Expected: Pet wanders to random position automatically
- Verify: hop.gif displays, movement is smooth

**Test 2: Right-Click Trigger**
- Action: Right-click pet
- Expected: Immediate wander
- Verify: Same smooth movement as Test 1

**Test 3: Smooth Movement**
- Action: Trigger wander, watch closely
- Expected: Linear movement, no jumps or stutters
- Verify: ~2 second duration, 60fps smoothness

**Test 4: Drag Cancellation**
- Action: Trigger wander → Immediately drag pet mid-movement
- Expected: Wander stops, drag works normally
- Verify: State changes to 'dragged', hop.gif stops

**Test 5: Bounds Testing**
- Action: Trigger wander 20+ times
- Expected: Pet always stays fully on-screen
- Verify: All parts of window visible

**Test 6: Timer Continuity**
- Action: Wait for 3 auto-wanders (6-15 minutes)
- Expected: Wanders happen continuously
- Verify: Each wander completes and reschedules next

**Test 7: Concurrent Wander Prevention**
- Action: Rapid right-clicks during wander
- Expected: Only one wander at a time
- Verify: Console logs "Already wandering, skipping"

**Test 8: State Transitions**
- Action: Observe state during complete cycle
- Expected: idle → wander → idle
- Verify: GIF changes correctly each time

---

## Configuration & Dependencies

### No New Dependencies
```
(all features use existing Electron APIs)
```

---

## Open Questions for Implementation

- [ ] **Easing function**: Currently linear, consider ease-in-out for more natural movement? (Start with linear)
- [ ] **Duration scaling**: Fixed 2s or based on distance? (Start with fixed 2s)
- [ ] **Timer persistence**: Save timer state between sessions? (No for now)
- [ ] **Feature flag location**: Hardcoded `enabled` or config file? (Hardcoded for MVP)

---

## Next Steps

✅ Review this implementation plan
⬜ Execute Phase 1: Add 'wander' state (Step 1)
⬜ Execute Phase 2: Create WanderManager (Step 2)
⬜ Execute Phase 3: Integrate into main.js (Step 3)
⬜ Execute Phase 4: Update preload (Step 4)
⬜ Execute Phase 5: Update renderer (Step 5)
⬜ Execute Phase 6: Testing (Step 6)
⬜ Update CLAUDE.md documentation

---

**Estimated time**: 2-3 hours for implementation + testing
**Files to create**: 1 (wanderManager.js)
**Files to modify**: 4 (stateManager.js, main.js, preload.js, app.js)
**Lines of code to add**: ~250 total (WanderManager is ~180 lines)

Does this implementation approach look good? Should I proceed with writing the code?
