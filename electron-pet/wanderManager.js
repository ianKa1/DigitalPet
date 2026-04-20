/**
 * WanderManager - Autonomous pet movement controller
 *
 * Manages autonomous wandering behavior with smooth linear interpolation.
 * Handles random destination selection, movement animation, and screen boundary constraints.
 */

const { screen } = require('electron');

/**
 * Configuration constants
 */
const WANDER_CONFIG = {
  minInterval: 3000,      // Minimum ms between movements
  maxInterval: 8000,      // Maximum ms between movements
  fps: 60,                // Animation frame rate
  speed: 150,             // Pixels per second
  // Distance is calculated dynamically based on screen size:
  // - Horizontal: 1/5 to 2/5 of screen width
  // - Vertical: 1/5 to 2/5 of screen height
};

/**
 * WanderManager class
 * Handles autonomous wandering behavior with timer-based movement
 */
class WanderManager {
  /**
   * Create a new WanderManager
   * @param {BrowserWindow} window - Electron window to control
   * @param {Function} onStateChange - Callback when wander state changes
   */
  constructor(window, onStateChange) {
    this.window = window;
    this.onStateChange = onStateChange;

    // State
    this.isWandering = false;
    this.isMoving = false;
    this.isPaused = false;

    // Timer references
    this.wanderTimer = null;
    this.animationTimer = null;

    // Movement state
    this.currentPosition = null;
    this.targetPosition = null;
    this.startTime = null;
    this.duration = null;
  }

  /**
   * Start the wander behavior
   * Begins the wander-wait-wander loop
   */
  start() {
    if (this.isWandering) return;

    this.isWandering = true;
    this.isPaused = false;
    this._scheduleNextWander();

    // Don't change state yet - only change to 'wander' when actually moving
    // Pet stays in 'idle' while waiting for first movement
  }

  /**
   * Stop the wander behavior
   * Clears all timers and resets state
   */
  stop() {
    if (!this.isWandering) return;

    this.isWandering = false;
    this.isMoving = false;
    this.isPaused = false;

    this._clearTimers();

    // Notify state change back to 'idle'
    if (this.onStateChange) {
      this.onStateChange('idle');
    }
  }

  /**
   * Pause wander behavior temporarily (e.g., during drag)
   * Preserves state to resume later
   */
  pause() {
    if (!this.isWandering || this.isPaused) return;

    this.isPaused = true;
    this._clearTimers();

    // Change back to idle when paused
    if (this.onStateChange) {
      this.onStateChange('idle');
    }
  }

  /**
   * Resume wander behavior after pause
   */
  resume() {
    if (!this.isWandering || !this.isPaused) return;

    this.isPaused = false;
    this._scheduleNextWander();
  }

  /**
   * Check if currently wandering
   * @returns {boolean} True if wander behavior is active
   */
  isActive() {
    return this.isWandering && !this.isPaused;
  }

  /**
   * Schedule the next wander movement after random delay
   * @private
   */
  _scheduleNextWander() {
    if (!this.isWandering || this.isPaused) return;

    const delay = this._randomInterval();

    this.wanderTimer = setTimeout(() => {
      this._executeWander();
    }, delay);
  }

  /**
   * Execute a single wander movement
   * @private
   */
  _executeWander() {
    if (!this.isWandering || this.isPaused) return;

    // Get current position
    const currentBounds = this.window.getBounds();
    this.currentPosition = { x: currentBounds.x, y: currentBounds.y };

    // Calculate target position
    this.targetPosition = this._calculateTargetPosition(this.currentPosition);

    // Calculate movement duration based on distance and speed
    const distance = this._distance(this.currentPosition, this.targetPosition);
    this.duration = (distance / WANDER_CONFIG.speed) * 1000; // ms

    // Change to wander state when starting movement
    if (this.onStateChange) {
      this.onStateChange('wander');
    }

    // Start movement animation
    this.isMoving = true;
    this.startTime = Date.now();
    this._animate();
  }

