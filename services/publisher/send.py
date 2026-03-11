import pika

connection = pika.BlockingConnection(
    pika.ConnectionParameters(
        host='192.168.1.154',
        port=5672,
        credentials=pika.PlainCredentials('ravyn','103595')
    )
)

channel = connection.channel()
channel.queue_declare(queue='ravyn.request')

message = "Hello from Exiled PC"

channel.basic_publish(
    exchange='',
    routing_key='ravyn.request',
    body=message
)

print("Sent:", message)
connection.close()