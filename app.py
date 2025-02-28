import os
import time
import threading
import logging
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_socketio import SocketIO, emit

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

from config import Config
from utils import (
    load_hose_assignments, save_hose_assignments, load_pump_calibrations, save_pump_calibration,
    load_hose_statuses, save_hose_statuses, load_bottle_volumes, save_bottle_volumes,
    update_remaining_volume, load_all_recipes, save_all_recipes, get_recipe_by_id,
    get_available_drinks, get_density, add_density, suggest_substitutes, is_ingredient_available,
    get_all_ingredients, load_json, DENSITY_FILE
)

app = Flask(__name__)
app.config.from_object(Config)
socketio = SocketIO(app)

# Static list of available ingredients for recipes (no longer used)
# AVAILABLE_INGREDIENTS = [
#    "Vodka", "Gin", "Whiskey", "Tequila", "Rum", "Cachaca",
#    "Triple Sec", "Soda Water", "Cranberry Juice", "Lime Juice",
#    "Lemon Juice", "Sugar Syrup", "Cola", "Tonic Water", "Coffee Liqueur",
#    "Pineapple Juice", "Coconut Cream", "Orgeat Syrup", "Coffee",
#    "Champagne", "Cognac", "Amaretto", "Absinthe", "Apple Brandy",
#    "Vermouth", "Elderflower Liqueur", "Sake"
# ]

# GPIO Setup
PUMP_GPIO_PINS = {1: 17, 2: 18, 3: 27, 4: 22, 5: 23, 6: 24, 7: 25, 8: 5}
if GPIO:
    GPIO.setmode(GPIO.BCM)
    for pin in PUMP_GPIO_PINS.values():
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

# Mixing lock and state (for drink mixing, unchanged)
mixing_lock = threading.Lock()
is_mixing = False
mixing_progress = 0.0

# Calibration data for calibration (press-and-hold)
CALIBRATION_DATA = {i: {"start_time": None, "last_run_time": 0.0} for i in range(1, 9)}
# Separate data for priming so they dont interfere
PRIME_DATA = {i: {"start_time": None, "last_run_time": 0.0} for i in range(1, 9)}

# PIN for settings access
CORRECT_PIN = "1234"

# Logging setup
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("logs/app.log"), logging.StreamHandler()]
)

@app.route('/')
def main():
    drinks = get_available_drinks()
    statuses = load_hose_statuses()
    volumes = load_bottle_volumes()
    assignments = load_hose_assignments()  # Load hose assignments

    # Build a detailed hose_status dict including total, percentage remaining, and assigned liquid.
    hose_status = {}
    for i in range(1, 9):
        stat = statuses.get(i, True)
        bottle = volumes.get(i, {})
        remaining = bottle.get('remaining_volume_ml', 0)
        total = bottle.get('total_volume_ml', 0)
        percent = 0
        if total > 0:
            percent = int((remaining / total) * 100)
        assigned_liquid = assignments.get(i, "")
        hose_status[i] = {
            'empty': stat, 
            'remaining': remaining, 
            'total': total, 
            'percent': percent, 
            'ingredient': assigned_liquid
        }
    return render_template('main.html', drinks=drinks, hose_status=hose_status, is_mixing=is_mixing)

@app.route('/mix/<int:drink_id>', methods=['POST'])
def mix_drink_route(drink_id):
    global is_mixing, mixing_progress
    if is_mixing:
        flash("A drink is already being dispensed")
        return redirect(url_for('main'))
    total_volume = float(request.form.get('size', 375))
    recipe = get_recipe_by_id(drink_id)
    if not recipe:
        flash("Recipe not found")
        return redirect(url_for('main'))
    # Check for unavailable ingredients and suggest substitutes
    unavailable = [ing for ing in recipe['ingredients'] if not is_ingredient_available(ing)]
    if unavailable:
        substitutes = {ing: suggest_substitutes(ing) for ing in unavailable}
        return render_template('main.html', drinks=get_available_drinks(),
                               hose_status=load_hose_statuses(), substitutes=substitutes,
                               drink_id=drink_id, size=total_volume)
    with mixing_lock:
        is_mixing = True
        mixing_progress = 0.0
    threading.Thread(target=mix_drink_thread, args=(drink_id, total_volume)).start()
    return redirect(url_for('mix_progress'))
    
