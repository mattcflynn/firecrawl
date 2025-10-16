# Coder's Note:
# Database-aware Taco Bell scraper using Firecrawl (self-hosted or cloud)
# - Checks for price changes and only records updates
# - Compatible with latest Firecrawl SDK (Oct 2025)
# - Handles both self-hosted and cloud environments automatically

import os
import re
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from firecrawl import Firecrawl

# --- Configuration ---
load_dotenv()  # Loads variables from .env
API_KEY = os.getenv("FIRECRAWL_API_KEY")
FIRECRAWL_API_URL = os.getenv("FIRECRAWL_API_URL")  # for self-hosting
DB_FILENAME = "macrobell.db"

EXCLUDED_CATEGORIES = ["groups", "drinks"]
EXCLUDED_ITEM_SUFFIXES = [
    "box", "meal", "combo", "sauce", "packet", "salsa", "pack", "meal for 2", "meal for 4"
]


# ---------------------- Database helpers ----------------------
def get_stores_to_scrape(conn):
    """Fetch list of store IDs from the database."""
    cur = conn.cursor()
    cur.execute("SELECT store_id FROM stores ORDER BY store_id")
    all_store_ids = [row[0] for row in cur.fetchall()]
    print(f"Loaded {len(all_store_ids)} stores from the database for a full scrape.")
    return all_store_ids


def get_latest_price(conn, store_id, item_name):
    """Get the most recently recorded price for a specific item."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT price FROM prices
        WHERE store_id = ? AND item_name = ?
        ORDER BY scrape_date DESC
        LIMIT 1
        """,
        (store_id, item_name),
    )
    result = cur.fetchone()
    return result[0] if result else None

import inspect

def crawl_any(fc, url, includes=None, excludes=None, max_depth=1,
              formats=("markdown",), only_main=True, limit=50):
    includes = includes or []
    excludes = excludes or []

    camel_crawler = {"includes": includes, "excludes": excludes, "maxDepth": max_depth}
    camel_scrape  = {"formats": list(formats), "onlyMainContent": bool(only_main)}

    snake_crawler = {"includes": includes, "excludes": excludes, "max_depth": max_depth}
    snake_scrape  = {"formats": list(formats), "only_main_content": bool(only_main)}

    # A) Newer 4.x (your error hints this is likely): camelCase kwargs at top level
    try:
        res = fc.crawl(
            url=url,
            crawlerOptions=camel_crawler,
            scrapeOptions=camel_scrape,
            limit=limit,
        )
        print("crawl_any: used A) camelCase kwargs")
        return res
    except TypeError as eA:
        last = eA

    # B) Other 4.x builds: snake_case kwargs at top level
    try:
        res = fc.crawl(
            url=url,
            crawler_options=snake_crawler,
            scrape_options=snake_scrape,
            limit=limit,
        )
        print("crawl_any: used B) snake_case kwargs")
        return res
    except TypeError as eB:
        last = eB

    # C) Very recent experiment some users hit: params + camelCase
    try:
        res = fc.crawl(
            url=url,
            scrape_options=snake_scrape,  # accepted widely
            params={"crawlerOptions": camel_crawler},
            limit=limit,
        )
        print("crawl_any: used C) params + camelCase")
        return res
    except TypeError as eC:
        last = eC

    # D) Legacy positional API (crawl_url or crawl)
    meth = getattr(fc, "crawl_url", None) or getattr(fc, "crawl", None)
    if meth:
        try:
            res = meth(url, camel_crawler, camel_scrape, limit)
            print("crawl_any: used D) positional legacy")
            return res
        except TypeError as eD:
            last = eD

    # If all failed, show the actual signature we found to debug
    sig = None
    try:
        sig = inspect.signature(getattr(fc, "crawl"))
    except Exception:
        pass
    raise TypeError(f"Firecrawl crawl signature mismatch. Found signature={sig}. Last error: {last}")


