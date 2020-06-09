# Created by Stephen Clarke at 07-Jul-19

import logging
import sys
import time

import requests
from bs4 import BeautifulSoup as bS

from utils import log


def get_parse_tree(url: str, timeout_retry_num: int) -> bS:
    """

    :param str url: Url path to page
    :param int timeout_retry_num: Number of times to try scraping data before terminating
    :return:
    """
    logging.info(f"Getting Parse tree for {url}")

    try:
        parsed_content = None

        #  Query the page multiple times if page does not load.
        for i in range(0, timeout_retry_num):

            # Get response from site
            response = _get_response(url)
            status_code = response.status_code

            if status_code == 200:
                #  Returns the page content to string using UTF-8
                content = response.text
                parsed_content = _parse_response(content)
                break
            else:
                logging.error(f'Status Code: "{status_code}" || Could not load page.')
                time.sleep(2)

        return parsed_content
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _get_response(url: str) -> requests:
    """

    :param url:
    :return:
    """
    try:
        # Sends Get request to URL and returns a response
        page_response = requests.get(url)
        return page_response

    except requests.exceptions.ConnectionError as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def _parse_response(response: str) -> bS:
    """
    Returns parsed data.
    :param response:
    :return bs:
    """

    try:
        #  Use lxml parser for speed and flexibility to work with the different Python versions.
        parsed_data = bS(response, 'lxml')

        return parsed_data

    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


def extract_cell_value(cell: bS, is_link: bool = False, is_link_text=False) -> str:
    """

    :param cell:
    :param is_link:
    :return:
    """

    value = None

    try:
        if is_link:
            #   Extract link value from <a> tag
            link = cell.find("a")
            if link:
                if is_link_text:
                    value = link.text
                else:
                    value = link['href'].strip()

        else:
            #  Extract text
            content = cell.find(text=True)
            if content:
                value = content.strip()

        return value
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)
