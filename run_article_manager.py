#!/usr/bin/env python3
"""Script to run the image manager web application."""

import os
import sys

# Add the project root to the Python path if needed
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from newsaggregator.web.app import app

if __name__ == '__main__':
    print("Starting Briefsnap Article Manager...")
    print("Visit http://localhost:3000 to access the application")
    app.run(debug=True, host='0.0.0.0', port=3000) 