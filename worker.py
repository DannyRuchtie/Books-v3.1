import os
import sys
from rq import Connection, Worker, Queue
from redis import Redis

# Set the environment variable to avoid fork() issues on macOS
os.environ['OBJC_DISABLE_INITIALIZE_FORK_SAFETY'] = 'YES'

# Set up Redis connection
redis_conn = Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379'))

if __name__ == '__main__':
    with Connection(redis_conn):
        worker = Worker(Queue('default'))
        worker.work()