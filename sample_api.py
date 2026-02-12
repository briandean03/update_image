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

OLD_IMAGE_PATH = "/images/"
NEW_IMAGE_PATH = "/pictures/"
OLD_EXTENSION = ".jpg"
NEW_EXTENSION = ".webp"

PER_PAGE = int(os.getenv("PER_PAGE", 10))  # smaller batch
START_PAGE = int(os.getenv("START_PAGE", 1))
END_PAGE = int(os.getenv("END_PAGE", 50))
DELAY_BETWEEN_PAGES = float(os.getenv("DELAY_BETWEEN_PAGES", 4))
DELAY_BETWEEN_PRODUCTS = float(os.getenv("DELAY_BETWEEN_PRODUCTS", 2))
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 60))

CHECKPOINT_FILE = "checkpoint.json"
LOG_FILE = f"image_update_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# ---- HELPER FUNCTIONS ----
def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_checkpoint(page, product_id=None):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_page": page, "last_product_id": product_id}, f)

def transform_image_url(url: str) -> str:
    if not url or "static.recar.lt" not in url:
        return url
    transformed_url = url.replace(OLD_IMAGE_PATH, NEW_IMAGE_PATH)
    transformed_url = transformed_url.replace(OLD_EXTENSION, NEW_EXTENSION).replace(".JPG", NEW_EXTENSION)
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

# ---- MAIN LOGIC ----
def process_batch():
    checkpoint = load_checkpoint()
    resume_page = checkpoint.get("last_page", START_PAGE)
    resume_product_id = checkpoint.get("last_product_id")

    total_checked = total_updated = total_skipped = 0

    print(f"🔁 Resuming from page {resume_page}, after product ID {resume_product_id}\n")

    with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as log_file:
        writer = csv.writer(log_file)
        writer.writerow(["page", "product_id", "product_name", "old_url", "new_url", "status"])

        for page in range(resume_page, END_PAGE + 1):
            print(f"\n🔹 Fetching page {page} ...")
            try:
                response = requests.get(
                    API_URL,
                    auth=(CONSUMER_KEY, CONSUMER_SECRET),
                    params={"per_page": PER_PAGE, "page": page},
                    timeout=TIMEOUT
                )
                response.raise_for_status()
            except requests.RequestException as e:
                print(f"❌ Error fetching page {page}: {e}")
                writer.writerow([page, "-", "-", "-", "-", f"ERROR {e}"])
                time.sleep(DELAY_BETWEEN_PAGES)
                continue

            products = response.json()
            if not products:
                print(f"⚠️ No products on page {page}.")
                writer.writerow([page, "-", "-", "-", "-", "EMPTY PAGE"])
                time.sleep(DELAY_BETWEEN_PAGES)
                continue

            for product in products:
                # Skip already-processed products on resume page
                if page == resume_page and resume_product_id and product["id"] <= resume_product_id:
                    continue

                total_checked += 1
                meta_data = product.get("meta_data", [])
                image_meta = next((m for m in meta_data if m.get("key") == "product_images_url"), None)
                if not image_meta:
                    total_skipped += 1
                    continue

                urls = normalize_urls(image_meta.get("value"))
                if not urls:
                    total_skipped += 1
                    continue

                updated_urls = [transform_image_url(u) for u in urls]
                if urls == updated_urls:
                    total_skipped += 1
                    continue

                total_updated += 1
                print(f"\n🟩 Product ID: {product['id']} | {product['name']}")
                for old, new in zip(urls, updated_urls):
                    if old != new:
                        print(f"  OLD: {old}")
                        print(f"  NEW: {new}")
                        writer.writerow([page, product["id"], product["name"], old, new, "UPDATED"])

                image_meta["value"] = updated_urls
                payload = {"meta_data": meta_data}

                try:
                    update = requests.put(
                        f"{API_URL}/{product['id']}",
                        auth=(CONSUMER_KEY, CONSUMER_SECRET),
                        json=payload,
                        timeout=TIMEOUT
                    )
                    update.raise_for_status()
                    save_checkpoint(page, product["id"])
                    time.sleep(DELAY_BETWEEN_PRODUCTS)
                except requests.RequestException as e:
                    print(f"  ❌ Failed to update product {product['id']}: {e}")
                    writer.writerow([page, product["id"], product["name"], "-", "-", f"FAILED {e}"])

            save_checkpoint(page)
            time.sleep(DELAY_BETWEEN_PAGES)

    print("\n----- SUMMARY -----")
    print(f"✅ Pages processed: {START_PAGE} → {END_PAGE}")
    print(f"✅ Products checked: {total_checked}")
    print(f"🧩 Updated: {total_updated}")
    print(f"⏩ Skipped: {total_skipped}")
    print(f"🗂️ Log file saved as: {LOG_FILE}")
    print("📍 Last checkpoint saved at:", CHECKPOINT_FILE)
    print("-------------------")
    print("🎯 Batch complete! You can safely stop and resume anytime.")

# ---- FLASK WEB SERVICE ----
app = Flask(__name__)

@app.route("/")
def home():
    return "🟢 Secrab Image Updater running (Render Web Service mode)"

@app.route("/status")
def status():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(data)
    return jsonify({"status": "no checkpoint yet"})

def start_updater():
    while True:
        try:
            process_batch()
            print("✅ Batch finished. Exiting updater loop.")
            break
        except Exception as e:
            print(f"⚠️ Updater crashed: {e}")
            print("⏳ Retrying in 30 seconds...")
            time.sleep(30)

if __name__ == "__main__":
    # Run updater in background
    threading.Thread(target=start_updater, daemon=True).start()
    # Keep Render alive
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
