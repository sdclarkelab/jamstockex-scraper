from apscheduler.schedulers.blocking import BlockingScheduler

import constants
import custom_logger
from services import scraper_factory

logger = custom_logger.setup_custom_logger("root")
sched = BlockingScheduler()


@sched.scheduled_job('cron', day_of_week='mon', hour=7, minute=00, timezone=constants.JA_TIMEZONE,
                     id=constants.LISTED_COMPANIES_RESOURCE)
def listed_companies():
    scraper_factory.scrape(resource_name=constants.LISTED_COMPANIES_RESOURCE, retry_num=2)


@sched.scheduled_job('cron', day_of_week='mon-fri', hour=17, minute=00, timezone=constants.JA_TIMEZONE,
                     id=constants.SUMMARY_RESOURCE)
def trade_summary():
    scraper_factory.scrape(resource_name=constants.SUMMARY_RESOURCE, retry_num=2)


@sched.scheduled_job('cron', day_of_week='mon', hour=20, minute=00, timezone=constants.JA_TIMEZONE,
                     id=constants.CORPORATE_ACTION_RESOURCE)
def corporate_action():
    scraper_factory.scrape(resource_name=constants.CORPORATE_ACTION_RESOURCE, retry_num=2)


sched.print_jobs()

sched.start()
