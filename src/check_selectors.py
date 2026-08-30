"""Report which Amazon Kindle selectors resolve against the page you actually get.

Amazon's search markup changes between deploys, so a selector that works one
week can silently find nothing the next. This walks the harvest selectors and
prints what resolved, what is absent, and what broke.

It does not type queries or write a harvest file. It only reads amazon.com
and a Kindle search results page.

	poetry run python src/check_selectors.py

Paste the output into a bug report. FAILED is what needs fixing.
"""

import sys
import time

from selenium import webdriver
from selenium.webdriver.common.by import By

import element_selectors
from constants import USER_DATA_DIR, PROFILE_NAME

RENDER_TIMEOUT = 60
KINDLE_RESULTS_URL = "https://www.amazon.com/s?k=mystery&i=digital-text"


def build_driver():
	options = webdriver.EdgeOptions()

	options.add_experimental_option("excludeSwitches", ["enable-automation"])
	options.add_experimental_option("useAutomationExtension", False)
	options.add_argument("--disable-blink-features=AutomationControlled")
	options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
	options.add_argument(f"--profile-directory={PROFILE_NAME}")

	return webdriver.Edge(options=options)


def wait_until(predicate, timeout=RENDER_TIMEOUT):
	deadline = time.time() + timeout

	while time.time() < deadline:
		try:
			if predicate():
				return True
		except Exception:
			pass

		time.sleep(2)

	return False


class Report:
	def __init__(self):
		self.rows = []

	def record(self, name, status, detail=""):
		self.rows.append((name, status, detail))
		print(f"  {status:<8} {name:<44} {detail}")

	def check(self, name, fn, optional=False):
		try:
			value = fn()
		except Exception as exc:
			self.record(name, "ABSENT" if optional else "FAILED", type(exc).__name__)
			return None

		if isinstance(value, list):
			detail = f"{len(value)} element(s)"

			if not value and optional:
				self.record(name, "ABSENT", "0 elements")
				return value
		elif isinstance(value, bool):
			detail = str(value)
		elif isinstance(value, dict):
			detail = repr(value.get("title") or value.get("asin") or value)[:44]
		else:
			try:
				detail = repr((value.text or "").replace("\n", " | ")[:44])
			except Exception:
				detail = "<element>"

		self.record(name, "OK", detail)
		return value

	def summary(self):
		counts = {"OK": 0, "ABSENT": 0, "FAILED": 0}

		for _, status, _ in self.rows:
			counts[status] = counts.get(status, 0) + 1

		print(f"\nOK={counts['OK']}  ABSENT={counts['ABSENT']}  FAILED={counts['FAILED']}")

		return counts["FAILED"]


def describe_environment(driver):
	print("\n## environment")

	caps = driver.capabilities

	print(f"  browser        {caps.get('browserVersion')}")
	print(f"  msedgedriver   {caps.get('msedge', {}).get('msedgedriverVersion', '?').split(' ')[0]}")
	print(f"  selenium       {getattr(__import__('selenium'), '__version__', '?')}")
	print(f"  python         {sys.version.split()[0]}")
	print(f"  url            {driver.current_url}")
	print(f"  page lang      {driver.find_element(By.TAG_NAME, 'html').get_attribute('lang')!r}")
	print(f"  viewport       {driver.execute_script('return [window.innerWidth, window.innerHeight];')}")


def main():
	driver = build_driver()
	elements = element_selectors.ElementSelectionUtils(driver)
	report = Report()

	try:
		driver.get(element_selectors.AMAZON_HOME)

		if elements.is_captcha_page():
			print("Amazon is showing a captcha. Solve it in the browser, then re-run.")
			return 2

		rendered = wait_until(lambda: elements.get_search_box() is not None)

		if not rendered:
			print("amazon.com never finished rendering the search box.")
			print("A captcha, continue-shopping wall, or cookie banner may be blocking it.")
			print("Open the profile in a normal Edge window, dismiss it, then run this again.")
			return 2

		describe_environment(driver)

		print("\n## home")
		report.check("get_search_box", elements.get_search_box)
		report.check("get_search_submit", elements.get_search_submit)
		report.check("get_department_dropdown", elements.get_department_dropdown)
		report.check("is_captcha_page", elements.is_captcha_page)
		report.check("get_continue_shopping_button", elements.get_continue_shopping_button, optional=True)

		print("\n## kindle results")
		driver.get(KINDLE_RESULTS_URL)

		if elements.is_captcha_page():
			print("Amazon is showing a captcha on the results page. Solve it, then re-run.")
			return 2

		wait_until(lambda: bool(elements.get_search_result_cards()), 30)
		cards = report.check("get_search_result_cards", elements.get_search_result_cards)
		report.check("get_next_page_link", elements.get_next_page_link, optional=True)

		if cards:
			sample = cards[0]
			parsed = elements.extract_card(sample, keyword="mystery")
			print(f"    sample title     {parsed.get('title')!r}" if parsed else "    sample unreadable")
			print(f"    sample author    {parsed.get('author')!r}" if parsed else "")
			print(f"    sample asin      {parsed.get('asin')!r}" if parsed else "")
			print(f"    sample url       {parsed.get('url')!r}" if parsed else "")
			print(f"    sample price     {parsed.get('price')!r}" if parsed else "")
			print(f"    sample sponsored {parsed.get('sponsored')!r}" if parsed else "")

		failures = report.summary()

		if failures:
			print("\nFAILED entries are selectors that should have resolved on this page.")
		else:
			print("\nEvery required selector resolved.")

		return 1 if failures else 0
	finally:
		driver.quit()


if __name__ == "__main__":
	sys.exit(main())
