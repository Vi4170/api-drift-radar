"""MongoDB client and index management.

Collections (all documents carry `endpoint_id` as a string UUID matching PostgreSQL):
  snapshots  _id = check_id            raw JSON body of one check (TTL-expired)
  schemas    _id = "<endpoint>:<hash>" inferred schema, deduplicated per endpoint
  diffs      _id = "<endpoint>:<baseline_hash>:<observed_hash>" deterministic diff document
"""

from functools import lru_cache

from pymongo import MongoClient
from pymongo.database import Database

from app.core.config import get_settings


@lru_cache
def get_mongo_client() -> MongoClient:
    return MongoClient(
        get_settings().mongo_url,
        serverSelectionTimeoutMS=3000,
        connectTimeoutMS=3000,
        socketTimeoutMS=10000,
        tz_aware=True,
        maxPoolSize=20,
    )


def get_mongo_db() -> Database:
    return get_mongo_client()[get_settings().mongo_db]
