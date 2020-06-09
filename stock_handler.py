# Created by Stephen Clarke at 07-Jul-19

import logging
import os
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ExecutionTimeout, CollectionInvalid

from stock.dividend import dividend as dividend_crawler
from stock.index_composition import index_composition as index_composition_crawler
from stock.stock_info import stock_info as stock_info_crawler
from utils import log, constants

sched = BlockingScheduler()

# ------------------------- MONGODB CLIENT DECLARATION -------------------------
try:
    #  Apply logger configurations
    log.setup_logger()

    #  Get environment variables
    load_dotenv()
    mongoDB_connection_str = os.getenv("DB_CONN_STR")
    mongoDB_name = os.getenv("DB_NAME")
    stock_col = os.getenv("STOCK_COL")

    #  Create mongoDB connection
    client = MongoClient(mongoDB_connection_str)
    jamstock_db = client[mongoDB_name]

except (ConnectionFailure, ExecutionTimeout) as e:
    logging.error(log.get_error_msg(e))
    sys.exit(1)
except Exception as e:
    logging.error(log.get_error_msg(e))
    sys.exit(1)


# ----------------------------- STOCK INFO ---------------------------------
def stock_info():
    try:
        stock_info_crawler.main(jamstock_db[stock_col])

    except CollectionInvalid as mongoDB_error:
        logging.error(log.get_error_msg(mongoDB_error))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


# ----------------------------- INDEX COMPOSITION ---------------------------------
def index_composition():
    try:
        index_composition_crawler.main(jamstock_db[stock_col])

    except CollectionInvalid as mongoDB_error:
        logging.error(log.get_error_msg(mongoDB_error))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


# ----------------------------- DIVIDEND ---------------------------------
def dividend():
    try:
        dividend_crawler.main(jamstock_db[stock_col])

    except CollectionInvalid as mongoDB_error:
        logging.error(log.get_error_msg(mongoDB_error))
        sys.exit(1)
    except Exception as e:
        logging.error(log.get_error_msg(e))
        sys.exit(1)


# --------------------------------- Start scheduler ---------------------------------
if __name__ == "__main__":
    sched.add_job(stock_info, 'cron', day_of_week='mon-fri', hour=7, minute=00, timezone=constants.JA_TIMEZONE,
                  id='stock_info')
    sched.add_job(index_composition, 'cron', day_of_week='mon-fri', hour=8, minute=00, timezone=constants.JA_TIMEZONE,
                  id='morning_index_composition')
    sched.add_job(index_composition, 'cron', day_of_week='mon-fri', hour=15, minute=00, timezone=constants.JA_TIMEZONE,
                  id='afternoon_index_composition')
    sched.add_job(dividend, 'cron', day_of_week='mon-fri', hour=7, minute=30, timezone=constants.JA_TIMEZONE,
                  id='dividend')
    sched.print_jobs()
    sched.start()
