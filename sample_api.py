import requests
import json
import time
import csv
from datetime import datetime

# ---- CONFIGURATION ----
API_URL = "https://server.secrab.store/wp-json/wc/v3/products"
CONSUMER_KEY = "ck_770033c87b39978e6213fc1557b5603c9a1e1252"
CONSUMER_SECRET = "cs_1665a56751b51d069227385b4574c8cc451fec0e"

OLD_DOMAIN = "https://d1ef4a9755q128.cloudfront.net/images/"
NEW_DOMAIN = "https://static.recar.lt/images/"

PER_PAGE = 20
START_PAGE = 5       # continue from where you left off
END_PAGE = 50     # run in batches (max ~2,000 products per run)
DELAY_SECONDS = 0.8  # wait time between page requests

LOG_FILE = f"image_update_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"


# ---- HELPER FUNCTIONS ----

def transform_image_url(url: str) -> str:
    if not url or OLD_DOMAIN not in url:
        return url
    return url.replace(OLD_DOMAIN, NEW_DOMAIN).replace("/1050x700/", "/")

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


# ---- MAIN ----

def main():
    total_checked = 0
    total_updated = 0
    total_skipped = 0

    # create log file
    with open(LOG_FILE, mode="w", newline="", encoding="utf-8") as log_file:
        writer = csv.writer(log_file)
        writer.writerow(["page", "product_id", "product_name", "old_url", "new_url", "status"])

        for page in range(START_PAGE, END_PAGE + 1):
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

                # ---- Perform the update ----
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

            # ---- Respect API limits ----
            time.sleep(DELAY_SECONDS)

    # ---- SUMMARY ----
    print("\n----- SUMMARY -----")
    print(f"✅ Pages processed: {START_PAGE} → {END_PAGE}")
    print(f"✅ Products checked: {total_checked}")
    print(f"🧩 Updated: {total_updated}")
    print(f"⏩ Skipped: {total_skipped}")
    print(f"🗂️ Log file saved as: {LOG_FILE}")
    print("-------------------")
    print("🎯 Batch complete! You can now continue with the next range safely.")


if __name__ == "__main__":
    main()
