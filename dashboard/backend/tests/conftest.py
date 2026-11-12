import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))                                  # backend
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "tools"))  # Phase 0 tools
