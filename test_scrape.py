from firecrawl import Firecrawl

app = Firecrawl(api_url="http://localhost:3002", api_key="test")  # local self-hosted Firecrawl


# Test a simple page (not Taco Bell yet)
res = app.scrape(
    url="https://example.com",
    scrape_options={"formats": ["markdown"], "only_main_content": True, "wait_for": 1000},
)

print(type(res))
if hasattr(res, "markdown"):
    print(res.markdown[:400])
else:
    print(res)
