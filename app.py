import os
import time
import threading
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_socketio import SocketIO, emit

try:
    import RPi.GPIO as GPIO
except ImportError:
    # For development environments without GPIO
    GPIO = None
    logging.warning("GPIO not available - running in simulation mode")

from config import Config
from utils import (
    load_hose_assignments, save_hose_assignments, load_pump_calibrations, save_pump_calibration,
    load_hose_statuses, save_hose_statuses, load_bottle_volumes, save_bottle_volumes,
    update_remaining_volume, load_all_recipes, save_all_recipes, get_recipe_by_id,
    get_available_drinks, get_density, add_density, suggest_substitutes, is_ingredient_available,
    get_all_ingredients, load_json, save_json, get_ingredient_usage_stats, update_ingredient_usage,
    save_maintenance_log, load_maintenance_log, DENSITY_FILE
)

app = Flask(__name__)
app.config.from_object(Config)
socketio = SocketIO(app, cors_allowed_origins="*")

# Configure logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/app.log"), 
        logging.StreamHandler()
    ]
)

# GPIO Setup
PUMP_GPIO_PINS = {1: 17, 2: 18, 3: 27, 4: 22, 5: 23, 6: 24, 7: 25, 8: 5}
if GPIO:
    try:
        GPIO.setmode(GPIO.BCM)
        for pin in PUMP_GPIO_PINS.values():
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
        logging.info("GPIO initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize GPIO: {e}")
        GPIO = None

# Mixing lock and state
mixing_lock = threading.Lock()
is_mixing = False
mixing_progress = 0.0
last_error = None

# Calibration & priming data
CALIBRATION_DATA = {i: {"start_time": None, "last_run_time": 0.0} for i in range(1, 9)}
PRIME_DATA = {i: {"start_time": None, "last_run_time": 0.0} for i in range(1, 9)}

# PIN for settings access
CORRECT_PIN = "1234"

# Maintenance tracking
MAINTENANCE_INTERVAL_DAYS = 30
PUMP_USAGE_THRESHOLD_ML = 5000  # ML of liquid pumped before maintenance recommended

# -------------------- Helper Functions --------------------

def get_maintenance_status():
    """Get maintenance status for all pumps."""
    try:
        maintenance_log = load_maintenance_log()
        usage_stats = get_ingredient_usage_stats()
        current_time = datetime.now()
        
        status = {}
        for pump_id in range(1, 9):
            pump_str = str(pump_id)
            last_maintenance = None
            
            # Safely get last maintenance date
            if pump_str in maintenance_log and isinstance(maintenance_log[pump_str], dict):
                last_maintenance = maintenance_log[pump_str].get("last_maintenance")
            
            # Calculate days since maintenance
            if last_maintenance:
                try:
                    last_date = datetime.fromisoformat(last_maintenance)
                    days_since = (current_time - last_date).days
                    needs_maintenance_time = days_since >= MAINTENANCE_INTERVAL_DAYS
                except (ValueError, TypeError):
                    days_since = None
                    needs_maintenance_time = False
            else:
                days_since = None
                needs_maintenance_time = False
                
            # Safely get usage volume
            usage_volume = 0
            if pump_str in usage_stats and isinstance(usage_stats[pump_str], dict):
                usage_volume = usage_stats[pump_str].get("volume_dispensed", 0) or 0
            
            needs_maintenance_volume = usage_volume >= PUMP_USAGE_THRESHOLD_ML
            
            status[pump_id] = {
                "days_since_maintenance": days_since,
                "volume_dispensed": usage_volume,
                "needs_maintenance": needs_maintenance_time or needs_maintenance_volume,
                "reason": "time" if needs_maintenance_time else "volume" if needs_maintenance_volume else None
            }
        
        return status
    except Exception as e:
        logging.error(f"Error in get_maintenance_status: {e}")
        # Return a safe fallback dictionary
        return {i: {"needs_maintenance": False, "days_since_maintenance": None, "volume_dispensed": 0, "reason": None} for i in range(1, 9)}

