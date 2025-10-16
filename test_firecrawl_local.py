from dotenv import load_dotenv
import os
from firecrawl import Firecrawl

load_dotenv()
client = Firecrawl(
    api_key=os.getenv("FIRECRAWL_API_KEY"),
    api_url=os.getenv("FIRECRAWL_API_URL", "http://localhost:3002"),
)

doc = client.scrape("https://example.com", formats=["markdown","html"])

# normalize to dict
data = doc.model_dump() if hasattr(doc, "model_dump") else (doc.dict() if hasattr(doc, "dict") else doc)
md = data.get("markdown") or getattr(doc, "markdown", None)
ht = data.get("html") or getattr(doc, "html", None)

print((md or ht or "")[:400])
