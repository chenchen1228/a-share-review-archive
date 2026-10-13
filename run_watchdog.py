"""Use one consistent source revision for each independent inspection attempt."""
import subprocess
import sys

subprocess.run([sys.executable, 'prepare_watchdog.py'], check=True)
subprocess.run([sys.executable, 'check_review_sites.py', '--scope', 'both', '--directory', 'monitor-docs'], check=True)