def get_smart_recommendations(limit=5):
    """Recommend drinks based on available ingredients and usage patterns."""
    try:
        available_ingredients = set(ingredient.lower() for _, ingredient in load_hose_assignments().items())
        recipes = load_all_recipes()
        
        # Score recipes based on ingredient match percentage
        scored_recipes = []
        for recipe in recipes:
            recipe_ingredients = set(ing.lower() for ing in recipe['ingredients'].keys())
            common_ingredients = recipe_ingredients.intersection(available_ingredients)
            
            if not common_ingredients:
                continue
                
            match_percentage = len(common_ingredients) / len(recipe_ingredients)
            if match_percentage >= 0.5:  # At least 50% of ingredients are available
                scored_recipes.append({
                    'recipe': recipe,
                    'score': match_percentage,
                    'missing': len(recipe_ingredients) - len(common_ingredients)
                })
        
        # Sort by score (descending) and then by missing ingredients (ascending)
        scored_recipes.sort(key=lambda x: (-x['score'], x['missing']))
        
        # Return top recommendations
        return [r['recipe'] for r in scored_recipes[:limit]]
    except Exception as e:
        logging.error(f"Error in get_smart_recommendations: {e}")
        return []

# -------------------- Route Handlers --------------------

@app.route('/')
def main():
    """Main page displaying available drinks and hose status."""
    try:
        # Load basic data with individual try/except blocks
        drinks = []
        try:
            drinks = get_available_drinks()
        except Exception as e:
            logging.error(f"Error getting available drinks: {e}")
            
        statuses = {}
        try:
            statuses = load_hose_statuses()
        except Exception as e:
            logging.error(f"Error loading hose statuses: {e}")
            
        volumes = {}
        try:
            volumes = load_bottle_volumes()
        except Exception as e:
            logging.error(f"Error loading bottle volumes: {e}")
            
        assignments = {}
        try:
            assignments = load_hose_assignments()
        except Exception as e:
            logging.error(f"Error loading hose assignments: {e}")
        
        # Create maintenance status manually - NO comprehensions here
        maintenance_status = {}
        for i in range(1, 9):
            maintenance_status[i] = {
                "needs_maintenance": False
            }
        maintenance_needed = False
        
        # Build hose_status object
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
                'ingredient': assigned_liquid,
                'maintenance': maintenance_status.get(i, {})
            }
        
        # No recommendations for now
        recommendations = []
        
        return render_template(
            'main.html', 
            drinks=drinks, 
            hose_status=hose_status, 
            is_mixing=is_mixing,
            maintenance_needed=maintenance_needed,
            recommendations=recommendations
        )
    except Exception as e:
        logging.error(f"Error in main route: {e}")
        # Simpler error handling
        return f"Error: {str(e)}"

@app.route('/mix/<int:drink_id>', methods=['POST'])
def mix_drink_route(drink_id):
    """Handle request to mix a specific drink."""
    global is_mixing, mixing_progress, last_error
    
    if is_mixing:
        flash("A drink is already being dispensed")
        return redirect(url_for('main'))
    
    try:
        total_volume = float(request.form.get('size', 375))
        recipe = get_recipe_by_id(drink_id)
        
        if not recipe:
            flash("Recipe not found")
            return redirect(url_for('main'))
        
        # Check for unavailable ingredients and suggest substitutes
        unavailable = [ing for ing in recipe['ingredients'] if not is_ingredient_available(ing)]
        if unavailable:
            substitutes = {ing: suggest_substitutes(ing) for ing in unavailable}
            
            # Render the substitutes template instead of showing them inline
            return render_template(
                'substitutes.html', 
                recipe=recipe,
                unavailable=unavailable,
                substitutes=substitutes,
                size=total_volume
            )
        
        # Check low volumes before starting
        hose_assignments = load_hose_assignments()
        bottle_volumes = load_bottle_volumes()
        
        for ingredient, percentage in recipe['ingredients'].items():
            pump_id = next((hid for hid, bev in hose_assignments.items() 
                          if bev.lower() == ingredient.lower()), None)
            if pump_id:
                required_volume = total_volume * (percentage / 100.0)
                remaining = bottle_volumes.get(pump_id, {}).get('remaining_volume_ml', 0)
                if remaining < required_volume:
                    flash(f"Warning: Low volume for {ingredient}. Please refill hose {pump_id}.")
        
        with mixing_lock:
            is_mixing = True
            mixing_progress = 0.0
            last_error = None
        
        # Start mixing in a separate thread
        threading.Thread(target=mix_drink_thread, args=(drink_id, total_volume)).start()
        
        return redirect(url_for('mix_progress'))
    
    except Exception as e:
        logging.error(f"Error in mix_drink_route: {e}")
        flash(f"An error occurred: {str(e)}")
        return redirect(url_for('main'))
    