  /**
   * Animation loop using linear interpolation
   * @private
   */
  _animate() {
    if (!this.isMoving || !this.isWandering || this.isPaused) {
      this.isMoving = false;
      return;
    }

    const elapsed = Date.now() - this.startTime;
    const progress = Math.min(elapsed / this.duration, 1.0);

    // Linear interpolation
    const x = this._lerp(this.currentPosition.x, this.targetPosition.x, progress);
    const y = this._lerp(this.currentPosition.y, this.targetPosition.y, progress);

    // Update window position
    this.window.setPosition(Math.round(x), Math.round(y));

    if (progress < 1.0) {
      // Continue animation
      this.animationTimer = setTimeout(() => {
        this._animate();
      }, 1000 / WANDER_CONFIG.fps);
    } else {
      // Movement complete
      this.isMoving = false;

      // Change back to idle when movement finishes
      if (this.onStateChange) {
        this.onStateChange('idle');
      }

      this._scheduleNextWander();
    }
  }

  /**
   * Calculate valid target position within screen bounds
   * @private
   * @param {Object} current - Current position {x, y}
   * @returns {Object} Target position {x, y}
   */
  _calculateTargetPosition(current) {
    // Get screen bounds where window currently is
    const display = screen.getDisplayNearestPoint({ x: current.x, y: current.y });
    const screenBounds = display.workArea;
    const windowBounds = this.window.getBounds();

    // Calculate max bounds (ensure entire window stays on screen)
    const maxX = screenBounds.x + screenBounds.width - windowBounds.width;
    const maxY = screenBounds.y + screenBounds.height - windowBounds.height;
    const minX = screenBounds.x;
    const minY = screenBounds.y;

    // Calculate minimum distances based on screen size (1/5 of screen dimensions)
    const minHorizontalDist = screenBounds.width / 5;
    const minVerticalDist = screenBounds.height / 5;

    let attempts = 0;
    const maxAttempts = 20;

    while (attempts < maxAttempts) {
      // Random horizontal and vertical distances (at least 1/5 screen size)
      const horizontalDist = minHorizontalDist + Math.random() * minHorizontalDist;
      const verticalDist = minVerticalDist + Math.random() * minVerticalDist;

      // Random directions (positive or negative)
      const xDirection = Math.random() < 0.5 ? -1 : 1;
      const yDirection = Math.random() < 0.5 ? -1 : 1;

      // Calculate target
      const targetX = current.x + (horizontalDist * xDirection);
      const targetY = current.y + (verticalDist * yDirection);

      // Check if within bounds
      if (targetX >= minX && targetX <= maxX &&
          targetY >= minY && targetY <= maxY) {
        return { x: targetX, y: targetY };
      }

      attempts++;
    }

    // Fallback: try smaller movements in valid directions
    const availableRight = maxX - current.x;
    const availableLeft = current.x - minX;
    const availableDown = maxY - current.y;
    const availableUp = current.y - minY;

    // Choose direction with most space
    const xDirection = availableRight > availableLeft ? 1 : -1;
    const yDirection = availableDown > availableUp ? 1 : -1;

    // Use smaller distance if needed to stay on screen
    const horizontalDist = Math.min(minHorizontalDist, xDirection > 0 ? availableRight : availableLeft);
    const verticalDist = Math.min(minVerticalDist, yDirection > 0 ? availableDown : availableUp);

    const targetX = current.x + (horizontalDist * xDirection);
    const targetY = current.y + (verticalDist * yDirection);

    return { x: targetX, y: targetY };
  }

  /**
   * Clear all timers
   * @private
   */
  _clearTimers() {
    if (this.wanderTimer) {
      clearTimeout(this.wanderTimer);
      this.wanderTimer = null;
    }
    if (this.animationTimer) {
      clearTimeout(this.animationTimer);
      this.animationTimer = null;
    }
  }

  /**
   * Generate random interval between wanders
   * @private
   * @returns {number} Delay in milliseconds
   */
  _randomInterval() {
    return WANDER_CONFIG.minInterval +
      Math.random() * (WANDER_CONFIG.maxInterval - WANDER_CONFIG.minInterval);
  }

  /**
   * Calculate Euclidean distance between two points
   * @private
   * @param {Object} p1 - Point 1 {x, y}
   * @param {Object} p2 - Point 2 {x, y}
   * @returns {number} Distance in pixels
   */
  _distance(p1, p2) {
    return Math.sqrt(Math.pow(p2.x - p1.x, 2) + Math.pow(p2.y - p1.y, 2));
  }

  /**
   * Linear interpolation between two values
   * @private
   * @param {number} start - Start value
   * @param {number} end - End value
   * @param {number} t - Progress [0, 1]
   * @returns {number} Interpolated value
   */
  _lerp(start, end, t) {
    return start + (end - start) * t;
  }
}

module.exports = WanderManager;
