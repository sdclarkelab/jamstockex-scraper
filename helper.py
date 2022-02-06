import logging
import random
import time
from datetime import datetime, timezone, timedelta

import pytz
import requests
from bs4 import BeautifulSoup as bS

logger = logging.getLogger('root')


def get_current_time():
    try:
        jamaica = pytz.timezone('Jamaica')
        t = datetime.now(tz=jamaica)
        current_time = datetime(t.year, t.month, t.day, t.hour, t.minute, t.second, t.microsecond, tzinfo=timezone.utc)

        return current_time
    except Exception as e:
        logger.error(e)
        raise


def format_date(current_time):
    try:
        return current_time.strftime('%Y-%m-%d')
    except Exception as e:
        logger.error(e)
        raise


def get_first_date():
    try:
        year = datetime.today().year
        first_date = datetime.strptime(f'{year}-01-01', '%Y-%m-%d')

        return format_date(first_date)
    except Exception as e:
        logger.error(e)


def get_current_formatted_date():
    """Get current date or previous business day"""
    try:
        current_time = get_current_time()
        diff = 0

        if current_time.weekday() == 5:
            diff = 1
        if current_time.weekday() == 6:
            diff = 2

        return format_date(current_time - timedelta(days=diff))

    except Exception as e:
        logger.error(e)
        raise


def get_response(url):
    try:
        ua_file = 'ua_file.txt'
        lines = open(ua_file).read().splitlines()
        random_ua = random.choice(lines)

        headers = {
            'User-Agent': random_ua,
        }
        page_response = requests.get(url, headers=headers)
        return page_response

    except Exception as e:
        logger.error(e)


def get_parse_tree(url, retry_num):
    logger.info(f"Getting parse tree for {url}")
    parse_tree = None

    try:
        for i in range(0, retry_num):
            response = get_response(url)

            if response is not None and response.status_code == 200:
                #  Returns the page content to string using UTF-8
                content = response.text
                parse_tree = bS(content, "html.parser")
                break
            else:
                logger.warning(f'Could not load page.')

                delay = random.randrange(5, 15)
                time.sleep(delay)

        return parse_tree

    except Exception:
        raise


def find_tables(parse_tree, is_find_all=False):
    try:
        if parse_tree is None:
            raise Exception('No data provided.')

        if is_find_all:
            table = parse_tree.findAll('table')
        else:
            table = parse_tree.find('table')

        if table is None:
            raise Exception('Table is missing.')

        return table
    except Exception as e:
        raise e


class Cells:
    def __init__(self, cells):
        self.cells = cells

    def extract_text(self, cell_number):
        if self.cells[cell_number].find("a"):
            return self.cells[cell_number].find("a").text.strip().lower()

        return self.cells[cell_number].text.strip().lower()

    def extract_href(self, cell_number):
        if self.cells[cell_number].find("a", href=True):
            return self.cells[cell_number].find("a", href=True).get("href", '').lower()
        return ''