@app.route('/mix_progress')
def mix_progress():
    """Display mixing progress page."""
    if not is_mixing:
        return redirect(url_for('main'))
    return render_template('mixing_progress_full.html')

def mix_drink_thread(drink_id, total_volume):
    """Thread function to handle the drink mixing process."""
    global is_mixing, mixing_progress, last_error
    
    try:
        recipe = get_recipe_by_id(drink_id)
        if recipe is None:
            last_error = "Recipe not found"
            socketio.emit('mixing_error', {'error': last_error})
            return

        hose_assignments = load_hose_assignments()
        calibrations = load_pump_calibrations()
        bottle_volumes = load_bottle_volumes()

        total_ingredients = len(recipe['ingredients'])
        completed = 0
        
        socketio.emit('mixing_start', {'drink_name': recipe['drink_name']})
        
        # Convert percentage to volume for each ingredient
        for ingredient, percentage in recipe['ingredients'].items():
            pump_id = next((hid for hid, bev in hose_assignments.items() 
                          if bev.lower() == ingredient.lower()), None)
            
            if not pump_id:
                logging.error(f"Ingredient {ingredient} not assigned")
                continue
                
            required_volume = total_volume * (percentage / 100.0)
            flow_rate = calibrations.get(pump_id, 10.0)
            remaining = bottle_volumes.get(pump_id, {}).get('remaining_volume_ml', 0)
            
            if remaining < required_volume:
                last_error = f"Insufficient volume for {ingredient}. Please refill hose {pump_id}."
                socketio.emit('mixing_error', {'error': last_error})
                break
                
            dispense_time = required_volume / flow_rate
            
            # Activate pump and handle potential errors
            try:
                activate_pump(pump_id, dispense_time)
                update_remaining_volume(pump_id, required_volume)
                update_ingredient_usage(pump_id, required_volume)
                
                completed += 1
                mixing_progress = completed / total_ingredients
                socketio.emit('mixing_progress', {'progress': mixing_progress})
                
                # Small delay between ingredients
                time.sleep(0.5)
                
            except Exception as e:
                last_error = f"Error dispensing {ingredient}: {str(e)}"
                logging.error(f"Pump error: {last_error}")
                socketio.emit('mixing_error', {'error': last_error})
                break
        
        socketio.emit('mixing_complete')
        
    except Exception as e:
        last_error = f"Error mixing drink {drink_id}: {str(e)}"
        logging.error(last_error)
        socketio.emit('mixing_error', {'error': last_error})
        
    finally:
        with mixing_lock:
            is_mixing = False
            mixing_progress = 0.0

def activate_pump(pump_id, duration):
    """Activate a pump for a specified duration."""
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
        # Ensure pump is turned off even if there's an error
        try:
            GPIO.output(pin, GPIO.LOW)
        except:
            pass
        logging.error(f"GPIO error for pump {pump_id}: {e}")
        raise

def activate_pump_raw(pump_id, on=True):
    """Directly activate or deactivate a pump."""
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
        raise

# -------------------- Recipe Management Routes --------------------

@app.route('/recipes')
def recipes():
    """Display recipe management page."""
    all_recipes = load_all_recipes()
    return render_template('recipes.html', recipes=all_recipes, available_ingredients=get_all_ingredients())

