/**
 * Planning Steps Component
 *
 * Renders and manages the planning steps from the deep agent's research plan.
 * Shows step status with visual indicators (pending, in progress, completed, failed).
 */

(function() {
    'use strict';

    /**
     * Planning Steps Manager
     * @param {string} containerId - ID of the container element
     */
    function PlanningSteps(containerId) {
        this.container = document.getElementById(containerId);
        this.steps = [];
        this.template = document.getElementById('planning-step-template');

        if (!this.container) {
            console.error('Planning steps container not found:', containerId);
        }
    }

    /**
     * Status icon mapping
     */
    PlanningSteps.prototype.statusIcons = {
        pending: 'fa-circle',
        in_progress: 'fa-spinner fa-spin',
        completed: 'fa-check-circle',
        failed: 'fa-times-circle',
        skipped: 'fa-forward'
    };

    /**
     * Status class mapping
     */
    PlanningSteps.prototype.statusClasses = {
        pending: 'step-pending',
        in_progress: 'step-in-progress',
        completed: 'step-completed',
        failed: 'step-failed',
        skipped: 'step-skipped'
    };

    /**
     * Update the planning steps display
     * @param {Array} steps - Array of planning step objects
     */
    PlanningSteps.prototype.update = function(steps) {
        if (!this.container || !Array.isArray(steps)) return;

        this.steps = steps;
        this.render();
    };

    /**
     * Render all planning steps
     */
    PlanningSteps.prototype.render = function() {
        if (!this.container) return;

        // Clear container
        this.container.innerHTML = '';

        if (this.steps.length === 0) {
            this.container.innerHTML = `
                <div class="deep-agent-empty-state">
                    <i class="fas fa-hourglass-start"></i>
                    <p>Creating research plan...</p>
                </div>
            `;
            return;
        }

        // Create steps list
        const stepsList = document.createElement('div');
        stepsList.className = 'deep-agent-steps-list';

        this.steps.forEach(function(step, index) {
            const stepEl = this.createStepElement(step, index + 1);
            stepsList.appendChild(stepEl);
        }, this);

        this.container.appendChild(stepsList);
    };

    /**
     * Create a step element
     * @param {Object} step - Step data
     * @param {number} number - Step number
     * @returns {HTMLElement}
     */
    PlanningSteps.prototype.createStepElement = function(step, number) {
        var stepEl;

        // Try to use template
        if (this.template) {
            stepEl = document.importNode(this.template.content, true).firstElementChild;
        } else {
            // Fallback: create element manually
            stepEl = document.createElement('div');
            stepEl.className = 'deep-agent-step';
            stepEl.innerHTML = `
                <div class="deep-agent-step-indicator">
                    <span class="deep-agent-step-icon">
                        <i class="fas fa-circle"></i>
                    </span>
                </div>
                <div class="deep-agent-step-content">
                    <div class="deep-agent-step-header">
                        <span class="deep-agent-step-number"></span>
                        <span class="deep-agent-step-name"></span>
                    </div>
                    <div class="deep-agent-step-details">
                        <span class="deep-agent-step-action"></span>
                        <span class="deep-agent-step-duration"></span>
                    </div>
                </div>
            `;
        }

        // Set data attribute
        stepEl.setAttribute('data-step-id', step.id || '');

        // Get status
        var status = step.status || 'pending';
        var statusClass = this.statusClasses[status] || 'step-pending';
        var iconClass = this.statusIcons[status] || 'fa-circle';

        // Add status class
        stepEl.classList.add(statusClass);

        // Update icon
        var iconEl = stepEl.querySelector('.deep-agent-step-icon i');
        if (iconEl) {
            iconEl.className = 'fas ' + iconClass;
        }

        // Update number
        var numberEl = stepEl.querySelector('.deep-agent-step-number');
        if (numberEl) {
            numberEl.textContent = number + '.';
        }

        // Update name
        var nameEl = stepEl.querySelector('.deep-agent-step-name');
        if (nameEl) {
            nameEl.textContent = step.name || 'Step ' + number;
        }

        // Update action badge
        var actionEl = stepEl.querySelector('.deep-agent-step-action');
        if (actionEl && step.action) {
            actionEl.textContent = step.action;
            actionEl.className = 'deep-agent-step-action action-' + (step.action || 'unknown').toLowerCase().replace(/[^a-z0-9]/g, '-');
        }

        // Update duration
        var durationEl = stepEl.querySelector('.deep-agent-step-duration');
        if (durationEl) {
            if (step.duration_ms) {
                var seconds = (step.duration_ms / 1000).toFixed(1);
                durationEl.textContent = seconds + 's';
                durationEl.style.display = '';
            } else if (status === 'in_progress') {
                durationEl.textContent = 'Running...';
                durationEl.style.display = '';
            } else {
                durationEl.style.display = 'none';
            }
        }

        // Add error indicator if failed
        if (status === 'failed' && step.error) {
            var errorEl = document.createElement('div');
            errorEl.className = 'deep-agent-step-error';
            errorEl.textContent = step.error;
            stepEl.querySelector('.deep-agent-step-content').appendChild(errorEl);
        }

        return stepEl;
    };

    /**
     * Get step by ID
     * @param {string} stepId - Step ID
     * @returns {Object|null}
     */
    PlanningSteps.prototype.getStep = function(stepId) {
        return this.steps.find(function(step) {
            return step.id === stepId;
        }) || null;
    };

    /**
     * Get completed steps count
     * @returns {number}
     */
    PlanningSteps.prototype.getCompletedCount = function() {
        return this.steps.filter(function(step) {
            return step.status === 'completed';
        }).length;
    };

    /**
     * Get progress percentage
     * @returns {number}
     */
    PlanningSteps.prototype.getProgress = function() {
        if (this.steps.length === 0) return 0;
        return Math.round((this.getCompletedCount() / this.steps.length) * 100);
    };

    /**
     * Clear all steps
     */
    PlanningSteps.prototype.clear = function() {
        this.steps = [];
        if (this.container) {
            this.container.innerHTML = `
                <div class="deep-agent-empty-state">
                    <i class="fas fa-hourglass-start"></i>
                    <p>Creating research plan...</p>
                </div>
            `;
        }
    };

    // Export to window
    window.PlanningSteps = PlanningSteps;

})();
