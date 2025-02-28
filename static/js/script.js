const socket = io();

socket.on('mixing_start', function(data) {
    document.getElementById('mixing-modal').style.display = 'block';
    document.getElementById('mixing-message').innerText = `Mixing your ${data.drink_name}, please hold on!`;
});

socket.on('mixing_progress', function(data) {
    document.getElementById('mixing-progress').value = data.progress * 100;
    document.getElementById('mixing-percentage').innerText = Math.round(data.progress * 100) + '%';
});

socket.on('mixing_complete', function() {
    document.getElementById('mixing-modal').style.display = 'none';
    alert('Drink is ready!');
});

// PIN input logic
let pin = '';
function addDigit(digit) {
    if (pin.length < 4) {
        pin += digit;
        document.getElementById('pin-display').innerText = '*'.repeat(pin.length);
    }
}
function submitPin() {
    if (pin.length === 4) {
        document.getElementById('pin-input').value = pin;
        document.getElementById('pin-form').submit();
    } else {
        alert('Please enter a 4-digit PIN');
    }
}