@app.route('/mix_progress')
def mix_progress():
    if not is_mixing:
        return redirect(url_for('main'))
    return render_template('mixing_progress_full.html')

def mix_drink_thread(drink_id, total_volume):
    global is_mixing, mixing_progress
    try:
        recipe = get_recipe_by_id(drink_id)
        if recipe is None:
            socketio.emit('mixing_error', {'error': 'Recipe not found'})
            return

        hose_assignments = load_hose_assignments()
        calibrations = load_pump_calibrations()
        bottle_volumes = load_bottle_volumes()

        total_ingredients = len(recipe['ingredients'])
        completed = 0
        socketio.emit('mixing_start', {'drink_name': recipe['drink_name']})
        # Convert percentage to volume for each ingredient
        for ingredient, percentage in recipe['ingredients'].items():
            pump_id = next((hid for hid, bev in hose_assignments.items() if bev.lower() == ingredient.lower()), None)
            if not pump_id:
                logging.error(f"Ingredient {ingredient} not assigned")
                continue
            required_volume = total_volume * (percentage / 100.0)
            flow_rate = calibrations.get(pump_id, 10.0)
            remaining = bottle_volumes.get(pump_id, {}).get('remaining_volume_ml', 0)
            if remaining < required_volume:
                socketio.emit('mixing_error', {'error': f"Insufficient volume for {ingredient}. Please refill hose {pump_id}."})
                break
            dispense_time = required_volume / flow_rate
            activate_pump(pump_id, dispense_time)
            update_remaining_volume(pump_id, required_volume)
            completed += 1
            mixing_progress = completed / total_ingredients
            socketio.emit('mixing_progress', {'progress': mixing_progress})
            time.sleep(1)
        socketio.emit('mixing_complete')
    except Exception as e:
        logging.error(f"Error mixing drink {drink_id}: {e}")
        socketio.emit('mixing_error', {'error': "An error occurred while mixing the drink"})
    finally:
        with mixing_lock:
            is_mixing = False
            mixing_progress = 0.0

def activate_pump(pump_id, duration):
    if not GPIO:
        logging.warning(f"Simulating pump {pump_id} for {duration}s")
        time.sleep(duration)
        return
    pin = PUMP_GPIO_PINS.get(pump_id)
    if not pin:
        logging.error(f"No GPIO pin for pump {pump_id}")
        return
    try:
        GPIO.output(pin, GPIO.HIGH)
        time.sleep(duration)
        GPIO.output(pin, GPIO.LOW)
    except Exception as e:
        logging.error(f"GPIO error for pump {pump_id}: {e}")

def activate_pump_raw(pump_id, on=True):
    if not GPIO:
        logging.warning(f"Simulating pump {pump_id} -> {'ON' if on else 'OFF'}")
        return
    pin = PUMP_GPIO_PINS.get(pump_id)
    if not pin:
        logging.error(f"No GPIO pin for pump {pump_id}")
        return
    try:
        GPIO.output(pin, GPIO.HIGH if on else GPIO.LOW)
    except Exception as e:
        logging.error(f"GPIO error for pump {pump_id}: {e}")

# Recipe Management Routes
@app.route('/recipes')
def recipes():
    all_recipes = load_all_recipes()
    # Pass available ingredients from densities via get_all_ingredients()
    return render_template('recipes.html', recipes=all_recipes, available_ingredients=get_all_ingredients())

@app.route('/recipes/add', methods=['GET', 'POST'])
def add_recipe():
    if request.method == 'POST':
        recipes = load_all_recipes()
        drink_id = max([r['drink_id'] for r in recipes] + [0]) + 1
        drink_name = request.form.get('drink_name')
        ingredients = {}
        for i in range(1, 6):
            ing = request.form.get(f'ingredient_{i}')
            perc = request.form.get(f'percentage_{i}')
            if ing and perc:
                try:
                    perc_val = float(perc)
                except ValueError:
                    continue
                ingredients[ing] = perc_val
        notes = request.form.get('notes', '')
        new_recipe = {'drink_id': drink_id, 'drink_name': drink_name, 'ingredients': ingredients, 'notes': notes}
        recipes.append(new_recipe)
        save_all_recipes(recipes)
        flash("Recipe added successfully")
        return redirect(url_for('recipes'))
    return render_template('recipe_form.html', action='Add', recipe={'ingredients': {}}, available_ingredients=get_all_ingredients())

