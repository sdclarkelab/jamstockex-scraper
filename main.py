import constants
import custom_logger
from services import scraper_factory

logger = custom_logger.setup_custom_logger("root")

if __name__ == "__main__":
    try:
        scraper_factory.scrape(resource_name=constants.LISTED_COMPANIES_RESOURCE, retry_num=2)

        scraper_factory.scrape(resource_name=constants.SUMMARY_RESOURCE, retry_num=2)

        scraper_factory.scrape(resource_name=constants.CORPORATE_ACTION_RESOURCE, retry_num=2)

    except Exception as e:
        logger.error(e)