@app.route('/recipes/add', methods=['GET', 'POST'])
def add_recipe():
    """Add a new recipe."""
    if request.method == 'POST':
        try:
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
                        ingredients[ing] = perc_val
                    except ValueError:
                        continue
                        
            notes = request.form.get('notes', '')
            
            # Validate total percentage is close to 100%
            total_percentage = sum(ingredients.values())
            if not (95 <= total_percentage <= 105):
                flash(f"Warning: Total ingredient percentage is {total_percentage}%, not 100%")
            
            new_recipe = {
                'drink_id': drink_id, 
                'drink_name': drink_name, 
                'ingredients': ingredients, 
                'notes': notes
            }
            
            recipes.append(new_recipe)
            save_all_recipes(recipes)
            flash("Recipe added successfully")
            
            return redirect(url_for('recipes'))
            
        except Exception as e:
            logging.error(f"Error adding recipe: {e}")
            flash(f"Error adding recipe: {str(e)}")
            
    return render_template(
        'recipe_form.html', 
        action='Add', 
        recipe={'ingredients': {}}, 
        available_ingredients=get_all_ingredients()
    )

@app.route('/recipes/edit/<int:drink_id>', methods=['GET', 'POST'])
def edit_recipe(drink_id):
    """Edit an existing recipe."""
    recipes = load_all_recipes()
    recipe = next((r for r in recipes if r['drink_id'] == drink_id), None)
    
    if not recipe:
        flash("Recipe not found")
        return redirect(url_for('recipes'))
        
    if request.method == 'POST':
        try:
            recipe['drink_name'] = request.form.get('drink_name')
            
            new_ingredients = {}
            for i in range(1, 6):
                ing = request.form.get(f'ingredient_{i}')
                perc = request.form.get(f'percentage_{i}')
                if ing and perc:
                    try:
                        perc_val = float(perc)
                        new_ingredients[ing] = perc_val
                    except ValueError:
                        continue
                        
            # Validate total percentage is close to 100%
            total_percentage = sum(new_ingredients.values())
            if not (95 <= total_percentage <= 105):
                flash(f"Warning: Total ingredient percentage is {total_percentage}%, not 100%")
                
            recipe['ingredients'] = new_ingredients
            recipe['notes'] = request.form.get('notes', '')
            
            save_all_recipes(recipes)
            flash("Recipe updated successfully")
            
            return redirect(url_for('recipes'))
            
        except Exception as e:
            logging.error(f"Error updating recipe: {e}")
            flash(f"Error updating recipe: {str(e)}")
            
    return render_template(
        'recipe_form.html', 
        action='Edit', 
        recipe=recipe, 
        available_ingredients=get_all_ingredients()
    )

@app.route('/recipes/delete/<int:drink_id>', methods=['POST'])
def delete_recipe(drink_id):
    """Delete a recipe."""
    try:
        recipes = load_all_recipes()
        recipes = [r for r in recipes if r['drink_id'] != drink_id]
        save_all_recipes(recipes)
        flash("Recipe deleted successfully")
    except Exception as e:
        logging.error(f"Error deleting recipe: {e}")
        flash(f"Error deleting recipe: {str(e)}")
        
    return redirect(url_for('recipes'))

# -------------------- Substitution Handling --------------------

