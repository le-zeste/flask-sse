from sse import Sse as PySse
from redis import StrictRedis
from redis import ConnectionPool as RedisConnectionPool
from flask import json, current_app, Blueprint, request


class ConnectionPool(object):
    pool = {}

    @classmethod
    def key(cls, *args, **kwargs):
        return ':'.join(args) + \
            ':'.join('%s=%s' % (k, v) for k, v in kwargs.items())

    @classmethod
    def lookup_pool(cls, *args, **kwargs):
        key = cls.key(*args, **kwargs)
        if key not in cls.pool:
            cls.pool[key] = RedisConnectionPool(*args, **kwargs)
        return cls.pool[key]

    @classmethod
    def get_connection(cls):
        pool = cls.lookup_pool(
            host=current_app.config.get('SSE_REDIS_HOST', 'localhost'),
            port=current_app.config.get('SSE_REDIS_PORT', 6379),
            db=current_app.config.get('SSE_REDIS_DB', 0),
            password=current_app.config.get('SSE_REDIS_PASSWORD', None),
            max_connections=current_app.config.get('SSE_REDIS_MAX_CONNECTIONS', None)
        )
        return StrictRedis(connection_pool=pool)


class SseStream(object):

    def __init__(self, conn, channel):
        self.conn = conn
        self.pubsub = conn.pubsub()
        self.pubsub.subscribe(channel)
        conn.publish(channel, '_flush')
        conn.publish(channel, '_flush')

    def close(self):
        self.pubsub.close()
        try:
            self.conn.connection_pool.release(self.conn)
        except AttributeError:
            pass

    def __iter__(self):
        sse = PySse()
        for data in sse:
            yield data.encode('u8')
        for message in self.pubsub.listen():
            if message['type'] == 'message':
                if message['data'] != '_flush':
                    event, data = json.loads(message['data'])
                    sse.add_message(event, data)
                    for data in sse:
                        yield data.encode('u8')
                else:
                    yield ":\n".encode('u8')

sse = Blueprint('sse', __name__)


@sse.route('')
def stream():
    conn = ConnectionPool.get_connection()
    channel = request.args.get('channel', 'sse')
    return current_app.response_class(
        SseStream(conn, channel),
        direct_passthrough=True,
        mimetype='text/event-stream',
    )


def send_event(event_name, data, channel='sse'):
    conn = ConnectionPool.get_connection()
    conn.publish(channel, json.dumps([event_name, data]))
