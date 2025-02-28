import os
import json
import logging
from threading import Lock
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
os.makedirs(DATA_DIR, exist_ok=True)

# File paths
HOSE_ASSIGNMENTS_FILE = os.path.join(DATA_DIR, 'hose_assignments.json')
PUMP_CALIBRATIONS_FILE = os.path.join(DATA_DIR, 'pump_calibrations.json')
HOSE_STATUSES_FILE = os.path.join(DATA_DIR, 'hose_statuses.json')
BOTTLE_VOLUMES_FILE = os.path.join(DATA_DIR, 'bottle_volumes.json')
RECIPE_FILE = os.path.join(DATA_DIR, 'drink_recipes.json')
DENSITY_FILE = os.path.join(DATA_DIR, 'densities.json')
USAGE_STATS_FILE = os.path.join(DATA_DIR, 'usage_stats.json')
MAINTENANCE_LOG_FILE = os.path.join(DATA_DIR, 'maintenance_log.json')

# Create separate locks for each file to avoid contention
file_locks = {
    HOSE_ASSIGNMENTS_FILE: Lock(),
    PUMP_CALIBRATIONS_FILE: Lock(),
    HOSE_STATUSES_FILE: Lock(),
    BOTTLE_VOLUMES_FILE: Lock(),
    RECIPE_FILE: Lock(),
    DENSITY_FILE: Lock(),
    USAGE_STATS_FILE: Lock(),
    MAINTENANCE_LOG_FILE: Lock()
}

DEFAULT_DENSITIES = {
    "vodka": 0.95, "gin": 0.95, "whiskey": 0.95, "tequila": 0.95, "rum": 0.95,
    "cachaca": 0.95, "triple sec": 1.00, "soda water": 1.00, "cranberry juice": 1.05,
    "lime juice": 1.03, "lemon juice": 1.03, "sugar syrup": 1.30, "cola": 1.03,
    "tonic water": 1.02, "coffee liqueur": 1.20, "pineapple juice": 1.04,
    "coconut cream": 1.10, "orgeat syrup": 1.20, "coffee": 1.00, "champagne": 0.99,
    "cognac": 0.96, "amaretto": 1.02, "absinthe": 0.92, "apple brandy": 0.96,
    "vermouth": 1.00, "elderflower liqueur": 1.00, "sake": 1.00,
    "grenadine": 1.10, "orange juice": 1.04, "red bull": 1.03, "peach schnapps": 1.02,
    "lemonade": 1.03, "milk": 1.03, "tomato juice": 1.05, "apple juice": 1.04,
    "bourbon": 0.96, "sour mix": 1.10, "simple syrup": 1.20
}

def load_json(file_path, default):
    """
    Load JSON data from a file with locking for thread safety.
    
    Args:
        file_path (str): Path to the JSON file
        default: Default value if file doesn't exist or can't be loaded
        
    Returns:
        The loaded JSON data or default value
    """
    lock = file_locks.get(file_path, Lock())  # Get lock or create new one
    
    with lock:
        if not os.path.exists(file_path):
            return default
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading {file_path}: {e}")
            return default

def save_json(data, file_path):
    """
    Save JSON data to a file with locking for thread safety.
    
    Args:
        data: Data to save as JSON
        file_path (str): Path to save the JSON file
    """
    lock = file_locks.get(file_path, Lock())  # Get lock or create new one
    
    with lock:
        try:
            # Create directory if it doesn't exist
            directory = os.path.dirname(file_path)
            os.makedirs(directory, exist_ok=True)
            
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving {file_path}: {e}")

# Hose assignments
def load_hose_assignments():
    """
    Load hose assignments from JSON file.
    
    Returns:
        dict: {hose_id: ingredient_name}
    """
    data = load_json(HOSE_ASSIGNMENTS_FILE, {})
    return {int(k): str(v) for k, v in data.items()}

def save_hose_assignments(assignments):
    """
    Save hose assignments to JSON file.
    
    Args:
        assignments (dict): {hose_id: ingredient_name}
    """
    save_json({str(k): v for k, v in assignments.items()}, HOSE_ASSIGNMENTS_FILE)

# Pump calibrations
def load_pump_calibrations():
    """
    Load pump calibrations (flow rates) from JSON file.
    
    Returns:
        dict: {pump_id: flow_rate_ml_per_second}
    """
    data = load_json(PUMP_CALIBRATIONS_FILE, {})
    return {int(k): float(v) for k, v in data.items()}

def save_pump_calibration(pump_id, flow_rate):
    """
    Save a single pump's calibration to JSON file.
    
    Args:
        pump_id (int): Pump ID
        flow_rate (float): Flow rate in ml/second
    """
    calibrations = load_pump_calibrations()
    calibrations[pump_id] = float(flow_rate)
    save_json({str(k): v for k, v in calibrations.items()}, PUMP_CALIBRATIONS_FILE)