@app.route('/mix_with_substitutes', methods=['POST'])
def mix_with_substitutes():
    """Handle mixing a drink with ingredient substitutions."""
    global is_mixing, mixing_progress
    
    if is_mixing:
        flash("A drink is already being dispensed")
        return redirect(url_for('main'))
    
    try:
        drink_id = int(request.form.get('drink_id'))
        total_volume = float(request.form.get('size', 375))
        
        original_recipe = get_recipe_by_id(drink_id)
        if not original_recipe:
            flash("Recipe not found")
            return redirect(url_for('main'))
        
        # Create a new recipe object based on the original
        recipe = {
            'drink_id': original_recipe['drink_id'],
            'drink_name': original_recipe['drink_name'],
            'ingredients': {},
            'notes': original_recipe['notes']
        }
        
        # Collect all form data for substitutions
        substitutions = {}
        for key, value in request.form.items():
            if key.startswith('substitute_') and value:
                # Get original ingredient name from the key
                original_ingredient = key[len('substitute_'):].replace('_', ' ')
                substitutions[original_ingredient] = value
        
        # Process all ingredients, using substitutes or skipping as needed
        total_percentage = 0
        for ingredient, percentage in original_recipe['ingredients'].items():
            if ingredient in substitutions:
                # Use the substitute
                substitute = substitutions[ingredient]
                recipe['ingredients'][substitute] = percentage
                total_percentage += percentage
            elif is_ingredient_available(ingredient):
                # Original ingredient is available
                recipe['ingredients'][ingredient] = percentage
                total_percentage += percentage
            # If not available and no substitute, skip this ingredient
        
        # If total percentage is not 100%, adjust all percentages
        if total_percentage > 0 and total_percentage != 100:
            scale_factor = 100 / total_percentage
            for ingredient, percentage in recipe['ingredients'].items():
                recipe['ingredients'][ingredient] = percentage * scale_factor
        
        # Log the substitutions
        if substitutions:
            logging.info(f"Drink {recipe['drink_name']} mixed with substitutions: {substitutions}")
            
            # Add a note about substitutions
            if recipe['notes']:
                recipe['notes'] += " (with substitutions)"
            else:
                recipe['notes'] = "Made with substitutions"
        
        # Start mixing
        with mixing_lock:
            is_mixing = True
            mixing_progress = 0.0
        
        # Use a custom thread for the modified recipe
        threading.Thread(target=mix_drink_thread_custom, args=(recipe, total_volume)).start()
        
        return redirect(url_for('mix_progress'))
        
    except Exception as e:
        logging.error(f"Error in mix_with_substitutes: {e}")
        flash(f"An error occurred: {str(e)}")
        return redirect(url_for('main'))

def mix_drink_thread_custom(recipe, total_volume):
    """Thread function to handle mixing a custom recipe with substitutions."""
    global is_mixing, mixing_progress, last_error
    
    try:
        if not recipe or not recipe.get('ingredients'):
            last_error = "Recipe not found or empty"
            socketio.emit('mixing_error', {'error': last_error})
            return

        hose_assignments = load_hose_assignments()
        calibrations = load_pump_calibrations()
        bottle_volumes = load_bottle_volumes()

        total_ingredients = len(recipe['ingredients'])
        completed = 0
        
        socketio.emit('mixing_start', {'drink_name': recipe['drink_name']})
        
        # Convert percentage to volume for each ingredient
        for ingredient, percentage in recipe['ingredients'].items():
            pump_id = next((hid for hid, bev in hose_assignments.items() 
                          if bev.lower() == ingredient.lower()), None)
            
            if not pump_id:
                logging.error(f"Ingredient {ingredient} not assigned")
                socketio.emit('mixing_progress', {'progress': (completed / total_ingredients)})
                completed += 1
                continue
                
            required_volume = total_volume * (percentage / 100.0)
            flow_rate = calibrations.get(pump_id, 10.0)
            remaining = bottle_volumes.get(pump_id, {}).get('remaining_volume_ml', 0)
            
            if remaining < required_volume:
                last_error = f"Insufficient volume for {ingredient}. Please refill hose {pump_id}."
                socketio.emit('mixing_error', {'error': last_error})
                break
                
            dispense_time = required_volume / flow_rate
            
            # Activate pump and handle potential errors
            try:
                activate_pump(pump_id, dispense_time)
                update_remaining_volume(pump_id, required_volume)
                update_ingredient_usage(pump_id, required_volume)
                
                completed += 1
                mixing_progress = completed / total_ingredients
                socketio.emit('mixing_progress', {'progress': mixing_progress})
                
                # Small delay between ingredients
                time.sleep(0.5)
                
            except Exception as e:
                last_error = f"Error dispensing {ingredient}: {str(e)}"
                logging.error(f"Pump error: {last_error}")
                socketio.emit('mixing_error', {'error': last_error})
                break
        
        socketio.emit('mixing_complete')
        
    except Exception as e:
        last_error = f"Error mixing custom drink: {str(e)}"
        logging.error(last_error)
        socketio.emit('mixing_error', {'error': last_error})
        
    finally:
        with mixing_lock:
            is_mixing = False
            mixing_progress = 0.0

