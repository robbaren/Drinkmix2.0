import os
import json
import logging
from threading import Lock

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# File paths
HOSE_ASSIGNMENTS_FILE = os.path.join(DATA_DIR, 'hose_assignments.json')
PUMP_CALIBRATIONS_FILE = os.path.join(DATA_DIR, 'pump_calibrations.json')
HOSE_STATUSES_FILE = os.path.join(DATA_DIR, 'hose_statuses.json')
BOTTLE_VOLUMES_FILE = os.path.join(DATA_DIR, 'bottle_volumes.json')
RECIPE_FILE = os.path.join(DATA_DIR, 'drink_recipes.json')
DENSITY_FILE = os.path.join(DATA_DIR, 'densities.json')

file_lock = Lock()

DEFAULT_DENSITIES = {
    "vodka": 0.95, "gin": 0.95, "whiskey": 0.95, "tequila": 0.95, "rum": 0.95,
    "cachaca": 0.95, "triple sec": 1.00, "soda water": 1.00, "cranberry juice": 1.05,
    "lime juice": 1.03, "lemon juice": 1.03, "sugar syrup": 1.30, "cola": 1.03,
    "tonic water": 1.02, "coffee liqueur": 1.20, "pineapple juice": 1.04,
    "coconut cream": 1.10, "orgeat syrup": 1.20, "coffee": 1.00, "champagne": 0.99,
    "cognac": 0.96, "amaretto": 1.02, "absinthe": 0.92, "apple brandy": 0.96,
    "vermouth": 1.00, "elderflower liqueur": 1.00, "sake": 1.00
}

def load_json(file_path, default):
    with file_lock:
        if not os.path.exists(file_path):
            return default
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading {file_path}: {e}")
            return default

def save_json(data, file_path):
    with file_lock:
        try:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving {file_path}: {e}")

# Hose assignments
def load_hose_assignments():
    data = load_json(HOSE_ASSIGNMENTS_FILE, {})
    return {int(k): str(v) for k, v in data.items()}

def save_hose_assignments(assignments):
    save_json({str(k): v for k, v in assignments.items()}, HOSE_ASSIGNMENTS_FILE)

# Pump calibrations
def load_pump_calibrations():
    data = load_json(PUMP_CALIBRATIONS_FILE, {})
    return {int(k): float(v) for k, v in data.items()}

def save_pump_calibration(pump_id, flow_rate):
    calibrations = load_pump_calibrations()
    calibrations[pump_id] = float(flow_rate)
    save_json({str(k): v for k, v in calibrations.items()}, PUMP_CALIBRATIONS_FILE)

# Hose statuses
def load_hose_statuses():
    data = load_json(HOSE_STATUSES_FILE, {})
    return {int(k): bool(v) for k, v in data.items()}

def save_hose_statuses(statuses):
    save_json({str(k): v for k, v in statuses.items()}, HOSE_STATUSES_FILE)

# Bottle volumes
def load_bottle_volumes():
    data = load_json(BOTTLE_VOLUMES_FILE, {})
    return {int(k): {'total_volume_ml': int(v['total_volume_ml']), 'remaining_volume_ml': int(v['remaining_volume_ml'])} for k, v in data.items()}

def save_bottle_volumes(volumes):
    save_json({str(k): v for k, v in volumes.items()}, BOTTLE_VOLUMES_FILE)

def update_remaining_volume(hose_id, dispensed_volume):
    volumes = load_bottle_volumes()
    if hose_id in volumes:
        volumes[hose_id]['remaining_volume_ml'] = max(0, volumes[hose_id]['remaining_volume_ml'] - dispensed_volume)
    save_bottle_volumes(volumes)

# Recipes
def load_all_recipes():
    recipes = load_json(RECIPE_FILE, [])
    return [{'drink_id': r['drink_id'], 'drink_name': r['drink_name'], 'ingredients': {k: int(v) for k, v in r['ingredients'].items()}, 'notes': r.get('notes', '')} for r in recipes]

def save_all_recipes(recipes):
    save_json(recipes, RECIPE_FILE)

def get_recipe_by_id(drink_id):
    return next((r for r in load_all_recipes() if r['drink_id'] == drink_id), None)

# Availability
def is_ingredient_available(ingredient):
    hose_assignments = load_hose_assignments()
    hose_statuses = load_hose_statuses()
    for hose_id, bev in hose_assignments.items():
        if bev.lower() == ingredient.lower() and not hose_statuses.get(hose_id, True):
            return True
    return False

def get_available_drinks():
    recipes = load_all_recipes()
    return [r for r in recipes if all(is_ingredient_available(ing) for ing in r['ingredients'])]

# Density
def get_density(liquid_name):
    densities = load_json(DENSITY_FILE, DEFAULT_DENSITIES)
    return densities if not liquid_name else densities.get(liquid_name.lower(), 1.0)

def add_density(liquid_name, density):
    densities = load_json(DENSITY_FILE, DEFAULT_DENSITIES)
    densities[liquid_name.lower()] = float(density)
    save_json(densities, DENSITY_FILE)
    
# Ingredients
def get_all_ingredients():
    """
    Loads all ingredient names from densities.json. 
    Keys are the ingredient names, values are densities.
    Returns a sorted list of ingredient names (capitalized).
    """
    densities = load_json(DENSITY_FILE, DEFAULT_DENSITIES)
    # densities keys are e.g. 'vodka', 'gin', etc.
    # We'll return them with initial caps for display, or keep them lowercase if you prefer.
    ingredients = [key.capitalize() for key in densities.keys()]
    # Sort them however you like; by default let's just do alphabetical
    ingredients.sort()
    return ingredients

# Suggest substitutes based on density similarity
def suggest_substitutes(ingredient):
    densities = load_json(DENSITY_FILE, DEFAULT_DENSITIES)
    target_density = get_density(ingredient)
    similar = sorted(densities.items(), key=lambda x: abs(x[1] - target_density))
    return [name for name, _ in similar if name != ingredient.lower()][:3]
