from datetime import datetime

from selenium import webdriver

import kindle_search
from constants import USER_DATA_DIR, PROFILE_NAME


def prompt_run_settings():
	raw = input("Keywords (comma-separated): ").strip()
	keywords = [part.strip() for part in raw.split(",") if part.strip()]

	if not keywords:
		raise SystemExit("No keywords given.")

	pages_raw = input("Pages per keyword [3]: ").strip()

	try:
		pages = int(pages_raw) if pages_raw else 3
	except ValueError:
		raise SystemExit("Pages per keyword must be a number.")

	if pages < 1:
		pages = 1

	default_path = f"harvested/kindle_links_{datetime.now():%Y%m%d_%H%M%S}.csv"
	path_raw = input(f"Output path [{default_path}]: ").strip()

	return keywords, pages, path_raw or default_path


def build_driver():
	options = webdriver.EdgeOptions()

	options.add_experimental_option("excludeSwitches", ["enable-automation"])
	options.add_experimental_option("useAutomationExtension", False)
	options.add_argument("--disable-blink-features=AutomationControlled")
	options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
	options.add_argument(f"--profile-directory={PROFILE_NAME}")

	return webdriver.Edge(options=options)


keywords, pages, output_path = prompt_run_settings()

driver = build_driver()

try:
	harvest = kindle_search.KindleSearchUtils(driver)
	records = harvest.harvest(keywords, pages, output_path)

	print(f"\nHarvested {len(records)} unique books")

	for keyword in keywords:
		count = sum(1 for record in records if record["keyword"] == keyword)
		print(f"  {keyword!r}: {count}")

	print(f"Wrote {output_path}")
finally:
	input("Press Enter to exit...")
	driver.quit()
