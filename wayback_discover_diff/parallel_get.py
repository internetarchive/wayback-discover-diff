from threading import Thread, enumerate
import urllib3
from time import sleep
from functools import reduce
import redis
from simhash import Simhash

UPDATE_INTERVAL = 0.01


class URLThread(Thread):
    def __init__(self, timestamp, site, simhash_size):
        super(URLThread, self).__init__()
        self.timestamp = timestamp
        self.site = site
        self.simhash_size = simhash_size
        self.response = None

    def run(self):
        http = urllib3.PoolManager
        self.url = 'https://web.archive.org/web/' + self.timestamp + '/' + self.site
        self.response = http.request(self.url)
        redis_db = redis.StrictRedis(host="localhost", port=6379, db=0)
        temp_simhash = Simhash(self.response.data.decode('utf-8'), simhash_size).value
        redis_db.set(self.url + self.timestamp, temp_simhash)


def multi_get(snapshots, site, simhash_size, timeout=2.0):
    def alive_count(lst):
        alive = map(lambda x : 1 if x.isAlive() else 0, lst)
        return reduce(lambda a,b : a + b, alive)
    threads = [ URLThread(snapshot, site, simhash_size) for snapshot in snapshots ]
    for thread in threads:
        thread.start()
    while alive_count(threads) > 0 and timeout > 0.0:
        timeout = timeout - UPDATE_INTERVAL
        sleep(UPDATE_INTERVAL)
    return [ (x.url, x.response) for x in threads ]