# -------------------- PIN Entry for Settings --------------------

@app.route('/pin', methods=['GET', 'POST'])
def pin_entry():
    """PIN entry page for settings access."""
    if request.method == 'POST':
        pin = request.form.get('pin')
        if pin == CORRECT_PIN:
            return redirect(url_for('settings'))
        flash("Incorrect PIN")
    return render_template('pin_entry.html')

@app.route('/settings')
def settings():
    """Settings main page."""
    try:
        maintenance_status = get_maintenance_status()
        maintenance_count = 0
        for status in maintenance_status.values():
            if status and status.get("needs_maintenance", False):
                maintenance_count += 1
    except Exception as e:
        logging.error(f"Error loading maintenance status for settings: {e}")
        maintenance_status = {}
        maintenance_count = 0
        
    return render_template('settings.html', 
                          maintenance_status=maintenance_status,
                          maintenance_count=maintenance_count)

# -------------------- Hose Assignment Route --------------------

@app.route('/hose_assignment', methods=['GET', 'POST'])
def hose_assignment():
    """Configure which ingredient is assigned to each hose."""
    if request.method == 'POST':
        try:
            assignments = {}
            for i in range(1, 9):
                selected_ingredient = request.form.get(f'hose_{i}', '')
                assignments[i] = selected_ingredient
            save_hose_assignments(assignments)
            flash("Hose assignments updated")
            return redirect(url_for('settings'))
        except Exception as e:
            logging.error(f"Error saving hose assignments: {e}")
            flash(f"Error saving hose assignments: {str(e)}")
            
    assignments = load_hose_assignments()
    all_ingredients = get_all_ingredients()
    return render_template(
        'hose_assignment.html',
        assignments=assignments,
        all_ingredients=all_ingredients
    )

# -------------------- Hose Status --------------------

@app.route('/hose_status', methods=['GET', 'POST'])
def hose_status_update():
    """Set which hoses are empty/disabled."""
    if request.method == 'POST':
        try:
            statuses = {}
            for i in range(1, 9):
                statuses[i] = request.form.get(f'hose_{i}') == 'on'
            save_hose_statuses(statuses)
            flash("Hose statuses updated")
            return redirect(url_for('settings'))
        except Exception as e:
            logging.error(f"Error saving hose statuses: {e}")
            flash(f"Error saving hose statuses: {str(e)}")
            
    statuses = load_hose_statuses()
    return render_template('hose_status.html', statuses=statuses)

# -------------------- Bottle Volumes --------------------

@app.route('/bottle_volumes', methods=['GET', 'POST'])
def bottle_volumes():
    """Configure bottle volumes for each hose."""
    if request.method == 'POST':
        try:
            volumes = {}
            for i in range(1, 9):
                total = request.form.get(f'total_{i}')
                remaining = request.form.get(f'remaining_{i}')
                try:
                    total = int(total)
                    remaining = int(remaining)
                    
                    # Validate inputs
                    if total < 0 or remaining < 0:
                        flash(f"Warning: Negative values for hose {i} were set to 0")
                        total = max(0, total)
                        remaining = max(0, remaining)
                        
                    if remaining > total:
                        flash(f"Warning: Remaining volume for hose {i} was higher than total, capped at total")
                        remaining = total
                        
                except:
                    total = 0
                    remaining = 0
                volumes[i] = {'total_volume_ml': total, 'remaining_volume_ml': remaining}
            save_bottle_volumes(volumes)
            flash("Bottle volumes updated")
            return redirect(url_for('settings'))
        except Exception as e:
            logging.error(f"Error saving bottle volumes: {e}")
            flash(f"Error saving bottle volumes: {str(e)}")
            
    volumes = load_bottle_volumes()
    return render_template('bottle_volumes.html', volumes=volumes)

# -------------------- Ingredient Management Routes --------------------

@app.route('/ingredients', methods=['GET'])
def list_ingredients():
    """Display all available ingredients."""
    densities = load_json(DENSITY_FILE, {})
    return render_template('ingredients.html', densities=densities)

