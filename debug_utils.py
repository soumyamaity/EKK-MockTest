import os
import logging
from datetime import datetime
from functools import wraps
from flask import request, current_app, has_app_context
import traceback

# Global logger instance
_logger = None

def get_logger():
    """Get or create the logger instance"""
    global _logger
    if _logger is None:
        _logger = _setup_logger()
    return _logger

def _setup_logger():
    """Set up the debug logger configuration"""
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Create a custom logger
    logger = logging.getLogger('app_debug')
    logger.setLevel(logging.DEBUG)
    
    # Clear existing handlers to avoid duplicate logs
    if logger.handlers:
        logger.handlers.clear()
    
    # File handler for all levels
    log_file = os.path.join(log_dir, f'debug_{datetime.now().strftime("%Y%m%d")}.log')
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    
    # Console handler for errors and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)
    
    # Create formatters and add it to handlers
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler.setFormatter(log_format)
    console_handler.setFormatter(log_format)
    
    # Add handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

def log_exceptions(f):
    """Decorator to log exceptions in views"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        logger = get_logger()
        
        try:
            logger.debug(f"Entering {f.__name__}")
            if has_app_context() and request.method == 'POST':
                logger.debug(f"Request data: {f.__name__} - {request.form.to_dict()}")
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Exception in {f.__name__}: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        finally:
            logger.debug(f"Exiting {f.__name__}")
    return decorated_function

def log_info(message):
    """Log an info message"""
    get_logger().info(message)

def log_error(message, exc_info=None):
    """Log an error message with optional exception info"""
    get_logger().error(message, exc_info=exc_info)

def log_debug(message):
    """Log a debug message"""
    get_logger().debug(message)
