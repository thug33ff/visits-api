import os
from dotenv import load_dotenv

load_dotenv()
MAX_USAGE=70
DB_NAME = "spam_xpert"
MONGO_URI = os.getenv("MONGO_URI") 
BASE_URLS = {
    "IND": "https://client.ind.freefiremobile.com",
    "BR":  "https://client.us.freefiremobile.com",
    "ME":  "https://clientbp.ggpolarbear.com",
    "BD":  "https://clientbp.ggpolarbear.com",
    "PK":  "https://clientbp.ggpolarbear.com",
    "EUROPE":"https://clientbp.ggpolarbear.com",

     "VN":"https://clientbp.ggpolarbear.com",
     "SG":"https://clientbp.ggpolarbear.com",
     "RU":"https://clientbp.ggpolarbear.com",
}

REGION_CONFIG = {
    region: {
        "tokens":    f"{region.lower()}_tokens",
        "url_spam":  f"{base}/RequestAddingFriend",
        "url_visit": f"{base}/GetPlayerPersonalShow",
    }
    for region, base in BASE_URLS.items()
}



LICENCE_API ="https://api.licensegate.io/license"
LICENCE_ID = "a1ff4"
SCOPE ="spamapi"