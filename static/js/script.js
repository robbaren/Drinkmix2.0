// Initialize socket connection
const socket = io();

// Drink Mixing Progress Handling
socket.on('mixing_start', function(data) {
    showMixingModal(data.drink_name);
});

socket.on('mixing_progress', function(data) {
    updateMixingProgress(data.progress);
});

socket.on('mixing_complete', function() {
    hideMixingModal();
    showCompletionMessage();
});

socket.on('mixing_error', function(data) {
    hideMixingModal();
    showErrorMessage(data.error);
});

// DOM Ready handler
document.addEventListener('DOMContentLoaded', function() {
    initPinEntry();
    initSizeOptions();
    initMaintenance();
    initEmergencyStop();
    initBottleVolumeValidation();
    initHoseStatusPolling();
});

// PIN Entry functionality
function initPinEntry() {
    // Only initialize if we're on the PIN entry page
    if (document.getElementById('pin-display')) {
        window.pin = '';
    }
}

function addDigit(digit) {
    if (window.pin === undefined) window.pin = '';
    
    if (window.pin.length < 4) {
        window.pin += digit;
        let display = document.getElementById('pin-display');
        if (display) {
            display.innerText = '*'.repeat(window.pin.length);
        }
    }
}

function submitPin() {
    if (window.pin && window.pin.length === 4) {
        let pinInput = document.getElementById('pin-input');
        let pinForm = document.getElementById('pin-form');
        
        if (pinInput && pinForm) {
            pinInput.value = window.pin;
            pinForm.submit();
        }
    } else {
        showErrorMessage('Please enter a 4-digit PIN');
    }
}

// Drink size options
function initSizeOptions() {
    const sizeOptions = document.querySelectorAll('.size-option input[type="radio"]');
    
    sizeOptions.forEach(option => {
        option.addEventListener('change', function() {
            // Find all sibling options and remove the active class
            const siblings = this.closest('.size-options').querySelectorAll('input[type="radio"]');
            siblings.forEach(sib => {
                sib.closest('.size-option').classList.remove('active');
            });
            
            // Add active class to the selected option
            this.closest('.size-option').classList.add('active');
        });
    });
    
    // Set initial active state
    sizeOptions.forEach(option => {
        if (option.checked) {
            option.closest('.size-option').classList.add('active');
        }
    });
}

// Maintenance tracking
function initMaintenance() {
    const maintenanceCards = document.querySelectorAll('.maintenance-card');
    
    maintenanceCards.forEach(card => {
        if (card.classList.contains('needs-maintenance')) {
            // Add subtle pulsing animation to highlight cards
            card.style.animation = 'pulse 2s infinite';
        }
    });
}

// Emergency stop button
function initEmergencyStop() {
    const emergencyBtn = document.querySelector('.emergency-stop');
    
    if (emergencyBtn) {
        emergencyBtn.addEventListener('click', function(e) {
            if (!confirm('Are you sure you want to perform an emergency stop? This will immediately halt all pumps.')) {
                e.preventDefault();
            }
        });
    }
}

// Bottle volume validation
function initBottleVolumeValidation() {
    const volumeForm = document.querySelector('form[action="/bottle_volumes"]');
    
    if (volumeForm) {
        volumeForm.addEventListener('submit', function(e) {
            let valid = true;
            
            for (let i = 1; i <= 8; i++) {
                const total = document.querySelector(`input[name="total_${i}"]`);
                const remaining = document.querySelector(`input[name="remaining_${i}"]`);
                
                if (total && remaining) {
                    const totalVal = parseFloat(total.value) || 0;
                    const remainingVal = parseFloat(remaining.value) || 0;
                    
                    if (remainingVal > totalVal) {
                        showErrorMessage(`Hose ${i}: Remaining volume cannot be greater than total volume`);
                        valid = false;
                        break;
                    }
                }
            }
            
            if (!valid) {
                e.preventDefault();
            }
        });
    }
}

// Periodic hose status polling
function initHoseStatusPolling() {
    const hoseStatusContainer = document.querySelector('.hose-status');
    
    if (hoseStatusContainer) {
        // Poll every 30 seconds for updates
        setInterval(refreshHoseStatus, 30000);
    }
}

function refreshHoseStatus() {
    fetch('/api/hose_status')
        .then(response => response.json())
        .then(data => {
            for (let i = 1; i <= 8; i++) {
                const hoseItem = document.querySelector(`.hose-item:nth-child(${i})`);
                if (hoseItem && data[i]) {
                    const percentElem = hoseItem.querySelector('.percentage');
                    if (percentElem) {
                        percentElem.textContent = `${data[i].percent}%`;
                    }
                    
                    // Update low class if needed
                    if (data[i].percent < 20) {
                        hoseItem.classList.add('low');
                    } else {
                        hoseItem.classList.remove('low');
                    }
                }
            }
        })
        .catch(err => console.error('Error fetching hose status:', err));
}

