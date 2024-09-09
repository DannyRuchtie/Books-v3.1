import os
import subprocess

# Set the environment variable
os.environ['OBJC_DISABLE_INITIALIZE_FORK_SAFETY'] = 'YES'

# Run the worker
subprocess.run(["python", "worker.py"])