@app.route('/recipes/edit/<int:drink_id>', methods=['GET', 'POST'])
def edit_recipe(drink_id):
    recipes = load_all_recipes()
    recipe = next((r for r in recipes if r['drink_id'] == drink_id), None)
    if not recipe:
        flash("Recipe not found")
        return redirect(url_for('recipes'))
    if request.method == 'POST':
        recipe['drink_name'] = request.form.get('drink_name')
        new_ingredients = {}
        for i in range(1, 6):
            ing = request.form.get(f'ingredient_{i}')
            perc = request.form.get(f'percentage_{i}')
            if ing and perc:
                try:
                    perc_val = float(perc)
                except ValueError:
                    continue
                new_ingredients[ing] = perc_val
        recipe['ingredients'] = new_ingredients
        recipe['notes'] = request.form.get('notes', '')
        save_all_recipes(recipes)
        flash("Recipe updated successfully")
        return redirect(url_for('recipes'))
    return render_template('recipe_form.html', action='Edit', recipe=recipe, available_ingredients=get_all_ingredients())

@app.route('/recipes/delete/<int:drink_id>', methods=['POST'])
def delete_recipe(drink_id):
    recipes = load_all_recipes()
    recipes = [r for r in recipes if r['drink_id'] != drink_id]
    save_all_recipes(recipes)
    flash("Recipe deleted successfully")
    return redirect(url_for('recipes'))

# PIN Entry for Settings
@app.route('/pin', methods=['GET', 'POST'])
def pin_entry():
    if request.method == 'POST':
        pin = request.form.get('pin')
        if pin == CORRECT_PIN:
            return redirect(url_for('settings'))
        flash("Incorrect PIN")
    return render_template('pin_entry.html')

@app.route('/settings')
def settings():
    return render_template('settings.html')

# Hose Assignment Route (using dropdowns from get_all_ingredients)
@app.route('/hose_assignment', methods=['GET', 'POST'])
def hose_assignment():
    if request.method == 'POST':
        assignments = {}
        for i in range(1, 9):
            selected_ingredient = request.form.get(f'hose_{i}', '')
            assignments[i] = selected_ingredient
        save_hose_assignments(assignments)
        flash("Hose assignments updated")
        return redirect(url_for('settings'))
    assignments = load_hose_assignments()
    all_ingredients = get_all_ingredients()
    return render_template('hose_assignment.html',
                           assignments=assignments,
                           all_ingredients=all_ingredients)

# Hose Status
@app.route('/hose_status', methods=['GET', 'POST'])
def hose_status_update():
    if request.method == 'POST':
        statuses = {}
        for i in range(1, 9):
            statuses[i] = request.form.get(f'hose_{i}') == 'on'
        save_hose_statuses(statuses)
        flash("Hose statuses updated")
        return redirect(url_for('settings'))
    statuses = load_hose_statuses()
    return render_template('hose_status.html', statuses=statuses)

# Bottle Volumes
@app.route('/bottle_volumes', methods=['GET', 'POST'])
def bottle_volumes():
    if request.method == 'POST':
        volumes = {}
        for i in range(1, 9):
            total = request.form.get(f'total_{i}')
            remaining = request.form.get(f'remaining_{i}')
            try:
                total = int(total)
                remaining = int(remaining)
            except:
                total = 0
                remaining = 0
            volumes[i] = {'total_volume_ml': total, 'remaining_volume_ml': remaining}
        save_bottle_volumes(volumes)
        flash("Bottle volumes updated")
        return redirect(url_for('settings'))
    volumes = load_bottle_volumes()
    return render_template('bottle_volumes.html', volumes=volumes)