@app.route('/ingredients/add', methods=['GET', 'POST'])
def add_ingredient():
    """Add a new ingredient."""
    if request.method == 'POST':
        try:
            ingredient_name = request.form.get('ingredient_name', '').strip().lower()
            density_str = request.form.get('density', '1.0').strip()
            
            if not ingredient_name:
                flash("Ingredient name is required.")
                return redirect(url_for('add_ingredient'))
                
            try:
                density_val = float(density_str)
                if density_val <= 0:
                    flash("Density must be greater than 0.")
                    return redirect(url_for('add_ingredient'))
            except ValueError:
                density_val = 1.0
                
            add_density(ingredient_name, density_val)
            flash(f"Added ingredient '{ingredient_name}' with density {density_val:.2f}.")
            return redirect(url_for('list_ingredients'))
        except Exception as e:
            logging.error(f"Error adding ingredient: {e}")
            flash(f"Error adding ingredient: {str(e)}")
            
    return render_template('add_ingredient.html')

# -------------------- Maintenance Routes --------------------

@app.route('/maintenance')
def maintenance():
    """View maintenance status and logs."""
    try:
        maintenance_status = get_maintenance_status()
        maintenance_log = load_maintenance_log()
    except Exception as e:
        logging.error(f"Error loading maintenance data: {e}")
        maintenance_status = {i: {"needs_maintenance": False} for i in range(1, 9)}
        maintenance_log = {}
        flash("Error loading maintenance data")
        
    return render_template(
        'maintenance.html', 
        maintenance_status=maintenance_status,
        maintenance_log=maintenance_log
    )

@app.route('/log_maintenance', methods=['POST'])
def log_maintenance():
    """Record a maintenance event."""
    try:
        pump_id = request.form.get('pump_id')
        notes = request.form.get('notes', '')
        
        if not pump_id:
            flash("Pump ID is required")
            return redirect(url_for('maintenance'))
            
        save_maintenance_log(pump_id, notes)
        flash(f"Maintenance for pump {pump_id} logged successfully")
    except Exception as e:
        logging.error(f"Error logging maintenance: {e}")
        flash(f"Error logging maintenance: {str(e)}")
        
    return redirect(url_for('maintenance'))

# -------------------- Calibration and Priming Routes --------------------

@app.route('/calibration')
def calibration():
    """Calibration and priming page."""
    # Pass pump calibrations and assignments to the template for better UI
    hose_assignments = load_hose_assignments()
    pump_calibrations = load_pump_calibrations()
    
    return render_template('calibration.html', 
                          hose_assignments=hose_assignments,
                          pump_calibrations=pump_calibrations)

@app.route('/start_pump/<int:pump_id>', methods=['POST'])
def start_pump(pump_id):
    """Start a pump for calibration."""
    try:
        CALIBRATION_DATA[pump_id]["start_time"] = time.time()
        activate_pump_raw(pump_id, on=True)
        return "Pump started"
    except Exception as e:
        logging.error(f"Error starting pump {pump_id}: {e}")
        return str(e), 500

@app.route('/stop_pump/<int:pump_id>', methods=['POST'])
def stop_pump(pump_id):
    """Stop a pump after calibration."""
    try:
        start_t = CALIBRATION_DATA[pump_id].get("start_time")
        if start_t is None:
            return "Pump was not started", 400
            
        duration = time.time() - start_t
        CALIBRATION_DATA[pump_id]["last_run_time"] = duration
        CALIBRATION_DATA[pump_id]["start_time"] = None
        
        activate_pump_raw(pump_id, on=False)
        return f"{duration:.2f}"
    except Exception as e:
        logging.error(f"Error stopping pump {pump_id}: {e}")
        # Make sure pump is off in case of error
        try:
            activate_pump_raw(pump_id, on=False)
        except:
            pass
        return str(e), 500

@app.route('/calibrate_pump', methods=['POST'])
def calibrate_pump():
    """Save pump calibration results."""
    try:
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
    except Exception as e:
        logging.error(f"Error calibrating pump: {e}")
        flash(f"Error calibrating pump: {str(e)}")
        
    return redirect(url_for('calibration'))

