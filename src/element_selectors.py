from __future__ import annotations

import re

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium import webdriver


KINDLE_DEPARTMENT_VALUE = "search-alias=digital-text"
AMAZON_HOME = "https://www.amazon.com/"
PRODUCT_URL_TEMPLATE = "https://www.amazon.com/dp/{asin}"

ASIN_RE = re.compile(r"(?:/dp/|/gp/product/)([A-Z0-9]{10})", re.IGNORECASE)
ASIN_ONLY_RE = re.compile(r"^[A-Z0-9]{10}$", re.IGNORECASE)


def asin_from_href(href: str) -> str | None:
	"""Pull a 10-character ASIN out of an Amazon product href."""
	if not href:
		return None

	match = ASIN_RE.search(href)

	if match:
		return match.group(1).upper()

	return None


def product_url(asin: str) -> str:
	return PRODUCT_URL_TEMPLATE.format(asin=asin.upper())


def normalize_asin(value: str) -> str | None:
	"""Accept a raw ASIN or a product href and return a canonical ASIN."""
	if not value:
		return None

	stripped = value.strip()

	if ASIN_ONLY_RE.fullmatch(stripped):
		return stripped.upper()

	return asin_from_href(stripped)


class ElementSelectionUtils:
	"""Selectors for Amazon Kindle search.

	Amazon's search markup shifts between deploys, so these lookups are
	semantic: stable ids for the nav, data-asin / data-component-type for
	result cards, and visible labels for captcha and continue-shopping.
	Anything the current page does not ship raises NoSuchElementException so
	the caller can wait, skip, or pause instead of aborting the whole run.
	"""

	def __init__(self, driver: webdriver.Edge):
		self.driver = driver

	def resolve(self, xpath: str):
		return self.driver.find_element(By.XPATH, xpath)

	# ------------------------------------------------------------------
	# nav
	# ------------------------------------------------------------------

	def get_search_box(self):
		return self.driver.find_element(By.ID, "twotabsearchtextbox")

	def get_search_submit(self):
		return self.driver.find_element(By.ID, "nav-search-submit-button")

	def get_department_dropdown(self):
		return self.driver.find_element(By.ID, "searchDropdownBox")

	# ------------------------------------------------------------------
	# result cards
	# ------------------------------------------------------------------

	def get_search_result_cards(self):
		"""Visible result cards that actually identify a product.

		Amazon emits empty `data-asin` placeholders and a hidden responsive
		copy of the list. Those are not harvestable: they have no product
		and cannot be clicked, so they are dropped here.
		"""
		matches = self.driver.find_elements(
			By.CSS_SELECTOR, 'div[data-component-type="s-search-result"]'
		)

		cards = []

		for match in matches:
			try:
				asin = (match.get_dom_attribute("data-asin") or "").strip()

				if asin and match.is_displayed():
					cards.append(match)
			except StaleElementReferenceException:
				continue

		return cards

	def extract_card(self, card: WebElement, keyword: str = "") -> dict | None:
		asin = normalize_asin(card.get_dom_attribute("data-asin") or "")

		if not asin:
			href = self._title_href(card)
			asin = normalize_asin(href or "")

		if not asin:
			return None

		return {
			"keyword": keyword,
			"title": self.extract_title(card),
			"author": self.extract_author(card),
			"asin": asin,
			"url": product_url(asin),
			"price": self.extract_price(card),
			"sponsored": self.card_is_sponsored(card),
		}

	def extract_title(self, card: WebElement) -> str:
		for selector in ("h2 a", '[data-cy="title-recipe"] h2'):
			try:
				for node in card.find_elements(By.CSS_SELECTOR, selector):
					text = (node.text or "").strip()

					if text:
						return text.split("\n")[0].strip()
			except StaleElementReferenceException:
				continue

		return ""

	def extract_author(self, card: WebElement) -> str:
		try:
			byline = card.find_element(By.CSS_SELECTOR, '[data-cy="byline-recipe"]')
			text = (byline.text or "").strip()

			if text:
				return self._author_from_byline(text)
		except (NoSuchElementException, StaleElementReferenceException):
			pass

		try:
			for row in card.find_elements(By.CSS_SELECTOR, ".a-row"):
				text = (row.text or "").strip()

				if text.lower().startswith("by "):
					return self._author_from_byline(text)
		except StaleElementReferenceException:
			pass

		return ""

	def extract_price(self, card: WebElement) -> str:
		try:
			for price in card.find_elements(By.CSS_SELECTOR, ".a-price .a-offscreen"):
				try:
					text = (price.text or "").strip()

					if text and price.is_displayed():
						return text
				except StaleElementReferenceException:
					continue
		except StaleElementReferenceException:
			pass

		return ""

	def card_is_sponsored(self, card: WebElement) -> bool:
		cls = card.get_dom_attribute("class") or ""

		if "AdHolder" in cls:
			return True

		try:
			for span in card.find_elements(By.TAG_NAME, "span"):
				try:
					if (span.text or "").strip().lower() == "sponsored":
						return True
				except StaleElementReferenceException:
					continue
		except StaleElementReferenceException:
			pass

		return False

	def _title_href(self, card: WebElement) -> str:
		try:
			link = card.find_element(By.CSS_SELECTOR, "h2 a")
		except (NoSuchElementException, StaleElementReferenceException):
			return ""

		return (
			link.get_dom_attribute("href")
			or (link.get_attribute("href") if hasattr(link, "get_attribute") else None)
			or ""
		)

	@staticmethod
	def _author_from_byline(text: str) -> str:
		stripped = text.strip()

		if stripped.lower().startswith("by "):
			stripped = stripped[3:]

		return stripped.split("\n")[0].strip()

	# ------------------------------------------------------------------
	# pagination
	# ------------------------------------------------------------------

	def get_next_page_link(self):
		candidates = self.driver.find_elements(By.CSS_SELECTOR, "a.s-pagination-next")

		for link in candidates:
			try:
				cls = link.get_dom_attribute("class") or ""
				aria = (link.get_dom_attribute("aria-disabled") or "").lower()

				if "s-pagination-disabled" in cls or aria == "true":
					continue

				if link.is_displayed():
					return link
			except StaleElementReferenceException:
				continue

		raise NoSuchElementException("no enabled next page link")

	# ------------------------------------------------------------------
	# interstitials
	# ------------------------------------------------------------------

	def is_captcha_page(self) -> bool:
		url = (getattr(self.driver, "current_url", "") or "").lower()

		if "validatecaptcha" in url or "/sorry/" in url:
			return True

		if self.driver.find_elements(By.ID, "captchacharacters"):
			return True

		if self.driver.find_elements(By.CSS_SELECTOR, "form[action*='validateCaptcha']"):
			return True

		return False

	def get_continue_shopping_button(self):
		for tag in ("button", "a", "input"):
			for element in self.driver.find_elements(By.TAG_NAME, tag):
				try:
					label = (element.text or "").strip().lower()
					value = (element.get_dom_attribute("value") or "").strip().lower()

					if "continue shopping" in label or "continue shopping" in value:
						if element.is_displayed():
							return element
				except StaleElementReferenceException:
					continue

		raise NoSuchElementException("no continue shopping button")

	# ------------------------------------------------------------------
	# viewport
	# ------------------------------------------------------------------

	def element_is_fully_in_viewport(self, elem: WebElement) -> bool:
		js_viewport_check = """
var elem = arguments[0];
var box = elem.getBoundingClientRect();

return (
	box.top >= 0 &&
	box.left >= 0 &&
	box.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
	box.right <= (window.innerWidth || document.documentElement.clientWidth)
);
"""

		return self.driver.execute_script(js_viewport_check, elem)
