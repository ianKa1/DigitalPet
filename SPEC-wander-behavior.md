# Feature Specification: Pet Wander Behavior

## Overview

Add autonomous movement to the desktop pet with a "wander" state. The pet randomly picks a position on screen and smoothly moves there, displaying a hopping animation. This makes the pet feel alive and interactive even when the user isn't directly interacting with it.

## Problem Statement

**Current state**: The pet is completely passive - it only moves when dragged by the user. It sits statically in one position, which makes it feel lifeless.

**User need**: Users want the pet to feel autonomous and alive, occasionally moving around the desktop on its own to create a sense of personality and presence.

**Target users**: Desktop pet users who want their pet to be an active companion, not just a static decoration.

## Proposed Solution

Implement a "wander" behavior system that:
1. Adds a new "wander" state to StateManager with hop.gif animation
2. Randomly picks a target position on the current screen
3. Smoothly moves the pet along a straight line to the target
4. Triggers via random timer (2-5 minute intervals) or right-click (test only)
5. Cancels if user interrupts by dragging
6. Keeps pet fully on-screen at all times

**Why this approach**:
- Extends existing StateManager architecture (consistent with drag behavior)
- Straight-line movement is simple and performant
- Timer-based triggering creates unpredictable, lifelike behavior
- Architecture allows future enhancements (custom paths, AI-driven targets)

## Technical Design

### Architecture Overview

```
Main Process:
  stateManager.js       # Add 'wander' state
  wanderManager.js      # Movement logic, timers (NEW)
  main.js               # Wire wanderManager, add IPC handlers

Renderer:
  app.js                # Trigger wander on right-click, cancel on drag
```

### Components

#### 1. StateManager Update (`stateManager.js`)

**Add new state to STATE_CONFIG**:
```javascript
const STATE_CONFIG = {
  idle: { gif: 'idle.gif' },
  dragged: { gif: 'float.gif' },
  wander: {
    gif: 'hop.gif',
    // Future properties:
    // speed: 200,           // pixels per second
    // trajectory: 'linear', // linear, bezier, random
  }
};
```

#### 2. WanderManager Module (`wanderManager.js`) - NEW

**Responsibility**: Manages wander timing, target selection, and smooth movement

**Class: WanderManager**

```javascript
class WanderManager {
  constructor(window, stateManager) {
    this.window = window;           // BrowserWindow instance
    this.stateManager = stateManager;
    this.isWandering = false;
    this.wanderTimer = null;
    this.animationFrame = null;
    this.enabled = true;            // Feature flag (disable right-click trigger)
  }

  // Start the random wander timer
  startTimer() {
    // Schedules wander every 2-5 minutes
  }

  // Stop the timer
  stopTimer() {
    clearTimeout(this.wanderTimer);
  }

  // Execute a wander to random position
  async wander() {
    const target = this.getRandomTarget();
    await this.moveToTarget(target);
  }

  // Get random position on current screen, fully on-screen
  getRandomTarget() {
    // Returns {x, y} within screen bounds
  }

  // Smoothly move window to target position
  async moveToTarget(target) {
    // Linear interpolation, update position each frame
  }

  // Cancel current wander (called when user drags)
  cancelWander() {
    // Stop animation, return to idle
  }

  // Enable/disable feature
  setEnabled(enabled) {
    this.enabled = enabled;
  }
}
```

**Key Methods Detail**:

**`startTimer()`**
- Purpose: Schedule next wander at random interval
- Logic:
  ```javascript
  const interval = randomBetween(120000, 300000); // 2-5 min in ms
  this.wanderTimer = setTimeout(() => {
    this.wander();
    this.startTimer(); // Reschedule
  }, interval);
  ```

**`getRandomTarget()`**
- Purpose: Pick valid target position
- Input: None
- Returns: `{x: number, y: number}` screen coordinates
- Logic:
  1. Get current screen bounds using `screen.getPrimaryDisplay()` or current display
  2. Get window size (200x200)
  3. Calculate valid range: `[0 to screenWidth-200, 0 to screenHeight-200]`
  4. Return random point within range
