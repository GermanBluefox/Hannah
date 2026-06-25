#!/usr/bin/env python3
"""
Screenshot helper for the webui started by driver.py. Needs Playwright +
its Chromium build (see SKILL.md Prerequisites) — not a webui dependency,
only used to visually verify pages from an agent.
"""
import argparse

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("out", help="output .png path")
    args = parser.parse_args()

    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1100, "height": 700})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(args.url, wait_until="networkidle")
        page.screenshot(path=args.out, full_page=True)
        browser.close()

    if errors:
        print("console errors:")
        for e in errors:
            print(" ", e)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
