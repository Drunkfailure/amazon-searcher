from __future__ import annotations

import csv
import os
import random
import sys
import time
from typing import Callable

from selenium import webdriver
from selenium.common.exceptions import (
	NoSuchElementException,
	StaleElementReferenceException,
	TimeoutException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import Select, WebDriverWait

import element_selectors
import mouse_trajectory
import mimic_typing
import tab_utils

CSV_FIELDS = ("keyword", "title", "author", "asin", "url", "price", "sponsored")


def write_csv(records: list[dict], path: str):
	directory = os.path.dirname(os.path.abspath(path))

	if directory:
		os.makedirs(directory, exist_ok=True)

	with open(path, "w", newline="", encoding="utf-8-sig") as handle:
		writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
		writer.writeheader()
		writer.writerows(records)


class KindleSearchUtils:
	def __init__(self, driver: webdriver.Edge):
		self.driver = driver

		self.tab_utils = tab_utils.TabUtils(driver)
		self.mouse = mouse_trajectory.MouseUtils(driver)
		self.keyboard = mimic_typing.KeyboardUtils(driver)
		self.elements = element_selectors.ElementSelectionUtils(driver)

	def find_element(self, xpath: str):
		return self.elements.resolve(xpath)

	def wait_for_element(
		self,
		element_getter: Callable[[], WebElement | list[WebElement] | bool],
		timeout: int = 15,
	) -> WebElement | list[WebElement]:
		def condition(_: webdriver.Edge):
			try:
				element_or_elements = element_getter()

				return element_or_elements
			except Exception:
				return False

		return WebDriverWait(self.driver, timeout).until(condition)

	def move_to_and_click(self, elem: WebElement):
		self.mouse.move_to_element(elem)
		self.mouse.human_like_click()

	def wait_for_then_click(self, element_getter: Callable[[], WebElement], timeout: int = 15):
		elem = self.wait_for_element(element_getter, timeout)
		self.move_to_and_click(elem)

	def pause_if_blocked(self):
		"""Stop and wait if Amazon is showing a captcha or continue-shopping wall."""
		while True:
			if self.elements.is_captcha_page():
				input(
					"Amazon is showing a captcha. Solve it in the browser, then press Enter..."
				)
				time.sleep(1)
				continue

			try:
				self.elements.get_continue_shopping_button()
			except NoSuchElementException:
				return

			input(
				"Amazon is showing a continue-shopping page. Click through in the browser, then press Enter..."
			)
			time.sleep(1)

	def open_amazon(self):
		self.driver.get(element_selectors.AMAZON_HOME)
		self.tab_utils.ensure_focus()
		self.pause_if_blocked()
		self.wait_for_element(self.elements.get_search_box, timeout=30)
		self.mouse.reinitialize()

	def select_kindle_store(self):
		dropdown = self.wait_for_element(self.elements.get_department_dropdown, timeout=20)

		try:
			if dropdown.is_displayed():
				self.move_to_and_click(dropdown)
				time.sleep(random.uniform(0.2, 0.5))
		except Exception:
			pass

		Select(dropdown).select_by_value(element_selectors.KINDLE_DEPARTMENT_VALUE)
		time.sleep(random.uniform(0.4, 0.9))

	def _modifier_key(self):
		return Keys.COMMAND if sys.platform == "darwin" else Keys.CONTROL

	def clear_and_type(self, box: WebElement, text: str):
		self.move_to_and_click(box)
		time.sleep(random.uniform(0.1, 0.25))

		actions = ActionChains(self.driver, duration=0)
		modifier = self._modifier_key()
		actions.key_down(modifier).send_keys("a").key_up(modifier).perform()
		time.sleep(random.uniform(0.05, 0.15))
		actions = ActionChains(self.driver, duration=0)
		actions.send_keys(Keys.BACKSPACE).perform()
		time.sleep(random.uniform(0.08, 0.2))

		self.keyboard.send_keys(text)

	def search_keyword(self, keyword: str):
		box = self.wait_for_element(self.elements.get_search_box, timeout=20)
		self.clear_and_type(box, keyword)
		self.keyboard.send_keys(Keys.ENTER)
		time.sleep(random.uniform(1.5, 3.0))
		self.pause_if_blocked()

	def harvest_current_page(self, keyword: str, seen_asins: set[str]) -> list[dict]:
		try:
			cards = self.wait_for_element(self.elements.get_search_result_cards, timeout=20)
		except TimeoutException:
			print(f"[WARNING] No results on this page for {keyword!r}")
			return []

		if cards:
			try:
				self.mouse.wheel_scroll_element_into_view(cards[min(2, len(cards) - 1)])
			except Exception:
				pass

		records = []

		for card in self.elements.get_search_result_cards():
			try:
				record = self.elements.extract_card(card, keyword)
			except StaleElementReferenceException:
				continue

			if not record or record["asin"] in seen_asins:
				continue

			seen_asins.add(record["asin"])
			records.append(record)

		return records

	def go_to_next_page(self) -> bool:
		try:
			next_link = self.elements.get_next_page_link()
		except NoSuchElementException:
			return False

		self.move_to_and_click(next_link)
		time.sleep(random.uniform(1.2, 2.4))
		self.pause_if_blocked()
		return True

	def harvest_keyword(self, keyword: str, pages: int) -> list[dict]:
		print(f"[INFO] Searching Kindle Store for {keyword!r}")
		self.search_keyword(keyword)

		seen: set[str] = set()
		records: list[dict] = []

		for page_number in range(1, pages + 1):
			page_records = self.harvest_current_page(keyword, seen)
			records.extend(page_records)
			print(
				f"[INFO] {keyword!r} page {page_number}: "
				f"{len(page_records)} new books ({len(records)} unique so far)"
			)

			if page_number >= pages:
				break

			if not self.go_to_next_page():
				print(f"[INFO] No further pages for {keyword!r}")
				break

		return records

	def harvest(self, keywords: list[str], pages: int, output_path: str) -> list[dict]:
		self.open_amazon()

		try:
			self.select_kindle_store()
		except Exception as exc:
			print(
				f"[WARNING] Could not select Kindle Store in the department dropdown "
				f"({type(exc).__name__}: {exc}). Searches will use the current department."
			)

		all_records: list[dict] = []

		for keyword in keywords:
			try:
				all_records.extend(self.harvest_keyword(keyword, pages))
			except Exception as exc:
				print(f"[FAIL] {keyword!r}: {type(exc).__name__}: {exc}")

			write_csv(all_records, output_path)

		return all_records