@app.route('/start_prime/<int:pump_id>', methods=['POST'])
def start_prime(pump_id):
    """Start priming a pump."""
    try:
        PRIME_DATA[pump_id]["start_time"] = time.time()
        activate_pump_raw(pump_id, on=True)
        return "Prime started"
    except Exception as e:
        logging.error(f"Error starting prime for pump {pump_id}: {e}")
        return str(e), 500

@app.route('/stop_prime/<int:pump_id>', methods=['POST'])
def stop_prime(pump_id):
    """Stop priming a pump."""
    try:
        start_t = PRIME_DATA[pump_id].get("start_time")
        if start_t is None:
            return "Prime was not started", 400
            
        duration = time.time() - start_t
        PRIME_DATA[pump_id]["last_run_time"] = duration
        PRIME_DATA[pump_id]["start_time"] = None
        
        activate_pump_raw(pump_id, on=False)
        return f"{duration:.2f}"
    except Exception as e:
        logging.error(f"Error stopping prime for pump {pump_id}: {e}")
        # Make sure pump is off in case of error
        try:
            activate_pump_raw(pump_id, on=False)
        except:
            pass
        return str(e), 500

@app.route('/prime_hose', methods=['POST'])
def prime_hose():
    """Log a priming operation."""
    try:
        pump_id = int(request.form.get("pump_id"))
        duration = PRIME_DATA[pump_id]["last_run_time"]
        PRIME_DATA[pump_id]["last_run_time"] = 0
        flash(f"Hose {pump_id} primed for {duration:.2f} seconds")
    except Exception as e:
        logging.error(f"Error priming hose: {e}")
        flash(f"Error priming hose: {str(e)}")
        
    return redirect(url_for('calibration'))

# -------------------- API Routes for AJAX --------------------

@app.route('/api/mixing_status')
def api_mixing_status():
    """Get current mixing status as JSON."""
    return jsonify({
        'is_mixing': is_mixing,
        'progress': mixing_progress,
        'error': last_error
    })

@app.route('/api/hose_status')
def api_hose_status():
    """Get current hose status as JSON."""
    statuses = load_hose_statuses()
    volumes = load_bottle_volumes()
    assignments = load_hose_assignments()
    
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
        
    return jsonify(hose_status)

# -------------------- Emergency Stop --------------------

@app.route('/emergency_stop', methods=['POST'])
def emergency_stop():
    """Emergency stop for all pumps."""
    global is_mixing, mixing_progress, last_error
    
    try:
        # Stop all pumps
        if GPIO:
            for pin in PUMP_GPIO_PINS.values():
                try:
                    GPIO.output(pin, GPIO.LOW)
                except Exception as e:
                    logging.error(f"Error turning off pin {pin}: {e}")
        
        # Reset mixing state
        with mixing_lock:
            is_mixing = False
            mixing_progress = 0.0
            last_error = "Emergency stop activated"
            
        flash("Emergency stop activated - all pumps stopped")
        return redirect(url_for('main'))
    except Exception as e:
        logging.error(f"Error in emergency stop: {e}")
        return str(e), 500

# -------------------- Error Routes --------------------

@app.route('/error')
def error_page():
    """Display error page."""
    error_msg = request.args.get('error', 'An unknown error occurred')
    return render_template('error.html', error=error_msg)

@app.errorhandler(404)
def page_not_found(e):
    """Handle 404 errors."""
    return render_template('error.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_server_error(e):
    """Handle 500 errors."""
    return render_template('error.html', error="Internal server error"), 500

# -------------------- Application Startup --------------------

if __name__ == '__main__':
    try:
        # Make sure data directory exists
        os.makedirs("data", exist_ok=True)
        logging.info("Starting Smart Drink Mixer application")
        socketio.run(app, host='0.0.0.0', port=5000, debug=Config.DEBUG)
    except Exception as e:
        logging.critical(f"Failed to start application: {e}")
    finally:
        # Clean up GPIO on exit
        if GPIO:
            GPIO.cleanup()