import sys
import psutil
import logging
from datetime import datetime
import os

# Logger references (will be set by main.py)
items_logger = None
efficiency_logger = None
run_logger = None  # New logger for general runtime logs

# Color constants
EFFICIENCY_COLOR = "\033[95m"  # Magenta
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET_COLOR = '\033[0m'

# Try to import GPUtil if available
try:
    import GPUtil
except ImportError:
    GPUtil = None

def setup_run_logger():
    """Setup the general runtime logger"""
    # Get the directory where log_utils.py is located
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up one level to newsfeed, then to logs
    log_base_dir = os.path.join(os.path.dirname(current_dir), 'logs')
    run_log_dir = os.path.join(log_base_dir, 'run')
    os.makedirs(run_log_dir, exist_ok=True)
    
    log_time = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_log_file_path = os.path.join(run_log_dir, f'run_{log_time}.log')
    
    run_logger = logging.getLogger('run_logger')
    run_logger.setLevel(logging.DEBUG)  # Capture all levels
    run_handler = logging.FileHandler(run_log_file_path)
    run_handler.setLevel(logging.DEBUG)
    run_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    run_handler.setFormatter(run_formatter)
    run_logger.addHandler(run_handler)
    run_logger.propagate = False
    
    return run_logger

def log_accepted(item, step=None):
    """Log accepted items"""
    step_str = f"[{step}] " if step else ""
    msg = f"{step_str}[ACCEPTED] {item.id} | {item.source} | {item.title}"
    
    # Console with color
    if sys.stdout.isatty():
        print(f"{GREEN}{msg}{RESET_COLOR}")
    else:
        print(msg)
    
    # File logs
    if items_logger:
        items_logger.info(msg)
    if run_logger:
        run_logger.info(f"[ITEM] {msg}")

def log_refused(item, step=None):
    """Log refused items with details"""
    step_str = f"[{step}] " if step else ""
    # Get score and label info if available
    max_score = getattr(item, 'relevance_score', None) or 0.0
    top_label = getattr(item, 'top_relevant_label', 'Unknown')
    
    msg = f"{step_str}[REFUSED] {item.title} | max_score={max_score:.2f} | label={top_label}"
    
    # Console with color
    if sys.stdout.isatty():
        print(f"{RED}{msg}{RESET_COLOR}")
    else:
        print(msg)
    
    # File logs
    if items_logger:
        items_logger.info(msg)
    if run_logger:
        run_logger.info(f"[ITEM] {msg}")

def log_efficiency(msg: str, step: str = ""):
    """Log efficiency metrics with clean formatting"""
    if step:
        # For console: add color if TTY
        console_msg = f"[EFFICIENCY - {step.upper()}] {msg}"
        if sys.stdout.isatty():
            console_msg = f"{EFFICIENCY_COLOR}{console_msg}{RESET_COLOR}"
        print(console_msg)
        
        # For file: no color, clean format
        file_msg = f"[{step.upper()}] {msg}"
        if efficiency_logger:
            efficiency_logger.info(file_msg)
        if run_logger:
            run_logger.info(f"[EFFICIENCY] {file_msg}")
    else:
        # Generic efficiency message
        print(msg)
        if efficiency_logger:
            efficiency_logger.info(msg)
        if run_logger:
            run_logger.info(f"[EFFICIENCY] {msg}")

def log_resource_usage(stage: str):
    """Log resource usage metrics in a clean format"""
    cpu_usage = psutil.cpu_percent(interval=None)
    memory_usage = psutil.virtual_memory().percent
    
    # Log each metric on its own line
    log_efficiency(f"CPU Usage: {cpu_usage:.1f}%", step=stage)
    log_efficiency(f"Memory Usage: {memory_usage:.1f}%", step=stage)
    
    if GPUtil:
        gpus = GPUtil.getGPUs()
        for gpu in gpus:
            log_efficiency(f"GPU {gpu.id} Usage: {gpu.load*100:.1f}%", step=stage)
            log_efficiency(f"GPU {gpu.id} Memory: {gpu.memoryUtil*100:.1f}%", step=stage)

def log_info(msg: str, source: str = None):
    """General info logging for pipeline status"""
    if source:
        formatted_msg = f"[{source}] {msg}"
    else:
        formatted_msg = msg
    
    # Console
    print(formatted_msg)
    
    # File log
    if run_logger:
        run_logger.info(formatted_msg)

def log_error(msg: str, source: str = None, exc_info=False):
    """Error logging"""
    if source:
        formatted_msg = f"[{source}] ERROR: {msg}"
    else:
        formatted_msg = f"ERROR: {msg}"
    
    # Console with color
    if sys.stdout.isatty():
        print(f"{RED}{formatted_msg}{RESET_COLOR}")
    else:
        print(formatted_msg)
    
    # File log
    if run_logger:
        run_logger.error(formatted_msg, exc_info=exc_info)
