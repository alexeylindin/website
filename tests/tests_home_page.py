from books import models
from tests.webdriver_test_case import WebdriverTestCase
from selenium.webdriver.common.by import By


class HomePageTests(WebdriverTestCase):
    '''Selenium tests for home-page related stuff.'''

    def get_first_book(self) -> models.Book:
        return models.Book.objects.filter(
            status=models.BookStatus.ACTIVE).order_by('-date').first()

    def test_click_book_title(self):
        self.driver.get(self.live_server_url)
        book = self.get_first_book()
        title = self.driver.find_element(By.LINK_TEXT, book.title)
        self.scroll_and_click(title)
        self.assertIn(f'/books/{book.slug}', self.driver.current_url)

    def test_click_book_cover(self):
        self.driver.get(self.live_server_url)
        book = self.get_first_book()
        cover_selector = f'img[alt="{book.title}"]'
        if book.cover_image == '':
            # when image is missing - find first auto-generated cover.
            # It should match the first book.
            cover_selector = '.cover.small'
        self.driver.find_element(By.CSS_SELECTOR, cover_selector).click()
        self.assertIn(f'/books/{book.slug}', self.driver.current_url)

    def test_click_book_author(self):
        self.driver.get(self.live_server_url)
        book = self.get_first_book()
        author = book.authors.first()
        author_elem = self.driver.find_element(By.LINK_TEXT, author.name)
        self.scroll_and_click(author_elem)
        self.assertIn(f'/person/{author.slug}', self.driver.current_url)

    def test_page_elements(self):
        self.driver.get(self.live_server_url)
        self.assertEqual('Беларускія аўдыякнігі', self.driver.title)