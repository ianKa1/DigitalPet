/**
 * StateManager - Pet behavior state machine
 *
 * Manages pet states and their associated animations.
 * Decoupled from main process for easy extension (AI agents, timers, etc.)
 */

/**
 * State configuration
 * Each state maps to a GIF file with optional future properties
 */
const STATE_CONFIG = {
  idle: {
    gif: 'idle.gif',
    // Future properties (placeholder):
    // duration: null,        // ms before auto-transition
    // transitions: [],       // valid next states
    // sound: null,           // audio file to play
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

/**
 * StateManager class
 * Handles state transitions and configuration
 */
class StateManager {
  /**
   * Create a new StateManager
   * @param {string} initialState - Starting state (default: 'idle')
   */
  constructor(initialState = 'idle') {
    this.currentState = initialState;
    this.stateConfig = STATE_CONFIG;
  }

  /**
   * Get current state name
   * @returns {string} Current state
   */
  getCurrentState() {
    return this.currentState;
  }

  /**
   * Get GIF filename for current state
   * @returns {string} GIF filename
   */
  getCurrentGif() {
    return this.stateConfig[this.currentState].gif;
  }

  /**
   * Transition to a new state
   * @param {string} newState - State name to transition to
   * @returns {string} GIF filename for the new state
   * @throws {Error} If state doesn't exist in configuration
   */
  setState(newState) {
    if (!this.stateConfig[newState]) {
      throw new Error(`Unknown state: ${newState}`);
    }
    this.currentState = newState;
    return this.getCurrentGif();
  }

  /**
   * Check if a state exists
   * @param {string} state - State name to check
   * @returns {boolean} True if state exists
   */
  hasState(state) {
    return state in this.stateConfig;
  }

  /**
   * Get all available state names
   * @returns {string[]} Array of state names
   */
  getAvailableStates() {
    return Object.keys(this.stateConfig);
  }

  /**
   * Get full state configuration for a state
   * @param {string} state - State name
   * @returns {object} State configuration object
   */
  getStateConfig(state) {
    return this.stateConfig[state];
  }
}

module.exports = StateManager;
