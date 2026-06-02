#!/usr/bin/env python3
import os
import glob
import json
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory

# Import the scraping function from our scraper module
from scraper import scrape_divar

app = Flask(__name__, static_folder='.')

# Global status dictionary to track scraper progress
scrape_status = {
    "status": "idle",  # idle, running, completed, error
    "message": "Scraper is ready.",
    "current_page": 0,
    "total_pages": 0,
    "matches": 0,
    "log": []
}
scrape_lock = threading.Lock()
scrape_thread = None

# Custom progress callback passed to the scraper
def progress_callback(status, message, current_page=0, total_pages=0, matches=0):
    global scrape_status
    with scrape_lock:
        scrape_status["status"] = status
        scrape_status["message"] = message
        scrape_status["current_page"] = current_page
        scrape_status["total_pages"] = total_pages
        scrape_status["matches"] = matches
        # Keep last 100 log lines to save memory
        scrape_status["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        if len(scrape_status["log"]) > 100:
            scrape_status["log"].pop(0)

# Scraper runner thread target
def run_scraper_thread(filters):
    global scrape_status
    try:
        # Run the scraper
        scrape_divar(filters, progress_callback=progress_callback)
    except Exception as e:
        progress_callback("error", f"Scraper crashed with error: {str(e)}")

# Route: Main entry serves viewer.html
@app.route('/')
def index():
    return send_from_directory('.', 'viewer.html')

@app.route('/viewer.html')
def viewer_direct():
    return send_from_directory('.', 'viewer.html')

@app.route('/districts.json')
def get_districts():
    return send_from_directory('.', 'districts.json')

# Search Presets Feature
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRESETS_FILE = os.path.join(BASE_DIR, "presets.json")

def load_presets():
    if os.path.exists(PRESETS_FILE):
        try:
            with open(PRESETS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_presets(presets):
    try:
        with open(PRESETS_FILE, 'w', encoding='utf-8') as f:
            json.dump(presets, f, indent=4, ensure_ascii=False)
        return True
    except Exception:
        return False

@app.route('/api/presets', methods=['GET'])
def get_presets_route():
    return jsonify(load_presets())

@app.route('/api/presets', methods=['POST'])
def save_preset_route():
    data = request.json or {}
    name = data.get("name", "").strip()
    filters = data.get("filters", {})
    if not name:
        return jsonify({"error": "Preset name is required"}), 400
        
    presets = load_presets()
    presets[name] = filters
    if save_presets(presets):
        return jsonify({"status": "success", "message": f"Preset '{name}' saved successfully."})
    else:
        return jsonify({"error": "Failed to save preset"}), 500

@app.route('/api/presets/<name>', methods=['DELETE'])
def delete_preset_route(name):
    presets = load_presets()
    if name in presets:
        del presets[name]
        if save_presets(presets):
            return jsonify({"status": "success", "message": f"Preset '{name}' deleted successfully."})
        else:
            return jsonify({"error": "Failed to delete preset"}), 500
    return jsonify({"error": f"Preset '{name}' not found"}), 404

# Route: List all CSV files in the workspace
@app.route('/api/csvs', methods=['GET'])
def list_csvs():
    csv_files = []
    # Search for all csv files in the current folder
    files = glob.glob("*.csv")
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        stat = os.stat(f)
        modified_time = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        csv_files.append({
            "name": f,
            "size_kb": round(stat.st_size / 1024.0, 1),
            "modified": modified_time
        })
    return jsonify(csv_files)

# Route: Serve a specific CSV file
@app.route('/api/csvs/<filename>', methods=['GET'])
def get_csv(filename):
    # Safety checks to prevent path traversal
    filename = os.path.basename(filename)
    if not filename.endswith('.csv'):
        return jsonify({"error": "Only CSV files are allowed"}), 400
    
    if not os.path.exists(filename):
        return jsonify({"error": f"File '{filename}' not found"}), 404
        
    response = send_from_directory('.', filename, as_attachment=True)
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    return response

# Route: Trigger new scraping task
@app.route('/api/scrape', methods=['POST'])
def start_scrape():
    global scrape_status, scrape_thread
    
    with scrape_lock:
        if scrape_status["status"] == "running":
            return jsonify({"error": "A scraping process is already running."}), 400
            
    # Parse filters from POST body
    data = request.json or {}
    
    # Extract filter options with robust defaults
    city_ids = data.get("city_ids", ["1"])
    category = data.get("category", "apartment-sell")
    
    # Area range
    area_min = int(data.get("area_min", 40))
    area_max = int(data.get("area_max", 140))
    
    # Price per m2 range (in Million Tomans)
    price_m2_min = float(data.get("price_m2_min", 175.0))
    price_m2_max = float(data.get("price_m2_max", 325.0))
    
    # Built year range
    year_min = int(data.get("year_min", 0))
    year_max = int(data.get("year_max", 9999))
    
    # Features (Yes / No / Any)
    elevator = data.get("elevator", "Yes")
    parking = data.get("parking", "Any")
    storage = data.get("storage", "Any")
    
    # Bedrooms (rooms) filter: Any, 0, 1, 2, 3, 4+
    rooms = data.get("rooms", "Any")
    
    # Authentic photos filter: Any, Yes, No
    authentic_photos = data.get("authentic_photos", "Any")
    
    # Total price range (in Billion Tomans)
    price_total_min = float(data.get("price_total_min", 0.0))
    price_total_max = float(data.get("price_total_max", 9999.0))
    
    # Target districts
    districts = data.get("districts", [])
    district_ids = data.get("district_ids", [])
    
    # Crawl settings
    max_pages = int(data.get("max_pages", 5))
    
    # Default to apartments.csv
    default_filename = "apartments.csv"
    output_filename = data.get("filename", "").strip() or default_filename
    
    # Force .csv extension and sanitize path
    output_filename = os.path.basename(output_filename)
    if not output_filename.endswith('.csv'):
        output_filename += '.csv'
        
    filters = {
        "city_ids": city_ids,
        "category": category,
        "area_min": area_min,
        "area_max": area_max,
        "price_m2_min": price_m2_min,
        "price_m2_max": price_m2_max,
        "price_total_min": price_total_min,
        "price_total_max": price_total_max,
        "year_min": year_min,
        "year_max": year_max,
        "elevator": elevator,
        "parking": parking,
        "storage": storage,
        "rooms": rooms,
        "authentic_photos": authentic_photos,
        "districts": districts,
        "district_ids": district_ids,
        "max_pages": max_pages,
        "output_file": output_filename
    }
    
    # Reset scrape status
    with scrape_lock:
        scrape_status = {
            "status": "running",
            "message": "Starting worker thread...",
            "current_page": 0,
            "total_pages": max_pages,
            "matches": 0,
            "log": [f"[{datetime.now().strftime('%H:%M:%S')}] Launching scraper thread..."],
            "filename": output_filename
        }
        
    # Start thread
    scrape_thread = threading.Thread(target=run_scraper_thread, args=(filters,))
    scrape_thread.daemon = True
    scrape_thread.start()
    
    return jsonify({
        "status": "started",
        "filename": output_filename,
        "message": f"Scraping started. Writing to {output_filename}"
    })

# Route: Check status of scrape job
@app.route('/api/scrape/status', methods=['GET'])
def get_scrape_status():
    global scrape_status
    with scrape_lock:
        return jsonify(scrape_status)

# Route: Reset scrape job status
@app.route('/api/scrape/cancel', methods=['POST'])
def cancel_scrape():
    global scrape_status
    with scrape_lock:
        if scrape_status["status"] == "running":
            scrape_status["status"] = "idle"
            scrape_status["message"] = "Scraper reset by user."
            scrape_status["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Scraper task stopped by user.")
            return jsonify({"status": "cancelled", "message": "Scraper stopped."})
        else:
            scrape_status["status"] = "idle"
            scrape_status["message"] = "Scraper is ready."
            scrape_status["log"] = []
            return jsonify({"status": "idle", "message": "Scraper reset."})

if __name__ == '__main__':
    print("--------------------------------------------------")
    print("Divar Tehran Apartments Web Analytics Server")
    print("Running locally at: http://localhost:5000")
    print("--------------------------------------------------")
    app.run(host='0.0.0.0', port=5000, debug=True)
