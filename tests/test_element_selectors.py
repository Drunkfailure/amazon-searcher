"""Tests for the Amazon Kindle card parsers and filters.

Every case here is a failure mode that would silently drop books or invent
links: an empty data-asin placeholder, a disabled Next button, a href that
is not yet a canonical /dp/ URL. They need no browser, so they run anywhere.

	python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

import element_selectors
from fakes import FakeDriver, FakeElement


def selectors_for(driver):
	return element_selectors.ElementSelectionUtils(driver)


def result_card(
	asin="B0ABC12345",
	title="The Example Book",
	href=None,
	author="Jane Doe",
	price="$4.99",
	sponsored=False,
	displayed=True,
	css_class="",
):
	if href is None:
		href = f"/The-Example-Book-ebook/dp/{asin}/ref=sr_1_1"

	title_link = FakeElement(text=title, attributes={"href": href})
	byline = FakeElement(text=f"by {author}") if author else None
	price_node = FakeElement(text=price) if price else None
	spans = [FakeElement(text="Sponsored")] if sponsored else []

	children = {
		(By.CSS_SELECTOR, "h2 a"): [title_link],
		(By.CSS_SELECTOR, '[data-cy="title-recipe"] h2'): [FakeElement(text=title)],
	}

	if byline is not None:
		children[(By.CSS_SELECTOR, '[data-cy="byline-recipe"]')] = [byline]
		children[(By.CSS_SELECTOR, ".a-row")] = [byline]

	if price_node is not None:
		children[(By.CSS_SELECTOR, ".a-price .a-offscreen")] = [price_node]

	if spans:
		children[(By.TAG_NAME, "span")] = spans

	classes = css_class
	if sponsored and "AdHolder" not in classes:
		classes = (classes + " AdHolder").strip()

	return FakeElement(
		text=f"{'Sponsored ' if sponsored else ''}{title}\nby {author}\n{price}",
		attributes={"data-asin": asin, "data-component-type": "s-search-result", "class": classes},
		children=children,
		displayed=displayed,
	)


class AsinAndUrl(unittest.TestCase):
	def test_reads_asin_from_dp_href(self):
		self.assertEqual(
			element_selectors.asin_from_href("/The-Example-Book-ebook/dp/B0ABC12345/ref=sr_1_1"),
			"B0ABC12345",
		)

	def test_reads_asin_from_gp_product_href(self):
		self.assertEqual(
			element_selectors.asin_from_href("https://www.amazon.com/gp/product/B00TESTAS1"),
			"B00TESTAS1",
		)

	def test_returns_none_when_href_has_no_asin(self):
		self.assertIsNone(element_selectors.asin_from_href("/s?k=mystery"))

	def test_normalize_accepts_a_bare_asin(self):
		self.assertEqual(element_selectors.normalize_asin("b0abc12345"), "B0ABC12345")

	def test_product_url_is_canonical(self):
		self.assertEqual(
			element_selectors.product_url("b0abc12345"),
			"https://www.amazon.com/dp/B0ABC12345",
		)


class ResultCardFilter(unittest.TestCase):
	def _driver(self, cards):
		return FakeDriver(children={
			(By.CSS_SELECTOR, 'div[data-component-type="s-search-result"]'): cards
		})

	def test_skips_empty_asin_placeholders(self):
		cards = selectors_for(self._driver([
			result_card(asin=""),
			result_card(asin="B0ABC12345"),
		])).get_search_result_cards()

		self.assertEqual(len(cards), 1)
		self.assertEqual(cards[0].get_dom_attribute("data-asin"), "B0ABC12345")

	def test_skips_hidden_cards(self):
		cards = selectors_for(self._driver([
			result_card(asin="B0HIDDEN01", displayed=False),
			result_card(asin="B0VISIBLE1"),
		])).get_search_result_cards()

		self.assertEqual(len(cards), 1)
		self.assertEqual(cards[0].get_dom_attribute("data-asin"), "B0VISIBLE1")


class CardExtraction(unittest.TestCase):
	def test_extracts_title_author_price_and_canonical_url(self):
		record = selectors_for(FakeDriver()).extract_card(
			result_card(),
			keyword="cozy mystery",
		)

		self.assertEqual(record["keyword"], "cozy mystery")
		self.assertEqual(record["title"], "The Example Book")
		self.assertEqual(record["author"], "Jane Doe")
		self.assertEqual(record["asin"], "B0ABC12345")
		self.assertEqual(record["url"], "https://www.amazon.com/dp/B0ABC12345")
		self.assertEqual(record["price"], "$4.99")
		self.assertFalse(record["sponsored"])

	def test_author_falls_back_to_by_row_when_byline_recipe_is_missing(self):
		card = result_card()
		del card.children[(By.CSS_SELECTOR, '[data-cy="byline-recipe"]')]

		record = selectors_for(FakeDriver()).extract_card(card)

		self.assertEqual(record["author"], "Jane Doe")

	def test_price_is_empty_when_the_card_has_no_price(self):
		record = selectors_for(FakeDriver()).extract_card(result_card(price=""))

		self.assertEqual(record["price"], "")

	def test_returns_none_when_the_card_has_no_asin(self):
		card = result_card(asin="", href="/s?k=mystery")

		self.assertIsNone(selectors_for(FakeDriver()).extract_card(card))

	def test_recovers_asin_from_the_title_href_when_data_asin_is_blank(self):
		card = result_card(asin="", href="/Foo-ebook/dp/B0FROMHREF/ref=sr_1_2")

		record = selectors_for(FakeDriver()).extract_card(card)

		self.assertEqual(record["asin"], "B0FROMHREF")
		self.assertEqual(record["url"], "https://www.amazon.com/dp/B0FROMHREF")


class SponsoredFlag(unittest.TestCase):
	def test_sponsored_span(self):
		self.assertTrue(
			selectors_for(FakeDriver()).card_is_sponsored(result_card(sponsored=True))
		)

	def test_organic_card_is_not_sponsored(self):
		self.assertFalse(
			selectors_for(FakeDriver()).card_is_sponsored(result_card(sponsored=False))
		)

	def test_adholder_class_without_label_is_still_sponsored(self):
		card = result_card(sponsored=False, css_class="AdHolder")

		self.assertTrue(selectors_for(FakeDriver()).card_is_sponsored(card))


class NextPage(unittest.TestCase):
	def _driver(self, links):
		return FakeDriver(children={(By.CSS_SELECTOR, "a.s-pagination-next"): links})

	def test_returns_the_enabled_next_link(self):
		link = FakeElement(
			text="Next",
			attributes={"class": "s-pagination-item s-pagination-next s-pagination-button"},
		)

		self.assertIs(selectors_for(self._driver([link])).get_next_page_link(), link)

	def test_skips_a_disabled_next_link(self):
		link = FakeElement(
			text="Next",
			attributes={
				"class": "s-pagination-item s-pagination-next s-pagination-disabled",
				"aria-disabled": "true",
			},
		)

		with self.assertRaises(NoSuchElementException):
			selectors_for(self._driver([link])).get_next_page_link()

	def test_skips_a_hidden_next_link(self):
		link = FakeElement(
			text="Next",
			attributes={"class": "s-pagination-item s-pagination-next"},
			displayed=False,
		)

		with self.assertRaises(NoSuchElementException):
			selectors_for(self._driver([link])).get_next_page_link()


class Interstitials(unittest.TestCase):
	def test_captcha_from_url(self):
		driver = FakeDriver(current_url="https://www.amazon.com/errors/validateCaptcha")

		self.assertTrue(selectors_for(driver).is_captcha_page())

	def test_captcha_from_form(self):
		driver = FakeDriver(
			children={(By.ID, "captchacharacters"): [FakeElement()]},
		)

		self.assertTrue(selectors_for(driver).is_captcha_page())

	def test_home_is_not_a_captcha(self):
		self.assertFalse(selectors_for(FakeDriver()).is_captcha_page())

	def test_continue_shopping_button(self):
		button = FakeElement(text="Continue shopping")
		driver = FakeDriver(children={(By.TAG_NAME, "button"): [button]})

		self.assertIs(selectors_for(driver).get_continue_shopping_button(), button)

	def test_raises_when_there_is_no_continue_shopping_button(self):
		with self.assertRaises(NoSuchElementException):
			selectors_for(FakeDriver()).get_continue_shopping_button()


if __name__ == "__main__":
	unittest.main()