# ---------------------- Main scraper logic ----------------------
def main():
    if not API_KEY and not FIRECRAWL_API_URL:
        raise ValueError(
            "No Firecrawl configuration found. Set FIRECRAWL_API_URL for self-host "
            "or FIRECRAWL_API_KEY for cloud in your .env file."
        )

    # Connect to SQLite database
    conn = sqlite3.connect(DB_FILENAME)
    stores_to_scrape = get_stores_to_scrape(conn)
    if not stores_to_scrape:
        print("No stores found in the database to scrape.")
        conn.close()
        return

    try:
        # Initialize Firecrawl client
        print(
            f"--- Using {'self-hosted' if FIRECRAWL_API_URL else 'cloud'} Firecrawl "
            f"{'at ' + FIRECRAWL_API_URL if FIRECRAWL_API_URL else ''} ---"
        )
        app = Firecrawl(api_key=API_KEY, api_url=FIRECRAWL_API_URL or None)

        today_str = datetime.now().strftime("%Y-%m-%d")

        for i, store_id in enumerate(stores_to_scrape):
            print("\n" + "=" * 40)
            print(f"Processing store {i + 1}/{len(stores_to_scrape)}: ID {store_id}")
            print("=" * 40)

            items_processed = 0
            prices_changed = 0
            seen_items_for_store = set()

            try:
                crawl_url = f"https://www.tacobell.com/food?store={store_id}"
                print(f" - Crawling menu pages for store {store_id}...")

                crawled_pages = app.crawl(
                    url=crawl_url,
                    include_paths=["/food/*"],
                    exclude_paths=["/food/drinks", "/food/groups"],
                    max_discovery_depth=1,
                    limit=50,  # optional safeguard
                    scrape_options={
                        "formats": ["markdown"],
                        "only_main_content": True,
                        # "wait_for": 2000,  # optional ms if you need more JS settle time
                    },
                )






                if not crawled_pages:
                    print(f"  -> FAILED: Crawl returned no pages for store {store_id}.")
                    continue

                print(f"  -> Success: Crawl returned {len(crawled_pages)} pages. Processing items...")

                # Loop through each crawled page
                for page_data in crawled_pages:
                    # Handle Pydantic model vs dict gracefully
                    md = getattr(page_data, "markdown", None)
                    if not md:
                        try:
                            md = page_data.model_dump().get("markdown")
                        except Exception:
                            md = None
                    if not md:
                        continue

                    # Regex pattern for markdown list: [**Name**](link) + price
                    item_pattern = re.compile(r"\[\*\*([^\*]+)\*\*\]\(.*\)\n\n(\$[\d\.]+)")
                    matches = item_pattern.findall(md)

                    for name, price_str in matches:
                        items_processed += 1
                        if any(name.lower().endswith(suffix) for suffix in EXCLUDED_ITEM_SUFFIXES):
                            continue

                        price_float_str = re.sub(r"[^\d.]", "", price_str)
                        if not price_float_str:
                            continue
                        price_float = float(price_float_str)

                        if name in seen_items_for_store:
                            continue
                        seen_items_for_store.add(name)

                        last_price = get_latest_price(conn, store_id, name)

                        if last_price is None or abs(last_price - price_float) >= 0.001:
                            print(f"   -> PRICE CHANGE: '{name}' from ${last_price} to ${price_float}")
                            conn.execute(
                                "INSERT INTO prices (store_id, item_name, price, scrape_date) VALUES (?, ?, ?, ?)",
                                (store_id, name, price_float, today_str),
                            )
                            prices_changed += 1

            except Exception as e:
                print(f"  -> An error occurred while crawling store {store_id}: {e}")
                continue

            # Update last_scraped_date after each store
            conn.execute(
                "UPDATE stores SET last_scraped_date = ? WHERE store_id = ?",
                (today_str, store_id),
            )
            conn.commit()
            print(
                f"\nFinished store {store_id}. Processed {items_processed} items, recorded {prices_changed} price changes."
            )

    except Exception as e:
        print(f"\nAn overall error occurred: {e}")
    finally:
        print("\n--- Scrape complete. Closing database connection. ---")
        conn.close()


if __name__ == "__main__":
    main()