- Constraints: Target must keep window fully visible

**`moveToTarget(target)`**
- Purpose: Smoothly move window from current position to target
- Input: `{x, y}` target coordinates
- Returns: Promise (resolves when movement complete)
- Logic:
  1. Change state to 'wander'
  2. Get current position
  3. Calculate total distance and duration (e.g., 2 seconds for any distance)
  4. Use `requestAnimationFrame` loop to interpolate position
  5. Update window position each frame via `window.setPosition()`
  6. When complete, change state back to 'idle'
- Movement: Linear interpolation (lerp)
  ```javascript
  currentPos = lerp(startPos, targetPos, progress)
  ```

**`cancelWander()`**
- Purpose: Interrupt wander when user drags
- Logic:
  1. Stop animation frame loop
  2. Change state to 'idle'
  3. Set `isWandering = false`

#### 3. Main Process (`main.js`)

**New initialization**:
```javascript
const WanderManager = require('./wanderManager');
let wanderManager = null;

app.whenReady().then(() => {
  stateManager = new StateManager('idle');
  createWindow();

  // Initialize wander manager after window created
  wanderManager = new WanderManager(mainWindow, stateManager);
  wanderManager.startTimer();
});
```

**New IPC Handlers**:
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

#### 4. Preload Script (`preload.js`)

**New APIs**:
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

#### 5. Renderer (`app.js`)

**Modification 1: Cancel wander on drag start**

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

**Addition 2: Right-click trigger (test only)**

```javascript
// Replace existing contextmenu prevention
document.addEventListener('contextmenu', (event) => {
  event.preventDefault();

  // TEMP: Trigger wander on right-click for testing
  // TODO: Remove this or add feature flag when done testing
  window.electronAPI.triggerWander();
});
```

**Future: Disable right-click trigger**
```javascript
// Production version (future)
const WANDER_TEST_MODE = false; // Feature flag

document.addEventListener('contextmenu', (event) => {
  event.preventDefault();

  if (WANDER_TEST_MODE) {
    window.electronAPI.triggerWander();
  }
});
```

### Data Flow

#### Automatic Wander Flow (Timer)
```
Timer fires (2-5 min)
  ↓
[main.js] wanderManager.wander()
  ↓
getRandomTarget() → {x: 450, y: 300}
  ↓
stateManager.setState('wander')
  ↓
Send 'state-changed' → renderer shows hop.gif
  ↓
moveToTarget() starts animation loop
  ↓
Each frame (60fps):
  currentPos = lerp(startPos, targetPos, progress)
  window.setPosition(currentPos.x, currentPos.y)
  ↓
Movement complete (after ~2 seconds)
  ↓
stateManager.setState('idle')
  ↓
Send 'state-changed' → renderer shows idle.gif
  ↓
startTimer() → schedule next wander
```

#### Right-Click Trigger Flow (Test)
```
User right-clicks pet
  ↓
[renderer] contextmenu event
  ↓
electronAPI.triggerWander()
  ↓
[main.js] receives 'trigger-wander' IPC
  ↓
if (wanderManager.enabled):
  wanderManager.wander()
  ↓
(same flow as automatic wander)
```

#### Drag Cancellation Flow
```
User drags pet during wander
  ↓
[renderer] handleMouseDown()
  ↓
electronAPI.cancelWander()
  ↓
[main.js] wanderManager.cancelWander()
  ↓
Stop animation loop
  ↓
stateManager.setState('idle')
  ↓
(normal drag behavior continues)
```

### Movement Algorithm