// Mixing progress modal functions
function showMixingModal(drinkName) {
    // Check if modal exists first
    let modal = document.getElementById('mixing-modal');
    
    if (!modal) {
        // Create modal if it doesn't exist yet
        modal = document.createElement('div');
        modal.id = 'mixing-modal';
        modal.className = 'mixing-modal';
        
        modal.innerHTML = `
            <div class="mixing-content">
                <h2 id="mixing-message">Mixing your drink, please wait!</h2>
                <div class="progress-container">
                    <div id="progress-bar" class="progress-bar"></div>
                </div>
                <p id="mixing-percentage">0%</p>
                <div class="mixing-animation">
                    <div class="liquid-wave"></div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
    }
    
    // Set drink name
    const messageElement = document.getElementById('mixing-message');
    if (messageElement) {
        messageElement.textContent = `Mixing your ${drinkName}, please wait!`;
    }
    
    // Reset progress
    updateMixingProgress(0);
    
    // Show modal with animation
    modal.style.display = 'flex';
    setTimeout(() => {
        modal.classList.add('visible');
    }, 10);
}

function updateMixingProgress(progress) {
    const progressBar = document.getElementById('progress-bar');
    const percentText = document.getElementById('mixing-percentage');
    
    if (progressBar && percentText) {
        const percentage = Math.round(progress * 100);
        progressBar.style.width = `${percentage}%`;
        percentText.textContent = `${percentage}%`;
    }
}

function hideMixingModal() {
    const modal = document.getElementById('mixing-modal');
    
    if (modal) {
        modal.classList.remove('visible');
        setTimeout(() => {
            modal.style.display = 'none';
        }, 300); // Wait for fade-out animation
    }
}

function showCompletionMessage() {
    const completionMessage = document.createElement('div');
    completionMessage.className = 'completion-message';
    completionMessage.innerHTML = `
        <div class="completion-content">
            <div class="completion-icon"></div>
            <h2>Drink Ready!</h2>
            <p>Your drink has been successfully prepared.</p>
            <button onclick="hideCompletionMessage()" class="button">Got it</button>
        </div>
    `;
    
    document.body.appendChild(completionMessage);
    
    // Show with animation
    setTimeout(() => {
        completionMessage.classList.add('visible');
    }, 10);
    
    // Auto hide after 5 seconds
    setTimeout(() => {
        hideCompletionMessage();
    }, 5000);
}

function hideCompletionMessage() {
    const message = document.querySelector('.completion-message');
    
    if (message) {
        message.classList.remove('visible');
        setTimeout(() => {
            message.remove();
        }, 300);
    }
}

function showErrorMessage(errorText) {
    const errorMessage = document.createElement('div');
    errorMessage.className = 'error-message-popup';
    errorMessage.innerHTML = `
        <div class="error-content">
            <div class="error-icon"> </div>
            <h2>Error</h2>
            <p>${errorText}</p>
            <button onclick="hideErrorMessage()" class="button">OK</button>
        </div>
    `;
    
    document.body.appendChild(errorMessage);
    
    // Show with animation
    setTimeout(() => {
        errorMessage.classList.add('visible');
    }, 10);
}

function hideErrorMessage() {
    const message = document.querySelector('.error-message-popup');
    
    if (message) {
        message.classList.remove('visible');
        setTimeout(() => {
            message.remove();
        }, 300);
    }
}

// Calibration Utilities
function startCalibrate() {
    const selectedPump = window.selectedPump || 1;
    const button = document.getElementById('calibButton');
    
    if (button) {
        button.classList.add('active');
    }
    
    fetch(`/start_pump/${selectedPump}`, { method: 'POST' })
        .catch(err => {
            console.error(err);
            showErrorMessage(`Failed to start pump ${selectedPump}: ${err.message}`);
        });
}

function stopCalibrate() {
    const selectedPump = window.selectedPump || 1;
    const button = document.getElementById('calibButton');
    
    if (button) {
        button.classList.remove('active');
    }
    
    fetch(`/stop_pump/${selectedPump}`, { method: 'POST' })
        .then(resp => resp.text())
        .then(seconds => {
            const timeElement = document.getElementById('calibTime');
            if (timeElement) {
                timeElement.innerText = seconds;
            }
        })
        .catch(err => {
            console.error(err);
            showErrorMessage(`Failed to stop pump ${selectedPump}: ${err.message}`);
        });
}

function submitCalibration() {
    const selectedPump = window.selectedPump || 1;
    const volumeInput = document.getElementById('dispensed_volume');
    
    if (!volumeInput || !volumeInput.value) {
        showErrorMessage('Please enter the dispensed volume (ml)');
        return;
    }
    
    const volume = parseFloat(volumeInput.value);
    if (isNaN(volume) || volume <= 0) {
        showErrorMessage('Please enter a valid positive number');
        return;
    }
    
    let formData = new FormData();
    formData.append('pump_id', selectedPump);
    formData.append('dispensed_volume', volume);
    
    fetch('/calibrate_pump', {
        method: 'POST',
        body: formData
    })
    .then(resp => {
        if(resp.redirected){
            window.location.href = resp.url;
        }
    })
    .catch(err => {
        console.error(err);
        showErrorMessage(`Calibration failed: ${err.message}`);
    });
}

function startPrime() {
    const selectedPump = window.selectedPump || 1;
    const button = document.getElementById('primeButton');
    
    if (button) {
        button.classList.add('active');
    }
    
    fetch(`/start_prime/${selectedPump}`, { method: 'POST' })
        .catch(err => {
            console.error(err);
            showErrorMessage(`Failed to start priming pump ${selectedPump}: ${err.message}`);
        });
}

function stopPrime() {
    const selectedPump = window.selectedPump || 1;
    const button = document.getElementById('primeButton');
    
    if (button) {
        button.classList.remove('active');
    }
    
    fetch(`/stop_prime/${selectedPump}`, { method: 'POST' })
        .then(resp => resp.text())
        .then(seconds => {
            const timeElement = document.getElementById('primeTime');
            if (timeElement) {
                timeElement.innerText = seconds;
            }
        })
        .catch(err => {
            console.error(err);
            showErrorMessage(`Failed to stop priming pump ${selectedPump}: ${err.message}`);
        });
}

function submitPrime() {
    const selectedPump = window.selectedPump || 1;
    let formData = new FormData();
    formData.append('pump_id', selectedPump);
    
    fetch('/prime_hose', {
        method: 'POST',
        body: formData
    })
    .then(resp => {
        if(resp.redirected){
            window.location.href = resp.url;
        }
    })
    .catch(err => {
        console.error(err);
        showErrorMessage(`Priming failed: ${err.message}`);
    });
}

function selectPump(pump) {
    window.selectedPump = pump;
    
    // Update UI
    if (document.getElementById('selectedPumpDisplay')) {
        document.getElementById('selectedPumpDisplay').innerText = pump;
    }
    
    // Update selected pump box
    for(let i = 1; i <= 8; i++){
        let box = document.getElementById('pumpBox' + i);
        if (box) {
            if(i === pump){
                box.classList.add('selected');
            } else {
                box.classList.remove('selected');
            }
        }
    }
}

// Add to your CSS (this will be appended to style.css)
document.addEventListener('DOMContentLoaded', function() {
    // Add CSS for the new components
    const styleElement = document.createElement('style');
    styleElement.textContent = `
        /* Mixing Modal */
        .mixing-modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.8);
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        
        .mixing-modal.visible {
            opacity: 1;
        }
        
        .mixing-content {
            background-color: #1E1E1E;
            border-radius: 12px;
            padding: 30px;
            width: 80%;
            max-width: 500px;
            text-align: center;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }
        
        .progress-container {
            width: 100%;
            height: 20px;
            background-color: #333;
            border-radius: 10px;
            overflow: hidden;
            margin: 20px 0;
        }
        
        .progress-bar {
            height: 100%;
            width: 0%;
            background: linear-gradient(45deg, #70e25a, #5ca044);
            transition: width 0.3s ease-out;
            border-radius: 10px;
        }
        
        .mixing-animation {
            height: 80px;
            margin-top: 20px;
            position: relative;
            overflow: hidden;
            border-radius: 8px;
            background-color: #333;
        }
        
        .liquid-wave {
            position: absolute;
            width: 200%;
            height: 100%;
            background: linear-gradient(90deg, transparent, #70e25a, transparent);
            animation: wave 2s infinite linear;
            opacity: 0.5;
        }
        
        @keyframes wave {
            0% { transform: translateX(-50%); }
            100% { transform: translateX(0%); }
        }
        
        /* Completion Message */
        .completion-message {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.8);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        
        .completion-message.visible {
            opacity: 1;
        }
        
        .completion-content {
            background-color: #1E1E1E;
            border-radius: 12px;
            padding: 30px;
            width: 80%;
            max-width: 400px;
            text-align: center;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }
        
        .completion-icon {
            font-size: 48px;
            color: #70e25a;
            margin-bottom: 15px;
        }
        
        /* Error Message */
        .error-message-popup {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.8);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        
        .error-message-popup.visible {
            opacity: 1;
        }
        
        .error-content {
            background-color: #1E1E1E;
            border-radius: 12px;
            padding: 30px;
            width: 80%;
            max-width: 400px;
            text-align: center;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }
        
        .error-icon {
            font-size: 48px;
            color: #ff4d4d;
            margin-bottom: 15px;
        }
        
        /* Calibration button active state */
        #calibButton.active, #primeButton.active {
            background: #ff4d4d;
            animation: pulse 1s infinite;
        }
        
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(255, 77, 77, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(255, 77, 77, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 77, 77, 0); }
        }
    `;
    
    document.head.appendChild(styleElement);
}); 
