import logging

import constants
import helper
from database import Database
from services.jse_scrapers import listed_companies_scraper, summary_scraper, corporate_action_scraper
from urls import URLS

logger = logging.getLogger('root')
urls = URLS()


def scrape(resource_name, retry_num):
    logger.info(f"{resource_name} scraper running ...")
    current_date = helper.get_current_formatted_date()

    try:
        data = None

        if resource_name == constants.LISTED_COMPANIES_RESOURCE:
            data = listed_companies_scraper.get_listed_companies(constants.MARKETS, retry_num)

        elif resource_name == constants.SUMMARY_RESOURCE:
            data = summary_scraper.get_trade_summaries(current_date, retry_num)

        elif resource_name == constants.CORPORATE_ACTION_RESOURCE:
            data = corporate_action_scraper.get_corporate_actions(constants.ALL_STOCKS, helper.get_first_date(),
                                                                  current_date, retry_num)
        db = Database()
        db.update_stock_collection(resource_name, data)

    except Exception:
        raise