**Linear interpolation (lerp)**:
```javascript
async function moveToTarget(target) {
  const start = this.window.getPosition();
  const startTime = Date.now();
  const duration = 2000; // 2 seconds

  this.isWandering = true;
  this.stateManager.setState('wander');

  return new Promise((resolve) => {
    const animate = () => {
      const elapsed = Date.now() - startTime;
      const progress = Math.min(elapsed / duration, 1);

      // Linear interpolation
      const x = start[0] + (target.x - start[0]) * progress;
      const y = start[1] + (target.y - start[1]) * progress;

      this.window.setPosition(Math.round(x), Math.round(y));

      if (progress < 1 && this.isWandering) {
        this.animationFrame = setImmediate(animate);
      } else {
        this.isWandering = false;
        this.stateManager.setState('idle');
        resolve();
      }
    };

    animate();
  });
}
```

### Screen Bounds Calculation

```javascript
function getRandomTarget() {
  const { screen } = require('electron');
  const display = screen.getDisplayNearestPoint(this.window.getPosition());
  const { x, y, width, height } = display.bounds;

  const windowSize = this.window.getSize();
  const windowWidth = windowSize[0];   // 200
  const windowHeight = windowSize[1];  // 200

  // Valid range keeps window fully on-screen
  const minX = x;
  const maxX = x + width - windowWidth;
  const minY = y;
  const maxY = y + height - windowHeight;

  return {
    x: randomInt(minX, maxX),
    y: randomInt(minY, maxY)
  };
}
```

## Success Criteria

### Functional Requirements

✅ **Must have**:
1. Pet displays hop.gif when wandering
2. Pet moves smoothly to random position every 2-5 minutes
3. Movement is straight-line interpolation
4. Right-click triggers wander (test mode)
5. Dragging pet cancels ongoing wander
6. Pet stays fully on-screen (current display)
7. Timer runs continuously (not paused)

✅ **Should have** (extensibility):
8. WanderManager is decoupled and replaceable
9. Movement algorithm is configurable (placeholders for future)
10. Right-click trigger can be disabled via flag

### Non-Functional Requirements

- **Performance**: Movement at 60fps, smooth visual transition
- **Timing accuracy**: Random interval within ±10% of target
- **Reliability**: Wander doesn't freeze app or cause lag
- **Multi-screen**: Correctly detects current screen bounds

### Acceptance Tests

1. **Auto wander**: Wait 2-5 min → Pet wanders to random spot
2. **Animation**: During wander → hop.gif displays continuously
3. **Smooth movement**: Movement is visually smooth, no jumps
4. **Right-click**: Right-click → Pet wanders immediately
5. **Drag cancellation**: Start wander → Drag pet → Wander stops
6. **Bounds**: Pet never goes off-screen or partially hidden
7. **Timer continuity**: After wander completes → Timer restarts for next wander
8. **Multi-wander**: Pet wanders multiple times → Works consistently

## Non-Goals

**Explicitly out of scope for this iteration**:
- Custom trajectories (bezier curves, arc paths)
- Variable movement speed
- Collision avoidance (obstacles, screen edges)
- Manual target selection (user clicks destination)
- Pathfinding around windows
- Animation variations (different hop styles)
- Sound effects during wander
- Pause wander during user activity
- Wander history/logging

**Future considerations** (extensibility placeholders):
- **Manual targeting**: `wanderManager.wanderTo(x, y)` method signature
- **Custom trajectories**: `trajectory` property in state config
  ```javascript
  wander: {
    gif: 'hop.gif',
    trajectory: 'bezier',  // linear, bezier, random
    trajectoryConfig: {
      controlPoints: [...],
      curvature: 0.5
    }
  }
  ```
- **Speed control**: `speed` property (pixels per second)
- **AI-driven targets**: `AIWanderManager extends WanderManager` with smart positioning
- **Pause conditions**: `pauseWhen: ['userActivity', 'fullscreen']`

## Implementation Notes

### Timer Management

**Random interval generation**:
```javascript
function randomBetween(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

const interval = randomBetween(120000, 300000); // 2-5 min
```

**Timer runs continuously**:
- After each wander completes, immediately schedule next one
- Don't reset timer on user interactions (drag, etc.)
- Timer persists for app lifetime

### Movement Performance