# Ingredient Management Routes
@app.route('/ingredients', methods=['GET'])
def list_ingredients():
    densities = load_json(DENSITY_FILE, {})
    return render_template('ingredients.html', densities=densities)

@app.route('/ingredients/add', methods=['GET', 'POST'])
def add_ingredient():
    if request.method == 'POST':
        ingredient_name = request.form.get('ingredient_name', '').strip().lower()
        density_str = request.form.get('density', '1.0').strip()
        if not ingredient_name:
            flash("Ingredient name is required.")
            return redirect(url_for('add_ingredient'))
        try:
            density_val = float(density_str)
        except ValueError:
            density_val = 1.0
        add_density(ingredient_name, density_val)
        flash(f"Added ingredient '{ingredient_name}' with density {density_val:.2f}.")
        return redirect(url_for('list_ingredients'))
    return render_template('add_ingredient.html')

# Calibration and Priming Routes (unchanged)
@app.route('/calibration')
def calibration():
    return render_template('calibration.html')

@app.route('/start_pump/<int:pump_id>', methods=['POST'])
def start_pump(pump_id):
    CALIBRATION_DATA[pump_id]["start_time"] = time.time()
    activate_pump_raw(pump_id, on=True)
    return "Pump started"

@app.route('/stop_pump/<int:pump_id>', methods=['POST'])
def stop_pump(pump_id):
    start_t = CALIBRATION_DATA[pump_id].get("start_time")
    if start_t is None:
        return "Pump was not started", 400
    duration = time.time() - start_t
    CALIBRATION_DATA[pump_id]["last_run_time"] = duration
    CALIBRATION_DATA[pump_id]["start_time"] = None
    activate_pump_raw(pump_id, on=False)
    return f"{duration:.2f}"

@app.route('/calibrate_pump', methods=['POST'])
def calibrate_pump():
    pump_id = int(request.form.get("pump_id"))
    dispensed_volume = float(request.form.get("dispensed_volume", 0))
    duration = CALIBRATION_DATA[pump_id]["last_run_time"]
    if duration <= 0:
        flash("No valid pump run time recorded.")
        return redirect(url_for('calibration'))
    flow_rate = dispensed_volume / duration
    save_pump_calibration(pump_id, flow_rate)
    CALIBRATION_DATA[pump_id]["last_run_time"] = 0
    flash(f"Pump {pump_id} calibrated to {flow_rate:.2f} ml/s")
    return redirect(url_for('calibration'))

@app.route('/start_prime/<int:pump_id>', methods=['POST'])
def start_prime(pump_id):
    PRIME_DATA[pump_id]["start_time"] = time.time()
    activate_pump_raw(pump_id, on=True)
    return "Prime started"

@app.route('/stop_prime/<int:pump_id>', methods=['POST'])
def stop_prime(pump_id):
    start_t = PRIME_DATA[pump_id].get("start_time")
    if start_t is None:
        return "Prime was not started", 400
    duration = time.time() - start_t
    PRIME_DATA[pump_id]["last_run_time"] = duration
    PRIME_DATA[pump_id]["start_time"] = None
    activate_pump_raw(pump_id, on=False)
    return f"{duration:.2f}"

@app.route('/prime_hose', methods=['POST'])
def prime_hose():
    pump_id = int(request.form.get("pump_id"))
    duration = PRIME_DATA[pump_id]["last_run_time"]
    PRIME_DATA[pump_id]["last_run_time"] = 0
    flash(f"Hose {pump_id} primed for {duration:.2f} seconds")
    return redirect(url_for('calibration'))

def activate_pump_raw(pump_id, on=True):
    if not GPIO:
        logging.warning(f"Simulating pump {pump_id} -> {'ON' if on else 'OFF'}")
        return
    pin = PUMP_GPIO_PINS.get(pump_id)
    if not pin:
        logging.error(f"No GPIO pin for pump {pump_id}")
        return
    try:
        GPIO.output(pin, GPIO.HIGH if on else GPIO.LOW)
    except Exception as e:
        logging.error(f"GPIO error for pump {pump_id}: {e}")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
