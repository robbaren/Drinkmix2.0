import os
import logging
from datetime import timedelta

class Config:
    """Application configuration"""
    
    # Basic Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or '5up3r-s3cur3-k3y-f0r-m1x-0-m4t1c'
    DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 't')
    
    # Application settings
    APP_NAME = "Mix 'O' Matic"
    APP_VERSION = "1.2.0"
    
    # Server settings
    HOST = os.environ.get('HOST', '0.0.0.0')
    PORT = int(os.environ.get('PORT', 5000))
    
    # Security settings
    DEFAULT_PIN = "1234"  # PIN for settings access
    SESSION_LIFETIME = timedelta(hours=1)
    
    # Hardware settings
    PUMP_GPIO_PINS = {1: 17, 2: 18, 3: 27, 4: 22, 5: 23, 6: 24, 7: 25, 8: 5}
    PUMP_COUNT = 8
    
    # Maintenance settings
    MAINTENANCE_INTERVAL_DAYS = 30
    PUMP_USAGE_THRESHOLD_ML = 5000  # ML of liquid pumped before maintenance recommended
    
    # Path settings
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    LOGS_DIR = os.path.join(BASE_DIR, 'logs')
    
    # File paths (avoid hardcoding in multiple places)
    @property
    def HOSE_ASSIGNMENTS_FILE(self):
        return os.path.join(self.DATA_DIR, 'hose_assignments.json')
        
    @property
    def PUMP_CALIBRATIONS_FILE(self):
        return os.path.join(self.DATA_DIR, 'pump_calibrations.json')
        
    @property
    def HOSE_STATUSES_FILE(self):
        return os.path.join(self.DATA_DIR, 'hose_statuses.json')
        
    @property
    def BOTTLE_VOLUMES_FILE(self):
        return os.path.join(self.DATA_DIR, 'bottle_volumes.json')
        
    @property
    def RECIPE_FILE(self):
        return os.path.join(self.DATA_DIR, 'drink_recipes.json')
        
    @property
    def DENSITY_FILE(self):
        return os.path.join(self.DATA_DIR, 'densities.json')
        
    @property
    def USAGE_STATS_FILE(self):
        return os.path.join(self.DATA_DIR, 'usage_stats.json')
        
    @property
    def MAINTENANCE_LOG_FILE(self):
        return os.path.join(self.DATA_DIR, 'maintenance_log.json')
    
    # Logging configuration
    LOGGING_CONFIG = {
        'version': 1,
        'formatters': {
            'default': {
                'format': '%(asctime)s - %(levelname)s - %(message)s',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'default',
                'level': logging.INFO,
            },
            'file': {
                'class': 'logging.FileHandler',
                'formatter': 'default',
                'level': logging.INFO,
                'filename': os.path.join(LOGS_DIR, 'app.log'),
            },
        },
        'root': {
            'level': logging.INFO,
            'handlers': ['console', 'file'],
        },
    }


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing configuration"""
    DEBUG = False
    TESTING = True
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    TESTING = False


# Configuration dictionary
config_dict = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

# Get configuration class based on environment
def get_config():
    config_name = os.environ.get('FLASK_CONFIG', 'default')
    return config_dict.get(config_name, config_dict['default'])()