**Use `setImmediate` vs `requestAnimationFrame`**:
- Main process doesn't have `requestAnimationFrame`
- Use `setImmediate` for animation loop
- Aim for ~60fps (16ms per frame)

**Optimization**:
```javascript
const targetFps = 60;
const frameDelay = 1000 / targetFps;
let lastFrame = Date.now();

const animate = () => {
  const now = Date.now();
  if (now - lastFrame < frameDelay) {
    setImmediate(animate);
    return;
  }
  lastFrame = now;

  // Update position
  // ...
};
```

### Screen Detection

**Get current screen**:
```javascript
const { screen } = require('electron');
const currentPos = window.getPosition();
const display = screen.getDisplayNearestPoint(currentPos);
```

**Handle multi-monitor**:
- Only consider current display bounds
- If pet is on display A, pick target on display A only
- Don't wander across displays (future feature)

### State Cancellation

**Race condition handling**:
- Check `isWandering` flag before state changes
- Cancel animation frame cleanly
- Don't change state if already cancelled

```javascript
cancelWander() {
  if (!this.isWandering) return;

  this.isWandering = false;
  clearImmediate(this.animationFrame);
  this.stateManager.setState('idle');
}
```

## Open Questions

- [ ] **Movement duration**: Fixed 2 seconds, or based on distance? (Current: Fixed 2s for simplicity)
- [ ] **Easing function**: Linear interpolation, or ease-in-out for more natural movement? (Current: Linear)
- [ ] **Timer persistence**: Should timer state save between sessions? (Current: No, timer resets on restart)
- [ ] **Collision with edges**: Should pet "bounce" if target is near edge, or just stop? (Current: Doesn't go to edges)

## Testing Strategy

### Manual Testing

**Test 1: Auto Wander**
- Start app → Wait up to 5 minutes
- Expected: Pet wanders to random location
- Verify: hop.gif displays, movement is smooth

**Test 2: Right-Click Trigger**
- Right-click pet
- Expected: Immediate wander
- Verify: Same as Test 1

**Test 3: Drag Cancellation**
- Trigger wander → Immediately drag pet
- Expected: Wander stops, drag works normally
- Verify: State changes to 'dragged', no hop.gif

**Test 4: Bounds Testing**
- Trigger wander 20+ times
- Expected: Pet always stays fully on-screen
- Verify: No part of window goes off-screen

**Test 5: Multi-Monitor** (if applicable)
- Move pet to secondary display
- Trigger wander
- Expected: Pet wanders within that display only
- Verify: Doesn't jump to primary display

**Test 6: Timer Continuity**
- Wait for 3 wanders (6-15 minutes)
- Expected: Each wander schedules the next
- Verify: Timer doesn't stop after first wander

### Edge Cases

- Wander during app startup (should not trigger before window ready)
- Wander when window is minimized (should skip or queue)
- Rapid right-clicks (should not trigger multiple simultaneous wanders)
- Screen resolution change mid-wander (should cancel or adapt)

## File Structure

```
electron-pet/
├── main.js              # Wire wanderManager, add IPC (modified)
├── stateManager.js      # Add 'wander' state (modified)
├── wanderManager.js     # Movement logic, timers (NEW)
├── preload.js           # Add wander APIs (modified)
├── renderer/
│   └── app.js           # Cancel on drag, right-click trigger (modified)
└── assets/
    └── Fluffball/animations/
        └── hop.gif      # Wander animation (existing)
```

## Next Steps

1. Review and approve this specification
2. Create implementation plan
3. Implement WanderManager module
4. Update StateManager with 'wander' state
5. Add wander IPC handlers
6. Update renderer for cancellation
7. Test thoroughly (especially bounds and cancellation)
8. Add feature flag to disable right-click trigger in production

---

**Estimated Complexity**: Moderate (4-6 hours for full implementation + testing)

**Key Files to Create**: 1 (wanderManager.js)
**Key Files to Modify**: 4 (stateManager.js, main.js, preload.js, app.js)
