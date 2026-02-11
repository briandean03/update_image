import requests
import json
import time
import csv
import os
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, jsonify
import threading

# ---- LOAD ENV ----
load_dotenv()

# ---- CONFIGURATION ----
API_URL = "https://server.secrab.store/wp-json/wc/v3/products"
CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")

# UPDATED: New transformation rules
OLD_IMAGE_PATH = "/images/"
NEW_IMAGE_PATH = "/pictures/"
OLD_EXTENSION = ".jpg"
NEW_EXTENSION = ".webp"

PER_PAGE = int(os.getenv("PER_PAGE", 20))  # ← ADDED THIS
START_PAGE = int(os.getenv("START_PAGE", 1))
END_PAGE = int(os.getenv("END_PAGE", 100))
DELAY_SECONDS = float(os.getenv("DELAY_SECONDS", 10))  # ← CHANGED DEFAULT TO 10

LOG_FILE = f"image_update_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# ---- HELPER FUNCTIONS ----

def transform_image_url(url: str) -> str:
    """
    Transform image URLs from static.recar.lt domain:
    - Replace /images/ with /pictures/
    - Replace .jpg with .webp
    
    Example:
    https://static.recar.lt/images/JVlNnjdlRy/24727104_xxx.jpg
    -> https://static.recar.lt/pictures/JVlNnjdlRy/24727104_xxx.webp
    """
    if not url:
        return url
    
    # Only transform URLs starting with static.recar.lt
    if "static.recar.lt" not in url:
        return url
    
    # Replace /images/ with /pictures/
    transformed_url = url.replace(OLD_IMAGE_PATH, NEW_IMAGE_PATH)
    
    # Replace .jpg with .webp (case-insensitive)
    transformed_url = transformed_url.replace(OLD_EXTENSION, NEW_EXTENSION)
    transformed_url = transformed_url.replace(OLD_EXTENSION.upper(), NEW_EXTENSION)
    transformed_url = transformed_url.replace(".JPG", NEW_EXTENSION)
    
    return transformed_url

def normalize_urls(raw_value):
    if isinstance(raw_value, list):
        return [str(u).strip() for u in raw_value]
    if isinstance(raw_value, str):
        try:
            data = json.loads(raw_value)
            if isinstance(data, list):
                return [str(u).strip() for u in data]
        except json.JSONDecodeError:
            return [u.strip() for u in raw_value.split(",") if u.strip()]
    return []


# ---- FLASK WEB SERVICE FOR RENDER ----

app = Flask(__name__)

# Global progress tracker
progress = {
    "status": "not started",
    "current_page": 0,
    "total_pages": 0,
    "products_checked": 0,
    "products_updated": 0,
    "products_skipped": 0,
    "start_time": None,
    "last_update": None
}

@app.route("/")
def home():
    return "🟢 Secrab Image Updater running (Render Web Service mode)"

@app.route("/status")
def status():
    return jsonify(progress)

# ---- MAIN LOGIC ----

def main():
    global progress
    
    progress["status"] = "running"
    progress["total_pages"] = END_PAGE - START_PAGE + 1
    progress["start_time"] = datetime.now().isoformat()
    
    total_checked = 0
    total_updated = 0
    total_skipped = 0

    print(f"🔁 Starting from page {START_PAGE} to {END_PAGE}\n")
    print(f"⏱️  Delay between pages: {DELAY_SECONDS} seconds\n")

    with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as log_file:
        writer = csv.writer(log_file)
        writer.writerow(["page", "product_id", "product_name", "old_url", "new_url", "status"])

        for page in range(START_PAGE, END_PAGE + 1):
            progress["current_page"] = page
            progress["last_update"] = datetime.now().isoformat()
            
            print(f"\n🔹 Fetching page {page} ...")
            response = requests.get(
                API_URL,
                auth=(CONSUMER_KEY, CONSUMER_SECRET),
                params={"per_page": PER_PAGE, "page": page}
            )

            if response.status_code != 200:
                print(f"❌ Error fetching page {page}: {response.status_code}")
                writer.writerow([page, "-", "-", "-", "-", f"ERROR {response.status_code}"])
                time.sleep(DELAY_SECONDS)
                continue

            products = response.json()
            if not products:
                print(f"⚠️ No products on page {page}.")
                writer.writerow([page, "-", "-", "-", "-", "EMPTY PAGE"])
                time.sleep(DELAY_SECONDS)
                continue

            for product in products:
                total_checked += 1
                progress["products_checked"] = total_checked
                
                meta_data = product.get("meta_data", [])
                image_meta = next((m for m in meta_data if m.get("key") == "product_images_url"), None)
                if not image_meta:
                    total_skipped += 1
                    progress["products_skipped"] = total_skipped
                    continue

                urls = normalize_urls(image_meta.get("value"))
                if not urls:
                    total_skipped += 1
                    progress["products_skipped"] = total_skipped
                    continue

                updated_urls = [transform_image_url(u) for u in urls]
                if urls == updated_urls:
                    total_skipped += 1
                    progress["products_skipped"] = total_skipped
                    continue

                total_updated += 1
                progress["products_updated"] = total_updated
                
                print(f"\n🟩 Product ID: {product['id']} | {product['name']}")
                for old, new in zip(urls, updated_urls):
                    if old != new:
                        print(f"  OLD: {old}")
                        print(f"  NEW: {new}")
                        writer.writerow([page, product["id"], product["name"], old, new, "UPDATED"])

                image_meta["value"] = updated_urls
                payload = {"meta_data": meta_data}
                update = requests.put(
                    f"{API_URL}/{product['id']}",
                    auth=(CONSUMER_KEY, CONSUMER_SECRET),
                    json=payload
                )

                if update.status_code == 200:
                    print(f"  ✅ Updated product {product['id']}")
                else:
                    print(f"  ❌ Failed to update product {product['id']}: {update.status_code}")
                    writer.writerow([page, product["id"], product["name"], "-", "-", f"FAILED {update.status_code}"])

            time.sleep(DELAY_SECONDS)

    progress["status"] = "completed"
    progress["last_update"] = datetime.now().isoformat()
    
    print("\n----- SUMMARY -----")
    print(f"✅ Pages processed: {START_PAGE} → {END_PAGE}")
    print(f"✅ Products checked: {total_checked}")
    print(f"🧩 Updated: {total_updated}")
    print(f"⏩ Skipped: {total_skipped}")
    print(f"🗂️ Log file saved as: {LOG_FILE}")
    print("-------------------")
    print("🎯 Batch complete!")
    
def start_updater():
    main()

if __name__ == "__main__":
    # Run the updater in background
    threading.Thread(target=start_updater, daemon=True).start()
    # Start Flask app to keep Render alive
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
