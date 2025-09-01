ACTIVE_SUBSCRIPTIONS = {
    'buy_subscription_lite' : {
        'name': 'Lite',
        'price' : 990 ,
        'description' : 'Lite',
        'payload' : 'lite'
    },
    'buy_subscription_pro' : {
        'name': 'Pro',
        'price': 1990,
        'description': 'Pro',
        'payload': 'pro'
    },
}

class Sub:
    price = None
    description = None
    payload = None

    def __init__(self, price, description, payload):
        self.price = price
        self.description = description
        self.payload = payload


def get_subscription_info(buy_subscription_lite):
    sub_info = ACTIVE_SUBSCRIPTIONS[buy_subscription_lite]
    sub = Sub(price=sub_info['price'], description=sub_info['description'], payload=sub_info['payload'])

    return sub
