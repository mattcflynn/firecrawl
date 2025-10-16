# Coder's Note:
# This script is the database-aware version of the scraper, built from the
# user's latest file-based scraper. It connects to the SQLite database,
# intelligently scrapes stores based on a staggering schedule, and only
# records new prices when a change is detected.
# Last checked: October 4, 2025

import os
import re
import time
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from firecrawl import Firecrawl

# --- Configuration ---
load_dotenv() # Loads variables from .env file
API_KEY = os.getenv("FIRECRAWL_API_KEY")
FIRECRAWL_API_URL = os.getenv("FIRECRAWL_API_URL") # For self-hosting
DB_FILENAME = "macrobell.db"

# --- Filtering logic from your latest scraper ---
EXCLUDED_CATEGORIES = ["groups", "drinks"]
EXCLUDED_ITEM_SUFFIXES = [
    "box", "meal", "combo", "sauce", "packet", "salsa", "pack", "meal for 2", "meal for 4"
]

def get_stores_to_scrape(conn):
    """
    Fetches the list of store IDs to be scraped from the database.
    Applies staggering logic if enabled.
    With self-hosting, we can scrape all stores every time.
    """
    cur = conn.cursor()
    cur.execute("SELECT store_id FROM stores ORDER BY store_id")
    all_store_ids = [row[0] for row in cur.fetchall()]
    
    print(f"Loaded {len(all_store_ids)} stores from the database for a full scrape.")
    return all_store_ids

def get_latest_price(conn, store_id, item_name):
    """
    Gets the most recently recorded price for an item at a specific store.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT price FROM prices
        WHERE store_id = ? AND item_name = ?
        ORDER BY scrape_date DESC
        LIMIT 1
    """, (store_id, item_name))
    result = cur.fetchone()
    return result[0] if result else None

def main():
    if not API_KEY and not FIRECRAWL_API_URL:
        raise ValueError("FIRECRAWL_API_KEY not found in .env file. Please create a .env file with your key.")

    conn = sqlite3.connect(DB_FILENAME)
    
    stores_to_scrape = get_stores_to_scrape(conn)
    if not stores_to_scrape:
        print("No stores found in the database to scrape.")
        conn.close()
        return

    try:
        if FIRECRAWL_API_URL:
            print(f"--- Using self-hosted Firecrawl at {FIRECRAWL_API_URL} ---")
            app = Firecrawl(api_url=FIRECRAWL_API_URL)
        else:
            # This print statement was missing, adding it for consistency.
            print("--- Using Firecrawl cloud service ---")
            app = Firecrawl(api_key=API_KEY)

        today_str = datetime.now().strftime("%Y-%m-%d")

        for i, store_id in enumerate(stores_to_scrape):
            print("\n" + "="*40)
            print(f"Processing store {i+1}/{len(stores_to_scrape)}: ID {store_id}")
            print("="*40)
            
            items_processed = 0
            prices_changed = 0
            # Use a set to avoid processing the same item multiple times if it appears on multiple pages
            seen_items_for_store = set()

            try:
                # This is the starting point for the crawl.
                crawl_url = f"https://www.tacobell.com/food?store={store_id}"
                print(f" - Crawling menu pages for store {store_id}...")

                # Use crawl instead of scrape. This is 1 credit per store.
                crawled_pages = app.crawl(
                    url=crawl_url,
                    params={
                        'crawlerOptions': {
                            'includes': ['/food/*'], # Only crawl pages under the /food/ path
                            'excludes': ['/food/drinks', '/food/groups'], # Exclude specific category pages
                            'maxDepth': 1, # Only go 1 level deep from the start URL
                        }
                    },
                    wait_for=2 # Wait 2 seconds for page to load before crawling
                )

                if not crawled_pages:
                    print(f"  -> FAILED: Crawl returned no pages for store {store_id}.")
                    continue

                print(f"  -> Success: Crawl returned {len(crawled_pages)} pages. Processing items...")
                # Loop through each page returned by the crawl
                for page_data in crawled_pages:
                    item_pattern = re.compile(r"\[\*\*([^\*]+)\*\*\]\(.*\)\n\n(\$[\d\.]+)")
                    matches = item_pattern.findall(page_data.markdown)
                    
                    for name, price_str in matches:
                        items_processed += 1
                        if any(name.lower().endswith(suffix) for suffix in EXCLUDED_ITEM_SUFFIXES):
                            continue

                        # Clean the price string and convert to float
                        price_float_str = re.sub(r'[^\d.]', '', price_str)
                        if not price_float_str: continue
                        price_float = float(price_float_str)

                        # If we've already processed this item for this store, skip it
                        if name in seen_items_for_store:
                            continue
                        seen_items_for_store.add(name)
                        
                        # --- "Store Only on Change" Logic ---
                        last_price = get_latest_price(conn, store_id, name)
                        
                        if last_price is None or not abs(last_price - price_float) < 0.001: # Compare floats safely
                            print(f"   -> PRICE CHANGE: '{name}' from ${last_price} to ${price_float}")
                            conn.execute(
                                "INSERT INTO prices (store_id, item_name, price, scrape_date) VALUES (?, ?, ?, ?)",
                                (store_id, name, price_float, today_str)
                            )
                            prices_changed += 1

            except Exception as e:
                print(f"  -> An error occurred while crawling store {store_id}: {e}")
                continue
            
            # Update the last_scraped_date for the store once all categories are done
            conn.execute("UPDATE stores SET last_scraped_date = ? WHERE store_id = ?", (today_str, store_id))
            conn.commit()
            print(f"\nFinished store {store_id}. Processed {items_processed} items, recorded {prices_changed} price changes.")

    except Exception as e:
        print(f"\nAn overall error occurred: {e}")
    finally:
        print("\n--- Scrape complete. Closing database connection. ---")
        conn.close()

if __name__ == "__main__":
    main()