# Hose statuses
def load_hose_statuses():
    """
    Load hose statuses from JSON file.
    
    Returns:
        dict: {hose_id: is_empty}
    """
    data = load_json(HOSE_STATUSES_FILE, {})
    return {int(k): bool(v) for k, v in data.items()}

def save_hose_statuses(statuses):
    """
    Save hose statuses to JSON file.
    
    Args:
        statuses (dict): {hose_id: is_empty}
    """
    save_json({str(k): v for k, v in statuses.items()}, HOSE_STATUSES_FILE)

# Bottle volumes
def load_bottle_volumes():
    """
    Load bottle volume information from JSON file.
    
    Returns:
        dict: {hose_id: {'total_volume_ml': int, 'remaining_volume_ml': int}}
    """
    data = load_json(BOTTLE_VOLUMES_FILE, {})
    return {int(k): {'total_volume_ml': int(v['total_volume_ml']), 
                    'remaining_volume_ml': int(v['remaining_volume_ml'])} 
            for k, v in data.items()}

def save_bottle_volumes(volumes):
    """
    Save bottle volume information to JSON file.
    
    Args:
        volumes (dict): {hose_id: {'total_volume_ml': int, 'remaining_volume_ml': int}}
    """
    save_json({str(k): v for k, v in volumes.items()}, BOTTLE_VOLUMES_FILE)

def update_remaining_volume(hose_id, dispensed_volume):
    """
    Update the remaining volume for a hose after dispensing.
    
    Args:
        hose_id (int): Hose ID
        dispensed_volume (float): Volume dispensed in ml
    """
    volumes = load_bottle_volumes()
    if hose_id in volumes:
        volumes[hose_id]['remaining_volume_ml'] = max(0, 
            volumes[hose_id]['remaining_volume_ml'] - dispensed_volume)
    save_bottle_volumes(volumes)

# Recipes
def load_all_recipes():
    """
    Load all drink recipes from JSON file.
    
    Returns:
        list: List of recipe dictionaries
    """
    recipes = load_json(RECIPE_FILE, [])
    # Convert percentages to floats since JSON doesn't guarantee numeric types
    return [{'drink_id': r['drink_id'], 
             'drink_name': r['drink_name'], 
             'ingredients': {k: float(v) for k, v in r['ingredients'].items()}, 
             'notes': r.get('notes', '')} 
            for r in recipes]

def save_all_recipes(recipes):
    """
    Save all drink recipes to JSON file.
    
    Args:
        recipes (list): List of recipe dictionaries
    """
    save_json(recipes, RECIPE_FILE)

def get_recipe_by_id(drink_id):
    """
    Get a recipe by its ID.
    
    Args:
        drink_id (int): Drink ID to look up
        
    Returns:
        dict: Recipe dictionary or None if not found
    """
    return next((r for r in load_all_recipes() if r['drink_id'] == drink_id), None)

# Availability
def is_ingredient_available(ingredient):
    """
    Check if an ingredient is available in any hose.
    
    Args:
        ingredient (str): Ingredient name to check
        
    Returns:
        bool: True if ingredient is available, False otherwise
    """
    hose_assignments = load_hose_assignments()
    hose_statuses = load_hose_statuses()
    bottle_volumes = load_bottle_volumes()
    
    for hose_id, bev in hose_assignments.items():
        if bev.lower() == ingredient.lower():
            # Check if hose is not empty (status False) and has remaining volume
            if not hose_statuses.get(hose_id, True):
                if hose_id in bottle_volumes:
                    remaining = bottle_volumes[hose_id].get('remaining_volume_ml', 0)
                    if remaining > 0:
                        return True
    return False

def get_available_drinks():
    """
    Get all drinks that can be made with the currently available ingredients.
    
    Returns:
        list: List of recipe dictionaries for available drinks
    """
    recipes = load_all_recipes()
    # A drink is available if ALL its ingredients are available
    return [r for r in recipes if all(is_ingredient_available(ing) for ing in r['ingredients'])]

# Density
def get_density(liquid_name):
    """
    Get the density of a liquid.
    
    Args:
        liquid_name (str): Name of the liquid
        
    Returns:
        float: Density of the liquid (g/ml)
    """
    densities = load_json(DENSITY_FILE, DEFAULT_DENSITIES)
    return densities.get(liquid_name.lower(), 1.0) if liquid_name else densities

def add_density(liquid_name, density):
    """
    Add or update density information for a liquid.
    
    Args:
        liquid_name (str): Name of the liquid
        density (float): Density value (g/ml)
    """
    densities = load_json(DENSITY_FILE, DEFAULT_DENSITIES)
    densities[liquid_name.lower()] = float(density)
    save_json(densities, DENSITY_FILE)
    
