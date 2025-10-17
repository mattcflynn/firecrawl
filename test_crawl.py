from firecrawl import Firecrawl
app = Firecrawl(api_url="http://localhost:3002")

crawl_url = "https://www.tacobell.com/food?store=000274"

job = app.crawl(
    url=crawl_url,
    include_paths=["/food/*"],
    exclude_paths=["/food/drinks", "/food/groups"],
    max_discovery_depth=1,
    limit=30,
    delay=2000,          # be gentle
    max_concurrency=1,   # one tab at a time
    timeout=120,
    scrape_options={"formats": ["markdown"], "only_main_content": True, "wait_for": 2000},
)

# fetch pages from the job
if hasattr(app, "get_crawl_result"):
    pages = app.get_crawl_result(job_id=job.id, poll_interval=2, timeout=180)
else:
    pages = app.crawl_result(job.id, poll_interval=2, timeout=180)

# normalize and read markdown
if hasattr(pages, "data"):
    pages = pages.data

for p in pages or []:
    md = getattr(p, "markdown", None)
    if not md:
        try: md = p.model_dump().get("markdown")
        except Exception: md = p.get("markdown") if isinstance(p, dict) else None
    if md:
        print(md[:200])
        break
