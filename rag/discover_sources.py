"""Discover links published on IITK DoAA pages and save a source inventory.

This is an inventory-only step: it does NOT download documents or call an AI API.
"""

import csv
import json
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

with open("sources.json", "r", encoding="utf-8") as file:
    config = json.load(file)

SEEDS = config["seed_urls"]
ALLOWED_DOMAINS = set(config["allowed_domains"])

HEADERS = {
    "User-Agent": "BabyBot-IITK-KnowledgeBase/0.1 (educational source discovery)"
}

session = requests.Session()
session.headers.update(HEADERS)


def is_allowed_url(url):
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() in ALLOWED_DOMAINS


def classify_link(url, anchor_text):
    path = urlparse(url).path.lower()
    text = anchor_text.lower()
    if path.endswith(".pdf"):
        return "PDF"
    if any(word in text for word in ["calendar", "manual", "rule", "regulation", "ordinance"]):
        return "Academic reference page"
    if any(word in text for word in ["notice", "announcement", "circular", "order"]):
        return "Notice / announcement"
    return "Webpage"


def main():
    queue = deque(SEEDS)
    visited_pages = set()
    discovered = {}

    while queue:
        page_url = queue.popleft()
        page_url = urldefrag(page_url)[0]
        if page_url in visited_pages or not is_allowed_url(page_url):
            continue
        visited_pages.add(page_url)

        print(f"Inspecting: {page_url}")
        try:
            response = session.get(page_url, timeout=25)
            response.raise_for_status()
        except requests.RequestException as error:
            print(f"  Could not access page: {error}")
            continue

        content_type = response.headers.get("Content-Type", "").lower()
        if "html" not in content_type:
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup.find_all("a", href=True):
            target = urldefrag(urljoin(response.url, tag["href"]))[0]
            if not is_allowed_url(target):
                continue

            title = " ".join(tag.get_text(" ", strip=True).split()) or target.rsplit("/", 1)[-1]
            discovered[target] = {
                "title": title,
                "url": target,
                "type": classify_link(target, title),
                "discovered_from": response.url
            }

            # Follow only DoAA pages, not every institute page linked from DoAA.
            parsed = urlparse(target)
            if parsed.path.startswith("/doaa") and not parsed.path.lower().endswith(".pdf"):
                if target not in visited_pages:
                    queue.append(target)

        time.sleep(0.4)  # Be polite to the institute website.

    rows = sorted(discovered.values(), key=lambda item: (item["type"], item["title"].lower()))
    output_file = "doaa_source_inventory.csv"
    with open(output_file, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["title", "url", "type", "discovered_from"])
        writer.writeheader()
        writer.writerows(rows)

    print("\nDiscovery complete.")
    print(f"Pages inspected: {len(visited_pages)}")
    print(f"Unique links found: {len(rows)}")
    print(f"Inventory saved to: {output_file}")
    print("Review the CSV before downloading or indexing anything.")


if __name__ == "__main__":
    main()