# Ingredients
def get_all_ingredients():
    """
    Get a list of all defined ingredients.
    
    Returns:
        list: Sorted list of ingredient names (capitalized)
    """
    densities = load_json(DENSITY_FILE, DEFAULT_DENSITIES)
    # Return capitalized ingredient names for display
    ingredients = [key.capitalize() for key in densities.keys()]
    ingredients.sort()
    return ingredients

# Suggest substitutes based on density similarity
def suggest_substitutes(ingredient):
    """
    Suggest substitute ingredients based on similar density.
    
    Args:
        ingredient (str): Ingredient to find substitutes for
        
    Returns:
        list: Up to 3 suggested substitutes (ingredient names)
    """
    densities = load_json(DENSITY_FILE, DEFAULT_DENSITIES)
    target_density = densities.get(ingredient.lower(), 1.0)
    
    # First check what ingredients are currently available
    available_ingredients = []
    hose_assignments = load_hose_assignments()
    hose_statuses = load_hose_statuses()
    bottle_volumes = load_bottle_volumes()
    
    for hose_id, assigned_ingredient in hose_assignments.items():
        if (not hose_statuses.get(hose_id, True) and 
            assigned_ingredient.lower() != ingredient.lower() and
            assigned_ingredient and
            bottle_volumes.get(hose_id, {}).get('remaining_volume_ml', 0) > 0):
            available_ingredients.append(assigned_ingredient.lower())
    
    # Sort all ingredients by density similarity
    similar = sorted(
        [(name, abs(density - target_density)) 
         for name, density in densities.items()
         if name != ingredient.lower()],
        key=lambda x: x[1]  # Sort by density difference
    )
    
    # Prioritize available ingredients
    available_substitutes = [name for name, _ in similar if name in available_ingredients][:3]
    
    # If we don't have 3 available substitutes, add other close matches
    other_substitutes = [name for name, _ in similar if name not in available_ingredients]
    
    return available_substitutes + other_substitutes[:3 - len(available_substitutes)]

# Usage statistics and maintenance tracking
def get_ingredient_usage_stats():
    """
    Get usage statistics for ingredients.
    
    Returns:
        dict: Usage statistics by pump ID
    """
    try:
        return load_json(USAGE_STATS_FILE, {})
    except Exception:
        logging.error("Error loading usage stats", exc_info=True)
        return {}

def update_ingredient_usage(pump_id, volume_ml):
    """
    Update usage statistics for an ingredient.
    
    Args:
        pump_id (int): Pump ID
        volume_ml (float): Volume dispensed in ml
    """
    try:
        usage_stats = get_ingredient_usage_stats()
        pump_str = str(pump_id)
        
        if pump_str not in usage_stats:
            usage_stats[pump_str] = {
                "volume_dispensed": 0,
                "dispense_count": 0,
                "last_used": None,
            }
        
        # Update stats
        usage_stats[pump_str]["volume_dispensed"] = usage_stats[pump_str].get("volume_dispensed", 0) + float(volume_ml)
        usage_stats[pump_str]["dispense_count"] = usage_stats[pump_str].get("dispense_count", 0) + 1
        usage_stats[pump_str]["last_used"] = datetime.now().isoformat()
        
        save_json(usage_stats, USAGE_STATS_FILE)
    except Exception:
        logging.error(f"Error updating ingredient usage for pump {pump_id}", exc_info=True)

def load_maintenance_log():
    """
    Load maintenance log.
    
    Returns:
        dict: Maintenance log by pump ID
    """
    try:
        return load_json(MAINTENANCE_LOG_FILE, {})
    except Exception:
        logging.error("Error loading maintenance log", exc_info=True)
        return {}

def save_maintenance_log(pump_id, notes=""):
    """
    Log a maintenance event and reset usage statistics.
    
    Args:
        pump_id (str or int): Pump ID
        notes (str): Maintenance notes
    """
    try:
        pump_str = str(pump_id)
        maintenance_log = load_maintenance_log()
        
        # Add new maintenance entry
        if pump_str not in maintenance_log:
            maintenance_log[pump_str] = {
                "maintenance_history": []
            }
        
        # Add this maintenance event
        maintenance_log[pump_str]["last_maintenance"] = datetime.now().isoformat()
        maintenance_log[pump_str]["maintenance_history"].append({
            "date": datetime.now().isoformat(),
            "notes": notes
        })
        
        # Save maintenance log
        save_json(maintenance_log, MAINTENANCE_LOG_FILE)
        
        # Reset usage statistics for this pump
        try:
            usage_stats = get_ingredient_usage_stats()
            if pump_str in usage_stats:
                usage_stats[pump_str]["volume_dispensed"] = 0
                save_json(usage_stats, USAGE_STATS_FILE)
        except Exception:
            logging.error(f"Error resetting usage stats for pump {pump_id}", exc_info=True)
    except Exception:
        logging.error(f"Error saving maintenance log for pump {pump_id}", exc_info=True)